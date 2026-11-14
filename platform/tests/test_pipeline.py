"""The full ingestion pipeline (plan feed-hub H8, decision 119). No real `claude` is started: a
fake launcher stands in for the process and the reads that need a configured project are patched.
Not run while testing is paused."""

from __future__ import annotations

import json
import os
import signal
import threading
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
from factory.services.miners import MinerState
from factory.services.mining import MinerListing
from factory.services.work_queue import QueueItem
from tests.helpers import install_skill

_REAL_STEPS = pipeline.automatic_steps

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
    monkeypatch.setattr(pipeline, "automatic_steps", lambda p, **kw: None)
    monkeypatch.setattr(
        "factory.services.miners.miner_state", lambda p, name, version: MinerState.CALIBRATED
    )
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


def test_an_uncalibrated_miner_does_not_apply(
    project: Project, configured: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """IDEA-69 (3): a listed version without a passed calibration is skipped by a pipeline (the
    runner would refuse it), with the reason shown, instead of stopping the pipeline."""
    states = {"m-alpha": MinerState.CALIBRATED, "m-beta": MinerState.REGISTERED}
    monkeypatch.setattr(
        "factory.services.miners.miner_state", lambda p, name, version: states[name]
    )
    found = {s.key: s for s in pipeline.stages(project)}
    assert found["mine:m-alpha"].applies
    beta = found["mine:m-beta"]
    assert not beta.applies and beta.pending == 4  # counted, for the exploratory button
    assert "mine:m-beta" not in pipeline.pending_by_stage(project)
    assert "no passed calibration" in beta.reason and "exploratory" in beta.reason
    assert beta.exploratory_only and not found["mine:m-alpha"].exploratory_only


def test_queue_page_offers_exploratory_for_an_uncalibrated_miner() -> None:
    """The hub lists an uncalibrated miner with its reason and an exploratory button, never a
    plain Process now button."""
    from factory.services.pipeline import PipelineStage
    from factory.services.site_queue import _pending_html

    def stage(key: str, applies: bool, only: bool) -> PipelineStage:
        return PipelineStage(
            key=key,
            label=key,
            skill="rf-mine",
            role="miner",
            model="claude-haiku-5-5",
            tools=("mcp__factory__mine_next",),
            pending=3,
            applies=applies,
            reason="version 1 has no passed calibration" if only else "listed",
            exploratory_only=only,
        )

    html = _pending_html({}, [stage("mine:m-a", True, False), stage("mine:m-b", False, True)])
    assert "data-stage='mine:m-b' data-exploratory=1" in html
    assert "Process exploratory" in html and "no passed calibration" in html
    assert "data-stage='mine:m-a'>Process now" in html
    assert "data-stage='mine:m-b'>Process now" not in html


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
    assert env["FACTORY_RUN_DIR"] == str(project.paths.dir / "runs" / "rnr_X")
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
    assert from_env.cap == 5 and from_env.run_id == "rnr_Y" and from_env.run_dir is None


def test_the_counter_writes_units_json_in_the_run_folder(tmp_path: Path) -> None:
    folder = tmp_path / "rnr_W"
    folder.mkdir()
    cap = UnitCap.from_env(
        {"FACTORY_UNIT_CAP": "5", "FACTORY_RUN_ID": "rnr_W", "FACTORY_RUN_DIR": str(folder)}
    )
    cap.count({"batch": {"records": [{}, {}]}})
    record = json.loads((folder / "units.json").read_text(encoding="utf-8"))
    assert record["run_id"] == "rnr_W" and record["served"] == 2 and record["cap"] == 5
    assert "updated_at" in record
    reserved = cap.reserve(3)
    cap.settle(reserved, {"batch": {"records": [{}]}})
    record = json.loads((folder / "units.json").read_text(encoding="utf-8"))
    assert record["served"] == 3  # 2 counted + 1 of the 3 reserved served; the other 2 returned
    assert not (folder / "units.json.tmp").exists()


def test_the_counter_without_a_run_dir_writes_nothing(tmp_path: Path) -> None:
    UnitCap(3, "rnr_V").count({"batch": {"records": [{}]}})
    assert list(tmp_path.iterdir()) == []


def test_the_counter_swallows_a_failed_write(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-folder"
    cap = UnitCap(3, "rnr_U", missing)
    cap.count({"batch": {"records": [{}]}})
    assert cap.served == 1
    assert not missing.exists()


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


# --- The hard unit cap ---


def test_reserve_refuses_a_batch_that_would_pass_the_cap_and_counts_in_one_step() -> None:
    cap = UnitCap(25, "rnr_R")
    assert cap.remaining() == 25 and UnitCap().remaining() is None
    assert cap.reserve(10) == 10 and cap.reserve(10) == 10
    assert cap.remaining() == 5
    with pytest.raises(FactoryValidationError) as caught:  # cap - 1 served, a 10-record batch
        cap.reserve(10)
    assert caught.value.issues[0].field == "cap-reached"
    assert cap.served == 20  # the refusal counted nothing
    assert cap.reserve(5) == 5 and cap.remaining() == 0


def test_cap_minus_one_served_refuses_a_multi_record_batch_but_serves_a_single_unit() -> None:
    cap = UnitCap(10)
    cap.served = 9
    with pytest.raises(FactoryValidationError):
        cap.reserve(10, whole=10)
    assert cap.reserve(1) == 1


def test_serving_settles_to_the_records_served_and_releases_on_failure() -> None:
    cap = UnitCap(30)
    with cap.serving(10, whole=10) as done:
        done({"batch": {"records": [{}, {}, {}]}})
    assert cap.served == 3
    with cap.serving(10, whole=10) as done:
        done({"batch": None})
    assert cap.served == 3
    with pytest.raises(RuntimeError), cap.serving(10, whole=10):
        raise RuntimeError("the service failed")
    assert cap.served == 3
    with cap.serving() as done:
        done({"batch": {"task_id": "t"}})
    assert cap.served == 4


def test_a_cap_smaller_than_one_batch_serves_one_batch_when_nothing_is_served() -> None:
    cap = UnitCap(3)
    assert cap.reserve(10, whole=10) == 3
    with pytest.raises(FactoryValidationError):
        cap.reserve(10, whole=10)


@pytest.mark.anyio
async def test_screen_next_refuses_when_a_batch_would_pass_the_cap(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    cap = UnitCap(15, "rnr_S")
    cap.served = 6  # 9 left, a batch is up to 10 records
    server = build_server(settings, clock=clock, sources={}, cap=cap)
    args = {
        "project": project.paths.slug,
        "pass_label": "A",
        "role": "screener",
        "model": "claude-haiku-5-5",
        "skill": "rf-screen",
    }
    async with Client(server) as client:
        result = await client.call_tool("screen_next", args)
    block: Any = result.content[0]
    body = json.loads(block.text)
    assert [e["field"] for e in body["errors"]] == ["cap-reached"]
    assert cap.served == 6


# --- The prompts ---


def test_the_screen_prompt_runs_title_abstract_then_full_text(
    project: Project, configured: dict[str, int]
) -> None:
    _, _, prompt = runner.build_command(project, "screen")
    assert prompt.index('stage="title-abstract"') < prompt.index('stage="full-text"')
    assert "overridden" in prompt and "pass A" in prompt


def test_the_intuition_prompt_puts_concepts_out_of_scope(
    project: Project, configured: dict[str, int]
) -> None:
    _, _, prompt = runner.build_command(project, "intuition")
    assert "out of scope" in prompt and "concept_propose" in prompt
    spec = runner.STAGES["intuition"]
    assert "mcp__factory__concept_propose" not in spec.tools
    assert "mcp__factory__concept_link" not in spec.tools


# --- The time limit of a run ---


class StuckProcess:
    """A child that exits only when it is released (by a signal the test delivers)."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self.done = threading.Event()
        self.code = 0

    def wait(self) -> int:
        self.done.wait(30)
        return self.code


class StuckLauncher:
    def __init__(self) -> None:
        self.processes: list[StuckProcess] = []

    def __call__(self, argv: Sequence[str], log_path: Path) -> StuckProcess:
        log_path.write_text('{"type":"result"}\n', encoding="utf-8")
        process = StuckProcess()
        self.processes.append(process)
        return process


def test_the_time_limit_is_per_unit_plus_a_base() -> None:
    assert runner.run_time_limit(25) == 25 * 120 + 600


@pytest.mark.parametrize("ignores_term", [False, True])
def test_a_run_past_its_limit_is_killed_recorded_failed_and_stops_the_pipeline(
    project: Project,
    configured: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
    ignores_term: bool,
) -> None:
    launcher = StuckLauncher()
    signals: list[int] = []

    def deliver(pid: int, sig: int) -> None:
        signals.append(sig)
        if sig == signal.SIGKILL or not ignores_term:
            launcher.processes[0].code = -sig
            launcher.processes[0].done.set()

    monkeypatch.setattr(runner, "run_time_limit", lambda cap: 0.2)
    monkeypatch.setattr(runner, "KILL_GRACE", 0.3)
    monkeypatch.setattr(runner, "_signal_group", deliver)
    pipeline_id = pipeline.run_pipeline(project, unit_cap=3, launcher=launcher)
    assert signals == ([signal.SIGTERM, signal.SIGKILL] if ignores_term else [signal.SIGTERM])
    assert len(launcher.processes) == 1  # the pipeline stopped at the first stage
    [view] = pipeline.pipeline_status(project)
    assert view.pipeline_id == pipeline_id
    assert view.status == "failed" and view.stopped_at == "screen"
    assert view.reason is not None and view.reason.startswith("timeout")
    [run_id] = view.run_ids
    assert runner.run_outcome(project, run_id) == "failed"


def test_wait_until_closed_uses_a_patched_clock(
    project: Project, configured: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = StuckLauncher()
    run_id = runner.start_run(project, "screen", unit_cap=2, launcher=launcher, pipeline=True)
    ticks = iter([0.0, 5.0, 10_000.0])
    monkeypatch.setattr(runner, "_monotonic", lambda: next(ticks))
    monkeypatch.setattr(runner, "_signal_group", lambda pid, sig: launcher.processes[0].done.set())
    assert runner.wait_until_closed(project, run_id, 0.05, limit=runner.run_time_limit(2)) is False
    assert runner.run_outcome(project, run_id) is not None


# --- The reference step of the automatic steps ---


def _steps_env(monkeypatch: pytest.MonkeyPatch, works: list[str], failing: set[str]) -> list[str]:
    calls: list[str] = []

    def extract(project: Project, actor: Actor, work_ids: Sequence[str], **kw: Any) -> None:
        [work] = work_ids
        calls.append(work)
        if work in failing:
            raise RuntimeError("the parser failed")

    monkeypatch.setattr("factory.services.references.included_works", lambda p: list(works))
    monkeypatch.setattr("factory.services.references.current_extraction", lambda p, w: None)
    monkeypatch.setattr("factory.services.references.extract_references", extract)
    monkeypatch.setattr("factory.services.document_read.default_conversion", lambda p, w: object())
    monkeypatch.setattr(runner, "_advance_after", lambda p: None)
    return calls


def test_a_failing_reference_extraction_does_not_block_the_next_work(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _steps_env(monkeypatch, ["wrk_3", "wrk_1", "wrk_2"], {"wrk_1"})
    failed: set[str] = set()
    _REAL_STEPS(project, unit_cap=2, failed=failed)
    assert calls == ["wrk_1", "wrk_2"] and failed == {"wrk_1"}
    calls.clear()
    _REAL_STEPS(project, unit_cap=2, failed=failed)  # wrk_1 is not tried again
    assert calls == ["wrk_2", "wrk_3"]


def test_reference_extraction_is_bounded_by_the_unit_cap(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _steps_env(monkeypatch, ["wrk_1", "wrk_2", "wrk_3"], set())
    _REAL_STEPS(project, unit_cap=1)
    assert calls == ["wrk_1"]


# --- The pipeline thread and its probe ---


def test_a_thread_that_does_not_start_releases_the_lock_and_closes_the_pipeline(
    project: Project, configured: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    with monkeypatch.context() as patched:  # undo only this patch, not the fixture's
        patched.setattr(threading.Thread, "start", refuse)
        with pytest.raises(RuntimeError):
            pipeline.start_pipeline(project, launcher=CodedLauncher())
    assert not pipeline.pipeline_active(project)
    [finished] = _events(project, "runner.pipeline_finished")
    assert finished.payload["outcome"] == "failed"
    plan = pipeline.begin_pipeline(project)  # the lock is free again
    pipeline.execute_pipeline(project, plan, launcher=CodedLauncher(*[0] * 6))


def test_the_active_probe_follows_the_open_pipeline_row(
    project: Project, configured: dict[str, int]
) -> None:
    assert not pipeline.pipeline_active(project)
    plan = pipeline.begin_pipeline(project)
    try:
        assert pipeline.pipeline_active(project)
        assert pipeline.pipeline_active(project)  # probing twice leaves the lock held by the plan
    finally:
        pipeline.execute_pipeline(project, plan, launcher=CodedLauncher(*[0] * 6))
    assert not pipeline.pipeline_active(project)
