"""Exports from events only: the bibliography of a scope of works, the PRISMA flow as SVG, the
nanopublications of claims and stated edges, and the RO-Crate of the project.

Read-only and byte-deterministic: works are selected by id, sorted by id, read from the
projection in pages of `PAGE` and serialised as they stream; nothing here touches the library
(R-47) or writes an event. A merged work is exported as its canonical record (the merge of its
members), as `canonical_works` would give it.

Invariants:
- Every refusal is a FactoryValidationError raised before the first character is produced.
- Exactly one of `scope` and `ids` selects works; an unknown or absorbed id is refused.
- Files go only to the path the researcher names, never under `projects/`. They are built in a
  staging directory beside it and reach the path by renames of the whole, so a refusal or a failure
  leaves the path as it was. If restoring the old directory itself fails, the error names where it
  is kept; it is never deleted.
- Assembly takes no lock: appending to the log takes none, so a lock would not stop the log moving,
  and it would block every other session. An export over a log that moved is refused instead.
- These file exports are the researcher's (CLI only, spec ruling 22), so nothing here is withheld.

Services imported inside a function are those that may reach `drafts`, which imports this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pydantic import JsonValue
from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BLOB_REF_RE, BlobIntegrityError, BlobNotFoundError
from factory.events.reader import event_files, read_file, relative_name
from factory.exports.bibtex import bibtex
from factory.exports.crate import (
    DESCRIPTOR,
    MANIFEST,
    RO_CRATE,
    AgentEntry,
    ConversionEntry,
    CrateFile,
    ManifestEntry,
    crate_metadata,
    manifest_json,
)
from factory.exports.csl import csl_json
from factory.exports.keys import assign_keys
from factory.exports.nanopub import (
    Attribution,
    Nanopub,
    base_iri,
    claim_nanopub,
    edge_nanopub,
    prefixes,
)
from factory.exports.prisma_svg import prisma_svg
from factory.exports.rdf import IRI, Literal_, iri, trig
from factory.lineage.graph import GraphEdge, GraphFilter
from factory.model.base import StrictModel
from factory.model.lineage import EdgeType
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.model.search import QueryPurpose
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.coverage import held_out_visible
from factory.services.dedup import active_merges
from factory.services.dedup_cascade import merge_works
from factory.services.prisma import (
    PrismaFlow,
    SearchReport,
    has_full_text_plan,
    prisma_flow,
    search_report,
)
from factory.services.search import load_works

if TYPE_CHECKING:
    from factory.services.evidence_report import EvidenceReport

BibScope = Literal["included", "corpus"]
DRAFT_SCOPE = "draft:"
BibFormat = Literal["bibtex", "csl"]
PAGE = 500
_BLOB_REF = re.compile(BLOB_REF_RE)
_ORCID = re.compile(r"(?:https://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")
_HASH_PREFIX = "sha256:"
_BUILD = "build"
_OLD = "old"


def _issue(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _corpus_ids(project: Project) -> list[str]:
    """Work ids with non-probe provenance, sorted; one streamed query."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT work_id FROM provenance WHERE query_id NOT IN "
                "(SELECT query_id FROM queries WHERE purpose = :probe) ORDER BY work_id"
            ),
            {"probe": QueryPurpose.PROBE.value},
        ).all()
    return [str(row[0]) for row in rows]


def _canonical_ids(project: Project) -> list[str]:
    """Corpus ids less those absorbed by an active merge whose primary is in the corpus."""
    corpus = _corpus_ids(project)
    present = set(corpus)
    absorbed = {
        wid
        for merge in active_merges(project)
        if merge.primary in present
        for wid in merge.absorbed
        if wid != merge.primary
    }
    return [wid for wid in corpus if wid not in absorbed]


def refuse_before_screening(project: Project) -> None:
    """The agent bibliography waits for a screening pass, for every project and whatever it holds.

    An entry's `doi` reads `[withheld]` when a held-out seed states it, and that would name the
    seed during query design, where decision 37 item 9 does not reach (decisions 43 and 81). The
    check reads no seed, so the refusal says nothing about any. The CLI is not refused.
    """
    if not held_out_visible(project):
        raise _issue("project", "available once a screening pass is open; until then use the CLI")


