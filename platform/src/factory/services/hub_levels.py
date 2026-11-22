"""Payload of the hub page `levels` ("How this study runs", plan tiers-and-autonomy, lane L7).

Invariants:
- Read-only: nothing is written and no model is called. Every figure is read from a service
  (`project_levels`, `level_statement`, `tiers.resolve`, `gates.effective_policy`,
  `gate_trust.trust_ledger`, `deferred_review`, `conductor.conductor_status`); this module only
  restructures them. The page judges nothing.
- Each section is guarded: one that cannot be read becomes `{"error": ...}` and the others
  still render.
- The conductor status is read directly (`conductor.conductor_status`); `levels_payload(...,
  conductor=...)` lets a test inject a reader.
- Deciding a deferred act stays a command-line act: each queue row carries the command, the page
  never writes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from factory.model.levels import AutonomyLevel
from factory.modules.contract import GateKind, GatePolicy, PolicyKind
from factory.modules.presets import preset
from factory.services.conductor import conductor_status
from factory.services.context import Project
from factory.services.project import project_levels
from factory.tiers.resolve import plan_for, skipped_steps

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

__all__ = ["DEFERRED_CAP", "METHODS", "build", "levels_payload"]

DEFERRED_CAP: Final = 200
"""Deferred rows listed; the count is exact."""

ConductorReader = Callable[[Project], dict[str, Any]]

METHODS: Final[dict[str, str]] = {
    "levels": (
        "The tier fixes the depth of the study and its rigour mode; the autonomy level says who "
        "closes the decision gates. Both are read from the project's creation event. A project "
        "created before tiers has no tier and runs attended."
    ),
    "statement": (
        "The level statement every report carries, built from the log: the tier, the level, what "
        "the tier skips compared with a systematic review, and which gates an agent closed. It "
        "says 'not human-confirmed' whenever an agent closed an act and no person has reviewed it."
    ),
    "plan": (
        "The stages of the tier's plan with their caps, from the plan data (`factory.tiers`). "
        "Skipped steps are the difference from the systematic plan, computed, never typed twice."
    ),
    "gates": (
        "One row per decision gate: the policy in force for this project (rigour preset, then the "
        "autonomy profile, then the protocol's entries, never below the gate's floor) and the "
        "preset it differs from. An agent that closes a gate under supervised or autonomous must "
        "be a different session from the one that proposed the act."
    ),
    "trust": (
        "Per gate: acts an agent closed, how many a person audited, how many the person "
        "overturned, and the rate. Watch above {watch:.0%} overturned with at least {minimum} "
        "audited; pause above {pause:.0%}. Agent labels never enter the rate."
    ),
    "deferred": (
        "Acts an agent closed that were drawn into an audit sample and still wait for a person. "
        "Deciding is a command-line act by a person; this list only shows what waits."
    ),
    "conductor": (
        "The state of the latest conductor run, read from its events. The conductor starts one "
        "outside Claude process per step; the platform calls no model."
    ),
}

TIER_BLURB: Final[dict[str, str]] = {
    "brief": "A quick, capped read of the field. Exploratory: not a systematic review.",
    "deep": "A deeper, capped study with independent checks. Exploratory rigour.",
    "pilot": "Two screening passes, your labels and advisory agreement.",
    "systematic": "Every gate enforced; the full method.",
}
NO_TIER_BLURB: Final = "A project created before tiers: no tier declared."
LEVEL_BLURB: Final[dict[str, str]] = {
    "attended": "You close every decision gate.",
    "supervised": (
        "An independent agent session closes the gates that allow it; a sampled audit follows."
    ),
    "autonomous": (
        "An orchestrated multi-agent run closes them with independent verification; you review "
        "afterwards. Every output is labelled not human-confirmed."
    ),
}


def _guard(fn: Callable[[], Any]) -> Any:
    """`fn()`, or `{"error": ...}`: a section that cannot be read never takes the page down."""
    try:
        return fn()
    except Exception as exc:  # a panel must never take the page down
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def who_may_close(policy: GatePolicy, level: AutonomyLevel) -> str:
    """The sentence for who may close a gate under `policy` (declared text, from the policy)."""
    if policy.kind is PolicyKind.HUMAN:
        return "A person only."
    if policy.kind is PolicyKind.AGENT_AUDIT:
        who = (
            f"An agent, then a sampled audit ({policy.fraction:.0%} of acts, at least "
            f"{policy.minimum})."
            if policy.fraction is not None and policy.minimum is not None
            else "An agent, then a sampled audit."
        )
    else:
        who = "An agent."
    if level is not AutonomyLevel.ATTENDED:
        who += " The closing session must differ from the proposing one."
    return who


def _policy_view(policy: GatePolicy) -> dict[str, Any]:
    return {"kind": policy.kind.value, "fraction": policy.fraction, "minimum": policy.minimum}


def _levels(project: Project) -> dict[str, Any]:
    lv = project_levels(project)
    tier = lv.tier.value if lv.tier is not None else None
    return {
        "tier": tier,
        "autonomy_level": lv.autonomy_level.value,
        "rigor_mode": lv.rigor_mode.value,
        "tier_blurb": TIER_BLURB.get(tier or "", NO_TIER_BLURB),
        "level_blurb": LEVEL_BLURB[lv.autonomy_level.value],
    }


def _statement(project: Project) -> dict[str, Any]:
    from factory.services.level_statement import level_statement

    s = level_statement(project)
    return {
        "lines": list(s.lines),
        "human_confirmed": s.human_confirmed,
        "steps_skipped": list(s.steps_skipped),
        "agent_closed": [c.model_dump(mode="json") for c in s.agent_closed],
    }


def _plan(project: Project) -> dict[str, Any]:
    lv = project_levels(project)
    if lv.tier is None:
        return {"declared": False, "stages": [], "skipped": [], "limits": None}
    plan = plan_for(lv.tier)
    return {
        "declared": True,
        "stages": [
            {
                "stage_id": s.stage_id,
                **({} if s.phase is None else {"phase": s.phase}),
                "skill": s.skill,
                "caps": dict(s.caps),
                "skipped": s.skipped,
                "note": s.note,
            }
            for s in plan.stages
        ],
        "skipped": list(skipped_steps(lv.tier)),
        "limits": plan.limits.model_dump(mode="json") if plan.limits is not None else None,
    }


def _gates(project: Project) -> list[dict[str, Any]]:
    from factory.services.gates import autonomy_level, effective_policy, rigor_mode
    from factory.services.modules.default import default_modules

    level = autonomy_level(project)
    mode = rigor_mode(project)
    rows: list[dict[str, Any]] = []
    for gate in default_modules().gates():
        if gate.kind is not GateKind.DECISION:
            continue
        policy = effective_policy(project, gate.gate_id)
        base = preset(mode, gate.gate_id)
        rows.append(
            {
                "gate_id": gate.gate_id,
                "floor": gate.floor.value,
                "policy": _policy_view(policy),
                "preset": _policy_view(base),
                "differs_from_preset": policy != base,
                "agent_may_close": policy.kind is not PolicyKind.HUMAN,
                "who": who_may_close(policy, level),
            }
        )
    return rows


def _trust(project: Project) -> dict[str, Any]:
    from factory.services import gate_trust

    return {
        "rows": [
            {
                "gate_id": t.gate_id,
                "closed_by_agent": t.closed_by_agent,
                "audited": t.audited,
                "overturned": t.overturned,
                "overturn_rate": t.overturn_rate,
                "state": t.state,
                "agent_audited": t.agent_audited,
                "agent_overturned": t.agent_overturned,
            }
            for t in gate_trust.trust_ledger(project)
        ],
        "watch_rate": gate_trust.WATCH_RATE,
        "watch_min_audited": gate_trust.WATCH_MIN_AUDITED,
        "pause_rate": gate_trust.PAUSE_RATE,
    }


def _deferred(project: Project) -> dict[str, Any]:
    from factory.services import deferred_review

    items = deferred_review.deferred_items(project)
    return {
        "count": len(items),
        "capped": len(items) > DEFERRED_CAP,
        "items": [
            {
                "gate_id": i.gate_id,
                "audit_id": i.audit_id,
                "act_event_id": i.act_event_id,
                "trust_state": i.trust_state,
                "command": f"factory review deferred decide {i.audit_id} {i.act_event_id} "
                "correct|overturn",
            }
            for i in items[:DEFERRED_CAP]
        ],
        "list_command": "factory review deferred list",
    }


def _read_conductor(project: Project) -> dict[str, Any]:
    status: dict[str, Any] = conductor_status(project).model_dump(mode="json")
    return status


def _conductor(project: Project, reader: ConductorReader | None) -> dict[str, Any]:
    use = reader if reader is not None else _read_conductor
    return {"present": True, "status": use(project)}


def levels_payload(project: Project, *, conductor: ConductorReader | None = None) -> dict[str, Any]:
    """The `levels` payload. `conductor` replaces the conductor reader (tests inject a fake)."""
    from factory.services import gate_trust

    methods = dict(METHODS)
    methods["trust"] = METHODS["trust"].format(
        watch=gate_trust.WATCH_RATE,
        minimum=gate_trust.WATCH_MIN_AUDITED,
        pause=gate_trust.PAUSE_RATE,
    )
    return {
        "levels": _guard(lambda: _levels(project)),
        "statement": _guard(lambda: _statement(project)),
        "plan": _guard(lambda: _plan(project)),
        "gates": _guard(lambda: _gates(project)),
        "trust": _guard(lambda: _trust(project)),
        "deferred": _guard(lambda: _deferred(project)),
        "conductor": _guard(lambda: _conductor(project, conductor)),
        "methods": methods,
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `levels` page."""
    return levels_payload(ctx.project)
