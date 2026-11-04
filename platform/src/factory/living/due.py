"""When a watched source is next due, computed from finished cycles (slice 4b, ruling 5).

Pure. Nothing is stored: due times are derived on read from `CycleView`s, so tests run on a
fixed clock and a rebuilt index gives the same answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from factory.model.watch import CycleStatus, WatchPlan, WatchSource


@dataclass(frozen=True)
class CycleView:
    """One watch cycle as the index records it.

    `sources` are the sources the cycle ran; `complete_sources` those whose every run completed;
    `full_replay_sources` those that ran as a full replay (not a window); `protocol_id` the
    protocol version the cycle ran under (empty when unknown).
    """

    cycle_id: str
    started_at: datetime
    finished_at: datetime | None
    status: CycleStatus
    sources: tuple[str, ...]
    complete_sources: tuple[str, ...]
    full_replay_sources: tuple[str, ...]
    protocol_id: str = ""


def next_due(plan: WatchSource, cycles: Sequence[CycleView]) -> datetime | None:
    """When `plan.source` is next due; None means due now because it has never finished a cycle.

    The last `finished_at` among cycles that covered the source, plus `interval_days`. An open
    cycle has not finished and moves nothing.
    """
    finished = [
        c.finished_at for c in cycles if plan.source in c.sources and c.finished_at is not None
    ]
    if not finished:
        return None
    return max(finished) + timedelta(days=plan.interval_days)


def due_sources(plan: WatchPlan, cycles: Sequence[CycleView], now: datetime) -> tuple[str, ...]:
    """The sources due at `now`, sorted. Empty once `plan.until` is before `now`'s date."""
    if plan.until is not None and plan.until < now.date():
        return ()
    due = [
        item.source
        for item in plan.sources
        if (when := next_due(item, cycles)) is None or when <= now
    ]
    return tuple(sorted(due))


def consecutive_failures(source: str, cycles: Sequence[CycleView]) -> int:
    """How many of the source's most recent cycles ended without it completing.

    Counted back from the latest cycle that covered the source; a cycle in which every run of the
    source completed ends the count. An open cycle counts as not yet complete.
    """
    covering = sorted((c for c in cycles if source in c.sources), key=lambda c: c.started_at)
    count = 0
    for cycle in reversed(covering):
        if source in cycle.complete_sources:
            break
        count += 1
    return count
