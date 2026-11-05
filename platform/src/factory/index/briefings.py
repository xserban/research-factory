"""Projection of served context packs (slice 7b, plan V-C; spec ruling 24, R-133).

`briefings_served` keeps one row per session and pack, the first `briefing.served` of the pair.

A serving is folded only when it is consistent with what `services/briefing.py` enforces; an event
that fails this stays in the log and changes nothing (no service writes one, so it was written by
hand):
- It comes from the system actor of the session it names, for the audience `agent` (the only one
  served; the event keeps `human` for the spec's schema).
- The session has joined no pass at that point of the log (decisions 43, 48).
- `as_of` is an earlier event of the log, and not a serving: a pack describes the log without them.
- The blob holds a briefing of this project built at `as_of` (when the blob store is at hand).

Handlers are total: a failure at any point folds nothing and never raises, on rebuild too.
"""

from __future__ import annotations

from sqlalchemy import Column, Index, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.clock import format_ts
from factory.errors import FactoryError
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.views import BriefingServed


def briefing_tables(metadata: MetaData) -> Table:
    return Table(
        "briefings_served",
        metadata,
        Column("session", String, primary_key=True),
        Column("blob", String, primary_key=True),
        Column("audience", String, nullable=False),
        Column("as_of", String, nullable=False),
        Column("ts", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_briefings_served_blob", "blob"),
    )


def briefing_handlers(served: Table, blobs: BlobStore | None) -> dict[str, Handler]:
    def fold(conn: Connection, event: Event) -> None:
        payload = BriefingServed.model_validate(event.payload)
        if not _consistent(conn, event, payload) or not _pack_matches(blobs, event, payload):
            return
        conn.execute(
            sqlite_insert(served)
            .values(
                session=payload.session,
                blob=payload.blob,
                audience=payload.audience,
                as_of=payload.as_of,
                ts=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["session", "blob"])
        )

    def total(conn: Connection, event: Event) -> None:
        try:
            with conn.begin_nested():
                fold(conn, event)
        except (ValueError, KeyError, TypeError, AttributeError, FactoryError, SQLAlchemyError):
            return

    return {"briefing.served": total}


def _consistent(conn: Connection, event: Event, payload: BriefingServed) -> bool:
    if event.actor.kind != "system" or event.actor.session != payload.session:
        return False
    if payload.audience != "agent" or payload.as_of >= event.id:
        return False
    position = conn.execute(
        text("SELECT type FROM events WHERE id = :i"), {"i": payload.as_of}
    ).first()
    if position is None or position[0] == "briefing.served":
        return False
    joined = conn.execute(
        text(
            "SELECT 1 FROM pass_sessions WHERE session = :s "
            "UNION ALL SELECT 1 FROM extraction_sessions WHERE session = :s LIMIT 1"
        ),
        {"s": payload.session},
    ).first()
    return joined is None


def _pack_matches(blobs: BlobStore | None, event: Event, payload: BriefingServed) -> bool:
    """Whether the blob holds a briefing of this project at `as_of`. Without a blob store the
    check cannot be made and is skipped."""
    if blobs is None:
        return True
    try:
        data = blobs.get_json(payload.blob)
    except (FactoryError, OSError, ValueError):
        return False
    meta = data.get("meta") if isinstance(data, dict) else None
    return (
        isinstance(meta, dict)
        and meta.get("view") == "briefing"
        and meta.get("project") == event.project
        and meta.get("as_of") == payload.as_of
    )
