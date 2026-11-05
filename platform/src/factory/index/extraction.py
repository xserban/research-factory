"""Projection of extraction: passes, sessions, rows, fields, claims, closures, resolutions, audits.

`extraction_rows` keeps every recorded row (one work, one pass); a row that a later one supersedes
gets `superseded_by` set, so a live row has `superseded_by` NULL. `extraction_fields` holds one row
per field of each row with its provenance. `extraction_claims` is likewise kept with supersession.
`extraction_resolutions` keeps the latest human choice per (work, row_key, field); a whole-row
choice stores field `*`. `extraction_audit_items.correct` is NULL until labelled; the latest label
wins; its `extraction_id` is the extraction the value came from when sampled (NULL in older
samples). `row_key` and `field` are indexed because plan E's cell trace queries them directly.

Handlers are total: an event naming an unknown row, claim or audit is stored (or changes nothing),
never refused. A repeated pass, join, close, row, claim or sample changes nothing (first write
wins); a repeated resolution or audit label replaces the earlier one (last write wins).
"""

from dataclasses import dataclass

from sqlalchemy import Boolean, Column, Index, Integer, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.extraction import (
    CONTRIBUTION_SCOPE_NAME,
    WHOLE_ROW_MARKER,
    ClaimRecorded,
    ExtractionAuditLabelled,
    ExtractionAuditSampled,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionResolved,
    Scope,
    audit_scope_of_pack,
    scope_of_pack,
    scope_of_schema_ref,
)

WHOLE_ROW = WHOLE_ROW_MARKER
"""The `field` stored for a resolution of a whole row."""


@dataclass(frozen=True)
class ExtractionTables:
    passes: Table
    sessions: Table
    rows: Table
    fields: Table
    claims: Table
    closures: Table
    resolutions: Table
    audits: Table
    audit_items: Table


