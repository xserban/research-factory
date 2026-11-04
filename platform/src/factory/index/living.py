"""Projection of review snapshots (living-B): one row per `living.snapshot_recorded` event.

Handlers are total and first-write-wins (a second event for a known snapshot id changes nothing).
`snapshots` is empty for a log without snapshot events, so it is left out of the state hash then.
"""

from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.living import SnapshotRecorded


def living_tables(metadata: MetaData) -> Table:
    return Table(
        "snapshots",
        metadata,
        Column("snapshot_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("cutoff_event", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("blob", String, nullable=False),
        Column("projection_version", String, nullable=False),
        Column("trigger", String, nullable=False),
    )


def living_handlers(snapshots: Table) -> dict[str, Handler]:
    def snapshot_recorded(conn: Connection, event: Event) -> None:
        payload = SnapshotRecorded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(snapshots)
            .values(
                snapshot_id=payload.snapshot_id,
                event_id=event.id,
                ts=format_ts(event.ts),
                cutoff_event=payload.cutoff_event,
                protocol_id=payload.protocol_id,
                blob=payload.blob,
                projection_version=payload.projection_version,
                trigger=payload.trigger,
            )
            .on_conflict_do_nothing(index_elements=["snapshot_id"])
        )

    return {"living.snapshot_recorded": snapshot_recorded}
