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
from factory.imports.model import ImportFields, ParseOutcome, RecordType
from factory.model.base import StrictModel
from factory.model.protocol import Limit
from factory.model.references import LinkState
from factory.model.search import QueryPurpose
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, exclusion_criteria, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.imports import import_row
from factory.services.protocol import current_protocol
from factory.services.reference_resolve import (
    LOOKUP_IDENTIFIER,
    LOOKUP_TITLE,
    NO_SOURCE_RECORD,
    _keys,
)
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


def classify_import(project: Project, import_id: str) -> Classified:
    """Buckets for the resolved records and counts for the unresolved and unconfirmed ones."""
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
