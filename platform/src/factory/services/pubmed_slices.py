"""Date slicing of a capped PubMed query (IDEA-75; decision 124 item 2).

PubMed serves at most 9,999 records of one query, so a larger query is recorded `partial` with
the note `esearch-cap`. This service splits such a query by publication date (`[dp]`), by year,
then month, then day, until every slice counts at most the cap. The split is arithmetic on counts
that PubMed reports; the platform never judges which slice matters, and no model is involved.

Invariants:
- The slice terms are `(<parent text>) AND ("YYYY/MM/DD"[dp] : "YYYY/MM/DD"[dp])`, sent verbatim
  by the adapter, so each slice is an ordinary recorded search with its own archived pages and
  its own reported count (R-03, R-23).
- Slices of one split are disjoint and cover [1000/01/01, 3000/12/31], so a difference between
  the sum of the slice counts and the unsplit count can only be records PubMed holds without a
  `[dp]` date, or an index that moved between requests; the report states the difference.
- A day above the cap cannot be split further: it stays a slice, runs partial with the
  `esearch-cap` note, and is flagged `over_cap`.
- The parent/children relation is not stored. A child's text names its parent's text, so
  `slice_report` derives the relation from the registered queries; no event type is added.
- Planning counts are archived as blobs (hashes returned) but written as no event: the
  authoritative counts are those of the recorded slice runs.
- A slice is not a planned query: in a pilot or systematic project registering it needs
  `deviation_id`, a recorded deviation of the current protocol (the ordinary gate).
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.services.budgets import budget_issue, exhausted_unit
from factory.services.context import Project
from factory.services.search import RunSummary, register_query, run_query
from factory.sources.base import Prober, RawPage, SourceError
from factory.sources.registry import SourceFactory

CAP = 9999
"""The most records PubMed serves for one query (mirrors the adapter)."""
FIRST_YEAR = 1900
EARLIEST = date(1000, 1, 1)
LATEST = date(3000, 12, 31)
_STAMP = r'"(\d{4}/\d{2}/\d{2})"\[dp\] : "(\d{4}/\d{2}/\d{2})"\[dp\]'
_CHILD = re.compile(rf"^\((?P<parent>.*)\) AND \({_STAMP}\)$", re.DOTALL)

Counter = Callable[[str], int | None]


def _stamp(day: date) -> str:
    return f"{day.year:04d}/{day.month:02d}/{day.day:02d}"


def slice_term(parent_text: str, start: date, end: date) -> str:
    """The parent query restricted to publication dates from `start` to `end`, both inclusive."""
    return f'({parent_text}) AND ("{_stamp(start)}"[dp] : "{_stamp(end)}"[dp])'


def parse_slice(term: str) -> tuple[str, date, date] | None:
    """(parent text, start, end) of a slice term, or None when `term` is not one."""
    match = _CHILD.match(term)
    if match is None:
        return None
    try:
        start = date.fromisoformat(match.group(2).replace("/", "-"))
        end = date.fromisoformat(match.group(3).replace("/", "-"))
    except ValueError:
        return None
    return match.group("parent"), start, end


@dataclass(frozen=True)
class Window:
    """A closed date range and the granularity it was cut at."""

    start: date
    end: date
    unit: str  # "range" | "year" | "month" | "day"


def _is_year(w: Window) -> bool:
    return w.start == date(w.start.year, 1, 1) and w.end == date(w.start.year, 12, 31)


def _is_month(w: Window) -> bool:
    last = calendar.monthrange(w.start.year, w.start.month)[1]
    return w.start.day == 1 and w.end == date(w.start.year, w.start.month, last)


def finer(window: Window) -> list[Window]:
    """The next finer cut of `window`: a range into years, a year into months, a month into days.
    A day, or a range that is not whole years (the open ends), has no finer cut: `[]`."""
    if window.unit == "year":
        return [
            Window(
                date(window.start.year, m, 1),
                date(window.start.year, m, calendar.monthrange(window.start.year, m)[1]),
                "month",
            )
            for m in range(1, 13)
        ]
    if window.unit == "month":
        days = (window.end - window.start).days + 1
        return [
            Window(window.start + timedelta(d), window.start + timedelta(d), "day")
            for d in range(days)
        ]
    return []


def top_windows(first_year: int, last_year: int) -> list[Window]:
    """The first cut: everything before `first_year`, one window per year, everything after
    `last_year`. The two open ends are ranges and are never cut further."""
    years = [
        Window(date(y, 1, 1), date(y, 12, 31), "year") for y in range(first_year, last_year + 1)
    ]
    return [
        Window(EARLIEST, date(first_year - 1, 12, 31), "range"),
        *years,
        Window(date(last_year + 1, 1, 1), LATEST, "range"),
    ]


@dataclass(frozen=True)
class PlannedSlice:
    """One slice of the plan: its window, term, PubMed's count and whether it is above the cap."""

    window: Window
    term: str
    count: int

    @property
    def over_cap(self) -> bool:
        return self.count > CAP


