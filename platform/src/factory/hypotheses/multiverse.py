"""Specification curve, ablations and controls from recorded runs (slice 6, plan XP-B, rulings 7
and 8; spec rulings 23 and 26). Pure: no I/O, no project state.

Invariants:
- The curve has one point per universe with at least two pairs. The primary universe is read on
  the confirmatory split (it is the registered test); every other universe can only have been run
  on the `dev` split (the design plans no other confirmatory cell), so its point is labelled
  `split: dev` and is descriptive: the rule applied to it says what the rule would give there,
  not a result. Runs of other arms never enter a point.
- `only-non-primary`: the primary outcome is `refuted` or `inconclusive` while some other
  universe would give `supported`. `fragile`: universe means of both signs exist.
- An ablation is read as (ablated arm - treatment) oriented, on the `dev` split of the primary
  universe: a negative effect of removing a component means the component helps.
- A control has only one arm of its own (the treatment configuration with its overrides, on the
  `dev` split). Its effect is the oriented difference to the baseline arm of the same seed on the
  same split and universe, as the treatment's effect is, so it is read against `dev` baseline
  runs. A positive control passes when its interval's lower bound is above zero; a negative
  control passes when its interval contains zero. With fewer than two pairs `passed` is None (not
  evaluated), never a pass. A failed control flags the outcome `control-failed`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from factory.hypotheses.design import run_config, universes
from factory.hypotheses.pairing import RunFact, pair_runs
from factory.hypotheses.rules import apply_experiment_rule
from factory.hypotheses.stats import PairedSummary, paired_summary, plain
from factory.hypotheses.tquantiles import Level
from factory.model.experiments import Cell, ExperimentDesign, SplitRole
from factory.model.hypotheses import HypothesisSpec, NonInferiority, Superiority


@dataclass(frozen=True)
class UniversePoint:
    universe: tuple[tuple[str, str], ...]
    primary: bool
    split: SplitRole
    n: int
    mean: str
    ci_low: str | None
    ci_high: str | None
    outcome_descriptive: str


@dataclass(frozen=True)
class AblationResult:
    name: str
    key: str
    n: int
    mean: str | None
    ci_low: str | None
    ci_high: str | None


@dataclass(frozen=True)
class ControlResult:
    name: str
    kind: str
    n: int
    mean: str | None
    ci_low: str | None
    ci_high: str | None
    passed: bool | None


def _strings(s: PairedSummary | None) -> tuple[str | None, str | None, str | None]:
    if s is None:
        return None, None, None
    return (
        plain(s.mean),
        None if s.ci_low is None else plain(s.ci_low),
        None if s.ci_high is None else plain(s.ci_high),
    )


def _differing_keys(design: ExperimentDesign, a: str, b: str) -> frozenset[str]:
    universe = tuple(sorted(design.primary_universe.items()))
    ca = run_config(design, Cell(universe=universe, seed=0, arm=a, split="dev"))
    cb = run_config(design, Cell(universe=universe, seed=0, arm=b, split="dev"))
    return frozenset(k for k in set(ca) | set(cb) if ca.get(k) != cb.get(k))


def specification_curve(
    design: ExperimentDesign,
    spec: HypothesisSpec,
    facts: Sequence[RunFact],
    *,
    level: Level,
    min_seeds: int,
) -> list[UniversePoint]:
    rule = spec.decision_rule
    assert isinstance(rule, Superiority | NonInferiority)
    margin = Decimal(spec.prediction.margin)
    points: list[UniversePoint] = []
    for universe in universes(design):
        primary = universe == design.primary_universe
        split: SplitRole = "confirmatory" if primary else "dev"
        pairing = pair_runs(
            facts,
            differing_keys=frozenset(design.factor),
            universe=universe,
            split=split,
            direction=spec.metric.direction,
        )
        if len(pairing.pairs) < 2:
            continue
        summary = paired_summary([d for _, _, d in pairing.pairs], level)
        result = apply_experiment_rule(rule, margin, summary, min_seeds=min_seeds)
        mean, low, high = _strings(summary)
        assert mean is not None
        points.append(
            UniversePoint(
                tuple(sorted(universe.items())),
                primary,
                split,
                summary.n,
                mean,
                low,
                high,
                result.outcome,
            )
        )
    return sorted(points, key=lambda p: (Decimal(p.mean), p.universe))


def ablation_results(
    design: ExperimentDesign,
    spec: HypothesisSpec,
    facts: Sequence[RunFact],
    *,
    level: Level,
) -> list[AblationResult]:
    out: list[AblationResult] = []
    for a in design.ablations:
        arm = f"ablation:{a.name}"
        pairing = pair_runs(
            facts,
            differing_keys=_differing_keys(design, arm, "treatment"),
            universe=design.primary_universe,
            split="dev",
            direction=spec.metric.direction,
            arms=(arm, "treatment"),
        )
        diffs = [d for _, _, d in pairing.pairs]
        mean, low, high = _strings(paired_summary(diffs, level) if diffs else None)
        out.append(AblationResult(a.name, a.key, len(diffs), mean, low, high))
    return out


def control_results(
    design: ExperimentDesign,
    spec: HypothesisSpec,
    facts: Sequence[RunFact],
    *,
    level: Level,
) -> list[ControlResult]:
    out: list[ControlResult] = []
    for c in design.controls:
        arm = f"control:{c.name}"
        pairing = pair_runs(
            facts,
            differing_keys=_differing_keys(design, arm, "baseline"),
            universe=design.primary_universe,
            split="dev",
            direction=spec.metric.direction,
            arms=(arm, "baseline"),
        )
        diffs = [d for _, _, d in pairing.pairs]
        summary = paired_summary(diffs, level) if diffs else None
        mean, low, high = _strings(summary)
        passed: bool | None = None
        if summary is not None and summary.ci_low is not None and summary.ci_high is not None:
            if c.kind == "positive":
                passed = summary.ci_low > 0
            else:
                passed = summary.ci_low <= 0 <= summary.ci_high
        out.append(ControlResult(c.name, c.kind, len(diffs), mean, low, high, passed))
    return out


def design_flags(
    design: ExperimentDesign,
    spec: HypothesisSpec,
    facts: Sequence[RunFact],
    *,
    level: Level,
    min_seeds: int,
    outcome: str,
) -> set[str]:
    flags: set[str] = set()
    curve = specification_curve(design, spec, facts, level=level, min_seeds=min_seeds)
    if outcome in ("refuted", "inconclusive") and any(
        not p.primary and p.outcome_descriptive == "supported" for p in curve
    ):
        flags.add("only-non-primary")
    means = [Decimal(p.mean) for p in curve]
    if any(m > 0 for m in means) and any(m < 0 for m in means):
        flags.add("fragile")
    if any(c.passed is False for c in control_results(design, spec, facts, level=level)):
        flags.add("control-failed")
    return flags
