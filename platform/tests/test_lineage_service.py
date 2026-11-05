"""Graph reads, overlays, filter and status over the projection (slice 3b, plan G2-D Task 2)."""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.lineage.graph import GraphFilter, graph_neighbours, load_fixture
from factory.model.lineage import EdgeStatus, EdgeType
from factory.services import lineage
from factory.services.context import Project
from factory.services.lineage import (
    graph_node,
    graph_status,
    index_neighbours,
    iter_edges,
    iter_nodes,
    require_node,
)
from tests.lineage_graph_helpers import GRAPH_SMALL, record, stand_in_basis, write_fixture
from tests.lineage_payloads import ITEM, idea, merge

FILTERS = [
    GraphFilter(),
    GraphFilter(include_inferred=True),
    GraphFilter(include_stale=True),
    GraphFilter(include_inferred=True, include_stale=True),
]
TYPE_SETS = [
    frozenset({EdgeType.CITES}),
    frozenset({EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON}),
    frozenset(EdgeType),
]
ALL = GraphFilter(include_inferred=True, include_stale=True)


def _doc() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(GRAPH_SMALL.read_text())
    return loaded


def _ids(prefix: str) -> list[str]:
    return sorted(n["id"] for n in _doc()["nodes"] if n["id"].startswith(prefix))


@pytest.fixture
def gp(project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> Project:
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    return project


@pytest.mark.parametrize("flt", FILTERS)
def test_index_neighbours_equal_in_memory_on_fixture(gp: Project, flt: GraphFilter) -> None:
    reference = graph_neighbours(load_fixture(GRAPH_SMALL, flt))
    indexed = index_neighbours(gp, flt)
    for node in (n["id"] for n in _doc()["nodes"]):
        for direction, types in itertools.product(("out", "in"), TYPE_SETS):
            assert indexed(node, direction, types) == reference(node, direction, types), (
                node,
                direction,
                sorted(t.value for t in types),
            )


def test_iter_edges_equal_the_fixture_view(gp: Project) -> None:
    for flt in FILTERS:
        expected = load_fixture(GRAPH_SMALL, flt).edges
        assert list(iter_edges(gp, flt)) == list(expected)


def test_iter_nodes_equal_the_fixture_view(gp: Project) -> None:
    for flt in FILTERS:
        got = [(n.node_id, n.node_type, n.scope, n.name, n.members) for n in iter_nodes(gp, flt)]
        want = [
            (n.node_id, n.node_type, n.scope, n.name, n.members)
            for n in load_fixture(GRAPH_SMALL, flt).nodes
        ]
        assert got == want


def test_corpus_scope_matches_canonical_works(gp: Project) -> None:
    papers = _ids("rf:")
    in_corpus, absorbed = papers[0], papers[1]
    with gp.index.connect() as conn:
        for work in (in_corpus, absorbed):
            conn.execute(
                text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, :d, 'x')"),
                {"w": work, "d": json.dumps({"title": "An invented title"})},
            )
        conn.execute(
            text(
                'INSERT INTO merges (merge_id, "primary", absorbed, rule, records, status) '
                "VALUES ('mrg_x', :p, :a, 'doi', 2, 'active')"
            ),
            {"p": in_corpus, "a": json.dumps([absorbed])},
        )
        conn.commit()
    scopes = {n.node_id: (n.scope, n.title) for n in iter_nodes(gp) if n.node_type == "paper"}
    assert scopes[in_corpus] == ("corpus", "An invented title")
    assert scopes[absorbed] == ("external", "An invented title")
    assert scopes[papers[2]] == ("external", None)
    assert graph_status(gp).nodes["paper-corpus"] == 1


def test_default_view_has_stated_and_confirmed_only(gp: Project) -> None:
    edges = list(iter_edges(gp))
    assert edges
    assert {e.status for e in edges} <= {EdgeStatus.STATED, EdgeStatus.CONFIRMED, "derived"}


def test_include_flags_widen_and_label(gp: Project) -> None:
    by_id = {e.edge_id: e.status for e in iter_edges(gp, ALL)}
    rels = {k: v for k, v in by_id.items() if k.startswith("rel_")}
    assert EdgeStatus.INFERRED in rels.values() and EdgeStatus.STALE in rels.values()
    only_inferred = {e.status for e in iter_edges(gp, GraphFilter(include_inferred=True))}
    assert EdgeStatus.INFERRED in only_inferred and EdgeStatus.STALE not in only_inferred
    only_stale = {e.status for e in iter_edges(gp, GraphFilter(include_stale=True))}
    assert EdgeStatus.STALE in only_stale and EdgeStatus.INFERRED not in only_stale


def test_rejected_never_shown(gp: Project) -> None:
    rejected = [e["id"] for e in _doc()["edges"] if e["status"] == "rejected"]
    assert rejected
    shown = {e.edge_id for e in iter_edges(gp, ALL)}
    assert not shown & set(rejected)
    # a cites edge a human rejected after the matcher resolved it disappears the same way
    assert all(e.status is not EdgeStatus.REJECTED for e in iter_edges(gp, ALL))


