"""Baseline reproduction verdicts (slice 6, plan XP-A ruling 7). Pure: no I/O, no project state.

Invariants:
- The reproduced value is the mean of the primary metric over the completed reproduction runs
  (one per seed), in exact decimal arithmetic, rounded half-even to six places and written as a
  plain canonical decimal.
- The verdict compares that rounded value with the reported one: `reproduced` when the absolute
  difference is at most the tolerance, which is absolute (in the metric unit) or relative to the
  magnitude of the reported value. Equality with the tolerance is `reproduced`. The sign and the
  direction of the metric do not matter: only the distance does.
- No completed run gives `no-runs-completed` and no reproduced value; so does a mean too large to
  round to six places (a diverged run is recorded, not refused).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation
from typing import Literal

EVALUATOR_VERSION = "baseline-eval@1"
PLACES = Decimal("0.000001")
_CTX = Context(prec=60)

Verdict = Literal["reproduced", "not-reproduced", "no-runs-completed"]


def _plain(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(_CTX), "f")


def reproduced_value(values: Sequence[str]) -> str | None:
    """The mean of `values` to six places; None for no values or a mean too large to round."""
    if not values:
        return None
    total = sum((Decimal(v) for v in values), Decimal(0))
    mean = _CTX.divide(total, Decimal(len(values)))
    try:
        return _plain(mean.quantize(PLACES, rounding=ROUND_HALF_EVEN, context=_CTX))
    except InvalidOperation:
        return None


def reproduction_verdict(
    reported: str, reproduced: str | None, tolerance: str, kind: Literal["absolute", "relative"]
) -> Verdict:
    if reproduced is None:
        return "no-runs-completed"
    reported_d, reproduced_d, tol = Decimal(reported), Decimal(reproduced), Decimal(tolerance)
    allowed = tol if kind == "absolute" else _CTX.multiply(tol, abs(reported_d))
    distance = abs(_CTX.subtract(reproduced_d, reported_d))
    return "reproduced" if distance <= allowed else "not-reproduced"
