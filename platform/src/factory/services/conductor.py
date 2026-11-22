"""The lifecycle conductor (plan tiers-and-autonomy C8, spec slice-9 section 7).

`begin_conductor` takes a tier's plan; `advance` then moves it one step at a time through
`factory.services.runner`: each step is one capped headless `claude -p` run (a proposer). Where an
agent may close a gate of the step at the study's autonomy level (`effective_policy` is not
`human`, and the level is `supervised` or `autonomous`), a second run of a verifier and a third of
an auditor follow, each a distinct run and MCP session (`spar_v2.advance` is the pattern). The
conductor is bookkeeping: it starts runs, counts and stops; every judgement is a role's.

Invariants:
- State is derived, never stored: the `conductor.*` system events are read from the log (no
  projection table, so no state hash moves). A hand-written event (non-system actor) is ignored.
- One step at a time, one open run: `advance` starts nothing while the conductor's run is open
  (or any run of the project: the runner refuses, and the refusal pauses with reason `refused`).
- The stop rules are computed: a failed or lost run (retried only by `advance(retry=True)`, as a
  new run in a new session), a spent budget (`max_runs`, `max_minutes`), any gate whose trust state
  is `pause`, and a human-only gate of a finished step (the conductor waits, escalates once to the
  deferred queue when that exists, and never starts a run for it). A stage is never skipped.
- The conductor records no human act and writes only `conductor.*` system events. The platform
  calls no model: a step is an outside process.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Event
from factory.events.reader import read_all, read_typed
from factory.model.base import StrictModel
from factory.model.conductor import (
    ConductorFinished,
    ConductorPaused,
    ConductorRole,
    ConductorStarted,
    ConductorStepFinished,
    ConductorStepStarted,
    PauseReason,
    StepOutcome,
)
from factory.model.levels import AutonomyLevel
from factory.modules.contract import PolicyKind
from factory.services import runner
from factory.services.context import Project
from factory.services.project import project_levels

EVENT_TYPES: Final = (
    "conductor.started",
    "conductor.step_started",
    "conductor.step_finished",
    "conductor.paused",
    "conductor.finished",
)

STEP_STAGE: Final[Mapping[str, str]] = {
    "frame": "frame",
    "gather": "gather",
    "screen": "screen",
    "screen:title-abstract": "screen",
    "screen:full-text": "screen-ft",
    "acquire": "acquire",
    "extract": "extract",
    "write": "write",
    "understand": "understand",
    "develop": "develop-lead",
    "maintain": "maintain",
}
"""The steps of a plan the conductor can run, and the runner stage of each (for `develop` the first
of its three role stages: `_DEVELOP_STAGES`). A step is a stage id, or `<stage id>:<phase>` for the
`screen` stage of a plan that screens full text after `acquire` (`StagePlan.step_key`); the bare
`screen` is the step of a log or plan without phases and screens both phases in one run."""

SECOND_PASS_STAGE: Final[Mapping[str, str]] = {"extract": "extract-b"}
"""The runner stage of the `second-pass` run of a step (extraction pass B)."""

_DEVELOP_STAGES: Final[Mapping[str, str]] = {
    "lead": "develop-lead",
    "drafter": "develop-draft",
    "critic": "develop-critic",
}
"""The runner stage of each role run of the develop step: lead author, drafter and critic are
three runs in three sessions. None of them may decide a lead or register a hypothesis (those
gates are the researcher's and stay out of every allow-list: v1 never lets an agent pass them)."""

STEP_GATES: Final[Mapping[str, tuple[str, ...]]] = {
    "frame": ("protocol.ready", "protocol.press_confirm"),
    "gather": ("import.resolution_confirm",),
    "extract": ("mine.resolve",),
    "write": ("writing.release", "manuscript.citation_confirm"),
    "develop": ("hypotheses.register",),
}
"""The gates that close after a step (`hypotheses.lead_decide` closes inside `develop`: see
`_ROLE_GATES`). `understand` and `maintain` close none: relations and ideas are confirmed by the
researcher on the command line, outside the step.

The gates that close in a step. A gate id no policy names is `human` (`presets.preset`), so an
id listed here that does not exist yet (`protocol.press_confirm`) fails safe: the conductor
waits."""

_ROLE_GATES: Final[Mapping[tuple[str, str], tuple[str, ...]]] = {
    ("develop", "drafter"): ("hypotheses.lead_decide",),
}
"""Gates that must be closed before a role run of a step starts: a drafter works only from a
promoted lead, and promoting is the researcher's act. A human-only gate here makes the conductor
wait before the role run, not after the step."""
_QUEUE_UNITS: Final = ("screen", "screen:title-abstract", "screen:full-text", "extract")
_PENDING_STAGE: Final[Mapping[str, str]] = {
    "screen:title-abstract": "screen",
    "screen:full-text": "screen-ft",
}
"""The runner stage whose work queue a queue step waits on (the step itself when not listed)."""
"""Steps whose pending units are a work queue: with nothing pending the step is complete."""

_STARTING: ContextVar[tuple[PendingUnits, GateClosed] | None] = ContextVar(
    "conductor_starting", default=None
)
"""Set only while `advance` calls the runner: the seams it decided with, so that the runner's
pending-unit question is answered from the same state."""


class StageLike(Protocol):
    @property
    def stage_id(self) -> str: ...
    @property
    def skipped(self) -> bool: ...
    @property
    def caps(self) -> Mapping[str, int]: ...
    @property
    def skill(self) -> str: ...
    @property
    def note(self) -> str: ...


def step_key(stage: StageLike) -> str:
    """The step identity of a plan stage: its id, plus `:<phase>` when it has a phase (a plan type
    without the field has none)."""
    phase = getattr(stage, "phase", None)
    return stage.stage_id if phase is None else f"{stage.stage_id}:{phase}"


def stage_of_step(step: str) -> str:
    """The lifecycle stage id of a step key (`screen:full-text` is stage `screen`)."""
    return step.split(":", 1)[0]


class LimitsLike(Protocol):
    @property
    def max_papers(self) -> int: ...
    @property
    def max_minutes(self) -> int: ...
    @property
    def max_runs(self) -> int: ...


class PlanLike(Protocol):
    """The shape of `factory.tiers.model.TierPlan` the conductor reads (contract C3)."""

    @property
    def tier(self) -> Any: ...
    @property
    def stages(self) -> Sequence[StageLike]: ...
    @property
    def limits(self) -> LimitsLike | None:
        """None means the plan has no budget (`pilot`, `systematic`): the conductor then applies
        the defaults `UNCAPPED_*`, never an unlimited run."""
        ...


UNCAPPED_MINUTES: Final = 24 * 60
UNCAPPED_RUNS: Final = 200
UNCAPPED_PAPERS: Final = runner.MAX_UNIT_CAP
"""The budget of a plan without limits: a plan with no cap still stops, at a day and 200 runs."""


@dataclass(frozen=True)
class Budget:
    max_minutes: int
    max_runs: int
    max_units_per_run: int


@dataclass(frozen=True)
class ConductorRun:
    conductor_id: str
    tier: str
    autonomy_level: str
    steps: tuple[str, ...]
    budget: Budget


class ConductorStatus(StrictModel):
    conductor_id: str | None
    state: Literal["none", "running", "waiting", "paused", "finished"]
    steps: tuple[str, ...] = ()
    steps_done: int = 0
    stage_id: str | None = None
    role: ConductorRole | None = None
    run_id: str | None = None
    runs: int = 0
    minutes: float = 0.0
    reason: str | None = None
    gate_id: str | None = None
    lines: tuple[str, ...] = ()


StartRun = Callable[..., str]
Automatic = Callable[[Project, int], None]
"""The deterministic step between `acquire` and full-text screening: takes the project and the
limit of works; raises to fail. The default is `default_automatic`."""
AUTOMATIC_STEP: Final = "automatic"
PendingUnits = Callable[[Project, str], dict[str, int]]
GateClosed = Callable[[Project, str, str], bool]
Escalate = Callable[[Project, str, str], None]


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# ------------------------------------------------------------------------------ derived state


@dataclass
class _Trail:
    started: Event
    meta: ConductorStarted
    events: list[Event]  # this run's later events, in id order

    def payloads(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.type == f"conductor.{kind}"]


def _load(project: Project) -> _Trail | None:
    """The latest conductor run that is not finished. System events only."""
    events = [
        e
        for e in read_typed(project.paths.events_dir, project.catalog, EVENT_TYPES)
        if e.actor.kind == "system"
    ]
    current: _Trail | None = None
    for event in events:
        if event.type == "conductor.started":
            current = _Trail(event, ConductorStarted.model_validate(event.payload), [])
        elif current is not None and event.payload.get("conductor_id") == current.meta.conductor_id:
            current.events.append(event)
    if current is None or current.payloads("finished"):
        return None
    return current


def _closed_roles(trail: _Trail) -> set[tuple[int, str]]:
    done = (
        ConductorStepFinished.model_validate(e.payload) for e in trail.payloads("step_finished")
    )
    return {(f.step, f.role) for f in done if f.outcome == "complete"}


def _open_run(trail: _Trail) -> ConductorStepStarted | None:
    finished = {e.payload.get("run_id") for e in trail.payloads("step_finished")}
    for event in reversed(trail.payloads("step_started")):
        payload = ConductorStepStarted.model_validate(event.payload)
        if payload.run_id is None:  # an `automatic` step runs in `advance`, never left open
            return None
        if payload.run_id not in finished:
            return payload
        return None
    return None


def _policy_kinds(project: Project, stage_id: str) -> dict[str, PolicyKind]:
    from factory.services.gates import effective_policy

    gates = STEP_GATES.get(stage_of_step(stage_id), ())
    return {g: effective_policy(project, g).kind for g in gates}


def effective_kind(project: Project, gate_id: str) -> PolicyKind:
    from factory.services.gates import effective_policy

    return effective_policy(project, gate_id).kind


def roles_of(
    project: Project, stage_id: str, level: AutonomyLevel, *, second_pass: bool = False
) -> tuple[ConductorRole, ...]:
    """The role runs of a step: always the proposer; the `second-pass` run right after it when the
    plan asks for one (whatever the level); a verifier and an auditor, each its own run, when the
    level is not `attended` and an agent may close some gate of the step."""
    stage_id = stage_of_step(stage_id)
    if stage_id == AUTOMATIC_STEP:
        return ("automatic",)
    if stage_id == "develop":
        return ("lead", "drafter", "critic")
    first: tuple[ConductorRole, ...] = ("proposer", "second-pass") if second_pass else ("proposer",)
    kinds = _policy_kinds(project, stage_id)
    if level is not AutonomyLevel.ATTENDED and any(
        k is not PolicyKind.HUMAN for k in kinds.values()
    ):
        return (*first, "verifier", "auditor")
    return first


def _stage_of(stage_id: str, role: ConductorRole) -> str:
    if stage_id not in STEP_STAGE:
        stage_id = stage_of_step(stage_id)
    if stage_id == "develop":
        return _DEVELOP_STAGES[role]
    if role == "second-pass":
        return SECOND_PASS_STAGE[stage_of_step(stage_id)]
    if role == "verifier":
        return "conduct-verify"
    if role == "auditor":
        return "conduct-audit"
    return STEP_STAGE[stage_id]


def draw_platform_audits(project: Project, stage_id: str) -> list[str]:
    """The platform's audit draw (finding I2, contract C4): for each `agent_audit` gate of the
    step with agent acts, the conductor (the system actor) draws the sample through
    `gates.gate_audit_sample_platform`. Returns the gates sampled. A gate with nothing to audit or
    an unchanged population is skipped (the draw refuses it; nothing is written)."""
    from factory.services.gates import gate_audit_sample_platform

    drawn: list[str] = []
    for gate_id, kind in _policy_kinds(project, stage_id).items():
        if kind is not PolicyKind.AGENT_AUDIT:
            continue
        try:
            gate_audit_sample_platform(project, gate_id)
        except FactoryValidationError:
            continue
        drawn.append(gate_id)
    return drawn


def _trust_pauses(project: Project) -> list[str]:
    try:
        module: Any = importlib.import_module("factory.services.gate_trust")
    except ModuleNotFoundError:
        return []
    return [str(t.gate_id) for t in module.trust_ledger(project) if t.state == "pause"]


_CHECK_ACTS: Final[Mapping[str, tuple[str, ...]]] = {
    "protocol.ready": ("protocol.recorded", "protocol.amended"),
}
"""The one step gate that is a check, not a declared gate: a recorded or amended protocol closes
it."""


def gate_act_closes(gate_id: str, event_type: str, actor_kind: str) -> bool:
    """Whether an event closes `gate_id`: a human actor and one of the gate's own act events
    (`GateSpec.act_events`, the module declarations). A gate the registry does not know is never
    closed here: it stays human (decision 84.6) and waits."""
    from factory.services.modules.default import default_modules

    try:
        acts = default_modules().gate(gate_id).act_events
    except KeyError:
        acts = _CHECK_ACTS.get(gate_id, ())
    return actor_kind == "human" and event_type in acts


def default_gate_closed(project: Project, stage_id: str, gate_id: str) -> bool:
    """Whether a human has acted on `gate_id` since the step's proposer finished: a human-actor
    event of one of the gate's own act event types (`gate_act_closes`) after the last
    `conductor.step_finished` of the step. A namespace match is not enough: another human event
    of the same module (an import, a draft) does not close the gate."""
    trail = _load(project)
    if trail is None:
        return False
    steps = trail.meta.steps
    index = steps.index(stage_id) if stage_id in steps else -1
    after = max(
        (e.id for e in trail.payloads("step_finished") if e.payload["step"] == index),
        default=None,
    )
    if after is None:
        return False
    return any(
        gate_act_closes(gate_id, e.type, e.actor.kind)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.id > after
    )


@dataclass(frozen=True)
class _Decision:
    kind: Literal["finished", "running", "start", "pause", "wait", "complete-empty", "automatic"]
    step: int | None = None
    stage_id: str | None = None
    role: ConductorRole | None = None
    reason: PauseReason | None = None
    gate_id: str | None = None
    detail: str = ""
    run_id: str | None = None


def _runs_started(trail: _Trail) -> int:
    """The runs started: the `automatic` step is no run and does not count."""
    return sum(1 for e in trail.payloads("step_started") if e.payload["role"] != "automatic")


def _minutes(project: Project, trail: _Trail) -> float:
    return (project.clock.now() - trail.started.ts).total_seconds() / 60.0


def _decide(
    project: Project,
    trail: _Trail,
    *,
    retry: bool,
    pending: PendingUnits,
    gate_closed: GateClosed,
) -> _Decision:
    meta = trail.meta
    level = AutonomyLevel(meta.autonomy_level)
    open_run = _open_run(trail)
    if open_run is not None:
        return _Decision(
            "running", open_run.step, open_run.stage_id, open_run.role, run_id=open_run.run_id
        )
    closed = _closed_roles(trail)
    position: tuple[int, str, ConductorRole] | None = None
    waiting_gate: str | None = None
    for index, stage_id in enumerate(meta.steps):
        roles = roles_of(project, stage_id, level, second_pass=stage_id in meta.second_pass_steps)
        todo = next((r for r in roles if (index, r) not in closed), None)
        if todo is not None:
            pre = [
                g
                for g in _ROLE_GATES.get((stage_id, todo), ())
                if effective_kind(project, g) is PolicyKind.HUMAN
                and not gate_closed(project, stage_id, g)
            ]
            if pre:
                waiting_gate = pre[0]
            position = (index, stage_id, todo)
            break
        human = [g for g, k in _policy_kinds(project, stage_id).items() if k is PolicyKind.HUMAN]
        waiting_gate = next((g for g in human if not gate_closed(project, stage_id, g)), None)
        if waiting_gate is not None:
            position = (index, stage_id, "proposer")
            break
    if position is None:
        return _Decision("finished")
    index, stage_id, role = position
    paused_gates = _trust_pauses(project)
    if paused_gates:
        return _Decision(
            "pause", index, stage_id, role, "trust-pause", paused_gates[0],
            f"trust state pause: {', '.join(paused_gates)}",
        )  # fmt: skip
    if waiting_gate is not None:
        return _Decision("wait", index, stage_id, None, "human-gate", waiting_gate,
                         f"gate {waiting_gate} awaits a human")  # fmt: skip
    last = [
        e
        for e in trail.payloads("step_finished")
        if e.payload["step"] == index and e.payload["role"] == role
    ]
    if last and not retry:
        outcome = last[-1].payload["outcome"]
        return _Decision(
            "pause",
            index,
            stage_id,
            role,
            "lost-run" if outcome == "lost" else "failed-run",
            detail=f"the {role} run of {stage_id} {outcome}; advance with retry",
        )
    if role == "automatic":  # no process: neither the run budget nor a queue applies
        return _Decision("automatic", index, stage_id, role)
    if _runs_started(trail) >= meta.max_runs:
        return _Decision(
            "pause", index, stage_id, role, "budget", detail=f"{meta.max_runs} runs started"
        )
    if _minutes(project, trail) >= meta.max_minutes:
        return _Decision(
            "pause", index, stage_id, role, "budget", detail=f"{meta.max_minutes} minutes spent"
        )
    if (
        role == "proposer"
        and stage_id in _QUEUE_UNITS
        and sum(pending(project, _PENDING_STAGE.get(stage_id, stage_id)).values()) == 0
    ):
        return _Decision("complete-empty", index, stage_id, role)
    return _Decision("start", index, stage_id, role)


# ----------------------------------------------------------------------- the runner's pending


def pending_units(project: Project, stage: str) -> int:
    """The pending unit of a conductor stage (`runner.CONDUCT_STAGES`): 1 while the conductor is
    starting exactly that role run, else 0 (so a hand start of the stage is refused)."""
    seams = _STARTING.get()
    if seams is None:
        return 0
    trail = _load(project)
    if trail is None:
        return 0
    decision = _decide(project, trail, retry=True, pending=seams[0], gate_closed=seams[1])
    if decision.kind != "start" or decision.stage_id is None or decision.role is None:
        return 0
    return int(_stage_of(decision.stage_id, decision.role) == stage)


# ------------------------------------------------------------------------------------ commands


def _second_pass(stage: StageLike) -> bool:
    """Whether the plan's stage asks for a second pass (a plan type without the field has none)."""
    return bool(getattr(stage, "second_pass", False))


def _plan_blob(project: Project, plan: PlanLike, steps: Sequence[str]) -> str:
    view: dict[str, JsonValue] = {
        "tier": str(getattr(plan.tier, "value", plan.tier)),
        "steps": list(steps),
        "stages": [
            {
                "stage_id": s.stage_id,
                **({"phase": phase} if (phase := getattr(s, "phase", None)) is not None else {}),
                "skill": s.skill,
                "skipped": s.skipped,
                "caps": dict(s.caps),
                "note": s.note,
            }
            for s in plan.stages
        ],
        "limits": (
            None
            if plan.limits is None
            else {
                "max_papers": plan.limits.max_papers,
                "max_minutes": plan.limits.max_minutes,
                "max_runs": plan.limits.max_runs,
            }
        ),
        "second_pass": [step_key(s) for s in plan.stages if _second_pass(s) and not s.skipped],
    }
    return project.blobs.put(canonical_json(view))


def default_automatic(project: Project, limit: int) -> None:
    """The platform's deterministic steps for the works acquired so far, as the system: resolve,
    fetch (`work_queue.advance`, the same sources and routes as the runner's automatic steps) and
    convert the live documents of promoted works with the default converters. No model."""
    from factory.document.registry import default_converters
    from factory.services import work_queue
    from factory.services.document_convert import convert_documents
    from factory.services.fulltext import MAX_LIMIT
    from factory.sources.fulltext.registry import default_routes
    from factory.sources.registry import default_sources

    work_queue.advance(
        project,
        sources=dict(default_sources()),
        fetchers=default_routes(project.settings),
        convert=True,
        limit=max(1, min(limit, MAX_LIMIT)),
    )
    convert_documents(project, default_converters())


def begin_conductor(project: Project, plan: PlanLike) -> ConductorRun:
    """Start a conductor run of `plan`: writes `conductor.started` (system actor). Refused, with
    nothing written, when a conductor run is open, when the plan's tier is not the project's
    declared tier, when no stage is left to run, or when a stage that is not skipped has no runner
    stage (a step is never silently skipped)."""
    if _load(project) is not None:
        raise _refuse("conductor", "a conductor run of this project is already open")
    levels = project_levels(project)
    if levels.tier is not None and levels.tier != plan.tier:
        raise _refuse("plan", f"the project declared tier {levels.tier.value}, not {plan.tier}")
    live = [step_key(s) for s in plan.stages if not s.skipped]
    unsupported = [s for s in live if s not in STEP_STAGE]
    if unsupported:
        raise _refuse("plan", f"no runner stage for: {', '.join(unsupported)}")
    if not live:
        raise _refuse("plan", "every stage of the plan is skipped")
    automatic_limit: int | None = None
    if "acquire" in live:  # resolve, fetch and convert run once after it, before full text
        live.insert(live.index("acquire") + 1, AUTOMATIC_STEP)
        acquire = next(s for s in plan.stages if s.stage_id == "acquire")
        automatic_limit = acquire.caps.get("max_included") or None
    second = tuple(step_key(s) for s in plan.stages if not s.skipped and _second_pass(s))
    unsupported = [s for s in second if stage_of_step(s) not in SECOND_PASS_STAGE]
    if unsupported:
        raise _refuse("plan", f"no second-pass runner stage for: {', '.join(unsupported)}")
    limits = plan.limits
    budget = Budget(
        max_minutes=UNCAPPED_MINUTES if limits is None else max(1, limits.max_minutes),
        max_runs=UNCAPPED_RUNS if limits is None else max(1, limits.max_runs),
        max_units_per_run=max(
            1, min(UNCAPPED_PAPERS if limits is None else limits.max_papers, runner.MAX_UNIT_CAP)
        ),
    )
    conductor_id = project.ids.new("cnd")
    blob = _plan_blob(project, plan, live)
    started = ConductorStarted(
        conductor_id=conductor_id,
        tier=str(getattr(plan.tier, "value", plan.tier)),
        autonomy_level=levels.autonomy_level.value,
        steps=tuple(live),
        max_minutes=budget.max_minutes,
        max_runs=budget.max_runs,
        max_units_per_run=budget.max_units_per_run,
        automatic_limit=automatic_limit,
        second_pass_steps=second,
        plan_blob=blob,
    )
    with project.writing():
        project.record(
            [
                project.events.make(
                    "conductor.started", started, project.system_actor(), input_blob=blob
                )
            ]
        )
    return ConductorRun(conductor_id, started.tier, started.autonomy_level, started.steps, budget)


def _write(project: Project, kind: str, payload: StrictModel) -> None:
    with project.writing():
        project.record([project.events.make(f"conductor.{kind}", payload, project.system_actor())])


def _already_paused(trail: _Trail, d: _Decision) -> bool:
    if not trail.events or trail.events[-1].type != "conductor.paused":
        return False
    p = trail.events[-1].payload
    return (p["reason"], p.get("step"), p.get("gate_id")) == (d.reason, d.step, d.gate_id)


def _escalate_default(project: Project, gate_id: str, stage_id: str) -> None:
    """Hand a waiting human gate to the deferred queue (lane L3) when it offers `escalate_waiting`;
    before that the `conductor.paused` event is the waiting item."""
    try:
        module: Any = importlib.import_module("factory.services.human_queue")
    except ModuleNotFoundError:  # pragma: no cover
        return
    hook = getattr(module, "escalate_waiting", None)
    if hook is not None:
        hook(project, gate_id, stage_id)


def advance(
    project: Project,
    *,
    retry: bool = False,
    start_run: StartRun | None = None,
    pending: PendingUnits | None = None,
    gate_closed: GateClosed | None = None,
    escalate: Escalate | None = None,
    automatic: Automatic | None = None,
) -> ConductorStatus:
    """Take the open conductor run one step further and return its status. First closes the
    conductor's own open run when the runner has recorded its outcome; then decides from the log
    (stop rules before anything is started) and starts at most one role run. `retry` lets a failed
    or lost role run be started again, as a new run in a new session. The five callables are the
    seams of the tests (a fake runner); the defaults are the runner and the deferred queue, and
    `default_automatic` for the deterministic step after `acquire` (run here, once, as the system:
    an exception is a failed step and pauses the conductor)."""
    trail = _load(project)
    if trail is None:
        return conductor_status(project)
    meta = trail.meta
    start = start_run or runner.start_run
    pend = pending or runner.pending_units
    closer = gate_closed or default_gate_closed
    open_run = _open_run(trail)
    if open_run is not None:
        assert open_run.run_id is not None
        outcome = runner.run_outcome(project, open_run.run_id)
        if outcome is not None:
            _write(
                project,
                "step_finished",
                ConductorStepFinished(
                    conductor_id=meta.conductor_id,
                    step=open_run.step,
                    stage_id=open_run.stage_id,
                    role=open_run.role,
                    run_id=open_run.run_id,
                    outcome=cast(StepOutcome, outcome),
                ),
            )
            trail = _load(project) or trail
    decision = _decide(project, trail, retry=retry, pending=pend, gate_closed=closer)
    if decision.kind == "complete-empty":
        assert decision.step is not None and decision.stage_id is not None
        _write(
            project,
            "step_finished",
            ConductorStepFinished(
                conductor_id=meta.conductor_id,
                step=decision.step,
                stage_id=decision.stage_id,
                role="proposer",
                outcome="complete",
            ),
        )
        return advance(
            project, retry=retry, start_run=start_run, pending=pending,
            gate_closed=gate_closed, escalate=escalate, automatic=automatic,
        )  # fmt: skip
    if decision.kind == "automatic":
        assert decision.step is not None and decision.stage_id is not None
        attempts = 1 + sum(
            1 for e in trail.payloads("step_started") if e.payload["step"] == decision.step
        )
        _write(
            project,
            "step_started",
            ConductorStepStarted(
                conductor_id=meta.conductor_id,
                step=decision.step,
                stage_id=decision.stage_id,
                role="automatic",
                attempt=attempts,
            ),
        )
        failure: str | None = None
        try:
            (automatic or default_automatic)(project, meta.automatic_limit or _unit_cap(meta))
        except Exception as exc:  # a failed step, as a failed run
            failure = f"{type(exc).__name__}: {exc}"
        _write(
            project,
            "step_finished",
            ConductorStepFinished(
                conductor_id=meta.conductor_id,
                step=decision.step,
                stage_id=decision.stage_id,
                role="automatic",
                outcome="complete" if failure is None else "failed",
            ),
        )
        if failure is None:
            return advance(
                project, retry=retry, start_run=start_run, pending=pending,
                gate_closed=gate_closed, escalate=escalate, automatic=automatic,
            )  # fmt: skip
        decision = _Decision(
            "pause", decision.step, decision.stage_id, "automatic", "failed-run",
            detail=f"the automatic step failed ({failure}); advance with retry",
        )  # fmt: skip
        trail = _load(project) or trail
    if decision.kind == "finished":
        _write(
            project,
            "finished",
            ConductorFinished(
                conductor_id=meta.conductor_id,
                steps_done=len(meta.steps),
                runs=_runs_started(trail),
            ),
        )
    elif decision.kind == "start":
        assert decision.step is not None and decision.stage_id is not None and decision.role
        stage = _stage_of(decision.stage_id, decision.role)
        cap = _unit_cap(meta)
        if decision.role == "auditor":
            draw_platform_audits(project, decision.stage_id)
        token = _STARTING.set((pend, closer))
        try:
            run_id = start(project, stage, unit_cap=cap)
        except FactoryValidationError as exc:
            decision = _Decision(
                "pause", decision.step, decision.stage_id, decision.role, "refused",
                detail="; ".join(f"{i.field}: {i.reason}" for i in exc.issues),
            )  # fmt: skip
        else:
            attempts = 1 + sum(
                1
                for e in trail.payloads("step_started")
                if e.payload["step"] == decision.step and e.payload["role"] == decision.role
            )
            _write(
                project,
                "step_started",
                ConductorStepStarted(
                    conductor_id=meta.conductor_id,
                    step=decision.step,
                    stage_id=decision.stage_id,
                    role=decision.role,
                    run_id=run_id,
                    attempt=attempts,
                ),
            )
        finally:
            _STARTING.reset(token)
    if decision.kind in ("pause", "wait") and not _already_paused(trail, decision):
        assert decision.reason is not None
        if decision.kind == "wait" and decision.gate_id is not None and decision.stage_id:
            (escalate or _escalate_default)(project, decision.gate_id, decision.stage_id)
        _write(
            project,
            "paused",
            ConductorPaused(
                conductor_id=meta.conductor_id,
                reason=decision.reason,
                step=decision.step,
                stage_id=decision.stage_id,
                gate_id=decision.gate_id,
                detail=decision.detail,
            ),
        )
    return conductor_status(project, retry=retry, pending=pend, gate_closed=closer)


def _unit_cap(meta: ConductorStarted) -> int:
    return max(1, min(meta.max_units_per_run, runner.MAX_UNIT_CAP))


def conductor_status(
    project: Project,
    *,
    retry: bool = False,
    pending: PendingUnits | None = None,
    gate_closed: GateClosed | None = None,
) -> ConductorStatus:
    """The status of the latest conductor run (read-only): where it is and why it stopped."""
    trail = _load(project)
    if trail is None:
        done = [
            e
            for e in read_typed(project.paths.events_dir, project.catalog, ("conductor.finished",))
            if e.actor.kind == "system"
        ]
        if done:
            last = ConductorFinished.model_validate(done[-1].payload)
            return ConductorStatus(
                conductor_id=last.conductor_id,
                state="finished",
                steps_done=last.steps_done,
                runs=last.runs,
                lines=(f"finished: {last.steps_done} steps, {last.runs} runs",),
            )
        return ConductorStatus(conductor_id=None, state="none", lines=("no conductor run",))
    meta = trail.meta
    decision = _decide(
        project,
        trail,
        retry=retry,
        pending=pending or runner.pending_units,
        gate_closed=gate_closed or default_gate_closed,
    )
    tail = trail.events[-1] if trail.events else None
    if decision.kind == "start" and tail is not None and tail.type == "conductor.paused":
        refusal = ConductorPaused.model_validate(tail.payload)
        if (
            refusal.reason == "refused"
        ):  # the runner refused the start; the next advance tries again
            decision = _Decision(
                "pause",
                refusal.step,
                refusal.stage_id,
                decision.role,
                "refused",
                detail=refusal.detail,
            )
    closed = _closed_roles(trail)
    done_steps = sum(
        1
        for i in range(len(meta.steps))
        if all(
            (i, r) in closed
            for r in roles_of(
                project,
                meta.steps[i],
                AutonomyLevel(meta.autonomy_level),
                second_pass=meta.steps[i] in meta.second_pass_steps,
            )
        )
    )
    state: Literal["running", "waiting", "paused"] = (
        "running"
        if decision.kind in ("running", "start", "complete-empty", "finished", "automatic")
        else "waiting" if decision.kind == "wait" else "paused"
    )  # fmt: skip
    lines = [f"conductor {meta.conductor_id}: {meta.tier} at {meta.autonomy_level}"]
    lines.append(f"steps: {done_steps}/{len(meta.steps)} done ({', '.join(meta.steps)})")
    lines.append(
        f"runs {_runs_started(trail)}/{meta.max_runs}, "
        f"minutes {_minutes(project, trail):.1f}/{meta.max_minutes}"
    )
    if decision.stage_id:
        lines.append(f"at {decision.stage_id}" + (f" ({decision.role})" if decision.role else ""))
    if decision.reason:
        lines.append(f"stopped: {decision.reason}: {decision.detail}")
    return ConductorStatus(
        conductor_id=meta.conductor_id,
        state=state,
        steps=meta.steps,
        steps_done=done_steps,
        stage_id=decision.stage_id,
        role=decision.role,
        run_id=decision.run_id,
        runs=_runs_started(trail),
        minutes=round(_minutes(project, trail), 2),
        reason=decision.reason,
        gate_id=decision.gate_id,
        lines=tuple(lines),
    )