def select_works(
    project: Project,
    scope: BibScope | str | None = None,
    ids: Sequence[str] = (),
) -> list[str]:
    """Canonical work ids (sorted) of a scope, or the explicit `ids` validated against them.

    `included` is the final outcome INCLUDED at the last declared screening stage: full text when
    the protocol declares a plan, else title/abstract. v1: this scope loads every outcome through
    `final_outcomes`, so it is not streamed (the corpus scope and `ids` are). `draft:<drf_...>` is
    the works its rendered sentences cite (spec ruling 18), those of this project.
    """
    if (scope is None) == (not ids):
        raise _issue("scope", "give exactly one of a scope and a list of ids")
    canonical = _canonical_ids(project)
    if ids:
        known = set(canonical)
        unknown = sorted({wid for wid in ids if wid not in known})
        if unknown:
            raise _issue("ids", f"{len(unknown)} id(s) are not works of this project")
        return sorted(set(ids))
    if scope == "corpus":
        return canonical
    if isinstance(scope, str) and scope.startswith(DRAFT_SCOPE):
        from factory.services.drafts import draft_works  # drafts imports this module

        cited = set(draft_works(project, scope.removeprefix(DRAFT_SCOPE)))
        return [wid for wid in canonical if wid in cited]
    if scope == "included":
        stage = (
            ScreeningStage.FULL_TEXT
            if has_full_text_plan(project)
            else ScreeningStage.TITLE_ABSTRACT
        )
        outcomes = final_outcomes(project, stage=stage)
        return [wid for wid in canonical if outcomes.get(wid) is Outcome.INCLUDED]
    raise _issue("scope", f"unknown scope {scope!r}; use included, corpus or draft:<drf_...>")


def iter_works(project: Project, work_ids: Sequence[str]) -> Iterator[Work]:
    """The canonical works of `work_ids`, in the order given, read in pages of `PAGE`."""
    for _, work in _iter_pairs(project, work_ids):
        yield work


def _iter_pairs(project: Project, work_ids: Sequence[str]) -> Iterator[tuple[str, Work]]:
    """(selected id, canonical work) pairs; the id keys the entry even if a merge re-ranks."""
    members = {merge.primary: merge.absorbed for merge in active_merges(project)}
    for start in range(0, len(work_ids), PAGE):
        page = list(work_ids[start : start + PAGE])
        wanted = list(dict.fromkeys(page + [a for wid in page for a in members.get(wid, ())]))
        loaded = {work.id: work for work in load_works(project, wanted)}
        for wid in page:
            group = [loaded[m] for m in (wid, *members.get(wid, ())) if m in loaded]
            if len(group) > 1:
                yield wid, merge_works(group)
            elif group:
                yield wid, group[0]


def export_bibliography(
    project: Project,
    fmt: BibFormat | str,
    *,
    scope: BibScope | str | None = None,
    ids: Sequence[str] = (),
    ascii_only: bool = False,
) -> Iterator[str]:
    """The bibliography text, streamed. With no `ids`, `scope` defaults to `included`.

    Selection and validation happen before this returns, so a refusal yields nothing.
    """
    if scope is None and not ids:
        scope = "included"
    return render_bibliography(
        project, fmt, select_works(project, scope, ids), ascii_only=ascii_only
    )


def render_bibliography(
    project: Project, fmt: BibFormat | str, work_ids: Sequence[str], *, ascii_only: bool = False
) -> Iterator[str]:
    """The bibliography text of already-selected canonical `work_ids`, streamed. An unknown
    `fmt` is refused before anything is produced."""
    if fmt not in ("bibtex", "csl"):
        raise _issue("format", f"unknown format {fmt!r}; use bibtex or csl")
    keys = assign_keys(work_ids)

    def entries() -> Iterator[tuple[str, Work]]:
        for wid, work in _iter_pairs(project, work_ids):
            yield keys[wid], work

    if fmt == "csl":
        return csl_json(entries())
    return bibtex(entries(), ascii_only=ascii_only)


def export_prisma_svg(project: Project) -> str:
    """The PRISMA 2020 flow of the project as SVG."""
    return prisma_svg(prisma_flow(project))


# --- The log, read once ---


