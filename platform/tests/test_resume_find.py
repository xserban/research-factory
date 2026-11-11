"""The interruption finder (plan restart-and-costs R1): events and run folders are written
directly, as `tests/test_runner.py` does; no process is started and nothing is reconciled."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.extraction import ExtractionPassJoined
from factory.model.runner import (
    PipelineFinished,
    PipelineStarted,
    RunnerFinished,
    RunnerOutcome,
    RunnerStarted,
)
from factory.model.screening import PassLabel
from factory.services import resume, runner
from factory.services.context import Project
from factory.services.resume import PASS_IDLE, interrupted
from factory.services.stages import EXTRACT_KINDS
from factory.services.tasks import TaskSpec, claim_next, create_tasks
from factory.services.work_queue import QueueItem


@pytest.fixture(autouse=True)
def _pending(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    pending = {"screen_a": 2, "extract_a": 0}
    monkeypatch.setattr(runner, "pending_work", lambda p: dict(pending))
    monkeypatch.setattr(resume, "pending_work", lambda p: dict(pending))
    return pending


def _event_count(project: Project) -> int:
    return len(list(read_all(project.paths.events_dir, project.catalog)))


def _started(project: Project, stage: str = "screen") -> str:
    run_id = project.ids.new("rnr")
    folder = project.paths.dir / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "pid").write_text("999999", encoding="utf-8")  # no such process
    payload = RunnerStarted(
        run_id=run_id,
        stage=stage,
        model="claude-haiku-5-5",
        allowed_tools=("mcp__factory__screen_next",),
        prompt_blob=project.blobs.put(f"prompt {run_id}".encode()),
        unit_cap=1,
        counts_before={"screen_a": 2},
        command=("claude",),
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])
    return run_id


def _finished(
    project: Project, run_id: str, outcome: RunnerOutcome, exit_status: int | None
) -> None:
    payload = RunnerFinished(
        run_id=run_id,
        exit_status=exit_status,
        outcome=outcome,
        log_blob=project.blobs.put(b""),
        counts_after={"screen_a": 2},
    )
    project.record([project.events.make("runner.finished", payload, project.system_actor())])


def _pipeline(
    project: Project,
    stages: tuple[str, ...] = ("screen", "extract"),
    finish: PipelineFinished | None = None,
) -> str:
    pipeline_id = project.ids.new("rpl")
    started = PipelineStarted(
        pipeline_id=pipeline_id, stages=stages, unit_cap=5, counts_before={s: 1 for s in stages}
    )
    project.record(
        [project.events.make("runner.pipeline_started", started, project.system_actor())]
    )
    if finish is not None:
        done = finish.model_copy(update={"pipeline_id": pipeline_id})
        project.record(
            [project.events.make("runner.pipeline_finished", done, project.system_actor())]
        )
    return pipeline_id


def test_a_clean_project_has_nothing_interrupted(project: Project) -> None:
    found = interrupted(project)
    assert found.is_clean
    assert (found.runs, found.pipelines, found.leases, found.passes) == ([], [], [], [])


def test_open_run_with_a_dead_process_is_reported_not_reconciled(project: Project) -> None:
    run_id = _started(project)
    before = _event_count(project)
    [run] = interrupted(project).runs
    assert (run.run_id, run.kind, run.stage, run.model) == (
        run_id,
        "open-gone",
        "screen",
        "claude-haiku-5-5",
    )
    assert run.stage_pending is True and run.prompt_blob.startswith("sha256")
    assert _event_count(project) == before
    assert runner.run_status(project, reconcile=False)[0].status == "lost?"


def test_lost_and_timeout_runs_but_not_a_plain_failure(project: Project) -> None:
    lost = _started(project)
    _finished(project, lost, "lost", None)
    killed = _started(project)
    _finished(project, killed, "failed", -15)
    plain = _started(project)
    _finished(project, plain, "failed", 1)
    kinds = {r.run_id: r.kind for r in interrupted(project).runs}
    assert kinds == {lost: "lost", killed: "timeout"}


def test_a_later_complete_run_of_the_stage_supersedes_and_pending_is_flagged(
    project: Project, _pending: dict[str, int]
) -> None:
    lost = _started(project)
    _finished(project, lost, "lost", None)
    _pending["screen_a"] = 0
    assert [r.stage_pending for r in interrupted(project).runs] == [False]
    ok = _started(project)
    _finished(project, ok, "complete", 0)
    assert interrupted(project).runs == []


def test_pipelines_orphaned_lost_and_timed_out(project: Project) -> None:
    timeout = _pipeline(
        project,
        finish=PipelineFinished(
            pipeline_id="x",
            outcome="failed",
            stopped_at="screen",
            reason="timeout: the run rnr_x passed its 700 s limit and was killed",
        ),
    )
    lost = _pipeline(
        project,
        finish=PipelineFinished(pipeline_id="x", outcome="lost", stopped_at="extract"),
    )
    orphan = _pipeline(project)  # open, nobody holds the lock
    found = {p.pipeline_id: p for p in interrupted(project).pipelines}
    assert found[timeout].kind == "timeout" and found[timeout].stages_left == ["screen", "extract"]
    assert found[lost].kind == "lost" and found[lost].stages_left == ["extract"]
    assert found[orphan].kind == "orphaned" and found[orphan].stages_left == ["screen", "extract"]


def test_a_later_complete_pipeline_supersedes_older_ones(project: Project) -> None:
    _pipeline(
        project, finish=PipelineFinished(pipeline_id="x", outcome="lost", stopped_at="screen")
    )
    _pipeline(project, finish=PipelineFinished(pipeline_id="x", outcome="complete"))
    assert interrupted(project).pipelines == []


def test_expired_leases_by_kind_use_the_claim_rule(
    project: Project, agent: Actor, clock: FixedClock
) -> None:
    ids = create_tasks(
        project,
        project.system_actor(),
        [TaskSpec("demo", 1), TaskSpec("demo", 2), TaskSpec("other", 3)],
    ).written
    assert claim_next(project, agent, "demo") is not None
    assert claim_next(project, agent, "other") is not None
    assert interrupted(project).leases == []  # live leases
    clock.advance(timedelta(hours=1))
    before = _event_count(project)
    leases = {e.kind: e for e in interrupted(project).leases}
    assert set(leases) == {"demo", "other"}
    assert leases["demo"].count == 1 and leases["demo"].task_ids == [ids[0]]
    assert _event_count(project) == before  # a pure read: the leases are not released


def test_a_silent_joined_pass_with_pending_units_is_stale(
    project: Project, agent: Actor, clock: FixedClock, _pending: dict[str, int]
) -> None:
    payload = ExtractionPassJoined(
        pass_label=PassLabel.A, session=agent.session, model="claude-opus-5-5"
    )
    project.record(
        [
            project.events.make(
                "extraction.pass_joined",
                payload,
                agent,
                input_blob=project.blobs.put_json({"pass_label": "A"}),
            )
        ]
    )
    kind = EXTRACT_KINDS[PassLabel.A]
    _pending[kind] = 3
    assert interrupted(project).passes == []  # active just now
    clock.advance(PASS_IDLE + timedelta(minutes=1))
    [stale] = interrupted(project).passes
    assert (stale.module, stale.scope, stale.session, stale.pending, stale.task_kind) == (
        "extraction",
        "evidence",
        agent.session,
        3,
        kind,
    )
    _pending[kind] = 0  # nothing left to do: not interrupted
    assert interrupted(project).passes == []


def test_automatic_steps_left_undone_are_counted(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def item(stage: str, stopped: bool = False) -> QueueItem:
        return QueueItem(
            entry_id="e",
            title="t",
            inbox_item_id="i",
            sent_at="2026-11-11T00:00:00.000Z",
            work_id=None,
            stage=stage,
            stopped=stopped,
            detail="",
        )

    items: list[Any] = [
        item("added"),
        item("added", True),
        item("screened-in"),
        item("full-text"),
        item("full-text"),
        item("extracted"),
    ]
    monkeypatch.setattr(resume, "added_papers", lambda p: items)
    auto = interrupted(project).automatic
    assert (auto.resolve, auto.fetch, auto.convert) == (1, 1, 2)


def _started_chain(project: Project, resumes: str | None, *, pid: bool = True) -> str:
    run_id = project.ids.new("rnr")
    folder = project.paths.dir / "runs" / run_id
    folder.mkdir(parents=True)
    if pid:
        (folder / "pid").write_text("999999", encoding="utf-8")
    payload = RunnerStarted(
        run_id=run_id,
        stage="screen",
        model="claude-haiku-5-5",
        allowed_tools=("mcp__factory__screen_next",),
        prompt_blob=project.blobs.put(b"prompt"),
        unit_cap=1,
        counts_before={"screen_a": 2},
        command=("claude",),
        resumes=resumes,
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])
    return run_id


def test_a_run_resumed_by_a_later_run_is_superseded(project: Project) -> None:
    first = _started_chain(project, None)
    _finished(project, first, "lost", None)
    second = _started_chain(project, first)
    _finished(project, second, "lost", None)
    third = _started_chain(project, second)
    _finished(project, third, "failed", -15)
    assert [r.run_id for r in interrupted(project).runs] == [third]


def test_a_launcher_failure_is_failed_to_start_and_not_offered_for_resume(
    project: Project,
) -> None:
    never = _started_chain(project, None, pid=False)
    _finished(project, never, "failed", None)
    killed = _started_chain(project, None)  # has a pid file: a real kill is a timeout
    _finished(project, killed, "failed", None)
    kinds = {r.run_id: r.kind for r in interrupted(project).runs}
    assert kinds == {never: "failed-to-start", killed: "timeout"}
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan)
    assert plan.failed_to_start == [never]
    assert plan.run is not None and plan.run.resumes == killed
    assert never not in plan.queued


_LIMIT_LOG = (
    '{"type":"assistant","message":{"id":"m1","content":[{"type":"text","text":'
    '"You\'ve hit your 5-hour limit \\u00b7 resets 3pm (Europe/Bucharest)"}]}}\n'
    '{"type":"result","is_error":true,"result":'
    '"You\'ve hit your 5-hour limit \\u00b7 resets 3pm (Europe/Bucharest)"}\n'
)


def _finished_with_log(project: Project, run_id: str, log: str, after: int = 2) -> None:
    payload = RunnerFinished(
        run_id=run_id,
        exit_status=0,
        outcome="complete",
        log_blob=project.blobs.put(log.encode()),
        counts_after={"screen_a": after},
    )
    project.record([project.events.make("runner.finished", payload, project.system_actor())])


def test_a_limit_stopped_run_exiting_zero_is_reported_and_hides_nothing(project: Project) -> None:
    lost = _started(project)
    _finished(project, lost, "lost", None)
    limited = _started(project)
    _finished_with_log(project, limited, _LIMIT_LOG)
    before = _event_count(project)
    runs = {r.run_id: r for r in interrupted(project).runs}
    assert set(runs) == {lost, limited}  # the older interrupted run is not hidden
    assert runs[limited].kind == "limit" and runs[lost].kind == "lost"
    assert runs[limited].limit_reason == "log"
    assert runs[limited].limit_reset_text == "3pm (Europe/Bucharest)"
    assert runs[limited].limit_reset_at is not None
    assert _event_count(project) == before


def test_a_normal_complete_run_still_supersedes_older_interrupted_runs(project: Project) -> None:
    lost = _started(project)
    _finished(project, lost, "lost", None)
    ok = _started(project)
    _finished_with_log(project, ok, '{"type":"result","is_error":false,"result":"done"}\n')
    assert interrupted(project).runs == []


def test_a_normal_complete_run_after_a_limit_stop_supersedes_it(project: Project) -> None:
    limited = _started(project)
    _finished_with_log(project, limited, _LIMIT_LOG)
    ok = _started(project)
    _finished_with_log(project, ok, '{"type":"result","is_error":false,"result":"done"}\n', after=0)
    assert interrupted(project).runs == []


def test_an_errored_result_that_closed_no_unit_is_a_limit_stop_without_a_reset(
    project: Project,
) -> None:
    run = _started(project)
    _finished_with_log(project, run, '{"type":"result","is_error":true,"result":"x"}\n')
    [found] = interrupted(project).runs
    assert (found.kind, found.limit_reason, found.limit_reset_at) == ("limit", "no-units", None)


def test_a_limit_log_that_closed_units_is_still_a_limit_stop(project: Project) -> None:
    run = _started(project)
    _finished_with_log(project, run, _LIMIT_LOG, after=1)  # one unit done before the limit
    [found] = interrupted(project).runs
    assert found.kind == "limit"


def test_parse_reset_reads_clock_times_dates_and_zones() -> None:
    from datetime import UTC, datetime

    from factory.services.usage_limit import parse_reset

    after = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)  # 12:00 in Bucharest (UTC+2)
    assert parse_reset("3pm (Europe/Bucharest)", after) == datetime(2026, 11, 11, 13, 0, tzinfo=UTC)
    assert parse_reset("11am (Europe/Bucharest)", after) == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    assert parse_reset("Nov 12, 3:30pm (UTC)", after) == datetime(2026, 11, 12, 15, 30, tzinfo=UTC)
    assert parse_reset("soon", after) is None
    assert parse_reset("3pm (No/Such_Zone)", after) is None
