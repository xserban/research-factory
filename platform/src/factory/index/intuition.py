"""Projection of interpretations and the layer graph (slice 3c, plan G3-A).

`interpretations` keeps every recorded interpretation with its review state folded from events:
`unreviewed` on recording, the latest `reviewed`/`wrong` review after, `superseded` once a later
interpretation names it in `supersedes` (terminal: a later review is kept in
`interpretation_reviews` but changes nothing). `interpretation_sources` has one row per stored
source. `layer_hidden` is a view of the hidden counts.

The layer graph has its own tables (plan ruling A1): `layer_nodes` (an interpretation is a node of
type `interpretation`) and `layer_edges` (`explains`, from the interpretation to its target), each
row with `class = 'interpretation'` (enforced by a CHECK) and the review state. G2's `graph_nodes`
and `graph_edges` are neither read nor written here: the separation from evidence rests on
storage, not on a filter.

Handlers are total: an event naming an unknown interpretation changes nothing, never raises, and an
interpretation id is first-write-wins. Defence in depth (R-51): a review is folded only when its
actor is human, and not when it comes from the session that wrote an agent-written interpretation
(a relay of a human answer by the writing session); no service writes such an event.
An MCP-relayed review records its session in `label_sessions`, which bars it from passes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    event,
    text,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.intuition import (
    Author,
    InterpretationRecorded,
    InterpretationReviewed,
    ReviewState,
)
from factory.model.screening import Channel

LAYER_CLASS = "interpretation"


@dataclass(frozen=True)
class IntuitionTables:
    interpretations: Table
    sources: Table
    reviews: Table
    layer_nodes: Table
    layer_edges: Table


def intuition_tables(metadata: MetaData, label_sessions: Table) -> IntuitionTables:
    interpretations = Table(
        "interpretations",
        metadata,
        Column("interpretation_id", String, primary_key=True),
        Column("target", String, nullable=False),
        Column("target_kind", String, nullable=False),
        Column("text", String, nullable=False),
        Column("author", String, nullable=False),
        Column("author_user", String, nullable=False),
        Column("writer_session", String, nullable=False),
        Column("writer_model", String),
        Column("task_id", String),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("review_state", String, nullable=False),
        Column("self_reviewed", Integer, nullable=False),
        Column("last_review_event", String),
        Column("input_blob", String),
        Column("event_id", String, nullable=False),
        Index("ix_interpretations_target", "target", "review_state"),
        Index("ix_interpretations_state", "review_state", "interpretation_id"),
    )
    sources = Table(
        "interpretation_sources",
        metadata,
        Column("interpretation_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("role", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("work_id", String),
        Column("conversion_id", String),
        Column("document_id", String),
        Column("anchor", String),
        Column("quote", String),
        Column("reference", String),
        Column("link_state", String),
        Column("resolved_work", String),
        Index("ix_interpretation_sources_document", "document_id"),
    )
    reviews = Table(
        "interpretation_reviews",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("interpretation_id", String, nullable=False),
        Column("state", String, nullable=False),
        Column("note", String, nullable=False),
        Column("reviewer_user", String, nullable=False),
        Column("self_reviewed", Integer, nullable=False),
        Column("channel", String, nullable=False),
        Index("ix_interpretation_reviews_id", "interpretation_id", "event_id"),
    )
    layer_nodes = Table(
        "layer_nodes",
        metadata,
        Column("node_id", String, primary_key=True),
        Column("node_type", String, nullable=False),
        Column("class", String, nullable=False),
        Column("review_state", String, nullable=False),
        Column("event_id", String, nullable=False),
        CheckConstraint("class = 'interpretation'", name="ck_layer_nodes_class"),
    )
    layer_edges = Table(
        "layer_edges",
        metadata,
        Column("edge_id", String, primary_key=True),
        Column("edge_type", String, nullable=False),
        Column("source", String, nullable=False),
        Column("target", String, nullable=False),
        Column("class", String, nullable=False),
        Column("review_state", String, nullable=False),
        Column("basis", String),
        Column("event_id", String, nullable=False),
        CheckConstraint("class = 'interpretation'", name="ck_layer_edges_class"),
        Index("ix_layer_edges_source", "source"),
        Index("ix_layer_edges_target", "target"),
    )
    event.listen(
        metadata,
        "after_create",
        DDL(  # type: ignore[no-untyped-call]
            "CREATE VIEW IF NOT EXISTS layer_hidden AS "
            "SELECT 'interpretation' AS item, review_state AS reason, COUNT(*) AS n "
            "FROM interpretations WHERE review_state IN ('wrong', 'superseded') "
            "GROUP BY review_state"
        ),
    )
    return IntuitionTables(interpretations, sources, reviews, layer_nodes, layer_edges)


def intuition_handlers(t: IntuitionTables, label_sessions: Table) -> dict[str, Handler]:
    return {
        "interpretation.recorded": _recorded(t),
        "interpretation.reviewed": _reviewed(t, label_sessions),
    }


def _recorded(t: IntuitionTables) -> Handler:
    def recorded(conn: Connection, ev: Event) -> None:
        p = InterpretationRecorded.model_validate(ev.payload)
        inserted = conn.execute(
            sqlite_insert(t.interpretations)
            .values(
                interpretation_id=p.interpretation_id,
                target=p.target,
                target_kind=p.target_kind,
                text=p.text,
                author=p.author.value,
                author_user=ev.actor.user,
                writer_session=ev.actor.session,
                writer_model=ev.actor.model,
                task_id=p.task_id,
                supersedes=p.supersedes,
                review_state=ReviewState.UNREVIEWED.value,
                self_reviewed=0,
                input_blob=ev.input_blob,
                event_id=ev.id,
            )
            .on_conflict_do_nothing(index_elements=["interpretation_id"])
        )
        if not inserted.rowcount:
            return
        for position, source in enumerate(p.sources):
            conn.execute(
                sqlite_insert(t.sources)
                .values(
                    interpretation_id=p.interpretation_id,
                    position=position,
                    role=source.role.value,
                    kind=source.kind,
                    work_id=source.work_id,
                    conversion_id=source.conversion_id,
                    document_id=source.document_id,
                    anchor=source.anchor,
                    quote=source.quote,
                    reference=source.reference,
                    link_state=source.link_state,
                    resolved_work=source.resolved_work,
                )
                .on_conflict_do_nothing(index_elements=["interpretation_id", "position"])
            )
        conn.execute(
            sqlite_insert(t.layer_nodes)
            .values(
                {
                    "node_id": p.interpretation_id,
                    "node_type": "interpretation",
                    "class": LAYER_CLASS,
                    "review_state": ReviewState.UNREVIEWED.value,
                    "event_id": ev.id,
                }
            )
            .on_conflict_do_nothing(index_elements=["node_id"])
        )
        conn.execute(
            sqlite_insert(t.layer_edges)
            .values(
                {
                    "edge_id": "explains:" + p.interpretation_id,
                    "edge_type": "explains",
                    "source": p.interpretation_id,
                    "target": p.target,
                    "class": LAYER_CLASS,
                    "review_state": ReviewState.UNREVIEWED.value,
                    "basis": p.interpretation_id,
                    "event_id": ev.id,
                }
            )
            .on_conflict_do_nothing(index_elements=["edge_id"])
        )
        if p.supersedes is not None:
            _supersede(conn, t, p.supersedes, p.interpretation_id)

    return recorded


def _set_state(conn: Connection, t: IntuitionTables, interpretation_id: str, state: str) -> None:
    conn.execute(
        update(t.layer_nodes)
        .where(t.layer_nodes.c.node_id == interpretation_id)
        .values(review_state=state)
    )
    conn.execute(
        update(t.layer_edges)
        .where(t.layer_edges.c.edge_id == "explains:" + interpretation_id)
        .values(review_state=state)
    )


def _supersede(conn: Connection, t: IntuitionTables, prior: str, new: str) -> None:
    changed = conn.execute(
        update(t.interpretations)
        .where(
            t.interpretations.c.interpretation_id == prior,
            t.interpretations.c.superseded_by.is_(None),
        )
        .values(superseded_by=new, review_state=ReviewState.SUPERSEDED.value)
    ).rowcount
    if changed:
        _set_state(conn, t, prior, ReviewState.SUPERSEDED.value)


def _reviewed(t: IntuitionTables, label_sessions: Table) -> Handler:
    def reviewed(conn: Connection, ev: Event) -> None:
        if ev.actor.kind != "human":
            return
        p = InterpretationReviewed.model_validate(ev.payload)
        row = conn.execute(
            text(
                "SELECT author, writer_session, review_state FROM interpretations "
                "WHERE interpretation_id = :i"
            ),
            {"i": p.interpretation_id},
        ).first()
        if row is None:
            return
        if row[0] == Author.AGENT.value and row[1] == ev.actor.session:
            return  # the writer never evaluates its own output, relayed or not
        conn.execute(
            sqlite_insert(t.reviews)
            .values(
                event_id=ev.id,
                interpretation_id=p.interpretation_id,
                state=p.state,
                note=p.note,
                reviewer_user=ev.actor.user,
                self_reviewed=int(p.self_reviewed),
                channel=p.channel.value,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        if p.channel is Channel.MCP:  # a relaying session cannot join a pass (37.6)
            conn.execute(
                sqlite_insert(label_sessions)
                .values(session=ev.actor.session)
                .on_conflict_do_nothing(index_elements=["session"])
            )
        if row[2] == ReviewState.SUPERSEDED.value:
            return
        conn.execute(
            update(t.interpretations)
            .where(t.interpretations.c.interpretation_id == p.interpretation_id)
            .values(
                review_state=p.state, self_reviewed=int(p.self_reviewed), last_review_event=ev.id
            )
        )
        _set_state(conn, t, p.interpretation_id, p.state)

    return reviewed
