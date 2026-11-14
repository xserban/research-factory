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
  A named work with a current extraction refuses the call, writing nothing: extracting it again
  would change nothing but the extraction id, which would stale what cites it.
- No raw entry text is stored (ruling 14): entries carry the parsed fields and `entry_sha256`
  over the whitespace-normalised text of the entry's anchor. Title, venue and surname longer than
  the model bounds are truncated (flag `field-truncated`); an over-long DOI, arXiv id or URL is
  dropped, since a cut identifier is a wrong one (flag `field-dropped`).
- An agent's events carry `input_blob`: the request, the conversion and the entry hashes, never
  the bibliography text (decision 39; the blob store is tracked in git).
- An extraction is current while it is the live extraction of its work, pinned to the work's
  default conversion, with this parser version. A new extraction supersedes the earlier one and
  takes over the human decisions on its entries, recorded in `reference.resolved` (`carried`).
- `re_resolve` retries links of live extractions (a failed lookup, or an older `MATCHER_VERSION`)
  in one `reference.re_resolved` event per extraction. The extraction id stays, so nothing that
  cites the extraction goes stale; a link holding a decision or a proposal is left alone.
  With `only_identifiers` only entries stating a DOI or arXiv id are retried (identifier lookups,
  never a title search); the others wait for a later call.
- Counts are computed from the live extractions, in SQL; the link states sum to the entry count.
- Listing is paged in SQL with a fixed cap (`MAX_PAGE`).
- Nothing here knows the seeds: a held-out seed's work reads as any corpus work in every link,
  count and list (decisions 37 item 9, 81). The MCP layer scrubs seed ids and stated identifiers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from sqlalchemy import RowMapping, text

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
    RE_RESOLVE_STATES,
    BblInfo,
    CitationContext,
    CitationContextsRecorded,
    Decision,
    LinkState,
    ReferenceEntry,
    ReferenceExtracted,
    ReferenceReResolved,
    ReferenceResolved,
    re_resolvable,
)
from factory.model.search import QueryPurpose
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
from factory.services.reference_resolve import (
    Corpus,
    carried_decisions,
    entry_digest,
    entry_raw,
    load_corpus,
    resolve_entries,
)
from factory.services.screening import background_works
from factory.services.work_ref import resolve_work_id, resolve_work_ids
from factory.sources.registry import SourceFactory

MAX_PAGE = 100

SkipReason = Literal["not-included", "no-conversion", "library-missing", "no-extraction"]


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


class ReResolved(StrictModel):
    """One `reference.re_resolved`: the ordinals retried and the states they now hold."""

    extraction_id: str
    work_id: str
    ordinals: list[int]
    states: dict[LinkState, int]
    lookup_runs: list[str]


class ReResolveSummary(StrictModel):
    re_resolved: list[ReResolved]
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


def _extractable_works(project: Project) -> set[str]:
    """The included works, plus (when the current protocol's snowball plan has `background_sources`)
    the works kept as background (IDEA-47), so a backward round can use them."""
    works = set(included_works(project))
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.snowball_plan
    if plan is not None and plan.background_sources:
        works |= set(background_works(project))
    return works


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
    conversion and no current extraction). A malformed work id, or a named work whose current
    extraction already uses this conversion and parser version, refuses the call, writing nothing.
    """
    if work_ids is not None:
        bad = [w for w in work_ids if re.match(WORK_ID_RE, w) is None]
        if bad:
            raise FactoryValidationError(
                [ValidationIssue("work_ids", f"{w!r}: not a work id") for w in bad]
            )
    project.index.sync()
    if work_ids is not None:
        work_ids = resolve_work_ids(project, work_ids)
    included = _extractable_works(project)
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
        current = [w for w, _ in scope if current_extraction(project, w) is not None]
        if current:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "work_ids",
                        f"{w}: already extracted from this conversion with this parser version",
                    )
                    for w in current
                ]
            )
    results: list[ExtractionResult] = []
    corpus = load_corpus(project) if scope else Corpus()
    for work, conversion in scope:
        result = _extract_one(project, actor, work, conversion, sources=sources, corpus=corpus)
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


def _state_after(state: LinkState, carried: Decision | None) -> LinkState:
    """A link's state once a carried decision is folded in."""
    if carried is None:
        return state
    return LinkState.RESOLVED if carried is Decision.CONFIRM else LinkState.UNRESOLVED


