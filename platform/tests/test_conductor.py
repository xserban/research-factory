"""The lifecycle conductor (plan tiers-and-autonomy, C8). A fake runner only: no process, no
`claude`, no model."""

from __future__ import annotations

import re
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.index.default import default_projection
from factory.model.conductor import ConductorStarted
from factory.model.levels import Tier
from factory.model.runner import STAGE_KEY_RE, RunnerStarted
from factory.modules.contract import GatePolicy, PolicyKind
from factory.services import conductor, runner
from factory.services.context import Project
from factory.services.project import init_project
from tests.helpers import SESSION

STEPS = ("frame", "gather", "screen", "acquire", "extract", "write")


@dataclass(frozen=True)
class FStage:
    stage_id: str
    skill: str = "rf-x"
    caps: Mapping[str, int] = field(default_factory=dict)
    skipped: bool = False
    note: str = ""


@dataclass(frozen=True)
class FLimits:
    max_papers: int = 30
    max_minutes: int = 60
    max_runs: int = 20


@dataclass(frozen=True)
class FPlan:
    tier: Tier
    stages: tuple[FStage, ...]
    limits: FLimits = FLimits()


def plan(*ids: str, skipped: tuple[str, ...] = (), limits: FLimits | None = None) -> FPlan:
    return FPlan(
        Tier.BRIEF,
        tuple(FStage(i, skipped=i in skipped) for i in ids),
        limits or FLimits(),
    )


