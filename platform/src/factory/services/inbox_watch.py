"""The candidate inbox as a computed view of pending works by discovery route (living-B).

No event type and no table: the view is built from the discovery record (first-surfaced route
and surfacing event, slice 4a), the watch cycle runs (`watch_cycle_runs`) and the title/abstract
outcomes. A work whose first-surfaced route is a watch cycle's search run has route
`database:<source>` and the cycle id as `route_ref`; any other work carries its discovery route
and its surfacing event id as `route_ref`.

Invariants:
- Entries are the canonical works whose title/abstract outcome is pending, ordered by
  `surfaced_at` (an event id, so event order) and then work id.
- It is a human view (the CLI) and has no MCP caller. Held-out seed works are listed like any
  other: leaving them out would tell the human which works are held out (decision 37 item 9).
- The view reads only. It does not touch the screening queue, whose order stays randomised
  (R-34); no priority is carried.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.discovery import discovery

WATCH_ROUTE_PREFIX = "database:"


class InboxEntry(StrictModel):
    """One pending work: how it first reached the corpus and at which event."""

    work_id: str
    route: str
    route_ref: str
    surfaced_at: str


def _watch_runs(project: Project) -> dict[str, tuple[str, str]]:
    """Each watch-cycle `search.run_started` event id mapped to (cycle id, source)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rs.id, w.cycle_id, w.source FROM watch_cycle_runs w"
                " JOIN events rs ON rs.type = 'search.run_started'"
                " AND json_extract(rs.refs, '$[0]') = w.run_id"
            )
        ).all()
    return {str(r[0]): (str(r[1]), str(r[2])) for r in rows}


def inbox_entries(
    project: Project, *, route: str | None = None, limit: int = 100, after: str | None = None
) -> list[InboxEntry]:
    """Pending works at title/abstract, ordered by surfacing event; `after` is the work id of the
    last entry of the previous page. `route` keeps one route (`database:<source>` for watches)."""
    project.index.sync()
    pending = {w for w, o in final_outcomes(project).items() if o is Outcome.PENDING}
    runs = _watch_runs(project)
    entries: list[InboxEntry] = []
    for record in discovery(project):
        if record.work_id not in pending:
            continue
        watch = runs.get(record.first_event_id)
        if watch is not None:
            cycle_id, source = watch
            entry = InboxEntry(
                work_id=record.work_id,
                route=f"{WATCH_ROUTE_PREFIX}{source}",
                route_ref=cycle_id,
                surfaced_at=record.first_event_id,
            )
        else:
            entry = InboxEntry(
                work_id=record.work_id,
                route=record.first_route.value,
                route_ref=record.first_event_id,
                surfaced_at=record.first_event_id,
            )
        if route is None or entry.route == route:
            entries.append(entry)
    entries.sort(key=lambda e: (e.surfaced_at, e.work_id))
    if after is not None:
        position = next((i for i, e in enumerate(entries) if e.work_id == after), None)
        if position is not None:
            entries = entries[position + 1 :]
    return entries[:limit]
