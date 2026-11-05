"""Coverage of an imported library by the systematic search (slice 3d ruling 25; plan Import-C).

A builder: it reads the import projection, provenance, queries, the protocol's sources and limits
and the final outcomes, and returns values. It writes no event.

`record_coverage` puts each resolved record of an import in exactly one bucket:

| bucket | rule |
| --- | --- |
| `found-database` | its work has `database` provenance from a search-purpose query |
| `found-supplementary` | else `citation-chase`, `seed-admission` or `hand-search` provenance |
| `outside-limits` | not found; its fields violate a protocol limit |
| `query-miss` | not found; within limits; a declared source returned the work |
| `source-unchecked` | not found; within limits; a declared source was not asked about it |
| `not-in-sources` | not found; within limits; every declared source was asked and had nothing |

`coverage_report` adds the figures per part (development and held-out when a split was drawn, else
one `unsplit` part). Search sensitivity is `found-database / (found-database +
found-supplementary + query-miss)` and corpus coverage `(found-database + found-supplementary) /
resolved`, each with numerator and denominator and `None` for a zero denominator (R-05).
Term suggestions come from the development (or unsplit) `query-miss` works only.

Invariants:
- `library-import` provenance (the admission of the import itself) and `supplied` provenance never
  make a record found, and probe-purpose provenance is a lookup, not a find.
- A record's work is its resolved or confirmed work, mapped through active merges to the merge
  group's primary. Records of one canonical work count once per import, at the lowest ordinal.
- Unresolved and unconfirmed records are omitted from the bucketed list; the report counts them.
  Malformed records are not records of the library and are not counted.
- "A declared source was asked" is read from how the resolver looks a record up: an arXiv id asks
  arXiv (then OpenAlex for a plain DOI the record also states, when arXiv returned nothing); a
  DOI asks OpenAlex; a title with neither asks OpenAlex. A record resolved in the corpus without
  a lookup asked no source.
- Records are read in ordinal ranges of `CHUNK`; only the bucketed output and the set of seen
  canonical works are held for the whole import.
- No text of a document or a record is returned beyond ids and counts.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, get_args

from pydantic import TypeAdapter
from sqlalchemy import bindparam, text

from factory.imports.limits import outside_limits
from factory.imports.model import ImportFields, ImportFormat, ImportRole, ParseOutcome, RecordType
from factory.model.base import StrictModel
from factory.model.probe import TermSuggestion
from factory.model.protocol import Limit
from factory.model.references import LinkState
from factory.model.search import QueryPurpose
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, exclusion_criteria, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.imports import import_row, list_imports
from factory.services.protocol import ProtocolVersion, current_protocol
from factory.services.reference_resolve import (
    LOOKUP_IDENTIFIER,
    LOOKUP_TITLE,
    NO_SOURCE_RECORD,
    _keys,
)
from factory.services.search import get_work
from factory.services.seeds import held_out_work_ids
from factory.services.vocabulary import suggest_terms
from factory.sources.importlist import NAME as IMPORTLIST

CHUNK = 2_000
_ID_CHUNK = 500
_OPENALEX = "openalex"
_ARXIV = "arxiv"
_SUPPLEMENTARY = frozenset(
    {
        ProvenanceMethod.CITATION_CHASE.value,
        ProvenanceMethod.SEED_ADMISSION.value,
        ProvenanceMethod.HAND_SEARCH.value,
    }
)
_RETURNED_PURPOSES = frozenset(
    {
        QueryPurpose.PROBE.value,
        QueryPurpose.IMPORT.value,
        QueryPurpose.SUPPLIED.value,
        QueryPurpose.SEARCH.value,
    }
)

_RECORD_TYPES = frozenset(get_args(RecordType))

Part = Literal["development", "held-out", "unsplit"]


class Bucket(StrEnum):
    FOUND_DATABASE = "found-database"
    FOUND_SUPPLEMENTARY = "found-supplementary"
    OUTSIDE_LIMITS = "outside-limits"
    NOT_IN_SOURCES = "not-in-sources"
    SOURCE_UNCHECKED = "source-unchecked"
    QUERY_MISS = "query-miss"


NOT_FOUND = (
    Bucket.OUTSIDE_LIMITS,
    Bucket.NOT_IN_SOURCES,
    Bucket.SOURCE_UNCHECKED,
    Bucket.QUERY_MISS,
)
FOUND = (Bucket.FOUND_DATABASE, Bucket.FOUND_SUPPLEMENTARY)


class RecordCoverage(StrictModel):
    """One resolved record of an import and the bucket it falls in."""

    ordinal: int
    work_id: str
    part: Part
    bucket: Bucket
    limits_violated: list[str]
    sources_found: list[str]
    """Real sources (not the offline import list) that returned the work, sorted."""
    outcome: Outcome | None
    """The screening outcome of a found record's work; None for a record that was not found."""
    excluded_by: list[str]
    """The criterion a found, excluded record is excluded under (bare id); empty otherwise."""


