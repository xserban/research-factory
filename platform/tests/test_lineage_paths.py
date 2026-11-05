"""Bounded lineage queries and their service wrappers (slice 3b, plan G2-D Task 3)."""

# ruff: noqa: F811

from __future__ import annotations

import json
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.lineage.graph import (
    Direction,
    Graph,
    GraphEdge,
    GraphFilter,
    Neighbours,
    graph_neighbours,
    load_fixture,
)
from factory.lineage.paths import (
    LINEAGE_TYPES,
    MAX_DEPTH,
    MAX_RESULTS,
    ancestors,
    cited_by_at_least,
    descendants,
    improvements_on,
    path,
)
from factory.model.lineage import EdgeStatus, EdgeType, RelationProposal
from factory.services.context import Project
from factory.services.lineage import GraphQueryResult, graph_query, no_stated_base
from factory.services.relations import propose_relation
from tests.lineage_graph_helpers import GRAPH_SMALL, stand_in_basis, write_fixture
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world  # noqa: F401

P = {n: f"rf:p{n}-{n:08x}" for n in range(1, 10)}


def _edge(eid: str, source: str, target: str, kind: EdgeType = EdgeType.BUILDS_ON) -> GraphEdge:
    return GraphEdge(eid, kind, source, target, EdgeStatus.STATED, None, (), False)


def _nb(*edges: GraphEdge) -> Neighbours:
    return graph_neighbours(Graph((), tuple(edges), GraphFilter()))


@pytest.fixture
def nb() -> Neighbours:
    return graph_neighbours(load_fixture(GRAPH_SMALL))


@pytest.fixture
def nb_inferred() -> Neighbours:
    return graph_neighbours(load_fixture(GRAPH_SMALL, GraphFilter(include_inferred=True)))


def test_ancestors_and_descendants_expected(nb: Neighbours) -> None:
    assert ancestors(nb, P[9], 8).nodes == tuple(sorted(P[n] for n in (1, 3, 5, 7)))
    assert descendants(nb, P[1], 2).nodes == tuple(sorted(P[n] for n in (3, 4, 5)))
    assert ancestors(nb, P[9], 1).nodes == tuple(sorted((P[5], P[7])))


def test_path_shortest_with_tiebreak(nb: Neighbours) -> None:
    result = path(nb, P[9], P[1])
    assert result.nodes == (P[9], P[5], P[3], P[1]) and result.depth == 3
    assert len(result.edges) == 3
    assert path(nb, P[1], P[9]).nodes == ()  # edges point from the later work to the earlier


def test_path_tiebreak_is_the_smallest_node_sequence() -> None:
    nb = _nb(
        _edge("e1", "a", "c"),
        _edge("e2", "a", "b"),
        _edge("e3", "b", "z"),
        _edge("e4", "c", "z"),
    )
    assert path(nb, "a", "z").nodes == ("a", "b", "z")


def test_path_respects_filter(nb: Neighbours, nb_inferred: Neighbours) -> None:  # Review Focus 3
    assert path(nb, P[8], P[2]).nodes == ()
    found = path(nb_inferred, P[8], P[2])
    assert found.nodes == (P[8], P[2])
    graph = load_fixture(GRAPH_SMALL, GraphFilter(include_inferred=True))
    [edge] = [e for e in graph.edges if e.edge_id in found.edges]
    assert edge.status is EdgeStatus.INFERRED


def test_cycles_terminate() -> None:  # Review Focus 2
    nb = _nb(_edge("e1", "a", "b"), _edge("e2", "b", "a"), _edge("e3", "b", "c"))
    assert ancestors(nb, "a", 8).nodes == ("b", "c")
    assert descendants(nb, "a", 8).nodes == ("b",)
    assert path(nb, "a", "a").nodes == ("a",)
    assert path(nb, "a", "c").nodes == ("a", "b", "c")


def test_bounds_clamp_and_truncate() -> None:
    def nb_large(node: str, direction: Direction, types: frozenset[EdgeType]) -> list[GraphEdge]:
        if direction != "out":
            return []
        level = int(node.split("-")[0])
        return [_edge(f"{node}>{i}", node, f"{level + 1}-{node}.{i}") for i in range(3)]

    result = ancestors(nb_large, "0-x", 50)
    assert result.depth == MAX_DEPTH and result.truncated
    assert len(result.nodes) <= MAX_RESULTS + 1
    shallow = ancestors(nb_large, "0-x", 2)
    assert shallow.depth == 2 and not shallow.truncated and len(shallow.nodes) == 12


def test_traversal_calls_lookup_once_per_frontier_node(nb: Neighbours) -> None:
    calls: list[tuple[str, str]] = []

    def spy(node: str, direction: Direction, types: frozenset[EdgeType]) -> list[GraphEdge]:
        calls.append((node, direction))
        return list(nb(node, direction, types))

    ancestors(spy, P[9], 8)
    assert len(calls) == len(set(calls)) and all(d == "out" for _, d in calls)
    assert set(calls) <= {(P[n], "out") for n in range(1, 10)}
    calls.clear()
    path(spy, P[9], P[1])
    assert len(calls) == len(set(calls))


