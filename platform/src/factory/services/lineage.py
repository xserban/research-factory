"""Graph reads, queries and exports over the projected lineage graph (slice 3b, plan G2-D).

Invariants:
- Read-only. Only the projector writes `graph_nodes` / `graph_edges`; this module reads them by
  indexed SQL and overlays only what it read (ruling 10): corpus membership, relation staleness
  and decisions (G2-C `relations`), idea merges and idea state.
- No call loads the whole graph. Neighbour lookups are one indexed read of one node's edges;
  `iter_nodes` / `iter_edges` stream ordered pages of `GRAPH_PAGE` rows.
- A relation that targets a merged idea is read as targeting the surviving idea, and as targeting
  the original again after the unmerge; nothing is stored. An edge to an idea the view does not
  show (rejected, superseded, or proposed without `include_inferred`) is dropped with it.
- Idea-to-idea `derived` edges (ruling 7) are computed on read from member edges, never stored.
- A held-out seed's work is an ordinary node (decision 37.9); this module does not filter by seed.
"""

from __future__ import annotations

import heapq
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.lineage.graph import (
    DEFAULT_FILTER,
    DERIVED,
    Direction,
    Graph,
    GraphEdge,
    GraphFilter,
    GraphNode,
    Neighbours,
    graph_neighbours,
    load_fixture,
)
from factory.lineage.paths import (
    LINEAGE_TYPES,
    MAX_DEPTH,
    MAX_RESULTS,
    QueryResult,
    ancestors,
    descendants,
    improvements_on,
    path,
)
from factory.model.base import StrictModel
from factory.model.extraction import Scope
from factory.model.lineage import EdgeStatus, EdgeType
from factory.services.context import Project
from factory.services.contributions import final_items
from factory.services.extraction import scope_population, stale_extractions, unit_states
from factory.services.ideas import _EFFECTIVE_MEMBERS
from factory.services.references import current_extraction
from factory.services.relations import _EFFECTIVE_SQL, relation_counts

__all__ = [
    "GRAPH_PAGE",
    "Direction",
    "Graph",
    "GraphEdge",
    "GraphFilter",
    "GraphNode",
    "GraphStatus",
    "Neighbours",
    "graph_neighbours",
    "graph_node",
    "graph_status",
    "index_neighbours",
    "iter_edges",
    "iter_nodes",
    "load_fixture",
    "require_node",
]

GRAPH_PAGE = 1000
_IDEA_PREFIX = "ida_"
_REJECTED = EdgeStatus.REJECTED
_DERIVED_STATUSES = frozenset({EdgeStatus.STATED, EdgeStatus.CONFIRMED})


def _is_idea(node_id: str) -> bool:
    return node_id.startswith(_IDEA_PREFIX)


def _stale_json(project: Project) -> str:
    return json.dumps(sorted(stale_extractions(project, scope=Scope.CONTRIBUTION)))


