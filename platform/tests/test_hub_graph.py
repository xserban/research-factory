"""Hub graph analytics (plan hub-ui, step 7): hand-built graphs with answers computed by hand."""

from __future__ import annotations

import json
import math
import random

from factory.services import hub_graph as hg
from factory.services.context import Project
from tests.test_references_index import FUZZY, _extract, _resolve
from tests.test_references_model import CITED, WORK, resolution


def g(edges: list[tuple[str, str]], dates: dict[str, str] | None = None) -> hg.CitationGraph:
    return hg.make_graph(dates or {}, edges)


def test_make_graph_dedupes_and_drops_self_loops() -> None:
    graph = hg.make_graph(["c"], [("a", "b"), ("a", "b"), ("c", "c")])
    assert graph.edges == (("a", "b"),)
    assert set(graph.nodes) == {"a", "b", "c"}


def test_foundations_exclude_corpus_and_rank_by_distinct_citers_ties_by_id() -> None:
    graph = g(
        [
            ("c1", "x"),
            ("c2", "x"),
            ("c3", "x"),
            ("c1", "y"),
            ("c2", "y"),
            ("c1", "w"),
            ("c2", "w"),
            ("c1", "c2"),
            ("c3", "c2"),
            ("o", "x"),
        ]  # c2 is a corpus work cited twice; o is outside
    )
    out = hg.foundations(graph, ["c1", "c2", "c3"])
    assert [f.id for f in out] == ["x", "w", "y"]  # 3 citers, then 2 and 2 by id
    assert "c2" not in {f.id for f in out}
    assert out[0].citing == ("c1", "c2", "c3") and out[0].count == 3
    assert out[0].share == 1.0 and out[1].share == 2 / 3
    assert len(hg.foundations(graph, ["c1", "c2", "c3"], top=1)) == 1


def test_foundations_empty_corpus() -> None:
    assert hg.foundations(g([("a", "b")]), []) == []


def test_coupling_counts_and_salton_cosine() -> None:
    graph = g(
        [
            ("A", "x"),
            ("A", "y"),
            ("A", "z"),
            ("B", "x"),
            ("B", "y"),
            ("B", "w"),
            ("C", "z"),
            ("D", "x"),
            ("D", "y"),
        ]
    )
    res = hg.coupling(graph, list("ABCD"))
    got = {(p.a, p.b): (p.shared, p.cosine) for p in res.pairs}
    assert set(got) == {("A", "B"), ("A", "D"), ("B", "D")}  # A-C shares only z
    assert got[("A", "B")] == (2, 2 / math.sqrt(9))
    assert got[("A", "D")][0] == 2 and math.isclose(got[("A", "D")][1], 2 / math.sqrt(6))
    assert math.isclose(got[("B", "D")][1], 2 / math.sqrt(6))
    loose = hg.coupling(graph, list("ABCD"), min_shared=1)
    assert ("A", "C") in {(p.a, p.b) for p in loose.pairs}


def _two_clusters() -> tuple[list[tuple[str, str]], dict[str, str]]:
    edges = [(f"a{i}", r) for i in (1, 2, 3) for r in ("r1", "r2")]
    edges += [(f"b{i}", r) for i in (1, 2, 3) for r in ("r3", "r4")]
    edges += [("lone", "r9")]
    labels = {"a1": "rl", "a2": "rl", "a3": "gen", "b1": "gen", "b2": "gen", "b3": "gen"}
    return edges, labels


def test_schools_find_two_clusters_with_dominant_label() -> None:
    edges, labels = _two_clusters()
    corpus = ["a1", "a2", "a3", "b1", "b2", "b3", "lone"]
    out = hg.schools(hg.coupling(g(edges), corpus), labels)
    assert [s.members for s in out[:2]] == [("a1", "a2", "a3"), ("b1", "b2", "b3")]
    assert out[0].dominant_label == "rl" and math.isclose(out[0].dominant_share, 2 / 3)
    assert out[1].dominant_label == "gen" and out[1].dominant_share == 1.0
    assert out[0].top_refs == (("r1", 3), ("r2", 3))
    assert out[-1].id == hg.UNCLUSTERED and out[-1].members == ("lone",)
    assert out[-1].dominant_label is None


def test_schools_deterministic_across_runs_and_input_order() -> None:
    edges, labels = _two_clusters()
    corpus = ["a1", "a2", "a3", "b1", "b2", "b3", "lone"]
    first = hg.schools(hg.coupling(g(edges), corpus), labels)
    assert first == hg.schools(hg.coupling(g(edges), corpus), labels)
    shuffled = edges[:]
    random.Random(7).shuffle(shuffled)
    assert first == hg.schools(hg.coupling(g(shuffled), corpus[::-1]), labels)


def test_schools_bridge_graph_is_stable() -> None:
    edges = [(f"n{i}", f"r{j}") for i in range(6) for j in (i % 3, (i + 1) % 3)]
    corpus = [f"n{i}" for i in range(6)]
    runs = {repr(hg.schools(hg.coupling(g(edges), corpus, 1), None, seed=3)) for _ in range(3)}
    assert len(runs) == 1


DAG = [("B", "A"), ("C", "A"), ("D", "B"), ("D", "C"), ("E", "D")]  # (citing, cited)


def test_main_path_spc_on_known_dag() -> None:
    mp = hg.main_path(g(DAG), list("ABCDE"))
    # flow A->B, A->C, B->D, C->D, D->E; two source-to-sink paths, both through D->E
    assert dict(mp.spc) == {
        ("A", "B"): 1,
        ("A", "C"): 1,
        ("B", "D"): 1,
        ("C", "D"): 1,
        ("D", "E"): 2,
    }
    assert mp.path == ("A", "B", "D", "E")  # tie A->B vs A->C by id
    assert mp.dropped == ()


