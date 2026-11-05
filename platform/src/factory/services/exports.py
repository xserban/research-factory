"""Exports from events only: the bibliography of a scope of works, the PRISMA flow as SVG, and the
nanopublications of claims and stated edges.

Read-only and byte-deterministic: works are selected by id, sorted by id, read from the
projection in pages of `PAGE` and serialised as they stream; nothing here touches the library
(R-47) or writes an event. A merged work is exported as its canonical record (the merge of its
members), as `canonical_works` would give it.

Invariants:
- Every refusal is a FactoryValidationError raised before the first character is produced.
- Exactly one of `scope` and `ids` selects works; an unknown or absorbed id is refused.
- Files go only to the path the researcher names, never under `projects/`. They are built in a
  staging directory beside it, under the index's lock so the log cannot move, and appear only
  when complete; a refusal or a failure leaves the path as it was.
- These file exports are the researcher's (CLI only, spec ruling 22), so nothing here is withheld.

Services imported inside a function are those that may reach `drafts`, which imports this module.
"""

import hashlib
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import JsonValue
from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BLOB_REF_RE
from factory.events.reader import event_files, read_file
from factory.exports.bibtex import bibtex
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
from factory.services.prisma import has_full_text_plan, prisma_flow
from factory.services.search import load_works

BibScope = Literal["included", "corpus"]
DRAFT_SCOPE = "draft:"
BibFormat = Literal["bibtex", "csl"]
PAGE = 500
_BLOB_REF = re.compile(BLOB_REF_RE)
_ORCID = re.compile(r"(?:https://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")
_HASH_PREFIX = "sha256:"


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
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.writelines(content)


def _move_children(stage: Path, target: Path) -> None:
    """Move what `stage` holds into `target`, which is created if absent."""
    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(stage.iterdir()):
        os.replace(child, target / child.name)


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
    """The researcher: ORCID, else `mailto:`, else the user name as a literal."""
    orcid = _orcid_iri(project)
    if orcid is not None:
        return IRI(orcid)
    mailto = project.settings.mailto
    if mailto:
        return iri(f"mailto:{quote(mailto, safe='@+')}")
    return Literal_(project.settings.user)


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
    stage = _stage_beside(out)
    try:
        with project.index.exclusive():
            summary = _write_nanopubs(
                project, stage, edges=edges, with_quotes=with_quotes, vocab=vocab
            )
        _move_children(stage, out)
        return summary
    except OSError as exc:
        raise _issue("out", f"cannot write there: {exc.strerror or exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


__all__ = [
    "PAGE",
    "BibFormat",
    "BibScope",
    "NanopubSummary",
    "export_bibliography",
    "export_nanopubs",
    "export_prisma_svg",
    "iter_works",
    "refuse_before_screening",
    "render_bibliography",
    "select_works",
]