@dataclass
class _View:
    """The overlays of one filtered view, with per-view caches. One instance lives as long as one
    query or stream; it holds no connection."""

    project: Project
    flt: GraphFilter
    stale: str
    shown_cache: dict[str, str | None] = field(default_factory=dict)

    # --- ideas ---

    def shown_idea(self, conn: Connection, idea_id: str) -> str | None:
        """The idea `idea_id` stands for in this view (its survivor after merges), or None when
        the view hides it: unknown, superseded, rejected, or not confirmed (without
        `include_inferred`), or ideas are off."""
        if idea_id in self.shown_cache:
            return self.shown_cache[idea_id]
        result: str | None = None
        if self.flt.include_ideas:
            current = idea_id
            seen: set[str] = set()
            while current not in seen:
                seen.add(current)
                row = conn.execute(
                    text(
                        "SELECT superseded_by, decision, merged_into FROM ideas WHERE idea_id = :i"
                    ),
                    {"i": current},
                ).first()
                if row is None or row[0] is not None or row[1] == "reject":
                    break
                if row[2] is None:
                    if row[1] == "confirm" or self.flt.include_inferred:
                        result = current
                    break
                current = str(row[2])
        self.shown_cache[idea_id] = result
        return result

    def idea_ends(self, conn: Connection, idea_id: str) -> list[str]:
        """The idea and every live idea merged into it (transitively): the targets a relation
        may name for it."""
        rows = conn.execute(
            text(
                "WITH RECURSIVE tree(idea_id) AS (SELECT :i UNION "
                "SELECT c.idea_id FROM ideas c JOIN tree t ON c.merged_into = t.idea_id "
                "WHERE c.superseded_by IS NULL) SELECT idea_id FROM tree"
            ),
            {"i": idea_id},
        ).all()
        return [str(r[0]) for r in rows]

    def effective_members(self, conn: Connection, idea_id: str) -> list[str]:
        return [str(r[0]) for r in conn.execute(text(_EFFECTIVE_MEMBERS), {"i": idea_id}).all()]

    # --- edges ---

    def relation_statuses(self, conn: Connection, ids: Sequence[str]) -> dict[str, EdgeStatus]:
        if not ids:
            return {}
        rows = conn.execute(
            text(
                f"{_EFFECTIVE_SQL} SELECT relation_id, effective FROM shown "
                "WHERE relation_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(sorted(set(ids))), "stale": self.stale},
        ).all()
        return {str(r[0]): EdgeStatus(str(r[1])) for r in rows}

    def overlay(
        self,
        conn: Connection,
        rows: Sequence[Any],
        types: frozenset[EdgeType],
    ) -> list[GraphEdge]:
        """The edges the view shows among `rows` (live `graph_edges` rows), with overlaid status
        and merge-retargeted ideas."""
        relation_ids = [str(r["edge_id"]) for r in rows if r["edge_type"] != EdgeType.CITES.value]
        statuses = self.relation_statuses(conn, relation_ids)
        allowed = self.flt.statuses()
        out: list[GraphEdge] = []
        for r in rows:
            edge_type = EdgeType(r["edge_type"])
            if edge_type not in types or edge_type not in self.flt.edge_types:
                continue
            if edge_type is EdgeType.CITES:
                status = _REJECTED if r["decision"] == "reject" else EdgeStatus(r["base_status"])
            else:
                found = statuses.get(str(r["edge_id"]))
                if found is None:
                    continue
                status = found
            if status not in allowed:
                continue
            target = str(r["target"])
            if _is_idea(target):
                survivor = self.shown_idea(conn, target)
                if survivor is None:
                    continue
                target = survivor
            out.append(
                GraphEdge(
                    edge_id=str(r["edge_id"]),
                    edge_type=edge_type,
                    source=str(r["source"]),
                    target=target,
                    status=status,
                    basis=None if r["basis"] is None else str(r["basis"]),
                    flags=tuple(json.loads(r["flags"])),
                    derived=False,
                )
            )
        return out

    def edges_of(
        self, conn: Connection, node: str, direction: Direction, types: frozenset[EdgeType]
    ) -> list[GraphEdge]:
        """The shown edges of `node` in `direction`: one indexed read, then the overlays."""
        if _is_idea(node):
            if self.shown_idea(conn, node) != node:
                return []
            if direction == "out":  # an idea is never the source of a stored edge
                return self.derived(conn, node, types, "out")
            ends, column = self.idea_ends(conn, node), "target"
        else:
            ends, column = [node], "source" if direction == "out" else "target"
        names = json.dumps(sorted(t.value for t in types & set(self.flt.edge_types)))
        rows = (
            conn.execute(
                text(
                    f"SELECT * FROM graph_edges WHERE {column} IN (SELECT value FROM "
                    "json_each(:ends)) AND edge_type IN (SELECT value FROM json_each(:types)) "
                    "AND live = 1"
                ),
                {"ends": json.dumps(ends), "types": names},
            )
            .mappings()
            .all()
        )
        edges = self.overlay(conn, rows, types)
        if _is_idea(node):
            edges += self.derived(conn, node, types, "in")
        return edges

    # --- derived idea edges (ruling 7) ---

    def derived(
        self,
        conn: Connection,
        idea_id: str,
        types: frozenset[EdgeType],
        direction: Direction,
    ) -> list[GraphEdge]:
        if EdgeType.BUILDS_ON not in types or EdgeType.BUILDS_ON not in self.flt.edge_types:
            return []
        if not self.flt.include_ideas or self.shown_idea(conn, idea_id) != idea_id:
            return []
        members = self.effective_members(conn, idea_id)
        if not members:
            return []
        own, other = ("source", "target") if direction == "out" else ("target", "source")
        rows = (
            conn.execute(
                text(
                    f"SELECT * FROM graph_edges WHERE {own} IN (SELECT value FROM json_each(:m)) "
                    "AND edge_type = 'builds-on' AND live = 1"
                ),
                {"m": json.dumps(members)},
            )
            .mappings()
            .all()
        )
        firm = self.relation_statuses(conn, [str(r["edge_id"]) for r in rows])
        ends = sorted(
            {str(r[other]) for r in rows if firm.get(str(r["edge_id"])) in _DERIVED_STATUSES}
        )
        if not ends:
            return []
        owners = conn.execute(
            text(
                "SELECT DISTINCT idea_id FROM idea_members "
                "WHERE work_id IN (SELECT value FROM json_each(:w)) ORDER BY idea_id"
            ),
            {"w": json.dumps(ends)},
        ).all()
        others: set[str] = set()
        for (owner,) in owners:
            survivor = self.shown_idea(conn, str(owner))
            if survivor is not None and survivor != idea_id:
                others.add(survivor)
        edges: list[GraphEdge] = []
        for o in sorted(others):
            source, target = (idea_id, o) if direction == "out" else (o, idea_id)
            edges.append(
                GraphEdge(
                    edge_id=f"drv:{source}:{target}",
                    edge_type=EdgeType.BUILDS_ON,
                    source=source,
                    target=target,
                    status=DERIVED,
                    basis=None,
                    flags=(),
                    derived=True,
                )
            )
        return edges


# --- Public reads ---


def _view(project: Project, flt: GraphFilter) -> _View:
    project.index.sync()
    return _View(project, flt, _stale_json(project))


_ABSORBED = (
    "SELECT DISTINCT j.value AS work_id FROM merges m, json_each(m.absorbed) j "
    "WHERE m.status = 'active'"
)


def _paper_nodes(conn: Connection, ids: Sequence[str]) -> dict[str, GraphNode]:
    """Paper nodes for `ids`: corpus when the work is recorded and not absorbed by an active
    merge (the rule of `canonical_works`), else external."""
    if not ids:
        return {}
    rows = conn.execute(
        text(
            f"WITH absorbed AS ({_ABSORBED}) SELECT i.value, "
            "json_extract(w.data, '$.title'), w.work_id IS NOT NULL AND "
            "i.value NOT IN (SELECT work_id FROM absorbed) "
            "FROM json_each(:ids) i LEFT JOIN works w ON w.work_id = i.value"
        ),
        {"ids": json.dumps(sorted(set(ids)))},
    ).all()
    return {
        str(r[0]): GraphNode(
            node_id=str(r[0]),
            node_type="paper",
            scope="corpus" if r[2] else "external",
            title=None if r[1] is None else str(r[1]),
            name=None,
            members=(),
        )
        for r in rows
    }


def _idea_node(view: _View, conn: Connection, idea_id: str) -> GraphNode:
    name = conn.execute(
        text("SELECT name FROM ideas WHERE idea_id = :i"), {"i": idea_id}
    ).scalar_one()
    return GraphNode(
        node_id=idea_id,
        node_type="idea",
        scope=None,
        title=None,
        name=str(name),
        members=tuple(view.effective_members(conn, idea_id)),
    )


def graph_node(
    project: Project, node_id: str, flt: GraphFilter = DEFAULT_FILTER
) -> GraphNode | None:
    """One node: a work that is in the graph or the corpus, or an idea the view shows. None when
    absent, filtered out, or an idea merged away."""
    view = _view(project, flt)
    with project.index.connect() as conn:
        if _is_idea(node_id):
            if view.shown_idea(conn, node_id) != node_id:
                return None
            return _idea_node(view, conn, node_id)
        known = conn.execute(
            text(
                "SELECT 1 FROM graph_nodes WHERE node_id = :n UNION "
                "SELECT 1 FROM works WHERE work_id = :n LIMIT 1"
            ),
            {"n": node_id},
        ).first()
        if known is None:
            return None
        return _paper_nodes(conn, [node_id])[node_id]


def require_node(
    project: Project, node_id: str, field_name: str, flt: GraphFilter = DEFAULT_FILTER
) -> GraphNode:
    """`graph_node`, or a `FactoryValidationError` on `field_name`: `node-unknown`, or
    `idea-merged:<surviving id>`."""
    node = graph_node(project, node_id, flt)
    if node is not None:
        return node
    if _is_idea(node_id):
        with project.index.connect() as conn:
            survivor = _View(project, GraphFilter(include_inferred=True), "[]").shown_idea(
                conn, node_id
            )
        if survivor is not None and survivor != node_id:
            raise FactoryValidationError([ValidationIssue(field_name, f"idea-merged:{survivor}")])
    raise FactoryValidationError([ValidationIssue(field_name, "node-unknown")])


def index_neighbours(project: Project, flt: GraphFilter = DEFAULT_FILTER) -> Neighbours:
    """The `Neighbours` lookup over the index: each call is one indexed read of one node's edges
    (plus the overlays of what it read). The index is synced and the stale set computed once, when
    the lookup is made."""
    view = _view(project, flt)

    def neighbours(node: str, direction: Direction, types: frozenset[EdgeType]) -> list[GraphEdge]:
        with project.index.connect() as conn:
            edges = view.edges_of(conn, node, direction, types)
        return sorted(
            edges,
            key=lambda e: (
                e.target if direction == "out" else e.source,
                e.edge_type.value,
                e.edge_id,
            ),
        )

    return neighbours


def iter_nodes(project: Project, flt: GraphFilter = DEFAULT_FILTER) -> Iterator[GraphNode]:
    """Every node the view shows, by id, in pages of `GRAPH_PAGE` rows."""
    view = _view(project, flt)
    last = ""
    while True:
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT node_id, node_type FROM graph_nodes WHERE node_id > :last "
                    "ORDER BY node_id LIMIT :n"
                ),
                {"last": last, "n": GRAPH_PAGE},
            ).all()
            papers = _paper_nodes(conn, [str(r[0]) for r in rows if r[1] == "paper"])
            for node_id, node_type in rows:
                if node_type == "paper":
                    yield papers[str(node_id)]
                elif view.shown_idea(conn, str(node_id)) == str(node_id):
                    yield _idea_node(view, conn, str(node_id))
        if len(rows) < GRAPH_PAGE:
            return
        last = str(rows[-1][0])


