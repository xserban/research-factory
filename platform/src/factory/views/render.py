"""Renderers of the onion view: Markdown and Graphviz DOT (slice 7b, plan V-A, ruling 6).

Invariants:
- Pure formatting of an `OnionView`: no count, status or order is computed here, so two renders
  of the same view are byte-identical.
- Every output names the filter, `as_of` and whether a ring was cut; a cut ring prints
  "showing N of M". Only listed nodes are drawn.
- Layout is Graphviz's job (slice-3b ruling 4): the DOT joins every listed node to one invisible
  `focus` node by an edge whose `len` is the ring plus one, and `twopi` places them in rings.
"""

from __future__ import annotations

import json

from factory.model.views import OnionNode, OnionView, Ring

DOT_STYLE = {
    "verified": "filled",
    "extracted": "solid",
    "screened": "dashed",
    "indexed": "dotted",
}
"""The node style of each processing depth."""


def _filter_text(view: OnionView) -> str:
    return json.dumps(view.meta.filter, sort_keys=True, separators=(",", ":"))


def _cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


def _row(node: OnionNode) -> str:
    year = "" if node.year is None else str(node.year)
    ideas = ", ".join(node.ideas)
    regions = ", ".join(node.regions)
    title = _cell(node.title)
    label = f"{title} ({node.work_id})" if title else node.work_id
    return f"| {label} | {year} | {node.depth} | {ideas} | {regions} |"


def _ring_block(ring: Ring) -> list[str]:
    lines = [f"## Ring {ring.distance} ({ring.total} works)", ""]
    depths = ", ".join(f"{name} {count}" for name, count in ring.by_depth.items())
    lines.append(f"By depth: {depths}.")
    if ring.truncated:
        lines.append(f"List cut: showing {len(ring.nodes)} of {ring.total}.")
    lines += ["", "| work | year | depth | ideas | regions |", "| --- | --- | --- | --- | --- |"]
    lines += [_row(node) for node in ring.nodes]
    lines.append("")
    return lines


def onion_markdown(view: OnionView) -> str:
    meta = view.meta
    lines = [
        "# Onion view",
        "",
        f"project: {meta.project}",
        f"as_of: {meta.as_of}",
        f"filter: {_filter_text(view)}",
        f"truncated: {'yes' if meta.truncated else 'no'}",
        "",
    ]
    if view.edges_considered:
        edges = ", ".join(f"{kind}: {n}" for kind, n in sorted(view.edges_considered.items()))
        lines += [f"Edges considered: {edges}.", ""]
    if meta.notices:
        lines.append("Notices:")
        lines += [f"- {n.code}: {n.text}" for n in meta.notices]
        lines.append("")
    for ring in view.rings:
        lines += _ring_block(ring)
    return "\n".join(lines).rstrip("\n") + "\n"


def _dot_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def onion_dot(view: OnionView) -> str:
    meta = view.meta
    lines = [
        f"// onion as_of={meta.as_of} truncated={'true' if meta.truncated else 'false'} "
        f"filter={_filter_text(view)}",
        "graph onion {",
        '  layout=twopi; root="focus";',
        '  "focus" [style=invis, label=""];',
    ]
    for ring in view.rings:
        for node in ring.nodes:
            ident = _dot_text(node.work_id)
            label = _dot_text(node.title or node.work_id)
            lines.append(f'  "{ident}" [label="{label}", style={DOT_STYLE[node.depth]}];')
            lines.append(f'  "focus" -- "{ident}" [len={ring.distance + 1}];')
    lines.append("}")
    return "\n".join(lines) + "\n"
