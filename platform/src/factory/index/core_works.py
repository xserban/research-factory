"""Projection of core-work marks (slice 8, IDEA-43): the works a forward round may start from.

`core_works` holds one row per work currently marked core: the note and the marking event.

Folded only if (a hand-written event failing a guard changes nothing on rebuild):
- `work.marked_core`: the actor is a human; the work is known to the index; the work is not
  already marked (the first mark and its note stand).
- `work.unmarked_core`: the actor is a human and the work is marked. The row is removed; the
  events stay in the log, and a later mark starts a new row.

Handlers are total: an event that does not validate changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, MetaData, String, Table, delete, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.core_works import WorkMarkedCore, WorkUnmarkedCore


@dataclass(frozen=True)
class CoreWorkTables:
    core: Table


def core_work_tables(metadata: MetaData) -> CoreWorkTables:
    core = Table(
        "core_works",
        metadata,
        Column("work_id", String, primary_key=True),
        Column("note", String),
        Column("event_id", String, nullable=False),
        Column("marked_by", String, nullable=False),
    )
    return CoreWorkTables(core)


def _marked(t: CoreWorkTables) -> Handler:
    def marked(conn: Connection, event: Event) -> None:
        p = WorkMarkedCore.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        known = conn.execute(
            text("SELECT 1 FROM works WHERE work_id = :w"), {"w": p.work_id}
        ).first()
        if known is None:
            return
        conn.execute(
            sqlite_insert(t.core)
            .values(work_id=p.work_id, note=p.note, event_id=event.id, marked_by=event.actor.id)
            .on_conflict_do_nothing(index_elements=["work_id"])
        )

    return _total(marked)


def _unmarked(t: CoreWorkTables) -> Handler:
    def unmarked(conn: Connection, event: Event) -> None:
        p = WorkUnmarkedCore.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        conn.execute(delete(t.core).where(t.core.c.work_id == p.work_id))

    return _total(unmarked)


def _total(handler: Handler) -> Handler:
    def run(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError, IndexError):
            return

    return run


def core_work_handlers(t: CoreWorkTables) -> dict[str, Handler]:
    return {"work.marked_core": _marked(t), "work.unmarked_core": _unmarked(t)}