def _base_edges(project: Project, view: _View) -> Iterator[GraphEdge]:
    """Stored edges in export order. A page holds whole source groups, so the sort after the
    overlay (which may retarget) is global."""
    types = frozenset(view.flt.edge_types)
    last = ""
    while True:
        with project.index.connect() as conn:
            rows = list(
                conn.execute(
                    text(
                        "SELECT * FROM graph_edges WHERE source > :last AND live = 1 "
                        "AND edge_type IN (SELECT value FROM json_each(:types)) "
                        "ORDER BY source, edge_type, target, edge_id LIMIT :n"
                    ),
                    {
                        "last": last,
                        "types": json.dumps(sorted(t.value for t in types)),
                        "n": GRAPH_PAGE,
                    },
                )
                .mappings()
                .all()
            )
            full = len(rows) == GRAPH_PAGE
            if full:
                tail = str(rows[-1]["source"])
                rows = [r for r in rows if r["source"] != tail]
                rows += list(
                    conn.execute(
                        text(
                            "SELECT * FROM graph_edges WHERE source = :s AND live = 1 "
                            "AND edge_type IN (SELECT value FROM json_each(:types))"
                        ),
                        {"s": tail, "types": json.dumps(sorted(t.value for t in types))},
                    )
                    .mappings()
                    .all()
                )
                last = tail
            edges = view.overlay(conn, rows, types)
        yield from sorted(edges, key=GraphEdge.sort_key)
        if not full:
            return


