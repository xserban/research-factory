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
from typing import cast, get_args

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.lineage.graph import GraphFilter
from factory.model.lineage import EdgeType
from factory.model.regions import RegionKind
from factory.model.search import QueryPurpose
from factory.model.views import (
    OnionEdgeType,
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
from factory.services.depth import DEPTH_RANK, DepthIndex, depth_index
from factory.services.lineage import (
    RING_BATCH,
    cites_expand,
    cites_incident_count,
    confirmed_ideas_of,
    has_active_merges,
    paper_nodes,
    ring_step,
)
from factory.services.references import included_works
from factory.services.regions import region_withheld
from factory.services.views import view_meta

ONION_MAX_RING = 3
VIEW_MAX_NODES = 500
VIEW_VERSION = 1

_SEEN = "onion_seen"
_PROBE = QueryPurpose.PROBE.value


DEFAULT_FILTER = OnionFilter()
_EDGE_TYPES = get_args(OnionEdgeType)


def parse_filter(
    max_ring: int,
    edge_types: Sequence[str] | None,
    include_inferred: bool,
    focus: Sequence[str] | None,
) -> OnionFilter:
    """The filter a tool or a command names, or a refusal (field `edge_types`) writing nothing.
    `edge_types` None means every type; an unknown or repeated-empty list is refused."""
    if edge_types is None:
        chosen = DEFAULT_FILTER.edge_types
    else:
        bad = [t for t in edge_types if t not in _EDGE_TYPES]
        if bad or not edge_types:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "edge_types", f"must name one or more of {', '.join(_EDGE_TYPES)}"
                    )
                ]
            )
        chosen = cast(tuple[OnionEdgeType, ...], tuple(dict.fromkeys(edge_types)))
    return OnionFilter(
        max_ring=max_ring,
        edge_types=chosen,
        include_inferred=include_inferred,
        focus=None if not focus else tuple(focus),
    )


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
    as_of = project.index.head()  # once, before any read: the view describes this position
    focus = _focus(project, flt)
    if not focus:
        notices.append(
            ViewNotice(
                code="focus-empty",
                text="No work is included yet (or the named focus is empty); every ring is empty.",
            )
        )
    depths = depth_index(project, agent=agent)
    considered: dict[EdgeType, set[str]] = {EdgeType(t): set() for t in flt.edge_types}
    cites_count = 0
    rings: list[Ring] = []
    with project.index.connect() as conn:
        conn.execute(text(f"CREATE TEMP TABLE {_SEEN} (work_id TEXT PRIMARY KEY, ring INTEGER)"))
        try:
            _seed(conn, focus)
            # `cites` is expanded set-based in SQL when no merge is active (the common case); the
            # lineage types, and every type while a merge is active, by the batched overlay.
            set_based = "cites" in flt.edge_types and not has_active_merges(conn)
            batched = tuple(EdgeType(t) for t in flt.edge_types if not (set_based and t == "cites"))
            batched_filter = GraphFilter(
                include_inferred=flt.include_inferred, edge_types=batched, include_ideas=False
            )
            for k in range(1, max_ring + 1):
                if set_based:
                    cites_expand(conn, _SEEN, k, graph_filter)
                if not batched:
                    continue
                frontier = _members(conn, k - 1)
                step = ring_step(project, conn, frontier, batched_filter)
                for edge_id, kind in step.edges.items():
                    considered[kind].add(edge_id)
                if step.neighbours:  # an empty executemany is an error
                    conn.execute(
                        text(f"INSERT OR IGNORE INTO {_SEEN} (work_id, ring) VALUES (:w, :k)"),
                        [{"w": w, "k": k} for w in sorted(step.neighbours)],
                    )
            if set_based:
                cites_count = cites_incident_count(conn, _SEEN, max_ring, graph_filter)
            for k in range(0, max_ring + 1):
                rings.append(_ring(project, conn, k, depths))
        finally:
            conn.execute(text(f"DROP TABLE IF EXISTS {_SEEN}"))
            conn.commit()
    rings = _with_regions(project, rings, agent)
    notices.extend(_region_notices(project, agent))
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
            as_of=as_of,
        ),
        rings=rings,
        edges_considered={
            t.value: len(ids) + (cites_count if t is EdgeType.CITES else 0)
            for t, ids in sorted(considered.items())
        },
    )


def _focus(project: Project, flt: OnionFilter) -> list[str]:
    """The ring-0 works: `included_works`, or the named `focus`, every one a corpus work."""
    if flt.focus is None:
        return sorted(set(included_works(project)))
    named = sorted(set(flt.focus))
    with project.index.connect() as conn:
        corpus = _corpus_among(conn, named)
    bad = [w for w in named if w not in corpus]
    if bad:
        raise FactoryValidationError(
            [ValidationIssue("focus", f"{w}: not a corpus work") for w in bad]
        )
    return named


