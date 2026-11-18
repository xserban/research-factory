"""`services.activity` (IDEA-98): the claimed tasks, the open passes, the traces. Tasks are made
with the task service on a bare project; the miner totals are the status service's and are
replaced by a fixed listing, so what is checked here is the reading, not the miner."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.services import activity as activity_service
from factory.services.activity import (
    STALE_MINUTES,
    activity,
    activity_cached,
)
from factory.services.context import Project
from factory.services.mining import MineStatus
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    complete_task,
    create_tasks,
    release_task,
)
from tests.helpers import T0


def _mine(work: str, *, calibration: str | None = None, label: str = "A") -> dict[str, Any]:
    return {
        "pass_label": label,
        "miner": "m-claims",
        "version": 2,
        "calibration_id": calibration,
        "records": [{"work_id": work, "title": f"Title {work}"}],
    }


def _make(project: Project, kind: str, *contents: Any) -> list[str]:
    result = create_tasks(project, project.system_actor(), [TaskSpec(kind, c) for c in contents])
    assert not result.rejected
    return list(result.written)


def test_a_claimed_task_shows_its_session_scope_and_minutes(project: Project, agent: Actor) -> None:
    _make(project, "mine_a", _mine("wrk_1", calibration="cal_1"))
    claim_next(project, agent, "mine_a")
    found = activity(project, T0 + timedelta(minutes=7))
    assert len(found.active) == 1
    row = found.active[0]
    assert row.session == agent.session
    assert (row.scope, row.miner_version, row.pass_label, row.mode) == (
        "m-claims",
        2,
        "A",
        "calibration",
    )
    assert (row.work_id, row.title) == ("wrk_1", "Title wrk_1")
    assert row.minutes_held == 7.0
    assert row.claimed_at.startswith("2026-10-31T12:00:00")
    assert row.rows_recorded == 0
    assert row.last_event_at is not None and row.stale is False


def test_a_production_task_and_a_plain_kind(project: Project, agent: Actor) -> None:
    _make(project, "mine_b", _mine("wrk_2", label="B"))
    _make(project, "demo", {"records": [{"work_id": "wrk_9", "title": "T"}]})
    claim_next(project, agent, "mine_b")
    claim_next(project, agent, "demo")
    rows = {r.kind: r for r in activity(project, T0).active}
    assert rows["mine_b"].mode == "production" and rows["mine_b"].pass_label == "B"
    assert rows["demo"].mode is None and rows["demo"].scope == "demo"


def test_a_completed_or_released_task_disappears(project: Project, agent: Actor) -> None:
    ids = _make(project, "demo", {"n": 1}, {"n": 2})
    first = claim_next(project, agent, "demo")
    second = claim_next(project, agent, "demo")
    assert first is not None and second is not None
    assert len(activity(project, T0).active) == 2
    complete_task(project, agent, ids[0])
    release_task(project, agent, ids[1], "done for now")
    assert activity(project, T0).active == []


def test_stale_at_the_threshold(project: Project, agent: Actor) -> None:
    _make(project, "demo", {"n": 1})
    claim_next(project, agent, "demo")
    before = activity(project, T0 + timedelta(minutes=STALE_MINUTES) - timedelta(seconds=1))
    at = activity(project, T0 + timedelta(minutes=STALE_MINUTES))
    assert before.active[0].stale is False
    assert at.active[0].stale is True
    assert at.active[0].minutes_held == float(STALE_MINUTES)


def test_rows_recorded_by_the_holder_are_counted(project: Project, agent: Actor) -> None:
    ids = _make(project, "demo", {"n": 1})
    claim_next(project, agent, "demo")
    activity(project, T0)  # syncs the index
    event_id = _claim_event_id(project)
    with project.index._engine.begin() as conn:  # a test world: the projection is rebuildable
        for n in range(3):
            conn.execute(
                text(
                    "INSERT INTO extraction_rows (extraction_id, scope, work_id, pass_label, "
                    "task_id, protocol_id, schema_ref, document_id, conversion_id, row_key, "
                    "event_id) VALUES (:i, 'm-claims', 'w', 'A', :t, 'p', 's', 'd', 'c', :i, :e)"
                ),
                {"i": f"ext_{n}", "t": ids[0], "e": event_id},
            )
    assert activity(project, T0).active[0].rows_recorded == 3


def _claim_event_id(project: Project) -> str:
    with project.index.connect() as conn:
        return str(
            conn.execute(text("SELECT id FROM events WHERE type = 'task.claimed'")).scalar_one()
        )


def _fixed_mine(monkeypatch: pytest.MonkeyPatch, units: int, closed: int) -> None:
    listed = [
        MineStatus(
            name="m-claims",
            version=2,
            digest="d",
            units=units,
            open=units - closed,
            closed=closed,
            rows=0,
            stale=0,
            agreement=None,
        )
    ]
    monkeypatch.setattr(activity_service, "mine_status", lambda *_, **__: listed)


def test_a_miner_pass_has_done_total_rate_and_eta(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _make(project, "mine_a", *[_mine(f"wrk_{n}") for n in range(4)])
    for task_id in ids[:2]:
        claim_next(project, agent, "mine_a")
        complete_task(project, agent, task_id)
    claim_next(project, agent, "mine_a")
    release_task(project, agent, ids[2], "stopping")
    _fixed_mine(monkeypatch, units=10, closed=2)
    row = activity(project, T0 + timedelta(minutes=10)).passes[0]
    assert (row.kind, row.name, row.version) == ("miner", "m-claims", 2)
    assert (row.done, row.total, row.completed_recent, row.released) == (2, 10, 2, 1)
    assert row.rate_estimate_per_hour == 4.0  # 2 in the last 30 minutes
    assert row.eta_estimate_minutes == 120.0  # 8 left at 4 an hour


def test_the_eta_is_none_when_nothing_completed_in_the_window(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _make(project, "mine_a", _mine("wrk_1"))
    claim_next(project, agent, "mine_a")
    complete_task(project, agent, ids[0])
    _fixed_mine(monkeypatch, units=5, closed=1)
    old = activity(project, T0 + timedelta(minutes=31)).passes[0]
    assert old.completed_recent == 0
    assert old.rate_estimate_per_hour == 0.0 and old.eta_estimate_minutes is None


def test_another_task_kind_with_open_tasks_is_a_pass(
    project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixed_mine(monkeypatch, units=0, closed=0)
    ids = _make(project, "demo", {"n": 1}, {"n": 2}, {"n": 3})
    claim_next(project, agent, "demo")
    complete_task(project, agent, ids[0])
    row = activity(project, T0 + timedelta(minutes=1)).passes[0]
    assert (row.kind, row.done, row.total, row.completed_recent) == ("demo", 1, 3, 1)
    assert row.rate_estimate_per_hour == 2.0 and row.eta_estimate_minutes == 60.0


def _live(project: Project, name: str, body: str, age_minutes: float) -> Path:
    path = project.paths.dir / "ops" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    stamp = (T0 - timedelta(minutes=age_minutes)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_traces_read_the_last_line_and_skip_old_or_other_files(project: Project) -> None:
    _live(project, "night/a.live", "11:20:19 > grep\n11:20:21 > document_read\n\n", 5)
    _live(project, "b.live", "11:00:00 > older\n", 20)
    _live(project, "old.live", "x\n", 121)
    _live(project, "night/notes.txt", "not a trace\n", 1)
    found = activity(project, T0).traces
    assert [t.path for t in found] == ["night/a.live", "b.live"]
    assert found[0].last_line == "11:20:21 > document_read"
    assert found[0].size == len("11:20:19 > grep\n11:20:21 > document_read\n\n")


def test_traces_are_capped_and_a_missing_ops_folder_is_empty(project: Project) -> None:
    assert activity(project, T0).traces == []
    for n in range(35):
        _live(project, f"t{n}.live", "x\n", n / 10)
    assert len(activity(project, T0).traces) == 30


def test_reading_writes_no_event(project: Project, agent: Actor) -> None:
    _make(project, "demo", {"n": 1})
    claim_next(project, agent, "demo")
    events = project.paths.events_dir
    before = {p: p.read_bytes() for p in events.rglob("*") if p.is_file()}
    activity(project, T0)
    after = {p: p.read_bytes() for p in events.rglob("*") if p.is_file()}
    assert before == after


def test_the_cache_serves_for_the_window_and_ends_with_a_new_event(
    project: Project, agent: Actor
) -> None:
    _make(project, "demo", {"n": 1})
    clock = [0.0]
    calls: list[int] = []

    def now() -> Any:
        calls.append(1)
        return T0

    first = activity_cached(project, clock=now, monotonic=lambda: clock[0])
    again = activity_cached(project, clock=now, monotonic=lambda: clock[0] + 1)
    assert again is first and len(calls) == 1
    later = activity_cached(
        project, clock=now, monotonic=lambda: clock[0] + activity_service.CACHE_SECONDS + 1
    )
    assert later is not first and len(calls) == 2
    claim_next(project, agent, "demo")
    changed = activity_cached(project, clock=now, monotonic=lambda: clock[0] + 1)
    assert changed is not later and len(changed.active) == 1
