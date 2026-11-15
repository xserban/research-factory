"""Window anchoring and full replays only on request (decision 127). Written with testing paused."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.living.due import CycleView
from factory.living.window import is_full_replay, window_start
from factory.model.watch import CycleStatus, WatchSource
from factory.services.context import Project
from factory.services.watch import watch_run
from tests.helpers import SourcesFor
from tests.watch_helpers import watch_ready, window_plan

BASELINE = date(2026, 10, 1)


def _cycle(day: int, *, full: bool = False) -> CycleView:
    started = datetime(2026, 11, day, 9, 0, tzinfo=UTC)
    return CycleView(
        cycle_id=f"wcy_{day}",
        started_at=started,
        finished_at=started + timedelta(hours=1),
        status=CycleStatus.COMPLETE,
        sources=("arxiv",),
        complete_sources=("arxiv",),
        full_replay_sources=("arxiv",) if full else (),
        protocol_id="P@00000000",
    )


def _source(every: int | None) -> WatchSource:
    return WatchSource(
        source="arxiv", interval_days=7, mode="window", overlap_days=3, full_replay_every=every
    )


def test_baseline_anchors_first_window() -> None:
    source = _source(52)
    assert not is_full_replay(source, [], BASELINE)
    assert window_start(source, [], BASELINE) == BASELINE - timedelta(days=3)


def test_no_cycle_and_no_baseline_is_full() -> None:
    assert is_full_replay(_source(None), [], None)
    assert is_full_replay(_source(52), [], None)
    assert window_start(_source(None), [], None) is None


def test_complete_cycle_beats_baseline() -> None:
    cycles = [_cycle(1)]
    assert window_start(_source(None), cycles, BASELINE) == date(2026, 10, 29)


def test_none_every_is_never_full_after_first() -> None:
    source = _source(None)
    cycles = [_cycle(day) for day in (1, 8, 15, 22)]
    assert not is_full_replay(source, cycles, None)
    assert not is_full_replay(source, cycles, BASELINE)
    assert not is_full_replay(source, [], BASELINE)


def test_requested_is_full() -> None:
    assert is_full_replay(_source(None), [_cycle(1)], BASELINE, requested=True)
    assert is_full_replay(_source(52), [_cycle(1, full=True)], BASELINE, requested=True)


def test_full_mode_unchanged() -> None:
    source = WatchSource(source="arxiv", interval_days=7, mode="full")
    assert is_full_replay(source, [_cycle(1)], BASELINE)


def test_every_set_keeps_old_rule() -> None:
    source = _source(3)
    assert is_full_replay(source, [_cycle(1)], None)  # no complete full replay yet
    cycles = [_cycle(1, full=True), _cycle(8)]
    assert not is_full_replay(source, cycles[:1], None)
    assert is_full_replay(source, [*cycles, _cycle(15)], None)  # two windows since the replay


def test_full_replay_request_refused_for_agent(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    watch_ready(project, agent, human, mock_sources, plan=window_plan())
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as exc:
        watch_run(project, sources={}, trigger="agent", actor=agent, full_replay=True)
    assert "full_replay" in [i.field for i in exc.value.issues]
    with pytest.raises(FactoryValidationError):
        watch_run(project, sources={}, trigger="scheduler", full_replay=True)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
