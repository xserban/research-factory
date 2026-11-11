"""Resuming interrupted work (plan restart-and-costs R2). No real `claude` is started: a fake
launcher stands in for the process; events and run folders are written directly."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.runner import PipelineFinished, PipelineStarted, RunnerFinished, RunnerStarted
from factory.services import pipeline, resume, runner
from factory.services.context import Project
from factory.services.pipeline import PipelineStage
from factory.services.tasks import TaskSpec, claim_next, create_tasks
from tests.helpers import install_skill


class FakeProcess:
    def __init__(self) -> None:
        self.pid = os.getpid()

    def wait(self) -> int:
        return 0


class FakeLauncher:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], log_path: Path) -> FakeProcess:
        log_path.write_text('{"type":"result"}\n', encoding="utf-8")
        self.calls.append(list(argv))
        return FakeProcess()


@pytest.fixture(autouse=True)
def _env(project: Project, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    install_skill(project.settings, "rf-extract", "EXTRACT SKILL BODY")
    install_skill(project.settings, "rf-screen", "SCREEN SKILL BODY")
    pending = {"screen_a": 2, "screen_ft_a": 0, "extract_a": 0}
    monkeypatch.setattr(runner, "pending_work", lambda p: dict(pending))
    monkeypatch.setattr(resume, "pending_work", lambda p: dict(pending))
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")
    monkeypatch.setattr(runner, "_advance_after", lambda p: None)
    monkeypatch.setattr(pipeline, "automatic_steps", lambda *a, **k: None)
    return pending


def _events(project: Project) -> list[Event]:
    return list(read_all(project.paths.events_dir, project.catalog))


def _started(
    project: Project,
    stage: str = "screen",
    tools: tuple[str, ...] | None = None,
    prompt: str = "RECORDED PROMPT",
) -> str:
    """An open run of `stage` whose process is gone, recorded with the stage's tools and model."""
    spec = runner.STAGES[stage]
    run_id = project.ids.new("rnr")
    folder = project.paths.dir / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "pid").write_text("999999", encoding="utf-8")  # no such process
    payload = RunnerStarted(
        run_id=run_id,
        stage=stage,
        model=spec.model,
        allowed_tools=spec.tools if tools is None else tools,
        prompt_blob=project.blobs.put(prompt.encode()),
        unit_cap=4,
        counts_before={"screen_a": 2},
        command=("claude",),
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])
    return run_id


def _row(project: Project, table: str, key: str, value: str) -> Any:
    project.index.sync()
    with project.index.connect() as conn:
        return (
            conn.execute(text(f"SELECT * FROM {table} WHERE {key} = :v"), {"v": value})
            .mappings()
            .one()
        )


def _plan_stages(monkeypatch: pytest.MonkeyPatch, keys: tuple[str, ...]) -> None:
    def fake(project: Project) -> list[PipelineStage]:
        return [
            PipelineStage(
                key=k,
                label=k,
                skill="s",
                role="r",
                model="m",
                tools=("t",),
                pending=1,
                applies=True,
                reason="",
            )
            for k in keys
        ]

    monkeypatch.setattr(pipeline, "stages", fake)


def test_nothing_interrupted_is_a_no_op(project: Project) -> None:
    before = len(_events(project))
    dry = resume.resume(project, dry_run=True)
    assert isinstance(dry, resume.ResumePlan) and dry.is_empty
    result = resume.resume(project, launcher=FakeLauncher())
    assert isinstance(result, resume.ResumeResult)
    assert result.plan.is_empty and result.run_id is None and result.pipeline_id is None
    assert result.reconciled == [] and result.refused == []
    assert len(_events(project)) == before


def test_a_dry_run_writes_nothing_not_even_the_reconcile(project: Project) -> None:
    run_id = _started(project)
    before = len(_events(project))
    launcher = FakeLauncher()
    plan = resume.resume(project, dry_run=True, launcher=launcher)
    assert isinstance(plan, resume.ResumePlan)
    assert plan.reconcile == [run_id]
    assert plan.run is not None and plan.run.resumes == run_id and plan.run.stage == "screen"
    assert len(_events(project)) == before and launcher.calls == []
    assert runner.run_status(project, reconcile=False)[0].status == "lost?"


