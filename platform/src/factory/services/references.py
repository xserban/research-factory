"""Reference extraction: orchestration, population, counts and listing (slice 3a).

`extract_references` parses the bibliography of each work's current default conversion (and the
`.bbl` of a live `arxiv-source` document, when held), finds the in-text markers, resolves every
entry (`reference_resolve.resolve_entries`, whose probe lookups are recorded searches), and then
writes, per work and in this order, one `reference.extracted`, one `citation.contexts_recorded`
and one `reference.resolved` event.

Invariants:
- Population (ruling 15): works whose final outcome is INCLUDED at the last declared stage (full
  text when the protocol has a full-text plan, else title/abstract), with a default conversion.
  The default scope is those without a current extraction; a named work that is not included, has
  no conversion or whose stored conversion is unreadable is skipped with a reason, never refused.
- No raw entry text is stored (ruling 14): entries carry the parsed fields and `entry_sha256`
  over the whitespace-normalised text of the entry's anchor. Title, venue and surname longer than
  the model bounds are truncated (flag `field-truncated`); an over-long DOI, arXiv id or URL is
  dropped, since a cut identifier is a wrong one (flag `field-dropped`).
- An agent's events carry `input_blob`: the request, the conversion and the entry hashes, never
  the bibliography text (decision 39; the blob store is tracked in git).
- An extraction is current while it is the live extraction of its work, pinned to the work's
  default conversion, with this parser version. A new extraction supersedes the earlier one.
- Counts are computed from the live extractions; the link states sum to the entry count.
- Listing is paged with a fixed cap (`MAX_PAGE`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.fulltext import Quality, Route
from factory.model.protocol import ScreeningStage
from factory.model.references import (
    MAX_ARXIV,
    MAX_DOI,
    MAX_SURNAME,
    MAX_TITLE,
    MAX_URL,
    MAX_VENUE,
    BblInfo,
    CitationContext,
    CitationContextsRecorded,
    LinkState,
    ReferenceEntry,
    ReferenceExtracted,
    ReferenceResolved,
)
from factory.model.seed import HeldOut
from factory.model.work_ids import WORK_ID_RE
from factory.references.bbl import align, read_bbl
from factory.references.markers import completeness_flags, find_contexts
from factory.references.match import MATCHER_VERSION
from factory.references.parse import (
    PARSER,
    PARSER_VERSION,
    Bibliography,
    RefFields,
    parse_bibliography,
)
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import ConversionRef, default_conversion
from factory.services.protocol import current_protocol
from factory.services.reference_resolve import entry_digest, entry_raw, resolve_entries
from factory.services.search import list_works
from factory.sources.registry import SourceFactory

MAX_PAGE = 100

SkipReason = Literal["not-included", "no-conversion", "library-missing"]


class Skipped(StrictModel):
    work_id: str
    reason: SkipReason


class ExtractionResult(StrictModel):
    """One recorded extraction: counts computed from what was written."""

    extraction_id: str
    work_id: str
    conversion_id: str
    entries: int
    markers: int
    flags: list[str]
    states: dict[LinkState, int]
    lookup_runs: list[str]


class ExtractSummary(StrictModel):
    extractions: list[ExtractionResult]
    skipped: list[Skipped]


class ReferenceCounts(StrictModel):
    """Over the live extractions. `in_corpus` and `new_candidates` count distinct works."""

    extractions: int
    entries: int
    resolved: int
    unconfirmed: int
    ambiguous: int
    unresolved: int
    no_source_record: int
    in_corpus: int
    new_candidates: int


class ReferenceItem(StrictModel):
    """One entry of a live extraction and its link; `work_id` is the linked work, if any."""

    extraction_id: str
    citing_work: str
    ordinal: int
    anchor: str
    label: str | None
    title: str | None
    first_author: str | None
    year: int | None
    doi: str | None
    arxiv: str | None
    state: LinkState
    work_id: str | None
    confidence: str | None
    method: str | None
    score: float | None
    candidates: list[tuple[str, float]]
    reason: str | None
    base_state: LinkState
    base_work_id: str | None
    decision: str | None
    confirmed_by: str | None
    proposal: str | None
    no_source_record: bool


class Page(StrictModel):
    items: list[ReferenceItem]
    total: int
    next_after: int | None


# --- Population ---


def included_works(project: Project) -> list[str]:
    """Works INCLUDED at the last declared stage (ruling 15), sorted."""
    protocol = current_protocol(project)
    full_text = protocol is not None and protocol.spec.full_text_screening is not None
    stage = ScreeningStage.FULL_TEXT if full_text else ScreeningStage.TITLE_ABSTRACT
    outcomes = final_outcomes(project, stage=stage)
    return sorted(w for w, outcome in outcomes.items() if outcome is Outcome.INCLUDED)


def current_extraction(project: Project, work_id: str) -> str | None:
    """The live extraction of `work_id` if it is pinned to the work's default conversion and was
    made with this parser version; else None."""
    project.index.sync()
    conversion = default_conversion(project, work_id)
    if conversion is None:
        return None
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT extraction_id, conversion_id, parser_version FROM reference_extractions "
                "WHERE work_id = :work AND live = 1"
            ),
            {"work": work_id},
        ).first()
    if row is None or row[1] != conversion.conversion_id or row[2] != PARSER_VERSION:
        return None
    return str(row[0])


# --- Extraction ---


def extract_references(
    project: Project,
    actor: Actor,
    work_ids: Sequence[str] | None,
    *,
    sources: Mapping[str, SourceFactory],
) -> ExtractSummary:
    """Extract and resolve the references of `work_ids` (default: every included work with a
    conversion and no current extraction). A malformed work id refuses the call, writing nothing.
    """
    if work_ids is not None:
        bad = [w for w in work_ids if re.match(WORK_ID_RE, w) is None]
        if bad:
            raise FactoryValidationError(
                [ValidationIssue("work_ids", f"{w!r}: not a work id") for w in bad]
            )
    project.index.sync()
    included = set(included_works(project))
    skipped: list[Skipped] = []
    scope: list[tuple[str, ConversionRef]] = []
    if work_ids is None:
        for work in sorted(included):
            conversion = default_conversion(project, work)
            if conversion is not None and current_extraction(project, work) is None:
                scope.append((work, conversion))
    else:
        for work in dict.fromkeys(work_ids):
            conversion = default_conversion(project, work)
            if work not in included:
                skipped.append(Skipped(work_id=work, reason="not-included"))
            elif conversion is None:
                skipped.append(Skipped(work_id=work, reason="no-conversion"))
            else:
                scope.append((work, conversion))
    results: list[ExtractionResult] = []
    for work, conversion in scope:
        result = _extract_one(project, actor, work, conversion, sources=sources)
        if isinstance(result, Skipped):
            skipped.append(result)
        else:
            results.append(result)
    return ExtractSummary(extractions=results, skipped=skipped)


def _bounded(value: str | None, limit: int) -> tuple[str | None, bool]:
    """`value` cut to `limit` characters (trailing space removed), and whether it was cut."""
    if value is None or len(value) <= limit:
        return value, False
    return value[:limit].rstrip() or None, True


def _kept(value: str | None, limit: int) -> tuple[str | None, bool]:
    """`value`, or None (dropped) when it is longer than `limit`."""
    if value is None or len(value) <= limit:
        return value, False
    return None, True


def _entries(
    bib: Bibliography,
    texts: Mapping[str, str],
    bbl_fields: Sequence[RefFields | None],
) -> tuple[tuple[ReferenceEntry, ...], list[str]]:
    out: list[ReferenceEntry] = []
    truncated = dropped = False
    for entry, extra in zip(bib.entries, bbl_fields, strict=True):
        f = entry.fields
        doi = f.doi or (extra.doi if extra else None)
        arxiv = f.arxiv or (extra.arxiv if extra else None)
        url = f.url or (extra.url if extra else None)
        title, cut_title = _bounded(f.title, MAX_TITLE)
        venue, cut_venue = _bounded(f.venue, MAX_VENUE)
        surname, cut_surname = _bounded(f.first_author, MAX_SURNAME)
        doi, drop_doi = _kept(doi, MAX_DOI)
        arxiv, drop_arxiv = _kept(arxiv, MAX_ARXIV)
        url, drop_url = _kept(url, MAX_URL)
        truncated = truncated or cut_title or cut_venue or cut_surname
        dropped = dropped or drop_doi or drop_arxiv or drop_url
        out.append(
            ReferenceEntry(
                ordinal=entry.ordinal,
                anchor=entry.anchor,
                label=entry.label,
                doi=doi,
                arxiv=arxiv,
                url=url,
                year=f.year,
                first_author=surname,
                title=title,
                venue=venue,
                entry_sha256=entry_digest(texts[entry.anchor]),
            )
        )
    flags = (["field-truncated"] if truncated else []) + (["field-dropped"] if dropped else [])
    return tuple(out), flags


def _bbl(
    project: Project, work: str, bib: Bibliography
) -> tuple[BblInfo, tuple[RefFields | None, ...], list[str]]:
    """The `.bbl` alignment of the work's live `arxiv-source` document, when there is one."""
    nothing: tuple[RefFields | None, ...] = (None,) * len(bib.entries)
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT raw_hash FROM fulltext_documents WHERE work_id = :work AND route = :route "
                "AND superseded_by IS NULL ORDER BY event_id DESC"
            ),
            {"work": work, "route": Route.ARXIV_SOURCE.value},
        ).first()
    if row is None:
        return BblInfo(status="absent"), nothing, []
    archive = str(row[0])
    try:
        data = project.library.get(archive)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        return BblInfo(status="absent"), nothing, ["bbl-archive-missing"]
    alignment = align(bib, read_bbl(data))
    if alignment.status == "absent":
        return BblInfo(status="absent"), nothing, []
    info = BblInfo(status=alignment.status, archive_blob=archive, bbl_count=alignment.bbl_count)
    flags = ["bbl-count-mismatch"] if alignment.status == "count-mismatch" else []
    return info, alignment.fields, flags


