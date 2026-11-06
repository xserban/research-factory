"""Projection of imported libraries (slice 3d, plan Import-A task 5).

`imports` keeps one row per `import.recorded`, with the split mode and seed folded from
`import.split_drawn`. `import_records` keeps one row per record with the searchable allow-listed
fields (abstract and tags stay in the records blob, read on demand, so the index stays small at
10^5 records) and its `part`: `development` or `held-out` for a drawn split, else `unsplit`.
`import_descriptions` keeps the researcher's overlay on a record, apart from it: the row of
`import_records` keeps what the export said, and `pending` says the record has not been resolved
since it was described.

The projector reads the records and parts blobs from `blobs/` (never the library). Handlers are
total and first-write-wins per key; a split for an unknown import changes nothing. A description
folds only from a human, for a record that exists, is not malformed and no admission plan names.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.imports.model import ImportRecord, ParseOutcome
from factory.index.projection import Handler
from factory.model.imports import (
    DESCRIBED_FIELDS,
    ImportAdmissionPlanned,
    ImportAttachmentLinked,
    ImportRecordDescribed,
    ImportRecorded,
    ImportResolutionDecided,
    ImportResolved,
    ImportSplitDrawn,
)
from factory.model.references import BINDING_DECISIONS, Confidence, Decision, LinkState

UNSPLIT = "unsplit"
BINDING = "binding"
PROPOSAL = "proposal"
_PARTS = {"development": "development", "held_out": "held-out"}
_CHUNK = 500


@dataclass(frozen=True)
class ImportTables:
    imports: Table
    records: Table
    decisions: Table
    admission_queries: Table
    attachments: Table
    descriptions: Table


def import_tables(metadata: MetaData) -> ImportTables:
    imports = Table(
        "imports",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("format", String, nullable=False),
        Column("role", String, nullable=False),
        Column("collection", String),
        Column("parser", String, nullable=False),
        Column("parser_version", String, nullable=False),
        Column("file_hash", String, nullable=False),
        Column("records_blob", String, nullable=False),
        Column("split_mode", String),
        Column("split_seed", Integer),
        Column("recorded_at", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    records = Table(
        "import_records",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("outcome", String, nullable=False),
        Column("title", String),
        Column("first_author", String),
        Column("year", Integer),
        Column("doi", String),
        Column("arxiv", String),
        Column("url", String),
        Column("venue", String),
        Column("type", String),
        Column("record_sha256", String, nullable=False),
        Column("attachment_path_sha256", String),
        Column("attachment_content_sha256", String),
        Column("part", String, nullable=False),
        # The resolution as recorded (`base_*`) and the live state folded from it (`link_state`,
        # `work_id`, `confidence`). NULL until the import is resolved.
        Column("link_state", String),
        Column("work_id", String),
        Column("method", String),
        Column("confidence", String),
        Column("score", Float),
        Column("base_state", String),
        Column("base_work_id", String),
        Column("base_confidence", String),
        Column("candidates", String),
        Column("reason", String),
        Column("no_source_record", Integer),
        Column("decision", String),
        Column("confirmed_by", String),
        Column("proposal", String),
    )
    decisions = Table(
        "import_decisions",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("kind", String, primary_key=True),
        Column("decision", String, nullable=False),
        Column("work_id", String),
        Column("confirmed_by", String),
        Column("event_id", String, nullable=False),
    )
    Index("ix_import_records_doi", records.c.doi)
    Index("ix_import_records_arxiv", records.c.arxiv)
    admission_queries = Table(
        "import_admission_queries",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("import_id", String, nullable=False),
        Column("source", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("text", String, nullable=False),
        Column("record_keys", String, nullable=False),
        Index("ix_import_admission_queries_import", "import_id"),
    )
    attachments = Table(
        "import_attachments",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("document_id", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    descriptions = Table(
        "import_descriptions",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("ordinal", Integer, primary_key=True),
        Column("title", String),
        Column("first_author", String),
        Column("year", Integer),
        Column("doi", String),
        Column("arxiv", String),
        Column("venue", String),
        Column("type", String),
        Column("fields", String, nullable=False),
        Column("pending", Integer, nullable=False),
        Column("event_id", String, nullable=False),
    )
    return ImportTables(imports, records, decisions, admission_queries, attachments, descriptions)


def import_handlers(t: ImportTables, blobs: BlobStore | None) -> dict[str, Handler]:
    return {
        "import.recorded": _recorded(t, blobs),
        "import.split_drawn": _split_drawn(t, blobs),
        "import.resolved": _resolved(t),
        "import.resolution_decided": _decided(t),
        "import.admission_planned": _admission_planned(t),
        "import.attachment_linked": _attachment_linked(t),
        "import.record_described": _described(t),
    }


def _store(blobs: BlobStore | None) -> BlobStore:
    if blobs is None:
        raise RuntimeError("the imports projection needs the project's blob store")
    return blobs


def _recorded(t: ImportTables, blobs: BlobStore | None) -> Handler:
    def recorded(conn: Connection, event: Event) -> None:
        p = ImportRecorded.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.imports)
            .values(
                import_id=p.import_id,
                format=p.format.value,
                role=p.role.value,
                collection=p.collection,
                parser=p.parser,
                parser_version=p.parser_version,
                file_hash=p.file_hash,
                records_blob=p.records_blob,
                recorded_at=format_ts(event.ts),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["import_id"])
        )
        if not inserted.rowcount:
            return
        raw = _store(blobs).get_json(p.records_blob)
        assert isinstance(raw, list)
        rows = [_row(p.import_id, ImportRecord.model_validate(item)) for item in raw]
        if rows:
            conn.execute(sqlite_insert(t.records).on_conflict_do_nothing(), rows)

    return recorded


def _row(import_id: str, r: ImportRecord) -> dict[str, object]:
    f = r.fields
    return {
        "import_id": import_id,
        "ordinal": r.ordinal,
        "outcome": r.outcome.value,
        "title": f.title if f else None,
        "first_author": f.authors[0] if f and f.authors else None,
        "year": f.year if f else None,
        "doi": f.doi if f else None,
        "arxiv": f.arxiv if f else None,
        "url": f.url if f else None,
        "venue": f.venue if f else None,
        "type": f.type if f else None,
        "record_sha256": r.record_sha256,
        "attachment_path_sha256": r.attachment.path_sha256 if r.attachment else None,
        "attachment_content_sha256": r.attachment.content_sha256 if r.attachment else None,
        "part": UNSPLIT,
    }


def _resolved(t: ImportTables) -> Handler:
    """A resolution replaces the earlier one of the import, record by record (last write wins)."""

    def resolved(conn: Connection, event: Event) -> None:
        p = ImportResolved.model_validate(event.payload)
        for r in p.resolutions:
            confidence = None if r.confidence is None else r.confidence.value
            # A new resolution starts the record's link again: earlier decisions on it leave the
            # live view, and a description now has its resolution.
            conn.execute(
                delete(t.decisions).where(
                    and_(t.decisions.c.import_id == p.import_id, t.decisions.c.ordinal == r.ordinal)
                )
            )
            conn.execute(
                update(t.descriptions)
                .where(
                    and_(
                        t.descriptions.c.import_id == p.import_id,
                        t.descriptions.c.ordinal == r.ordinal,
                    )
                )
                .values(pending=0)
            )
            conn.execute(
                update(t.records)
                .where(and_(t.records.c.import_id == p.import_id, t.records.c.ordinal == r.ordinal))
                .values(
                    decision=None,
                    confirmed_by=None,
                    proposal=None,
                    link_state=r.state.value,
                    work_id=r.work_id,
                    method=r.method,
                    confidence=confidence,
                    score=r.score,
                    base_state=r.state.value,
                    base_work_id=r.work_id,
                    base_confidence=confidence,
                    candidates=canonical_json(
                        [c.model_dump(mode="json") for c in r.candidates]
                    ).decode(),
                    reason=r.reason,
                    no_source_record=1 if r.no_source_record else 0,
                )
            )

    return resolved


def _admission_planned(t: ImportTables) -> Handler:
    """Each planned query of an admission, in order; the event id makes each admission distinct."""

    def planned(conn: Connection, event: Event) -> None:
        p = ImportAdmissionPlanned.model_validate(event.payload)
        for position, q in enumerate(p.queries):
            conn.execute(
                sqlite_insert(t.admission_queries)
                .values(
                    event_id=event.id,
                    position=position,
                    import_id=p.import_id,
                    source=q.source,
                    kind=q.kind.value,
                    text=q.text,
                    record_keys=canonical_json(list(q.record_keys)).decode(),
                )
                .on_conflict_do_nothing(index_elements=["event_id", "position"])
            )

    return planned


def _described(t: ImportTables) -> Handler:
    """The researcher's overlay on a record, latest event winning; see the module docstring."""

    def described(conn: Connection, event: Event) -> None:
        p = ImportRecordDescribed.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        outcome = conn.execute(
            select(t.records.c.outcome).where(
                and_(t.records.c.import_id == p.import_id, t.records.c.ordinal == p.ordinal)
            )
        ).scalar()
        if outcome is None or outcome == ParseOutcome.MALFORMED.value:
            return
        key = canonical_json(f"{p.import_id}:{p.ordinal}").decode()
        planned = conn.execute(
            select(t.admission_queries.c.event_id)
            .where(
                and_(
                    t.admission_queries.c.import_id == p.import_id,
                    func.instr(t.admission_queries.c.record_keys, key) > 0,
                )
            )
            .limit(1)
        ).first()
        if planned is not None:
            return
        fields = p.model_dump(mode="json", include=set(DESCRIBED_FIELDS), exclude_none=True)
        if not p.authors:
            fields.pop("authors")
        values = {
            "title": p.title,
            "first_author": p.authors[0] if p.authors else None,
            "year": p.year,
            "doi": p.doi,
            "arxiv": p.arxiv,
            "venue": p.venue,
            "type": p.type,
            "fields": canonical_json(fields).decode(),
            "pending": 1,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.descriptions)
            .values(import_id=p.import_id, ordinal=p.ordinal, **values)
            .on_conflict_do_update(index_elements=["import_id", "ordinal"], set_=values)
        )

    return described