def test_expired_leases_are_reported_released_by_expiry_with_no_event(
    project: Project, agent: Actor, clock: FixedClock
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    assert claim_next(project, agent, "demo") is not None
    clock.advance(timedelta(hours=1))
    before = len(_events(project))
    result = resume.resume(project, launcher=FakeLauncher())
    assert isinstance(result, resume.ResumeResult)
    assert [(lease.kind, lease.count) for lease in result.plan.leases] == [("demo", 1)]
    assert len(_events(project)) == before
    assert all(e.type != "task.released" for e in _events(project))
    assert claim_next(project, agent, "demo") is not None  # the lapsed claim is claimable again


def test_a_lost_run_is_resumed_with_the_same_prompt_tools_and_model(project: Project) -> None:
    earlier = _started(project)
    old = _row(project, "runner_runs", "run_id", earlier)
    launcher = FakeLauncher()
    result = resume.resume(project, launcher=launcher)
    assert isinstance(result, resume.ResumeResult)
    assert result.reconciled == [earlier] and result.refused == []
    assert result.run_id is not None and result.run_id != earlier
    assert runner.wait(result.run_id, 10)
    new = _row(project, "runner_runs", "run_id", result.run_id)
    assert new["resumes"] == earlier
    assert (new["prompt_blob"], new["allowed_tools"], new["model"], new["unit_cap"]) == (
        old["prompt_blob"],
        old["allowed_tools"],
        old["model"],
        old["unit_cap"],
    )
    [argv] = launcher.calls
    assert "RECORDED PROMPT" in argv  # the recorded prompt, not a rebuilt one
    assert argv[argv.index("--model") + 1] == old["model"]
    assert _row(project, "runner_runs", "run_id", earlier)["outcome"] == "lost"
    assert [e.type for e in _events(project) if earlier in str(e.payload)] == [
        "runner.started",
        "runner.finished",
        "runner.started",  # the resumed run names it; the earlier events are unchanged
    ]


def test_a_changed_stage_spec_refuses_the_resume(project: Project) -> None:
    earlier = _started(project, tools=("mcp__factory__screen_next",))
    launcher = FakeLauncher()
    result = resume.resume(project, launcher=launcher)
    assert isinstance(result, resume.ResumeResult)
    assert result.run_id is None and launcher.calls == []
    assert len(result.refused) == 1 and "changed since" in result.refused[0]
    assert "fresh run" in result.refused[0]
    with pytest.raises(FactoryValidationError):
        runner.start_run(project, "screen", resumes=earlier, launcher=launcher)
    started = [e for e in _events(project) if e.type == "runner.started"]
    assert len(started) == 1


def test_start_run_refuses_a_resume_of_an_unknown_other_stage_or_complete_run(
    project: Project,
) -> None:
    earlier = _started(project)
    with pytest.raises(FactoryValidationError):
        runner.start_run(project, "screen", resumes="rnr_" + "0" * 26, launcher=FakeLauncher())
    with pytest.raises(FactoryValidationError):
        runner.start_run(project, "extract", resumes=earlier, launcher=FakeLauncher())


def test_an_interrupted_pipeline_resumes_from_the_stage_that_did_not_finish(
    project: Project, _env: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    _env["extract_a"] = 2
    _plan_stages(monkeypatch, ("screen", "extract"))
    old = project.ids.new("rpl")
    project.record(
        [
            project.events.make(
                "runner.pipeline_started",
                PipelineStarted(
                    pipeline_id=old,
                    stages=("screen", "extract"),
                    unit_cap=5,
                    counts_before={"screen": 2, "extract": 2},
                ),
                project.system_actor(),
            ),
            project.events.make(
                "runner.pipeline_finished",
                PipelineFinished(pipeline_id=old, outcome="lost", stopped_at="extract"),
                project.system_actor(),
            ),
        ]
    )
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan) and plan.pipeline is not None
    assert (plan.pipeline.resumes, plan.pipeline.from_stage) == (old, "extract")
    launcher = FakeLauncher()
    result = resume.resume(project, launcher=launcher)
    assert isinstance(result, resume.ResumeResult) and result.pipeline_id is not None
    assert pipeline.wait(result.pipeline_id, 10)
    new = _row(project, "runner_pipelines", "pipeline_id", result.pipeline_id)
    assert new["resumes"] == old and new["stages"] == '["extract"]'
    assert len(launcher.calls) == 1
    assert launcher.calls[0][launcher.calls[0].index("--model") + 1] == "claude-sonnet-5-5"


def test_old_runner_started_without_resumes_still_folds(project: Project) -> None:
    run_id = _started(project)
    [event] = [e for e in _events(project) if e.type == "runner.started"]
    legacy = {k: v for k, v in event.payload.items() if k != "resumes"}
    assert "resumes" not in legacy
    other = project.ids.new("rnr")
    legacy["run_id"] = other
    project.record([event.model_copy(update={"id": project.ids.new("ev"), "payload": legacy})])
    assert _row(project, "runner_runs", "run_id", other)["resumes"] is None
    assert run_id != other


def test_the_fold_drops_an_unknown_resumes_and_keeps_the_run(project: Project) -> None:
    run_id = project.ids.new("rnr")
    payload = RunnerStarted(
        run_id=run_id,
        stage="screen",
        model="claude-haiku-5-5",
        allowed_tools=("mcp__factory__screen_next",),
        prompt_blob=project.blobs.put(b"p"),
        unit_cap=1,
        counts_before={},
        command=("claude",),
        resumes="rnr_" + "0" * 26,
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])
    assert _row(project, "runner_runs", "run_id", run_id)["resumes"] is None