def test_unconfirmed_idea_not_drawn(gp: Project, agent: Actor) -> None:  # acceptance 12
    papers = _ids("rf:")
    proposed = "ida_01HZX3K4M5N6P7Q8R9S0000299"
    record(
        gp,
        "idea.proposed",
        idea(
            idea_id=proposed,
            name="idea three",
            origin=papers[7],
            members=[papers[7]],
            name_item=ITEM,
        ),
        agent,
    )
    assert proposed not in {n.node_id for n in iter_nodes(gp)}
    assert graph_node(gp, proposed) is None
    assert proposed in {n.node_id for n in iter_nodes(gp, GraphFilter(include_inferred=True))}
    assert graph_node(gp, proposed, GraphFilter(include_inferred=True)) is not None
    assert not any(e.target == proposed or e.source == proposed for e in iter_edges(gp, ALL))


def test_derived_idea_edges_labelled_and_not_stored(gp: Project) -> None:
    derived = [e for e in iter_edges(gp) if e.derived]
    one, two = _ids("ida_")
    assert [(e.source, e.target, e.status) for e in derived] == [(two, one, "derived")]
    with gp.index.connect() as conn:
        stored = conn.execute(
            text("SELECT COUNT(*) FROM graph_edges WHERE edge_id LIKE 'drv:%'")
        ).scalar_one()
    assert stored == 0
    assert not any(e.derived for e in iter_edges(gp, GraphFilter(include_ideas=False)))


def test_unknown_or_merged_node(gp: Project) -> None:  # Review Focus 4
    with pytest.raises(FactoryValidationError) as unknown:
        require_node(gp, "rf:nobody-00000000", "node")
    assert [(i.field, i.reason) for i in unknown.value.issues] == [("node", "node-unknown")]
    one, two = _ids("ida_")
    record(gp, "idea.merged", merge(one, two), gp.human_actor())
    with pytest.raises(FactoryValidationError) as merged:
        require_node(gp, one, "node")
    assert [(i.field, i.reason) for i in merged.value.issues] == [("node", f"idea-merged:{two}")]
    assert require_node(gp, two, "node").members == tuple(
        sorted(set(_doc_members(one)) | set(_doc_members(two)))
    )


def _doc_members(idea_id: str) -> list[str]:
    [members] = [n["members"] for n in _doc()["nodes"] if n["id"] == idea_id]
    return list(members)


def test_relation_to_merged_idea_is_retargeted_and_restored(gp: Project) -> None:
    one, two = _ids("ida_")
    papers = _ids("rf:")
    p4 = papers[3]
    flt = GraphFilter(include_inferred=True)

    def targets() -> list[str]:
        edges = index_neighbours(gp, flt)(p4, "out", frozenset({EdgeType.BUILDS_ON}))
        return [e.target for e in edges if e.edge_id.startswith("rel_")]

    before = targets()
    assert one in before
    record(gp, "idea.merged", merge(one, two), gp.human_actor())
    assert one not in targets() and two in targets()
    into_two = index_neighbours(gp, flt)(two, "in", frozenset({EdgeType.BUILDS_ON}))
    assert any(e.source == p4 and e.target == two for e in into_two)
    record(gp, "idea.unmerged", merge(one, two), gp.human_actor())
    assert targets() == before


def test_iter_edges_streams_in_order(gp: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    whole = list(iter_edges(gp, ALL))
    monkeypatch.setattr(lineage, "GRAPH_PAGE", 3)  # several pages, and a source group cut by one
    assert list(iter_edges(gp, ALL)) == whole
    assert [e.sort_key() for e in whole] == sorted(e.sort_key() for e in whole)
    assert [n.node_id for n in iter_nodes(gp)] == sorted(n.node_id for n in iter_nodes(gp))


def test_status_counts_derived_and_name_filter(gp: Project) -> None:
    status = graph_status(gp)
    assert status.nodes == {"idea": 2, "paper-corpus": 0, "paper-external": 9}
    cites = status.edges["cites"]
    assert (cites["stated"], cites["confirmed"], cites["inferred"]) == (6, 2, 0)
    assert status.edges["builds-on"]["stated"] == 5 and status.edges["builds-on"]["rejected"] == 1
    assert status.edges["builds-on"]["stale"] == 1 and status.edges["builds-on"]["inferred"] == 2
    assert status.edges["improves-on"]["stated"] == 1
    assert "statuses" in status.filter and status.not_stated == 0 and status.uncited_base == 0


def test_every_cites_edge_has_a_resolved_link(gp: Project) -> None:  # acceptance 10 (cites part)
    cites = [e for e in iter_edges(gp, ALL) if e.edge_type is EdgeType.CITES]
    assert cites
    with gp.index.connect() as conn:
        for e in cites:
            assert e.basis is not None
            extraction, ordinal = e.basis.split(":")
            state = conn.execute(
                text("SELECT state FROM reference_links WHERE extraction_id = :x AND ordinal = :o"),
                {"x": extraction, "o": int(ordinal)},
            ).scalar_one()
            assert state == "resolved"
