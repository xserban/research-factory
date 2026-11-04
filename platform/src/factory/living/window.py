"""Window start and full-replay cadence for a watched source (slice 4b, rulings 2 and 4).

Pure. A window query is the planned query plus `filters["listed_since"]`, a listing-date filter
the source adapter understands; it is never a publication-date filter (R-21).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from factory.living.due import CycleView
from factory.model.protocol import PlannedQuery
from factory.model.search import QueryPurpose, QuerySpec
from factory.model.watch import WatchSource

LISTED_SINCE = "listed_since"


def _complete(source: str, cycles: Sequence[CycleView]) -> list[CycleView]:
    return sorted((c for c in cycles if source in c.complete_sources), key=lambda c: c.started_at)


def window_start(source: WatchSource, cycles: Sequence[CycleView]) -> date | None:
    """The date a window query lists from; None when the source has no complete cycle (run full).

    It is the start of the last cycle in which every run of the source completed, minus
    `overlap_days`. A partial cycle advances nothing.
    """
    complete = _complete(source.source, cycles)
    if not complete:
        return None
    return (complete[-1].started_at - timedelta(days=source.overlap_days)).date()


def is_full_replay(source: WatchSource, cycles: Sequence[CycleView]) -> bool:
    """Whether the source's next cycle is a full replay.

    True for `full` mode, with no complete cycle yet, with no complete full replay yet, or when
    the complete cycles since the last complete full replay number `full_replay_every - 1`.
    """
    if source.mode == "full":
        return True
    complete = _complete(source.source, cycles)
    replays = [c for c in complete if source.source in c.full_replay_sources]
    if not replays or source.full_replay_every is None:
        return True
    since = [c for c in complete if c.started_at > replays[-1].started_at]
    return len(since) >= source.full_replay_every - 1


def window_spec(planned: PlannedQuery, start: date) -> QuerySpec:
    """The planned query restricted to records listed since `start`; purpose `search`."""
    return QuerySpec(
        source=planned.source,
        kind=planned.kind,
        text=planned.text,
        purpose=QueryPurpose.SEARCH,
        filters={**planned.filters, LISTED_SINCE: start.isoformat()},
    )