def _corpus_among(conn: Connection, ids: Sequence[str]) -> set[str]:
    """The ids that are corpus works as `list_works` defines the corpus (a non-probe provenance
    row) and that no active merge absorbs. Role-blind: a seed's work is an ordinary corpus work."""
    found: set[str] = set()
    for start in range(0, len(ids), RING_BATCH):
        rows = conn.execute(
            text(
                "SELECT DISTINCT p.work_id FROM provenance p "
                "WHERE p.work_id IN (SELECT value FROM json_each(:ids)) "
                "AND p.query_id NOT IN (SELECT query_id FROM queries WHERE purpose = :probe) "
                "AND p.work_id NOT IN (SELECT mm.work_id FROM merge_members mm JOIN merges m "
                "ON m.merge_id = mm.merge_id WHERE m.status = 'active' "
                'AND mm.work_id != m."primary")'
            ),
            {"ids": json.dumps(list(ids[start : start + RING_BATCH])), "probe": _PROBE},
        )
        found.update(str(r[0]) for r in rows)
    return found


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
    """One ring from a single ordered pass over its ids: per-depth counts for every member, and
    per depth the first `VIEW_MAX_NODES` ids (enough: the list takes the highest depth first and
    ids in order within a depth)."""
    counts: dict[str, int] = dict.fromkeys(DEPTH_RANK, 0)
    first: dict[str, list[str]] = {d: [] for d in DEPTH_RANK}
    rows = conn.execute(
        text(f"SELECT work_id FROM {_SEEN} WHERE ring = :k ORDER BY work_id"), {"k": k}
    )
    for (work,) in rows:
        depth = depths.of(str(work))
        counts[depth] += 1
        if len(first[depth]) < VIEW_MAX_NODES:
            first[depth].append(str(work))
    total = sum(counts.values())
    by_rank = sorted(DEPTH_RANK, key=lambda d: -DEPTH_RANK[d])
    listed = [w for d in by_rank for w in first[d]][:VIEW_MAX_NODES]
    return Ring(
        distance=k,
        total=total,
        by_depth=counts,
        nodes=_nodes(project, conn, listed, depths),
        truncated=len(listed) < total,
    )


def _nodes(
    project: Project, conn: Connection, listed: Sequence[str], depths: DepthIndex
) -> list[OnionNode]:
    if not listed:
        return []
    papers = paper_nodes(conn, listed)
    corpus = _corpus_among(conn, listed)
    years = _years(conn, listed)
    ideas = confirmed_ideas_of(project, conn, listed)
    return [
        OnionNode(
            work_id=w,
            title=papers[w].title or "",
            year=years.get(w),
            depth=depths.of(w),
            scope="corpus" if w in corpus else "external",
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

    listed = sorted({n.work_id for ring in rings for n in ring.nodes})
    held = _focus_members(project, listed)
    out: list[Ring] = []
    for ring in rings:
        nodes = [
            node.model_copy(
                update={
                    "regions": [r for r in held.get(node.work_id, []) if r in focus and shown(r)]
                }
            )
            for node in ring.nodes
        ]
        out.append(ring.model_copy(update={"nodes": nodes}))
    return out


def _focus_members(project: Project, work_ids: Sequence[str]) -> dict[str, list[str]]:
    """For each listed work, the regions whose latest version holds it and is reviewed, by region
    id: the read of `regions_of` for a batch of canonical work ids (one indexed read per batch
    instead of one per work)."""
    out: dict[str, list[str]] = {}
    with project.index.connect() as conn:
        for start in range(0, len(work_ids), RING_BATCH):
            rows = conn.execute(
                text(
                    "SELECT m.member, m.region_id FROM region_members m "
                    "WHERE m.member_type = :t AND m.member IN (SELECT value FROM json_each(:ids)) "
                    "AND COALESCE((SELECT r.state FROM region_reviews r "
                    "WHERE r.version = m.version ORDER BY r.event_id DESC LIMIT 1), "
                    "'unreviewed') = 'reviewed' "
                    "ORDER BY m.region_id"
                ),
                {
                    "t": MemberType.WORK.value,
                    "ids": json.dumps(list(work_ids[start : start + RING_BATCH])),
                },
            )
            for member, region in rows:
                out.setdefault(str(member), []).append(str(region))
    return out


def _region_notices(project: Project, agent: bool) -> list[ViewNotice]:
    """`regions-none` when no reviewed focus region exists, `regions-empty` when some exists and
    none holds a member. For an agent a withheld region is not counted either way, so the text
    reads the same whether or not one exists."""
    with project.index.connect() as conn:
        reviewed = [
            str(r[0])
            for r in conn.execute(
                text(
                    "SELECT r.region_id FROM regions r WHERE r.kind = :k AND COALESCE((SELECT "
                    "rv.state FROM region_reviews rv WHERE rv.version = (SELECT s.version FROM "
                    "region_snapshots s WHERE s.region_id = r.region_id ORDER BY s.event_id DESC "
                    "LIMIT 1) ORDER BY rv.event_id DESC LIMIT 1), 'unreviewed') = 'reviewed'"
                ),
                {"k": RegionKind.FOCUS.value},
            )
        ]
        visible = [r for r in reviewed if not (agent and region_withheld(project, r))]
        if not visible:
            return [
                ViewNotice(
                    code="regions-none",
                    text="No reviewed focus region exists here; the regions column is empty.",
                )
            ]
        held = conn.execute(
            text(
                "SELECT 1 FROM region_members WHERE region_id IN (SELECT value FROM json_each(:r)) "
                "LIMIT 1"
            ),
            {"r": json.dumps(visible)},
        ).first()
    if held is None:
        return [
            ViewNotice(
                code="regions-empty",
                text="No reviewed focus region holds a member; the regions column is empty.",
            )
        ]
    return []


__all__ = ["ONION_MAX_RING", "VIEW_MAX_NODES", "ProcessingDepth", "onion_view", "parse_filter"]