@dataclass
class _LogScan:
    """What one streaming pass over the log found. `last_id` is the log position, and `actors`
    holds the attribution of each event the caller asked for."""

    last_id: str | None = None
    last_ts: str = ""
    agents: Counter[tuple[str, str]] = field(default_factory=Counter)
    refs: set[str] = field(default_factory=set)
    actors: dict[str, Attribution] = field(default_factory=dict)


def _blob_refs(value: JsonValue) -> Iterator[str]:
    """Every string in `value` that has the form of a blob ref."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _BLOB_REF.fullmatch(item):
                yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _scan_log(project: Project, wanted: Collection[str] = ()) -> _LogScan:
    """One pass over the event files, a file at a time. A torn last line is not read."""
    scan = _LogScan()
    for path in event_files(project.paths.events_dir):
        for event in read_file(path, project.catalog).events:
            if scan.last_id is None or event.id > scan.last_id:
                scan.last_id, scan.last_ts = event.id, format_ts(event.ts)
            actor = event.actor
            if actor.kind == "agent" and actor.model is not None and actor.skill is not None:
                scan.agents[(actor.model, actor.skill)] += 1
            if event.input_blob is not None:
                scan.refs.add(event.input_blob)
            scan.refs.update(_blob_refs(event.payload))
            if event.id in wanted:
                scan.actors[event.id] = Attribution(event.id, actor.id, actor.model, actor.skill)
    return scan


def _log_mark(project: Project) -> tuple[tuple[str, int], ...]:
    """Each event file with its size. Event files only grow, so two equal marks mean no event was
    appended between them, wherever in the log it would land. Costs no parse of the log."""
    return tuple((str(path), path.stat().st_size) for path in event_files(project.paths.events_dir))


def _refuse_if_moved(project: Project, mark: tuple[tuple[str, int], ...]) -> None:
    """Refuse an export whose parts may come from different log positions."""
    if _log_mark(project) != mark:
        raise _issue("project", "the log moved; run again")


def _position(scan: _LogScan) -> str:
    """The log position; an empty log has nothing to export."""
    if scan.last_id is None:
        raise _issue("project", "the event log is empty")
    return scan.last_id


# --- Where files go ---


def _refuse_under_projects(project: Project, out: Path) -> None:
    """Exports hold quotes and renderings, so none is written under `projects/`."""
    if out.resolve().is_relative_to((project.paths.root / "projects").resolve()):
        raise _issue("out", "an export is not written under projects/")


def _stage_beside(out: Path) -> Path:
    """A fresh staging directory on the file system of `out`, creating its parents."""
    parent = out.resolve().parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=".factory-export-", dir=parent))
    except OSError as exc:
        raise _issue("out", f"cannot write there: {exc.strerror or exc}") from exc


def _put(stage: Path, path: str, content: Iterable[str] | bytes) -> None:
    """Write one staged file at the POSIX `path`, from bytes or from chunks of text."""
    target = stage / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
        return
    with target.open("w", encoding="utf-8", errors="replace", newline="") as handle:
        handle.writelines(content)


def _build_dir(stage: Path) -> Path:
    """The directory an export is built in. Not the stage itself, whose mode is 0700: this one has
    the mode the umask gives, as the published directory should."""
    built = stage / _BUILD
    built.mkdir()
    return built


def _publish_dir(stage: Path, target: Path) -> None:
    """Put the built directory at `target` by renames, so `target` is at every moment the old
    directory or the new one, whole. A new or empty `target` takes one rename. A full one moves
    aside into the stage first, and back if the new one cannot follow. An existing `target` keeps
    its mode. If moving back fails too, the old directory stays at `<stage>/old`, the error names
    it, and `_staging` leaves the stage in place."""
    built, old = stage / _BUILD, stage / _OLD
    if target.exists():
        os.chmod(built, stat.S_IMODE(target.stat().st_mode))
    if not target.exists() or not any(target.iterdir()):
        os.replace(built, target)
        return
    os.rename(target, old)
    try:
        os.rename(built, target)
    except OSError:
        try:
            os.rename(old, target)
        except OSError as exc:
            raise _issue("out", f"the previous contents are kept at {old}") from exc
        raise
    shutil.rmtree(old, ignore_errors=True)


@contextmanager
def _staging(out: Path) -> Iterator[Path]:
    """A stage beside `out`, removed afterwards unless it holds the only copy of the old `out`."""
    stage = _stage_beside(out)
    try:
        yield stage
    except OSError as exc:
        raise _issue("out", f"cannot write there: {exc.strerror or exc}") from exc
    finally:
        if not (stage / _OLD).exists():
            shutil.rmtree(stage, ignore_errors=True)


# --- Nanopublications ---


class NanopubSummary(StrictModel):
    """What `export_nanopubs` wrote: `claims` and `edges` add up to `written`."""

    written: int
    skipped_no_identifier: int
    claims: int
    edges: int


def _orcid_iri(project: Project) -> str | None:
    """The configured ORCID as an IRI; a malformed one is refused."""
    orcid = project.settings.orcid
    if orcid is None:
        return None
    found = _ORCID.fullmatch(orcid)
    if found is None:
        raise _issue("orcid", "FACTORY_ORCID must be an ORCID iD such as 0000-0002-1825-0097")
    return f"https://orcid.org/{found.group(1)}"


def _creator(project: Project) -> IRI | Literal_:
    """The researcher: ORCID, else the user name as a literal (spec ruling 21). `FACTORY_MAILTO`
    is for source APIs and never reaches an export."""
    orcid = _orcid_iri(project)
    return Literal_(project.settings.user) if orcid is None else IRI(orcid)


def _vocab(project: Project) -> str:
    """The configured vocabulary namespace, which ends in `#` or `/`; else refused."""
    vocab = project.settings.vocab
    try:
        iri(vocab)
    except ValueError:
        raise _issue("vocab", "FACTORY_VOCAB must be an IRI") from None
    if not vocab.endswith(("#", "/")):
        raise _issue("vocab", "FACTORY_VOCAB must end in # or /")
    return vocab


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def _canonical_of(project: Project) -> dict[str, str]:
    """Absorbed work id to the primary of its active merge."""
    return {
        absorbed: merge.primary
        for merge in active_merges(project)
        for absorbed in merge.absorbed
        if absorbed != merge.primary
    }


def _conversion_hashes(project: Project) -> dict[str, str]:
    """Conversion id to the hex hash of its Markdown, as the events state it; the library is not
    read."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT conversion_id, markdown_hash FROM document_conversions")
        ).all()
    return {str(cid): str(ref).removeprefix(_HASH_PREFIX) for cid, ref in rows}


