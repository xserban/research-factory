"""Rendering of the visible interpretation layer next to a lineage export (slice 3c, plan G3-C).

Pure and deterministic. The layer is a separate part of the output, never merged into the evidence
nodes and edges, and always announced by `LAYER_NOTICE`:

- JSON: `{"evidence": <the G2 export object>, "interpretation": {"edges", "hidden", "nodes"},
  "notice": LAYER_NOTICE}`, sorted keys, compact, one trailing newline (the format of
  `factory.lineage.export`, so the evidence part is that module's text unchanged).
- DOT: the G2 text with a first comment line `// LAYER_NOTICE` and, before its closing brace, a
  `subgraph cluster_interpretation` labelled `interpretation (not evidence)`; layer nodes and edges
  are dashed and every label ends in the item's `interpretation · <review state>`.

`iter_*` functions produce the layer part in chunks from iterables consumed once, so a whole-layer
export streams; `layer_json`, `layer_dot`, `with_layer_json` and `with_layer_dot` are their
materialised forms and give the same text.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

from pydantic import JsonValue

from factory.intuition.labels import layer_label
from factory.model.intuition import LayerEdge, LayerGraph, LayerHidden, LayerNode

__all__ = [
    "LAYER_NOTICE",
    "hidden_comment",
    "iter_layer_dot",
    "iter_layer_json",
    "layer_dot",
    "layer_json",
    "with_layer_dot",
    "with_layer_json",
]

LAYER_NOTICE = "interpretation layer: not evidence; every item carries its review state"
CLUSTER_LABEL = "interpretation (not evidence)"


def _dumps(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _node_json(n: LayerNode) -> JsonValue:
    return {
        "class": n.class_,
        "flags": list(n.flags),
        "id": n.node_id,
        "label": n.label,
        "name": n.name,
        "review_state": n.review_state,
        "type": n.node_type,
    }


def _edge_json(e: LayerEdge) -> JsonValue:
    return {
        "basis": e.basis,
        "class": e.class_,
        "id": e.edge_id,
        "label": e.label,
        "review_state": e.review_state,
        "source": e.source,
        "target": e.target,
        "type": e.edge_type,
    }


def _hidden_json(h: LayerHidden) -> JsonValue:
    return json.loads(h.model_dump_json())  # type: ignore[no-any-return]


def iter_layer_json(
    nodes: Iterable[LayerNode], edges: Iterable[LayerEdge], hidden: LayerHidden
) -> Iterator[str]:
    """`{"edges":[...],"hidden":{...},"nodes":[...]}`; edges are consumed before nodes."""
    yield '{"edges":['
    for i, edge in enumerate(edges):
        yield ("," if i else "") + _dumps(_edge_json(edge))
    yield '],"hidden":' + _dumps(_hidden_json(hidden)) + ',"nodes":['
    for i, node in enumerate(nodes):
        yield ("," if i else "") + _dumps(_node_json(node))
    yield "]}"


def layer_json(layer: LayerGraph) -> dict[str, JsonValue]:
    """The layer part of a JSON export, as a value."""
    return {
        "edges": [_edge_json(e) for e in layer.edges],
        "hidden": _hidden_json(layer.hidden),
        "nodes": [_node_json(n) for n in layer.nodes],
    }


def with_layer_json(evidence: dict[str, JsonValue], layer: LayerGraph) -> str:
    """The labelled export: the evidence object, the layer part and the notice."""
    whole: dict[str, JsonValue] = {
        "evidence": evidence,
        "interpretation": layer_json(layer),
        "notice": LAYER_NOTICE,
    }
    return _dumps(whole) + "\n"


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _node_dot(n: LayerNode) -> str:
    shown = f"{n.name or n.node_id} · {layer_label(n.review_state)}"
    return f"    {_quote(n.node_id)} [shape=note, style=dashed, label={_quote(shown)}];\n"


def _edge_dot(e: LayerEdge) -> str:
    shown = f"{e.edge_type} · {layer_label(e.review_state)}"
    return f"  {_quote(e.source)} -> {_quote(e.target)} [style=dashed, label={_quote(shown)}];\n"


def hidden_comment(h: LayerHidden) -> str:
    """The hidden counts as one DOT comment line (every view reports what it hides)."""
    i, c = h.interpretations, h.concepts
    return (
        f"// hidden: interpretations wrong {i.wrong}, superseded {i.superseded}; "
        f"concepts unapproved {c.unapproved}, wrong {c.wrong}, merged {c.merged}; "
        f"links inferred {c.links_inferred}, rejected {c.links_rejected}; "
        f"edges with a hidden endpoint {h.endpoint_hidden}\n"
    )


def iter_layer_dot(
    nodes: Iterable[LayerNode], edges: Iterable[LayerEdge], hidden: LayerHidden
) -> Iterator[str]:
    """The hidden-count comment, the cluster of layer nodes, then the layer edges (dashed,
    cross-layer ones included)."""
    yield hidden_comment(hidden)
    yield "  subgraph cluster_interpretation {\n"
    yield f"    label={_quote(CLUSTER_LABEL)};\n    style=dashed;\n"
    for n in nodes:
        yield _node_dot(n)
    yield "  }\n"
    for e in edges:
        yield _edge_dot(e)


def layer_dot(layer: LayerGraph) -> list[str]:
    """The lines of the cluster and the layer edges."""
    return list(iter_layer_dot(layer.nodes, layer.edges, layer.hidden))


def with_layer_dot(evidence_dot: str, layer: LayerGraph) -> str:
    """`evidence_dot` with the notice on top and the layer before its closing brace."""
    closing = "}\n"
    if not evidence_dot.endswith(closing):
        raise ValueError("not a DOT graph")
    return (
        f"// {LAYER_NOTICE}\n" + evidence_dot[: -len(closing)] + "".join(layer_dot(layer)) + closing
    )
