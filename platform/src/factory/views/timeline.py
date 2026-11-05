"""Records and per-year frontiers of dated points (slice 7b, plan V-B, task 3; spec ruling 6).

Pure: no project, index or I/O. Declares: `DatedPoint`, `records`, `yearly_frontiers`.

Invariants:
- Only independent rows with a year take part; a copied row is never a record and never a
  frontier point (evidence-report ruling 6), an undated row is neither.
- A point is a record when its value is strictly better than every earlier-dated point's (the
  first dated year therefore makes every point sharing its best value a record). Rows of one year
  never make each other earlier. Output is ordered by (year, work id, row key) whatever the input
  order.
- The frontier of a year and an axis is `evidence.pareto.pareto` over the points dated up to and
  including that year with a positive cost on the axis, listed in the pareto order (cost, then
  metric best first); a year appears when at least one independent point carries it. Callers pass
  the points of one value unit and resolution; this module does not mix units.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from factory.evidence.pareto import Point, pareto


@dataclass(frozen=True)
class DatedPoint:
    trace_id: str
    work_id: str
    row_key: str
    year: int | None
    value: Decimal
    unit: str
    costs: Mapping[str, Decimal]
    independent: bool


def _order(p: DatedPoint) -> tuple[int, str, str]:
    assert p.year is not None
    return (p.year, p.work_id, p.row_key)


def _usable(points: Sequence[DatedPoint]) -> list[DatedPoint]:
    return sorted((p for p in points if p.independent and p.year is not None), key=_order)


def records(points: Sequence[DatedPoint], higher_is_better: bool) -> list[DatedPoint]:
    """The record points, in (year, work id, row key) order."""
    out: list[DatedPoint] = []
    best: Decimal | None = None  # best value among strictly earlier years
    pending: Decimal | None = None
    current: int | None = None
    for p in _usable(points):
        if p.year != current:
            if pending is not None and (best is None or _better(pending, best, higher_is_better)):
                best = pending
            current, pending = p.year, None
        if best is None or _better(p.value, best, higher_is_better):
            out.append(p)
        if pending is None or _better(p.value, pending, higher_is_better):
            pending = p.value
    return out


def _better(a: Decimal, b: Decimal, higher_is_better: bool) -> bool:
    return a > b if higher_is_better else a < b


def yearly_frontiers(
    points: Sequence[DatedPoint], higher_is_better: bool, axes: Sequence[str]
) -> dict[int, dict[str, list[str]]]:
    """Per year with a new independent dated point, per axis, the trace ids of the frontier of
    the points dated up to that year."""
    usable = _usable(points)
    out: dict[int, dict[str, list[str]]] = {}
    for year in sorted({p.year for p in usable if p.year is not None}):
        upto = [p for p in usable if p.year is not None and p.year <= year]
        out[year] = {axis: _frontier(upto, axis, higher_is_better) for axis in axes}
    return out


def _frontier(points: Sequence[DatedPoint], axis: str, higher_is_better: bool) -> list[str]:
    chosen = [
        Point(f"{p.work_id}|{p.trace_id}", p.costs[axis], p.value, "", p.work_id)
        for p in points
        if axis in p.costs and p.costs[axis] > 0
    ]
    if not chosen:
        return []
    names = {f"{p.work_id}|{p.trace_id}": p.trace_id for p in points}
    result = pareto(chosen, higher_is_better=higher_is_better)
    return [names[q.row_key] for q in result.frontier]
