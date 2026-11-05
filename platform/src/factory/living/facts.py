"""Conclusion facts of a living review (slice 4b, plan living-D): computed, never typed.

`conclusion_facts` reads an `EvidenceReport` and states, per comparability group, which rows lie
on each frontier partition, how many independent rows the group holds and, where defined, which
independent row or rows are best. `facts_diff` compares two such readings. Both are pure.

Invariants:
- `best` is defined only for a group whose metric direction is known (`declared` or
  `pack-default`), whose metric is a group key and whose independent numeric rows share one value
  unit; otherwise it is None with a reason, never a guess (plan ruling 1). Ties are all listed,
  sorted. Copied rows are never candidates (decision 52).
- The same report always gives the same facts, in the same order (groups by id, keys sorted).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from factory.model.base import StrictModel

if TYPE_CHECKING:
    from factory.services.evidence_report import EvidenceReport, GroupReport


class GroupFacts(StrictModel):
    """The facts of one comparability group. `frontier` maps `<axis>|<unit>|<resolution>` (with
    `|<metric>` appended when the partition is split by metric) to the sorted row keys on that
    frontier."""

    group_id: str
    independent_rows: int
    frontier: dict[str, tuple[str, ...]]
    best: tuple[str, ...] | None
    best_reason: str | None


class ConclusionFacts(StrictModel):
    """The facts a conclusion may rest on: groups sorted by id, the included-set size and the
    lineage paths (source, target, exists) when slice 3b supplies them."""

    included: int
    groups: tuple[GroupFacts, ...]
    paths: tuple[tuple[str, str, bool], ...] = ()


class GroupDiff(StrictModel):
    """What changed in one group present in both readings."""

    group_id: str
    frontier_added: dict[str, tuple[str, ...]]
    frontier_removed: dict[str, tuple[str, ...]]
    best_changed: tuple[tuple[str, ...] | None, tuple[str, ...] | None] | None
    rows_delta: int


class FactsDiff(StrictModel):
    """The difference between two readings; `groups` lists only groups that changed."""

    groups_added: tuple[str, ...]
    groups_removed: tuple[str, ...]
    groups: tuple[GroupDiff, ...]
    included_delta: int

    @property
    def empty(self) -> bool:
        return not (self.groups_added or self.groups_removed or self.groups or self.included_delta)


def conclusion_facts(
    report: EvidenceReport,
    *,
    included: int,
    paths: Sequence[tuple[str, str, bool]] = (),
) -> ConclusionFacts:
    """The facts of `report`; `included` is the size of the included set, `paths` the lineage
    reachability facts (empty without slice 3b)."""
    groups = sorted((_group_facts(g) for g in report.groups), key=lambda g: g.group_id)
    return ConclusionFacts(included=included, groups=tuple(groups), paths=tuple(sorted(paths)))


def _group_facts(group: GroupReport) -> GroupFacts:
    frontier: dict[str, tuple[str, ...]] = {}
    for axis in group.frontiers:
        for part in axis.partitions:
            key = f"{axis.axis}|{part.unit or ''}|{part.resolution or ''}"
            if part.metric is not None:
                key += f"|{part.metric}"
            frontier[key] = tuple(sorted(p.row_key for p in part.points if p.on_frontier))
    best, reason = _best(group)
    return GroupFacts(
        group_id=group.group_id,
        independent_rows=group.counts.independent,
        frontier=dict(sorted(frontier.items())),
        best=best,
        best_reason=reason,
    )


def _best(group: GroupReport) -> tuple[tuple[str, ...] | None, str | None]:
    if group.direction_status not in ("declared", "pack-default") or group.direction is None:
        return None, "direction-unknown"
    if "metric" not in dict(group.key):
        return None, "metric-not-a-key"
    values: list[tuple[str, str | None, Decimal]] = []
    for row in group.rows:
        if not row.independent:
            continue
        number = _number(row.value.canonical)
        if number is not None:
            values.append((row.row_key, row.value.unit, number))
    if not values:
        return None, "no-numeric-value"
    if len({unit for _, unit, _ in values}) > 1:
        return None, "units-differ"
    top = (max if group.direction else min)(v for _, _, v in values)
    return tuple(sorted(k for k, _, v in values if v == top)), None


def _number(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def facts_diff(old: ConclusionFacts, new: ConclusionFacts) -> FactsDiff:
    """What changed from `old` to `new`; pure."""
    before = {g.group_id: g for g in old.groups}
    after = {g.group_id: g for g in new.groups}
    changed: list[GroupDiff] = []
    for gid in sorted(before.keys() & after.keys()):
        a, b = before[gid], after[gid]
        added: dict[str, tuple[str, ...]] = {}
        removed: dict[str, tuple[str, ...]] = {}
        for key in sorted(a.frontier.keys() | b.frontier.keys()):
            was, now = set(a.frontier.get(key, ())), set(b.frontier.get(key, ()))
            if now - was:
                added[key] = tuple(sorted(now - was))
            if was - now:
                removed[key] = tuple(sorted(was - now))
        best = (a.best, b.best) if a.best != b.best else None
        delta = b.independent_rows - a.independent_rows
        if added or removed or best is not None or delta:
            changed.append(
                GroupDiff(
                    group_id=gid,
                    frontier_added=added,
                    frontier_removed=removed,
                    best_changed=best,
                    rows_delta=delta,
                )
            )
    return FactsDiff(
        groups_added=tuple(sorted(after.keys() - before.keys())),
        groups_removed=tuple(sorted(before.keys() - after.keys())),
        groups=tuple(changed),
        included_delta=new.included - old.included,
    )
