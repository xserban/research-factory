"""Date slicing of a capped PubMed query (IDEA-75): arithmetic on counts, offline."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from itertools import pairwise

import httpx
import pytest

from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.services import pubmed_slices
from factory.services.context import Project
from factory.services.pubmed_slices import (
    CAP,
    Window,
    finer,
    parse_slice,
    plan_slices,
    propose_slices,
    run_slices,
    slice_report,
    slice_term,
    top_windows,
)
from factory.services.search import register_query, run_query
from factory.sources import pubmed as pubmed_module
from factory.sources.pubmed import PubmedSource
from factory.sources.registry import SourceFactory
from tests.test_pubmed import article, efetch, esearch, make_source


def test_slice_term_is_parent_and_inclusive_dp_range() -> None:
    assert (
        slice_term("asthma[MeSH]", date(2020, 3, 1), date(2020, 3, 31))
        == '(asthma[MeSH]) AND ("2020/03/01"[dp] : "2020/03/31"[dp])'
    )


def test_parse_slice_round_trips_and_rejects_other_text() -> None:
    term = slice_term("a OR (b)", date(2020, 1, 1), date(2020, 12, 31))
    assert parse_slice(term) == ("a OR (b)", date(2020, 1, 1), date(2020, 12, 31))
    assert parse_slice("asthma[MeSH]") is None
    assert parse_slice('(x) AND ("2020/13/01"[dp] : "2020/13/02"[dp])') is None


def test_finer_cuts_year_into_months_and_month_into_days_exactly() -> None:
    year = Window(date(2024, 1, 1), date(2024, 12, 31), "year")
    months = finer(year)
    assert [m.start.month for m in months] == list(range(1, 13))
    assert months[1].end == date(2024, 2, 29)  # leap year
    days = finer(months[1])
    assert (
        len(days) == 29 and days[0].start == date(2024, 2, 1) and days[-1].end == date(2024, 2, 29)
    )
    assert finer(days[0]) == []


def test_top_windows_are_disjoint_and_cover_everything() -> None:
    windows = top_windows(2000, 2002)
    assert [w.unit for w in windows] == ["range", "year", "year", "year", "range"]
    for left, right in pairwise(windows):
        assert (right.start - left.end).days == 1
    assert windows[0].start == date(1000, 1, 1) and windows[-1].end == date(3000, 12, 31)


def _counter(
    per_year: dict[int, int], per_month: dict[tuple[int, int], int] | None = None
) -> tuple[Callable[[str], int | None], list[str]]:
    asked: list[str] = []

    def count(term: str) -> int | None:
        asked.append(term)
        parsed = parse_slice(term)
        assert parsed is not None
        _, start, end = parsed
        if start.year != end.year:
            return 0
        if (start.month, start.day) == (1, 1) and (end.month, end.day) == (12, 31):
            return per_year.get(start.year, 0)
        if per_month is not None and start.day == 1 and end.day >= 28:
            return per_month.get((start.year, start.month), 0)
        return 0

    return count, asked


def test_only_oversized_years_are_cut_further() -> None:
    count, asked = _counter({2020: 20000, 2021: 5}, {(2020, m): 1000 for m in range(1, 13)})
    plan = plan_slices("q", 20005, count, first_year=2020, last_year=2021)
    units = [s.window.unit for s in plan.slices]
    assert units.count("month") == 12 and units.count("year") == 1
    assert all(s.count <= CAP for s in plan.slices)
    assert plan.total == 12000 + 5
    assert plan.counts_requested == len(asked) == 2 + 2 + 12  # 2 ends, 2 years, 12 months


def test_a_dense_month_is_cut_into_days_and_a_day_above_the_cap_is_flagged() -> None:
    def count(term: str) -> int | None:
        parsed = parse_slice(term)
        assert parsed is not None
        _, start, end = parsed
        if start.year != 2020:
            return 0
        if start == end:
            return CAP + 1 if start == date(2020, 1, 5) else 10
        return 20000 if start.month == 1 else 0

    plan = plan_slices("q", 20000, count, first_year=2020, last_year=2020)
    over = [s for s in plan.slices if s.over_cap]
    assert [s.window.start for s in over] == [date(2020, 1, 5)]
    assert over[0].window.unit == "day"


def test_a_missing_count_raises_rather_than_guessing() -> None:
    import pytest

    with pytest.raises(ValueError, match="no count"):
        plan_slices("q", 20000, lambda _t: None, first_year=2020, last_year=2020)


# ---- service level: register and run each slice, derive the relation ---------------------------
MONTHS_2020 = {1: 6, 2: 6, 3: 6, 4: 6}


@pytest.fixture
def small_cap(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(pubmed_module, "_CAP", 10)
    monkeypatch.setattr(pubmed_slices, "CAP", 10)
    yield


def _world(parent_count: int) -> tuple[dict[str, SourceFactory], list[httpx.Request]]:
    seen: list[httpx.Request] = []
    pmids = iter(range(1, 10_000))

    def count_for(term: str) -> int:
        if term == "asthma":
            return parent_count
        parsed = parse_slice(term)
        assert parsed is not None
        _, start, end = parsed
        if (start.month, start.day, end.month, end.day) == (1, 1, 12, 31):
            return {2020: 24, 2021: 1}.get(start.year, 0)
        if start.year == 2020 and start.day == 1 and end.day >= 28 and start.month == end.month:
            return MONTHS_2020.get(start.month, 0)
        return 0

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, text=esearch(count_for(request.url.params["term"])))
        n = int(request.url.params["retmax"])
        body = efetch(*[article(str(p), f"Title {p}") for p in (next(pmids) for _ in range(n))])
        return httpx.Response(200, text=body)

    source = make_source(handler)
    factory = SourceFactory(
        PubmedSource.kinds,
        lambda _s, _c: source,
        probe_kinds=frozenset({QueryKind.KEYWORD}),
        window_filter=True,
    )
    return {"pubmed": factory}, seen


def _parent(project: Project, sources: dict[str, SourceFactory]) -> str:
    spec = QuerySpec(source="pubmed", kind=QueryKind.KEYWORD, text="asthma")
    return register_query(project, project.human_actor(), spec, sources=sources)


@pytest.mark.usefixtures("small_cap")
def test_propose_cuts_only_the_oversized_year_and_writes_nothing(explore_project: Project) -> None:
    sources, _ = _world(25)
    parent = _parent(explore_project, sources)
    before = len(read_all(explore_project.paths.events_dir, explore_project.catalog))
    plan = propose_slices(explore_project, parent, sources=sources, first_year=2020)
    assert plan.parent_count == 25
    assert [s.count for s in plan.runnable] == [6, 6, 6, 6, 1]
    assert plan.total == 25
    assert len(read_all(explore_project.paths.events_dir, explore_project.catalog)) == before


@pytest.mark.usefixtures("small_cap")
def test_a_query_within_the_cap_is_refused(explore_project: Project) -> None:
    sources, _ = _world(9)
    parent = _parent(explore_project, sources)
    with pytest.raises(FactoryValidationError, match="within the cap"):
        propose_slices(explore_project, parent, sources=sources, first_year=2020)


@pytest.mark.usefixtures("small_cap")
def test_only_a_pubmed_keyword_search_is_sliced(explore_project: Project) -> None:
    sources, _ = _world(25)
    spec = QuerySpec(source="pubmed", kind=QueryKind.ID_LIST, text="1,2")
    ident = register_query(explore_project, explore_project.human_actor(), spec, sources=sources)
    with pytest.raises(FactoryValidationError, match="keyword"):
        propose_slices(explore_project, ident, sources=sources)


@pytest.mark.usefixtures("small_cap")
def test_each_slice_is_its_own_recorded_search_and_the_sum_is_reported(
    explore_project: Project,
) -> None:
    sources, _ = _world(25)
    parent = _parent(explore_project, sources)
    capped = run_query(explore_project, parent, sources=sources)
    assert capped.status is RunStatus.PARTIAL and capped.note is not None
    assert capped.note.startswith("esearch-cap")

    summary = run_slices(
        explore_project, explore_project.human_actor(), parent, sources=sources, first_year=2020
    )
    assert len(summary.runs) == 5
    assert all(r.status is RunStatus.COMPLETE for r in summary.runs)
    report = summary.report
    assert [c.reported_count for c in report.children] == [6, 6, 6, 6, 1]
    assert report.slice_reported_total == 25 == report.parent_reported
    assert report.difference == 0 and report.note is None
    texts = {c.query_id for c in report.children}
    assert len(texts) == 5 and parent not in texts


@pytest.mark.usefixtures("small_cap")
def test_rerunning_leaves_completed_slices_alone(explore_project: Project) -> None:
    sources, _ = _world(25)
    parent = _parent(explore_project, sources)
    run_query(explore_project, parent, sources=sources)
    first = run_slices(
        explore_project, explore_project.human_actor(), parent, sources=sources, first_year=2020
    )
    again = run_slices(
        explore_project, explore_project.human_actor(), parent, sources=sources, first_year=2020
    )
    assert len(first.runs) == 5 and again.runs == []
    assert len(again.report.children) == 5


@pytest.mark.usefixtures("small_cap")
def test_a_count_difference_is_stated(explore_project: Project) -> None:
    sources, _ = _world(26)  # one record the slices cannot reach (no [dp] date)
    parent = _parent(explore_project, sources)
    run_query(explore_project, parent, sources=sources)
    summary = run_slices(
        explore_project, explore_project.human_actor(), parent, sources=sources, first_year=2020
    )
    assert summary.report.difference == -1
    assert summary.report.note is not None and "-1" in summary.report.note
    assert slice_report(explore_project, parent).difference == -1
