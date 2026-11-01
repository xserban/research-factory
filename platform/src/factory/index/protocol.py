"""Projection of the protocol: each recorded version, PRESS reviews and deviations.

`protocols` keeps every `protocol.recorded` row, with its search-strategy hash; the current
protocol is the row with the greatest `event_id`. `press_reviews` keeps each review; its
`responses` are set by the first `protocol.press_confirmed` for it. `deviations` keeps each
recorded deviation. `protocol.amended` adds a `protocols` row (with the amended spec, under its
version, which may equal the previous one for a prose-only change) and an `amendments` row
holding the whole payload. Handlers are total: a second row for the same key is ignored, and a
confirmation for an unknown or already confirmed review changes nothing.
"""

from dataclasses import dataclass

from sqlalchemy import Column, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.protocol import (
    DeviationRecorded,
    PressConfirmed,
    PressReviewed,
    ProtocolAmended,
    ProtocolRecorded,
    search_strategy_hash,
)


@dataclass(frozen=True)
class ProtocolTables:
    protocols: Table
    reviews: Table
    deviations: Table
    amendments: Table


def protocol_tables(metadata: MetaData) -> ProtocolTables:
    protocols = Table(
        "protocols",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("protocol_id", String, nullable=False),
        Column("status", String, nullable=False),
        Column("search_hash", String, nullable=False),
        Column("spec", String, nullable=False),
        Column("at", String, nullable=False),
    )
    reviews = Table(
        "press_reviews",
        metadata,
        Column("review_id", String, primary_key=True),
        Column("protocol_id", String, nullable=False),
        Column("findings", String, nullable=False),
        Column("responses", String),
        Column("event_id", String, nullable=False),
    )
    deviations = Table(
        "deviations",
        metadata,
        Column("deviation_id", String, primary_key=True),
        Column("protocol_id", String, nullable=False),
        Column("description", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("affects", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    amendments = Table(
        "amendments",
        metadata,
        Column("amendment_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("payload", String, nullable=False),
    )
    return ProtocolTables(protocols, reviews, deviations, amendments)


def protocol_handlers(t: ProtocolTables) -> dict[str, Handler]:
    return {
        "protocol.recorded": _recorded(t),
        "protocol.press_reviewed": _reviewed(t),
        "protocol.press_confirmed": _confirmed(t),
        "protocol.deviation_recorded": _deviation(t),
        "protocol.amended": _amended(t),
    }


def _recorded(t: ProtocolTables) -> Handler:
    def recorded(conn: Connection, event: Event) -> None:
        payload = ProtocolRecorded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.protocols)
            .values(
                event_id=event.id,
                protocol_id=payload.protocol_id,
                status=payload.status.value,
                search_hash=search_strategy_hash(payload.spec),
                spec=canonical_json(payload.spec.model_dump(mode="json")).decode(),
                at=format_ts(event.ts),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return recorded


def _reviewed(t: ProtocolTables) -> Handler:
    def reviewed(conn: Connection, event: Event) -> None:
        payload = PressReviewed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.reviews)
            .values(
                review_id=payload.review_id,
                protocol_id=payload.protocol_id,
                findings=canonical_json(
                    [finding.model_dump(mode="json") for finding in payload.findings]
                ).decode(),
                responses=None,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["review_id"])
        )

    return reviewed


def _confirmed(t: ProtocolTables) -> Handler:
    def confirmed(conn: Connection, event: Event) -> None:
        payload = PressConfirmed.model_validate(event.payload)
        conn.execute(
            update(t.reviews)
            .where(t.reviews.c.review_id == payload.review_id)
            .where(t.reviews.c.responses.is_(None))
            .values(responses=canonical_json(list(payload.responses)).decode())
        )

    return confirmed


def _deviation(t: ProtocolTables) -> Handler:
    def deviation(conn: Connection, event: Event) -> None:
        payload = DeviationRecorded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.deviations)
            .values(
                deviation_id=payload.deviation_id,
                protocol_id=payload.protocol_id,
                description=payload.description,
                reason=payload.reason,
                affects=canonical_json(list(payload.affects)).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["deviation_id"])
        )

    return deviation


def _amended(t: ProtocolTables) -> Handler:
    def amended(conn: Connection, event: Event) -> None:
        payload = ProtocolAmended.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.protocols)
            .values(
                event_id=event.id,
                protocol_id=payload.to_version,
                status="ready",
                search_hash=search_strategy_hash(payload.spec),
                spec=canonical_json(payload.spec.model_dump(mode="json")).decode(),
                at=format_ts(event.ts),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        conn.execute(
            sqlite_insert(t.amendments)
            .values(
                amendment_id=payload.amendment_id,
                event_id=event.id,
                payload=canonical_json(payload.model_dump(mode="json")).decode(),
            )
            .on_conflict_do_nothing(index_elements=["amendment_id"])
        )

    return amended
