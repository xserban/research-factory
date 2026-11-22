"""The level statement: what tier and autonomy level a study ran at, what it skipped and what no
human confirmed (plan tiers-and-autonomy, C7). Every report carries it, so an output of a quick or
autonomous run is never read as a human-confirmed systematic one.

Invariants:
- Computed from the events only; nothing is typed. A legacy project says "tier: not declared".
- `human_confirmed` is true only at `attended` with no agent-closed act; at `supervised` and
  `autonomous` it stays false (the deferred human review samples acts; it does not confirm them
  all).
- `steps_skipped` comes from the tier plans (`tiers.resolve.skipped_steps`) and `agent_closed` from
  the trust ledger (`gate_trust.trust_ledger`): both are read directly, never with a fallback.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Literal

from pydantic import JsonValue

from factory.events.reader import read_typed
from factory.model.base import StrictModel
from factory.model.levels import AutonomyLevel, Tier
from factory.model.project import RigorMode
from factory.services.context import Project
from factory.services.gate_trust import trust_ledger
from factory.services.project import project_levels
from factory.tiers.resolve import skipped_steps
from factory.tiers.validation import validation_profile

LEVEL_STATEMENT_KEY = "level_statement"

SkippedSteps = Callable[[Tier], tuple[str, ...]]


class AgentClosed(StrictModel):
    """One gate's agent-closed acts. Mirrors `gate_trust.GateTrust`."""

    gate_id: str
    closed_by_agent: int
    audited: int = 0
    overturned: int = 0
    overturn_rate: float | None = None
    state: Literal["ok", "watch", "pause"] = "ok"


class LevelStatement(StrictModel):
    tier: Tier | None
    autonomy_level: AutonomyLevel
    rigor_mode: RigorMode
    steps_skipped: tuple[str, ...]
    agent_closed: tuple[AgentClosed, ...]
    human_confirmed: bool
    lines: tuple[str, ...]


def _agent_closed(project: Project) -> tuple[AgentClosed, ...]:
    return tuple(
        AgentClosed(
            gate_id=t.gate_id,
            closed_by_agent=t.closed_by_agent,
            audited=t.audited,
            overturned=t.overturned,
            overturn_rate=t.overturn_rate,
            state=t.state,
        )
        for t in trust_ledger(project)
        if t.closed_by_agent > 0
    )


_VALIDATION_TYPES = (
    "screening.decision_recorded",
    "extraction.recorded",
    "extraction.claim_recorded",
    "calibration.labelled",
    "miner.calibration_labelled",
    "audit.sampled",
    "audit.labelled",
    "extraction.audit_sampled",
    "extraction.audit_labelled",
)


def _validation_lines(project: Project, tier: Tier, level: AutonomyLevel) -> list[str]:
    """What actually ran, from the events: the profile label, the passes per stage, whether an audit
    sample was drawn and labelled and whether a calibration was labelled. Where the profile's
    evidence is missing the line says `unvalidated`."""
    profile = validation_profile(tier, level)
    passes: dict[str, set[str]] = {"screening": set(), "extraction": set()}
    seen: Counter[str] = Counter()
    for event in read_typed(project.paths.events_dir, project.catalog, _VALIDATION_TYPES):
        seen[event.type] += 1
        stage = event.type.split(".")[0]
        if stage in passes and event.payload.get("pass_label") is not None:
            passes[stage].add(str(event.payload["pass_label"]))
    ran = "; ".join(
        f"{stage} {'+'.join(sorted(labels))}" if labels else f"{stage} none"
        for stage, labels in passes.items()
    )
    lines = [f"validation: {profile.label}", f"passes that ran: {ran}"]
    sampled = seen["audit.sampled"] + seen["extraction.audit_sampled"]
    labelled = seen["audit.labelled"] + seen["extraction.audit_labelled"]
    if sampled == 0:
        lines.append("audit: no sample drawn (unvalidated)")
    elif labelled == 0:
        lines.append(f"audit: {sampled} sample(s) drawn, none labelled (unvalidated)")
    else:
        lines.append(f"audit: {sampled} sample(s) drawn, {labelled} label(s) recorded")
    if seen["calibration.labelled"] + seen["miner.calibration_labelled"] > 0:
        lines.append("calibration: a human-labelled gold set exists")
    elif profile.calibration_required:
        lines.append("calibration: none (unvalidated)")
    else:
        lines.append("calibration: none")
    if profile.independent_judge:
        lines.append("validation by a session and model other than the proposer's is required")
    return lines


def level_statement(project: Project, *, skipped: SkippedSteps | None = None) -> LevelStatement:
    """The statement for `project`. `skipped` replaces the tier-plan resolver (tests inject a
    fake); it is called only for a project that declared a tier."""
    levels = project_levels(project)
    resolver = skipped if skipped is not None else skipped_steps
    steps = resolver(levels.tier) if levels.tier is not None else ()
    closed = _agent_closed(project)
    confirmed = levels.autonomy_level is AutonomyLevel.ATTENDED and not closed
    lines: list[str] = []
    if levels.tier is None:
        lines.append("tier: not declared (a project that predates tiers)")
    else:
        lines.append(f"tier: {levels.tier.value} (rigor mode {levels.rigor_mode.value})")
    lines.append(f"autonomy level: {levels.autonomy_level.value}")
    if levels.rigor_mode is RigorMode.EXPLORATORY:
        lines.append("exploratory: the results are not a systematic review")
    if steps:
        lines.append("skipped compared with a systematic review: " + "; ".join(steps))
    if closed:
        lines.append(
            "gates closed by an agent: "
            + ", ".join(f"{c.gate_id} ({c.closed_by_agent})" for c in closed)
        )
    if levels.tier is not None:
        lines.extend(_validation_lines(project, levels.tier, levels.autonomy_level))
    if not confirmed:
        lines.append("not human-confirmed: no person has confirmed the acts an agent closed")
    return LevelStatement(
        tier=levels.tier,
        autonomy_level=levels.autonomy_level,
        rigor_mode=levels.rigor_mode,
        steps_skipped=steps,
        agent_closed=closed,
        human_confirmed=confirmed,
        lines=tuple(lines),
    )


def render_level_statement(statement: LevelStatement) -> str:
    return "\n".join(statement.lines)


def with_level_statement(project: Project, view: JsonValue) -> JsonValue:
    """A report's JSON view with the statement as one more field, `level_statement`. A view that is
    not an object is returned unchanged (no report is one)."""
    if not isinstance(view, dict):
        return view
    return {**view, LEVEL_STATEMENT_KEY: level_statement(project).model_dump(mode="json")}