def _basis_hashes(project: Project) -> dict[str, str]:
    """Each final contribution row's id to the `sha256` of its item's quote: one read of the
    items, however many edges there are."""
    from factory.services.contributions import final_items

    return {
        source.extraction_id: _sha256(item.quote)
        for item in final_items(project)
        if item.quote is not None
        for source in item.sources.values()
    }


def _stated_edges(project: Project) -> list[GraphEdge]:
    """The stated and confirmed `builds-on` and `improves-on` edges (the view's default statuses),
    by edge id."""
    from factory.services.lineage import iter_edges

    flt = GraphFilter(edge_types=(EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON), include_ideas=False)
    with entering():
        return sorted(iter_edges(project, flt), key=lambda edge: edge.edge_id)


def _write_nanopub(stage: Path, ident: str, graphs: Nanopub, *, slug: str, vocab: str) -> None:
    _put(stage, f"{ident}.trig", [trig(graphs, prefixes=prefixes(base_iri(slug, ident), vocab))])


def _write_nanopubs(
    project: Project, stage: Path, *, edges: bool, with_quotes: bool, vocab: str
) -> NanopubSummary:
    from factory.services.extraction import live_claims

    slug = project.paths.slug
    creator = _creator(project)
    included = set(select_works(project, "included"))
    canonical = _canonical_of(project)
    claims = [
        claim
        for claim in live_claims(project, PassLabel.A)
        if canonical.get(claim.work_id, claim.work_id) in included
    ]
    scan = _scan_log(project, {claim.event_id for claim in claims})
    position = _position(scan)
    relations = _stated_edges(project) if edges else []
    needed = {canonical.get(claim.work_id, claim.work_id) for claim in claims}
    needed |= {end for edge in relations for end in (edge.source, edge.target)}
    works = dict(_iter_pairs(project, sorted(needed)))
    conversions = _conversion_hashes(project)
    written_claims = written_edges = skipped = 0
    for claim in claims:
        work = works.get(canonical.get(claim.work_id, claim.work_id))
        graphs = None
        if work is not None:
            graphs = claim_nanopub(
                claim,
                work,
                slug=slug,
                creator=creator,
                created=scan.last_ts,
                log_position=position,
                conversion_sha256=conversions.get(claim.conversion_id),
                quote_sha256=_sha256(claim.quote),
                attribution=scan.actors[claim.event_id],
                with_quotes=with_quotes,
                vocab=vocab,
            )
        if graphs is None:
            skipped += 1
            continue
        _write_nanopub(stage, claim.claim_id, graphs, slug=slug, vocab=vocab)
        written_claims += 1
    basis = _basis_hashes(project) if relations else {}
    for edge in relations:
        source, target = works.get(edge.source), works.get(edge.target)
        graphs = None
        if source is not None and target is not None:  # an end may be an idea or a work not held
            graphs = edge_nanopub(
                edge,
                source,
                target,
                basis_quote_sha256=None if edge.basis is None else basis.get(edge.basis),
                slug=slug,
                creator=creator,
                created=scan.last_ts,
                log_position=position,
                vocab=vocab,
            )
        if graphs is None:
            skipped += 1
            continue
        _write_nanopub(stage, edge.edge_id, graphs, slug=slug, vocab=vocab)
        written_edges += 1
    return NanopubSummary(
        written=written_claims + written_edges,
        skipped_no_identifier=skipped,
        claims=written_claims,
        edges=written_edges,
    )