def extraction_tables(metadata: MetaData) -> ExtractionTables:
    passes = Table(
        "extraction_passes",
        metadata,
        Column("scope", String, primary_key=True),
        Column("pass_label", String, primary_key=True),
        Column("random_seed", Integer, nullable=False),
        Column("field_order", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    sessions = Table(
        "extraction_sessions",
        metadata,
        Column("session", String, primary_key=True),
        Column("scope", String, nullable=False, server_default="evidence"),
        Column("pass_label", String, nullable=False),
        Column("model", String, nullable=False),
    )
    rows = Table(
        "extraction_rows",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("scope", String, nullable=False, server_default="evidence"),
        Column("pack", String),
        Column("cited_extraction_id", String),
        Column("cited_ordinal", Integer),
        Column("cited_marker", String),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("task_id", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("schema_ref", String, nullable=False),
        Column("document_id", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("row_key", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("event_id", String, nullable=False),
        Index("ix_extraction_rows_row_key", "row_key"),
        Index("ix_extraction_rows_pack", "pack"),
        Index("ix_extraction_rows_work_pass", "work_id", "pass_label"),
    )
    fields = Table(
        "extraction_fields",
        metadata,
        Column("extraction_id", String, primary_key=True),
        Column("field", String, primary_key=True),
        Column("value", String, nullable=False),
        Column("unit", String),
        Column("canonical", String),
        Column("anchor", String),
        Column("cell", String),
        Column("quote", String),
        Column("reported_in", String, nullable=False),
        Column("copy_marker", Boolean, nullable=False),
        Column("reproduced", Boolean, nullable=False),
        Column("cited_work", String),
        Index("ix_extraction_fields_field", "field"),
    )
    claims = Table(
        "extraction_claims",
        metadata,
        Column("claim_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("task_id", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("document_id", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("statement", String, nullable=False),
        Column("claim_type", String, nullable=False),
        Column("evidence_type", String, nullable=False),
        Column("strength", String, nullable=False),
        Column("anchor", String, nullable=False),
        Column("quote", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("event_id", String, nullable=False),
    )
    closures = Table(
        "extraction_closures",
        metadata,
        Column("task_id", String, primary_key=True),
        Column("scope", String, nullable=False, server_default="evidence"),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("rows", Integer, nullable=False),
        Column("claims", Integer, nullable=False),
        Column("reason", String),
        Column("event_id", String, nullable=False),
    )
    resolutions = Table(
        "extraction_resolutions",
        metadata,
        Column("scope", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("row_key", String, primary_key=True),
        Column("field", String, primary_key=True),
        Column("choice", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    audits = Table(
        "extraction_audits",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("scope", String, nullable=False, server_default="evidence"),
        Column("random_seed", Integer, nullable=False),
        Column("population", Integer, nullable=False),
        Column("population_digest", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    audit_items = Table(
        "extraction_audit_items",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("row_key", String, primary_key=True),
        Column("field", String, primary_key=True),
        Column("scope", String, nullable=False, server_default="evidence"),
        Column("correct", Boolean),
        Column("note", String, nullable=False, server_default=""),
        Column("extraction_id", String),
    )
    return ExtractionTables(
        passes=passes,
        sessions=sessions,
        rows=rows,
        fields=fields,
        claims=claims,
        closures=closures,
        resolutions=resolutions,
        audits=audits,
        audit_items=audit_items,
    )


def extraction_handlers(t: ExtractionTables) -> dict[str, Handler]:
    return {
        "extraction.pass_opened": _pass_opened(t),
        "extraction.pass_joined": _pass_joined(t),
        "extraction.recorded": _recorded(t),
        "extraction.claim_recorded": _claim(t),
        "extraction.closed": _closed(t),
        "extraction.resolved": _resolved(t),
        "extraction.audit_sampled": _audit_sampled(t),
        "extraction.audit_labelled": _audit_labelled(t),
    }


def _pass_opened(t: ExtractionTables) -> Handler:
    def pass_opened(conn: Connection, event: Event) -> None:
        payload = ExtractionPassOpened.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.passes)
            .values(
                scope=scope_of_pack(payload.pack).value,
                pass_label=payload.pass_label.value,
                random_seed=payload.random_seed,
                field_order=payload.field_order,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["scope", "pass_label"])
        )

    return pass_opened


def _pass_joined(t: ExtractionTables) -> Handler:
    def pass_joined(conn: Connection, event: Event) -> None:
        payload = ExtractionPassJoined.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.sessions)
            .values(
                session=payload.session,
                scope=scope_of_pack(payload.pack).value,
                pass_label=payload.pass_label.value,
                model=payload.model,
            )
            .on_conflict_do_nothing(index_elements=["session"])
        )

    return pass_joined


def _recorded(t: ExtractionTables) -> Handler:
    def recorded(conn: Connection, event: Event) -> None:
        payload = ExtractionRecorded.model_validate(event.payload)
        cited = payload.cited
        scope = scope_of_schema_ref(payload.schema_ref)
        inserted = conn.execute(
            sqlite_insert(t.rows)
            .values(
                extraction_id=payload.extraction_id,
                scope=scope.value,
                pack=CONTRIBUTION_SCOPE_NAME if scope is Scope.CONTRIBUTION else None,
                cited_extraction_id=cited.reference_extraction_id if cited else None,
                cited_ordinal=cited.ordinal if cited else None,
                cited_marker=cited.marker if cited else None,
                work_id=payload.work_id,
                pass_label=payload.pass_label.value,
                task_id=payload.task_id,
                protocol_id=payload.protocol_id,
                schema_ref=payload.schema_ref,
                document_id=payload.document_id,
                conversion_id=payload.conversion_id,
                row_key=payload.row_key,
                supersedes=payload.supersedes,
                superseded_by=None,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["extraction_id"])
        )
        if inserted.rowcount == 0:
            return
        for name, field in payload.fields.items():
            conn.execute(
                sqlite_insert(t.fields)
                .values(
                    extraction_id=payload.extraction_id,
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
                .on_conflict_do_nothing(index_elements=["extraction_id", "field"])
            )
        if payload.supersedes is not None:
            conn.execute(
                update(t.rows)
                .where(t.rows.c.extraction_id == payload.supersedes)
                .where(t.rows.c.superseded_by.is_(None))
                .values(superseded_by=payload.extraction_id)
            )

    return recorded


def _claim(t: ExtractionTables) -> Handler:
    def claim(conn: Connection, event: Event) -> None:
        payload = ClaimRecorded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.claims)
            .values(
                claim_id=payload.claim_id,
                work_id=payload.work_id,
                pass_label=payload.pass_label.value,
                task_id=payload.task_id,
                protocol_id=payload.protocol_id,
                document_id=payload.document_id,
                conversion_id=payload.conversion_id,
                statement=payload.statement,
                claim_type=payload.claim_type.value,
                evidence_type=payload.evidence_type.value,
                strength=payload.strength.value,
                anchor=payload.anchor,
                quote=payload.quote,
                supersedes=payload.supersedes,
                superseded_by=None,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["claim_id"])
        )
        if payload.supersedes is not None:
            conn.execute(
                update(t.claims)
                .where(t.claims.c.claim_id == payload.supersedes)
                .where(t.claims.c.superseded_by.is_(None))
                .values(superseded_by=payload.claim_id)
            )

    return claim


def _closed(t: ExtractionTables) -> Handler:
    def closed(conn: Connection, event: Event) -> None:
        payload = ExtractionClosed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.closures)
            .values(
                task_id=payload.task_id,
                scope=scope_of_pack(payload.pack).value,
                work_id=payload.work_id,
                pass_label=payload.pass_label.value,
                rows=payload.rows,
                claims=payload.claims,
                reason=payload.reason,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["task_id"])
        )

    return closed


def _resolved(t: ExtractionTables) -> Handler:
    def resolved(conn: Connection, event: Event) -> None:
        payload = ExtractionResolved.model_validate(event.payload)
        values = {
            "scope": scope_of_pack(payload.pack).value,
            "work_id": payload.work_id,
            "row_key": payload.row_key,
            "field": WHOLE_ROW if payload.field is None else payload.field,
            "choice": payload.choice,
            "reason": payload.reason,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.resolutions)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["scope", "work_id", "row_key", "field"], set_=values
            )
        )

    return resolved


def _audit_sampled(t: ExtractionTables) -> Handler:
    def audit_sampled(conn: Connection, event: Event) -> None:
        payload = ExtractionAuditSampled.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.audits)
            .values(
                audit_id=payload.audit_id,
                scope=audit_scope_of_pack(payload.pack).value,
                random_seed=payload.random_seed,
                population=payload.population,
                population_digest=payload.population_digest,
                protocol_id=payload.protocol_id,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["audit_id"])
        )
        if inserted.rowcount == 0:
            return
        for item in payload.items:
            conn.execute(
                sqlite_insert(t.audit_items)
                .values(
                    audit_id=payload.audit_id,
                    scope=audit_scope_of_pack(payload.pack).value,
                    work_id=item.work_id,
                    row_key=item.row_key,
                    field=item.field,
                    extraction_id=item.extraction_id,
                    correct=None,
                    note="",
                )
                .on_conflict_do_nothing(index_elements=["audit_id", "work_id", "row_key", "field"])
            )

    return audit_sampled


def _audit_labelled(t: ExtractionTables) -> Handler:
    def audit_labelled(conn: Connection, event: Event) -> None:
        payload = ExtractionAuditLabelled.model_validate(event.payload)
        conn.execute(
            update(t.audit_items)
            .where(t.audit_items.c.audit_id == payload.audit_id)
            .where(t.audit_items.c.work_id == payload.work_id)
            .where(t.audit_items.c.row_key == payload.row_key)
            .where(t.audit_items.c.field == payload.field)
            .values(correct=payload.correct, note=payload.note)
        )

    return audit_labelled