# --- review fixes: foreground, live runs, caps ----------------------------------------------


class SlowLauncher:
    """The process ends only after a pause: a caller that does not wait sees the run still open."""

    def __call__(self, argv: Sequence[str], log_path: Path) -> FakeProcess:
        log_path.write_text('{"type":"result"}\n', encoding="utf-8")
        process = FakeProcess()
        process.wait = lambda: (time.sleep(0.3), 0)[1]  # type: ignore[method-assign]
        return process


def _lost_pipeline(project: Project, cap: int) -> str:
    old = project.ids.new("rpl")
    project.record(
        [
            project.events.make(
                "runner.pipeline_started",
                PipelineStarted(
                    pipeline_id=old,
                    stages=("screen", "extract"),
                    unit_cap=cap,
                    counts_before={"screen": 2, "extract": 2},
                ),
                project.system_actor(),
            ),
            project.events.make(
                "runner.pipeline_finished",
                PipelineFinished(pipeline_id=old, outcome="lost", stopped_at="screen"),
                project.system_actor(),
            ),
        ]
    )
    return old


def test_foreground_resume_of_a_run_waits_until_it_is_closed(project: Project) -> None:
    _started(project)
    result = resume.resume(project, launcher=SlowLauncher(), foreground=True)
    assert isinstance(result, resume.ResumeResult) and result.run_id is not None
    assert result.refused == []
    # Without a wait here the 0.3 s process would still be open.
    assert runner.run_outcome(project, result.run_id) == "complete"