def export_nanopubs(
    project: Project, out: Path, *, edges: bool = False, with_quotes: bool = False
) -> NanopubSummary:
    """One `.trig` file per live pass A claim of an included work under `out/`, named by claim id,
    and with `edges` one per stated or confirmed lineage edge, named by edge id. Unsigned. Refuses
    an `out` under `projects/` or one that already holds files, since a file left from an older
    log would read as part of this export. A work without a DOI or arXiv id is skipped and
    counted."""
    _refuse_under_projects(project, out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise _issue("out", "must be an empty directory or a new path")
    vocab = _vocab(project)
    with _staging(out) as stage:
        mark = _log_mark(project)
        summary = _write_nanopubs(
            project, _build_dir(stage), edges=edges, with_quotes=with_quotes, vocab=vocab
        )
        _refuse_if_moved(project, mark)
        _publish_dir(stage, out.resolve())
        return summary


# --- The RO-Crate ---


class CrateSummary(StrictModel):
    """What `export_crate` wrote. `files` and `bytes` count the descriptor too. A referenced blob
    that is not text is left out (`blobs_binary`), and so is one that no longer matches its hash
    or whose hash the library also holds (`blobs_left_out`)."""

    files: int
    bytes: int
    documents_listed: int
    drafts: int
    blobs_binary: int
    blobs_left_out: int


@dataclass(frozen=True)
class CrateRenderers:
    """The report renderers, which live with the CLI's formatting. Passed in so that a service
    does not import `cli/`."""

    prisma_markdown: Callable[[PrismaFlow], str]
    search_markdown: Callable[[SearchReport], str]
    evidence_markdown: Callable[[EvidenceReport], str]
    evidence_rows_csv: Callable[[EvidenceReport], str]
    evidence_points_csv: Callable[[EvidenceReport], str]


_CRATE_TOP = frozenset(
    {DESCRIPTOR, MANIFEST, "bibliography", "blobs", "events", "protocol", "reports"}
)
_FORMATS = {
    ".bib": "application/x-bibtex",
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".md": "text/markdown",
    ".svg": "image/svg+xml",
}
_GENERATED = ("bibliography/", "reports/")
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_ZIP_NAME = ".crate.zip"


def _bytes(value: str) -> bytes:
    """UTF-8; a lone surrogate from a hand-written event cannot stop the export."""
    return value.encode("utf-8", "replace")


def _json(value: JsonValue) -> bytes:
    return _bytes(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _check_crate_target(project: Project, out: Path, *, zip_: bool, force: bool) -> None:
    """Refuse a path under `projects/` and, without `force`, one that holds anything. `force`
    replaces only what proves to be a crate by its descriptor, never by the names of its entries:
    `reports/` or `events/` alone may be the researcher's own."""
    _refuse_under_projects(project, out)
    if zip_:
        if out.is_dir():
            raise _issue("out", "is a directory; a zip crate needs a file path")
        if out.exists() and not force:
            raise _issue("out", "already exists; --force replaces a crate there")
        if out.exists() and not _is_crate_zip(out):
            raise _issue("out", "is not a zip crate; --force replaces only a crate")
        return
    if not out.exists():
        return
    if not out.is_dir():
        raise _issue("out", "is a file; a crate needs a directory, or --zip")
    held = {child.name for child in out.iterdir()}
    if not held:
        return
    if not force:
        raise _issue("out", "is not empty; --force replaces a crate there")
    if not _is_crate_dir(out):
        raise _issue("out", "is not a crate; --force replaces only a crate")
    if held - _CRATE_TOP:
        raise _issue("out", "holds files that are not part of a crate")


def _is_descriptor(data: bytes) -> bool:
    """Whether `data` is an RO-Crate 1.1 metadata file: JSON whose descriptor entity conforms."""
    try:
        document = json.loads(data)
    except ValueError:
        return False
    graph = document.get("@graph") if isinstance(document, dict) else None
    return isinstance(graph, list) and any(
        isinstance(entity, dict)
        and entity.get("@id") == DESCRIPTOR
        and entity.get("conformsTo") == {"@id": RO_CRATE}
        for entity in graph
    )


def _is_crate_dir(path: Path) -> bool:
    try:
        return _is_descriptor((path / DESCRIPTOR).read_bytes())
    except OSError:
        return False


def _is_crate_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return _is_descriptor(archive.read(DESCRIPTOR))
    except (OSError, KeyError, zipfile.BadZipFile):
        return False


def _copy_events(project: Project, stage: Path) -> None:
    """The event files as they are, without a torn last line, which is not part of the log."""
    events_dir = project.paths.events_dir
    for path in event_files(events_dir):
        data = path.read_bytes()
        _put(stage, f"events/{relative_name(path, events_dir)}", data[: data.rfind(b"\n") + 1])


def _copy_blobs(project: Project, stage: Path, refs: Iterable[str]) -> tuple[int, int]:
    """The text blobs among `refs`, at the store's own layout; `(binary, left out)` counts.

    A ref in a payload may name the library. The blob store holds none of that, but a blob with
    the same hash as a library entry is its content, so it stays out whatever the store says
    (R-47). `project.library` is asked only whether the hash exists; its content is never read."""
    binary = left_out = 0
    for ref in sorted(refs):
        if project.library.exists(ref):
            left_out += int(project.blobs.exists(ref))
            continue
        try:
            data = project.blobs.get(ref)
        except BlobNotFoundError:
            continue  # library hashes have the same form, and their files are not in this store
        except BlobIntegrityError:
            left_out += 1
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            binary += 1
            continue
        digest = ref.removeprefix(_HASH_PREFIX)
        _put(stage, f"blobs/sha256/{digest[:2]}/{digest[2:]}", data)
    return binary, left_out


def _write_protocol(project: Project, stage: Path) -> None:
    from factory.services.protocol import current_protocol, list_amendments

    protocol = current_protocol(project)
    if protocol is None:
        return
    amendments = [a.model_dump(mode="json") for a in list_amendments(project)]
    body: dict[str, JsonValue] = {
        "amendments": cast(JsonValue, amendments),
        "protocol": protocol.model_dump(mode="json"),
    }
    _put(stage, "protocol/protocol.json", _json(body))


def _graph_exists(project: Project) -> bool:
    with project.index.connect() as conn:
        return conn.execute(text("SELECT 1 FROM graph_nodes LIMIT 1")).first() is not None


def _write_reports(project: Project, stage: Path, renderers: CrateRenderers) -> None:
    """Each report as the researcher's own service gives it: complete, nothing withheld."""
    from factory.services.evidence_report import evidence_report
    from factory.services.lineage import iter_graph_export
    from factory.services.methods import methods_report, render_methods

    flow = prisma_flow(project)
    evidence = evidence_report(project)
    _put(stage, "reports/prisma.md", _bytes(renderers.prisma_markdown(flow)))
    _put(stage, "reports/prisma.svg", _bytes(prisma_svg(flow)))
    _put(stage, "reports/search.md", _bytes(renderers.search_markdown(search_report(project))))
    _put(stage, "reports/methods.md", _bytes(render_methods(methods_report(project))))
    _put(stage, "reports/evidence.md", _bytes(renderers.evidence_markdown(evidence)))
    _put(stage, "reports/evidence-rows.csv", _bytes(renderers.evidence_rows_csv(evidence)))
    _put(stage, "reports/evidence-points.csv", _bytes(renderers.evidence_points_csv(evidence)))
    if _graph_exists(project):
        with entering():
            _put(stage, "reports/lineage.json", iter_graph_export(project, "json"))


def _release_rows(project: Project, draft_id: str) -> list[dict[str, JsonValue]]:
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT event_id, as_of, policy, released_by, actor_kind, counts "
                    "FROM draft_releases WHERE draft_id = :d ORDER BY event_id"
                ),
                {"d": draft_id},
            )
            .mappings()
            .all()
        )
    return [{**dict(row), "counts": json.loads(str(row["counts"]))} for row in rows]


