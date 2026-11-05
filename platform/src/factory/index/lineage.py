"""Projection of relations and ideas (slice 3b, plan G2-C).

`relations` keeps every proposal; a proposal that a later one supersedes gets `superseded_by`, so a
live relation has it NULL. `decision` is the latest human decision (confirm or reject) of the
relation; a superseding proposal starts without one. `ideas` is likewise kept with supersession and
the latest human decision; `merged_into` folds the latest merge or unmerge of the idea in event
order (NULL when it is not merged). `idea_members` has one row per member of each proposal and an
index on `work_id`, which the derived idea edges read. `idea_merges` keeps every merge and unmerge.

Only a decision, merge or unmerge whose actor is a human is folded (defence in depth: no service
writes one for another actor, R-51). Handlers are total: an event naming an unknown relation or
idea changes nothing, never raises. Proposals are first-write-wins per id.

Staleness is not stored: it depends on the extraction ledger and on G1 link liveness, which change
without a relation event, so services compute it on read.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, and_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.lineage import (
    IdeaDecided,
    IdeaMerged,
    IdeaProposed,
    IdeaUnmerged,
    RelationDecided,
    RelationProposed,
)

MERGED = "merged"
UNMERGED = "unmerged"


@dataclass(frozen=True)
class LineageTables:
    relations: Table
    ideas: Table
    members: Table
    merges: Table


def lineage_tables(metadata: MetaData) -> LineageTables:
    relations = Table(
        "relations",
        metadata,
        Column("relation_id", String, primary_key=True),
        Column("source_work", String, nullable=False),
        Column("target", String, nullable=False),
        Column("edge_type", String, nullable=False),
        Column("basis_item", String),
        Column("status", String, nullable=False),
        Column("status_reason", String),
        Column("resolved_target", String),
        Column("reference_extraction_id", String),
        Column("cited_entry", Integer),
        Column("flags", String, nullable=False),
        Column("note", String),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("decision", String),
        Column("decision_event_id", String),
        Column("event_id", String, nullable=False),
        Index("ix_relations_triple", "source_work", "target", "edge_type"),
        Index("ix_relations_basis", "basis_item"),
        Index("ix_relations_target", "target"),
    )
    ideas = Table(
        "ideas",
        metadata,
        Column("idea_id", String, primary_key=True),
        Column("name", String, nullable=False),
        Column("name_item", String, nullable=False),
        Column("origin", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("decision", String),
        Column("decision_event_id", String),
        Column("merged_into", String),
        Column("event_id", String, nullable=False),
        Index("ix_ideas_merged_into", "merged_into"),
    )
    members = Table(
        "idea_members",
        metadata,
        Column("idea_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Index("ix_idea_members_work", "work_id"),
    )
    merges = Table(
        "idea_merges",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("from_idea", String, nullable=False),
        Column("into_idea", String, nullable=False),
    )
    return LineageTables(relations, ideas, members, merges)


def lineage_handlers(t: LineageTables) -> dict[str, Handler]:
    return {
        "relation.proposed": _relation_proposed(t),
        "relation.decided": _relation_decided(t),
        "idea.proposed": _idea_proposed(t),
        "idea.decided": _idea_decided(t),
        "idea.merged": _merge_handler(t, MERGED),
        "idea.unmerged": _merge_handler(t, UNMERGED),
    }


def _relation_proposed(t: LineageTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = RelationProposed.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.relations)
            .values(
                relation_id=p.relation_id,
                source_work=p.source_work,
                target=p.target,
                edge_type=p.edge_type,
                basis_item=p.basis_item,
                status=p.status,
                status_reason=None if p.status_reason is None else p.status_reason.value,
                resolved_target=p.resolved_target,
                reference_extraction_id=p.reference_extraction_id,
                cited_entry=p.cited_entry,
                flags=canonical_json(list(p.flags)).decode(),
                note=p.note,
                supersedes=p.supersedes,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["relation_id"])
        )
        if inserted.rowcount and p.supersedes is not None:
            conn.execute(
                update(t.relations)
                .where(
                    and_(
                        t.relations.c.relation_id == p.supersedes,
                        t.relations.c.superseded_by.is_(None),
                    )
                )
                .values(superseded_by=p.relation_id)
            )

    return proposed


def _relation_decided(t: LineageTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = RelationDecided.model_validate(event.payload)
        conn.execute(
            update(t.relations)
            .where(t.relations.c.relation_id == p.relation_id)
            .values(decision=p.decision.value, decision_event_id=event.id)
        )

    return decided


def _idea_proposed(t: LineageTables) -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = IdeaProposed.model_validate(event.payload)
        inserted = conn.execute(
            sqlite_insert(t.ideas)
            .values(
                idea_id=p.idea_id,
                name=p.name,
                name_item=p.name_item,
                origin=p.origin,
                supersedes=p.supersedes,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["idea_id"])
        )
        if not inserted.rowcount:
            return
        for work in p.members:
            conn.execute(
                sqlite_insert(t.members)
                .values(idea_id=p.idea_id, work_id=work)
                .on_conflict_do_nothing(index_elements=["idea_id", "work_id"])
            )
        if p.supersedes is not None:
            conn.execute(
                update(t.ideas)
                .where(and_(t.ideas.c.idea_id == p.supersedes, t.ideas.c.superseded_by.is_(None)))
                .values(superseded_by=p.idea_id)
            )

    return proposed


def _idea_decided(t: LineageTables) -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = IdeaDecided.model_validate(event.payload)
        conn.execute(
            update(t.ideas)
            .where(t.ideas.c.idea_id == p.idea_id)
            .values(decision=p.decision.value, decision_event_id=event.id)
        )

    return decided


def _merge_handler(t: LineageTables, kind: str) -> Handler:
    def merged(conn: Connection, event: Event) -> None:
        if event.actor.kind != "human":
            return
        p = (IdeaMerged if kind == MERGED else IdeaUnmerged).model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.merges)
            .values(event_id=event.id, kind=kind, from_idea=p.from_idea, into_idea=p.into)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        conn.execute(
            update(t.ideas)
            .where(t.ideas.c.idea_id == p.from_idea)
            .values(merged_into=p.into if kind == MERGED else None)
        )

    return merged