class Ratio(StrictModel):
    """A figure with its numerator and denominator; reported together, never alone (R-05)."""

    numerator: int
    denominator: int
    value: float


class PartCoverage(StrictModel):
    """Coverage of one part of an import: counts per bucket and the two figures."""

    part: Part
    counts: dict[Bucket, int]
    unresolved: int
    unconfirmed: int
    resolved: int
    sensitivity: Ratio | None
    coverage: Ratio | None
    outcomes: dict[str, int]
    """Screening outcome counts of the found records (`included`, `excluded`, `pending`)."""
    excluded: list[str]
    """Work ids of found records excluded by screening: a list for the researcher, no verdict."""


CoverageLabel = Literal["held-out", "post-search", "optimistic"]


class CoverageReport(StrictModel):
    import_id: str
    label: CoverageLabel
    parts: list[PartCoverage]
    included_not_in_library: int | None
    """Included works absent from the import's resolved records; None when withheld."""
    suggestions: list[TermSuggestion]
    protocol_id: str | None
    as_of: str
    """The id of the last event the report reads."""


@dataclass(frozen=True)
class Classified:
    """The buckets of one import plus the records the buckets leave out, by part."""

    records: list[RecordCoverage]
    unresolved: dict[Part, int]
    unconfirmed: dict[Part, int]


@dataclass(frozen=True)
class _Row:
    ordinal: int
    part: Part
    link_state: str | None
    work_id: str | None
    method: str | None
    no_source_record: bool
    year: int | None
    type: str | None
    doi: str | None
    arxiv: str | None


@dataclass(frozen=True)
class _Prov:
    sources: frozenset[str]
    database: bool
    supplementary: bool


def record_coverage(project: Project, import_id: str) -> list[RecordCoverage]:
    """The bucketed resolved records of an import, in ordinal order."""
    return classify_import(project, import_id).records


def classify_import(
    project: Project, import_id: str, *, exclude_works: frozenset[str] = frozenset()
) -> Classified:
    """Buckets for the resolved records and counts for the unresolved and unconfirmed ones.

    A record whose work is in `exclude_works` (after merging) is left out of every count."""
    import_row(project, import_id)  # FactoryValidationError for an unknown import
    protocol = current_protocol(project)
    declared = (
        frozenset()
        if protocol is None
        else frozenset(s.name for s in protocol.spec.sources if s.included)
    )
    limits: Sequence[Limit] = () if protocol is None else protocol.spec.limits
    primary = {absorbed: m.primary for m in active_merges(project) for absorbed in m.absorbed}
    groups: dict[str, list[str]] = {}
    for absorbed, head in primary.items():
        groups.setdefault(head, []).append(absorbed)

    unresolved: dict[Part, int] = {"development": 0, "held-out": 0, "unsplit": 0}
    unconfirmed: dict[Part, int] = {"development": 0, "held-out": 0, "unsplit": 0}
    seen: set[str] = set()
    out: list[RecordCoverage] = []
    outcomes: Mapping[str, Outcome] | None = None
    criteria: Mapping[str, str | None] | None = None
    for chunk in _chunks(project, import_id):
        pending: list[tuple[_Row, str]] = []
        for row in chunk:
            state = row.link_state
            if state == LinkState.RESOLVED.value and row.work_id is not None:
                head = primary.get(row.work_id, row.work_id)
                if head in seen:
                    continue
                seen.add(head)
                if head in exclude_works or row.work_id in exclude_works:
                    continue
                pending.append((row, head))
            elif state in (LinkState.UNCONFIRMED.value, LinkState.AMBIGUOUS.value):
                unconfirmed[row.part] += 1
            else:
                unresolved[row.part] += 1
        if not pending:
            continue
        provenance = _provenance(project, {h for _, h in pending}, groups)
        for row, head in pending:
            prov = provenance.get(head, _Prov(frozenset(), False, False))
            fields = ImportFields(year=row.year, type=_record_type(row.type))
            violated = list(outside_limits(fields, limits))
            bucket = _bucket(row, prov, violated, declared)
            outcome: Outcome | None = None
            excluded: list[str] = []
            if bucket in FOUND:
                if outcomes is None:
                    outcomes = final_outcomes(project)
                    criteria = exclusion_criteria(project)
                assert criteria is not None
                members = (head, *groups.get(head, ()))
                outcome = next((outcomes[m] for m in members if m in outcomes), None)
                cited = next((criteria[m] for m in members if m in criteria), None)
                excluded = [cited] if outcome is Outcome.EXCLUDED and cited else []
            out.append(
                RecordCoverage(
                    ordinal=row.ordinal,
                    work_id=head,
                    part=row.part,
                    bucket=bucket,
                    limits_violated=violated,
                    sources_found=sorted(prov.sources),
                    outcome=outcome,
                    excluded_by=excluded,
                )
            )
    return Classified(records=out, unresolved=unresolved, unconfirmed=unconfirmed)


