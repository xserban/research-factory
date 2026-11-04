"""Projection of imported libraries (slice 3d, plan Import-A task 5).

`imports` keeps one row per `import.recorded`, with the split mode and seed folded from
`import.split_drawn`. `import_records` keeps one row per record with the searchable allow-listed
fields (abstract and tags stay in the records blob, read on demand, so the index stays small at
10^5 records) and its `part`: `development` or `held-out` for a drawn split, else `unsplit`.

The projector reads the records and parts blobs from `blobs/` (never the library). Handlers are
total and first-write-wins per key; a split for an unknown import changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Float, Index, Integer, MetaData, String, Table, and_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.blobs import BlobStore
from factory.events.envelope import Event
from factory.imports.model import ImportRecord
from factory.index.projection import Handler
from factory.model.imports import ImportRecorded, ImportResolved, ImportSplitDrawn

UNSPLIT = "unsplit"
_PARTS = {"development": "development", "held_out": "held-out"}
_CHUNK = 500


@dataclass(frozen=True)
class ImportTables:
    imports: Table
    records: Table


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
    )
    Index("ix_import_records_doi", records.c.doi)
    Index("ix_import_records_arxiv", records.c.arxiv)
    return ImportTables(imports, records)


def import_handlers(t: ImportTables, blobs: BlobStore | None) -> dict[str, Handler]:
    return {
        "import.recorded": _recorded(t, blobs),
        "import.split_drawn": _split_drawn(t, blobs),
        "import.resolved": _resolved(t),
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
            conn.execute(
                update(t.records)
                .where(and_(t.records.c.import_id == p.import_id, t.records.c.ordinal == r.ordinal))
                .values(
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