@dataclass
class SlicePlan:
    """The slices that together cover a capped query, as counted at planning time."""

    parent_text: str
    parent_count: int
    slices: list[PlannedSlice] = field(default_factory=list)
    counts_requested: int = 0

    @property
    def total(self) -> int:
        return sum(s.count for s in self.slices)

    @property
    def runnable(self) -> list[PlannedSlice]:
        """The slices that hold records; an empty slice is counted but not run."""
        return [s for s in self.slices if s.count > 0]


def plan_slices(
    parent_text: str,
    parent_count: int,
    counter: Counter,
    *,
    first_year: int = FIRST_YEAR,
    last_year: int,
) -> SlicePlan:
    """Cut the query by year, then month, then day until each slice counts at most the cap.

    `counter(term)` is PubMed's count for a term (None when it gave none, which raises
    ValueError: a plan is never built on a guessed count). Arithmetic only; deterministic given
    the counts. Slices are returned in date order.
    """
    plan = SlicePlan(parent_text, parent_count)

    def visit(window: Window) -> None:
        term = slice_term(parent_text, window.start, window.end)
        count = counter(term)
        plan.counts_requested += 1
        if count is None:
            raise ValueError(f"PubMed gave no count for {term}")
        pieces = finer(window) if count > CAP else []
        if not pieces:
            plan.slices.append(PlannedSlice(window, term, count))
            return
        for piece in pieces:
            visit(piece)

    for window in top_windows(first_year, last_year):
        visit(window)
    return plan


class SliceReport(StrictModel):
    """The slices recorded for one parent query, against the parent's own count."""

    parent_query_id: str
    parent_reported: int | None
    children: list[ChildRow]
    slice_reported_total: int
    slice_retrieved_total: int
    difference: int | None
    note: str | None


class ChildRow(StrictModel):
    query_id: str
    start: date
    end: date
    status: str | None
    reported_count: int | None
    retrieved_count: int | None
    over_cap: bool


SliceReport.model_rebuild()


