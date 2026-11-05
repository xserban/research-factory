"""Pure value types of the lineage graph view (slice 3b, plan G2-D).

A `Graph` is a materialised subgraph (a query result, an export part or a test fixture), never the
whole projection (ruling 10). `Neighbours` is the one lookup the traversals in `lineage.paths` use:
the filtered edges of one node in one direction. `graph_neighbours` adapts an in-memory `Graph`;
`factory.services.lineage.index_neighbours` is the indexed equivalent, and the two agree on the
same data.

Invariants: a filter never admits `rejected` edges; the default filter shows `stated` and
`confirmed` edges and confirmed ideas; `derived` idea edges are shown exactly when ideas are.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from factory.model.lineage import DEFAULT_STATUSES, EdgeStatus, EdgeType

DERIVED: Literal["derived"] = "derived"
Direction = Literal["out", "in"]
ALL_TYPES: tuple[EdgeType, ...] = (EdgeType.CITES, EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON)


@dataclass(frozen=True)
class GraphFilter:
    """Which edges and ideas a view shows (spec ruling 14)."""

    include_inferred: bool = False
    include_stale: bool = False
    edge_types: tuple[EdgeType, ...] = ALL_TYPES
    include_ideas: bool = True

    def statuses(self) -> frozenset[EdgeStatus]:
        shown = set(DEFAULT_STATUSES)
        if self.include_inferred:
            shown.add(EdgeStatus.INFERRED)
        if self.include_stale:
            shown.add(EdgeStatus.STALE)
        return frozenset(shown)

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "include_inferred": self.include_inferred,
            "include_stale": self.include_stale,
            "edge_types": [t.value for t in sorted(self.edge_types, key=lambda t: t.value)],
            "include_ideas": self.include_ideas,
            "statuses": [s.value for s in sorted(self.statuses(), key=lambda s: s.value)],
        }


DEFAULT_FILTER = GraphFilter()


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: Literal["paper", "idea"]
    scope: Literal["corpus", "external"] | None
    title: str | None
    name: str | None
    members: tuple[str, ...]


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    edge_type: EdgeType
    source: str
    target: str
    status: EdgeStatus | Literal["derived"]
    basis: str | None
    flags: tuple[str, ...]
    derived: bool

    def sort_key(self) -> tuple[str, str, str, str]:
        """The export order of ruling 8."""
        return (self.source, self.edge_type.value, self.target, self.edge_id)


@dataclass(frozen=True)
class Graph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    filter: GraphFilter

    def node(self, node_id: str) -> GraphNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None


Neighbours = Callable[[str, Direction, frozenset[EdgeType]], Sequence[GraphEdge]]
"""The filtered edges of one node in one direction, sorted by `(other end, edge_type, edge_id)`."""


def shown(edge: GraphEdge, flt: GraphFilter) -> bool:
    """Whether `flt` admits `edge`."""
    if edge.edge_type not in flt.edge_types:
        return False
    if edge.status == DERIVED:
        return flt.include_ideas
    return edge.status in flt.statuses()


def graph_neighbours(graph: Graph) -> Neighbours:
    """The in-memory `Neighbours` of `graph`, applying its filter."""
    by_end: dict[tuple[str, Direction], list[GraphEdge]] = {}
    for edge in graph.edges:
        if not shown(edge, graph.filter):
            continue
        by_end.setdefault((edge.source, "out"), []).append(edge)
        by_end.setdefault((edge.target, "in"), []).append(edge)

    def neighbours(node: str, direction: Direction, types: frozenset[EdgeType]) -> list[GraphEdge]:
        edges = [e for e in by_end.get((node, direction), []) if e.edge_type in types]
        return sorted(
            edges,
            key=lambda e: (
                e.target if direction == "out" else e.source,
                e.edge_type.value,
                e.edge_id,
            ),
        )

    return neighbours


def load_fixture(path: Path | str, flt: GraphFilter = DEFAULT_FILTER) -> Graph:
    """Load a constructed graph from JSON `{"nodes": [...], "edges": [...]}` and apply `flt`.

    A node is `{"id", "type"}` plus `scope`/`title` for papers or `name`/`members`/`state`
    (`proposed|confirmed`) for ideas; an edge is `{"id", "type", "source", "target", "status"}`
    plus optional `basis`, `flags`. A `derived` edge has status `derived`. Ideas that `flt` hides
    are dropped with the edges that touch them."""
    doc = json.loads(Path(path).read_text())
    nodes: list[GraphNode] = []
    hidden: set[str] = set()
    for n in doc["nodes"]:
        if n["type"] == "idea":
            state = n.get("state", "confirmed")
            if not flt.include_ideas or (state != "confirmed" and not flt.include_inferred):
                hidden.add(n["id"])
                continue
        nodes.append(
            GraphNode(
                node_id=n["id"],
                node_type=n["type"],
                scope=n.get("scope"),
                title=n.get("title"),
                name=n.get("name"),
                members=tuple(n.get("members", ())),
            )
        )
    edges = [
        GraphEdge(
            edge_id=e["id"],
            edge_type=EdgeType(e["type"]),
            source=e["source"],
            target=e["target"],
            status=e["status"] if e["status"] == DERIVED else EdgeStatus(e["status"]),
            basis=e.get("basis"),
            flags=tuple(e.get("flags", ())),
            derived=e["status"] == DERIVED,
        )
        for e in doc["edges"]
        if e["source"] not in hidden and e["target"] not in hidden
    ]
    edges = [e for e in edges if shown(e, flt)]
    return Graph(
        nodes=tuple(sorted(nodes, key=lambda n: n.node_id)),
        edges=tuple(sorted(edges, key=GraphEdge.sort_key)),
        filter=flt,
    )
