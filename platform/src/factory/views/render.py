"""Renderers of the views: onion (Markdown, Graphviz DOT; plan V-A, ruling 6) and the coverage,
timeline and horizon views (Markdown, CSV; plan V-B, task 5).

Invariants:
- Pure formatting of an `OnionView`: no count, status or order is computed here, so two renders
  of the same view are byte-identical.
- Every output names the filter, `as_of` and whether a ring was cut; a cut ring prints
  "showing N of M". Only listed nodes are drawn.
- The coverage, timeline and horizon renderers state the filter, `as_of`, the notices (among them
  the corpus horizon) and "counts are activity, not quality"; CSV is `csv`-module output with
  "\\n" line ends, one header row, nothing but counts, ids and the values of one group.
- Layout is Graphviz's job (slice-3b ruling 4): the DOT joins every listed node to one invisible
  `focus` node by an edge whose `len` is the ring plus one, and `twopi` places them in rings.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence

from factory.model.views import (
    CoverageCell,
    CoverageView,
    HorizonView,
    OnionNode,
    OnionView,
    Ring,
    TimelineView,
    ViewMeta,
)

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


# --- Coverage, timeline and horizon (plan V-B) ---

ACTIVITY_NOTE = (
    "Counts are activity, not quality: they say what the corpus holds, not what is good."
)


def _header(title: str, meta: ViewMeta) -> list[str]:
    lines = [
        f"# {title}",
        "",
        f"project: {meta.project}",
        f"as_of: {meta.as_of}",
        f"filter: {json.dumps(meta.filter, sort_keys=True, separators=(',', ':'))}",
        f"truncated: {'yes' if meta.truncated else 'no'}",
        "",
        ACTIVITY_NOTE,
        "",
    ]
    if meta.notices:
        lines.append("Notices:")
        lines += [f"- {n.code}: {n.text}" for n in meta.notices]
        lines.append("")
    return lines


def _table(head: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    out.append("")
    return out


def _counts(cell: CoverageCell | None) -> str:
    return "" if cell is None else f"{cell.independent}/{cell.copied}/{cell.works}"


def _csv(head: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(head)
    writer.writerows(rows)
    return buffer.getvalue()


def _matrix(
    title: str,
    rows: Sequence[str],
    groups: Sequence[str],
    cells: dict[str, dict[str, CoverageCell]],
) -> list[str]:
    lines = [f"## {title}", "", "Cells: independent / copied / works.", ""]
    lines += _table(
        ["", *groups],
        [[name, *(_counts(cells.get(name, {}).get(g)) for g in groups)] for name in rows],
    )
    return lines


def coverage_markdown(view: CoverageView) -> str:
    lines = _header("Coverage map", view.meta)
    shown = [g.group_id for g in view.groups]
    if view.meta.truncated:
        lines += [
            f"List cut: showing {len(view.groups)} of {view.total_groups} groups, "
            f"{len(view.methods)} of {view.total_methods} methods, "
            f"{len(view.ideas)} of {view.total_ideas} ideas.",
            "",
        ]
    lines += ["## Groups", ""]
    lines += _table(
        ["group", "key", "works", "rows", "independent", "copied"],
        [
            [
                g.group_id,
                "; ".join(f"{k}={v}" for k, v in g.key),
                str(g.works),
                str(g.rows),
                str(g.independent),
                str(g.copied),
            ]
            for g in view.groups
        ],
    )
    lines += _matrix("Methods by group", view.methods, shown, view.cells)
    if view.ideas:
        lines += _matrix("Confirmed ideas by group", view.ideas, shown, view.idea_cells)
    return "\n".join(lines).rstrip("\n") + "\n"


def coverage_csv(view: CoverageView) -> str:
    rows: list[list[str]] = []
    for matrix, names, cells in (
        ("method", view.methods, view.cells),
        ("idea", view.ideas, view.idea_cells),
    ):
        for name in names:
            for gid, c in sorted(cells.get(name, {}).items()):
                rows.append([matrix, name, gid, str(c.independent), str(c.copied), str(c.works)])
    return _csv(["matrix", "row", "group_id", "independent", "copied", "works"], rows)


def timeline_markdown(view: TimelineView) -> str:
    lines = _header(f"Timeline of {view.group_id}", view.meta)
    lines += [
        f"group: {view.group_id}",
        "key: " + "; ".join(f"{k}={v}" for k, v in view.key),
        f"direction: {view.direction}"
        + (
            "" if view.higher_is_better is None else f" (higher is better: {view.higher_is_better})"
        ),
        "",
    ]
    for label, unit in view.units.items():
        lines += [f"## {label}", "", "Records:", ""]
        lines += _table(
            ["year", "work", "value", "trace id"],
            [[str(r.year), r.work_id, r.value, r.trace_id] for r in unit.records],
        )
        if unit.frontiers:
            lines += ["Frontiers by year (trace ids):", ""]
            lines += _table(
                ["year", "axis", "frontier"],
                [
                    [str(year), axis, ", ".join(ids)]
                    for year, axes in sorted(unit.frontiers.items())
                    for axis, ids in sorted(axes.items())
                ],
            )
    if view.undated:
        lines += ["Undated works (no publication date; never dated by a guess):", ""]
        lines += [f"- {w}" for w in view.undated] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def timeline_csv(view: TimelineView) -> str:
    rows: list[list[str]] = []
    for label, unit in view.units.items():
        rows += [
            [label, "record", str(r.year), "", r.trace_id, r.work_id, r.value] for r in unit.records
        ]
        rows += [
            [label, "frontier", str(year), axis, trace_id, "", ""]
            for year, axes in sorted(unit.frontiers.items())
            for axis, ids in sorted(axes.items())
            for trace_id in ids
        ]
    return _csv(["unit", "kind", "year", "axis", "trace_id", "work_id", "value"], rows)


def horizon_markdown(view: HorizonView) -> str:
    lines = _header("Horizon activity", view.meta)
    if view.horizon:
        lines += ["## Latest search or watch run per source", ""]
        lines += _table(["source", "date"], [[s, d] for s, d in view.horizon.items()])
    years = [str(y) for y in view.years]
    if view.meta.truncated:
        lines += [f"List cut: {len(view.idea_members)} of {view.total_ideas} ideas listed.", ""]
    lines += ["## Included works per idea and year", ""]
    lines += _table(
        ["idea", *years],
        [
            [idea, *(str(per.get(y, "")) for y in view.years)]
            for idea, per in view.idea_members.items()
        ],
    )
    lines += ["## New ideas (by origin year)", ""]
    lines += _table(["year", "ideas"], [[str(y), ", ".join(i)] for y, i in view.new_ideas.items()])
    lines += ["## New stated or confirmed lineage edges (by citing work year)", ""]
    lines += _table(["year", "edges"], [[str(y), str(n)] for y, n in view.new_edges.items()])
    lines += ["## Records per group and year", ""]
    lines += _table(
        ["group", *years],
        [[g, *(str(per.get(y, "")) for y in view.years)] for g, per in view.group_records.items()],
    )
    lines += ["## Undated items", ""]
    lines += _table(["series", "count"], [[k, str(v)] for k, v in sorted(view.undated.items())])
    return "\n".join(lines).rstrip("\n") + "\n"


def horizon_csv(view: HorizonView) -> str:
    rows: list[list[str]] = []
    for idea, per in view.idea_members.items():
        rows += [["idea_members", idea, str(y), str(n)] for y, n in sorted(per.items())]
    for year, ideas in sorted(view.new_ideas.items()):
        rows += [["new_ideas", idea, str(year), "1"] for idea in ideas]
    rows += [["new_edges", "", str(y), str(n)] for y, n in sorted(view.new_edges.items())]
    for group, per in view.group_records.items():
        rows += [["group_records", group, str(y), str(n)] for y, n in sorted(per.items())]
    rows += [["undated", k, "", str(v)] for k, v in sorted(view.undated.items())]
    return _csv(["series", "subject", "year", "value"], rows)