def slice_report(project: Project, parent_query_id: str) -> SliceReport:
    """The recorded slices of a query and the sum of their counts against the unsplit count.

    The relation is derived: a child is a registered PubMed keyword search whose text is
    `slice_term` of the parent's text. The difference (slice total minus unsplit count) is
    stated, never hidden (R-23); a slice with no finished run counts as nothing so far.
    """
    project.index.sync()
    with project.index.connect() as conn:
        parent = (
            conn.execute(
                text('SELECT source, kind, "text" FROM queries WHERE query_id = :q'),
                {"q": parent_query_id},
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            raise FactoryValidationError([ValidationIssue("query_id", "unknown query")])
        rows = (
            conn.execute(
                text(
                    'SELECT query_id, "text" FROM queries WHERE source = :s AND kind = :k '
                    "AND purpose = :p ORDER BY registered_at, query_id"
                ),
                {
                    "s": parent["source"],
                    "k": QueryKind.KEYWORD.value,
                    "p": QueryPurpose.SEARCH.value,
                },
            )
            .mappings()
            .all()
        )
        latest = _latest_runs(conn)
    parent_run = latest.get(parent_query_id)
    parent_reported = None if parent_run is None else parent_run["reported_count"]
    seen: dict[tuple[date, date], ChildRow] = {}
    for row in rows:
        parsed = parse_slice(str(row["text"]))
        if parsed is None or parsed[0] != str(parent["text"]):
            continue
        run = latest.get(str(row["query_id"]))
        reported = None if run is None else run["reported_count"]
        seen[(parsed[1], parsed[2])] = ChildRow(
            query_id=str(row["query_id"]),
            start=parsed[1],
            end=parsed[2],
            status=None if run is None else str(run["status"]),
            reported_count=reported,
            retrieved_count=None if run is None else run["retrieved_count"],
            over_cap=reported is not None and reported > CAP,
        )
    children = [seen[key] for key in sorted(seen)]
    reported_total = sum(c.reported_count or 0 for c in children)
    retrieved_total = sum(c.retrieved_count or 0 for c in children)
    difference = None if parent_reported is None else reported_total - int(parent_reported)
    note = None
    if difference:
        note = (
            f"slice counts total {reported_total} against {parent_reported} for the unsplit "
            f"query (difference {difference:+d}): records without a [dp] date, or an index that "
            "moved between requests"
        )
    return SliceReport(
        parent_query_id=parent_query_id,
        parent_reported=None if parent_reported is None else int(parent_reported),
        children=children,
        slice_reported_total=reported_total,
        slice_retrieved_total=retrieved_total,
        difference=difference,
        note=note,
    )


def _latest_runs(conn: Connection) -> dict[str, Mapping[str, Any]]:
    """Each query's latest run (by start time) as a mapping of the columns the report reads."""
    out: dict[str, Mapping[str, Any]] = {}
    for row in (
        conn.execute(
            text(
                "SELECT query_id, status, reported_count, retrieved_count, started_at, run_id "
                "FROM runs ORDER BY started_at, run_id"
            )
        )
        .mappings()
        .all()
    ):
        out[str(row["query_id"])] = dict(row)
    return out


def _parent_spec(project: Project, query_id: str) -> QuerySpec:
    """The registered query to split, or a refusal naming why it cannot be."""
    project.index.sync()
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text(
                    'SELECT source, kind, "text", purpose, filters FROM queries WHERE query_id = :q'
                ),
                {"q": query_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise FactoryValidationError([ValidationIssue("query_id", "unknown query")])
    issues: list[ValidationIssue] = []
    if row["source"] != "pubmed" or row["kind"] != QueryKind.KEYWORD.value:
        issues.append(ValidationIssue("query_id", "only a pubmed keyword query is sliced"))
    if row["purpose"] != QueryPurpose.SEARCH.value:
        issues.append(ValidationIssue("query_id", "only a search query is sliced"))
    if row["filters"] not in ("{}", "", None):
        issues.append(ValidationIssue("query_id", "a query with filters is not sliced"))
    if issues:
        raise FactoryValidationError(issues)
    return QuerySpec(source="pubmed", kind=QueryKind.KEYWORD, text=str(row["text"]))


def _count_counter(
    project: Project, sources: Mapping[str, SourceFactory], blobs: list[str]
) -> Counter:
    adapter = sources["pubmed"](project.settings, project.clock)
    if not isinstance(adapter, Prober):
        raise FactoryValidationError([ValidationIssue("source", "pubmed cannot count")])

    def archive(page: RawPage) -> str:
        ref = project.blobs.put(page.body.encode("utf-8"))
        blobs.append(ref)
        return ref

    def count(term: str) -> int | None:
        spent = exhausted_unit(project, project.principal, REQUESTS_SEARCH)
        if spent is not None:
            raise FactoryValidationError([budget_issue(spent)])
        spec = QuerySpec(source="pubmed", kind=QueryKind.KEYWORD, text=term)
        try:
            return adapter.count(spec, archive=archive)
        except SourceError as exc:
            raise FactoryValidationError([ValidationIssue("count", str(exc))]) from exc

    return count


def propose_slices(
    project: Project,
    query_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    first_year: int = FIRST_YEAR,
) -> SlicePlan:
    """Plan the date slices of a capped query: one esearch count per candidate slice, no record
    fetched, nothing recorded. Refused when the query is not a pubmed keyword search, or its
    unsplit count is within the cap (nothing to split)."""
    spec = _parent_spec(project, query_id)
    blobs: list[str] = []
    counter = _count_counter(project, sources, blobs)
    parent_count = counter(spec.text)
    if parent_count is None:
        raise FactoryValidationError([ValidationIssue("count", "PubMed gave no count")])
    if parent_count <= CAP:
        raise FactoryValidationError(
            [ValidationIssue("query_id", f"{parent_count} records are within the cap of {CAP}")]
        )
    last_year = project.clock.now().year
    try:
        return plan_slices(
            spec.text, parent_count, counter, first_year=first_year, last_year=last_year
        )
    except ValueError as exc:
        raise FactoryValidationError([ValidationIssue("count", str(exc))]) from exc


class SliceRunSummary(StrictModel):
    """What one slicing run did: the slices planned, the queries and runs, and the report."""

    parent_query_id: str
    slices_planned: int
    empty_slices: int
    over_cap_slices: int
    runs: list[RunSummary]
    report: SliceReport


def run_slices(
    project: Project,
    actor: Actor,
    query_id: str,
    *,
    sources: Mapping[str, SourceFactory],
    deviation_id: str | None = None,
    first_year: int = FIRST_YEAR,
) -> SliceRunSummary:
    """Plan the slices, register each non-empty one as its own search (the slice term verbatim)
    and run it. Re-running continues: a slice whose latest run completed is left alone, a partial
    run with a resume token is resumed, anything else runs again. Every slice is registered
    before the first run, so a refusal (protocol gate, unknown deviation) writes nothing."""
    plan = propose_slices(project, query_id, sources=sources, first_year=first_year)
    specs = [QuerySpec(source="pubmed", kind=QueryKind.KEYWORD, text=s.term) for s in plan.runnable]
    ids: list[str] = []
    for spec in specs:
        existing = _registered(project, spec.text)
        ids.append(
            existing
            or register_query(project, actor, spec, sources=sources, deviation_id=deviation_id)
        )
    runs: list[RunSummary] = []
    for slice_query in ids:
        status, run_id, token = _last_run(project, slice_query)
        if status == RunStatus.COMPLETE.value:
            continue
        resume = run_id if status == RunStatus.PARTIAL.value and token else None
        runs.append(
            run_query(project, slice_query, sources=sources, actor=actor, resume_run=resume)
        )
    return SliceRunSummary(
        parent_query_id=query_id,
        slices_planned=len(plan.slices),
        empty_slices=len(plan.slices) - len(plan.runnable),
        over_cap_slices=sum(1 for s in plan.slices if s.over_cap),
        runs=runs,
        report=slice_report(project, query_id),
    )


def _registered(project: Project, term: str) -> str | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                'SELECT query_id FROM queries WHERE source = :s AND kind = :k AND "text" = :t '
                "AND purpose = :p AND filters = '{}' ORDER BY registered_at, query_id"
            ),
            {
                "s": "pubmed",
                "k": QueryKind.KEYWORD.value,
                "t": term,
                "p": QueryPurpose.SEARCH.value,
            },
        ).first()
    return None if row is None else str(row[0])


def _last_run(project: Project, query_id: str) -> tuple[str | None, str | None, str | None]:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, run_id, resume_token FROM runs WHERE query_id = :q "
                "ORDER BY started_at DESC, run_id DESC"
            ),
            {"q": query_id},
        ).first()
    return (None, None, None) if row is None else (str(row[0]), str(row[1]), row[2])
