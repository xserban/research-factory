"""Decision rules from the fixed menu, applied to computed statistics (slice 6, plan XP-B, ruling
5; spec rulings 16 and 17). Pure: no I/O, no project state.

Invariants:
- Superiority: `supported` if the interval's lower bound is above the margin, `refuted` if its
  upper bound is below the margin, else `inconclusive`. Non-inferiority is the same with the
  margin negated. The interval is the paired-t one of `hypotheses.stats`.
- Fewer than two pairs give `inconclusive` with the flag `too-few-pairs`; fewer pairs than the
  minimum seeds add `below-min-seeds`.
- Literature direction (unit: work): with `n` comparing works, `k` favouring treatment by more than
  the margin and `j` favouring the baseline by more than the margin, `supported` if `n >= n_min`
  and `k/n >= q`, `refuted` if `n >= n_min` and `j/n >= q`, else `inconclusive`; `n < n_min` adds
  `insufficient-evidence`. Shares are compared exactly (`k >= q * n`), never as floats.
- The outcome is a function of the numbers and the rule alone; nothing here reads a project.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from factory.hypotheses.stats import PairedSummary
from factory.model.hypotheses import LiteratureDirection, NonInferiority, Superiority

Outcome = Literal["supported", "refuted", "inconclusive"]
Favour = Literal["treatment", "baseline", "tie"]


@dataclass(frozen=True)
class RuleResult:
    outcome: Outcome
    flags: frozenset[str]
    summary: PairedSummary | None
    counts: Mapping[str, int]


def apply_experiment_rule(
    rule: Superiority | NonInferiority,
    margin: Decimal,
    summary: PairedSummary,
    *,
    min_seeds: int,
) -> RuleResult:
    flags: set[str] = set()
    if summary.n < min_seeds:
        flags.add("below-min-seeds")
    counts = {"n": summary.n}
    if summary.ci_low is None or summary.ci_high is None:
        flags.add("too-few-pairs")
        return RuleResult("inconclusive", frozenset(flags), summary, counts)
    threshold = margin if isinstance(rule, Superiority) else -margin
    outcome: Outcome = "inconclusive"
    if summary.ci_low > threshold:
        outcome = "supported"
    elif summary.ci_high < threshold:
        outcome = "refuted"
    return RuleResult(outcome, frozenset(flags), summary, counts)


def favour_of(treatment: Decimal, baseline: Decimal, direction: str, margin: Decimal) -> Favour:
    """Which method one work favours: the oriented difference beyond the margin either way."""
    diff = treatment - baseline if direction == "higher" else baseline - treatment
    if diff > margin:
        return "treatment"
    if -diff > margin:
        return "baseline"
    return "tie"


def apply_literature_rule(rule: LiteratureDirection, favour: Sequence[Favour]) -> RuleResult:
    n = len(favour)
    k = sum(1 for f in favour if f == "treatment")
    j = sum(1 for f in favour if f == "baseline")
    counts = {"n": n, "favour_treatment": k, "favour_baseline": j, "ties": n - k - j}
    flags: set[str] = set()
    if n < rule.n_min:
        flags.add("insufficient-evidence")
        return RuleResult("inconclusive", frozenset(flags), None, counts)
    q = Decimal(rule.q)
    outcome: Outcome = "inconclusive"
    if Decimal(k) >= q * n:
        outcome = "supported"
    elif Decimal(j) >= q * n:
        outcome = "refuted"
    return RuleResult(outcome, frozenset(flags), None, counts)
