"""Watch cycles: runs, incremental dedup, counts recomputed from events, resume and locking."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.living.counts import source_counts
from factory.model.search import RunStatus
from factory.model.watch import CycleStatus, WatchCycleFinished
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project, open_project
from factory.services.dedup import active_merges, dedup_run
from factory.services.search import list_works
from factory.services.watch import CycleSummary, cycles, watch_run, watch_status
from tests.helpers import SESSION, SourcesFor
from tests.test_dedup_service import PREPRINT, PUBLISHED
from tests.watch_helpers import ScriptedSource, adapters, by_text, record, watch_ready

A = [record("Alpha methods for sparse graphs", author="Ana Li", year=2021)]
B = [record("Beta bounds on federated drift", author="Bo Chen", year=2022)]
C = [record("Gamma routing of experts", author="Cy Dee", year=2023)]


def _events(project: Project, type_: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == type_]


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _run(project: Project, source: ScriptedSource, **kw: Any) -> CycleSummary | None:
    return watch_run(project, sources=adapters(source), trigger="scheduler", **kw)


@pytest.fixture
def ready(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    watch_ready(project, agent, human, mock_sources)
    return project


def test_cycle_runs_every_planned_query_of_due_sources(ready: Project) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    summary = _run(ready, source)
    assert summary is not None and summary.status is CycleStatus.COMPLETE
    assert [s.text for s in source.specs] == ["attention", "transformers"]
    [started] = _events(ready, "watch.cycle_started")
    [finished] = _events(ready, "watch.cycle_finished")
    assert started.payload["trigger"] == "scheduler"
    assert started.payload["sources"][0]["source"] == "openalex"
    assert started.refs[0] == summary.cycle_id
    run_starts = [e for e in _events(ready, "search.run_started") if e.refs[-1].startswith("wcy_")]
    assert [e.refs[-1] for e in run_starts] == [summary.cycle_id, summary.cycle_id]
    assert finished.payload["run_ids"] == [e.refs[0] for e in run_starts]
    assert summary.run_ids == tuple(finished.payload["run_ids"])
    [counts] = summary.counts
    assert (counts.runs, counts.complete_runs, counts.retrieved, counts.new_works) == (2, 2, 2, 2)
    assert counts.disappeared == 0 and counts.window_missed is None
    assert len(summary.new_work_ids) == 2
    # Full queries reuse the registered query ids on a second replay.
    ready.clock.advance(timedelta(days=8))  # type: ignore[attr-defined]
    before = len(_events(ready, "query.registered"))
    assert _run(ready, source) is not None
    assert len(_events(ready, "query.registered")) == before


def test_nothing_due_writes_nothing(ready: Project, clock: FixedClock) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    assert _run(ready, source) is not None
    before = _count(ready)
    clock.advance(timedelta(days=3))
    assert _run(ready, source) is None
    assert _count(ready) == before
    assert len(source.specs) == 2


def test_cycle_counts_recompute(ready: Project, clock: FixedClock) -> None:
    source = ScriptedSource(by_text({"attention": [A + B], "transformers": [B + C]}))
    first = _run(ready, source)
    assert first is not None
    [finished] = _events(ready, "watch.cycle_finished")
    recorded = WatchCycleFinished.model_validate(finished.payload).counts
    assert source_counts(ready, first.cycle_id) == recorded == first.counts
    assert recorded[0].new_works == 3 and recorded[0].retrieved == 4

    clock.advance(timedelta(days=8))
    second = _run(ready, source)
    assert second is not None and second.counts[0].new_works == 0
    # Later cycles add provenance to the same works; the first cycle's counts do not move.
    assert source_counts(ready, first.cycle_id) == recorded


def test_failed_run_makes_cycle_partial_and_others_run(ready: Project) -> None:
    source = ScriptedSource(lambda n, spec: "fail" if n == 0 else [B])
    summary = _run(ready, source)
    assert summary is not None and summary.status is CycleStatus.PARTIAL
    assert len(source.specs) == 2
    [counts] = summary.counts
    assert (counts.runs, counts.complete_runs) == (2, 1) and not counts.complete
    assert counts.disappeared is None
    view = cycles(ready)[0]
    assert view.complete_sources == () and view.status is CycleStatus.PARTIAL


def test_all_runs_failed_makes_cycle_failed(ready: Project) -> None:
    summary = _run(ready, ScriptedSource(lambda _n, _s: "fail"))
    assert summary is not None and summary.status is CycleStatus.FAILED


def _crash_before_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("process died")

    monkeypatch.setattr("factory.services.watch._finish", boom)


def test_open_cycle_resumed_not_doubled(ready: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    source = ScriptedSource(lambda n, _s: [A] if n == 0 else "fail")
    with monkeypatch.context() as patch:
        _crash_before_finish(patch)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError):
            _run(ready, source)
    [started] = _events(ready, "watch.cycle_started")
    assert _events(ready, "watch.cycle_finished") == []
    assert len(source.specs) == 2  # attention completed, transformers failed

    retry = ScriptedSource(lambda _n, _s: [B])
    summary = _run(ready, retry)
    assert summary is not None and summary.cycle_id == started.payload["cycle_id"]
    assert [s.text for s in retry.specs] == ["transformers"]  # the completed query is skipped
    assert len(_events(ready, "watch.cycle_started")) == 1
    assert summary.status is CycleStatus.COMPLETE
    assert summary.counts[0].runs == 2 and summary.counts[0].complete_runs == 2


def test_abandoned_cycle_closed_partial(
    ready: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    with monkeypatch.context() as patch:
        _crash_before_finish(patch)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError):
            _run(ready, source)
    clock.advance(timedelta(hours=25))
    summary = _run(ready, source, force=True)
    [old, new] = cycles(ready)
    assert old.status is CycleStatus.PARTIAL and new.status is CycleStatus.COMPLETE
    first_finish = WatchCycleFinished.model_validate(
        _events(ready, "watch.cycle_finished")[0].payload
    )
    assert first_finish.note == "abandoned" and first_finish.status is CycleStatus.PARTIAL
    assert summary is not None and summary.cycle_id == new.cycle_id


def test_concurrent_runs_write_one_cycle(ready: Project, settings: Settings) -> None:
    barrier = threading.Barrier(2)
    results: list[CycleSummary | None] = []
    lock = threading.Lock()
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))

    def go() -> None:
        opened = open_project(settings, "demo", session=SESSION, clock=ready.clock)
        barrier.wait()
        summary = watch_run(opened, sources=adapters(source), trigger="scheduler")
        with lock:
            results.append(summary)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_events(ready, "watch.cycle_started")) == 1
    assert len(_events(ready, "watch.cycle_finished")) == 1
    assert sorted(r is None for r in results) == [False, True]
    assert len(source.specs) == 2


def test_refused_when_protocol_not_ready(project: Project) -> None:
    before = _count(project)
    with pytest.raises(FactoryValidationError) as raised:
        _run(project, ScriptedSource(lambda _n, _s: [[]]))
    assert [i.field for i in raised.value.issues] == ["protocol"]
    assert _count(project) == before


def test_refused_without_watch_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from tests.helpers import ready_protocol

    ready_protocol(project, agent, human, mock_sources)
    before = _count(project)
    with pytest.raises(FactoryValidationError) as raised:
        _run(project, ScriptedSource(lambda _n, _s: [[]]))
    assert [i.field for i in raised.value.issues] == ["watch_plan"]
    assert _count(project) == before


def test_refused_when_adapter_missing(ready: Project) -> None:
    before = _count(ready)
    with pytest.raises(FactoryValidationError) as raised:
        watch_run(ready, sources={}, trigger="scheduler")
    assert raised.value.issues[0].field == "sources"
    assert _count(ready) == before


def test_full_replay_reports_disappeared(ready: Project, clock: FixedClock) -> None:
    pages = {"first": {"attention": [A + B], "transformers": [[]]}, "second": {"attention": [A]}}
    first = _run(ready, ScriptedSource(by_text(pages["first"])))
    assert first is not None and first.counts[0].disappeared == 0
    clock.advance(timedelta(days=8))
    second = _run(ready, ScriptedSource(by_text({**pages["second"], "transformers": [[]]})))
    assert second is not None
    assert second.counts[0].disappeared == 1 and second.counts[0].new_works == 0
    assert len(list_works(ready)) == 2  # reported, never deleted


def test_new_works_are_pending(ready: Project) -> None:
    summary = _run(ready, ScriptedSource(by_text({"attention": [A + B], "transformers": [C]})))
    assert summary is not None and len(summary.new_work_ids) == 3
    outcomes = final_outcomes(ready)
    assert {outcomes[w] for w in summary.new_work_ids} == {Outcome.PENDING}


def test_new_records_are_deduplicated_incrementally(ready: Project) -> None:
    summary = _run(ready, ScriptedSource(by_text({"attention": [[PUBLISHED, PREPRINT]]})))
    assert summary is not None
    [merge] = active_merges(ready)
    assert {merge.primary, *merge.absorbed} == set(summary.new_work_ids)
    assert _events(ready, "dedup.merged")[0].actor.kind == "system"


def test_hooks_called_once_with_new_ids(ready: Project) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def hook(project: Project, cycle_id: str, new: tuple[str, ...]) -> tuple[str, ...]:
        seen.append((cycle_id, new))
        return ()

    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    summary = _run(ready, source, after_runs=[hook])
    assert summary is not None and summary.status is CycleStatus.COMPLETE
    assert seen == [(summary.cycle_id, summary.new_work_ids)]


def test_failing_hook_makes_cycle_partial(ready: Project) -> None:
    def broken(_p: Project, _c: str, _n: tuple[str, ...]) -> tuple[str, ...]:
        raise RuntimeError("no")

    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    summary = _run(ready, source, after_runs=[broken])
    assert summary is not None and summary.status is CycleStatus.PARTIAL
    [finished] = _events(ready, "watch.cycle_finished")
    assert "broken" in str(finished.payload["note"])
    assert summary.counts[0].complete


def test_hook_run_ids_are_recorded(ready: Project) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    summary = _run(ready, source, after_runs=[lambda _p, _c, _n: ("run_X",)])
    assert summary is not None
    [finished] = _events(ready, "watch.cycle_finished")
    assert finished.payload["status_run_ids"] == ["run_X"]


def test_force_runs_sources_that_are_not_due(ready: Project, clock: FixedClock) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    assert _run(ready, source) is not None
    clock.advance(timedelta(days=1))
    assert _run(ready, source) is None
    forced = _run(ready, source, force=True)
    assert forced is not None and len(_events(ready, "watch.cycle_started")) == 2


def test_agent_trigger_is_recorded_with_its_input(ready: Project, agent: Actor) -> None:
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    summary = watch_run(ready, sources=adapters(source), trigger="agent", actor=agent)
    assert summary is not None
    [started] = _events(ready, "watch.cycle_started")
    assert started.actor.kind == "agent" and started.actor.model == agent.model
    assert started.input_blob is not None
    run_starts = [e for e in _events(ready, "search.run_started") if e.refs[-1].startswith("wcy_")]
    assert {e.actor.kind for e in run_starts} == {"agent"}
    assert _events(ready, "watch.cycle_finished")[0].actor.kind == "system"


def test_watch_status(ready: Project, clock: FixedClock) -> None:
    status = watch_status(ready)
    [row] = status.sources
    assert status.has_plan and row.due and row.next_due is None and row.last_cycle is None
    summary = _run(ready, ScriptedSource(by_text({"attention": [A], "transformers": [B]})))
    assert summary is not None
    after = watch_status(ready).sources[0]
    assert not after.due and after.last_cycle == summary.cycle_id
    assert after.next_due is not None and after.consecutive_failures == 0
    clock.advance(timedelta(days=8))
    assert watch_status(ready).sources[0].due


def test_rebuild_identical_watch_tables(ready: Project, clock: FixedClock) -> None:
    source = ScriptedSource(
        by_text({"attention": [A + B], "transformers": [[PUBLISHED, PREPRINT]]})
    )
    assert _run(ready, source) is not None
    clock.advance(timedelta(days=8))
    assert (
        _run(ready, ScriptedSource(by_text({"attention": [A], "transformers": "fail"}))) is not None
    )  # type: ignore[dict-item]
    assert ready.index.state_hash() == ready.index.rebuild()
    assert RunStatus.COMPLETE


# --- dedup covers every returned work and carries forward unreconciled cycles ---

DOI_A = record("Sparse routing for experts", author="Ana Li", year=2024, doi="10.1/a")
OPENALEX_B = {"title": "A different paper", "authors": ["Bo Chen"], "year": 2020, "openalex": "W9"}


def test_identifier_added_to_known_work_is_deduplicated(ready: Project, clock: FixedClock) -> None:
    first = _run(ready, ScriptedSource(by_text({"attention": [[DOI_A, OPENALEX_B]]})))
    assert first is not None and active_merges(ready) == []
    clock.advance(timedelta(days=8))
    again = {**DOI_A, "openalex": "W9"}
    second = _run(ready, ScriptedSource(by_text({"attention": [[again]]})))
    assert second is not None and second.new_work_ids == ()
    assert len(active_merges(ready)) == 1
    before = _count(ready)
    assert dedup_run(ready).created == []
    assert _count(ready) == before


def test_failed_dedup_is_carried_to_the_next_cycle(
    ready: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("dedup died")

    dup = {**record("Sparse routing, revisited", author="Cy Dee", year=2023), "doi": "10.1/a"}
    with monkeypatch.context() as patch:
        patch.setattr("factory.services.watch.dedup_new", broken)
        one = _run(ready, ScriptedSource(by_text({"attention": [[DOI_A, dup]]})))
    assert one is not None and one.status is CycleStatus.PARTIAL
    assert active_merges(ready) == []
    clock.advance(timedelta(days=8))
    two = _run(ready, ScriptedSource(by_text({"attention": [[OPENALEX_B]]})))
    assert two is not None and two.status is CycleStatus.COMPLETE
    assert len(active_merges(ready)) == 1  # the earlier cycle's works were reconciled
    payloads = [e.payload for e in _events(ready, "watch.cycle_finished")]
    finished = [WatchCycleFinished.model_validate(p) for p in payloads]
    assert [f.dedup_complete for f in finished] == [False, True]
    assert finished[1].reconciled == (one.cycle_id,)
    clock.advance(timedelta(days=8))
    assert _run(ready, ScriptedSource(by_text({"attention": [[OPENALEX_B]]}))) is not None
    last = WatchCycleFinished.model_validate(_events(ready, "watch.cycle_finished")[-1].payload)
    assert last.reconciled == ()  # nothing left to carry


def test_abandoned_cycle_works_are_reconciled_by_the_next(
    ready: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def killed(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    dup = {**record("Sparse routing, revisited", author="Cy Dee", year=2023), "doi": "10.1/a"}
    with monkeypatch.context() as patch:
        patch.setattr("factory.services.watch.dedup_new", killed)
        with pytest.raises(KeyboardInterrupt):
            _run(ready, ScriptedSource(by_text({"attention": [[DOI_A, dup]]})))
    clock.advance(timedelta(hours=25))
    two = _run(ready, ScriptedSource(by_text({"attention": [[OPENALEX_B]]})))
    assert two is not None
    assert len(active_merges(ready)) == 1
    old = cycles(ready)[0]
    assert old.status is CycleStatus.PARTIAL
    last = WatchCycleFinished.model_validate(_events(ready, "watch.cycle_finished")[-1].payload)
    assert last.reconciled == (old.cycle_id,)
