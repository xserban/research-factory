"""Projection of appraisal (IDEA-21): answers, judgements, closures and audits.

Tables:
- `appraisal_answers`: one row per item of an `appraisal.recorded` event, keyed by the event.
- `appraisal_judgements`: a human's judgement item (`source` `judged`) or choice between the
  two passes on a span item (`source` `resolved`), keyed by the event.
- `appraisal_closures`: the work a pass finished.
- `appraisal_audits` and `appraisal_audit_items`: a drawn sample and its labels.

All are omitted from the index hash while empty, so a project that never appraises keeps its
hash. Handlers are total (see the fold rules in `index/briefings.py`): an event failing any guard
stays in the log and changes nothing, on rebuild too. The guards are the ones the services
enforce, so a hand-written event cannot do what a service refuses:
- A recording comes from an agent whose model and session are the event's own, under the
  instrument and digest in force, and holds only items of kind `agent-span`.
- A judgement or a resolution comes from a human, under the digest in force, for an item of the
  right kind. No agent writes a judgement item by any route.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Boolean, Column, Index, Integer, MetaData, String, Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from factory.errors import FactoryError
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.appraisal import AppraisalInstrument, ItemKind
from factory.model.appraisal_events import (
    AppraisalAuditLabelled,
    AppraisalAuditSampled,
    AppraisalJudged,
    AppraisalRecorded,
    AppraisalResolved,
)
from factory.model.protocol import ProtocolSpec, section_digest


@dataclass(frozen=True)
class AppraisalTables:
    protocols: Table
    answers: Table
    judgements: Table
    closures: Table
    audits: Table
    audit_items: Table


_Fold = Callable[[Connection, Event, AppraisalTables], None]


def appraisal_tables(metadata: MetaData, protocols: Table) -> AppraisalTables:
    answers = Table(
        "appraisal_answers",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("item", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("task_id", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("instrument", String, nullable=False),
        Column("digest", String, nullable=False),
        Column("answer", String, nullable=False),
        Column("anchor", String),
        Column("quote", String),
        Column("session", String, nullable=False),
        Column("model", String, nullable=False),
        Index("ix_appraisal_answers_work", "work_id", "pass_label"),
    )
    judgements = Table(
        "appraisal_judgements",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("source", String, nullable=False),
        Column("work_id", String, nullable=False),
        Column("item", String, nullable=False),
        Column("answer", String, nullable=False),
        Column("rationale", String, nullable=False),
        Column("digest", String, nullable=False),
        Index("ix_appraisal_judgements_work", "work_id", "item"),
    )
    closures = Table(
        "appraisal_closures",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("conversion_id", String, nullable=False),
        Column("digest", String, nullable=False),
        Column("reason", String),
        Index("ix_appraisal_closures_work", "work_id", "pass_label"),
    )
    audits = Table(
        "appraisal_audits",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("random_seed", Integer, nullable=False),
        Column("digest", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    audit_items = Table(
        "appraisal_audit_items",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("item", String, primary_key=True),
        Column("correct", Boolean),
        Column("note", String, nullable=False, default=""),
        Column("label_event_id", String),
    )
    return AppraisalTables(protocols, answers, judgements, closures, audits, audit_items)


def appraisal_handlers(t: AppraisalTables) -> dict[str, Handler]:
    return {
        "appraisal.recorded": _total(_recorded, t),
        "appraisal.judged": _total(_judged, t),
        "appraisal.resolved": _total(_resolved, t),
        "appraisal.audit_sampled": _total(_audit_sampled, t),
        "appraisal.audit_labelled": _total(_audit_labelled, t),
    }


def _total(fold: _Fold, t: AppraisalTables) -> Handler:
    def handler(conn: Connection, event: Event) -> None:
        try:
            with conn.begin_nested():
                fold(conn, event, t)
        except (ValueError, KeyError, TypeError, AttributeError, FactoryError, SQLAlchemyError):
            return

    return handler


def instrument_in_force(
    conn: Connection, protocols: Table
) -> tuple[AppraisalInstrument, str] | None:
    """The instrument of the latest protocol recorded so far and its section digest, or None."""
    row = conn.execute(
        select(protocols.c.spec).order_by(protocols.c.event_id.desc()).limit(1)
    ).first()
    if row is None:
        return None
    spec = ProtocolSpec.model_validate_json(str(row[0]))
    if spec.appraisal_instrument is None:
        return None
    return spec.appraisal_instrument, section_digest(spec, "appraisal_instrument")


def _kind_ok(conn: Connection, t: AppraisalTables, digest: str, item: str, kind: ItemKind) -> bool:
    found = instrument_in_force(conn, t.protocols)
    if found is None or found[1] != digest:
        return False
    declared = found[0].item(item)
    return declared is not None and declared.kind is kind


def _recorded(conn: Connection, event: Event, t: AppraisalTables) -> None:
    p = AppraisalRecorded.model_validate(event.payload)
    actor = event.actor
    if actor.kind != "agent" or actor.model != p.model or actor.session != p.session:
        return
    found = instrument_in_force(conn, t.protocols)
    if found is None or found[1] != p.digest or found[0].ref != p.instrument:
        return
    seen: set[str] = set()
    for a in p.answers:
        declared = found[0].item(a.item)
        if declared is None or declared.kind is not ItemKind.AGENT_SPAN or a.item in seen:
            return
        seen.add(a.item)
        if a.answer.value != "unclear" and (not a.anchor or not (a.quote or "").strip()):
            return
    for a in p.answers:
        conn.execute(
            sqlite_insert(t.answers)
            .values(
                event_id=event.id,
                item=a.item,
                work_id=p.work_id,
                pass_label=p.pass_label.value,
                task_id=p.task_id,
                conversion_id=p.conversion_id,
                instrument=p.instrument,
                digest=p.digest,
                answer=a.answer.value,
                anchor=a.anchor,
                quote=a.quote,
                session=p.session,
                model=p.model,
            )
            .on_conflict_do_nothing()
        )
    if p.finished:
        conn.execute(
            sqlite_insert(t.closures)
            .values(
                event_id=event.id,
                work_id=p.work_id,
                pass_label=p.pass_label.value,
                conversion_id=p.conversion_id,
                digest=p.digest,
                reason=p.reason,
            )
            .on_conflict_do_nothing()
        )


def _judged(conn: Connection, event: Event, t: AppraisalTables) -> None:
    p = AppraisalJudged.model_validate(event.payload)
    if event.actor.kind != "human" or not _kind_ok(conn, t, p.digest, p.item, ItemKind.JUDGEMENT):
        return
    conn.execute(
        sqlite_insert(t.judgements)
        .values(
            event_id=event.id,
            source="judged",
            work_id=p.work_id,
            item=p.item,
            answer=p.answer.value,
            rationale=p.rationale,
            digest=p.digest,
        )
        .on_conflict_do_nothing()
    )


def _resolved(conn: Connection, event: Event, t: AppraisalTables) -> None:
    p = AppraisalResolved.model_validate(event.payload)
    if event.actor.kind != "human" or not _kind_ok(conn, t, p.digest, p.item, ItemKind.AGENT_SPAN):
        return
    conn.execute(
        sqlite_insert(t.judgements)
        .values(
            event_id=event.id,
            source="resolved",
            work_id=p.work_id,
            item=p.item,
            answer=p.choice,
            rationale=p.reason,
            digest=p.digest,
        )
        .on_conflict_do_nothing()
    )


def _audit_sampled(conn: Connection, event: Event, t: AppraisalTables) -> None:
    p = AppraisalAuditSampled.model_validate(event.payload)
    found = instrument_in_force(conn, t.protocols)
    if event.actor.kind == "agent" or found is None or found[1] != p.digest:
        return
    conn.execute(
        sqlite_insert(t.audits)
        .values(audit_id=p.audit_id, random_seed=p.random_seed, digest=p.digest, event_id=event.id)
        .on_conflict_do_nothing()
    )
    for work_id, item in p.items:
        conn.execute(
            sqlite_insert(t.audit_items)
            .values(audit_id=p.audit_id, work_id=work_id, item=item, note="")
            .on_conflict_do_nothing()
        )


def _audit_labelled(conn: Connection, event: Event, t: AppraisalTables) -> None:
    p = AppraisalAuditLabelled.model_validate(event.payload)
    if event.actor.kind != "human":
        return
    conn.execute(
        t.audit_items.update()
        .where(
            t.audit_items.c.audit_id == p.audit_id,
            t.audit_items.c.work_id == p.work_id,
            t.audit_items.c.item == p.item,
        )
        .values(correct=p.correct, note=p.note, label_event_id=event.id)
    )
