"""Projection of the lineage graph: papers, ideas and their edges (slice 3b, plan G2-D).

`graph_edges` has one row per `cites` edge (id `cit:<rex_id>:<ordinal>`, one per resolved or
confirmed G1 link) and one per relation (id = `relation_id`). It stores event-derived facts only:
`base_status` (`stated` or `confirmed` for `cites`; the proposal status for a relation), `decision`
(the latest binding decision of the link or relation), `live` (the G1 extraction is current; the
relation is not superseded). Staleness, corpus membership and idea merges are overlays computed on
read; they depend on state that changes without a graph event.

The handlers run after the G1 and G2-C handlers of the same event (`chain`) and copy from the
tables those just folded, so decision precedence is decided in one place. They are total and
deterministic: an upsert of an id sets the row to what the source tables say, never appends.
`graph_nodes` has a row for every work that is the source or target of an edge or a member of an
idea, and for every idea. Indexes on `(source, edge_type)`, `(target, edge_type)` and `(edge_type)`
serve the level-by-level traversals.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, text
from sqlalchemy.engine import Connection

from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.lineage import IdeaProposed, RelationDecided, RelationProposed
from factory.model.references import (
    ReferenceReResolved,
    ReferenceResolutionDecided,
    ReferenceResolved,
)

PAPER = "paper"
IDEA = "idea"
IDEA_PREFIX = "ida_"


@dataclass(frozen=True)
class GraphTables:
    nodes: Table
    edges: Table


def graph_tables(metadata: MetaData) -> GraphTables:
    nodes = Table(
        "graph_nodes",
        metadata,
        Column("node_id", String, primary_key=True),
        Column("node_type", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_graph_nodes_type", "node_type"),
    )
    edges = Table(
        "graph_edges",
        metadata,
        Column("edge_id", String, primary_key=True),
        Column("edge_type", String, nullable=False),
        Column("source", String, nullable=False),
        Column("target", String, nullable=False),
        Column("base_status", String, nullable=False),
        Column("basis", String),
        Column("reference_extraction_id", String),
        Column("ordinal", Integer),
        Column("live", Integer, nullable=False),
        Column("decision", String),
        Column("flags", String, nullable=False),
        Column("event_id", String, nullable=False),
        Index("ix_graph_edges_source_type", "source", "edge_type"),
        Index("ix_graph_edges_target_type", "target", "edge_type"),
        Index("ix_graph_edges_type", "edge_type"),
    )
    return GraphTables(nodes, edges)


def graph_handlers() -> dict[str, Handler]:
    """Handlers to chain after the G1 and G2-C handlers of the same event types."""
    return {
        "reference.extracted": _extracted(),
        "reference.resolved": _resolved(),
        "reference.re_resolved": _re_resolved(),
        "reference.resolution_decided": _decided(),
        "relation.proposed": _relation_proposed(),
        "relation.decided": _relation_decided(),
        "idea.proposed": _idea_proposed(),
    }


def _node(conn: Connection, node_id: str, node_type: str, event_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:n, :t, :e) "
            "ON CONFLICT (node_id) DO NOTHING"
        ),
        {"n": node_id, "t": node_type, "e": event_id},
    )


def _kind(node_id: str) -> str:
    return IDEA if node_id.startswith(IDEA_PREFIX) else PAPER


_UPSERT = text(
    "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, basis, "
    "reference_extraction_id, ordinal, live, decision, flags, event_id) "
    "VALUES (:id, :type, :source, :target, :status, :basis, :rex, :ordinal, :live, :decision, "
    ":flags, :event) "
    "ON CONFLICT (edge_id) DO UPDATE SET edge_type = :type, source = :source, target = :target, "
    "base_status = :status, basis = :basis, reference_extraction_id = :rex, ordinal = :ordinal, "
    "live = :live, decision = :decision, flags = :flags, event_id = :event"
)


def _sync_link(conn: Connection, extraction_id: str, ordinal: int, event_id: str) -> None:
    """Make the `cites` edge of one G1 link what the link table says now."""
    row = conn.execute(
        text(
            "SELECT l.state, l.work_id, l.confidence, l.base_state, l.base_work_id, l.decision, "
            "x.work_id, x.live FROM reference_links l "
            "JOIN reference_extractions x ON x.extraction_id = l.extraction_id "
            "WHERE l.extraction_id = :x AND l.ordinal = :o"
        ),
        {"x": extraction_id, "o": ordinal},
    ).first()
    if row is None:
        return
    state, work_id, confidence, base_state, base_work, decision, source, live = row
    target = work_id if state == "resolved" else base_work if base_state == "resolved" else None
    edge_id = f"cit:{extraction_id}:{ordinal}"
    if target is None:
        conn.execute(text("DELETE FROM graph_edges WHERE edge_id = :i"), {"i": edge_id})
        return
    conn.execute(
        _UPSERT,
        {
            "id": edge_id,
            "type": "cites",
            "source": source,
            "target": target,
            "status": "confirmed" if confidence == "confirmed" else "stated",
            "basis": f"{extraction_id}:{ordinal}",
            "rex": extraction_id,
            "ordinal": ordinal,
            "live": int(live),
            "decision": decision,
            "flags": "[]",
            "event": event_id,
        },
    )
    _node(conn, str(source), PAPER, event_id)
    _node(conn, str(target), PAPER, event_id)


def _extracted() -> Handler:
    def extracted(conn: Connection, event: Event) -> None:
        conn.execute(
            text(
                "UPDATE graph_edges SET live = COALESCE("
                "(SELECT x.live FROM reference_extractions x "
                "WHERE x.extraction_id = graph_edges.reference_extraction_id), live) "
                "WHERE edge_type = 'cites' AND source = :w"
            ),
            {"w": str(event.payload["work_id"])},
        )

    return extracted


def _resolved() -> Handler:
    def resolved(conn: Connection, event: Event) -> None:
        p = ReferenceResolved.model_validate(event.payload)
        ordinals = sorted({r.ordinal for r in p.resolutions} | {c.ordinal for c in p.carried})
        for ordinal in ordinals:
            _sync_link(conn, p.extraction_id, ordinal, event.id)

    return resolved


def _re_resolved() -> Handler:
    def re_resolved(conn: Connection, event: Event) -> None:
        # Only the links this event changed: a refused event leaves every edge as it was.
        p = ReferenceReResolved.model_validate(event.payload)
        rows = conn.execute(
            text("SELECT ordinal FROM reference_links WHERE extraction_id = :x AND event_id = :e"),
            {"x": p.extraction_id, "e": event.id},
        ).all()
        for row in rows:
            _sync_link(conn, p.extraction_id, int(row[0]), event.id)

    return re_resolved


def _decided() -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = ReferenceResolutionDecided.model_validate(event.payload)
        _sync_link(conn, p.extraction_id, p.ordinal, event.id)

    return decided


def _sync_relation(conn: Connection, relation_id: str) -> None:
    row = conn.execute(
        text(
            "SELECT edge_type, source_work, target, status, basis_item, reference_extraction_id, "
            "cited_entry, superseded_by, decision, flags, event_id FROM relations "
            "WHERE relation_id = :r"
        ),
        {"r": relation_id},
    ).first()
    if row is None:
        return
    edge_type, source, target, status, basis, rex, entry, superseded, decision, flags, event = row
    conn.execute(
        _UPSERT,
        {
            "id": relation_id,
            "type": edge_type,
            "source": source,
            "target": target,
            "status": status,
            "basis": basis,
            "rex": rex,
            "ordinal": entry,
            "live": 0 if superseded is not None else 1,
            "decision": decision,
            "flags": flags,
            "event": event,
        },
    )
    _node(conn, str(source), PAPER, str(event))
    _node(conn, str(target), _kind(str(target)), str(event))


def _relation_proposed() -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = RelationProposed.model_validate(event.payload)
        _sync_relation(conn, p.relation_id)
        if p.supersedes is not None:
            _sync_relation(conn, p.supersedes)

    return proposed


def _relation_decided() -> Handler:
    def decided(conn: Connection, event: Event) -> None:
        p = RelationDecided.model_validate(event.payload)
        _sync_relation(conn, p.relation_id)

    return decided


def _idea_proposed() -> Handler:
    def proposed(conn: Connection, event: Event) -> None:
        p = IdeaProposed.model_validate(event.payload)
        won = conn.execute(
            text("SELECT 1 FROM ideas WHERE idea_id = :i AND event_id = :e"),
            {"i": p.idea_id, "e": event.id},
        ).first()
        if won is None:
            return
        _node(conn, p.idea_id, IDEA, event.id)
        for work in p.members:
            _node(conn, work, PAPER, event.id)

    return proposed