def test_main_path_prefers_heavier_branch_and_ignores_outside_edges() -> None:
    # F and G also cite B, so B carries more paths than C
    edges = [*DAG, ("F", "B"), ("G", "B"), ("A", "OUT")]
    mp = hg.main_path(g(edges), list("ABCDEFG"))
    assert mp.spc[("A", "B")] == 1 * (1 + 1 + 1)  # B reaches sinks D->E... via D, F, G: 3 paths
    assert mp.spc[("A", "C")] == 1 * 1
    assert mp.path[:2] == ("A", "B")
    assert all("OUT" not in e for e in mp.spc)


def test_main_path_breaks_cycle_by_date_and_reports() -> None:
    graph = g(
        [("X", "Y"), ("Y", "X"), ("Z", "Y")],
        {"X": "2020-01", "Y": "2021-01-05", "Z": "2022"},
    )
    mp = hg.main_path(graph, ["X", "Y", "Z"])
    assert mp.dropped == (("X", "Y"),)  # X (2020) cannot cite the later Y
    assert dict(mp.spc) == {("X", "Y"): 1, ("Y", "Z"): 1}
    assert mp.path == ("X", "Y", "Z")


def test_main_path_empty_and_big_integers() -> None:
    assert hg.main_path(g([]), ["a"]).path == ()
    # a ladder of diamonds makes 2**69 paths: no overflow with ints
    edges: list[tuple[str, str]] = []
    nodes = ["s"]
    for i in range(70):
        a, b, j = f"a{i}", f"b{i}", f"j{i}"
        prev = nodes[-1]
        edges += [(a, prev), (b, prev), (j, a), (j, b)]
        nodes.append(j)
    corpus = [n for e in edges for n in e]
    mp = hg.main_path(g(edges), corpus)
    assert max(mp.spc.values()) == 2**69


def test_river_lag_in_months() -> None:
    graph = g(
        [("p", "q"), ("p", "r"), ("p", "out")],
        {"p": "2021-05-20", "q": "2020-11", "r": "2021", "out": "2019"},
    )
    arcs = hg.river(graph, ["p", "q", "r"])
    assert [(a.cited, a.lag_months) for a in arcs] == [("q", 6), ("r", 4)]
    assert hg.river(g([("p", "q")]), ["p", "q"])[0].lag_months is None
    assert hg.river(graph, ["p", "q"], {"p": "2022-01", "q": "2022-01"})[0].lag_months == 0


def test_landscape_first_ring_and_hidden_counts() -> None:
    graph = g([("c1", "x"), ("c2", "x"), ("c1", "y"), ("c1", "c2")], {"c1": "2020-03"})
    land = hg.landscape(graph, ["c1", "c2"], {"c1": "s1"}, {"c2": "rl"})
    assert [n.id for n in land.nodes] == ["c1", "c2", "x"]
    by = {n.id: n for n in land.nodes}
    assert by["x"].in_degree == 2 and not by["x"].in_corpus
    assert by["c1"].out_degree == 3 and by["c1"].year == 2020 and by["c1"].cluster == "s1"
    assert by["c2"].label == "rl"
    assert land.hidden_nodes == 1 and land.hidden_edges == 1 and land.ring_min == 2
    assert set(land.edges) == {("c1", "x"), ("c2", "x"), ("c1", "c2")}
    full = hg.landscape(graph, ["c1", "c2"], full=True)
    assert full.hidden_nodes == 0 and len(full.nodes) == 4 and full.full


def test_landscape_caps_node_count_by_raising_ring_threshold() -> None:
    edges = [(c, "x") for c in ("c1", "c2", "c3")] + [(c, "y") for c in ("c1", "c2")]
    land = hg.landscape(g(edges), ["c1", "c2", "c3"], max_nodes=4)
    assert [n.id for n in land.nodes if not n.in_corpus] == ["x"]
    assert land.ring_min == 3 and land.hidden_nodes == 1
    tiny = hg.landscape(g(edges), ["c1", "c2", "c3"], max_nodes=3)
    assert all(n.in_corpus for n in tiny.nodes)


def test_reference_health_counts_states_and_flags_missing() -> None:
    rows = [("a", "resolved"), ("a", "resolved"), ("a", "unconfirmed"), ("b", "unresolved")]
    rows += [("zz", "resolved")]  # not in corpus
    out = hg.reference_health(rows, ["b", "a", "c"])
    assert [h.work_id for h in out] == ["a", "b", "c"]
    assert out[0].counts == {"resolved": 2, "ambiguous": 0, "unconfirmed": 1, "unresolved": 0}
    assert out[0].total == 3 and out[0].has_extraction and not out[2].has_extraction
    tot = hg.health_totals(out)
    assert tot["resolved"] == 2 and tot["unresolved"] == 1 and tot["works_without_extraction"] == 1


def test_loaders_and_payload_on_a_small_project(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1, confidence="identifier"), FUZZY])
    project.index.sync()
    graph = hg.load_citation_graph(project)
    assert graph.edges == ((WORK, CITED),)  # unconfirmed link is no edge
    assert hg.load_reference_rows(project) == [(WORK, "resolved"), (WORK, "unconfirmed")]
    payload = hg.graph_payload(project, [WORK], {WORK: "rl"})
    json.dumps(payload)
    assert payload["landscape"]["total_edges"] == 1
    assert payload["reference_health"]["totals"]["unconfirmed"] == 1
    assert set(payload["methods"]) >= {"landscape", "main_path", "reference_health"}
