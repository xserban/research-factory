"""Serialisation of a lineage graph view as JSON or Graphviz DOT (slice 3b, plan G2-D, ruling 8).

Pure and deterministic: nodes are written by id and edges by `(source, edge_type, target,
edge_id)`, so the same view is byte-identical across rebuilds. `iter_json` and `iter_dot` produce
the document in chunks from iterables consumed once, so a whole view streams without being held;
`to_json` and `to_dot` are their concatenation for a materialised `Graph`. No quotes, notes or
entry text appear: an edge carries ids, a status and a basis id, a node an id, a type, a scope
and (papers) its bibliographic title or (ideas) its name and members.

DOT: papers are ellipses, ideas boxes; `stated` solid, `confirmed` solid labelled, `inferred`
dashed labelled, `stale` dotted labelled, `cites` gray, `derived` bold labelled. No layout engine.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

from pydantic import JsonValue

from factory.lineage.graph import DERIVED, Graph, GraphEdge, GraphFilter, GraphNode
from factory.model.lineage import EdgeStatus, EdgeType


def _dumps(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _node_json(n: GraphNode) -> JsonValue:
    if n.node_type == "paper":
        return {"id": n.node_id, "scope": n.scope, "title": n.title, "type": "paper"}
    return {"id": n.node_id, "members": list(n.members), "name": n.name, "type": "idea"}


def _status(e: GraphEdge) -> str:
    return DERIVED if e.status == DERIVED else EdgeStatus(e.status).value


def _edge_json(e: GraphEdge) -> JsonValue:
    return {
        "basis": e.basis,
        "derived": e.derived,
        "flags": list(e.flags),
        "id": e.edge_id,
        "source": e.source,
        "status": _status(e),
        "target": e.target,
        "type": e.edge_type.value,
    }


def iter_json(
    flt: GraphFilter, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]
) -> Iterator[str]:
    """`{"edges": [...], "filter": {...}, "nodes": [...]}` with sorted keys, compact, ending in a
    newline. `edges` is consumed before `nodes` (the key order), each once."""
    yield '{"edges":['
    for i, edge in enumerate(edges):
        yield ("," if i else "") + _dumps(_edge_json(edge))
    yield '],"filter":' + _dumps(flt.as_dict()) + ',"nodes":['
    for i, node in enumerate(nodes):
        yield ("," if i else "") + _dumps(_node_json(node))
    yield "]}\n"


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _attrs(e: GraphEdge) -> str:
    status = _status(e)
    if status == DERIVED:
        attrs = ["style=bold", 'label="derived"']
    elif status == EdgeStatus.INFERRED.value:
        attrs = ["style=dashed", 'label="inferred"']
    elif status == EdgeStatus.STALE.value:
        attrs = ["style=dotted", 'label="stale"']
    elif status == EdgeStatus.CONFIRMED.value:
        attrs = ["style=solid", 'label="confirmed"']
    else:
        attrs = ["style=solid"]
    if e.edge_type is EdgeType.CITES:
        attrs.append("color=gray")
    return ", ".join(attrs)


def iter_dot(
    flt: GraphFilter, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]
) -> Iterator[str]:
    """`digraph lineage` with the filter in a comment; nodes, then edges, each once."""
    yield "digraph lineage {\n"
    yield "  // filter: " + _dumps(flt.as_dict()).replace("\n", " ") + "\n"
    for n in nodes:
        if n.node_type == "paper":
            yield f"  {_quote(n.node_id)} [shape=ellipse, label={_quote(n.node_id)}];\n"
        else:
            yield f"  {_quote(n.node_id)} [shape=box, label={_quote(n.name or n.node_id)}];\n"
    for e in edges:
        yield f"  {_quote(e.source)} -> {_quote(e.target)} [{_attrs(e)}];\n"
    yield "}\n"


def _ordered(graph: Graph) -> tuple[list[GraphNode], list[GraphEdge]]:
    return (
        sorted(graph.nodes, key=lambda n: n.node_id),
        sorted(graph.edges, key=GraphEdge.sort_key),
    )


def to_json(graph: Graph) -> str:
    nodes, edges = _ordered(graph)
    return "".join(iter_json(graph.filter, nodes, edges))


def to_dot(graph: Graph) -> str:
    nodes, edges = _ordered(graph)
    return "".join(iter_dot(graph.filter, nodes, edges))


def subgraph(graph: Graph, nodes: Iterable[str], edges: Iterable[str]) -> Graph:
    """The part of `graph` with the named nodes and edges, same filter."""
    keep_nodes, keep_edges = set(nodes), set(edges)
    return Graph(
        tuple(n for n in graph.nodes if n.node_id in keep_nodes),
        tuple(e for e in graph.edges if e.edge_id in keep_edges),
        graph.filter,
    )
