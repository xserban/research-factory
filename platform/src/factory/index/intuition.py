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
(a relay of a human answer by the writing session); no service writes such an event. A decision
that came over the MCP channel (`channel = mcp`: a relay by an agent session) is never folded
whoever the actor is; a review is kept with `folded = 0`.
`interpretation_reviews.folded` is 0 for a review the fold dropped, so the history lists it.
No layer event writes a screening table (`label_sessions` gates pass joins).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
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
    delete,
    event,
    text,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.intuition.classify import fold
from factory.model.intuition import (
    Author,
    ConceptDefined,
    ConceptLinkDecided,
    ConceptLinkProposed,
    ConceptMerged,
    ConceptReviewed,
    ConceptSourceDecided,
    ConceptState,
    ConceptUnmerged,
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
    concepts: Table
    concept_aliases: Table
    concept_definitions: Table
    concept_reviews: Table
    concept_quotes: Table
    concept_source_decisions: Table
    concept_uses: Table
    concept_merges: Table


def intuition_tables(metadata: MetaData) -> IntuitionTables:
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
        Column("folded", Integer, nullable=False),
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
            "GROUP BY review_state "
            "UNION ALL "
            "SELECT 'concept', reason, COUNT(*) FROM (SELECT CASE "
            "WHEN merged_into IS NOT NULL THEN 'merged' "
            "WHEN source_state != 'approved' THEN 'unapproved' "
            "WHEN review_state = 'wrong' THEN 'wrong' END AS reason FROM concepts) "
            "WHERE reason IS NOT NULL GROUP BY reason "
            "UNION ALL "
            "SELECT 'concept_link', status, COUNT(*) FROM concept_uses "
            "WHERE status IN ('inferred', 'rejected') GROUP BY status"
        ),
    )
    c = _concept_tables(metadata)
    return IntuitionTables(
        interpretations,
        sources,
        reviews,
        layer_nodes,
        layer_edges,
        c["concepts"],
        c["concept_aliases"],
        c["concept_definitions"],
        c["concept_reviews"],
        c["concept_quotes"],
        c["concept_source_decisions"],
        c["concept_uses"],
        c["concept_merges"],
    )


