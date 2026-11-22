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
from factory.model.conductor import ConductorStarted, ConductorStepStarted
from factory.model.levels import Tier
from factory.model.runner import STAGE_KEY_RE, RunnerStarted
from factory.modules.contract import GatePolicy, PolicyKind
from factory.services import conductor, runner
from factory.services.context import Project
from factory.services.project import init_project
from tests.helpers import SESSION

STEPS = ("frame", "gather", "screen", "acquire", "extract", "write")
RUN_STEPS = ("frame", "gather", "screen", "acquire", "automatic", "extract", "write")
"""`begin_conductor` adds the `automatic` step right after `acquire`."""


@dataclass(frozen=True)
class FStage:
    stage_id: str
    skill: str = "rf-x"
    caps: Mapping[str, int] = field(default_factory=dict)
    skipped: bool = False
    note: str = ""
    second_pass: bool = False
    phase: str | None = None


@dataclass(frozen=True)
class FLimits:
    max_papers: int = 30
    max_minutes: int = 60
    max_runs: int = 20


@dataclass(frozen=True)
class FPlan:
    tier: Tier
    stages: tuple[FStage, ...]
    limits: FLimits | None = FLimits()


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


@pytest.fixture(autouse=True)
def automatic_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Stands for the platform's deterministic step (`default_automatic`): records the calls."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        conductor,
        "default_automatic",
        lambda project, limit: calls.append((project.paths.slug, limit)),
    )
    return calls


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
    assert run.steps == RUN_STEPS and run.budget == conductor.Budget(60, 20, 30)
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
        conductor.begin_conductor(project, plan("no-such-stage"))  # no runner stage: never skipped
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
    assert status.state == "finished" and status.steps_done == len(RUN_STEPS)
    # screen and extract are work-queue steps with nothing pending (the real counts): no run
    assert fake.stages == ["frame", "gather", "acquire", "write"]
    assert [c[1] for c in fake.calls] == [30, 30, 30, 30]
    assert len({c[2] for c in fake.calls}) == 4
    assert len(_events(project, "conductor.finished")) == 1


def test_queue_steps_run_when_work_is_idleing(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("screen"))
    status = conductor.advance(project, start_run=fake.start_run, pending=_busy, gate_closed=_open)
    assert status.state == "running" and fake.stages == ["screen"]


def _phased() -> FPlan:
    return FPlan(
        Tier.BRIEF,
        (
            FStage("gather"),
            FStage("screen", phase="title-abstract"),
            FStage("acquire"),
            FStage("screen", phase="full-text"),
            FStage("extract"),
        ),
        FLimits(),
    )


def test_screen_runs_twice_around_acquire_with_its_own_step_keys(
    project: Project, fake: FakeRunner
) -> None:
    run = conductor.begin_conductor(project, _phased())
    assert run.steps == (
        "gather",
        "screen:title-abstract",
        "acquire",
        "automatic",
        "screen:full-text",
        "extract",
    )
    asked: list[str] = []

    def pending(_p: Project, stage: str) -> dict[str, int]:
        asked.append(stage)
        return {stage: 1 if stage.startswith("screen") else 0}

    for _ in range(12):
        status = conductor.advance(
            project, start_run=fake.start_run, pending=pending, gate_closed=_open,
            escalate=lambda *_a: None,
        )  # fmt: skip
        if status.state in ("finished", "paused", "waiting"):
            break
    assert status.state == "finished"
    # the full-text screen is a run of its own, after acquire; extract has nothing pending
    assert fake.stages == ["gather", "screen", "acquire", "screen-ft"]
    assert "screen" in asked and "screen-ft" in asked
    started = [
        ConductorStepStarted.model_validate(e.payload)
        for e in _events(project, "conductor.step_started")
    ]
    assert [e.stage_id for e in started] == [
        "gather", "screen:title-abstract", "acquire", "automatic", "screen:full-text",
    ]  # fmt: skip


def test_a_phased_screen_step_without_pending_work_completes_without_a_run(
    project: Project, fake: FakeRunner
) -> None:
    conductor.begin_conductor(project, _phased())
    status = drive(project, fake)
    assert status.state == "finished" and fake.stages == ["gather", "acquire"]


