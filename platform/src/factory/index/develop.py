"""Projection of rendered level documents (slice 8, plan A9).

`document_renders` has one row per `document.rendered` event: its level, version, source event
ids (a JSON list) and blob ref. Nothing else reads it. The table is left out of the state hash
while empty.

The fold is total and atomic: an event that does not come from the system actor, or whose version
is not one more than the level's latest, or whose payload does not validate, changes nothing and never raises.
"""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.develop import DocumentRendered


def develop_tables(metadata: MetaData) -> Table:
    return Table(
        "document_renders",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("level", String, nullable=False),
        Column("version", Integer, nullable=False),
        Column("ts", String, nullable=False),
        Column("sources", String, nullable=False),
        Column("blob", String, nullable=False),
    )


def develop_handlers(table: Table) -> dict[str, Handler]:
    def rendered(conn: Connection, event: Event) -> None:
        if event.actor.kind != "system":
            return
        try:
            p = DocumentRendered.model_validate(event.payload)
        except ValidationError:
            return
        latest = conn.execute(
            select(func.max(table.c.version)).where(table.c.level == p.level.value)
        ).scalar_one()
        if p.version != (0 if latest is None else int(latest)) + 1:
            return
        conn.execute(
            sqlite_insert(table)
            .values(
                event_id=event.id,
                level=p.level.value,
                version=p.version,
                ts=format_ts(event.ts),
                sources=canonical_json(list(p.sources)).decode(),
                blob=p.blob,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return {"document.rendered": rendered}
