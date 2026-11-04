"""Due and window computation over cycle views: pure, on a fixed clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from factory.living.due import CycleView, consecutive_failures, due_sources, next_due
from factory.living.window import is_full_replay, window_spec, window_start
from factory.model.protocol import PlannedQuery
from factory.model.search import QueryKind, QueryPurpose
from factory.model.watch import CycleStatus, WatchPlan, WatchSource

T0 = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


def _cycle(
    n: int,
    *,
    sources: tuple[str, ...] = ("arxiv",),
    complete: tuple[str, ...] | None = None,
    full: tuple[str, ...] = (),
    status: CycleStatus | None = None,
    finished: bool = True,
) -> CycleView:
    done = sources if complete is None else complete
    started = T0 + timedelta(days=7 * n)
    return CycleView(
        cycle_id=f"wcy_{n}",
        started_at=started,
        finished_at=started + timedelta(hours=1) if finished else None,
        status=status or (CycleStatus.COMPLETE if done == sources else CycleStatus.PARTIAL),
        sources=sources,
        complete_sources=done,
        full_replay_sources=full,
    )


ARXIV = WatchSource(source="arxiv", interval_days=7)
OPENALEX = WatchSource(source="openalex", interval_days=30)
WINDOW3 = WatchSource(
    source="arxiv", interval_days=7, mode="window", overlap_days=3, full_replay_every=3
)


def test_never_run_is_due_now() -> None:
    assert next_due(ARXIV, []) is None
    plan = WatchPlan(sources=(ARXIV, OPENALEX))
    assert due_sources(plan, [], T0) == ("arxiv", "openalex")


def test_due_after_interval_on_fixed_clock() -> None:
    cycles = [_cycle(0, sources=("arxiv", "openalex"))]
    finished = cycles[0].finished_at
    assert finished is not None
    assert next_due(ARXIV, cycles) == finished + timedelta(days=7)
    plan = WatchPlan(sources=(ARXIV, OPENALEX))
    assert due_sources(plan, cycles, finished + timedelta(days=6)) == ()
    assert due_sources(plan, cycles, finished + timedelta(days=7)) == ("arxiv",)
    assert due_sources(plan, cycles, finished + timedelta(days=30)) == ("arxiv", "openalex")


def test_open_cycle_does_not_advance_due() -> None:
    cycles = [_cycle(0, finished=False, status=CycleStatus.OPEN)]
    assert next_due(ARXIV, cycles) is None


def test_until_passed_nothing_due() -> None:
    plan = WatchPlan(sources=(ARXIV,), until=date(2026, 1, 10))
    assert due_sources(plan, [], datetime(2026, 1, 10, 23, tzinfo=UTC)) == ("arxiv",)
    assert due_sources(plan, [], datetime(2026, 1, 11, 0, tzinfo=UTC)) == ()


def test_window_start_skips_partial_cycles() -> None:
    c0 = _cycle(0)
    c1 = _cycle(1, complete=())  # partial: the source did not complete
    assert window_start(WINDOW3, [c0]) == (T0 - timedelta(days=3)).date()
    assert window_start(WINDOW3, [c0, c1]) == (T0 - timedelta(days=3)).date()
    assert window_start(WINDOW3, [c1]) is None
    assert window_start(WINDOW3, []) is None


def test_window_start_uses_cycle_start_not_finish() -> None:
    c = _cycle(2)
    assert window_start(WINDOW3, [c]) == (c.started_at - timedelta(days=3)).date()


def test_full_replay_every_three() -> None:
    cycles: list[CycleView] = []
    seen: list[bool] = []
    for n in range(7):
        full = is_full_replay(WINDOW3, cycles)
        seen.append(full)
        cycles.append(_cycle(n, full=("arxiv",) if full else ()))
    assert seen == [True, False, False, True, False, False, True]


def test_failed_full_replay_does_not_reset_the_count() -> None:
    cycles = [_cycle(0, full=("arxiv",)), _cycle(1), _cycle(2)]
    assert is_full_replay(WINDOW3, cycles)
    cycles.append(_cycle(3, complete=(), full=("arxiv",)))
    assert is_full_replay(WINDOW3, cycles)


def test_full_mode_is_always_full() -> None:
    assert is_full_replay(ARXIV, [_cycle(0)])


def test_window_spec_differs_only_by_listed_since() -> None:
    planned = PlannedQuery(
        source="arxiv", kind=QueryKind.KEYWORD, text="attention", filters={"year": "2020"}
    )
    spec = window_spec(planned, date(2026, 3, 1))
    assert spec.filters == {"year": "2020", "listed_since": "2026-03-01"}
    assert (spec.source, spec.kind, spec.text, spec.purpose) == (
        "arxiv",
        QueryKind.KEYWORD,
        "attention",
        QueryPurpose.SEARCH,
    )


def test_consecutive_failures_resets_on_complete() -> None:
    ok = _cycle(0)
    bad1 = _cycle(1, complete=())
    bad2 = _cycle(2, complete=(), status=CycleStatus.FAILED)
    assert consecutive_failures("arxiv", [ok]) == 0
    assert consecutive_failures("arxiv", [ok, bad1, bad2]) == 2
    assert consecutive_failures("arxiv", [ok, bad1, bad2, _cycle(3)]) == 0
    assert consecutive_failures("openalex", [ok, bad1, bad2]) == 0
    open_cycle = _cycle(4, finished=False, status=CycleStatus.OPEN, complete=())
    assert consecutive_failures("arxiv", [ok, bad1, open_cycle]) == 2