def test_screen_ft_pending_is_the_full_text_queue_only(project: Project) -> None:
    pending = runner.pending_units(project, "screen-ft")
    assert list(pending) == [runner.STAGES["screen-ft"].kinds[0]]
    assert runner.STAGES["screen-ft"].tools == runner.STAGES["screen"].tools
    assert runner.STAGES["screen-ft"].skill == "rf-screen"


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
        if key == "extract-b":  # a work queue of its own: see the second-pass tests
            continue
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


# ------------------------------------------------------------------- understand, develop, maintain

LATER = ("understand", "develop", "maintain")
HUMAN_ONLY_ACTS = re.compile(  # `selection_resolve` is a read of the corpus selection, no act
    r"lead_decide|hypothesis_register|miner_(admit|register)|_confirm|_release|(?<!selection)_resolve|_decide"
    r"|protocol_(amend|record)|review_decide|reference_decide|relation_decide|idea_decide"
)


@pytest.mark.parametrize(
    "stages",
    [
        ("frame", "gather", "screen", "acquire", "extract", "develop", "write"),  # deep
        ("frame", "gather", "screen", "acquire", "extract", *LATER, "write"),  # pilot, systematic
    ],
)
def test_the_later_stages_now_begin(project: Project, stages: tuple[str, ...]) -> None:
    run = conductor.begin_conductor(project, plan(*stages))
    assert run.steps == tuple(
        x for s in stages for x in ((s, "automatic") if s == "acquire" else (s,))
    )


def test_a_stage_without_a_spec_is_still_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        conductor.begin_conductor(project, plan("develop", "no-such-stage"))
    assert _events(project, "conductor.started") == []


def test_understand_and_maintain_start_one_run_each(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("understand", "maintain"))
    assert drive(project, fake).state == "finished"
    assert fake.stages == ["understand", "maintain"]
    assert runner.STAGES["understand"].skill == "rf-lineage"
    assert runner.STAGES["maintain"].skill == "rf-living"
    assert {
        "mcp__factory__relation_propose",
        "mcp__factory__idea_propose",
    } <= set(runner.STAGES["understand"].tools)
    assert {
        "mcp__factory__watch_run",
        "mcp__factory__feed_run",
        "mcp__factory__digest_get",
    } <= set(runner.STAGES["maintain"].tools)


