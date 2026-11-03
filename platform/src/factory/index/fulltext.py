"""Projection of full-text acquisition: fetches, attempts, documents and source changes.

`fulltext_fetches` keeps each fetch and the kind of actor that started it. `fulltext_attempts`
keeps every route tried, one row per attempt, whatever its outcome. `fulltext_documents` keeps
each document; a document that a later document supersedes carries that later id in
`superseded_by` (first write wins). `fulltext_source_changes` keeps each re-fetch that hashed
differently from its document.

Hash fields are library references, stored as text. The projection never reads the library
(decision 39): the state hash depends on events alone. Handlers are total: a repeated event
for a key that already has a row changes nothing.
"""

from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.fulltext import Attempted, DocumentAdded, FetchStarted, SourceChanged


@dataclass(frozen=True)
class FulltextTables:
    fetches: Table
    attempts: Table
    documents: Table
    source_changes: Table


def fulltext_tables(metadata: MetaData) -> FulltextTables:
    fetches = Table(
        "fulltext_fetches",
        metadata,
        Column("fetch_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
        Column("actor_kind", String, nullable=False),
    )
    attempts = Table(
        "fulltext_attempts",
        metadata,
        Column("attempt_id", String, primary_key=True),
        Column("fetch_id", String),
        Column("work_id", String, nullable=False),
        Column("route", String, nullable=False),
        Column("url", String),
        Column("http_status", Integer),
        Column("outcome", String, nullable=False),
        Column("reason", String),
        Column("retrieved_at", String, nullable=False),
        Column("source_version", String),
        Column("licence", String),
        Column("licence_status", String, nullable=False),
        Column("media_type", String),
        Column("raw_hash", String),
        Column("metadata_blob", String),
        Column("document_id", String),
        Column("event_id", String, nullable=False),
    )
    documents = Table(
        "fulltext_documents",
        metadata,
        Column("document_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("route", String, nullable=False),
        Column("quality", String, nullable=False),
        Column("source_version", String, nullable=False),
        Column("raw_hash", String, nullable=False),
        Column("media_type", String, nullable=False),
        Column("attempt_id", String, nullable=False),
        Column("provenance", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("event_id", String, nullable=False),
    )
    source_changes = Table(
        "fulltext_source_changes",
        metadata,
        Column("attempt_id", String, primary_key=True),
        Column("document_id", String, nullable=False),
        Column("expected_hash", String, nullable=False),
        Column("observed_hash", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return FulltextTables(fetches, attempts, documents, source_changes)


def fulltext_handlers(t: FulltextTables) -> dict[str, Handler]:
    return {
        "fulltext.fetch_started": _fetch_started(t),
        "fulltext.attempted": _attempted(t),
        "fulltext.document_added": _document_added(t),
        "fulltext.source_changed": _source_changed(t),
    }


def _fetch_started(t: FulltextTables) -> Handler:
    def fetch_started(conn: Connection, event: Event) -> None:
        payload = FetchStarted.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.fetches)
            .values(fetch_id=payload.fetch_id, event_id=event.id, actor_kind=event.actor.kind)
            .on_conflict_do_nothing(index_elements=["fetch_id"])
        )

    return fetch_started


def _attempted(t: FulltextTables) -> Handler:
    def attempted(conn: Connection, event: Event) -> None:
        values = Attempted.model_validate(event.payload).model_dump(mode="json")
        conn.execute(
            sqlite_insert(t.attempts)
            .values(**values, event_id=event.id)
            .on_conflict_do_nothing(index_elements=["attempt_id"])
        )

    return attempted


def _document_added(t: FulltextTables) -> Handler:
    def document_added(conn: Connection, event: Event) -> None:
        payload = DocumentAdded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.documents)
            .values(
                **payload.model_dump(mode="json"),
                superseded_by=None,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["document_id"])
        )
        if payload.supersedes is not None:
            conn.execute(
                update(t.documents)
                .where(t.documents.c.document_id == payload.supersedes)
                .where(t.documents.c.superseded_by.is_(None))
                .values(superseded_by=payload.document_id)
            )

    return document_added


def _source_changed(t: FulltextTables) -> Handler:
    def source_changed(conn: Connection, event: Event) -> None:
        values = SourceChanged.model_validate(event.payload).model_dump(mode="json")
        conn.execute(
            sqlite_insert(t.source_changes)
            .values(**values, event_id=event.id)
            .on_conflict_do_nothing(index_elements=["attempt_id"])
        )

    return source_changed
