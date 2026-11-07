"""Projection of suggested decisions and the scientist's selections (slice 8, plan A2).

`decision_sets` (not `decisions`, which is the screening table) has one row per suggestion;
`decision_items` one row per item, suggested or added.

Folds are total and atomic: an event that fails a guard changes nothing, on rebuild too, and never
raises. A suggestion is folded only from an agent, with a new id, and a `supersedes` naming a known
decision not yet superseded. A selection is folded only from a human over an unforged, unbarred
channel, on a known and unsuperseded decision, and only when every selected id is one of the
decision's suggested items. The latest selection on a decision decides the statuses: selected
items are `validated`, the other suggested items `rejected`, and each added text becomes an item
`A01`, `A02`, ... with origin and status `added`. The log keeps every earlier selection;
`decision_sets` keeps the accepted one (`sel_*`).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.human_channel import sign_off_counts
from factory.index.projection import Handler
from factory.model.decisions import DecisionSelected, DecisionSuggested


@dataclass(frozen=True)
class DecisionTables:
    decisions: Table
    decision_items: Table


def decision_tables(metadata: MetaData) -> DecisionTables:
    decisions = Table(
        "decision_sets",
        metadata,
        Column("decision_id", String, primary_key=True),
        Column("level", String, nullable=False),
        Column("subject", String, nullable=False),
        Column("explanation", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("suggested_at", String, nullable=False),
        Column("actor", String, nullable=False),
        # The accepted selection the fold took last (all NULL until one is folded): the view and
        # the binding read these, never the log, so they agree with the statuses of the items.
        Column("sel_event", String),
        Column("sel_actor", String),
        Column("sel_ts", String),
        Column("sel_channel", String),
        Column("sel_note", String),
        Column("sel_reconstructed", Integer),
        Column("sel_selected", String),
        Column("sel_added", String),
    )
    items = Table(
        "decision_items",
        metadata,
        Column("decision_id", String, primary_key=True),
        Column("item_id", String, primary_key=True),
        Column("text", String, nullable=False),
        Column("grounds", String, nullable=False),
        Column("recommended", Integer, nullable=False),
        Column("origin", String, nullable=False),
        Column("status", String, nullable=False),
    )
    return DecisionTables(decisions, items)


def decision_handlers(t: DecisionTables) -> dict[str, Handler]:
    def suggested(conn: Connection, event: Event) -> None:
        if event.actor.kind != "agent":
            return
        try:
            p = DecisionSuggested.model_validate(event.payload)
        except ValidationError:
            return
        known = conn.execute(
            select(t.decisions.c.decision_id).where(t.decisions.c.decision_id == p.decision_id)
        ).first()
        if known is not None:
            return
        if p.supersedes is not None:
            prior = conn.execute(
                select(t.decisions.c.superseded_by).where(t.decisions.c.decision_id == p.supersedes)
            ).first()
            if prior is None or prior[0] is not None:
                return
        conn.execute(
            sqlite_insert(t.decisions).values(
                decision_id=p.decision_id,
                level=p.level.value,
                subject=p.subject,
                explanation=p.explanation,
                supersedes=p.supersedes,
                suggested_at=format_ts(event.ts),
                actor=event.actor.id,
            )
        )
        for item in p.items:
            conn.execute(
                sqlite_insert(t.decision_items).values(
                    decision_id=p.decision_id,
                    item_id=item.item_id,
                    text=item.text,
                    grounds=canonical_json(list(item.grounds)).decode(),
                    recommended=int(item.recommended),
                    origin="suggested",
                    status="proposed",
                )
            )
        if p.supersedes is not None:
            conn.execute(
                update(t.decisions)
                .where(t.decisions.c.decision_id == p.supersedes)
                .values(superseded_by=p.decision_id)
            )

    def selected(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        try:
            p = DecisionSelected.model_validate(event.payload)
        except ValidationError:
            return
        if not sign_off_counts(conn, event.actor, p.channel):
            return
        row = conn.execute(
            select(t.decisions.c.superseded_by).where(t.decisions.c.decision_id == p.decision_id)
        ).first()
        if row is None or row[0] is not None:
            return
        suggested_ids = {
            str(r[0])
            for r in conn.execute(
                select(t.decision_items.c.item_id).where(
                    t.decision_items.c.decision_id == p.decision_id,
                    t.decision_items.c.origin == "suggested",
                )
            )
        }
        if not set(p.selected) <= suggested_ids:
            return
        conn.execute(
            delete(t.decision_items).where(
                t.decision_items.c.decision_id == p.decision_id,
                t.decision_items.c.origin == "added",
            )
        )
        for item_id in suggested_ids:
            conn.execute(
                update(t.decision_items)
                .where(
                    t.decision_items.c.decision_id == p.decision_id,
                    t.decision_items.c.item_id == item_id,
                )
                .values(status="validated" if item_id in p.selected else "rejected")
            )
        conn.execute(
            update(t.decisions)
            .where(t.decisions.c.decision_id == p.decision_id)
            .values(
                sel_event=event.id,
                sel_actor=event.actor.id,
                sel_ts=format_ts(event.ts),
                sel_channel=p.channel.value,
                sel_note=p.note,
                sel_reconstructed=int(p.reconstructed),
                sel_selected=canonical_json(list(p.selected)).decode(),
                sel_added=canonical_json(list(p.added)).decode(),
            )
        )
        for n, text in enumerate(p.added, start=1):
            conn.execute(
                sqlite_insert(t.decision_items).values(
                    decision_id=p.decision_id,
                    item_id=f"A{n:02d}",
                    text=text,
                    grounds="[]",
                    recommended=0,
                    origin="added",
                    status="added",
                )
            )

    return {"decision.suggested": suggested, "decision.selected": selected}
