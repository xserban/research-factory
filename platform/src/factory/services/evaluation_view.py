"""The evaluation of a hypothesis as the two readers see it (plan XP-B task 8; decision 93 item 9).

Invariants:
- Read-only. The researcher's variant (`researcher_evaluation`) carries the computed statistics:
  mean, interval, the specification curve, ablations and controls with their effects.
- The agent variant (`agent_evaluation`) carries the outcome, the number of pairs or works, the
  level, the counts, the flags, the number of universes in the curve with its flags and, per
  control, only whether it passed. It carries no mean, no interval, no effect size and no run
  count by split: no MCP view carries a metric value (decision 93 item 9), and an effect over
  test-split runs is one.
- A hypothesis without an evaluation has neither variant (None).
"""

from __future__ import annotations

from pydantic import JsonValue

from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.evaluation import EvaluationView, latest_evaluation
from factory.services.multiverse import (
    AblationResult,
    ControlResult,
    SpecificationCurve,
    ablations,
    controls,
    specification_curve,
)


class ResearcherEvaluation(StrictModel):
    evaluation: EvaluationView
    curve: SpecificationCurve | None
    ablations: list[AblationResult]
    controls: list[ControlResult]


def researcher_evaluation(project: Project, hypothesis_id: str) -> ResearcherEvaluation | None:
    live = latest_evaluation(project, hypothesis_id)
    if live is None:
        return None
    exp = live.payload.experiment_id
    return ResearcherEvaluation(
        evaluation=live,
        curve=None if exp is None else specification_curve(project, exp),
        ablations=[] if exp is None else ablations(project, exp),
        controls=[] if exp is None else controls(project, exp),
    )


def agent_evaluation(project: Project, hypothesis_id: str) -> dict[str, JsonValue] | None:
    live = latest_evaluation(project, hypothesis_id)
    if live is None:
        return None
    p = live.payload
    out: dict[str, JsonValue] = {
        "outcome": p.outcome,
        "n": p.n,
        "level": p.level,
        "counts": dict(p.counts),
        "flags": list(p.flags),
        "event_id": live.event_id,
        "evaluator_version": p.evaluator_version,
    }
    if p.experiment_id is not None:
        curve = specification_curve(project, p.experiment_id)
        out["specification_curve"] = {"universes": len(curve.points), "flags": list(curve.flags)}
        out["controls"] = [
            {"name": c.name, "kind": c.kind, "n": c.n, "passed": c.passed}
            for c in controls(project, p.experiment_id)
        ]
    return out
