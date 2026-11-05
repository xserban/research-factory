"""Specification curve, ablations and controls of an experiment, computed on read (slice 6, plan
XP-B, rulings 7 and 8; spec rulings 23 and 26).

Invariants:
- Read-only and recomputed on every call from the recorded runs; nothing here is stored or typed.
- The primary universe's point is the confirmatory test; other universes' points can only come
  from `dev`-split runs and are descriptive (`hypotheses.multiverse`, which also records how a
  control with a single arm of its own is read).
- The curve's flags are those the evaluation carries: `only-non-primary` and `fragile`.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.hypotheses.evaluate import ExperimentInputs, compute_experiment, facts_of
from factory.hypotheses.multiverse import (
    ablation_results,
    control_results,
)
from factory.hypotheses.multiverse import (
    specification_curve as curve_of,
)
from factory.index.evaluation import read_experiment_inputs
from factory.model.base import StrictModel
from factory.services.context import Project


class UniversePoint(StrictModel):
    universe: dict[str, str]
    primary: bool
    split: str
    n: int
    mean: str
    ci_low: str | None
    ci_high: str | None
    outcome_descriptive: str
    """What the rule would give if this universe were the primary one; a description, not a
    result."""


class SpecificationCurve(StrictModel):
    points: list[UniversePoint]
    flags: tuple[str, ...]


class AblationResult(StrictModel):
    name: str
    key: str
    n: int
    mean: str | None
    ci_low: str | None
    ci_high: str | None


class ControlResult(StrictModel):
    name: str
    kind: str
    n: int
    mean: str | None
    ci_low: str | None
    ci_high: str | None
    passed: bool | None
    """None while fewer than two pairs exist; a control is never passed by default."""


def _inputs(project: Project, experiment_id: str) -> ExperimentInputs | None:
    project.index.sync()
    with project.index.connect() as conn:
        hypothesis = conn.execute(
            text(
                "SELECT hypothesis FROM experiments WHERE experiment_id = :e "
                "AND superseded_by IS NULL AND frozen_event_id IS NOT NULL"
            ),
            {"e": experiment_id},
        ).scalar()
        if hypothesis is None:
            return None
        inputs = read_experiment_inputs(conn, str(hypothesis))
    return inputs if inputs is not None and inputs.experiment_id == experiment_id else None


def specification_curve(project: Project, experiment_id: str) -> SpecificationCurve:
    inputs = _inputs(project, experiment_id)
    if inputs is None:
        return SpecificationCurve(points=[], flags=())
    points = curve_of(
        inputs.design, inputs.spec, facts_of(inputs), level=inputs.level, min_seeds=inputs.min_seeds
    )
    flags = set(compute_experiment(inputs).flags)
    return SpecificationCurve(
        points=[
            UniversePoint(
                universe=dict(p.universe),
                primary=p.primary,
                split=p.split,
                n=p.n,
                mean=p.mean,
                ci_low=p.ci_low,
                ci_high=p.ci_high,
                outcome_descriptive=p.outcome_descriptive,
            )
            for p in points
        ],
        flags=tuple(sorted(flags & {"only-non-primary", "fragile"})),
    )


def ablations(project: Project, experiment_id: str) -> list[AblationResult]:
    inputs = _inputs(project, experiment_id)
    if inputs is None:
        return []
    found = ablation_results(inputs.design, inputs.spec, facts_of(inputs), level=inputs.level)
    return [AblationResult(**vars(a)) for a in found]


def controls(project: Project, experiment_id: str) -> list[ControlResult]:
    inputs = _inputs(project, experiment_id)
    if inputs is None:
        return []
    found = control_results(inputs.design, inputs.spec, facts_of(inputs), level=inputs.level)
    return [ControlResult(**vars(c)) for c in found]
