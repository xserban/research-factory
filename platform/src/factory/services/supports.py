"""Support resolution: is a typed reference eligible, and what does it say? (slice 7b, plan W-A).

Declares: `ResolvedSupport`, `resolve_supports`, `REASONS`. A reader of the index; it writes nothing
and reads no library file (R-47): quotes come from the extraction events' projection.

Invariants:
- A support is eligible only when it rests on verified material that is current: a live pass-A
  claim of an included work whose document is current; a cell of a visible final row whose sources
  are not stale; a live final contribution item; an edge whose effective status is `stated` or
  `confirmed`; a group with a visible row; a registered stat whose arguments resolve; an
  interpretation or concept a human reviewed, and only for an `interpretive` sentence.
- Every refusal reason is one of `REASONS`; none carries text of a document.
- `resolve_supports` returns one entry per reference, in order; an ineligible entry still carries
  what could be read (its works), never a quote.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.extraction.numbers import normalise_text, parse_printed
from factory.model.drafts import SentenceClass, SupportKind, SupportRef
from factory.model.intuition import ConceptState, ReviewState
from factory.model.lineage import DEFAULT_STATUSES, EdgeStatus
from factory.model.screening import PassLabel
from factory.references.match import surname_key
from factory.services.call_memo import entering
from factory.services.concepts import concept_view
from factory.services.context import Project
from factory.services.contributions import ItemView, final_items
from factory.services.extraction import stale_claims, stale_extractions
from factory.services.interpretations import interpretation_state
from factory.services.lineage import cites_status
from factory.services.notices import work_states
from factory.services.references import included_works
from factory.services.relations import relation_view
from factory.services.search import get_work
from factory.services.write_rows import visible_rows_by_group
from factory.writing.stats import compute_stat, group_of_stat

REASONS = (
    "unknown",
    "superseded",
    "stale",
    "not-included",
    "not-final",
    "inferred",
    "rejected",
    "unreviewed",
    "class-not-allowed",
)


@dataclass(frozen=True)
class ResolvedSupport:
    ref: SupportRef
    eligible: bool
    reason: str | None = None
    work_ids: tuple[str, ...] = ()
    spans: tuple[str, ...] = ()
    numbers: tuple[Decimal, ...] = ()
    group_ids: tuple[str, ...] = ()
    stat_value: int | None = None
    first_authors: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    method_names: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)
    """Read-only facts a slot shows (the field of a cell, the type of a claim)."""


class _Reader:
    """What the resolution reads once per call."""

    def __init__(self, project: Project) -> None:
        project.index.sync()
        self.project = project
        self.included = set(included_works(project))
        self.excluded = {w for w, s in work_states(project).items() if s.synthesis == "excluded"}
        self._items: dict[str, ItemView] | None = None
        self._stale_rows: set[str] | None = None
        self._stale_claims: set[str] | None = None

    def counts(self, work_id: str) -> bool:
        return work_id in self.included and work_id not in self.excluded

    def items(self) -> dict[str, ItemView]:
        if self._items is None:
            self._items = {
                s.extraction_id: i for i in final_items(self.project) for s in i.sources.values()
            }
        return self._items

    def stale_rows(self) -> set[str]:
        if self._stale_rows is None:
            self._stale_rows = stale_extractions(self.project)
        return self._stale_rows

    def stale_claim_ids(self) -> set[str]:
        if self._stale_claims is None:
            self._stale_claims = stale_claims(self.project)
        return self._stale_claims

    def work_facts(self, work_ids: Sequence[str]) -> tuple[tuple[str, ...], tuple[int, ...]]:
        authors: list[str] = []
        years: list[int] = []
        for work_id in work_ids:
            work = get_work(self.project, work_id)
            if work is None:
                continue
            if work.authors:
                key = surname_key(work.authors[0].name)
                if key:
                    authors.append(key)
            if work.dates.year is not None:
                years.append(work.dates.year)
        return tuple(authors), tuple(years)


def _refuse(ref: SupportRef, reason: str, works: Sequence[str] = ()) -> ResolvedSupport:
    return ResolvedSupport(ref=ref, eligible=False, reason=reason, work_ids=tuple(works))


def _numbers(*values: object) -> tuple[Decimal, ...]:
    found: list[Decimal] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, Decimal):
            found.append(value)
        else:
            parsed = parse_printed(str(value))
            if parsed is not None:
                found.append(parsed)
    return tuple(dict.fromkeys(found))


def resolve_supports(
    project: Project, refs: Sequence[SupportRef], *, cls: SentenceClass
) -> list[ResolvedSupport]:
    """One `ResolvedSupport` per reference, in order, for a sentence of class `cls`."""
    with entering():
        reader = _Reader(project)
        return [_resolve(reader, ref, cls) for ref in refs]


def _resolve(reader: _Reader, ref: SupportRef, cls: SentenceClass) -> ResolvedSupport:
    if ref.kind is SupportKind.INTERP:
        return _interp(reader, ref, cls)
    if ref.kind is SupportKind.CLAIM:
        return _claim(reader, ref)
    if ref.kind is SupportKind.CELL:
        return _cell(reader, ref)
    if ref.kind is SupportKind.ITEM:
        return _item(reader, ref)
    if ref.kind is SupportKind.EDGE:
        return _edge(reader, ref)
    if ref.kind is SupportKind.GROUP:
        return _group(reader, ref)
    return _stat(reader, ref)


def _with_facts(reader: _Reader, base: ResolvedSupport) -> ResolvedSupport:
    authors, years = reader.work_facts(base.work_ids)
    return ResolvedSupport(
        ref=base.ref,
        eligible=base.eligible,
        reason=base.reason,
        work_ids=base.work_ids,
        spans=base.spans,
        numbers=base.numbers,
        group_ids=base.group_ids,
        stat_value=base.stat_value,
        first_authors=authors,
        years=years,
        method_names=base.method_names,
        extra=base.extra,
    )


def _claim(reader: _Reader, ref: SupportRef) -> ResolvedSupport:
    with reader.project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT work_id, pass_label, superseded_by, quote, claim_type "
                "FROM extraction_claims WHERE claim_id = :c"
            ),
            {"c": ref.ref},
        ).first()
    if row is None:
        return _refuse(ref, "unknown")
    work, label, superseded, quote, claim_type = (
        str(row[0]),
        str(row[1]),
        row[2],
        str(row[3]),
        str(row[4]),
    )
    if superseded is not None:
        return _refuse(ref, "superseded", [work])
    if label != PassLabel.A.value:
        return _refuse(ref, "not-final", [work])
    if not reader.counts(work):
        return _refuse(ref, "not-included", [work])
    if ref.ref in reader.stale_claim_ids():
        return _refuse(ref, "stale", [work])
    return _with_facts(
        reader,
        ResolvedSupport(
            ref=ref,
            eligible=True,
            work_ids=(work,),
            spans=(quote,),
            extra={"claim_type": claim_type},
        ),
    )


def _cell(reader: _Reader, ref: SupportRef) -> ResolvedSupport:
    row_key, _, name = ref.ref.partition("/")
    found = visible_rows_by_group(reader.project).row(row_key)
    if found is None:
        with reader.project.index.connect() as conn:
            exists = conn.execute(
                text(
                    "SELECT work_id FROM extraction_rows WHERE row_key = :k AND scope = 'evidence'"
                ),
                {"k": row_key},
            ).first()
        if exists is None:
            return _refuse(ref, "unknown")
        work = str(exists[0])
        return _refuse(ref, "not-included" if not reader.counts(work) else "not-final", [work])
    row, gid = found
    if not reader.counts(row.work_id):
        return _refuse(ref, "not-included", [row.work_id])
    cell = row.fields.get(name)
    if cell is None:
        return _refuse(ref, "unknown", [row.work_id])
    if any(f.extraction_id in reader.stale_rows() for f in row.fields.values()):
        return _refuse(ref, "stale", [row.work_id])
    method = row.fields.get("method_name")
    return _with_facts(
        reader,
        ResolvedSupport(
            ref=ref,
            eligible=True,
            work_ids=(row.work_id,),
            spans=() if cell.quote is None else (cell.quote,),
            numbers=_numbers(cell.canonical, cell.value),
            group_ids=() if gid is None else (gid,),
            method_names=() if method is None else (normalise_text(str(method.value)),),
            extra={"field": name},
        ),
    )


def _item(reader: _Reader, ref: SupportRef) -> ResolvedSupport:
    with reader.project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT work_id, scope, superseded_by FROM extraction_rows WHERE extraction_id = :i"
            ),
            {"i": ref.ref},
        ).first()
    if row is None or str(row[1]) != "contribution":
        return _refuse(ref, "unknown")
    work = str(row[0])
    if row[2] is not None:
        return _refuse(ref, "superseded", [work])
    if not reader.counts(work):
        return _refuse(ref, "not-included", [work])
    item = reader.items().get(ref.ref)
    if item is None:
        return _refuse(ref, "not-final", [work])
    if item.stale:
        return _refuse(ref, "stale", [work])
    return _with_facts(
        reader,
        ResolvedSupport(
            ref=ref,
            eligible=True,
            work_ids=(work,),
            spans=() if item.quote is None else (item.quote,),
            numbers=_numbers(item.canonical, item.value),
            extra={"item_kind": item.item_kind},
        ),
    )


_EDGE_REASON = {
    EdgeStatus.INFERRED: "inferred",
    EdgeStatus.REJECTED: "rejected",
    EdgeStatus.STALE: "stale",
}


def _edge(reader: _Reader, ref: SupportRef) -> ResolvedSupport:
    cites = ref.ref.startswith("cit:")
    with reader.project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT source, target, base_status, decision, live, basis "
                "FROM graph_edges WHERE edge_id = :e"
            ),
            {"e": ref.ref},
        ).first()
    if row is None:
        return _refuse(ref, "unknown")
    source, target, base, decision, live, basis = row
    works = [str(source)] + ([str(target)] if str(target).startswith("rf:") else [])
    if not live:
        return _refuse(ref, "superseded", works)
    if cites:
        status = cites_status(str(base), None if decision is None else str(decision))
    else:
        view = relation_view(reader.project, ref.ref)
        if view is None:
            return _refuse(ref, "unknown", works)
        status = view.effective
    if status not in DEFAULT_STATUSES:
        return _refuse(ref, _EDGE_REASON[status], works)
    if not reader.counts(str(source)):
        return _refuse(ref, "not-included", works)
    quote: tuple[str, ...] = ()
    if basis is not None:
        item = reader.items().get(str(basis))
        if item is not None and item.quote is not None:
            quote = (item.quote,)
    return _with_facts(
        reader,
        ResolvedSupport(ref=ref, eligible=True, work_ids=tuple(works), spans=quote),
    )


def _group(reader: _Reader, ref: SupportRef) -> ResolvedSupport:
    visible = visible_rows_by_group(reader.project).groups
    if ref.ref not in visible:
        return _refuse(ref, "unknown")
    works = sorted({r.work_id for r in visible[ref.ref][1]})
    return _with_facts(
        reader,
        ResolvedSupport(ref=ref, eligible=True, work_ids=tuple(works), group_ids=(ref.ref,)),
    )


def _stat(reader: _Reader, ref: SupportRef) -> ResolvedSupport:
    kind, *args = ref.ref.split(":")
    try:
        value = compute_stat(reader.project, kind, args)
    except FactoryValidationError:
        return _refuse(ref, "unknown")
    gid = group_of_stat(kind, args)
    return ResolvedSupport(
        ref=ref,
        eligible=True,
        stat_value=value,
        numbers=(Decimal(value),),
        group_ids=() if gid is None else (gid,),
    )


def _interp(reader: _Reader, ref: SupportRef, cls: SentenceClass) -> ResolvedSupport:
    if ref.ref.startswith("int_"):
        state = interpretation_state(reader.project, ref.ref)
        if state is None:
            return _refuse(ref, "unknown")
        if state is ReviewState.SUPERSEDED:
            return _refuse(ref, "superseded")
        if state is ReviewState.WRONG:
            return _refuse(ref, "rejected")
        reviewed = state is ReviewState.REVIEWED
    else:
        view = concept_view(reader.project, ref.ref)
        if view is None:
            return _refuse(ref, "unknown")
        if view.review_state is ConceptState.MERGED:
            return _refuse(ref, "superseded")
        if view.review_state is ConceptState.WRONG:
            return _refuse(ref, "rejected")
        reviewed = view.review_state is ConceptState.REVIEWED
    if not reviewed:
        return _refuse(ref, "unreviewed")
    if cls is not SentenceClass.INTERPRETIVE:
        return _refuse(ref, "class-not-allowed")
    return ResolvedSupport(ref=ref, eligible=True)