def _quality(project: Project, document_id: str) -> Quality:
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT quality FROM fulltext_documents WHERE document_id = :doc"),
            {"doc": document_id},
        ).scalar_one()
    return Quality(str(value))


def _extract_one(
    project: Project,
    actor: Actor,
    work: str,
    conversion: ConversionRef,
    *,
    sources: Mapping[str, SourceFactory],
) -> ExtractionResult | Skipped:
    try:
        manifest = conversion_manifest(project, conversion.conversion_id)
    except FactoryValidationError:
        return Skipped(work_id=work, reason="library-missing")
    bib = parse_bibliography(manifest)
    contexts, marker_count = find_contexts(manifest, bib)
    texts: dict[str, str] = {}
    for entry in bib.entries:
        anchor = manifest.get(entry.anchor)
        texts[entry.anchor] = entry_raw(anchor.text if anchor is not None else entry.text)
    bbl, bbl_fields, bbl_flags = _bbl(project, work, bib)
    entries, field_flags = _entries(bib, texts, bbl_fields)
    flags = list(
        dict.fromkeys([*bib.flags, *completeness_flags(bib, contexts), *bbl_flags, *field_flags])
    )
    outcome = resolve_entries(project, actor, entries, sources=sources)

    extraction_id = project.ids.new("rex")
    extracted = ReferenceExtracted(
        extraction_id=extraction_id,
        work_id=work,
        document_id=conversion.document_id,
        conversion_id=conversion.conversion_id,
        parser=PARSER,
        parser_version=PARSER_VERSION,
        entry_anchors=bib.entry_anchors,
        source_quality=_quality(project, conversion.document_id),
        entries=entries,
        marker_count=marker_count,
        flags=tuple(flags),
        bbl=bbl,
    )
    recorded = CitationContextsRecorded(
        extraction_id=extraction_id,
        contexts=tuple(
            CitationContext(
                citing_anchor=c.citing_anchor,
                entry=c.entry,
                marker=c.marker,
                method=c.method,
                state=c.state,
            )
            for c in contexts
        ),
    )
    resolved = ReferenceResolved(
        extraction_id=extraction_id,
        resolutions=outcome.resolutions,
        matcher_version=MATCHER_VERSION,
        lookup_runs=outcome.lookup_runs,
    )
    input_blob = (
        project.blobs.put_json(
            {
                "work_id": work,
                "document_id": conversion.document_id,
                "conversion_id": conversion.conversion_id,
                "parser": f"{PARSER}@{PARSER_VERSION}",
                "matcher_version": MATCHER_VERSION,
                "entry_sha256": [e.entry_sha256 for e in entries],
            }
        )
        if actor.kind == "agent"
        else None
    )
    events: list[Event] = [
        project.events.make(
            type_, payload, actor, refs=(extraction_id, work), input_blob=input_blob
        )
        for type_, payload in (
            ("reference.extracted", extracted),
            ("citation.contexts_recorded", recorded),
            ("reference.resolved", resolved),
        )
    ]
    with project.index.exclusive():
        project.record(events)
    states = {state: 0 for state in LinkState}
    for r in outcome.resolutions:
        states[r.state] += 1
    return ExtractionResult(
        extraction_id=extraction_id,
        work_id=work,
        conversion_id=conversion.conversion_id,
        entries=len(entries),
        markers=marker_count,
        flags=flags,
        states=states,
        lookup_runs=list(outcome.lookup_runs),
    )


