"""Projection of notices and versions (living-C): observations and human acts, never states.

`notices` keeps one row per notice identity (the first observation wins; a repeat changes nothing).
Whether a work is retracted or a correction is pending is computed at read time from these rows
by `model.notices.notice_state`; nothing derived is stored here.

Handlers are total: an event naming an unknown notice or a repeated identity changes nothing.
Every table is empty for a log without the events, so each is left out of the state hash then.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.notices import NoticeObserved


@dataclass(frozen=True)
class NoticeTables:
    notices: Table


def notice_tables(metadata: MetaData) -> NoticeTables:
    notices = Table(
        "notices",
        metadata,
        Column("notice_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("identity", String, nullable=False),
        Column("notice_date", String),
        Column("notice_doi", String),
        Column("source", String, nullable=False),
        Column("run_id", String, nullable=False),
        Column("raw_blob", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("observed_at", String, nullable=False),
        Index("ix_notices_work", "work_id"),
        Index("uq_notices_identity", "work_id", "kind", "identity", unique=True),
    )
    return NoticeTables(notices)


def notice_handlers(t: NoticeTables) -> dict[str, Handler]:
    def observed(conn: Connection, event: Event) -> None:
        payload = NoticeObserved.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.notices)
            .values(
                notice_id=payload.notice_id,
                work_id=payload.work_id,
                kind=payload.kind.value,
                identity=payload.identity,
                notice_date=None
                if payload.notice_date is None
                else payload.notice_date.isoformat(),
                notice_doi=payload.notice_doi,
                source=payload.source,
                run_id=payload.run_id,
                raw_blob=payload.raw_blob,
                event_id=event.id,
                observed_at=format_ts(event.ts),
            )
            .on_conflict_do_nothing()
        )

    return {"notice.observed": observed}