def test_improvements_on_and_cited_by(nb: Neighbours) -> None:
    assert improvements_on(nb, P[5]).nodes == (P[6],)
    assert improvements_on(nb, P[3]).nodes == ()
    cites = [e for e in load_fixture(GRAPH_SMALL).edges]
    assert cited_by_at_least(cites, 3).nodes == (P[1], P[5])  # three citers each
    assert cited_by_at_least(cites, 4).nodes == ()
    with pytest.raises(ValueError):
        cited_by_at_least(cites, 0)


# --- service wrappers ---


@pytest.fixture
def gp(project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> Project:
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    return project


def _result(r: GraphQueryResult) -> tuple[str, ...]:
    return tuple(n["id"] for n in r.nodes)  # type: ignore[misc]


def test_service_queries_equal_pure_on_fixture(gp: Project, nb: Neighbours) -> None:
    for flt in (GraphFilter(), GraphFilter(include_inferred=True, include_stale=True)):
        pure = graph_neighbours(load_fixture(GRAPH_SMALL, flt))
        for node in P.values():
            for depth in (1, 3, 8):
                a = graph_query(gp, "ancestors", node=node, depth=depth, flt=flt)
                assert _result(a) == ancestors(pure, node, depth).nodes
                d = graph_query(gp, "descendants", node=node, depth=depth, flt=flt)
                assert _result(d) == descendants(pure, node, depth).nodes
        found = graph_query(gp, "path", node=P[9], target=P[1], flt=flt)
        assert _result(found) == path(pure, P[9], P[1]).nodes
        assert [e["status"] for e in found.edges] == ["stated"] * 3
        imp = graph_query(gp, "improvements_on", node=P[5], flt=flt)
        assert _result(imp) == improvements_on(pure, P[5]).nodes
    cited = graph_query(gp, "cited_by_at_least", k=2)
    edges = [e for e in load_fixture(GRAPH_SMALL).edges if e.edge_type is EdgeType.CITES]
    assert _result(cited) == cited_by_at_least(edges, 2).nodes


def test_service_reports_clamp_filter_and_node_info(gp: Project) -> None:
    result = graph_query(gp, "ancestors", node=P[9], depth=50)
    assert result.depth == MAX_DEPTH and result.depth_clamped
    assert result.filter["include_inferred"] is False and result.query == "ancestors"
    assert {n["type"] for n in result.nodes} == {"paper"}
    assert all(set(n) == {"id", "type", "scope"} for n in result.nodes)
    assert all(set(e) == {"id", "type", "source", "target", "status"} for e in result.edges)


def test_graph_query_argument_errors(gp: Project) -> None:
    def fields(**kw: Any) -> list[tuple[str, str]]:
        with pytest.raises(FactoryValidationError) as e:
            graph_query(gp, **kw)
        return [(i.field, i.reason) for i in e.value.issues]

    assert fields(query="ancestors") == [("node", "required")]
    assert fields(query="path", node=P[1]) == [("target", "required")]
    assert fields(query="cited_by_at_least", k=0) == [("k", "must be at least 1")]
    assert fields(query="ancestors", node=P[1], depth=0) == [("depth", "must be at least 1")]
    assert fields(query="ancestors", node="rf:nobody-00000000") == [("node", "node-unknown")]
    assert fields(query="path", node=P[1], target="rf:nobody-00000000") == [
        ("target", "node-unknown")
    ]
    assert fields(query="bogus", node=P[1]) == [("query", "unknown query")]


def test_no_stated_base_categories_disjoint_and_complete(gp: Project) -> None:
    r = no_stated_base(gp)
    cats = [r.unextracted, r.not_stated, r.target_outside_corpus, r.no_relation]
    flat = [w for c in cats for w in c]
    assert len(flat) == len(set(flat))  # disjoint
    assert r.filter["include_inferred"] is False
    # without a protocol the contribution population is empty, so every category is empty
    assert flat == []


def test_graph_query_result_is_json(gp: Project) -> None:
    result = graph_query(gp, "ancestors", node=P[9])
    assert json.loads(result.model_dump_json())["query"] == "ancestors"
    assert {EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON} == LINEAGE_TYPES


def test_no_stated_base_on_a_real_population(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    before = no_stated_base(project)
    flat = [
        w
        for c in (
            before.unextracted,
            before.not_stated,
            before.target_outside_corpus,
            before.no_relation,
        )
        for w in c
    ]
    assert sorted(flat) == sorted(set(flat)) and lin.source in flat
    assert lin.source in before.no_relation  # extracted, a base idea with a corpus target
    assert set(world) - {lin.source} <= set(before.unextracted)
    propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=lin.source, target=lin.target5, edge_type="builds-on", basis_item=lin.base
        ),
    )
    after = no_stated_base(project)
    assert lin.source not in after.no_relation
    with_inferred = no_stated_base(project, GraphFilter(include_inferred=True))
    assert lin.source not in with_inferred.no_relation
