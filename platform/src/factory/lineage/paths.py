"""Bounded lineage queries over a `Neighbours` lookup (slice 3b, plan G2-D, rulings 5 and 10).

Pure and deterministic. Traversals expand the frontier level by level with one lookup per frontier
node, so they run unchanged on a small in-memory graph and on the index, and never see the whole
graph. They follow `builds-on` and `improves-on` edges (either type; `improves-on` implies
`builds-on` in queries) from the later work to the earlier one. Bounds: `MAX_DEPTH` levels and
`MAX_RESULTS` nodes; a larger depth is clamped (the result reports the depth used) and an
oversized result is cut with `truncated = True`. Each node is reported once, so cycles terminate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from factory.lineage.graph import Direction, GraphEdge, Neighbours
from factory.model.lineage import EdgeType

MAX_DEPTH = 8
MAX_RESULTS = 500
LINEAGE_TYPES = frozenset({EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON})


@dataclass(frozen=True)
class QueryResult:
    """`nodes` sorted by id (in path order for `path`); `edges` are the ids of the edges the
    query followed, sorted; `depth` is the depth used (`None` for queries without one, and for a
    `path` that does not exist)."""

    query: str
    nodes: tuple[str, ...]
    edges: tuple[str, ...]
    depth: int | None
    truncated: bool


def _walk(
    nb: Neighbours,
    node: str,
    depth: int,
    direction: Direction,
    query: str,
    limit: int = MAX_RESULTS,
) -> QueryResult:
    depth = max(0, min(depth, MAX_DEPTH))
    visited = {node}
    edge_ids: set[str] = set()
    frontier = [node]
    truncated = False
    for _ in range(depth):
        following: list[str] = []
        for current in sorted(frontier):
            for edge in nb(current, direction, LINEAGE_TYPES):
                other = edge.target if direction == "out" else edge.source
                if other not in visited and len(visited) > limit:
                    truncated = True
                    break
                edge_ids.add(edge.edge_id)
                if other not in visited:
                    visited.add(other)
                    following.append(other)
            if truncated:
                break
        if truncated or not following:
            break
        frontier = following
    return QueryResult(
        query=query,
        nodes=tuple(sorted(visited - {node})),
        edges=tuple(sorted(edge_ids)),
        depth=depth,
        truncated=truncated,
    )


def ancestors(nb: Neighbours, node: str, depth: int, *, limit: int = MAX_RESULTS) -> QueryResult:
    """The works `node` builds on, transitively, up to `depth` levels. `limit` replaces
    `MAX_RESULTS` for callers with their own bound (regions)."""
    return _walk(nb, node, depth, "out", "ancestors", limit)


def descendants(nb: Neighbours, node: str, depth: int, *, limit: int = MAX_RESULTS) -> QueryResult:
    """The works that build on `node`, transitively, up to `depth` levels (`limit` as above)."""
    return _walk(nb, node, depth, "in", "descendants", limit)


def path(nb: Neighbours, a: str, b: str) -> QueryResult:
    """The shortest path from `a` to `b` along edge direction; among shortest paths the one whose
    node-id sequence is lexicographically smallest. `nodes` is in path order; empty when none."""
    paths: dict[str, tuple[str, ...]] = {a: (a,)}
    via: dict[str, str] = {}
    frontier = [a]
    truncated = False
    for _ in range(MAX_DEPTH):
        if b in paths or not frontier or truncated:
            break
        following: list[str] = []
        for current in sorted(frontier, key=lambda n: paths[n]):
            for edge in nb(current, "out", LINEAGE_TYPES):
                if edge.target in paths:
                    continue
                if len(paths) > MAX_RESULTS:
                    truncated = True
                    break
                paths[edge.target] = (*paths[current], edge.target)
                via[edge.target] = edge.edge_id
                following.append(edge.target)
            if truncated:
                break
        frontier = following
    if b not in paths:
        return QueryResult("path", (), (), None, truncated)
    nodes = paths[b]
    edges = tuple(via[n] for n in nodes[1:])
    return QueryResult("path", nodes, edges, len(nodes) - 1, False)


def improvements_on(nb: Neighbours, node: str) -> QueryResult:
    """The works with an `improves-on` edge into `node`."""
    edges = nb(node, "in", frozenset({EdgeType.IMPROVES_ON}))
    return QueryResult(
        "improvements_on",
        tuple(sorted({e.source for e in edges})),
        tuple(sorted(e.edge_id for e in edges)),
        None,
        False,
    )


def cited_by_at_least(edges: Iterable[GraphEdge], k: int) -> QueryResult:
    """Targets cited by at least `k` distinct sources over `cites` edges, by id, cut at
    `MAX_RESULTS`. Pure reference of the service's SQL aggregate."""
    if k < 1:
        raise ValueError("k must be at least 1")
    cites = [e for e in edges if e.edge_type is EdgeType.CITES]
    counts = Counter(t for t, _ in {(e.target, e.source) for e in cites})
    targets = sorted(t for t, n in counts.items() if n >= k)
    truncated = len(targets) > MAX_RESULTS
    targets = targets[:MAX_RESULTS]
    keep = set(targets)
    return QueryResult(
        "cited_by_at_least",
        tuple(targets),
        tuple(sorted(e.edge_id for e in cites if e.target in keep)),
        None,
        truncated,
    )
