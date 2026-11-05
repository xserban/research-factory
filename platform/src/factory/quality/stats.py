"""Pure quality statistics: agreement, rates, audit sizing and draws.

Invariants:
- Every function is deterministic given its inputs and the supplied `random.Random` or seed;
  nothing reads a clock, the event log or the index.
- Undefined quantities (empty denominator, no variation) are `None`, never `0.0` or `NaN`.
- Counts are computed here from the inputs; callers never supply them.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from factory.model.base import StrictModel

T = TypeVar("T")

EXCLUSION_SHARE = 0.75
"""Share of an audit sample drawn from agreed exclusions (ruling 3, rounded half up)."""


class Rates(StrictModel):
    sensitivity: float | None
    specificity: float | None
    n_positive: int
    n_negative: int


class AuditRates(StrictModel):
    false_exclusion: float | None
    false_inclusion: float | None
    weighted: float | None
    labelled: int


def cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa for two binary raters; `None` when undefined (no pairs or chance agreement 1).

    Computed in integers and divided once, so the result is exact for the given counts.
    """
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(1 for a, b in pairs if a == b)
    a_true = sum(1 for a, _ in pairs if a)
    b_true = sum(1 for _, b in pairs if b)
    expected = a_true * b_true + (n - a_true) * (n - b_true)
    if n * n == expected:
        return None
    return (agree * n - expected) / (n * n - expected)


def kappa_by_criterion(
    pairs: Sequence[tuple[str | None, str | None]],
    criteria: Sequence[str],
) -> dict[str, float | None]:
    """Kappa per criterion over the binary event "this rater excluded citing that criterion".

    `pairs` holds `(human_criterion, pass_criterion)` per work, `None` for no exclusion.
    """
    return {
        cid: cohen_kappa([(human == cid, passed == cid) for human, passed in pairs])
        for cid in criteria
    }


def sensitivity_specificity(pairs: Sequence[tuple[bool, bool]]) -> Rates:
    """Sensitivity and specificity of a pass against human labels.

    `pairs` holds `(human_include, pass_promotes)` per calibration item. Sensitivity is the
    share of human includes the pass promotes; specificity is the share of human excludes
    the pass does not promote.
    """
    true_pos = sum(1 for h, p in pairs if h and p)
    false_neg = sum(1 for h, p in pairs if h and not p)
    true_neg = sum(1 for h, p in pairs if not h and not p)
    false_pos = sum(1 for h, p in pairs if not h and p)
    return Rates(
        sensitivity=_ratio(true_pos, true_pos + false_neg),
        specificity=_ratio(true_neg, true_neg + false_pos),
        n_positive=true_pos + false_neg,
        n_negative=true_neg + false_pos,
    )


def audit_size(population: int, fraction: float, minimum: int) -> int:
    """Audit sample size `min(N, max(ceil(fraction * N), minimum))` over `N` agreed decisions.

    The ceiling is taken after rounding the product to 9 decimals, so float noise in
    `fraction * N` cannot add a unit.
    """
    scaled = math.ceil(round(fraction * population, 9))
    return min(population, max(scaled, minimum))


def draw_audit(
    exclusions: Sequence[str],
    inclusions: Sequence[str],
    n: int,
    rng: random.Random,
) -> list[str]:
    """Draw `n` audit items: about 75% agreed exclusions, the rest agreed inclusions.

    The exclusion target is `floor(0.75 * n + 0.5)`. A short stratum is filled from the
    other, so the result has `min(n, total)` items. Each stratum is sampled from its sorted
    input, so the draw depends only on the members and the seed. The output is sorted.
    """
    n = min(n, len(exclusions) + len(inclusions))
    n_excl = min(math.floor(EXCLUSION_SHARE * n + 0.5), len(exclusions))
    n_incl = min(n - n_excl, len(inclusions))
    n_excl = min(n - n_incl, len(exclusions))
    drawn = rng.sample(sorted(exclusions), n_excl) + rng.sample(sorted(inclusions), n_incl)
    return sorted(drawn)


def audit_error_rates(
    rows: Sequence[tuple[bool, bool]],
    pop_exclusions: int,
    pop_inclusions: int,
) -> AuditRates:
    """Error rates of agreed decisions, from audited rows `(agreed_include, human_include)`.

    `false_exclusion` is the share of agreed exclusions the human includes; `false_inclusion`
    the share of agreed inclusions the human excludes. `weighted` averages the two rates by
    the population shares `pop_exclusions` and `pop_inclusions`. It is `None` if a stratum
    with population has no labelled rows.
    """
    excluded_rows = [human for agreed, human in rows if not agreed]
    included_rows = [human for agreed, human in rows if agreed]
    false_exclusion = _ratio(sum(excluded_rows), len(excluded_rows))
    false_inclusion = _ratio(sum(1 for human in included_rows if not human), len(included_rows))
    return AuditRates(
        false_exclusion=false_exclusion,
        false_inclusion=false_inclusion,
        weighted=_weighted([(pop_exclusions, false_exclusion), (pop_inclusions, false_inclusion)]),
        labelled=len(rows),
    )


def draw_uniform(items: Sequence[T], size: int, seed: int, key: Callable[[T], Any]) -> list[T]:
    """`size` items of `items` (sorted by `key`), uniformly at random from `seed`; sorted result."""
    return sorted(random.Random(seed).sample(sorted(items, key=key), size), key=key)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _weighted(strata: Sequence[tuple[int, float | None]]) -> float | None:
    total = sum(population for population, _ in strata)
    if total == 0:
        return None
    acc = 0.0
    for population, rate in strata:
        if population == 0:
            continue
        if rate is None:
            return None
        acc += population * rate
    return acc / total
