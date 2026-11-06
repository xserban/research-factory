"""Projection of lab-library adoption: `fulltext_adoptions` and `library_source_confirmations`.

`fulltext_adoptions` keeps one row per adopted document: the source project, document and attempt,
the shared bytes and the conversions adopted with it. `library_source_confirmations` keeps the first
confirmation of each source project by the owner. `referenced_check` is what `ProjectLibrary` asks:
whether this project's own events reference a library hash.

The projection never reads the library (decision 39): the state hash depends on events alone.
Handlers are total: a malformed payload, a repeated event and an event that fails a guard change
nothing, on rebuild too. An adoption must name a document of this project that has the adopted
bytes, the `lab-library` route and the same work; a confirmation must be a person's, in their own
name, and the owner's at that point of the log.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.index import Index
from factory.index.ledger import governs
from factory.index.members import MemberTables
from factory.index.projection import Handler
from factory.model.fulltext import Route
from factory.model.lab_library import FulltextAdopted, SourceConfirmed

FULLTEXT_ADOPTED = "fulltext.adopted"
LIBRARY_SOURCE_CONFIRMED = "library.source_confirmed"

_REFERENCES = """
SELECT raw_hash FROM fulltext_documents
UNION SELECT raw_hash FROM fulltext_attempts WHERE raw_hash IS NOT NULL
UNION SELECT observed_hash FROM fulltext_source_changes
UNION SELECT raw_hash FROM document_conversions
UNION SELECT markdown_hash FROM document_conversions
UNION SELECT manifest_hash FROM document_conversions
UNION SELECT sha256 FROM fulltext_adoptions
UNION SELECT file_hash FROM imports
UNION SELECT 'sha256:' || attachment_content_sha256 FROM import_records
  WHERE attachment_content_sha256 IS NOT NULL
UNION SELECT library_hash FROM manuscripts
UNION SELECT bib_hash FROM manuscripts WHERE bib_hash IS NOT NULL
UNION SELECT bbl_archive FROM reference_extractions WHERE bbl_archive IS NOT NULL
"""
"""Every column of the projection that holds a library reference: a hash is the project's own to
read exactly when one of these names it."""


@dataclass(frozen=True)
class LibraryTables:
    adoptions: Table
    confirmations: Table


def library_tables(metadata: MetaData) -> LibraryTables:
    adoptions = Table(
        "fulltext_adoptions",
        metadata,
        Column("document_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("source_project", String, nullable=False),
        Column("source_doc", String, nullable=False),
        Column("source_attempt", String, nullable=False),
        Column("attempt_id", String, nullable=False),
        Column("sha256", String, nullable=False),
        Column("licence_status", String, nullable=False),
        Column("conversions", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    confirmations = Table(
        "library_source_confirmations",
        metadata,
        Column("source_project", String, primary_key=True),
        Column("reason", String, nullable=False),
        Column("confirmed_by", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return LibraryTables(adoptions, confirmations)


def library_handlers(
    t: LibraryTables, members: MemberTables, documents: Table
) -> dict[str, Handler]:
    return {
        FULLTEXT_ADOPTED: _adopted(t, documents),
        LIBRARY_SOURCE_CONFIRMED: _confirmed(t, members),
    }


def _adopted(t: LibraryTables, documents: Table) -> Handler:
    def adopted(conn: Connection, event: Event) -> None:
        try:
            payload = FulltextAdopted.model_validate(event.payload)
        except ValidationError:
            return
        doc = conn.execute(
            select(documents.c.work_id, documents.c.raw_hash, documents.c.route).where(
                documents.c.document_id == payload.document_id
            )
        ).first()
        if doc is None or doc.route != Route.LAB_LIBRARY.value:
            return
        if doc.work_id != payload.work_id or doc.raw_hash != payload.sha256:
            return
        conn.execute(
            sqlite_insert(t.adoptions)
            .values(
                document_id=payload.document_id,
                work_id=payload.work_id,
                source_project=payload.source_project,
                source_doc=payload.source_doc,
                source_attempt=payload.source_attempt,
                attempt_id=payload.attempt_id,
                sha256=payload.sha256,
                licence_status=payload.licence_status.value,
                conversions=canonical_json(list(payload.conversions)).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["document_id"])
        )

    return adopted


def _confirmed(t: LibraryTables, members: MemberTables) -> Handler:
    def confirmed(conn: Connection, event: Event) -> None:
        try:
            payload = SourceConfirmed.model_validate(event.payload)
        except ValidationError:
            return
        if not governs(conn, members, event.actor):
            return
        conn.execute(
            sqlite_insert(t.confirmations)
            .values(
                source_project=payload.source_project,
                reason=payload.reason,
                confirmed_by=event.actor.user,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["source_project"])
        )

    return confirmed


def referenced_hashes(index: Index) -> frozenset[str]:
    """Every library reference this project's events name, as the projection holds them."""
    with index.connect() as conn:
        return frozenset(str(row[0]) for row in conn.execute(text(_REFERENCES)))


def referenced_check(index: Index) -> Callable[[str], bool]:
    """A predicate over library references: whether this project's events reference the hash. The
    set is read from the projection once per index head and kept until the head moves."""
    cache: dict[str, frozenset[str]] = {}

    def referenced(ref: str) -> bool:
        head = index.head() or ""
        known = cache.get(head)
        if known is None:
            known = referenced_hashes(index)
            cache.clear()
            cache[head] = known
        return ref in known

    return referenced