def test_develop_is_three_runs_in_three_sessions(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.gates as gates

    monkeypatch.setattr(gates, "effective_policy", policy(PolicyKind.AGENT))
    conductor.begin_conductor(project, plan("develop"))
    assert drive(project, fake).state == "finished"
    assert fake.stages == ["develop-lead", "develop-draft", "develop-critic"]
    assert len({c[2] for c in fake.calls}) == 3
    roles = [e.payload["role"] for e in _events(project, "conductor.step_started")]
    assert roles == ["lead", "drafter", "critic"]
    assert [runner.STAGES[k].role for k in fake.stages] == ["lead-author", "drafter", "critic"]
    assert {runner.STAGES[k].skill for k in fake.stages} == {"rf-hypothesis-engine", "rf-critic"}


def test_develop_waits_for_a_human_to_promote_leads_before_the_drafter(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.gates as gates

    monkeypatch.setattr(gates, "effective_policy", policy(PolicyKind.HUMAN))
    conductor.begin_conductor(project, plan("develop"))
    status = drive(project, fake, gate_closed=lambda *_a: False)
    assert status.state == "waiting" and status.gate_id == "hypotheses.lead_decide"
    assert fake.stages == ["develop-lead"]
    opened: set[str] = {"hypotheses.lead_decide"}
    status = drive(project, fake, gate_closed=lambda _p, _s, g: g in opened)
    assert status.state == "waiting" and status.gate_id == "hypotheses.register"
    assert fake.stages == ["develop-lead", "develop-draft", "develop-critic"]
    opened.add("hypotheses.register")
    assert drive(project, fake, gate_closed=lambda _p, _s, g: g in opened).state == "finished"
    assert fake.stages.count("develop-critic") == 1


def test_a_human_gate_of_a_later_step_does_not_skip_the_step(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.gates as gates

    monkeypatch.setattr(gates, "effective_policy", policy(PolicyKind.HUMAN))
    conductor.begin_conductor(project, plan("develop", "maintain"))
    drive(project, fake, gate_closed=lambda *_a: False)
    assert "maintain" not in fake.stages


def test_no_later_stage_allow_list_holds_a_human_only_act() -> None:
    for key in ("understand", "develop-lead", "develop-draft", "develop-critic", "maintain"):
        assert key in runner.CONDUCT_STAGES
        names = [t.removeprefix("mcp__factory__") for t in runner.STAGES[key].tools]
        assert not [n for n in names if HUMAN_ONLY_ACTS.search(n)], key
        assert "hypothesis_review" not in names or key == "develop-critic"
    assert HUMAN_ONLY_ACTS.search("lead_decide") and HUMAN_ONLY_ACTS.search("hypothesis_register")
    assert "hypothesis_review" not in {
        t.removeprefix("mcp__factory__")
        for k in ("develop-lead", "develop-draft")
        for t in runner.STAGES[k].tools
    }
    assert conductor.STEP_GATES["develop"] == ("hypotheses.register",)


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


# ------------------------------------------------------------------------------ the second pass


def second_plan(*, limits: FLimits | None = None, unlimited: bool = False) -> FPlan:
    stages = tuple(FStage(i, second_pass=i == "extract") for i in STEPS)
    return FPlan(Tier.BRIEF, stages, None if unlimited else limits or FLimits())


def test_a_second_pass_is_a_separate_run_after_the_proposer(
    project: Project, fake: FakeRunner
) -> None:
    run = conductor.begin_conductor(project, second_plan())
    started = ConductorStarted.model_validate(_events(project, "conductor.started")[0].payload)
    assert started.second_pass_steps == ("extract",) and run.steps == RUN_STEPS
    status = drive(project, fake)
    assert status.state == "finished"
    # `extract` has nothing pending for pass A (no run), but pass B is opened by its own run
    assert fake.stages == ["frame", "gather", "acquire", "extract-b", "write"]
    roles = [
        (e.payload["stage_id"], e.payload["role"])
        for e in _events(project, "conductor.step_started")
    ]
    assert ("extract", "second-pass") in roles


def test_the_second_pass_runs_at_every_autonomy_level(
    settings: Settings, clock: FixedClock, fake: FakeRunner
) -> None:
    project = make(settings, clock, level="autonomous")
    assert conductor.roles_of(
        project, "extract", conductor.AutonomyLevel.ATTENDED, second_pass=True
    ) == (
        "proposer",
        "second-pass",
    )
    assert "second-pass" not in conductor.roles_of(
        project, "extract", conductor.AutonomyLevel.ATTENDED
    )


def test_the_second_pass_stage_uses_another_model_and_the_extraction_tools() -> None:
    first, second = runner.STAGES["extract"], runner.STAGES["extract-b"]
    assert second.model != first.model and second.tools == first.tools
    assert "extract-b" in runner.CONDUCT_STAGES
    assert conductor.SECOND_PASS_STAGE["extract"] == "extract-b"


def test_a_second_pass_without_a_runner_stage_is_refused(project: Project) -> None:
    stages = tuple(FStage(i, second_pass=i == "frame") for i in STEPS)
    with pytest.raises(FactoryValidationError):
        conductor.begin_conductor(project, FPlan(Tier.BRIEF, stages))
    assert _events(project, "conductor.started") == []


def test_a_plan_without_limits_has_the_default_budget(project: Project) -> None:
    run = conductor.begin_conductor(project, second_plan(unlimited=True))
    assert run.budget.max_runs == conductor.UNCAPPED_RUNS
    assert run.budget.max_minutes == conductor.UNCAPPED_MINUTES


# --------------------------------------------------------------------- the automatic step


def test_the_automatic_step_runs_once_between_acquire_and_full_text(
    project: Project, fake: FakeRunner
) -> None:
    order: list[str] = []
    base = fake.start_run

    def start(p: Project, stage: str, *, unit_cap: int) -> str:
        order.append(stage)
        return base(p, stage, unit_cap=unit_cap)

    def automatic(_p: Project, limit: int) -> None:
        order.append(f"automatic:{limit}")

    plan_ = FPlan(
        Tier.BRIEF,
        (
            FStage("gather"),
            FStage("screen", phase="title-abstract"),
            FStage("acquire", caps={"max_included": 7}),
            FStage("screen", phase="full-text"),
        ),
        FLimits(),
    )
    conductor.begin_conductor(project, plan_)
    for _ in range(12):
        status = conductor.advance(
            project, start_run=start, pending=_busy, gate_closed=_open, automatic=automatic,
            escalate=lambda *_a: None,
        )  # fmt: skip
        if status.state == "finished":
            break
    assert status.state == "finished"
    assert order == ["gather", "screen", "acquire", "automatic:7", "screen-ft"]
    steps = [
        (e.payload["role"], e.payload.get("run_id"))
        for e in _events(project, "conductor.step_started")
    ]
    assert ("automatic", None) in steps
    assert {e.actor.kind for e in _events(project, "conductor.step_finished")} == {"system"}
    # it is no run: the budget counts the four runs only
    assert status.runs == 4


def test_a_plan_without_acquire_has_no_automatic_step(project: Project, fake: FakeRunner) -> None:
    run = conductor.begin_conductor(project, plan("frame", "gather"))
    assert "automatic" not in run.steps
    drive(project, fake)
    assert fake.stages == ["frame", "gather"]


def test_a_failing_automatic_step_pauses_and_retries_once_per_advance(
    project: Project, fake: FakeRunner
) -> None:
    calls: list[int] = []

    def boom(_p: Project, limit: int) -> None:
        calls.append(limit)
        raise RuntimeError("network down")

    conductor.begin_conductor(project, plan("acquire", "write"))
    kw: dict[str, Any] = dict(
        start_run=fake.start_run, pending=_idle, gate_closed=_open, escalate=lambda *_a: None
    )
    status = conductor.advance(project, automatic=boom, **kw)  # acquire starts
    status = conductor.advance(project, automatic=boom, **kw)  # acquire closed; automatic fails
    assert status.state == "paused" and status.reason == "failed-run"
    assert calls == [30] and fake.stages == ["acquire"]
    again = conductor.advance(project, automatic=boom, **kw)
    assert again.state == "paused" and calls == [30]  # not retried without `retry`
    ok = conductor.advance(project, retry=True, automatic=lambda *_a: None, **kw)
    assert ok.state in ("running", "finished")
    drive(project, fake)
    assert fake.stages == ["acquire", "write"]
    assert {e.actor.kind for e in _events(project, "conductor.paused")} == {"system"}


def test_every_runner_stage_key_is_accepted_by_the_stage_key_pattern() -> None:
    """`RunnerStarted` validates the stage against `STAGE_KEY_RE`: a stage in the runner's table
    that the pattern rejects would fail a real `start_run` while the fake runner hides it (the
    `screen-ft` and `extract-b` omissions)."""
    import re

    from factory.model.runner import STAGE_KEY_RE

    bad = sorted(k for k in runner.STAGES if not re.match(STAGE_KEY_RE, k))
    assert bad == []
    bad_conduct = sorted(k for k in runner.CONDUCT_STAGES if not re.match(STAGE_KEY_RE, k))
    assert bad_conduct == []


# ------------------------------------------- a queue step runs again until its queue is empty


class Queue:
    """A work queue of `n` units that each fake run works off `per_run` of (the unit cap of the
    run): the `pending` seam the conductor reads and the effect of the fake runner."""

    def __init__(self, fake: FakeRunner, n: int, per_run: int | None = None) -> None:
        self.left = n
        self.per_run = per_run
        self.runs = 0
        self.fake = fake

    def pending(self, _p: Project, stage: str) -> dict[str, int]:
        return {stage: self.left if stage in ("screen", "screen-ft", "extract") else 0}

    def start_run(self, project: Project, stage: str, *, unit_cap: int) -> str:
        run_id = self.fake.start_run(project, stage, unit_cap=unit_cap)
        if stage == "screen":
            self.runs += 1
            self.left = max(0, self.left - (unit_cap if self.per_run is None else self.per_run))
        return run_id


def _run_screen(project: Project, fake: FakeRunner, queue: Queue, limit: int = 30) -> Any:
    status = None
    for _ in range(limit):
        status = conductor.advance(
            project, start_run=queue.start_run, pending=queue.pending, gate_closed=_open,
            escalate=lambda *_a: None,
        )  # fmt: skip
        if status.state in ("finished", "paused", "waiting"):
            break
    return status


def test_a_queue_step_runs_again_while_units_are_pending_and_progress_is_made(
    project: Project, fake: FakeRunner
) -> None:
    conductor.begin_conductor(project, plan("screen"))  # unit cap 30 per run
    queue = Queue(fake, 70)
    status = _run_screen(project, fake, queue)
    assert status.state == "finished"
    assert fake.stages == ["screen", "screen", "screen"]  # 70 -> 40 -> 10 -> 0
    assert queue.left == 0


def test_a_queue_step_stops_when_a_run_made_no_progress(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("screen"))
    queue = Queue(fake, 70, per_run=0)  # e.g. a stopping rule: units remain, nothing is served
    status = _run_screen(project, fake, queue)
    assert status.state == "finished" and fake.stages == ["screen"]


def test_a_queue_step_stops_at_the_tier_cap(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    conductor.begin_conductor(project, plan("screen"))
    queue = Queue(fake, 500)
    monkeypatch.setattr(conductor, "queue_cap_reached", lambda _p, _s: queue.runs >= 2)
    status = _run_screen(project, fake, queue)
    assert status.state == "finished" and fake.stages == ["screen", "screen"]
    assert queue.left == 440  # the cap, not the queue, ended the step


def test_a_queue_step_stops_at_the_run_budget(project: Project, fake: FakeRunner) -> None:
    conductor.begin_conductor(project, plan("screen", limits=FLimits(max_runs=2)))
    queue = Queue(fake, 500)
    status = _run_screen(project, fake, queue)
    assert status.state == "paused" and status.reason == "budget"
    assert fake.stages == ["screen", "screen"]


# ----------------------- a waiting human-only gate is an item of the human queue (read-only)


def test_a_waiting_human_gate_is_a_human_queue_item_until_a_human_acts(
    project: Project, fake: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services.human_queue import Gate, human_queue

    acted = {"done": False}
    monkeypatch.setattr(conductor, "default_gate_closed", lambda _p, _s, _g: acted["done"])
    assert [i for i in human_queue(project).items if i.gate is Gate.CONDUCTOR_WAITING] == []
    conductor.begin_conductor(project, plan("frame"))
    status = drive(project, fake, gate_closed=lambda *_a: False)
    assert status.state == "waiting" and status.gate_id == "protocol.ready"
    before = len(_events(project, "conductor.paused"))
    [item] = [i for i in human_queue(project).items if i.gate is Gate.CONDUCTOR_WAITING]
    assert (item.count, item.stage) == (1, "frame")
    assert item.command.startswith("factory --project demo protocol ")
    assert len(_events(project, "conductor.paused")) == before  # read-only: nothing written
    assert [i for i in human_queue(project, agent=True).items if i.gate is Gate.CONDUCTOR_WAITING]
    acted["done"] = True  # the human act: the gate closes and the item goes
    assert [i for i in human_queue(project).items if i.gate is Gate.CONDUCTOR_WAITING] == []


def test_the_conductor_calls_no_missing_escalation_hook() -> None:
    import inspect

    assert "escalate_waiting" not in inspect.getsource(conductor)


# --------------------------- the run budget of a tier covers its whole plan at every autonomy level


def _runs_a_full_plan_needs(project: Project, tier: Tier) -> int:
    """The role runs of every live step of the tier's plan, as the conductor derives them (the
    proposer, the second pass, the verifier and the auditor; `automatic` is no run)."""
    from factory.model.levels import AutonomyLevel
    from factory.tiers.resolve import plan_for

    plan_ = plan_for(tier)
    run = conductor.begin_conductor(project, plan_)
    level = AutonomyLevel(run.autonomy_level)
    second = {conductor.step_key(s) for s in plan_.stages if s.second_pass and not s.skipped}
    return sum(
        len([r for r in conductor.roles_of(project, step, level, second_pass=step in second)
             if r != "automatic"])
        for step in run.steps
    )  # fmt: skip


@pytest.mark.parametrize("tier", [Tier.BRIEF, Tier.DEEP])
@pytest.mark.parametrize("level", ["attended", "supervised", "autonomous"])
def test_the_run_limit_of_a_tier_covers_its_plan_at_each_level(
    settings: Settings, clock: FixedClock, tier: Tier, level: str
) -> None:
    from factory.tiers.resolve import plan_for

    project = init_project(
        settings, "demo", None, session=SESSION, clock=clock, tier=tier.value, autonomy_level=level
    )
    needed = _runs_a_full_plan_needs(project, tier)
    limits = plan_for(tier).limits
    assert limits is not None
    # one extra run of slack per queue step for the repeated run of a long queue is not counted
    # here: the number is the plan alone, so that no tier pauses for budget before `write`
    assert limits.max_runs >= needed, f"{tier.value} at {level}: {limits.max_runs} < {needed}"