def test_foreground_resume_of_a_pipeline_runs_it_in_the_calling_thread(
    project: Project, _env: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    _env["extract_a"] = 2
    _plan_stages(monkeypatch, ("screen", "extract"))
    _lost_pipeline(project, 5)

    def never(*a: object, **k: object) -> str:
        raise AssertionError("the background start must not be used")

    monkeypatch.setattr(pipeline, "start_pipeline", never)
    result = resume.resume(project, launcher=FakeLauncher(), foreground=True)
    assert isinstance(result, resume.ResumeResult) and result.pipeline_id is not None
    new = _row(project, "runner_pipelines", "pipeline_id", result.pipeline_id)
    assert new["outcome"] == "complete"  # already recorded: nothing runs in a thread


def test_a_resumed_pipeline_keeps_the_cap_of_the_pipeline_it_resumes(
    project: Project, _env: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    _env["extract_a"] = 2
    _plan_stages(monkeypatch, ("screen", "extract"))
    _lost_pipeline(project, 7)
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan) and plan.pipeline is not None
    assert plan.pipeline.unit_cap == 7
    kept = resume.resume(project, launcher=FakeLauncher(), foreground=True)
    assert isinstance(kept, resume.ResumeResult) and kept.pipeline_id is not None
    assert _row(project, "runner_pipelines", "pipeline_id", kept.pipeline_id)["unit_cap"] == 7
    _lost_pipeline(project, 7)  # a newer interrupted pipeline
    over = resume.resume(project, launcher=FakeLauncher(), foreground=True, unit_cap=3)
    assert isinstance(over, resume.ResumeResult) and over.pipeline_id is not None
    assert _row(project, "runner_pipelines", "pipeline_id", over.pipeline_id)["unit_cap"] == 3


def _live_run(project: Project) -> str:
    """An open run whose process (this one) is alive."""
    run_id = _started(project)
    (project.paths.dir / "runs" / run_id / "pid").write_text(str(os.getpid()), encoding="utf-8")
    return run_id


def test_a_live_run_blocks_the_resume_and_no_step_runs(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _live_run(project)
    advanced: list[int] = []
    monkeypatch.setattr(runner, "_advance_after", lambda p: advanced.append(1))
    launcher = FakeLauncher()
    before = len(_events(project))
    result = resume.resume(project, launcher=launcher)
    assert isinstance(result, resume.ResumeResult)
    assert result.refused == [f"blocked: live run {live}"]
    assert result.plan.blocked == f"live run {live}"
    assert advanced == [] and launcher.calls == [] and result.run_id is None
    assert len(_events(project)) == before
    dry = resume.resume(project, dry_run=True)
    assert isinstance(dry, resume.ResumePlan) and dry.blocked == f"live run {live}"
    assert not dry.is_empty


def test_the_steps_run_once_when_the_reconcile_already_ran_them(
    project: Project, _env: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    _env["screen_a"] = 0  # nothing to start: no watcher thread advances in the background
    _started(project)  # open, its process gone: finish_lost closes it and advances
    advanced: list[int] = []
    monkeypatch.setattr(runner, "_advance_after", lambda p: advanced.append(1))
    resume.resume(project, launcher=FakeLauncher())
    assert advanced == [1]
    advanced.clear()
    resume.resume(project, launcher=FakeLauncher())  # nothing to reconcile now
    assert advanced == [1]


def _limit_run(project: Project, log: str) -> str:
    run_id = _started(project)
    payload = RunnerFinished(
        run_id=run_id,
        exit_status=0,
        outcome="complete",
        log_blob=project.blobs.put(log.encode()),
        counts_after={"screen_a": 2},
    )
    project.record([project.events.make("runner.finished", payload, project.system_actor())])
    return run_id


def _limit_log(reset: str) -> str:
    message = f"You've hit your 5-hour limit \\u00b7 resets {reset}"
    return f'{{"type":"result","is_error":true,"result":"{message}"}}\n'


def test_resume_waits_for_the_limit_reset_and_a_dry_run_says_so(
    project: Project, clock: FixedClock
) -> None:
    run_id = _limit_run(project, _limit_log("11pm (UTC)"))
    launcher = FakeLauncher()
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan)
    assert plan.run is None and len(plan.waiting) == 1 and run_id in plan.waiting[0]
    result = resume.resume(project, launcher=launcher)
    assert isinstance(result, resume.ResumeResult)
    assert result.run_id is None and launcher.calls == []
    assert any(r.startswith("waiting: ") and run_id in r for r in result.refused)


def test_resume_starts_a_limit_stopped_run_after_the_reset(
    project: Project, clock: FixedClock
) -> None:
    run_id = _limit_run(project, _limit_log("11pm (UTC)"))
    clock.advance(timedelta(days=1))
    launcher = FakeLauncher()
    result = resume.resume(project, launcher=launcher)
    assert isinstance(result, resume.ResumeResult)
    assert result.refused == [] and result.run_id is not None
    assert runner.wait(result.run_id, 10)
    assert _row(project, "runner_runs", "run_id", result.run_id)["resumes"] == run_id


def test_an_unparsed_reset_text_waits_run_end_plus_five_hours_estimated(
    project: Project, clock: FixedClock
) -> None:
    _limit_run(project, _limit_log("when the moon is full"))
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan)
    assert len(plan.waiting) == 1 and "(estimated)" in plan.waiting[0]
    assert "waiting until" in plan.waiting[0]
    result = resume.resume(project, launcher=FakeLauncher())
    assert isinstance(result, resume.ResumeResult)
    assert result.run_id is None
    assert any("(estimated)" in r for r in result.refused)


def test_a_parsed_reset_is_not_marked_estimated(project: Project) -> None:
    _limit_run(project, _limit_log("11pm (UTC)"))
    plan = resume.resume(project, dry_run=True)
    assert isinstance(plan, resume.ResumePlan)
    assert len(plan.waiting) == 1 and "(estimated)" not in plan.waiting[0]


def test_resume_may_start_once_the_estimate_has_expired(
    project: Project, clock: FixedClock
) -> None:
    run_id = _limit_run(project, _limit_log("when the moon is full"))
    clock.advance(timedelta(hours=5, minutes=1))
    result = resume.resume(project, launcher=FakeLauncher())
    assert isinstance(result, resume.ResumeResult)
    assert result.refused == [] and result.run_id is not None
    assert runner.wait(result.run_id, 10)
    assert _row(project, "runner_runs", "run_id", result.run_id)["resumes"] == run_id