def _derived_edges(project: Project, view: _View) -> Iterator[GraphEdge]:
    """Derived idea edges in export order (ideas sort by id; their edges by type, target)."""
    if not view.flt.include_ideas:
        return
    types = frozenset(view.flt.edge_types)
    last = ""
    while True:
        with project.index.connect() as conn:
            ids = [
                str(r[0])
                for r in conn.execute(
                    text(
                        "SELECT idea_id FROM ideas WHERE idea_id > :last AND merged_into IS NULL "
                        "ORDER BY idea_id LIMIT :n"
                    ),
                    {"last": last, "n": GRAPH_PAGE},
                ).all()
            ]
            page = [
                e
                for idea_id in ids
                for e in sorted(view.derived(conn, idea_id, types, "out"), key=GraphEdge.sort_key)
            ]
        yield from page
        if len(ids) < GRAPH_PAGE:
            return
        last = ids[-1]


def iter_edges(project: Project, flt: GraphFilter = DEFAULT_FILTER) -> Iterator[GraphEdge]:
    """Every edge the view shows, ordered by `(source, edge_type, target, edge_id)`, streamed:
    the stored edges and the derived idea edges are merged page by page."""
    view = _view(project, flt)
    yield from heapq.merge(
        _base_edges(project, view), _derived_edges(project, view), key=GraphEdge.sort_key
    )


