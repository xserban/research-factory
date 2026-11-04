"""Projection of document conversion events: converted documents and failed conversions.

`document_conversions` keeps each conversion; a repeat of the same document, converter and
converter version changes nothing (the unique key keeps the first row). `document_failures` keeps
each failed conversion by the event that recorded it.

Hash fields are library references, stored as text. `counts` and `warnings` are stored as JSON
text. The projection never reads the library, so the state hash depends on events alone.
Handlers are total: a repeated event changes nothing.
"""

import json

from sqlalchemy import Column, MetaData, String, Table, UniqueConstraint
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.document import ConversionFailed, Converted


def document_tables(metadata: MetaData) -> tuple[Table, Table]:
    conversions = Table(
        "document_conversions",
        metadata,
        Column("conversion_id", String, primary_key=True),
        Column("document_id", String, nullable=False),
        Column("converter", String, nullable=False),
        Column("converter_version", String, nullable=False),
        Column("raw_hash", String, nullable=False),
        Column("markdown_hash", String, nullable=False),
        Column("manifest_hash", String, nullable=False),
        Column("counts", String, nullable=False),
        Column("warnings", String, nullable=False),
        Column("event_id", String, nullable=False),
        UniqueConstraint("document_id", "converter", "converter_version"),
    )
    failures = Table(
        "document_failures",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("document_id", String, nullable=False),
        Column("converter", String),
        Column("reason", String, nullable=False),
        Column("error_class", String),
    )
    return conversions, failures


def document_handlers(conversions: Table, failures: Table) -> dict[str, Handler]:
    return {
        "document.converted": _converted(conversions),
        "document.conversion_failed": _conversion_failed(failures),
    }


def _converted(conversions: Table) -> Handler:
    def converted(conn: Connection, event: Event) -> None:
        payload = Converted.model_validate(event.payload)
        conn.execute(
            sqlite_insert(conversions)
            .values(
                conversion_id=payload.conversion_id,
                document_id=payload.document_id,
                converter=payload.converter,
                converter_version=payload.converter_version,
                raw_hash=payload.raw_hash,
                markdown_hash=payload.markdown_hash,
                manifest_hash=payload.manifest_hash,
                counts=json.dumps(payload.counts, sort_keys=True),
                warnings=json.dumps(payload.warnings),
                event_id=event.id,
            )
            .on_conflict_do_nothing()
        )

    return converted


def _conversion_failed(failures: Table) -> Handler:
    def conversion_failed(conn: Connection, event: Event) -> None:
        values = ConversionFailed.model_validate(event.payload).model_dump(mode="json")
        conn.execute(
            sqlite_insert(failures)
            .values(**values, event_id=event.id)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return conversion_failed
