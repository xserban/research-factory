"""The outcome of an experiment hypothesis, computed from recorded facts (slice 6, plan XP-B;
spec rulings 16, 17, 22, 23; R-121). Pure: no I/O, no project state.

Invariants:
- The input is `ExperimentInputs`, plain data read from the projection (`index.evaluation`); the
  result is the full `HypothesisEvaluated` payload. Nothing here takes an outcome from anyone.
- Pairs are formed on the confirmatory split of the primary universe (`hypotheses.pairing`). The
  evaluation is `incomplete` while a primary cell (arm and seed) has no completed run; otherwise
  the decision rule of the hypothesis is applied to the paired-t interval of the oriented
  per-seed differences at the plan's confidence level.
- `inputs_hash` covers every fact the computation reads (hypothesis and design versions, rule,
  margin, level, minimum seeds, every reported run of the design with its event and metrics,
  the deviations, whether a baseline was accepted and the autonomy labels), so a changed input
  gives another hash even when the outcome is the same.
- Flags (all computed): `test-reused`, `deviated`, `baseline-not-reproduced`, `autonomy:agent`,
  the rule's own (`too-few-pairs`, `below-min-seeds`), `incomplete`, and the multiverse and
  control flags (`hypotheses.multiverse`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.hypotheses.design import primary_metric, run_config
from factory.hypotheses.multiverse import design_flags
from factory.hypotheses.pairing import RunFact, pair_runs
from factory.hypotheses.rules import RuleResult, apply_experiment_rule
from factory.hypotheses.stats import paired_summary, plain
from factory.hypotheses.tquantiles import Level
from factory.model.experiments import Cell, ExperimentDesign
from factory.model.hypotheses import (
    EVALUATOR_VERSION,
    HypothesisEvaluated,
    HypothesisSpec,
    NonInferiority,
    Superiority,
)


@dataclass(frozen=True)
class RunRow:
    """A registered run as the projection holds it; `reported_event_id` is None while planned."""

    run_id: str
    cell: Cell
    reported_event_id: str | None
    exit_status: int | None
    metrics: dict[str, str] | None
    flags: frozenset[str]


@dataclass(frozen=True)
class DeviationRow:
    kind: str
    semantic: bool
    after_unlock: bool


@dataclass(frozen=True)
class ExperimentInputs:
    hypothesis_id: str
    h_version: str
    spec: HypothesisSpec
    experiment_id: str
    e_version: str
    design: ExperimentDesign
    runs: tuple[RunRow, ...]
    deviations: tuple[DeviationRow, ...]
    baseline_accepted: bool
    autonomy: tuple[str, ...]
    """The autonomy labels of the registration, the freeze and the unlock."""
    min_seeds: int
    level: Level
    unlocked: bool = True


def inputs_hash(inputs: ExperimentInputs) -> str:
    reported = sorted(
        [r.run_id, r.reported_event_id, r.exit_status, sorted(map(list, (r.metrics or {}).items()))]
        for r in inputs.runs
        if r.reported_event_id is not None
    )
    body: dict[str, JsonValue] = {
        "h": inputs.h_version,
        "e": inputs.e_version,
        "rule": inputs.spec.decision_rule.model_dump(mode="json"),
        "margin": inputs.spec.prediction.margin,
        "level": inputs.level,
        "min_seeds": inputs.min_seeds,
        "runs": cast(JsonValue, reported),
        "deviations": cast(
            JsonValue, sorted([d.kind, d.semantic, d.after_unlock] for d in inputs.deviations)
        ),
        "accepted": inputs.baseline_accepted,
        "autonomy": cast(JsonValue, sorted(set(inputs.autonomy))),
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()[:16]


def facts_of(inputs: ExperimentInputs) -> list[RunFact]:
    """The reported runs as pairing facts, in the order they were reported. The configuration is
    recomputed from the design and the cell, as the registration did."""
    metric = primary_metric(inputs.design).name
    reported = sorted(
        (r for r in inputs.runs if r.reported_event_id is not None),
        key=lambda r: (str(r.reported_event_id), r.run_id),
    )
    facts: list[RunFact] = []
    for order, r in enumerate(reported):
        value: Decimal | None = None
        if r.exit_status == 0 and r.metrics is not None and metric in r.metrics:
            value = Decimal(r.metrics[metric])
        facts.append(
            RunFact(
                run_id=r.run_id,
                cell=r.cell,
                config=run_config(inputs.design, r.cell),
                value=value,
                flags=r.flags,
                reported_order=order,
            )
        )
    return facts


def compute_experiment(inputs: ExperimentInputs) -> HypothesisEvaluated:
    spec, design = inputs.spec, inputs.design
    facts = facts_of(inputs)
    pairing = pair_runs(
        facts,
        differing_keys=frozenset(design.factor),
        universe=design.primary_universe,
        split="confirmatory",
        direction=spec.metric.direction,
    )
    complete = len(pairing.pairs) + len(pairing.confounded) == len(set(design.seeds))
    diffs = [d for _, _, d in pairing.pairs]
    rule = spec.decision_rule
    assert isinstance(rule, Superiority | NonInferiority)  # an experiment hypothesis (H-C)
    margin = Decimal(spec.prediction.margin)
    result: RuleResult
    if diffs:
        result = apply_experiment_rule(
            rule, margin, paired_summary(diffs, inputs.level), min_seeds=inputs.min_seeds
        )
    else:
        result = RuleResult(
            "inconclusive", frozenset({"too-few-pairs", "below-min-seeds"}), None, {"n": 0}
        )
    summary = result.summary
    flags = set(result.flags)
    outcome = result.outcome if complete else "incomplete"
    if not complete:
        flags.add("incomplete")
    flags |= _evidence_flags(inputs, facts)
    flags |= design_flags(
        design, spec, facts, level=inputs.level, min_seeds=inputs.min_seeds, outcome=outcome
    )
    counts = {
        "n": len(pairing.pairs),
        "confounded": len(pairing.confounded),
        "excluded": len(pairing.excluded),
        "extra_runs": len(pairing.extra_runs),
        "seeds": len(set(design.seeds)),
    }
    return HypothesisEvaluated(
        hypothesis_id=inputs.hypothesis_id,
        h_version=inputs.h_version,
        experiment_id=inputs.experiment_id,
        e_version=inputs.e_version,
        outcome=outcome,
        n=len(pairing.pairs),
        mean=None if summary is None else plain(summary.mean),
        ci_low=None if summary is None or summary.ci_low is None else plain(summary.ci_low),
        ci_high=None if summary is None or summary.ci_high is None else plain(summary.ci_high),
        level=inputs.level,
        counts=counts,
        flags=tuple(sorted(flags)),
        runs=tuple(r for t, b, _ in pairing.pairs for r in (t, b)),
        inputs_hash=inputs_hash(inputs),
        evaluator_version=EVALUATOR_VERSION,
    )


def _evidence_flags(inputs: ExperimentInputs, facts: Sequence[RunFact]) -> set[str]:
    flags: set[str] = set()
    universe = tuple(sorted(inputs.design.primary_universe.items()))
    if any(
        "test-reused" in f.flags
        for f in facts
        if f.cell.split == "confirmatory" and f.cell.universe == universe
    ):
        flags.add("test-reused")
    if any(d.semantic and d.after_unlock for d in inputs.deviations):
        flags.add("deviated")
    if inputs.baseline_accepted:
        flags.add("baseline-not-reproduced")
    if "agent" in inputs.autonomy:
        flags.add("autonomy:agent")
    return flags
