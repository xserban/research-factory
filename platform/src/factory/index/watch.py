"""Projection of watch cycles: the cycle, the sources it ran and the search runs it grouped.

`watch_cycles` keeps each cycle (open until `watch.cycle_finished`), `watch_cycle_sources` the
sources it ran with their mode, window start and whether every planned query of the source
completed, and `watch_cycle_runs` the runs that named the cycle as the last ref of their
`search.run_started` event, in the order they started (`seq`).

Handlers are total and first-write-wins: a second start or finish of a known cycle, a finish of an
unknown cycle, and a run that names an unknown or finished cycle change nothing. Rules use event
data only (`event.ts`, never the wall clock), so a rebuild reproduces the incremental state.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.search import SearchRunStarted
from factory.model.watch import CycleStatus, WatchCycleFinished, WatchCycleStarted

CYCLE_REF_PREFIX = "wcy_"


@dataclass(frozen=True)
class WatchTables:
    cycles: Table
    sources: Table
    runs: Table
    search_runs: Table
    """The search projection's `runs` table, read to name a run's source."""


def watch_tables(metadata: MetaData, search_runs: Table) -> WatchTables:
    cycles = Table(
        "watch_cycles",
        metadata,
        Column("cycle_id", String, primary_key=True),
        Column("started_event", String, nullable=False),
        Column("started_at", String, nullable=False),
        Column("finished_at", String),
        Column("status", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("trigger", String, nullable=False),
        Column("note", String),
        Column("dedup_complete", Integer),
        Column("reconciled", String),
    )
    sources = Table(
        "watch_cycle_sources",
        metadata,
        Column("cycle_id", String, primary_key=True),
        Column("source", String, primary_key=True),
        Column("mode", String, nullable=False),
        Column("window_start", String),
        Column("full_replay", Integer, nullable=False),
        Column("complete", Integer, nullable=False),
    )
    runs = Table(
        "watch_cycle_runs",
        metadata,
        Column("cycle_id", String, primary_key=True),
        Column("run_id", String, primary_key=True),
        Column("query_id", String, nullable=False),
        Column("source", String, nullable=False),
        Column("seq", Integer, nullable=False),
    )
    return WatchTables(cycles, sources, runs, search_runs)


def watch_handlers(t: WatchTables) -> dict[str, Handler]:
    return {
        "watch.cycle_started": _started(t),
        "watch.cycle_finished": _finished(t),
    }


def run_started_handler(t: WatchTables) -> Handler:
    """Link a run to the cycle it names as the last ref of its `search.run_started` event.

    Runs after the search projection's own handler, which creates the run row this one reads.
    """

    def run_started(conn: Connection, event: Event) -> None:
        if not event.refs or not event.refs[-1].startswith(CYCLE_REF_PREFIX):
            return
        cycle_id = event.refs[-1]
        payload = SearchRunStarted.model_validate(event.payload)
        cycle = conn.execute(
            select(t.cycles.c.status).where(t.cycles.c.cycle_id == cycle_id)
        ).one_or_none()
        if cycle is None or cycle.status != CycleStatus.OPEN.value:
            return
        run = conn.execute(
            select(t.search_runs.c.source).where(t.search_runs.c.run_id == payload.run_id)
        ).one_or_none()
        if run is None:
            return
        seq = conn.execute(select(func.count()).select_from(t.runs)).scalar_one() + 1
        conn.execute(
            sqlite_insert(t.runs)
            .values(
                cycle_id=cycle_id,
                run_id=payload.run_id,
                query_id=payload.query_id,
                source=run.source,
                seq=seq,
            )
            .on_conflict_do_nothing(index_elements=["cycle_id", "run_id"])
        )

    return run_started


def _started(t: WatchTables) -> Handler:
    def started(conn: Connection, event: Event) -> None:
        payload = WatchCycleStarted.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.cycles)
            .values(
                cycle_id=payload.cycle_id,
                started_event=event.id,
                started_at=format_ts(event.ts),
                finished_at=None,
                status=CycleStatus.OPEN.value,
                protocol_id=payload.protocol_id,
                trigger=payload.trigger,
                note=None,
            )
            .on_conflict_do_nothing(index_elements=["cycle_id"])
        ).rowcount
        if not inserted:
            return
        for item in payload.sources:
            conn.execute(
                sqlite_insert(t.sources).values(
                    cycle_id=payload.cycle_id,
                    source=item.source,
                    mode=item.mode,
                    window_start=None
                    if item.window_start is None
                    else item.window_start.isoformat(),
                    full_replay=int(item.full_replay),
                    complete=0,
                )
            )

    return started


def _finished(t: WatchTables) -> Handler:
    def finished(conn: Connection, event: Event) -> None:
        payload = WatchCycleFinished.model_validate(event.payload)
        current = conn.execute(
            select(t.cycles.c.status).where(t.cycles.c.cycle_id == payload.cycle_id)
        ).one_or_none()
        if current is None or current.status != CycleStatus.OPEN.value:
            return
        conn.execute(
            update(t.cycles)
            .where(t.cycles.c.cycle_id == payload.cycle_id)
            .values(
                status=payload.status.value,
                finished_at=format_ts(event.ts),
                note=payload.note,
                dedup_complete=int(payload.dedup_complete),
                reconciled=canonical_json(list(payload.reconciled)).decode(),
            )
        )
        for counts in payload.counts:
            conn.execute(
                update(t.sources)
                .where(
                    t.sources.c.cycle_id == payload.cycle_id, t.sources.c.source == counts.source
                )
                .values(complete=int(counts.complete))
            )

    return finished
