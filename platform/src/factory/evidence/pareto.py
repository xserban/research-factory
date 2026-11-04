"""Deterministic Pareto frontier and within-paper speed ratio (plan 2E, rulings 7 and 8).

Pure: no project, index or I/O. Invariants:

* Every cost is positive; a non-positive cost raises ``ValueError``.
* Points are processed in the total order ``(cost, metric best-first, method, work_id, row_key)``,
  so the result does not depend on input order.
* ``q`` dominates ``p`` iff ``q.cost <= p.cost``, ``q``'s metric is at least as good, and at
  least one of the two is strictly better. Identical (cost, metric) points never dominate each
  other and all stay on the frontier.
* ``frontier`` and ``dominated`` are in sorted order; each dominated point is paired with the
  first dominating point in sorted order (which is always itself a frontier point).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class Point:
    """One candidate frontier point; ``cost`` is strictly positive."""

    row_key: str
    cost: Decimal
    metric: Decimal
    method: str
    work_id: str


@dataclass(frozen=True)
class ParetoResult:
    """Frontier points and ``(dominated point, first dominating point)`` pairs, sorted."""

    frontier: tuple[Point, ...]
    dominated: tuple[tuple[Point, Point], ...]


def pareto(points: Sequence[Point], *, higher_is_better: bool) -> ParetoResult:
    """Compute the Pareto frontier of ``points`` over (low cost, good metric)."""
    for p in points:
        if p.cost <= 0:
            raise ValueError(f"cost must be positive: {p.row_key} has {p.cost}")

    def key(p: Point) -> tuple[Decimal, Decimal, str, str, str]:
        metric = -p.metric if higher_is_better else p.metric
        return (p.cost, metric, p.method, p.work_id, p.row_key)

    def better(a: Decimal, b: Decimal) -> bool:
        return a > b if higher_is_better else a < b

    ordered = sorted(points, key=key)
    frontier: list[Point] = []
    dominated: list[tuple[Point, Point]] = []
    best_cheaper: Decimal | None = None  # best metric among strictly cheaper points
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j].cost == ordered[i].cost:
            j += 1
        group = ordered[i:j]
        group_best = group[0].metric  # sorted best-first within the cost group
        group_on_frontier = best_cheaper is None or better(group_best, best_cheaper)
        for p in group:
            if group_on_frontier and p.metric == group_best:
                frontier.append(p)
            else:
                dominator = next(q for q in frontier if _dominates(q, p, higher_is_better))
                dominated.append((p, dominator))
        if best_cheaper is None or better(group_best, best_cheaper):
            best_cheaper = group_best
        i = j
    return ParetoResult(tuple(frontier), tuple(dominated))


def _dominates(q: Point, p: Point, higher_is_better: bool) -> bool:
    if q.cost > p.cost:
        return False
    if higher_is_better:
        at_least, strict_metric = q.metric >= p.metric, q.metric > p.metric
    else:
        at_least, strict_metric = q.metric <= p.metric, q.metric < p.metric
    return at_least and (q.cost < p.cost or strict_metric)


def speed_ratio(proposed: Decimal, baseline: Decimal, *, higher_is_faster: bool) -> Decimal | None:
    """How many times faster ``proposed`` is than ``baseline``, to 2 places (half-even).

    Throughput (``higher_is_faster``): proposed / baseline. Latency: baseline / proposed.
    ``None`` unless both values are positive.
    """
    if proposed <= 0 or baseline <= 0:
        return None
    ratio = proposed / baseline if higher_is_faster else baseline / proposed
    return ratio.quantize(_TWO_PLACES, rounding=ROUND_HALF_EVEN)
