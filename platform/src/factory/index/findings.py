"""Projection of claim contradictions (slice 6, plan H-B).

`contradictions` has one row per proposed pair; the pair `(ref_a, ref_b)` is unique, so a second
proposal of the same pair changes nothing (first write wins). A decision is folded only when its
actor is a human (defence in depth, R-51: no service writes one for another actor kind), and the
latest human decision governs. Handlers are total: a decision naming an unknown contradiction
changes nothing. The table is empty for a log without these events, so it is left out of the
state hash then. The quotes, anchors and note of the first proposal are kept for readers (N10).
"""

from __future__ import annotations

from sqlalchemy import Column, Index, MetaData, String, Table, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.findings import ContradictionDecided, ContradictionProposed


def finding_tables(metadata: MetaData) -> Table:
    return Table(
        "contradictions",
        metadata,
        Column("contradiction_id", String, primary_key=True),
        Column("ref_a", String, nullable=False),
        Column("ref_b", String, nullable=False),
        Column("work_a", String, nullable=False),
        Column("work_b", String, nullable=False),
        Column("quote_a", String),
        Column("quote_b", String),
        Column("anchor_a", String),
        Column("anchor_b", String),
        Column("note", String),
        Column("decision", String),
        Column("decision_event_id", String),
        Column("event_id", String, nullable=False),
        Index("ix_contradictions_pair", "ref_a", "ref_b", unique=True),
    )


def finding_handlers(contradictions: Table) -> dict[str, Handler]:
    def proposed(conn: Connection, event: Event) -> None:
        p = ContradictionProposed.model_validate(event.payload)
        conn.execute(
            sqlite_insert(contradictions)
            .values(
                contradiction_id=p.contradiction_id,
                ref_a=p.ref_a,
                ref_b=p.ref_b,
                work_a=p.work_a,
                work_b=p.work_b,
                quote_a=p.quote_a,
                quote_b=p.quote_b,
                anchor_a=p.anchor_a,
                anchor_b=p.anchor_b,
                note=p.note,
                event_id=event.id,
            )
            .on_conflict_do_nothing()
        )

    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = ContradictionDecided.model_validate(event.payload)
        conn.execute(
            update(contradictions)
            .where(contradictions.c.contradiction_id == p.contradiction_id)
            .values(decision=p.decision, decision_event_id=event.id)
        )

    return {"contradiction.proposed": proposed, "contradiction.decided": decided}
