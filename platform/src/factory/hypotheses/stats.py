"""Paired statistics in exact decimal arithmetic (slice 6, plan XP-B, rulings 2 and 3). Pure.

Invariants:
- Arithmetic uses a local `Decimal` context of 28 digits; the mean is the exact sum over n, the
  standard deviation is the sample one (n - 1), the standard error is sd over the square root of n
  (`Decimal.sqrt`), and the interval is mean +/- t * se with the embedded table's quantile at
  df = n - 1 (`tquantiles`).
- Every stored result is quantised to six places, half-even; no floating point is used.
- With fewer than two differences there is no sd, se or interval (all `None`).
- Orientation: the difference is treatment - baseline for a `higher` metric and baseline -
  treatment for a `lower` one, so a positive difference always means "treatment better".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Literal

from factory.hypotheses.tquantiles import Level, t_quantile

PLACES = Decimal("0.000001")
_CTX = Context(prec=28)

Direction = Literal["higher", "lower"]


@dataclass(frozen=True)
class PairedSummary:
    n: int
    mean: Decimal
    sd: Decimal | None
    se: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    level: Level


def quantise(value: Decimal) -> Decimal:
    return value.quantize(PLACES, rounding=ROUND_HALF_EVEN, context=_CTX)


def plain(value: Decimal) -> str:
    """A quantised value as a plain canonical decimal (no exponent, no trailing zeros)."""
    q = quantise(value)
    return "0" if q == 0 else format(q.normalize(_CTX), "f")


def oriented(treatment: Decimal, baseline: Decimal, direction: Direction) -> Decimal:
    """The difference in the direction where positive means "treatment better"."""
    return (
        _CTX.subtract(treatment, baseline)
        if direction == "higher"
        else _CTX.subtract(baseline, treatment)
    )


def paired_summary(diffs: Sequence[Decimal], level: Level) -> PairedSummary:
    n = len(diffs)
    if n == 0:
        raise ValueError("a summary needs at least one difference")
    total = Decimal(0)
    for d in diffs:
        total = _CTX.add(total, d)
    mean = _CTX.divide(total, Decimal(n))
    if n < 2:
        return PairedSummary(n, quantise(mean), None, None, None, None, level)
    squares = Decimal(0)
    for d in diffs:
        dev = _CTX.subtract(d, mean)
        squares = _CTX.add(squares, _CTX.multiply(dev, dev))
    variance = _CTX.divide(squares, Decimal(n - 1))
    sd = variance.sqrt(_CTX)
    se = _CTX.divide(sd, Decimal(n).sqrt(_CTX))
    half = _CTX.multiply(t_quantile(level, n - 1), se)
    return PairedSummary(
        n,
        quantise(mean),
        quantise(sd),
        quantise(se),
        quantise(_CTX.subtract(mean, half)),
        quantise(_CTX.add(mean, half)),
        level,
    )