def _bucket(row: _Row, prov: _Prov, violated: list[str], declared: frozenset[str]) -> Bucket:
    if prov.database:
        return Bucket.FOUND_DATABASE
    if prov.supplementary:
        return Bucket.FOUND_SUPPLEMENTARY
    if violated:
        return Bucket.OUTSIDE_LIMITS
    if prov.sources & declared:
        return Bucket.QUERY_MISS
    if declared - _asked(row, prov.sources):
        return Bucket.SOURCE_UNCHECKED
    return Bucket.NOT_IN_SOURCES


def _asked(row: _Row, returned: frozenset[str]) -> frozenset[str]:
    """The sources the resolver asked about the record (see the module docstring)."""
    if row.method not in (LOOKUP_IDENTIFIER, NO_SOURCE_RECORD, LOOKUP_TITLE):
        return frozenset()
    arxiv, doi = _keys(row.doi, row.arxiv)
    if arxiv is None and doi is None:
        return frozenset({_OPENALEX})
    asked: set[str] = set()
    if arxiv is not None:
        asked.add(_ARXIV)
        if doi is not None and _ARXIV not in returned:
            asked.add(_OPENALEX)
    elif doi is not None:
        asked.add(_OPENALEX)
    return frozenset(asked)


def _record_type(value: str | None) -> RecordType:
    return TypeAdapter(RecordType).validate_python(value) if value in _RECORD_TYPES else "other"


def _chunks(project: Project, import_id: str) -> Iterator[list[_Row]]:
    """The non-malformed records of the import by ascending ordinal, `CHUNK` at a time."""
    last = 0
    while True:
        with project.index.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT ordinal, part, link_state, work_id, method, no_source_record, "
                        "year, type, doi, arxiv FROM import_records "
                        "WHERE import_id = :i AND ordinal > :last AND outcome != :malformed "
                        "ORDER BY ordinal LIMIT :n"
                    ),
                    {
                        "i": import_id,
                        "last": last,
                        "malformed": ParseOutcome.MALFORMED.value,
                        "n": CHUNK,
                    },
                )
                .mappings()
                .all()
            )
        if not rows:
            return
        last = int(rows[-1]["ordinal"])
        yield [
            _Row(
                ordinal=int(r["ordinal"]),
                part=_part(str(r["part"])),
                link_state=None if r["link_state"] is None else str(r["link_state"]),
                work_id=None if r["work_id"] is None else str(r["work_id"]),
                method=None if r["method"] is None else str(r["method"]),
                no_source_record=bool(r["no_source_record"]),
                year=None if r["year"] is None else int(r["year"]),
                type=None if r["type"] is None else str(r["type"]),
                doi=None if r["doi"] is None else str(r["doi"]),
                arxiv=None if r["arxiv"] is None else str(r["arxiv"]),
            )
            for r in rows
        ]


def _part(value: str) -> Part:
    if value == "development":
        return "development"
    if value == "held-out":
        return "held-out"
    return "unsplit"