class FakeRunner:
    """Stands for `runner.start_run`; asks the runner's own pending-unit question first, as the
    real one does, so the conductor's hook is exercised. Starts nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []
        self.outcomes: dict[str, str] = {}
        self.refuse: str | None = None
        self.open: set[str] = set()

    def start_run(self, project: Project, stage: str, *, unit_cap: int) -> str:
        if self.refuse is not None:
            from factory.errors import ValidationIssue

            raise FactoryValidationError([ValidationIssue("run", self.refuse)])
        if stage in runner.CONDUCT_STAGES:
            assert sum(runner.pending_units(project, stage).values()) == 1
        run_id = project.ids.new("rnr")
        self.calls.append((stage, unit_cap, run_id))
        return run_id

    def outcome(self, project: Project, run_id: str) -> str | None:
        return None if run_id in self.open else self.outcomes.get(run_id, "complete")

    @property
    def stages(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    f = FakeRunner()
    monkeypatch.setattr(runner, "run_outcome", f.outcome)
    return f


def make(settings: Settings, clock: FixedClock, level: str = "attended") -> Project:
    return init_project(
        settings, "demo", None, session=SESSION, clock=clock, tier="brief", autonomy_level=level
    )


def _open(_p: Project, _s: str, _g: str) -> bool:
    return True


def _idle(_p: Project, stage: str) -> dict[str, int]:
    return {stage: 0}


def _busy(_p: Project, stage: str) -> dict[str, int]:
    return {stage: 1}


def drive(
    project: Project,
    fake: FakeRunner,
    *,
    gate_closed: Callable[[Project, str, str], bool] = _open,
    retry: bool = False,
    limit: int = 40,
) -> conductor.ConductorStatus:
    status = conductor.conductor_status(project)
    for _ in range(limit):
        status = conductor.advance(
            project,
            retry=retry,
            start_run=fake.start_run,
            pending=_idle,
            gate_closed=gate_closed,
            escalate=lambda *_a: None,
        )
        if status.state in ("finished", "paused", "waiting"):
            return status
    raise AssertionError("did not stop")


@pytest.fixture
def project(settings: Settings, clock: FixedClock) -> Project:
    return make(settings, clock)


def policy(kind: PolicyKind) -> Callable[..., GatePolicy]:
    return lambda _project, _gate, **_kw: GatePolicy(kind)


# ------------------------------------------------------------------------------------- begin


def test_begin_writes_one_started_event_with_the_budget(project: Project) -> None:
    run = conductor.begin_conductor(project, plan(*STEPS, "understand", skipped=("understand",)))
    assert run.steps == STEPS and run.budget == conductor.Budget(60, 20, 30)
    [event] = _events(project, "conductor.started")
    assert event.actor.kind == "system" and event.input_blob is not None
    started = ConductorStarted.model_validate(event.payload)
    assert started.tier == "brief" and started.autonomy_level == "attended"
    assert project.blobs.exists(started.plan_blob)


def _events(project: Project, kind: str) -> list[Any]:
    from factory.events.reader import read_typed

    return read_typed(project.paths.events_dir, project.catalog, (kind,))


def test_begin_refuses_and_writes_nothing(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        conductor.begin_conductor(project, plan("understand"))  # no runner stage: never skipped
    with pytest.raises(FactoryValidationError):
        conductor.begin_conductor(project, plan("frame", skipped=("frame",)))
    wrong = FPlan(Tier.DEEP, (FStage("frame"),), FLimits())
    with pytest.raises(FactoryValidationError):
        conductor.begin_conductor(project, wrong)
    assert _events(project, "conductor.started") == []
    conductor.begin_conductor(project, plan("frame"))
    with pytest.raises(FactoryValidationError):
        conductor.begin_conductor(project, plan("frame"))


def test_status_without_a_conductor(project: Project) -> None:
    assert conductor.conductor_status(project).state == "none"


# ------------------------------------------------------------------------------------ steps


def test_every_step_advances_in_order_to_finished(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan(*STEPS))
    status = drive(project, fake)
    assert status.state == "finished" and status.steps_done == len(STEPS)
    # screen and extract are work-queue steps with nothing pending (the real counts): no run
    assert fake.stages == ["frame", "gather", "acquire", "write"]
    assert [c[1] for c in fake.calls] == [30, 30, 30, 30]
    assert len({c[2] for c in fake.calls}) == 4
    assert len(_events(project, "conductor.finished")) == 1


def test_queue_steps_run_when_work_is_idleing(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("screen"))
    status = conductor.advance(project, start_run=fake.start_run, pending=_busy, gate_closed=_open)
    assert status.state == "running" and fake.stages == ["screen"]


def test_one_run_at_a_time(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("frame", "gather"))
    first = conductor.advance(project, start_run=fake.start_run, pending=_idle, gate_closed=_open)
    assert first.state == "running" and first.run_id is not None
    fake.open.add(first.run_id)
    again = conductor.advance(project, start_run=fake.start_run, pending=_idle, gate_closed=_open)
    assert again.state == "running" and len(fake.calls) == 1


# -------------------------------------------------------------------------------- stop rules


@pytest.mark.parametrize("outcome", ["failed", "lost"])
def test_a_failed_or_lost_run_stops_and_is_retried_in_a_new_run(
    project: Project, fake: FakeRunner, outcome: str
) -> None:
    conductor.begin_conductor(project, plan("frame", "gather"))
    first = conductor.advance(project, start_run=fake.start_run, pending=_idle, gate_closed=_open)
    fake.outcomes[first.run_id or ""] = outcome
    status = drive(project, fake)
    assert status.state == "paused" and status.reason == f"{outcome}-run"
    assert len(fake.calls) == 1  # nothing was retried silently
    again = drive(project, fake)
    assert again.state == "paused" and len(_events(project, "conductor.paused")) == 1
    retried = drive(project, fake, retry=True)
    assert retried.state == "finished" and fake.stages == ["frame", "frame", "gather"]
    assert fake.calls[0][2] != fake.calls[1][2]
    attempts = [e.payload["attempt"] for e in _events(project, "conductor.step_started")]
    assert attempts == [1, 2, 1]


def test_the_run_budget_stops(settings: Settings, clock: FixedClock, fake: FakeRunner) -> None:
    project = make(settings, clock)
    conductor.begin_conductor(project, plan("frame", "gather", limits=FLimits(max_runs=1)))
    status = drive(project, fake)
    assert status.state == "paused" and status.reason == "budget" and len(fake.calls) == 1
    assert "1 runs" in status.lines[-1]


def test_the_time_budget_stops(project: Project, clock: FixedClock, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("frame", "gather", limits=FLimits(max_minutes=10)))
    conductor.advance(project, start_run=fake.start_run, pending=_idle, gate_closed=_open)
    clock.advance(timedelta(minutes=11))
    status = drive(project, fake)
    assert status.reason == "budget" and fake.stages == ["frame"]


def _fake_trust(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    module = types.ModuleType("factory.services.gate_trust")

    def trust_ledger(_project: Project) -> tuple[Any, ...]:
        return (types.SimpleNamespace(gate_id="mine.resolve", state=state),)

    module.trust_ledger = trust_ledger  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "factory.services.gate_trust", module)


def test_a_gate_in_pause_stops_everything(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_trust(monkeypatch, "pause")
    conductor.begin_conductor(project, plan("frame"))
    status = drive(project, fake)
    assert status.state == "paused" and status.reason == "trust-pause"
    assert status.gate_id == "mine.resolve" and fake.calls == []


def test_a_gate_in_watch_does_not_stop(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_trust(monkeypatch, "watch")
    conductor.begin_conductor(project, plan("frame"))
    assert drive(project, fake).state == "finished"


def test_a_runner_refusal_pauses_with_its_reason(project: Project, fake: FakeRunner) -> None:
    fake.refuse = "a run of this project is already open"
    conductor.begin_conductor(project, plan("frame"))
    status = drive(project, fake)
    assert status.state == "paused" and status.reason == "refused"
    assert "already open" in status.lines[-1]


# ------------------------------------------------------------------------------ human gates


def test_a_human_only_gate_makes_the_conductor_wait(project: Project, fake: FakeRunner) -> None:
    escalated: list[tuple[str, str]] = []
    conductor.begin_conductor(project, plan("frame", "gather"))
    closed = {"yes": False}

    def gate_closed(_p: Project, _stage: str, _gate: str) -> bool:
        return closed["yes"]

    def run() -> conductor.ConductorStatus:
        return conductor.advance(
            project,
            start_run=fake.start_run,
            pending=_idle,
            gate_closed=gate_closed,
            escalate=lambda _p, g, s: escalated.append((g, s)),
        )

    run()  # frame proposer started
    waiting = run()  # its run is complete; the protocol gate is a human's
    assert waiting.state == "waiting" and waiting.gate_id in {
        "protocol.ready",
        "protocol.press_confirm",
    }
    assert run().state == "waiting"
    assert fake.stages == ["frame"]  # no run for a human gate, none for the next stage
    assert len(escalated) == 1 and len(_events(project, "conductor.paused")) == 1
    closed["yes"] = True
    assert drive(project, fake, gate_closed=gate_closed).state == "finished"
    assert fake.stages == ["frame", "gather"]


def test_default_gate_closed_reads_a_later_human_act(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("frame"))
    conductor.advance(project, start_run=fake.start_run, pending=_idle, gate_closed=_open)
    assert not conductor.default_gate_closed(project, "frame", "protocol.ready")
    status = conductor.advance(
        project, start_run=fake.start_run, pending=_idle, escalate=lambda *_a: None
    )
    assert status.state == "waiting"


# ------------------------------------------------------------------------------- role runs


def test_roles_are_separate_runs_when_an_agent_closes_the_gate(
    settings: Settings, clock: FixedClock, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.gates as gates

    monkeypatch.setattr(gates, "effective_policy", policy(PolicyKind.AGENT))
    project = make(settings, clock, "autonomous")
    conductor.begin_conductor(project, plan("write"))
    status = drive(project, fake)
    assert status.state == "finished"
    assert fake.stages == ["write", "conduct-verify", "conduct-audit"]
    assert len({c[2] for c in fake.calls}) == 3
    roles = [e.payload["role"] for e in _events(project, "conductor.step_started")]
    assert roles == ["proposer", "verifier", "auditor"]


def test_attended_starts_no_role_runs(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.gates as gates

    monkeypatch.setattr(gates, "effective_policy", policy(PolicyKind.AGENT))
    conductor.begin_conductor(project, plan("write"))
    assert drive(project, fake).state == "finished"
    assert fake.stages == ["write"]


def test_no_role_run_for_a_human_only_gate(
    settings: Settings, clock: FixedClock, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.gates as gates

    monkeypatch.setattr(gates, "effective_policy", policy(PolicyKind.HUMAN))
    project = make(settings, clock, "autonomous")
    conductor.begin_conductor(project, plan("write"))
    status = drive(project, fake, gate_closed=lambda *_a: False)
    assert status.state == "waiting" and fake.stages == ["write"]


# ------------------------------------------------------------------- the log and the runner


def test_hand_written_events_change_nothing(project: Project) -> None:
    from factory.model.conductor import ConductorFinished, ConductorPaused

    human = project.human_actor()
    forged = ConductorStarted(
        conductor_id="cnd_" + "0" * 26,
        tier="brief",
        autonomy_level="attended",
        steps=("frame",),
        max_minutes=1,
        max_runs=1,
        max_units_per_run=1,
        plan_blob="sha256:" + "0" * 64,
    )
    with project.writing():
        project.record([project.events.make("conductor.started", forged, human)])
    assert conductor.conductor_status(project).state == "none"
    conductor.begin_conductor(project, plan("frame"))
    real = conductor.conductor_status(project).conductor_id
    with project.writing():
        project.record(
            [
                project.events.make(
                    "conductor.paused",
                    ConductorPaused(conductor_id=real or "", reason="budget"),
                    human,
                ),
                project.events.make(
                    "conductor.finished",
                    ConductorFinished(conductor_id=real or "", steps_done=1, runs=0),
                    human,
                ),
            ]
        )
    status = conductor.conductor_status(project)
    assert status.state == "running" and status.reason is None


def test_no_projection_table_or_handler_for_the_conductor() -> None:
    projection = default_projection()
    assert not [t for t in projection.metadata.tables if "conductor" in t]
    assert not [h for h in projection.handlers if h.startswith("conductor.")]


def test_the_stages_are_declared_without_the_gate_acts() -> None:
    for key in runner.CONDUCT_STAGES:
        spec = runner.STAGES[key]
        assert re.match(STAGE_KEY_RE, key) and runner.is_stage_key(key)
        assert spec.model == "claude-sonnet-5-5" and spec.fixed_cap == 1
        assert all(t.startswith("mcp__factory__") for t in spec.tools)
        assert not [t for t in spec.tools if re.search(r"release|press|amend|confirm|decide", t)]
    for key in ("conduct-verify", "conduct-audit"):
        writes = [
            t
            for t in runner.STAGES[key].tools
            if t.endswith(("_record", "_write", "_propose", "_create", "_run", "_fetch"))
        ]
        assert writes == []
    assert {runner.STAGES[k].skill for k in ("frame", "gather", "acquire")} == {
        "rf-frame",
        "rf-search-run",
        "rf-acquire",
    }
    RunnerStarted(
        run_id="rnr_" + "0" * 26,
        stage="conduct-verify",
        model="m",
        allowed_tools=("t",),
        prompt_blob="sha256:" + "0" * 64,
        unit_cap=1,
        counts_before={"conduct-verify": 1},
        command=("c",),
    )


def test_a_conductor_stage_cannot_be_started_by_hand(project: Project) -> None:
    for key in runner.CONDUCT_STAGES:
        assert runner.pending_units(project, key) == {key: 0}
    conductor.begin_conductor(project, plan("frame"))
    assert runner.pending_units(project, "frame") == {"frame": 0}


def test_the_platform_imports_no_model_sdk() -> None:
    root = Path(conductor.__file__).resolve().parents[1]
    sdk = re.compile(
        r"^\s*(import|from)\s+(anthropic|openai|claude_agent_sdk|claude_code_sdk)\b", re.M
    )
    offenders = [str(p) for p in root.rglob("*.py") if sdk.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