# --- Status ---


class GraphStatus(StrictModel):
    """Counts derived from the projection and the log. `filter` names the statuses counted: all
    of them, so `edges` lists every status of every edge type."""

    filter: dict[str, JsonValue]
    nodes: dict[str, int]
    edges: dict[str, dict[str, int]]
    unextracted: list[str]
    no_references: list[str]
    not_stated: int
    uncited_base: int


def _population(project: Project) -> list[str]:
    try:
        return scope_population(project, Scope.CONTRIBUTION)
    except FactoryValidationError:
        return []


def graph_status(project: Project) -> GraphStatus:
    """Node and edge counts by SQL aggregates (no full-table read into memory), plus the
    contribution population's gaps."""
    project.index.sync()
    all_statuses = {s.value for s in EdgeStatus}
    with project.index.connect() as conn:
        node_rows = conn.execute(
            text(
                f"WITH absorbed AS ({_ABSORBED}) "
                "SELECT CASE WHEN n.node_type = 'idea' THEN 'idea' "
                "WHEN w.work_id IS NOT NULL AND n.node_id NOT IN (SELECT work_id FROM absorbed) "
                "THEN 'paper-corpus' ELSE 'paper-external' END, COUNT(*) "
                "FROM graph_nodes n LEFT JOIN works w ON w.work_id = n.node_id "
                "WHERE n.node_type = 'paper' OR n.node_id IN (SELECT idea_id FROM ideas "
                "WHERE superseded_by IS NULL AND merged_into IS NULL "
                "AND (decision IS NULL OR decision != 'reject')) GROUP BY 1"
            )
        ).all()
        cite_rows = conn.execute(
            text(
                "SELECT CASE WHEN decision = 'reject' THEN 'rejected' ELSE base_status END, "
                "COUNT(*) FROM graph_edges WHERE edge_type = 'cites' AND live = 1 GROUP BY 1"
            )
        ).all()
    nodes = {"idea": 0, "paper-corpus": 0, "paper-external": 0}
    nodes.update({str(k): int(n) for k, n in node_rows})
    cites = dict.fromkeys(sorted(all_statuses), 0)
    cites.update({str(k): int(n) for k, n in cite_rows})
    edges: dict[str, dict[str, int]] = {"cites": cites}
    for edge_type, counts in relation_counts(project).items():
        edges[edge_type] = counts
    population = _population(project)
    current = {
        s.work_id for s in unit_states(project, scope=Scope.CONTRIBUTION) if s.state == "current"
    }
    items = final_items(project)
    return GraphStatus(
        filter={
            "statuses": sorted(all_statuses),
            "edge_types": sorted(t.value for t in EdgeType),
            "include_ideas": True,
        },
        nodes=dict(sorted(nodes.items())),
        edges={k: dict(sorted(v.items())) for k, v in sorted(edges.items())},
        unextracted=[w for w in population if w not in current],
        no_references=[w for w in population if current_extraction(project, w) is None],
        not_stated=sum(1 for i in items if i.item_kind == "not-stated"),
        uncited_base=sum(1 for i in items if i.item_kind == "base-idea" and i.cited_entry is None),
    )


