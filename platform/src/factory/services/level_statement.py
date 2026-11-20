"""The level statement: what tier and autonomy level a study ran at, what it skipped and what no
human confirmed (plan tiers-and-autonomy, C7). Every report carries it, so an output of a quick or
autonomous run is never read as a human-confirmed systematic one.

Invariants:
- Computed from the events only; nothing is typed. A legacy project says "tier: not declared".
- `human_confirmed` is true only at `attended` with no agent-closed act; at `supervised` and
  `autonomous` it is false until the deferred human review exists.
- The two optional inputs (tier plans, trust ledger) are imported when their modules exist; before
  they do, `steps_skipped` is empty and `agent_closed` counts the agent-labelled acts in the log.
"""

from __future__ import annotations

import importlib
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal

from pydantic import JsonValue

from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.levels import AutonomyLevel, Tier
from factory.model.project import RigorMode
from factory.services.context import Project
from factory.services.project import project_levels

AGENT_LABELS = frozenset({"agent", "audited-agent"})
"""`autonomy` values of an agent-written act (`modules.contract.Autonomy`, minus `human`)."""

LEVEL_STATEMENT_KEY = "level_statement"

SkippedSteps = Callable[[Tier], tuple[str, ...]]


class AgentClosed(StrictModel):
    """One gate's agent-closed acts. Mirrors `gate_trust.GateTrust` (lane L3); before that module
    exists `audited` and `overturned` are zero and `state` is `ok`."""

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


def _skipped_steps_of_plans() -> SkippedSteps | None:
    try:
        module: Any = importlib.import_module("factory.tiers.resolve")
    except ModuleNotFoundError:
        return None
    resolver: SkippedSteps = module.skipped_steps
    return resolver


def _agent_closed(project: Project) -> tuple[AgentClosed, ...]:
    try:
        module: Any = importlib.import_module("factory.services.gate_trust")
    except ModuleNotFoundError:
        module = None
    if module is not None:
        return tuple(
            AgentClosed(
                gate_id=t.gate_id,
                closed_by_agent=t.closed_by_agent,
                audited=t.audited,
                overturned=t.overturned,
                overturn_rate=t.overturn_rate,
                state=t.state,
            )
            for t in module.trust_ledger(project)
            if t.closed_by_agent > 0
        )
    counts: Counter[str] = Counter(
        event.type
        for event in read_all(project.paths.events_dir, project.catalog)
        if event.payload.get("autonomy") in AGENT_LABELS
    )
    return tuple(AgentClosed(gate_id=g, closed_by_agent=n) for g, n in sorted(counts.items()))


def level_statement(project: Project, *, skipped: SkippedSteps | None = None) -> LevelStatement:
    """The statement for `project`. `skipped` replaces the tier-plan resolver (tests inject a
    fake); it is called only for a project that declared a tier."""
    levels = project_levels(project)
    resolver = skipped if skipped is not None else _skipped_steps_of_plans()
    steps = resolver(levels.tier) if levels.tier is not None and resolver is not None else ()
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