def _write_drafts(project: Project, stage: Path) -> int:
    """Each released draft in clean form, rendered from the current log, with its release records
    and the current status counts beside it, so a draft gone stale since shows the difference."""
    from factory.services.draft_release import released_drafts
    from factory.services.drafts import draft_render, sentence_status, status_counts

    released = sorted(released_drafts(project))
    for draft_id in released:
        clean = draft_render(project, draft_id, "clean")
        _put(stage, f"reports/drafts/{draft_id}.md", _bytes(clean))
        record: dict[str, JsonValue] = {
            "current_counts": cast(JsonValue, status_counts(sentence_status(project, draft_id))),
            "draft_id": draft_id,
            "releases": cast(JsonValue, _release_rows(project, draft_id)),
        }
        _put(stage, f"reports/drafts/{draft_id}.release.json", _json(record))
    return len(released)


def _write_bibliography(project: Project, stage: Path) -> None:
    included = select_works(project, "included")
    _put(stage, "bibliography/included.bib", render_bibliography(project, "bibtex", included))
    _put(stage, "bibliography/included.csl.json", render_bibliography(project, "csl", included))


def _manifest_entries(project: Project) -> list[ManifestEntry]:
    """One entry per document of the full-text events, from the projection: metadata only."""
    with project.index.connect() as conn:
        documents = (
            conn.execute(
                text(
                    "SELECT d.document_id, d.work_id, d.raw_hash, d.route, d.source_version, "
                    "a.url, a.licence, a.licence_status, a.retrieved_at "
                    "FROM fulltext_documents d "
                    "LEFT JOIN fulltext_attempts a ON a.attempt_id = d.attempt_id "
                    "ORDER BY d.document_id"
                )
            )
            .mappings()
            .all()
        )
        conversions = (
            conn.execute(
                text(
                    "SELECT document_id, conversion_id, converter, converter_version, "
                    "markdown_hash, manifest_hash FROM document_conversions "
                    "ORDER BY conversion_id"
                )
            )
            .mappings()
            .all()
        )
    by_document: dict[str, list[ConversionEntry]] = {}
    for row in conversions:
        by_document.setdefault(str(row["document_id"]), []).append(
            ConversionEntry(
                conversion_id=str(row["conversion_id"]),
                converter=str(row["converter"]),
                converter_version=str(row["converter_version"]),
                markdown_sha256=str(row["markdown_hash"]).removeprefix(_HASH_PREFIX),
                manifest_sha256=str(row["manifest_hash"]).removeprefix(_HASH_PREFIX),
            )
        )
    return [
        ManifestEntry(
            document_id=str(row["document_id"]),
            work_id=str(row["work_id"]),
            sha256=str(row["raw_hash"]).removeprefix(_HASH_PREFIX),
            route=str(row["route"]),
            url=row["url"],
            source_version=str(row["source_version"]),
            licence=row["licence"],
            licence_status=row["licence_status"],
            retrieved_at=row["retrieved_at"],
            conversions=tuple(by_document.get(str(row["document_id"]), ())),
        )
        for row in documents
    ]