def _provenance(
    project: Project, heads: set[str], groups: Mapping[str, list[str]]
) -> dict[str, _Prov]:
    """How the corpus came to hold each work (its merge group's provenance), by group head."""
    members: dict[str, str] = {}
    for head in heads:
        members[head] = head
        for absorbed in groups.get(head, ()):
            members[absorbed] = head
    ids = sorted(members)
    sources: dict[str, set[str]] = {}
    database: set[str] = set()
    supplementary: set[str] = set()
    statement = text(
        "SELECT p.work_id, p.source, p.method, q.purpose FROM provenance p "
        "JOIN queries q ON q.query_id = p.query_id WHERE p.work_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with project.index.connect() as conn:
        for start in range(0, len(ids), _ID_CHUNK):
            for work, source, method, purpose in conn.execute(
                statement, {"ids": ids[start : start + _ID_CHUNK]}
            ).all():
                head = members[str(work)]
                if str(source) != IMPORTLIST and str(purpose) in _RETURNED_PURPOSES:
                    sources.setdefault(head, set()).add(str(source))
                if str(method) == ProvenanceMethod.DATABASE.value and str(purpose) == (
                    QueryPurpose.SEARCH.value
                ):
                    database.add(head)
                elif str(method) in _SUPPLEMENTARY:
                    supplementary.add(head)
    return {
        head: _Prov(
            sources=frozenset(sources.get(head, ())),
            database=head in database,
            supplementary=head in supplementary,
        )
        for head in heads
    }


# --- The report ---


def coverage_report(
    project: Project, import_id: str, *, exclude_works: frozenset[str] = frozenset()
) -> CoverageReport:
    """The full report (the researcher's view): every part, every figure.

    `exclude_works` leaves those works out of every count and list (the agent view passes the
    held-out seeds' works, R-20).
    """
    row = import_row(project, import_id)
    classified = classify_import(project, import_id, exclude_works=exclude_works)
    drawn = row.split_mode == "drawn"
    label: CoverageLabel = (
        "held-out" if drawn else "post-search" if row.split_mode == "post-search" else "optimistic"
    )
    names: tuple[Part, ...] = ("development", "held-out") if drawn else ("unsplit",)
    parts = [_part_coverage(name, classified) for name in names]
    protocol = current_protocol(project)
    return CoverageReport(
        import_id=import_id,
        label=label,
        parts=parts,
        included_not_in_library=_included_not_in_library(project, classified, exclude_works),
        suggestions=_suggestions(project, classified, protocol),
        protocol_id=None if protocol is None else protocol.protocol_id,
        as_of=_last_event(project),
    )


def _part_coverage(part: Part, classified: Classified) -> PartCoverage:
    rows = [r for r in classified.records if r.part == part]
    counts = {bucket: sum(1 for r in rows if r.bucket is bucket) for bucket in Bucket}
    found = sum(counts[b] for b in FOUND)
    reached = found + counts[Bucket.QUERY_MISS]
    outcomes = dict.fromkeys((o.value for o in Outcome), 0)
    for r in rows:
        if r.bucket in FOUND:
            outcomes[(r.outcome or Outcome.PENDING).value] += 1
    return PartCoverage(
        part=part,
        counts=counts,
        unresolved=classified.unresolved[part],
        unconfirmed=classified.unconfirmed[part],
        resolved=len(rows),
        sensitivity=_ratio(counts[Bucket.FOUND_DATABASE], reached),
        coverage=_ratio(found, len(rows)),
        outcomes=outcomes,
        excluded=sorted(r.work_id for r in rows if r.outcome is Outcome.EXCLUDED),
    )


def _ratio(numerator: int, denominator: int) -> Ratio | None:
    if denominator == 0:
        return None
    return Ratio(numerator=numerator, denominator=denominator, value=numerator / denominator)


def _included_not_in_library(
    project: Project, classified: Classified, exclude_works: frozenset[str]
) -> int:
    """Included works (merge groups counted once) that no resolved record of the import names."""
    primary = {absorbed: m.primary for m in active_merges(project) for absorbed in m.absorbed}
    included = {
        primary.get(work, work)
        for work, outcome in final_outcomes(project).items()
        if outcome is Outcome.INCLUDED
    }
    included -= {primary.get(w, w) for w in exclude_works}
    return len(included - {r.work_id for r in classified.records})


def _suggestions(
    project: Project, classified: Classified, protocol: ProtocolVersion | None
) -> list[TermSuggestion]:
    """Term blocks the development (or unsplit) query misses share that the queries lack."""
    if protocol is None:
        return []
    missed_ids = [
        r.work_id
        for r in classified.records
        if r.bucket is Bucket.QUERY_MISS and r.part != "held-out"
    ]
    missed = [w for wid in missed_ids if (w := get_work(project, wid)) is not None]
    query = " ".join(q.text for q in protocol.spec.queries)
    return suggest_terms(missed, missed, query)


def _last_event(project: Project) -> str:
    project.index.sync()
    with project.index.connect() as conn:
        last = conn.execute(text("SELECT MAX(id) FROM events")).scalar_one_or_none()
    return "" if last is None else str(last)


# --- Agent view (decision 43) ---


def held_out_visible(project: Project) -> bool:
    """Whether held-out figures may be shown to an agent: a screening pass has been opened.
    Before then, a figure that includes the held-out part is a differential oracle."""
    project.index.sync()
    with project.index.connect() as conn:
        return conn.execute(text("SELECT 1 FROM passes LIMIT 1")).first() is not None


def agent_coverage(
    project: Project, import_id: str, *, held_out_works: frozenset[str] | None = None
) -> CoverageReport:
    """The report as an agent outside the passes may read it (decision 43; spec ruling 23).

    The development (or unsplit) part is always shown; the held-out part only once a screening
    pass has been opened, and then as figures only: its excluded-work list is dropped, so no work
    is named as a held-out record. Works a held-out seed resolves to are left out of every count
    (R-20). Before a pass is opened `included_not_in_library` is None, since it counts the whole
    library, held-out part included.
    """
    exclude = held_out_work_ids(project) if held_out_works is None else held_out_works
    report = coverage_report(project, import_id, exclude_works=exclude)
    visible = held_out_visible(project)
    parts = [
        p.model_copy(update={"excluded": []}) if p.part == "held-out" else p
        for p in report.parts
        if visible or p.part != "held-out"
    ]
    return report.model_copy(
        update={
            "parts": parts,
            "included_not_in_library": report.included_not_in_library if visible else None,
        }
    )


class ImportStatusRow(StrictModel):
    """One import as an agent may see it: the development (or unsplit) part only, no ordinal and
    no record total (a total would let a reader subtract and recover the held-out count)."""

    import_id: str
    format: ImportFormat
    role: ImportRole
    collection: str | None
    label: CoverageLabel | None
    """None while the import is unresolved."""
    states: dict[str, int] | None
    """Records by resolution state (`resolved`, `unconfirmed`, `unresolved`); None if unresolved."""
    buckets: dict[Bucket, int] | None


def agent_import_status(project: Project) -> list[ImportStatusRow]:
    """Every import, oldest first, as `ImportStatusRow`s (decision 43, spec ruling 23)."""
    resolved = set(resolved_import_ids(project))
    held = held_out_work_ids(project)
    rows: list[ImportStatusRow] = []
    for listing in list_imports(project):
        info = listing.row
        label: CoverageLabel | None = None
        states: dict[str, int] | None = None
        buckets: dict[Bucket, int] | None = None
        if info.import_id in resolved:
            report = agent_coverage(project, info.import_id, held_out_works=held)
            [part] = [p for p in report.parts if p.part != "held-out"]
            label, buckets = report.label, part.counts
            states = {
                "resolved": part.resolved,
                "unconfirmed": part.unconfirmed,
                "unresolved": part.unresolved,
            }
        rows.append(
            ImportStatusRow(
                import_id=info.import_id,
                format=info.format,
                role=info.role,
                collection=info.collection,
                label=label,
                states=states,
                buckets=buckets,
            )
        )
    return rows


def resolved_import_ids(project: Project) -> list[str]:
    """The imports that have been resolved (some record has a link state), oldest first."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT i.import_id FROM imports i WHERE EXISTS (SELECT 1 FROM import_records r "
                "WHERE r.import_id = i.import_id AND r.link_state IS NOT NULL) "
                "ORDER BY i.recorded_at, i.event_id"
            )
        ).all()
    return [str(r[0]) for r in rows]
