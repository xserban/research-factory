"""Projection of curation proposals and their decisions (IDEA-15, plan SV task 4, PD-8; R-34, R-51,
R-52).

`curation_proposals` keeps one row per `cur_` id: the proposal, who proposed it, and, once decided,
the decision. A row is never removed; a rejected proposal stays (R-52).

Folded only if (a hand-written event failing a guard changes nothing on rebuild):
- `curation.proposed`: an agent or a human proposes; a `cur_` id is written once.
- `curation.decided`: the actor is a human other than the proposer (same id or same user, R-51);
  the proposal exists and is undecided; a linked amendment event exists in `amendments` and the
  proposal is of kind `amendment`. The decision records the link and changes no protocol.

Handlers are total: an event that does not validate or names something unknown changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.curation import (
    CurationDecided,
    CurationDecision,
    CurationKind,
    CurationProposed,
)


@dataclass(frozen=True)
class CurationTables:
    proposals: Table


def curation_tables(metadata: MetaData) -> CurationTables:
    proposals = Table(
        "curation_proposals",
        metadata,
        Column("cur_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("text", String, nullable=False),
        Column("lessons_json", String, nullable=False),
        Column("target", String),
        Column("proposer_kind", String, nullable=False),
        Column("proposer_id", String, nullable=False),
        Column("proposer_user", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("decision", String),
        Column("rationale", String),
        Column("amendment_event", String),
        Column("decided_by", String),
        Column("decision_event_id", String),
    )
    return CurationTables(proposals)


def _proposed(t: CurationTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = CurationProposed.model_validate(event.payload)
        if event.actor.kind not in ("agent", "human"):
            return
        conn.execute(
            sqlite_insert(t.proposals)
            .values(
                cur_id=p.cur_id,
                kind=p.kind.value,
                text=p.text,
                lessons_json=canonical_json(list(p.lessons)).decode(),
                target=p.target,
                proposer_kind=event.actor.kind,
                proposer_id=event.actor.id,
                proposer_user=event.actor.user,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["cur_id"])
        )

    return _total(proposed)


def _decided(t: CurationTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = CurationDecided.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        row = conn.execute(
            text(
                "SELECT kind, proposer_id, proposer_user, decision FROM curation_proposals"
                " WHERE cur_id = :c"
            ),
            {"c": p.cur_id},
        ).first()
        if row is None or row[3] is not None:
            return  # unknown, or decided once already
        if event.actor.id == str(row[1]) or event.actor.user == str(row[2]):
            return  # a proposer never decides its own proposal (R-51)
        if p.amendment_event is not None:
            linked = conn.execute(
                text("SELECT 1 FROM amendments WHERE event_id = :e"), {"e": p.amendment_event}
            ).first()
            if linked is None or str(row[0]) != CurationKind.AMENDMENT.value:
                return
        conn.execute(
            text(
                "UPDATE curation_proposals SET decision = :d, rationale = :r, amendment_event = :a,"
                " decided_by = :u, decision_event_id = :e WHERE cur_id = :c"
            ),
            {
                "d": CurationDecision(p.decision).value,
                "r": p.rationale,
                "a": p.amendment_event,
                "u": event.actor.id,
                "e": event.id,
                "c": p.cur_id,
            },
        )

    return _total(decided)


def _total(handler: Handler) -> Handler:
    def run(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError, IndexError):
            return

    return run


def curation_handlers(t: CurationTables) -> dict[str, Handler]:
    return {"curation.proposed": _proposed(t), "curation.decided": _decided(t)}
