"""The full ingestion pipeline (plan feed-hub H8, decision 118). No real `claude` is started: a
fake launcher stands in for the process and the reads that need a configured project are patched.
Not run while testing is paused."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.mcp.unit_cap import UnitCap
from factory.services import pipeline, runner
from factory.services.context import Project
from factory.services.mining import MinerListing
from factory.services.work_queue import QueueItem
from tests.helpers import install_skill

SKILLS = ("rf-screen", "rf-extract", "rf-mine", "rf-appraise", "rf-contributions", "rf-intuition")


class InstantProcess:
    """A child that has already exited with `code`."""

    def __init__(self, code: int) -> None:
        self.pid = os.getpid()
        self.code = code

    def wait(self) -> int:
        return self.code


class CodedLauncher:
    """Starts instant processes with the given exit codes, in order, and records each argv."""

    def __init__(self, *codes: int) -> None:
        self.codes = list(codes)
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], log_path: Path) -> InstantProcess:
        log_path.write_text('{"type":"result"}\n', encoding="utf-8")
        self.calls.append(list(argv))
        return InstantProcess(self.codes.pop(0))


def _listing(name: str, listed: bool = True) -> MinerListing:
    return MinerListing(
        name=name, version=1, digest="sha256:" + "0" * 64, proposer_kind="agent", listed=listed
    )


def _issue(field: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, "not declared")])


@pytest.fixture
def configured(project: Project, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """A project whose every stage applies, with two listed miners; returns the pending counts."""
    for skill in SKILLS:
        install_skill(project.settings, skill, f"{skill} body")
    pending = {
        "screen": 2,
        "extract": 3,
        "mine:m-alpha": 1,
        "mine:m-beta": 4,
        "appraise": 5,
        "contributions": 6,
        "intuition": 7,
    }
    monkeypatch.setattr(pipeline, "_ready", lambda p: True)
    monkeypatch.setattr(pipeline, "require_schema", lambda p, scope: None)
    monkeypatch.setattr(pipeline, "appraisal_progress", lambda p: {})
    monkeypatch.setattr(pipeline, "confirmed_ideas", lambda p: [object()])
    monkeypatch.setattr(
        pipeline, "miner_listing", lambda p: [_listing("m-alpha"), _listing("m-beta")]
    )
    monkeypatch.setattr(pipeline, "stage_pending", lambda p, key: pending.get(key, 0))
    monkeypatch.setattr(runner, "pending_units", lambda p, key: {key: pending.get(key, 0)})
    monkeypatch.setattr("factory.services.mining.miner_listing", lambda p: pipeline_miners())
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")
    monkeypatch.setattr(runner, "_advance_after", lambda p: None)
    monkeypatch.setattr(pipeline, "automatic_steps", lambda p: None)
    return pending


def pipeline_miners() -> list[MinerListing]:
    return [_listing("m-alpha"), _listing("m-beta")]


def _keys(project: Project) -> list[str]:
    return [s.key for s in pipeline.stages(project)]


def _events(project: Project, prefix: str) -> list[Any]:
    return [
        e for e in read_all(project.paths.events_dir, project.catalog) if e.type.startswith(prefix)
    ]


def test_unconfigured_project_has_only_the_screening_stage_applying(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "_ready", lambda p: True)
    monkeypatch.setattr(pipeline, "stage_pending", lambda p, key: 0)
    found = {s.key: s for s in pipeline.stages(project)}
    assert [k for k, s in found.items() if s.applies] == ["screen"]
    assert "extract" in found and not found["extract"].applies
    assert found["extract"].reason  # the schema is not declared
    assert not found["appraise"].applies and "instrument" in found["appraise"].reason
    assert not found["contributions"].applies
    assert not found["intuition"].applies
    assert not any(k.startswith("mine:") for k in found)


def test_no_schema_means_no_extract_and_no_instrument_means_no_appraise(
    project: Project, configured: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_evidence(p: Project, scope: Any) -> None:
        if str(scope.value) == "evidence":
            raise _issue("extraction_schema")

    monkeypatch.setattr(pipeline, "require_schema", no_evidence)
    monkeypatch.setattr(pipeline, "appraisal_progress", lambda p: None)
    found = {s.key: s for s in pipeline.stages(project)}
    assert not found["extract"].applies and found["extract"].pending == 0
    assert not found["appraise"].applies and found["appraise"].pending == 0
    assert found["contributions"].applies and found["screen"].applies


def test_two_miners_make_two_mine_stages_in_order(
    project: Project, configured: dict[str, int]
) -> None:
    assert _keys(project) == [
        "screen",
        "extract",
        "mine:m-alpha",
        "mine:m-beta",
        "appraise",
        "contributions",
        "intuition",
    ]
    found = {s.key: s for s in pipeline.stages(project)}
    assert found["mine:m-alpha"].pending == 1 and found["mine:m-beta"].pending == 4


def test_an_unlisted_miner_does_not_apply(
    project: Project, configured: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline, "miner_listing", lambda p: [_listing("m-alpha"), _listing("m-beta", False)]
    )
    found = {s.key: s for s in pipeline.stages(project)}
    assert found["mine:m-alpha"].applies
    assert not found["mine:m-beta"].applies and found["mine:m-beta"].pending == 0


def test_model_skill_and_role_per_stage(project: Project, configured: dict[str, int]) -> None:
    found = {s.key: s for s in pipeline.stages(project)}
    haiku = "claude-haiku-5-5"
    sonnet = "claude-sonnet-5-5"
    assert found["screen"].model == haiku
    assert found["mine:m-alpha"].model == haiku and found["mine:m-beta"].model == haiku
    for key in ("extract", "appraise", "contributions", "intuition"):
        assert found[key].model == sonnet
    assert found["screen"].skill == "rf-screen"
    assert found["mine:m-alpha"].skill == "rf-mine"
    assert found["appraise"].skill == "rf-appraise"
    assert found["contributions"].skill == "rf-contributions"
    assert found["intuition"].skill == "rf-intuition"
    assert "mcp__factory__mine_next" in found["mine:m-beta"].tools
    assert "mcp__factory__intuition_next" in found["intuition"].tools
    assert all(t.startswith("mcp__factory__") for s in found.values() for t in s.tools)


def test_the_prompt_names_the_miner_and_the_stage_skill(
    project: Project, configured: dict[str, int]
) -> None:
    argv, config, prompt = runner.build_command(project, "mine:m-beta", 4, run_id="rnr_X")
    assert "miner `m-beta`" in prompt and "version 1" in prompt and "skill `rf-mine`" in prompt
    assert "role `miner`" in prompt and "rf-mine body" in prompt
    assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
    loaded: Any = config
    env = loaded["mcpServers"]["factory"]["env"]
    assert env["FACTORY_UNIT_CAP"] == "4" and env["FACTORY_RUN_ID"] == "rnr_X"
    _, _, appraisal = runner.build_command(project, "appraise")
    assert "role `appraiser`" in appraisal and "rf-appraise body" in appraisal


def test_unknown_stage_keys_are_refused(project: Project, configured: dict[str, int]) -> None:
    for key in ("nonsense", "mine:", "mine:m-gamma", "all"):
        with pytest.raises(FactoryValidationError):
            runner.build_command(project, key)
    assert runner.is_stage_key("mine:m-alpha") and not runner.is_stage_key("all")
    with pytest.raises(FactoryValidationError):
        runner._as_stage("nonsense")


# --- The unit cap of a run ---


def test_cap_counts_records_of_a_screening_batch_and_batches_otherwise() -> None:
    cap = UnitCap(3, "rnr_X")
    cap.check()
    cap.count({"batch": {"records": [{}, {}]}})
    cap.count({"batch": None})
    cap.check()
    cap.count({"batch": {"task_id": "t"}})
    with pytest.raises(FactoryValidationError) as caught:
        cap.check()
    assert caught.value.issues[0].field == "cap-reached"
    assert "rnr_X" in caught.value.issues[0].reason


def test_no_cap_variable_means_no_cap() -> None:
    free = UnitCap.from_env({})
    for _ in range(1000):
        free.count({"batch": {"records": [{}]}})
        free.check()
    assert UnitCap.from_env({"FACTORY_UNIT_CAP": "abc"}).cap is None
    assert UnitCap.from_env({"FACTORY_UNIT_CAP": "0"}).cap is None
    from_env = UnitCap.from_env({"FACTORY_UNIT_CAP": "5", "FACTORY_RUN_ID": "rnr_Y"})
    assert from_env.cap == 5 and from_env.run_id == "rnr_Y"


NEXT_CALLS: dict[str, dict[str, Any]] = {
    "screen_next": {"pass_label": "A"},
    "extract_next": {"pass_label": "A"},
    "mine_next": {"miner": "m-alpha", "version": 1, "pass_label": "A"},
    "appraisal_next": {"pass_label": "A"},
    "contribution_next": {"pass_label": "A"},
    "intuition_next": {},
}


@pytest.mark.anyio
@pytest.mark.parametrize("tool", sorted(NEXT_CALLS))
async def test_next_tools_refuse_with_cap_reached_once_the_cap_is_served(
    tool: str, settings: Settings, project: Project, clock: FixedClock
) -> None:
    cap = UnitCap(2, "rnr_Z")
    cap.served = 2
    server = build_server(settings, clock=clock, sources={}, cap=cap)
    args = {
        "project": project.paths.slug,
        "role": "worker",
        "model": "claude-haiku-5-5",
        "skill": "rf-screen",
        **NEXT_CALLS[tool],
    }
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    block: Any = result.content[0]
    body = json.loads(block.text)
    assert body["ok"] is False
    assert [e["field"] for e in body["errors"]] == ["cap-reached"]


@pytest.mark.anyio
async def test_without_a_cap_the_next_tools_are_unchanged(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    server = build_server(settings, clock=clock, sources={}, cap=UnitCap())
    args = {
        "project": project.paths.slug,
        "pass_label": "A",
        "role": "appraiser",
        "model": "claude-sonnet-5-5",
        "skill": "rf-appraise",
    }
    async with Client(server) as client:
        result = await client.call_tool("appraisal_next", args)
    block: Any = result.content[0]
    body = json.loads(block.text)
    assert "cap-reached" not in [e["field"] for e in body.get("errors", [])]


# --- Running the pipeline ---


def test_the_pipeline_runs_each_stage_with_pending_work_in_order(
    project: Project, configured: dict[str, int]
) -> None:
    configured["extract"] = 0  # nothing to extract: the stage is skipped
    launcher = CodedLauncher(*[0] * 6)
    pipeline_id = pipeline.run_pipeline(project, unit_cap=3, launcher=launcher)
    assert len(launcher.calls) == 6
    models = [c[c.index("--model") + 1] for c in launcher.calls]
    assert models == ["claude-haiku-5-5"] * 3 + ["claude-sonnet-5-5"] * 3
    [started] = _events(project, "runner.pipeline_started")
    [finished] = _events(project, "runner.pipeline_finished")
    assert started.payload["pipeline_id"] == pipeline_id
    assert started.payload["stages"][0] == "screen" and started.payload["unit_cap"] == 3
    assert finished.payload["outcome"] == "complete" and len(finished.payload["run_ids"]) == 6
    stage_runs = [e.payload["stage"] for e in _events(project, "runner.started")]
    assert stage_runs == [
        "screen",
        "mine:m-alpha",
        "mine:m-beta",
        "appraise",
        "contributions",
        "intuition",
    ]
    [view] = pipeline.pipeline_status(project)
    assert view.status == "complete" and view.stopped_at is None


def test_the_pipeline_stops_at_the_first_failed_run(
    project: Project, configured: dict[str, int]
) -> None:
    launcher = CodedLauncher(0, 1, 0, 0)
    pipeline.run_pipeline(project, launcher=launcher)
    assert len(launcher.calls) == 2  # screen ran, extract failed, nothing after
    [finished] = _events(project, "runner.pipeline_finished")
    assert finished.payload["outcome"] == "failed"
    assert finished.payload["stopped_at"] == "extract"
    assert len(finished.payload["run_ids"]) == 2
    assert len(_events(project, "runner.started")) == 2
    [view] = pipeline.pipeline_status(project)
    assert view.status == "failed" and view.stopped_at == "extract"
    assert not pipeline.pipeline_active(project)  # the lock was released


def test_a_pipeline_with_nothing_pending_is_idle(
    project: Project, configured: dict[str, int]
) -> None:
    for key in configured:
        configured[key] = 0
    launcher = CodedLauncher()
    pipeline.run_pipeline(project, launcher=launcher)
    assert launcher.calls == []
    [finished] = _events(project, "runner.pipeline_finished")
    assert finished.payload["outcome"] == "idle" and finished.payload["run_ids"] == []


def test_a_second_pipeline_or_a_stage_run_is_refused_while_one_runs(
    project: Project, configured: dict[str, int]
) -> None:
    plan = pipeline.begin_pipeline(project)
    try:
        with pytest.raises(FactoryValidationError) as again:
            pipeline.begin_pipeline(project)
        assert again.value.issues[0].field == "pipeline"
        with pytest.raises(FactoryValidationError) as single:
            runner.start_run(project, "screen", launcher=CodedLauncher(0))
        assert single.value.issues[0].field == "pipeline"
    finally:
        pipeline.execute_pipeline(project, plan, launcher=CodedLauncher(*[0] * 6))
    assert len(_events(project, "runner.pipeline_started")) == 1


def test_refusals_write_no_pipeline_event(
    project: Project, configured: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    for cap in (0, runner.MAX_UNIT_CAP + 1):
        with pytest.raises(FactoryValidationError):
            pipeline.run_pipeline(project, unit_cap=cap, launcher=CodedLauncher())
    monkeypatch.setattr(runner, "claude_path", lambda: None)
    with pytest.raises(FactoryValidationError):
        pipeline.run_pipeline(project, launcher=CodedLauncher())
    assert _events(project, "runner.pipeline_") == []


def test_an_orphaned_open_pipeline_is_closed_as_lost_by_the_next_one(
    project: Project, configured: dict[str, int]
) -> None:
    plan = pipeline.begin_pipeline(project)
    pipeline._release(plan.lock)  # the process that ran it ended without recording the finish
    pipeline.run_pipeline(project, launcher=CodedLauncher(*[0] * 7))
    outcomes = [e.payload["outcome"] for e in _events(project, "runner.pipeline_finished")]
    assert outcomes[0] == "lost" and outcomes[-1] == "complete"


# --- Events are system-only ---


def _started_payload() -> dict[str, Any]:
    return {
        "pipeline_id": "rpl_" + "0" * 26,
        "stages": ["screen", "mine:m-alpha"],
        "unit_cap": 5,
        "counts_before": {"screen": 1},
    }


def _count(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM runner_pipelines")).scalar_one())


def _outcome(project: Project) -> str | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT outcome FROM runner_pipelines")).first()
    return None if row is None or row[0] is None else str(row[0])


def test_pipeline_events_by_a_human_or_agent_fold_to_nothing(
    project: Project, agent: Actor
) -> None:
    blob = project.blobs.put(b"x")
    started = project.catalog.get("runner.pipeline_started").payload
    finished = project.catalog.get("runner.pipeline_finished").payload
    for actor in (project.human_actor(), agent):
        project.record(
            [
                project.events.make(
                    "runner.pipeline_started",
                    started.model_validate(_started_payload()),
                    actor,
                    input_blob=blob if actor.kind == "agent" else None,
                )
            ]
        )
    assert _count(project) == 0
    project.record(
        [
            project.events.make(
                "runner.pipeline_started",
                started.model_validate(_started_payload()),
                project.system_actor(),
            )
        ]
    )
    assert _count(project) == 1
    done = {"pipeline_id": "rpl_" + "0" * 26, "outcome": "complete", "run_ids": []}
    for actor in (project.human_actor(), agent):
        project.record(
            [
                project.events.make(
                    "runner.pipeline_finished",
                    finished.model_validate(done),
                    actor,
                    input_blob=blob if actor.kind == "agent" else None,
                )
            ]
        )
    assert _outcome(project) is None
    project.record(
        [
            project.events.make(
                "runner.pipeline_finished", finished.model_validate(done), project.system_actor()
            )
        ]
    )
    assert _outcome(project) == "complete"


def test_the_real_pipeline_events_are_system_events(
    project: Project, configured: dict[str, int]
) -> None:
    pipeline.run_pipeline(project, launcher=CodedLauncher(*[0] * 7))
    events = _events(project, "runner.pipeline_")
    assert len(events) == 2 and {e.actor.kind for e in events} == {"system"}


# --- Per-paper progress ---


def _item(stage: str, *, stopped: bool = False, work: str | None = "wrk_1") -> QueueItem:
    return QueueItem(
        entry_id="fe_1",
        title="A paper",
        inbox_item_id="inb_1",
        sent_at="2026-11-11T00:00:00Z",
        work_id=work,
        stage=stage,  # type: ignore[arg-type]
        stopped=stopped,
        detail="",
    )


def test_cells_read_done_pending_not_applicable_and_stopped() -> None:
    assert pipeline._cell(_item("in-corpus"), "screen", {}) == "pending"
    assert pipeline._cell(_item("in-corpus", stopped=True), "screen", {}) == "stopped"
    assert pipeline._cell(_item("screened-in"), "screen", {}) == "done"
    assert pipeline._cell(_item("full-text"), "extract", {}) == "pending"
    assert pipeline._cell(_item("screened-out", stopped=True), "extract", {}) == "stopped"
    assert pipeline._cell(_item("converted"), "extract", {"wrk_1": False}) == "pending"
    assert pipeline._cell(_item("extracted"), "extract", {"wrk_1": True}) == "done"
    assert pipeline._cell(_item("converted"), "mine:m-alpha", {}) == "n/a"