# --- Counts and listing ---

_LIVE = "JOIN reference_extractions x ON x.extraction_id = {t}.extraction_id AND x.live = 1"


def agent_extract_view(summary: ExtractSummary, held_out: HeldOut) -> ExtractSummary:
    """`summary` without the extractions and skips of held-out works (R-20)."""
    return ExtractSummary(
        extractions=[e for e in summary.extractions if not held_out.hides(e.work_id)],
        skipped=[k for k in summary.skipped if not held_out.hides(k.work_id)],
    )


def _hidden(item: ReferenceItem, held: HeldOut) -> bool:
    """Whether a link touches a held-out seed's work: its linked, base or candidate work, or an
    identifier the entry states."""
    works = (item.work_id, item.base_work_id, *(w for w, _ in item.candidates))
    return any(held.hides(w) for w in works) or held.hides(None, item.doi, item.arxiv)


def _masked(item: ReferenceItem) -> ReferenceItem:
    """The item as an unresolved entry: no linked work, no identifier, no title (R-20)."""
    return item.model_copy(
        update={
            "state": LinkState.UNRESOLVED,
            "work_id": None,
            "confidence": None,
            "method": None,
            "score": None,
            "candidates": [],
            "reason": None,
            "base_state": LinkState.UNRESOLVED,
            "base_work_id": None,
            "decision": None,
            "confirmed_by": None,
            "proposal": None,
            "no_source_record": False,
            "doi": None,
            "arxiv": None,
            "title": None,
        }
    )