# --- Queries ---

QueryKind = Literal[
    "ancestors", "descendants", "path", "no_stated_base", "improvements_on", "cited_by_at_least"
]
_NEEDS_NODE = frozenset({"ancestors", "descendants", "path", "improvements_on"})
_KINDS = frozenset(get_args(QueryKind))


class NoStatedBase(StrictModel):
    """Population works with no live `builds-on` (or `improves-on`) edge in the filter, in exactly
    one category each (ruling 6): `unextracted` (no current contribution unit), `not-stated` (a
    final base-idea item recorded as not stated), `target-outside-corpus` (a final base-idea item
    citing an entry that resolves to a work outside the corpus), `no-relation` (all others)."""

    filter: dict[str, JsonValue]
    unextracted: list[str]
    not_stated: list[str]
    target_outside_corpus: list[str]
    no_relation: list[str]


def no_stated_base(project: Project, flt: GraphFilter = DEFAULT_FILTER) -> NoStatedBase:
    view = _view(project, flt)
    population = _population(project)
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT * FROM graph_edges WHERE source IN (SELECT value FROM json_each(:p)) "
                    "AND edge_type IN ('builds-on', 'improves-on') AND live = 1"
                ),
                {"p": json.dumps(population)},
            )
            .mappings()
            .all()
        )
        based = {e.source for e in view.overlay(conn, rows, LINEAGE_TYPES)}
        rest = [w for w in population if w not in based]
        current = {
            s.work_id
            for s in unit_states(project, scope=Scope.CONTRIBUTION)
            if s.state == "current"
        }
        items = [i for i in final_items(project) if i.work_id in set(rest)]
        absent = {
            i.work_id for i in items if i.item_kind == "not-stated" and i.absent_kind == "base-idea"
        }
        cited = [i for i in items if i.item_kind == "base-idea" and i.cited is not None]
        outside: set[str] = set()
        if cited:
            links = {
                (str(r[0]), int(r[1])): str(r[2])
                for r in conn.execute(
                    text(
                        "SELECT extraction_id, ordinal, work_id FROM reference_links "
                        "WHERE state = 'resolved' AND work_id IS NOT NULL"
                    )
                ).all()
                if (str(r[0]), int(r[1]))
                in {(i.cited.reference_extraction_id, i.cited.ordinal) for i in cited if i.cited}
            }
            scopes = _paper_nodes(conn, sorted(set(links.values())))
            for i in cited:
                assert i.cited is not None
                found = links.get((i.cited.reference_extraction_id, i.cited.ordinal))
                if found is not None and scopes[found].scope == "external":
                    outside.add(i.work_id)
    unextracted = [w for w in rest if w not in current]
    out: dict[str, list[str]] = {"u": [], "n": [], "o": [], "r": []}
    for w in rest:
        key = "u" if w not in current else "n" if w in absent else "o" if w in outside else "r"
        out[key].append(w)
    assert len(unextracted) == len(out["u"])
    return NoStatedBase(
        filter=flt.as_dict(),
        unextracted=sorted(out["u"]),
        not_stated=sorted(out["n"]),
        target_outside_corpus=sorted(out["o"]),
        no_relation=sorted(out["r"]),
    )


class GraphQueryResult(StrictModel):
    """A query's answer: ids and statuses only, never prose. `depth` is the depth used and
    `depth_clamped` says the requested one was larger than `MAX_DEPTH`."""

    query: QueryKind
    filter: dict[str, JsonValue]
    nodes: list[dict[str, JsonValue]]
    edges: list[dict[str, JsonValue]]
    truncated: bool
    depth: int | None
    depth_clamped: bool = False
    categories: dict[str, list[str]] | None = None


def _node_rows(project: Project, ids: Sequence[str]) -> list[dict[str, JsonValue]]:
    """`{id, type, scope}` for each id, in the order given."""
    with project.index.connect() as conn:
        papers = _paper_nodes(conn, [i for i in ids if not _is_idea(i)])
    out: list[dict[str, JsonValue]] = []
    for ident in ids:
        if _is_idea(ident):
            out.append({"id": ident, "type": "idea", "scope": None})
        else:
            scope = papers[ident].scope if ident in papers else "external"
            out.append({"id": ident, "type": "paper", "scope": scope})
    return out


