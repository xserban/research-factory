"""Projection of registered conclusions (living-D): one row per `conclusion.registered` event.

Handlers are total: a repeated registration changes nothing, a retirement of an unknown or an
already retired conclusion changes nothing. `conclusions` is empty for a log without these events,
so it is left out of the state hash then.
"""

from __future__ import annotations

import json

from sqlalchemy import Column, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.conclusions import ConclusionRegistered, ConclusionRetired


def conclusion_tables(metadata: MetaData) -> Table:
    return Table(
        "conclusions",
        metadata,
        Column("conclusion_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("registered_at", String, nullable=False),
        Column("statement", String, nullable=False),
        Column("basis", String, nullable=False),
        Column("predicate", String),
        Column("actor_id", String, nullable=False),
        Column("retired_event", String),
        Column("retired_at", String),
        Column("retire_reason", String),
    )


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def conclusion_handlers(conclusions: Table) -> dict[str, Handler]:
    def registered(conn: Connection, event: Event) -> None:
        payload = ConclusionRegistered.model_validate(event.payload)
        predicate = payload.predicate
        conn.execute(
            sqlite_insert(conclusions)
            .values(
                conclusion_id=payload.conclusion_id,
                event_id=event.id,
                registered_at=format_ts(event.ts),
                statement=payload.statement,
                basis=_dump([b.model_dump(mode="json") for b in payload.basis]),
                predicate=None
                if predicate is None
                else _dump(predicate.model_dump(mode="json", exclude_none=True)),
                actor_id=event.actor.id,
            )
            .on_conflict_do_nothing(index_elements=["conclusion_id"])
        )

    def retired(conn: Connection, event: Event) -> None:
        payload = ConclusionRetired.model_validate(event.payload)
        conn.execute(
            update(conclusions)
            .where(
                conclusions.c.conclusion_id == payload.conclusion_id,
                conclusions.c.retired_event.is_(None),
            )
            .values(
                retired_event=event.id,
                retired_at=format_ts(event.ts),
                retire_reason=payload.reason,
            )
        )

    return {"conclusion.registered": registered, "conclusion.retired": retired}