_CELL_ANCHOR_RE = re.compile(r"^(t\d+)\.r\d+\.c\d+$")


def _citing_anchor(anchor: str) -> str:
    """The anchor a citation context is recorded against: a marker inside a table cell is
    recorded against its table, since a context names a paragraph-level anchor."""
    cell = _CELL_ANCHOR_RE.match(anchor)
    return cell.group(1) if cell else anchor


def _extract_one(
    project: Project,
    actor: Actor,
    work: str,
    conversion: ConversionRef,
    *,
    sources: Mapping[str, SourceFactory],
    corpus: Corpus,
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
    outcome = resolve_entries(project, actor, entries, sources=sources, corpus=corpus)

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
                citing_anchor=_citing_anchor(c.citing_anchor),
                entry=c.entry,
                marker=c.marker,
                method=c.method,
                state=c.state,
            )
            for c in contexts
        ),
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
    with project.index.exclusive():
        project.index.sync()
        carried = carried_decisions(project, work, entries, outcome.resolutions)
        resolved = ReferenceResolved(
            extraction_id=extraction_id,
            resolutions=outcome.resolutions,
            matcher_version=MATCHER_VERSION,
            lookup_runs=outcome.lookup_runs,
            carried=carried,
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
        project.record(events)
    decided = {c.ordinal: c.decision for c in carried}
    states = {state: 0 for state in LinkState}
    for r in outcome.resolutions:
        states[_state_after(r.state, decided.get(r.ordinal))] += 1
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


_LIVE = "JOIN reference_extractions x ON x.extraction_id = {t}.extraction_id AND x.live = 1"
_ENTRY_LINK = (
    "JOIN reference_links l ON l.extraction_id = n.extraction_id AND l.ordinal = n.ordinal"
)
_ENTRIES = f"FROM reference_entries n {_LIVE.format(t='n')} {_ENTRY_LINK}"
"""The entries of the live extractions (`n`, extraction `x`) with their links (`l`)."""


# --- Re-resolution ---


def _retryable(
    project: Project,
    work_ids: Sequence[str] | None,
    states: Sequence[str],
    *,
    only_identifiers: bool = False,
) -> dict[tuple[str, str], list[ReferenceEntry]]:
    """(extraction, citing work) -> the entries to retry, over the live extractions; with
    `only_identifiers`, only those stating a DOI or an arXiv id."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT x.extraction_id, x.work_id AS citing_work, l.base_state, l.reason, "
                    "l.matcher_version, l.decision, l.proposal, n.ordinal, n.anchor, n.label, "
                    "n.doi, n.arxiv, n.url, n.year, n.first_author, n.title, n.venue, "
                    f"n.entry_sha256 {_ENTRIES} ORDER BY x.work_id, n.ordinal"
                )
            )
            .mappings()
            .all()
        )
    named = None if work_ids is None else set(work_ids)
    found: dict[tuple[str, str], list[ReferenceEntry]] = {}
    for row in rows:
        selector = row["reason"] or row["base_state"]
        if (named is not None and row["citing_work"] not in named) or selector not in states:
            continue
        if not re_resolvable(
            reason=row["reason"],
            link_matcher=str(row["matcher_version"]),
            matcher=MATCHER_VERSION,
            decision=row["decision"],
            proposal=row["proposal"],
        ):
            continue
        if only_identifiers and row["doi"] is None and row["arxiv"] is None:
            continue
        entry = ReferenceEntry(
            ordinal=int(row["ordinal"]),
            anchor=str(row["anchor"]),
            label=row["label"],
            doi=row["doi"],
            arxiv=row["arxiv"],
            url=row["url"],
            year=row["year"],
            first_author=row["first_author"],
            title=row["title"],
            venue=row["venue"],
            entry_sha256=str(row["entry_sha256"]),
        )
        found.setdefault((str(row["extraction_id"]), str(row["citing_work"])), []).append(entry)
    return found


def _re_resolve_one(
    project: Project,
    actor: Actor,
    extraction_id: str,
    work: str,
    entries: Sequence[ReferenceEntry],
    *,
    sources: Mapping[str, SourceFactory],
    corpus: Corpus,
    states: Sequence[str],
    only_identifiers: bool = False,
) -> ReResolved | None:
    """Look the entries up, then write under the lock what is still retryable: a decision, or a
    new extraction, may have landed during the lookups. None when nothing is left to write."""
    outcome = resolve_entries(project, actor, entries, sources=sources, corpus=corpus)
    with project.index.exclusive():
        project.index.sync()
        still = _retryable(project, [work], states, only_identifiers=only_identifiers).get(
            (extraction_id, work), []
        )
        ordinals = {e.ordinal for e in still}
        resolutions = tuple(r for r in outcome.resolutions if r.ordinal in ordinals)
        if not resolutions:
            return None
        payload = ReferenceReResolved(
            extraction_id=extraction_id,
            resolutions=resolutions,
            matcher_version=MATCHER_VERSION,
            lookup_runs=outcome.lookup_runs,
            carried=carried_decisions(project, work, still, resolutions),
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "extraction_id": extraction_id,
                    "matcher_version": MATCHER_VERSION,
                    "ordinals": [r.ordinal for r in resolutions],
                    "states": list(states),
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "reference.re_resolved",
                    payload,
                    actor,
                    refs=(extraction_id, work),
                    input_blob=input_blob,
                )
            ]
        )
    decided = {c.ordinal: c.decision for c in payload.carried}
    counts = {state: 0 for state in LinkState}
    for r in resolutions:
        counts[_state_after(r.state, decided.get(r.ordinal))] += 1
    return ReResolved(
        extraction_id=extraction_id,
        work_id=work,
        ordinals=[r.ordinal for r in resolutions],
        states=counts,
        lookup_runs=list(outcome.lookup_runs),
    )


def re_resolve(
    project: Project,
    actor: Actor,
    *,
    work_ids: Sequence[str] | None = None,
    states: Sequence[str] = ("source-error",),
    sources: Mapping[str, SourceFactory],
    only_identifiers: bool = False,
) -> ReResolveSummary:
    """Resolve again the links of the live extractions selected by `states` (`RE_RESOLVE_STATES`:
    an unresolved reason, or a link state), in `work_ids` or everywhere.

    A selected link is retried when its lookup failed or a newer `MATCHER_VERSION` recorded it
    (`re_resolvable`), so a repeat with nothing to retry writes nothing. A malformed work id or an
    unknown state refuses the call, writing nothing; a named work with no live extraction is
    skipped with a reason. The entries are not parsed again: their stored fields are looked up.
    With `only_identifiers`, only entries with a DOI or arXiv id are retried, by identifier
    lookup; entries without one are left as recorded.
    """
    issues: list[ValidationIssue] = []
    if work_ids is not None:
        issues += [
            ValidationIssue("work_ids", f"{w!r}: not a work id")
            for w in work_ids
            if re.match(WORK_ID_RE, w) is None
        ]
    issues += [
        ValidationIssue("states", f"{s!r}: one of {sorted(RE_RESOLVE_STATES)}")
        for s in states
        if s not in RE_RESOLVE_STATES
    ]
    if issues:
        raise FactoryValidationError(issues)
    project.index.sync()
    with project.index.connect() as conn:
        extracted = {
            str(row[0])
            for row in conn.execute(
                text("SELECT work_id FROM reference_extractions WHERE live = 1")
            ).all()
        }
    skipped = [
        Skipped(work_id=w, reason="no-extraction")
        for w in dict.fromkeys(work_ids or ())
        if w not in extracted
    ]
    scope = _retryable(project, work_ids, states, only_identifiers=only_identifiers)
    corpus = load_corpus(project) if scope else Corpus()
    results = [
        result
        for (extraction_id, work), entries in scope.items()
        if (
            result := _re_resolve_one(
                project,
                actor,
                extraction_id,
                work,
                entries,
                sources=sources,
                corpus=corpus,
                states=states,
                only_identifiers=only_identifiers,
            )
        )
        is not None
    ]
    return ReResolveSummary(re_resolved=results, skipped=skipped)


# --- Counts and listing ---


def reference_counts(project: Project) -> ReferenceCounts:
    """Counts over the live extractions, in SQL; the four states sum to `entries`."""
    project.index.sync()
    params = {"resolved": LinkState.RESOLVED.value, "probe": QueryPurpose.PROBE.value}
    resolved = f"{_ENTRIES} WHERE l.state = :resolved AND l.work_id IS NOT NULL"
    with project.index.connect() as conn:
        extractions = conn.execute(
            text("SELECT COUNT(*) FROM reference_extractions x WHERE live = 1")
        ).scalar_one()
        by_state = conn.execute(text(f"SELECT l.state, COUNT(*) {_ENTRIES} GROUP BY 1")).all()
        no_source = conn.execute(
            text(f"SELECT COUNT(*) {resolved} AND l.no_source_record = 1"), params
        ).scalar_one()
        targets, in_corpus = conn.execute(
            text(
                "SELECT COUNT(*), COALESCE(SUM(t.work IN (SELECT work_id FROM provenance "
                "WHERE query_id NOT IN (SELECT query_id FROM queries WHERE purpose = :probe))), 0) "
                f"FROM (SELECT DISTINCT l.work_id AS work {resolved}) t"
            ),
            params,
        ).one()
    states = {state: 0 for state in LinkState}
    for state, count in by_state:
        states[LinkState(str(state))] = int(count)
    return ReferenceCounts(
        extractions=int(extractions),
        entries=sum(states.values()),
        resolved=states[LinkState.RESOLVED],
        unconfirmed=states[LinkState.UNCONFIRMED],
        ambiguous=states[LinkState.AMBIGUOUS],
        unresolved=states[LinkState.UNRESOLVED],
        no_source_record=int(no_source),
        in_corpus=int(in_corpus),
        new_candidates=int(targets) - int(in_corpus),
    )


def _item(row: RowMapping) -> ReferenceItem:
    return ReferenceItem(
        extraction_id=str(row["extraction_id"]),
        citing_work=str(row["citing_work"]),
        ordinal=int(row["ordinal"]),
        anchor=str(row["anchor"]),
        label=row["label"],
        title=row["title"],
        first_author=row["first_author"],
        year=row["year"],
        doi=row["doi"],
        arxiv=row["arxiv"],
        state=LinkState(str(row["state"])),
        work_id=row["work_id"],
        confidence=row["confidence"],
        method=row["method"],
        score=row["score"],
        candidates=[(str(c["work_id"]), float(c["score"])) for c in json.loads(row["candidates"])],
        reason=row["reason"],
        base_state=LinkState(str(row["base_state"])),
        base_work_id=row["base_work_id"],
        decision=row["decision"],
        confirmed_by=row["confirmed_by"],
        proposal=row["proposal"],
        no_source_record=bool(row["no_source_record"]),
    )


def list_references(
    project: Project,
    *,
    state: LinkState | None,
    work_id: str | None,
    after: int,
    limit: int,
) -> Page:
    """Entries of the live extractions with their links, by citing work, extraction and ordinal.

    `after` is the number of matching items already seen; `limit` is 1..`MAX_PAGE`. The page and
    the total are taken in SQL, so only the page's items are built.
    """
    issues: list[ValidationIssue] = []
    if not 1 <= limit <= MAX_PAGE:
        issues.append(ValidationIssue("limit", f"between 1 and {MAX_PAGE}"))
    if after < 0:
        issues.append(ValidationIssue("after", "must not be negative"))
    if issues:
        raise FactoryValidationError(issues)
    project.index.sync()
    if work_id is not None:
        work_id = resolve_work_id(project, work_id)
    scope = (
        f"{_ENTRIES} WHERE (:work IS NULL OR x.work_id = :work) "
        "AND (:state IS NULL OR l.state = :state)"
    )
    params: dict[str, object] = {
        "work": work_id,
        "state": None if state is None else state.value,
    }
    with project.index.connect() as conn:
        total = int(conn.execute(text(f"SELECT COUNT(*) {scope}"), params).scalar_one())
        rows = (
            conn.execute(
                text(
                    "SELECT n.extraction_id, x.work_id AS citing_work, n.ordinal, n.anchor, "
                    "n.label, n.title, n.first_author, n.year, n.doi, n.arxiv, l.state, "
                    "l.work_id, l.confidence, l.method, l.score, l.candidates, l.reason, "
                    "l.base_state, l.base_work_id, l.decision, l.confirmed_by, l.proposal, "
                    f"l.no_source_record {scope} "
                    "ORDER BY x.work_id, n.extraction_id, n.ordinal LIMIT :limit OFFSET :after"
                ),
                {**params, "limit": limit, "after": after},
            )
            .mappings()
            .all()
        )
    end = after + len(rows)
    return Page(
        items=[_item(row) for row in rows], total=total, next_after=end if end < total else None
    )
