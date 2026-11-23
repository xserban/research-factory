"""Projection of the gate audit (slice M, M-B): one row per sample, one per sampled act.

`gate_audits` holds each `gate.audit_sampled`; `gate_audit_items` the sampled act ids with the
human's latest label (`correct`, `note`), null until labelled. Handlers are total: a label of an
unknown audit or an act outside its sample changes nothing, and a later label replaces an earlier
one. A sample and a label are human acts (the services refuse any other actor, R-51): an event of
another actor is left unfolded. Both tables are empty for a log without these events, so they are
left out of the state hash then.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.human_channel import sign_off_counts
from factory.index.projection import Handler
from factory.model.gate_audit import GateAuditLabelled, GateAuditSampled


@dataclass(frozen=True)
class GateTables:
    audits: Table
    items: Table


def gate_tables(metadata: MetaData) -> GateTables:
    audits = Table(
        "gate_audits",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("gate_id", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("population", Integer, nullable=False),
        Column("population_digest", String, nullable=False),
        Column("random_seed", Integer, nullable=False),
        Column("protocol_id", String),
    )
    items = Table(
        "gate_audit_items",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("act_event_id", String, primary_key=True),
        Column("correct", Boolean),
        Column("note", String),
    )
    return GateTables(audits, items)


def gate_handlers(t: GateTables) -> dict[str, Handler]:
    def sampled(conn: Connection, event: Event) -> None:
        if event.actor.kind not in ("human", "system"):  # system: the platform's draw (C4)
            return
        payload = GateAuditSampled.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.audits)
            .values(
                audit_id=payload.audit_id,
                gate_id=payload.gate_id,
                event_id=event.id,
                population=payload.population,
                population_digest=payload.population_digest,
                random_seed=payload.random_seed,
                protocol_id=payload.protocol_id,
            )
            .on_conflict_do_nothing(index_elements=["audit_id"])
        )
        for act in payload.act_event_ids:
            conn.execute(
                sqlite_insert(t.items)
                .values(audit_id=payload.audit_id, act_event_id=act)
                .on_conflict_do_nothing(index_elements=["audit_id", "act_event_id"])
            )

    def labelled(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        payload = GateAuditLabelled.model_validate(event.payload)
        if not sign_off_counts(conn, event.actor, payload.channel):
            return
        conn.execute(
            update(t.items)
            .where(
                t.items.c.audit_id == payload.audit_id,
                t.items.c.act_event_id == payload.act_event_id,
            )
            .values(correct=payload.correct, note=payload.note)
        )

    return {"gate.audit_sampled": sampled, "gate.audit_labelled": labelled}
