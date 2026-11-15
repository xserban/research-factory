"""Projection of registered study files: one row per registration, versions kept (plan
flow-transparency, part B).

`registered_files` holds every `file.registered` event: path, content hash, kind, title, the blob
holding the content, the event id, the registration it supersedes and its date. The latest version
of a path is the row with the greatest event id. Handlers are total: a second fold of the same
event changes nothing.
"""

from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.files import FileRegistered


def file_tables(metadata: MetaData) -> Table:
    return Table(
        "registered_files",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("path", String, nullable=False, index=True),
        Column("sha256", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("title", String),
        Column("blob", String, nullable=False),
        Column("supersedes", String),
        Column("registered_at", String, nullable=False),
    )


def file_handlers(table: Table) -> dict[str, Handler]:
    def registered(conn: Connection, event: Event) -> None:
        payload = FileRegistered.model_validate(event.payload)
        if event.input_blob != f"sha256:{payload.sha256}":
            return  # the content blob is the file: a registration without it is no record
        conn.execute(
            sqlite_insert(table)
            .values(
                event_id=event.id,
                path=payload.path,
                sha256=payload.sha256,
                kind=payload.kind,
                title=payload.title,
                blob=event.input_blob,
                supersedes=payload.supersedes,
                registered_at=event.ts.isoformat(),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return {"file.registered": registered}