def intuition_handlers(t: IntuitionTables) -> dict[str, Handler]:
    return {
        "interpretation.recorded": _recorded(t),
        "interpretation.reviewed": _reviewed(t),
        "concept.defined": _defined(t),
        "concept.source_decided": _source_decided(t),
        "concept.reviewed": _concept_reviewed(t),
        "concept.link_proposed": _link_proposed(t),
        "concept.link_decided": _link_decided(t),
        "concept.merged": _merged(t),
        "concept.unmerged": _unmerged(t),
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


def _reviewed(t: IntuitionTables) -> Handler:
    def reviewed(conn: Connection, ev: Event) -> None:
        p = InterpretationReviewed.model_validate(ev.payload)
        row = conn.execute(
            text(
                "SELECT author, writer_session, review_state FROM interpretations "
                "WHERE interpretation_id = :i"
            ),
            {"i": p.interpretation_id},
        ).first()
        # The fold stays pure; every review is kept, and `folded` says whether it counted.
        # Dropped: not by a human, an unknown interpretation, or (R-51) the writing session of an
        # agent-written one. A review of a superseded interpretation is kept and folded as history.
        folded = (
            ev.actor.kind == "human"
            and p.channel is not Channel.MCP
            and row is not None
            and not (row[0] == Author.AGENT.value and row[1] == ev.actor.session)
        )
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
                folded=int(folded),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        if not folded or row is None or row[2] == ReviewState.SUPERSEDED.value:
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


# --- Background concepts (plan G3-B) ---------------------------------------------------------


def _concept_tables(metadata: MetaData) -> dict[str, Table]:
    concepts = Table(
        "concepts",
        metadata,
        Column("concept_id", String, primary_key=True),
        Column("name", String, nullable=False),
        Column("name_folded", String, nullable=False),
        Column("text", String),
        Column("author", String, nullable=False),
        Column("author_user", String, nullable=False),
        Column("writer_session", String, nullable=False),
        Column("writer_model", String),
        Column("definition_event", String, nullable=False),
        Column("source_kind", String),
        Column("source_citation", String),
        Column("source_work", String),
        Column("source_digest", String),
        Column("source_verifiable", Integer),
        Column("source_state", String, nullable=False),
        Column("review_state", String, nullable=False),
        Column("self_reviewed", Integer, nullable=False),
        Column("merged_into", String),
        Column("input_blob", String),
        Column("event_id", String, nullable=False),
        Index("ix_concepts_name", "name_folded"),
        Index("ix_concepts_state", "source_state", "review_state", "concept_id"),
        Index("ix_concepts_merged", "merged_into"),
    )
    aliases = Table(
        "concept_aliases",
        metadata,
        Column("concept_id", String, primary_key=True),
        Column("alias", String, nullable=False),
        Column("alias_folded", String, primary_key=True),
        Index("ix_concept_aliases_folded", "alias_folded"),
    )
    definitions = Table(
        "concept_definitions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("concept_id", String, nullable=False),
        Column("supersedes", String),
        Index("ix_concept_definitions_concept", "concept_id", "event_id"),
    )
    reviews = Table(
        "concept_reviews",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("concept_id", String, nullable=False),
        Column("definition", String, nullable=False),
        Column("state", String, nullable=False),
        Column("note", String, nullable=False),
        Column("reviewer_user", String, nullable=False),
        Column("self_reviewed", Integer, nullable=False),
        Column("channel", String, nullable=False),
        Column("folded", Integer, nullable=False),
        Index("ix_concept_reviews_concept", "concept_id", "definition", "event_id"),
    )
    quotes = Table(
        "concept_quotes",
        metadata,
        Column("concept_id", String, primary_key=True),
        Column("position", Integer, primary_key=True),
        Column("work_id", String),
        Column("conversion_id", String),
        Column("document_id", String),
        Column("anchor", String),
        Column("quote", String),
        Index("ix_concept_quotes_document", "document_id"),
    )
    decisions = Table(
        "concept_source_decisions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("concept_id", String, nullable=False),
        Column("decision", String, nullable=False),
        Column("source_digest", String, nullable=False),
        Column("reviewer_user", String, nullable=False),
        Column("note", String, nullable=False),
        Index("ix_concept_decisions_concept", "concept_id", "source_digest", "event_id"),
    )
    uses = Table(
        "concept_uses",
        metadata,
        Column("link_id", String, primary_key=True),
        Column("from_node", String, nullable=False),
        Column("from_kind", String, nullable=False),
        Column("concept_id", String, nullable=False),
        Column("basis_kind", String, nullable=False),
        Column("basis_work", String),
        Column("basis_conversion", String),
        Column("basis_document", String),
        Column("basis_anchor", String),
        Column("basis_quote", String),
        Column("reference", String),
        Column("cited_work", String),
        Column("basis_digest", String, nullable=False),
        Column("proposed_status", String, nullable=False),
        Column("status", String, nullable=False),
        Column("status_reason", String, nullable=False),
        Column("note", String),
        Column("proposer_kind", String, nullable=False),
        Column("proposer_session", String, nullable=False),
        Column("decision", String),
        Column("decided_by", String),
        Column("decision_event", String),
        Column("event_id", String, nullable=False),
        Index("ix_concept_uses_concept", "concept_id", "status", "link_id"),
        Index("ix_concept_uses_from", "from_node"),
        Index("ix_concept_uses_status", "status", "link_id"),
    )
    merges = Table(
        "concept_merges",
        metadata,
        Column("from_concept", String, primary_key=True),
        Column("into_concept", String, nullable=False),
        Column("active", Integer, nullable=False),
        Column("merge_event", String, nullable=False),
        Column("unmerge_event", String),
        Index("ix_concept_merges_into", "into_concept", "active"),
    )
    return {
        "concepts": concepts,
        "concept_aliases": aliases,
        "concept_definitions": definitions,
        "concept_reviews": reviews,
        "concept_quotes": quotes,
        "concept_source_decisions": decisions,
        "concept_uses": uses,
        "concept_merges": merges,
    }


def _human_not_writer(conn: Connection, ev: Event, concept_id: str) -> bool:
    """A concept decision is folded only for a human who is not the session that wrote the live
    definition of an agent-written concept (R-51 defence in depth; the services refuse it)."""
    if ev.actor.kind != "human":
        return False
    row = conn.execute(
        text("SELECT author, writer_session FROM concepts WHERE concept_id = :c"),
        {"c": concept_id},
    ).first()
    if row is None:
        return False
    return not (row[0] == Author.AGENT.value and row[1] == ev.actor.session)


def _defined(t: IntuitionTables) -> Handler:
    def defined(conn: Connection, ev: Event) -> None:
        p = ConceptDefined.model_validate(ev.payload)
        conn.execute(
            sqlite_insert(t.concept_definitions)
            .values(event_id=ev.id, concept_id=p.concept_id, supersedes=p.supersedes)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        live = conn.execute(
            text("SELECT definition_event FROM concepts WHERE concept_id = :c"),
            {"c": p.concept_id},
        ).first()
        if live is None:
            if p.supersedes is not None:
                return  # a redefinition of an unknown concept
        elif p.supersedes != live[0]:
            return  # only the live definition is superseded (ruling B5)
        src = p.source
        values = {
            "name": p.name,
            "name_folded": fold(p.name),
            "text": p.text,
            "author": p.author.value,
            "author_user": ev.actor.user,
            "writer_session": ev.actor.session,
            "writer_model": ev.actor.model,
            "definition_event": ev.id,
            "source_kind": None if src is None else src.kind.value,
            "source_citation": None if src is None else src.citation,
            "source_work": None if src is None else src.work_id,
            "source_digest": None if src is None else src.digest,
            "source_verifiable": None if src is None else int(src.verifiable),
            "input_blob": ev.input_blob,
        }
        if live is None:
            conn.execute(
                sqlite_insert(t.concepts).values(
                    concept_id=p.concept_id,
                    source_state="none",
                    review_state=ConceptState.UNREVIEWED.value,
                    self_reviewed=0,
                    event_id=ev.id,
                    **values,
                )
            )
        else:
            conn.execute(
                update(t.concepts).where(t.concepts.c.concept_id == p.concept_id).values(**values)
            )
            conn.execute(
                delete(t.concept_aliases).where(t.concept_aliases.c.concept_id == p.concept_id)
            )
            conn.execute(
                delete(t.concept_quotes).where(t.concept_quotes.c.concept_id == p.concept_id)
            )
        for alias in p.aliases:
            conn.execute(
                sqlite_insert(t.concept_aliases)
                .values(concept_id=p.concept_id, alias=alias, alias_folded=fold(alias))
                .on_conflict_do_nothing(index_elements=["concept_id", "alias_folded"])
            )
        for position, q in enumerate(p.quotes):
            conn.execute(
                sqlite_insert(t.concept_quotes)
                .values(
                    concept_id=p.concept_id,
                    position=position,
                    work_id=q.work_id,
                    conversion_id=q.conversion_id,
                    document_id=q.document_id,
                    anchor=q.anchor,
                    quote=q.quote,
                )
                .on_conflict_do_nothing(index_elements=["concept_id", "position"])
            )
        _refresh_concepts(conn, t, [p.concept_id])

    return defined


def _source_decided(t: IntuitionTables) -> Handler:
    def decided(conn: Connection, ev: Event) -> None:
        p = ConceptSourceDecided.model_validate(ev.payload)
        if p.channel is Channel.MCP or not _human_not_writer(conn, ev, p.concept_id):
            return
        conn.execute(
            sqlite_insert(t.concept_source_decisions)
            .values(
                event_id=ev.id,
                concept_id=p.concept_id,
                decision=p.decision,
                source_digest=p.source_digest,
                reviewer_user=ev.actor.user,
                note=p.note,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        _refresh_concepts(conn, t, [p.concept_id])

    return decided


def _concept_reviewed(t: IntuitionTables) -> Handler:
    def reviewed(conn: Connection, ev: Event) -> None:
        p = ConceptReviewed.model_validate(ev.payload)
        # Every review is kept; `folded` says whether it counted (a human who is not the writer
        # of an agent-written definition, for a known concept).
        folded = p.channel is not Channel.MCP and _human_not_writer(conn, ev, p.concept_id)
        conn.execute(
            sqlite_insert(t.concept_reviews)
            .values(
                event_id=ev.id,
                concept_id=p.concept_id,
                definition=p.definition,
                state=p.state,
                note=p.note,
                reviewer_user=ev.actor.user,
                self_reviewed=int(p.self_reviewed),
                channel=p.channel.value,
                folded=int(folded),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        if folded:
            _refresh_concepts(conn, t, [p.concept_id])

    return reviewed


def _link_proposed(t: IntuitionTables) -> Handler:
    def proposed(conn: Connection, ev: Event) -> None:
        p = ConceptLinkProposed.model_validate(ev.payload)
        q = p.quote
        inserted = conn.execute(
            sqlite_insert(t.concept_uses)
            .values(
                link_id=p.link_id,
                from_node=p.from_node,
                from_kind=p.from_kind,
                concept_id=p.concept_id,
                basis_kind=p.basis_kind,
                basis_work=None if q is None else q.work_id,
                basis_conversion=None if q is None else q.conversion_id,
                basis_document=None if q is None else q.document_id,
                basis_anchor=None if q is None else q.anchor,
                basis_quote=None if q is None else q.quote,
                reference=p.reference,
                cited_work=p.cited_work,
                basis_digest=p.basis_digest,
                proposed_status=p.status,
                status=p.status,
                status_reason=p.status_reason,
                note=p.note,
                proposer_kind=ev.actor.kind,
                proposer_session=ev.actor.session,
                event_id=ev.id,
            )
            .on_conflict_do_nothing(index_elements=["link_id"])
        )
        if inserted.rowcount:
            ids = [p.concept_id] + ([p.from_node] if p.from_kind == "concept" else [])
            _refresh_concepts(conn, t, ids)

    return proposed


def _link_decided(t: IntuitionTables) -> Handler:
    def decided(conn: Connection, ev: Event) -> None:
        p = ConceptLinkDecided.model_validate(ev.payload)
        if ev.actor.kind != "human" or p.channel is Channel.MCP:
            return
        row = conn.execute(
            text(
                "SELECT concept_id, from_node, from_kind, proposer_kind, proposer_session "
                "FROM concept_uses WHERE link_id = :l"
            ),
            {"l": p.link_id},
        ).first()
        if row is None:
            return
        if row[3] == "agent" and row[4] == ev.actor.session:
            return  # the proposing session never decides its own link, relayed or not
        conn.execute(
            update(t.concept_uses)
            .where(t.concept_uses.c.link_id == p.link_id)
            .values(
                status="confirmed" if p.decision == "confirm" else "rejected",
                decision=p.decision,
                decided_by=ev.actor.user,
                decision_event=ev.id,
            )
        )
        ids = [str(row[0])] + ([str(row[1])] if row[2] == "concept" else [])
        _refresh_concepts(conn, t, ids)

    return decided


def _merged(t: IntuitionTables) -> Handler:
    def merged(conn: Connection, ev: Event) -> None:
        p = ConceptMerged.model_validate(ev.payload)
        if ev.actor.kind != "human" or p.into == p.from_concept:
            return
        known = conn.execute(
            text("SELECT COUNT(*) FROM concepts WHERE concept_id IN (:a, :b)"),
            {"a": p.into, "b": p.from_concept},
        ).scalar_one()
        active = conn.execute(
            text("SELECT 1 FROM concept_merges WHERE from_concept = :f AND active = 1"),
            {"f": p.from_concept},
        ).first()
        if known != 2 or active is not None:
            return
        conn.execute(
            sqlite_insert(t.concept_merges)
            .values(
                from_concept=p.from_concept,
                into_concept=p.into,
                active=1,
                merge_event=ev.id,
                unmerge_event=None,
            )
            .on_conflict_do_update(
                index_elements=["from_concept"],
                set_={
                    "into_concept": p.into,
                    "active": 1,
                    "merge_event": ev.id,
                    "unmerge_event": None,
                },
            )
        )
        _refresh_concepts(conn, t, [p.into, p.from_concept])

    return merged


def _unmerged(t: IntuitionTables) -> Handler:
    def unmerged(conn: Connection, ev: Event) -> None:
        p = ConceptUnmerged.model_validate(ev.payload)
        if ev.actor.kind != "human":
            return
        changed = conn.execute(
            update(t.concept_merges)
            .where(
                t.concept_merges.c.from_concept == p.from_concept,
                t.concept_merges.c.into_concept == p.into,
                t.concept_merges.c.active == 1,
            )
            .values(active=0, unmerge_event=ev.id)
        ).rowcount
        if changed:
            _refresh_concepts(conn, t, [p.into, p.from_concept])

    return unmerged


def _refresh_concepts(conn: Connection, t: IntuitionTables, concept_ids: Sequence[str]) -> None:
    """Recompute, from the concept tables only, the source state, review state and merge of each
    concept, its `layer_nodes` row and every `uses` row of `layer_edges` that touches it
    (rulings B1, B2, B9). The result depends on the tables' current content and on nothing else,
    so a merge followed by its reversal leaves the rows it found."""
    ids = sorted(set(concept_ids))
    for cid in ids:
        row = conn.execute(
            text(
                "SELECT definition_event, source_digest, event_id FROM concepts "
                "WHERE concept_id = :c"
            ),
            {"c": cid},
        ).first()
        if row is None:
            continue
        merged_into = conn.execute(
            text("SELECT into_concept FROM concept_merges WHERE from_concept = :c AND active = 1"),
            {"c": cid},
        ).scalar()
        source_state = "none"
        if row[1] is not None:
            decision = conn.execute(
                text(
                    "SELECT decision FROM concept_source_decisions WHERE concept_id = :c "
                    "AND source_digest = :d ORDER BY event_id DESC LIMIT 1"
                ),
                {"c": cid, "d": row[1]},
            ).scalar()
            source_state = (
                "proposed"
                if decision is None
                else ("approved" if decision == "approve" else "rejected")
            )
        review = conn.execute(
            text(
                "SELECT state, self_reviewed FROM concept_reviews WHERE concept_id = :c "
                "AND definition = :d AND folded = 1 ORDER BY event_id DESC LIMIT 1"
            ),
            {"c": cid, "d": row[0]},
        ).first()
        state = ConceptState.UNREVIEWED.value if review is None else str(review[0])
        if merged_into is not None:
            state = ConceptState.MERGED.value
        conn.execute(
            update(t.concepts)
            .where(t.concepts.c.concept_id == cid)
            .values(
                source_state=source_state,
                review_state=state,
                self_reviewed=0 if review is None else int(review[1]),
                merged_into=merged_into,
            )
        )
        conn.execute(
            sqlite_insert(t.layer_nodes)
            .values(
                {
                    "node_id": cid,
                    "node_type": "concept",
                    "class": LAYER_CLASS,
                    "review_state": state,
                    "event_id": row[2],
                }
            )
            .on_conflict_do_update(index_elements=["node_id"], set_={"review_state": state})
        )
    if not ids:
        return
    links = conn.execute(
        text(
            "SELECT u.link_id, u.status, u.event_id, "
            "COALESCE(f.merged_into, u.from_node), COALESCE(c.merged_into, u.concept_id) "
            "FROM concept_uses u LEFT JOIN concepts c ON c.concept_id = u.concept_id "
            "LEFT JOIN concepts f ON f.concept_id = u.from_node AND u.from_kind = 'concept' "
            "WHERE u.concept_id IN (SELECT value FROM json_each(:ids)) "
            "OR (u.from_kind = 'concept' AND u.from_node IN (SELECT value FROM json_each(:ids)))"
        ),
        {"ids": json.dumps(ids)},
    ).all()
    for link_id, status, event_id, source, target in links:
        conn.execute(
            sqlite_insert(t.layer_edges)
            .values(
                {
                    "edge_id": "uses:" + link_id,
                    "edge_type": "uses",
                    "source": source,
                    "target": target,
                    "class": LAYER_CLASS,
                    "review_state": status,
                    "basis": link_id,
                    "event_id": event_id,
                }
            )
            .on_conflict_do_update(
                index_elements=["edge_id"],
                set_={"source": source, "target": target, "review_state": status},
            )
        )