def _staged_files(stage: Path) -> list[Path]:
    """Every staged file, by POSIX path relative to `stage`."""
    return sorted(
        (path for path in stage.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(stage).as_posix(),
    )


def _members(project: Project, stage: Path) -> list[CrateFile]:
    """The crate's files with their hashes. The last line of defence for R-47: a file whose hash
    the library holds stops the export, whatever put it there."""
    members: list[CrateFile] = []
    for path in _staged_files(stage):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if project.library.exists(f"{_HASH_PREFIX}{digest}"):
            raise _issue("library", "a crate file equals a library file; nothing was written")
        name = path.relative_to(stage).as_posix()
        generated = name.startswith(_GENERATED)
        members.append(
            CrateFile(
                path=name,
                sha256=digest,
                encoding_format=_FORMATS.get(path.suffix, "text/plain"),
                produced_by=f"Generate {name}" if generated else None,
            )
        )
    return members


def _factory_version() -> str:
    try:
        return version("factory")
    except PackageNotFoundError:
        return "unknown"


def _description(project: Project) -> str:
    """The latest raw goal: the researcher's own text, not literature."""
    from factory.services.question import goals

    stated = goals(project)
    return stated[-1].text if stated else f"Research Factory project {project.paths.slug}"


def _assemble(project: Project, stage: Path, renderers: CrateRenderers) -> CrateSummary:
    """Every crate file under `stage`. Reads events, blobs and the projection, and of the library
    only whether a hash exists."""
    scan = _scan_log(project)
    position = _position(scan)
    orcid = _orcid_iri(project)
    _copy_events(project, stage)
    binary, left_out = _copy_blobs(project, stage, scan.refs)
    _write_protocol(project, stage)
    _write_reports(project, stage, renderers)
    drafts = _write_drafts(project, stage)
    _write_bibliography(project, stage)
    entries = _manifest_entries(project)
    _put(stage, MANIFEST, _bytes(manifest_json(entries)))
    members = _members(project, stage)
    metadata = crate_metadata(
        slug=project.paths.slug,
        description=_description(project),
        last_event=position,
        last_ts=scan.last_ts,
        licence=project.settings.licence,
        person=project.settings.user,
        orcid=orcid,
        factory_version=_factory_version(),
        files=members,
        agents=[
            AgentEntry(model=model, skill=skill, events=count)
            for (model, skill), count in sorted(scan.agents.items())
        ],
    )
    _put(stage, DESCRIPTOR, _bytes(metadata))
    paths = _staged_files(stage)
    return CrateSummary(
        files=len(paths),
        bytes=sum(path.stat().st_size for path in paths),
        documents_listed=len(entries),
        drafts=drafts,
        blobs_binary=binary,
        blobs_left_out=left_out,
    )


def _write_zip(source: Path, built: Path, target: Path) -> None:
    """The files under `source` zipped at `built`, then moved to `target` in one step: sorted,
    fixed timestamps, `ZIP_DEFLATED` level 9, so the same files give the same bytes."""
    with zipfile.ZipFile(built, "w") as archive:
        for path in _staged_files(source):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=_ZIP_DATE)
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(
                info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    os.replace(built, target)


def export_crate(
    project: Project,
    out: Path,
    renderers: CrateRenderers,
    *,
    zip_: bool = False,
    force: bool = False,
) -> CrateSummary:
    """The project as an RO-Crate 1.1 at `out`: a directory, or a zip file with `zip_`.

    Holds the log, the text blobs the events reference, the protocol, the reports, the released
    drafts, the bibliography and a manifest of library documents without their content (spec
    ruling 20). Byte-identical for the same log and settings. Refuses an `out` under `projects/`
    and, without `force`, one that holds anything. CLI only (spec ruling 22)."""
    _check_crate_target(project, out, zip_=zip_, force=force)
    with _staging(out) as stage:
        mark = _log_mark(project)
        built = _build_dir(stage)
        summary = _assemble(project, built, renderers)
        _refuse_if_moved(project, mark)
        if zip_:
            _write_zip(built, stage / _ZIP_NAME, out.resolve())
        else:
            _publish_dir(stage, out.resolve())
        return summary


__all__ = [
    "PAGE",
    "BibFormat",
    "BibScope",
    "CrateRenderers",
    "CrateSummary",
    "NanopubSummary",
    "export_bibliography",
    "export_crate",
    "export_nanopubs",
    "export_prisma_svg",
    "iter_works",
    "refuse_before_screening",
    "render_bibliography",
    "select_works",
]
