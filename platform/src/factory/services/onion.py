"""The onion view: rings of works around the included corpus (slice 7b, plan V-A, rulings 2-5).

Ring k holds the works at undirected hop distance k from the focus (by default the works
INCLUDED at the last declared stage) over the chosen edge types, in the default status filter
(`stated`, `confirmed`; `inferred` too with `include_inferred`). Idea nodes are not ring members.

Invariants:
- Read-only. The visited set is a connection-local TEMP table, dropped before the connection is
  returned; the index file is not written. Ring expansion reads only the edges incident to the
  current frontier; nothing loads the graph.
- Counts are complete: `total` and `by_depth` of a ring cover every member, whatever the node
  list shows. A node list is cut at `VIEW_MAX_NODES`, ordered by (depth rank descending, work
  id), and `truncated` says so.
- A work is never filtered or masked (decision 37.9); no output marks a work as a seed.
- Agent variant (`agent=True`): every source is read as an agent may read it. Depth leaves out the
  labelled-audit path (`services/depth.py`); the `regions` column leaves out a region that is
  withheld from agents (`region_withheld`) and says nothing of it, and its notice for "no region"
  reads the same whether or not a withheld region exists. The researcher's view is complete.
- A region is shown on a node only when it is a focus region whose latest version is reviewed
  (reconciliation of 2026-11-04: the overlay reads reviewed focus-region snapshots).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.lineage.graph import GraphFilter
from factory.model.lineage import EdgeType
from factory.model.regions import RegionKind
from factory.model.views import (
    OnionFilter,
    OnionNode,
    OnionView,
    ProcessingDepth,
    Ring,
    ViewNotice,
)
from factory.regions.rules import MemberType
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.depth import DEPTH_RANK, DepthIndex, depth_counts, depth_index
from factory.services.lineage import (
    RING_BATCH,
    confirmed_ideas_of,
    paper_nodes,
    ring_step,
)
from factory.services.references import included_works
from factory.services.regions import region_withheld, regions_of
from factory.services.views import view_meta

ONION_MAX_RING = 3
VIEW_MAX_NODES = 500
VIEW_VERSION = 1

_SEEN = "onion_seen"


DEFAULT_FILTER = OnionFilter()


def onion_view(
    project: Project, flt: OnionFilter = DEFAULT_FILTER, *, agent: bool = False
) -> OnionView:
    """Build the onion view. `agent` selects the agent variant of every source (see the module
    docstring); the MCP tool passes it, the CLI does not."""
    if flt.max_ring < 0:
        raise FactoryValidationError([ValidationIssue("max_ring", "must be 0 or more")])
    if not flt.edge_types:
        raise FactoryValidationError([ValidationIssue("edge_types", "name at least one type")])
    with entering():
        return _build(project, flt, agent)


def _build(project: Project, flt: OnionFilter, agent: bool) -> OnionView:
    notices: list[ViewNotice] = []
    max_ring = min(flt.max_ring, ONION_MAX_RING)
    if flt.max_ring > ONION_MAX_RING:
        notices.append(
            ViewNotice(
                code="ring-clamped",
                text=f"Requested {flt.max_ring} rings; the view shows at most {ONION_MAX_RING}.",
            )
        )
    graph_filter = GraphFilter(
        include_inferred=flt.include_inferred,
        edge_types=tuple(EdgeType(t) for t in flt.edge_types),
        include_ideas=False,
    )
    project.index.sync()
    focus = _focus(project, flt)
    depths = depth_index(project, agent=agent)
    considered: dict[EdgeType, set[str]] = {EdgeType(t): set() for t in flt.edge_types}
    rings: list[Ring] = []
    with project.index.connect() as conn:
        conn.execute(text(f"CREATE TEMP TABLE {_SEEN} (work_id TEXT PRIMARY KEY, ring INTEGER)"))
        try:
            _seed(conn, focus)
            for k in range(1, max_ring + 1):
                frontier = _members(conn, k - 1)
                step = ring_step(project, conn, frontier, graph_filter)
                for edge_id, kind in step.edges.items():
                    considered[kind].add(edge_id)
                conn.execute(
                    text(f"INSERT OR IGNORE INTO {_SEEN} (work_id, ring) VALUES (:w, :k)"),
                    [{"w": w, "k": k} for w in sorted(step.neighbours)],
                )
            for k in range(0, max_ring + 1):
                rings.append(_ring(project, conn, k, depths))
        finally:
            conn.execute(text(f"DROP TABLE IF EXISTS {_SEEN}"))
            conn.commit()
    rings = _with_regions(project, rings, agent)
    if not _any_visible_region(project, agent):
        notices.append(
            ViewNotice(
                code="regions-none",
                text="No reviewed focus region exists here; the regions column is empty.",
            )
        )
    filter_note: dict[str, JsonValue] = {
        "max_ring": max_ring,
        "edge_types": [str(t) for t in sorted(flt.edge_types)],
        "include_inferred": flt.include_inferred,
        "focus": None if flt.focus is None else [str(w) for w in sorted(set(flt.focus))],
        "statuses": [s.value for s in sorted(graph_filter.statuses(), key=lambda s: s.value)],
    }
    return OnionView(
        meta=view_meta(
            project,
            "onion",
            VIEW_VERSION,
            filter_note,
            truncated=any(r.truncated for r in rings),
            notices=notices,
        ),
        rings=rings,
        edges_considered={t.value: len(ids) for t, ids in sorted(considered.items())},
    )


def _focus(project: Project, flt: OnionFilter) -> list[str]:
    """The ring-0 works: `included_works`, or the named `focus`, every one a corpus work."""
    if flt.focus is None:
        return sorted(set(included_works(project)))
    named = sorted(set(flt.focus))
    with project.index.connect() as conn:
        nodes = paper_nodes(conn, named)
    bad = [w for w in named if w not in nodes or nodes[w].scope != "corpus"]
    if bad:
        raise FactoryValidationError(
            [ValidationIssue("focus", f"{w}: not a corpus work") for w in bad]
        )
    return named


def _seed(conn: Connection, focus: Sequence[str]) -> None:
    if focus:
        conn.execute(
            text(f"INSERT OR IGNORE INTO {_SEEN} (work_id, ring) VALUES (:w, 0)"),
            [{"w": w} for w in focus],
        )


def _members(conn: Connection, ring: int) -> list[str]:
    rows = conn.execute(
        text(f"SELECT work_id FROM {_SEEN} WHERE ring = :k ORDER BY work_id"), {"k": ring}
    )
    return [str(r[0]) for r in rows]


def _ring(project: Project, conn: Connection, k: int, depths: DepthIndex) -> Ring:
    members = _members(conn, k)
    counts = depth_counts(
        project, f"SELECT work_id FROM {_SEEN} WHERE ring = :k", {"k": k}, conn=conn, index=depths
    )
    ordered = sorted(members, key=lambda w: (-DEPTH_RANK[depths.of(w)], w))
    listed = ordered[:VIEW_MAX_NODES]
    return Ring(
        distance=k,
        total=len(members),
        by_depth={d: counts[d] for d in DEPTH_RANK},
        nodes=_nodes(project, conn, listed, depths),
        truncated=len(listed) < len(members),
    )


def _nodes(
    project: Project, conn: Connection, listed: Sequence[str], depths: DepthIndex
) -> list[OnionNode]:
    if not listed:
        return []
    papers = paper_nodes(conn, listed)
    years = _years(conn, listed)
    ideas = confirmed_ideas_of(project, conn, listed)
    return [
        OnionNode(
            work_id=w,
            title=papers[w].title or "",
            year=years.get(w),
            depth=depths.of(w),
            scope=papers[w].scope or "external",
            ideas=ideas.get(w, []),
        )
        for w in listed
    ]


def _years(conn: Connection, ids: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for start in range(0, len(ids), RING_BATCH):
        rows = conn.execute(
            text(
                "SELECT work_id, substr(json_extract(data, '$.dates.published'), 1, 4) "
                "FROM works WHERE work_id IN (SELECT value FROM json_each(:w))"
            ),
            {"w": json.dumps(list(ids[start : start + RING_BATCH]))},
        )
        out.update({str(w): int(y) for w, y in rows if y is not None and str(y).isdigit()})
    return out


# --- the regions overlay ---


def _focus_regions(project: Project) -> set[str]:
    """Regions of kind focus (every one, withheld or not)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT region_id FROM regions WHERE kind = :k"), {"k": RegionKind.FOCUS.value}
        )
        return {str(r[0]) for r in rows}


