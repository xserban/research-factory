"""JSON and DOT export of the lineage graph (slice 3b, plan G2-D Task 4; acceptance 14)."""

from __future__ import annotations

import json

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.lineage.export import iter_dot, iter_json, subgraph, to_dot, to_json
from factory.lineage.graph import Graph, GraphFilter, graph_neighbours, load_fixture
from factory.lineage.paths import ancestors
from factory.services import lineage
from factory.services.context import Project
from factory.services.lineage import (
    MCP_EXPORT_MAX_EDGES,
    export_edge_count,
    graph_export,
    iter_edges,
)
from tests.lineage_graph_helpers import GRAPH_SMALL, record, stand_in_basis, write_fixture
from tests.lineage_payloads import ITEM, merge, stated

ALL = GraphFilter(include_inferred=True, include_stale=True)
P9 = "rf:p9-00000009"


@pytest.fixture
def g() -> Graph:
    return load_fixture(GRAPH_SMALL, ALL)


@pytest.fixture
def gp(project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> Project:
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    return project


def _ids(doc: dict[str, list[dict[str, str]]], key: str) -> list[str]:
    return [x["id"] for x in doc[key]]


def test_json_shape_and_order(g: Graph) -> None:
    text = to_json(g)
    doc = json.loads(text)
    assert set(doc) == {"filter", "nodes", "edges"} and text.endswith("}\n")
    assert _ids(doc, "nodes") == sorted(_ids(doc, "nodes"))
    keys = [(e["source"], e["type"], e["target"], e["id"]) for e in doc["edges"]]
    assert keys == sorted(keys)
    assert all({"status", "basis"} <= set(e) for e in doc["edges"])
    assert doc["filter"]["include_inferred"] is True
    assert text == json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def test_dot_marks_inferred_dashed_and_labelled(g: Graph) -> None:
    dot = to_dot(g)
    assert 'style=dashed, label="inferred"' in dot
    assert 'style=dotted, label="stale"' in dot
    assert 'style=bold, label="derived"' in dot
    assert 'style=solid, label="confirmed"' in dot
    assert "color=gray" in dot and dot.startswith("digraph lineage {\n")
    assert "shape=box" in dot and "shape=ellipse" in dot
    assert "// filter:" in dot and dot.endswith("}\n")


def test_dot_quotes_and_escapes() -> None:
    from factory.lineage.graph import GraphNode

    node = GraphNode("ida_x", "idea", None, None, 'a "quoted" \\ name', ())
    dot = "".join(iter_dot(GraphFilter(), [node], []))
    assert 'label="a \\"quoted\\" \\\\ name"' in dot


def test_streamed_export_equals_whole_on_fixture(g: Graph) -> None:
    assert "".join(iter_json(g.filter, g.nodes, g.edges)) == to_json(g)
    assert "".join(iter_dot(g.filter, g.nodes, g.edges)) == to_dot(g)


def test_no_quotes_notes_or_entry_text(gp: Project, agent: Actor) -> None:
    secret = "SECRET-NOTE-TEXT"
    record(
        gp,
        "relation.proposed",
        stated(
            relation_id="rel_01HZX3K4M5N6P7Q8R9S0000777",
            source_work="rf:p2-00000002",
            target="rf:p4-00000004",
            basis_item=ITEM,
            note=secret,
            status="inferred",
            status_reason="no-cited-entry",
            resolved_target=None,
            reference_extraction_id=None,
            cited_entry=None,
        ),
        agent,
    )
    for fmt in ("json", "dot"):
        out = graph_export(gp, fmt, flt=ALL)  # type: ignore[arg-type]
        assert ("rel_01HZX3K4M5N6P7Q8R9S0000777" in out) == (fmt == "json")
        assert '"rf:p2-00000002" -> "rf:p4-00000004"' in out or fmt == "json"
        for forbidden in (
            secret,
            "An invented title about kernels",
            "invented rationale",
            "checked",
        ):
            assert forbidden not in out


def test_export_byte_identical_across_rebuilds(gp: Project) -> None:
    before = (graph_export(gp, "json"), graph_export(gp, "dot", flt=ALL))
    gp.index.rebuild()
    assert (graph_export(gp, "json"), graph_export(gp, "dot", flt=ALL)) == before


def test_export_follows_merge_and_unmerge(gp: Project) -> None:  # Review Focus 5
    one, two = (
        n["id"] for n in json.loads(GRAPH_SMALL.read_text())["nodes"] if n["type"] == "idea"
    )
    before = graph_export(gp, "json", flt=ALL)
    record(gp, "idea.merged", merge(one, two), gp.human_actor())
    merged = json.loads(graph_export(gp, "json", flt=ALL))
    assert one not in _ids(merged, "nodes") and two in _ids(merged, "nodes")
    to_idea = [e for e in merged["edges"] if e["id"] == "rel_" + "01HZX3K4M5N6P7Q8R9S0000111"]
    assert [e["target"] for e in to_idea] == [two]
    record(gp, "idea.unmerged", merge(one, two), gp.human_actor())
    assert graph_export(gp, "json", flt=ALL) == before


def test_query_export_is_the_query_subgraph(gp: Project, g: Graph) -> None:
    out = json.loads(graph_export(gp, "json", query="ancestors", node=P9, depth=8))
    expected = ancestors(graph_neighbours(load_fixture(GRAPH_SMALL)), P9, 8)
    assert set(_ids(out, "nodes")) == {P9, *expected.nodes}
    assert set(_ids(out, "edges")) == set(expected.edges)
    assert subgraph(g, [P9], []).nodes[0].node_id == P9
    dot = graph_export(gp, "dot", query="ancestors", node=P9, depth=8)
    assert "digraph lineage" in dot and P9 in dot


def test_export_cap_checked_before_rendering(gp: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("iter_edges must not be called")

    monkeypatch.setattr(lineage, "iter_edges", boom)
    assert export_edge_count(gp, GraphFilter()) > 1
    with pytest.raises(FactoryValidationError) as refused:
        graph_export(gp, "json", max_edges=1)
    assert [(i.field, i.reason) for i in refused.value.issues] == [
        ("query", "too large; use a query or the CLI")
    ]
    assert MCP_EXPORT_MAX_EDGES == 2000
    monkeypatch.undo()
    assert graph_export(gp, "json", max_edges=MCP_EXPORT_MAX_EDGES).endswith("}\n")


def test_export_edge_count_is_exact_here(gp: Project) -> None:
    for flt in (GraphFilter(), ALL, GraphFilter(edge_types=(lineage.EdgeType.CITES,))):
        assert export_edge_count(gp, flt) == len(list(iter_edges(gp, flt)))
