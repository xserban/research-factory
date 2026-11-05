"""Projection of `mine.imported` (slice M ruling 19): imports, their items and the imported rows.

`mine_imports` and `mine_import_items` say where each imported row came from. The rows themselves
go into `extraction_rows` and `extraction_fields` under the miner's scope, with the import's id as
`task_id` (`MINE_IMPORT_PREFIX`), so the extraction tables gain no column and a log without imports
keeps its state hash. Readers of mined rows leave them out by that prefix.

A later import of a work replaces the earlier import's live rows of that work: they get the new
import's id as `superseded_by`.

The handler is total and atomic. It writes nothing unless every guard holds, for a hand-written
event as for a replayed one, and it reads only this project's tables, never the library, a blob or
another project (decision 39: the state hash depends on events alone):
- the payload parses and its writer is a human or the system (the services write no other);
- the source is another project, and the import id is new;
- the miner version is registered here with that digest and is not retired;
- every item names a conversion of this project, of its document and work, a new extraction id, and
  a `(work, row key)` no other item of the event names.
Whether a field re-verifies needs the library: `check` reports that (`mine-import-unverified`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.events.envelope import Event
from factory.index.extraction import ExtractionTables
from factory.index.fulltext import FulltextTables
from factory.index.miners import MinerTables
from factory.index.projection import Handler
from factory.model.extraction import MinerScope, pack_tag
from factory.model.mine_imports import MINE_IMPORT_PREFIX, ImportedItem, MineImported


@dataclass(frozen=True)
class MineImportTables:
    imports: Table
    items: Table


def mine_import_tables(metadata: MetaData) -> MineImportTables:
    imports = Table(
        "mine_imports",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("source_project", String, nullable=False),
        Column("miner", String, nullable=False),
        Column("version", Integer, nullable=False),
        Column("digest", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    items = Table(
        "mine_import_items",
        metadata,
        Column("import_id", String, primary_key=True),
        Column("extraction_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("source_conversion_id", String, nullable=False),
        Column("source_row_key", String, nullable=False),
        Column("source_status", String, nullable=False),
        Column("dual", Boolean, nullable=False),
        Column("source_extraction_ids", String, nullable=False),
        Column("source_passes", String, nullable=False),
        Index("ix_mine_import_items_extraction", "extraction_id"),
    )
    return MineImportTables(imports, items)


def mine_import_handlers(
    t: MineImportTables,
    extraction: ExtractionTables,
    conversions: Table,
    fulltext: FulltextTables,
    miners: MinerTables,
) -> dict[str, Handler]:
    def miner_stands(conn: Connection, payload: MineImported) -> bool:
        table = miners.miners
        row = conn.execute(
            select(table.c.digest, table.c.retired).where(
                table.c.name == payload.miner, table.c.version == payload.version
            )
        ).first()
        return row is not None and row[0] == payload.digest and not row[1]

    def item_stands(conn: Connection, item: ImportedItem) -> bool:
        documents = fulltext.documents
        row = conn.execute(
            select(conversions.c.document_id, documents.c.work_id)
            .join(documents, documents.c.document_id == conversions.c.document_id)
            .where(conversions.c.conversion_id == item.conversion_id)
        ).first()
        if row is None or (row[0], row[1]) != (item.document_id, item.work_id):
            return False
        taken = conn.execute(
            select(extraction.rows.c.extraction_id).where(
                extraction.rows.c.extraction_id == item.extraction_id
            )
        ).first()
        return taken is None

    def stands(conn: Connection, event: Event, payload: MineImported) -> bool:
        items = payload.items
        known = conn.execute(
            select(t.imports.c.import_id).where(t.imports.c.import_id == payload.import_id)
        ).first()
        return (
            payload.source_project != event.project
            and known is None
            and miner_stands(conn, payload)
            and len({i.extraction_id for i in items}) == len(items)
            and len({(i.work_id, i.row_key) for i in items}) == len(items)
            and all(item_stands(conn, item) for item in items)
        )

    def replace_earlier(conn: Connection, payload: MineImported) -> None:
        rows = extraction.rows
        conn.execute(
            update(rows)
            .where(rows.c.scope == payload.miner)
            .where(rows.c.work_id.in_({i.work_id for i in payload.items}))
            .where(func.substr(rows.c.task_id, 1, len(MINE_IMPORT_PREFIX)) == MINE_IMPORT_PREFIX)
            .where(rows.c.superseded_by.is_(None))
            .values(superseded_by=payload.import_id)
        )

    def write_item(conn: Connection, payload: MineImported, item: ImportedItem, at: str) -> None:
        cited = item.cited
        conn.execute(
            sqlite_insert(extraction.rows).values(
                extraction_id=item.extraction_id,
                scope=payload.miner,
                pack=pack_tag(MinerScope(payload.miner)),
                cited_extraction_id=cited.reference_extraction_id if cited else None,
                cited_ordinal=cited.ordinal if cited else None,
                cited_marker=cited.marker if cited else None,
                work_id=item.work_id,
                pass_label="A",
                task_id=payload.import_id,
                protocol_id=payload.protocol_id,
                schema_ref=f"{payload.miner}@{payload.version}",
                document_id=item.document_id,
                conversion_id=item.conversion_id,
                row_key=item.row_key,
                supersedes=None,
                superseded_by=None,
                event_id=at,
            )
        )
        for name, field in item.fields.items():
            conn.execute(
                sqlite_insert(extraction.fields).values(
                    extraction_id=item.extraction_id,
                    field=name,
                    value=str(field.value),
                    unit=field.unit,
                    canonical=field.canonical,
                    anchor=field.anchor,
                    cell=field.cell,
                    quote=field.quote,
                    reported_in=field.reported_in.value,
                    copy_marker=field.copy_marker,
                    reproduced=field.reproduced,
                    cited_work=field.cited_work,
                )
            )
        conn.execute(
            sqlite_insert(t.items).values(
                import_id=payload.import_id,
                extraction_id=item.extraction_id,
                work_id=item.work_id,
                conversion_id=item.conversion_id,
                source_conversion_id=item.source_conversion_id,
                source_row_key=item.source_row_key,
                source_status=item.source_status,
                dual=item.dual,
                source_extraction_ids=json.dumps(list(item.source_extraction_ids)),
                source_passes=json.dumps(
                    [p.model_dump(mode="json") for p in item.source_passes], sort_keys=True
                ),
            )
        )

    def fold(conn: Connection, event: Event, payload: MineImported) -> None:
        replace_earlier(conn, payload)
        conn.execute(
            sqlite_insert(t.imports).values(
                import_id=payload.import_id,
                source_project=payload.source_project,
                miner=payload.miner,
                version=payload.version,
                digest=payload.digest,
                protocol_id=payload.protocol_id,
                event_id=event.id,
            )
        )
        for item in payload.items:
            write_item(conn, payload, item, event.id)

    def imported(conn: Connection, event: Event) -> None:
        if event.actor.kind not in ("human", "system"):
            return
        try:
            payload = MineImported.model_validate(event.payload)
            with conn.begin_nested():  # all of the event or nothing
                if stands(conn, event, payload):
                    fold(conn, event, payload)
        except (ValueError, ArithmeticError, SQLAlchemyError):
            return  # a `ValidationError` is a `ValueError`

    return {"mine.imported": imported}
