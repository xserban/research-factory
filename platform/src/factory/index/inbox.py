"""Projection of the link inbox: captured items and every resolution attempt (slice 4a).

`inbox_items` keeps one row per captured item with its status: `open` at capture, `resolved`
after any resolution other than `failed`, `withdrawn` after a withdrawal. `inbox_resolutions`
keeps every attempt on an open item, failed ones included.

Handlers are total: a second capture under an existing id, and a resolution or withdrawal of an
unknown or closed item, change nothing (the service refuses these before writing).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, MetaData, String, Table, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.inbox import InboxLinkAdded, InboxLinkResolved, InboxLinkWithdrawn, ResolveStatus

OPEN = "open"
RESOLVED = "resolved"
WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class InboxTables:
    items: Table
    resolutions: Table


def inbox_tables(metadata: MetaData) -> InboxTables:
    items = Table(
        "inbox_items",
        metadata,
        Column("item_id", String, primary_key=True),
        Column("route", String, nullable=False),
        Column("identifier_kind", String, nullable=False),
        Column("identifier_value", String, nullable=False),
        Column("identifier_version", String),
        Column("link", String, nullable=False),
        Column("actor_kind", String, nullable=False),
        Column("session", String, nullable=False),
        Column("channel", String, nullable=False),
        Column("basis", String),
        Column("note", String),
        Column("added_event_id", String, nullable=False),
        Column("status", String, nullable=False),
        Column("withdrawn_event_id", String),
    )
    resolutions = Table(
        "inbox_resolutions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("item_id", String, nullable=False, index=True),
        Column("query_id", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("status", String, nullable=False),
        Column("work_id", String),
        Column("deviation_id", String),
    )
    return InboxTables(items, resolutions)


def inbox_handlers(t: InboxTables) -> dict[str, Handler]:
    return {
        "inbox.link_added": _added(t),
        "inbox.link_withdrawn": _withdrawn(t),
        "inbox.link_resolved": _resolved(t),
    }


def _is_open(conn: Connection, t: InboxTables, item_id: str) -> bool:
    status = conn.execute(
        select(t.items.c.status).where(t.items.c.item_id == item_id)
    ).scalar_one_or_none()
    return status == OPEN


def _added(t: InboxTables) -> Handler:
    def added(conn: Connection, event: Event) -> None:
        payload = InboxLinkAdded.model_validate(event.payload)
        basis = (
            None
            if payload.basis is None
            else canonical_json(payload.basis.model_dump(mode="json")).decode()
        )
        conn.execute(
            sqlite_insert(t.items)
            .values(
                item_id=payload.item_id,
                route=payload.route.value,
                identifier_kind=payload.identifier_kind.value,
                identifier_value=payload.identifier_value,
                identifier_version=payload.identifier_version,
                link=payload.link,
                actor_kind=event.actor.kind,
                session=event.actor.session,
                channel=payload.channel.value,
                basis=basis,
                note=payload.note,
                added_event_id=event.id,
                status=OPEN,
                withdrawn_event_id=None,
            )
            .on_conflict_do_nothing(index_elements=["item_id"])
        )

    return added


def _withdrawn(t: InboxTables) -> Handler:
    def withdrawn(conn: Connection, event: Event) -> None:
        payload = InboxLinkWithdrawn.model_validate(event.payload)
        conn.execute(
            update(t.items)
            .where(t.items.c.item_id == payload.item_id, t.items.c.status == OPEN)
            .values(status=WITHDRAWN, withdrawn_event_id=event.id)
        )

    return withdrawn


def _resolved(t: InboxTables) -> Handler:
    def resolved(conn: Connection, event: Event) -> None:
        payload = InboxLinkResolved.model_validate(event.payload)
        if not _is_open(conn, t, payload.item_id):
            return
        conn.execute(
            insert(t.resolutions).values(
                event_id=event.id,
                item_id=payload.item_id,
                query_id=payload.query_id,
                run_id=payload.run_id,
                status=payload.status.value,
                work_id=payload.work_id,
                deviation_id=payload.deviation_id,
            )
        )
        if payload.status is not ResolveStatus.FAILED:
            conn.execute(
                update(t.items).where(t.items.c.item_id == payload.item_id).values(status=RESOLVED)
            )

    return resolved