def reference_counts(project: Project, held_out: HeldOut | None = None) -> ReferenceCounts:
    """Counts over the live extractions; the four states sum to `entries`. With `held_out`, a link
    that touches a held-out seed's work counts as unresolved, as `list_references` shows it."""
    if held_out is not None and (held_out.work_ids or held_out.keys):
        return _counts(project, _agent_items(project, held_out))
    return _counts_sql(project)


def _counts(project: Project, items: Sequence[ReferenceItem]) -> ReferenceCounts:
    corpus = {w.id for w in list_works(project)}
    states = {state: 0 for state in LinkState}
    targets: set[str] = set()
    no_source = 0
    extractions = {i.extraction_id for i in items}
    for i in items:
        states[i.state] += 1
        if i.state is LinkState.RESOLVED and i.work_id is not None:
            targets.add(i.work_id)
            no_source += int(i.no_source_record)
    return ReferenceCounts(
        extractions=len(extractions),
        entries=len(items),
        resolved=states[LinkState.RESOLVED],
        unconfirmed=states[LinkState.UNCONFIRMED],
        ambiguous=states[LinkState.AMBIGUOUS],
        unresolved=states[LinkState.UNRESOLVED],
        no_source_record=no_source,
        in_corpus=len(targets & corpus),
        new_candidates=len(targets - corpus),
    )