def _with_regions(project: Project, rings: list[Ring], agent: bool) -> list[Ring]:
    """The rings with each listed node's regions: the reviewed focus regions whose latest version
    holds it. For an agent a region that is withheld from agents is left out (`region_withheld`),
    without a trace. One indexed read per listed node, after the view's own connection closed."""
    focus = _focus_regions(project)
    withheld: dict[str, bool] = {}

    def shown(region_id: str) -> bool:
        if not agent:
            return True
        if region_id not in withheld:
            withheld[region_id] = region_withheld(project, region_id)
        return not withheld[region_id]

    out: list[Ring] = []
    for ring in rings:
        nodes = [
            node.model_copy(
                update={
                    "regions": [
                        m.region_id
                        for m in regions_of(project, MemberType.WORK, node.work_id)
                        if m.review_state == "reviewed"
                        and m.region_id in focus
                        and shown(m.region_id)
                    ]
                }
            )
            for node in ring.nodes
        ]
        out.append(ring.model_copy(update={"nodes": nodes}))
    return out


def _any_visible_region(project: Project, agent: bool) -> bool:
    """Whether some reviewed focus region (visible to the caller) holds a member."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT m.region_id FROM region_members m "
                "JOIN regions r ON r.region_id = m.region_id WHERE r.kind = :k AND "
                "COALESCE((SELECT rv.state FROM region_reviews rv WHERE rv.version = m.version "
                "ORDER BY rv.event_id DESC LIMIT 1), 'unreviewed') = 'reviewed'"
            ),
            {"k": RegionKind.FOCUS.value},
        ).all()
    return any(not (agent and region_withheld(project, str(r[0]))) for r in rows)


__all__ = ["ONION_MAX_RING", "VIEW_MAX_NODES", "ProcessingDepth", "onion_view"]
