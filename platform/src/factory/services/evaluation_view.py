"""The evaluation of a hypothesis with what qualifies it (plan XP-B task 8; decision 94).

Invariants:
- Read-only: the live evaluation with its statistics, the specification curve, ablations and
  controls. The researcher and an agent read the same detail: nothing here is a confirmatory
  baseline's value or verdict, the one thing agent paths withhold, because no evaluation exists
  before the unlock.
- A hypothesis without an evaluation has none (None).
"""

from __future__ import annotations

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


class EvaluationDetail(StrictModel):
    evaluation: EvaluationView
    curve: SpecificationCurve | None
    ablations: list[AblationResult]
    controls: list[ControlResult]


def evaluation_detail(project: Project, hypothesis_id: str) -> EvaluationDetail | None:
    live = latest_evaluation(project, hypothesis_id)
    if live is None:
        return None
    exp = live.payload.experiment_id
    return EvaluationDetail(
        evaluation=live,
        curve=None if exp is None else specification_curve(project, exp),
        ablations=[] if exp is None else ablations(project, exp),
        controls=[] if exp is None else controls(project, exp),
    )