def _counts_sql(project: Project) -> ReferenceCounts:
    """Counts over the live extractions; the four states sum to `entries`."""
    project.index.sync()
    with project.index.connect() as conn:
        extractions = conn.execute(
            text("SELECT COUNT(*) FROM reference_extractions WHERE live = 1")
        ).scalar_one()
        entries = conn.execute(
            text(f"SELECT COUNT(*) FROM reference_entries n {_LIVE.format(t='n')}")
        ).scalar_one()
        links = conn.execute(
            text(
                f"SELECT l.state, l.work_id, l.no_source_record FROM reference_links l "
                f"{_LIVE.format(t='l')}"
            )
        ).all()
    corpus = {w.id for w in list_works(project)}
    states = {state: 0 for state in LinkState}
    targets: set[str] = set()
    no_source = 0
    for state, work, flagged in links:
        states[LinkState(str(state))] += 1
        if state == LinkState.RESOLVED.value and work is not None:
            targets.add(str(work))
            no_source += int(flagged)
    return ReferenceCounts(
        extractions=int(extractions),
        entries=int(entries),
        resolved=states[LinkState.RESOLVED],
        unconfirmed=states[LinkState.UNCONFIRMED],
        ambiguous=states[LinkState.AMBIGUOUS],
        unresolved=states[LinkState.UNRESOLVED],
        no_source_record=no_source,
        in_corpus=len(targets & corpus),
        new_candidates=len(targets - corpus),
    )


def _all_items(project: Project, work_id: str | None = None) -> list[ReferenceItem]:
    """Every entry of the live extractions with its link, by citing work, extraction, ordinal."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT n.extraction_id, x.work_id AS citing_work, n.ordinal, n.anchor, "
                    "n.label, n.title, n.first_author, n.year, n.doi, n.arxiv, l.state, "
                    "l.work_id, l.confidence, l.method, l.score, l.candidates, l.reason, "
                    "l.base_state, l.base_work_id, l.decision, l.confirmed_by, l.proposal, "
                    "l.no_source_record "
                    f"FROM reference_entries n {_LIVE.format(t='n')} "
                    "JOIN reference_links l ON l.extraction_id = n.extraction_id "
                    "AND l.ordinal = n.ordinal "
                    "WHERE (:work IS NULL OR x.work_id = :work) "
                    "ORDER BY x.work_id, n.extraction_id, n.ordinal"
                ),
                {"work": work_id},
            )
            .mappings()
            .all()
        )
    return [
        ReferenceItem(
            extraction_id=str(r["extraction_id"]),
            citing_work=str(r["citing_work"]),
            ordinal=int(r["ordinal"]),
            anchor=str(r["anchor"]),
            label=r["label"],
            title=r["title"],
            first_author=r["first_author"],
            year=r["year"],
            doi=r["doi"],
            arxiv=r["arxiv"],
            state=LinkState(str(r["state"])),
            work_id=r["work_id"],
            confidence=r["confidence"],
            method=r["method"],
            score=r["score"],
            candidates=[
                (str(c["work_id"]), float(c["score"])) for c in json.loads(r["candidates"])
            ],
            reason=r["reason"],
            base_state=LinkState(str(r["base_state"])),
            base_work_id=r["base_work_id"],
            decision=r["decision"],
            confirmed_by=r["confirmed_by"],
            proposal=r["proposal"],
            no_source_record=bool(r["no_source_record"]),
        )
        for r in rows
    ]


def _agent_items(
    project: Project, held: HeldOut, work_id: str | None = None
) -> list[ReferenceItem]:
    """The items an agent may see: entries cited from a held-out work are left out; a link that
    touches a held-out work is shown as an unresolved entry."""
    return [
        _masked(i) if _hidden(i, held) else i
        for i in _all_items(project, work_id)
        if not held.hides(i.citing_work)
    ]


def list_references(
    project: Project,
    *,
    state: LinkState | None,
    work_id: str | None,
    after: int,
    limit: int,
    held_out: HeldOut | None = None,
) -> Page:
    """Entries of the live extractions with their links, by citing work, extraction and ordinal.

    `after` is the number of matching items already seen; `limit` is 1..`MAX_PAGE`. With
    `held_out` (agent views) the held-out works are hidden before filtering and counting.
    """
    issues: list[ValidationIssue] = []
    if not 1 <= limit <= MAX_PAGE:
        issues.append(ValidationIssue("limit", f"between 1 and {MAX_PAGE}"))
    if after < 0:
        issues.append(ValidationIssue("after", "must not be negative"))
    if issues:
        raise FactoryValidationError(issues)
    everything = (
        _all_items(project, work_id)
        if held_out is None
        else _agent_items(project, held_out, work_id)
    )
    rows = [i for i in everything if state is None or i.state is state]
    page = rows[after : after + limit]
    end = after + len(page)
    return Page(items=page, total=len(rows), next_after=end if end < len(rows) else None)