def _attachment_linked(t: ImportTables) -> Handler:
    """One link per record, first write wins."""

    def linked(conn: Connection, event: Event) -> None:
        p = ImportAttachmentLinked.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.attachments)
            .values(
                import_id=p.import_id,
                ordinal=p.ordinal,
                work_id=p.work_id,
                document_id=p.document_id,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["import_id", "ordinal"])
        )

    return linked


def _decided(t: ImportTables) -> Handler:
    """A decision replaces the earlier one of its kind (binding or proposal) for the record."""

    def decided(conn: Connection, event: Event) -> None:
        p = ImportResolutionDecided.model_validate(event.payload)
        kind = BINDING if p.decision in BINDING_DECISIONS else PROPOSAL
        values = {
            "decision": p.decision.value,
            "work_id": p.work_id,
            "confirmed_by": p.confirmed_by,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.decisions)
            .values(import_id=p.import_id, ordinal=p.ordinal, kind=kind, **values)
            .on_conflict_do_update(index_elements=["import_id", "ordinal", "kind"], set_=values)
        )
        _fold(conn, t, p.import_id, p.ordinal)

    return decided


def _fold(conn: Connection, t: ImportTables, import_id: str, ordinal: int) -> None:
    """Recompute a record's live link from its recorded resolution and its latest decisions."""
    where = and_(t.records.c.import_id == import_id, t.records.c.ordinal == ordinal)
    base = conn.execute(
        select(t.records.c.base_state, t.records.c.base_work_id, t.records.c.base_confidence).where(
            where
        )
    ).first()
    if base is None or base[0] is None:
        return
    d = t.decisions.c
    rows = conn.execute(
        select(d.kind, d.decision, d.work_id, d.confirmed_by).where(
            and_(d.import_id == import_id, d.ordinal == ordinal)
        )
    ).all()
    by_kind = {str(row[0]): row for row in rows}
    state, work_id, confidence = base[0], base[1], base[2]
    decision = confirmed_by = None
    binding = by_kind.get(BINDING)
    if binding is not None:
        decision, confirmed_by = binding[1], binding[3]
        if decision == Decision.CONFIRM.value:
            state, work_id = LinkState.RESOLVED.value, binding[2]
            confidence = Confidence.CONFIRMED.value
        else:
            state, work_id, confidence = LinkState.UNRESOLVED.value, None, None
    proposal = by_kind.get(PROPOSAL)
    conn.execute(
        update(t.records)
        .where(where)
        .values(
            link_state=state,
            work_id=work_id,
            confidence=confidence,
            decision=decision,
            confirmed_by=confirmed_by,
            proposal=None if proposal is None else proposal[1],
        )
    )


def _split_drawn(t: ImportTables, blobs: BlobStore | None) -> Handler:
    def split_drawn(conn: Connection, event: Event) -> None:
        p = ImportSplitDrawn.model_validate(event.payload)
        updated = conn.execute(
            update(t.imports)
            .where(and_(t.imports.c.import_id == p.import_id, t.imports.c.split_mode.is_(None)))
            .values(split_mode=p.mode, split_seed=p.random_seed)
        )
        if not updated.rowcount or p.parts_blob is None:
            return
        parts = _store(blobs).get_json(p.parts_blob)
        assert isinstance(parts, dict)
        for key, part in _PARTS.items():
            raw = parts[key]
            assert isinstance(raw, list)
            ordinals = [int(str(o)) for o in raw]
            # Chunked so a large import stays under SQLite's bound-parameter limit.
            for start in range(0, len(ordinals), _CHUNK):
                conn.execute(
                    update(t.records)
                    .where(
                        and_(
                            t.records.c.import_id == p.import_id,
                            t.records.c.ordinal.in_(ordinals[start : start + _CHUNK]),
                        )
                    )
                    .values(part=part)
                )

    return split_drawn