def _edge_rows(edges: Sequence[GraphEdge]) -> list[dict[str, JsonValue]]:
    return [
        {
            "id": e.edge_id,
            "type": e.edge_type.value,
            "source": e.source,
            "target": e.target,
            "status": e.status
            if isinstance(e.status, str) and e.status == DERIVED
            else e.status.value,
        }
        for e in sorted(edges, key=GraphEdge.sort_key)
    ]


def graph_query(
    project: Project,
    query: str,
    *,
    node: str | None = None,
    target: str | None = None,
    depth: int = 3,
    k: int = 2,
    flt: GraphFilter = DEFAULT_FILTER,
) -> GraphQueryResult:
    """Run a bounded query; invalid arguments raise `FactoryValidationError` and read nothing."""
    if query not in _KINDS:
        raise FactoryValidationError([ValidationIssue("query", "unknown query")])
    kind: QueryKind = query  # type: ignore[assignment]
    issues: list[ValidationIssue] = []
    if kind in _NEEDS_NODE and node is None:
        issues.append(ValidationIssue("node", "required"))
    if kind == "path" and target is None:
        issues.append(ValidationIssue("target", "required"))
    if kind in ("ancestors", "descendants") and depth < 1:
        issues.append(ValidationIssue("depth", "must be at least 1"))
    if kind == "cited_by_at_least" and k < 1:
        issues.append(ValidationIssue("k", "must be at least 1"))
    if issues:
        raise FactoryValidationError(issues)
    if kind in _NEEDS_NODE:
        assert node is not None
        require_node(project, node, "node", flt)
    if kind == "path":
        assert target is not None
        require_node(project, target, "target", flt)
    if kind == "no_stated_base":
        base = no_stated_base(project, flt)
        categories = {
            "unextracted": base.unextracted,
            "not-stated": base.not_stated,
            "target-outside-corpus": base.target_outside_corpus,
            "no-relation": base.no_relation,
        }
        flat = sorted(w for ws in categories.values() for w in ws)
        return GraphQueryResult(
            query=kind,
            filter=flt.as_dict(),
            nodes=_node_rows(project, flat),
            edges=[],
            truncated=False,
            depth=None,
            categories=categories,
        )
    if kind == "cited_by_at_least":
        with project.index.connect() as conn:
            project.index.sync()
            rows = conn.execute(
                text(
                    "SELECT target FROM graph_edges WHERE edge_type = 'cites' AND live = 1 "
                    "AND (decision IS NULL OR decision != 'reject') GROUP BY target "
                    "HAVING COUNT(DISTINCT source) >= :k ORDER BY target LIMIT :n"
                ),
                {"k": k, "n": MAX_RESULTS + 1},
            ).all()
        ids = [str(r[0]) for r in rows]
        return GraphQueryResult(
            query=kind,
            filter=flt.as_dict(),
            nodes=_node_rows(project, ids[:MAX_RESULTS]),
            edges=[],
            truncated=len(ids) > MAX_RESULTS,
            depth=None,
        )
    seen: dict[str, GraphEdge] = {}
    lookup = index_neighbours(project, flt)

    def recording(n: str, d: Direction, types: frozenset[EdgeType]) -> Sequence[GraphEdge]:
        found = lookup(n, d, types)
        seen.update((e.edge_id, e) for e in found)
        return found

    assert node is not None
    result: QueryResult
    if kind == "ancestors":
        result = ancestors(recording, node, depth)
    elif kind == "descendants":
        result = descendants(recording, node, depth)
    elif kind == "path":
        assert target is not None
        result = path(recording, node, target)
    else:
        result = improvements_on(recording, node)
    return GraphQueryResult(
        query=kind,
        filter=flt.as_dict(),
        nodes=_node_rows(project, result.nodes),
        edges=_edge_rows([seen[i] for i in result.edges]),
        truncated=result.truncated,
        depth=result.depth,
        depth_clamped=kind in ("ancestors", "descendants") and depth > MAX_DEPTH,
    )
