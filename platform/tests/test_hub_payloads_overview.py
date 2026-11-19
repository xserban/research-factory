"""Hub overview payload, cited-here counts and the facts they lead with (plan hub-ui, step 3)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.services import hub_payloads as hp
from factory.services.context import Project
from factory.services.hub_graph import CitationGraph, load_citation_graph, make_graph
from factory.services.prisma import prisma_flow
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor
from tests.test_hub_payloads_flow import _miner_row, listed_miners  # noqa: F401

# ---------------------------------------------------------------- cited here


def test_cited_here_counts_distinct_included_citers_and_ignores_loops() -> None:
    g = make_graph(
        ["a", "b", "c", "d", "out"],
        [("b", "a"), ("c", "a"), ("a", "a"), ("out", "a"), ("a", "b"), ("c", "b")],
    )
    got = hp.cited_here_from(g, ["a", "b", "c", "d"])
    assert got["a"].count == 2 and got["a"].citers == ("b", "c")  # not 'out', not itself
    assert got["b"].count == 2
    assert got["c"].count == 0 and got["d"].count == 0
    assert set(got) == {"a", "b", "c", "d"}


def test_cited_here_counts_a_pair_once() -> None:
    g = CitationGraph({"a": None, "b": None}, (("b", "a"), ("b", "a")))  # duplicated edge row
    assert hp.cited_here_from(g, ["a", "b"])["a"].count == 1


def test_self_citation_share_uses_shared_author_names() -> None:
    g = make_graph(["a", "b", "c"], [("b", "a"), ("c", "a")])
    names = {"a": frozenset({"lee a"}), "b": frozenset({"lee a", "x y"}), "c": frozenset({"q r"})}
    got = hp.cited_here_from(g, ["a", "b", "c"], names)["a"]
    assert (got.count, got.self_count) == (2, 1)
    assert hp.cited_here_from(g, ["a", "b", "c"])["a"].self_count == 0  # no names: none


def _work(project: Project, wid: str, title: str, published: str, authors: list[str]) -> None:
    data = {
        "title": title,
        "dates": {"published": published},
        "authors": [{"name": n} for n in authors],
    }
    with project.index._engine.begin() as conn:
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, :d, 'e')"),
            {"w": wid, "d": json.dumps(data)},
        )


def _edge(project: Project, a: str, b: str, live: int = 1) -> None:
    with project.index._engine.begin() as conn:
        for n in (a, b):
            conn.execute(
                text(
                    "INSERT INTO graph_nodes (node_id, node_type, event_id) "
                    "VALUES (:n, 'paper', 'e') "
                    "ON CONFLICT (node_id) DO NOTHING"
                ),
                {"n": n},
            )
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, live, "
                "flags, event_id) VALUES (:i, 'cites', :a, :b, 'stated', :l, '', 'e')"
            ),
            {"i": f"cit:{a}:{b}", "a": a, "b": b, "l": live},
        )


def test_cited_here_from_the_live_graph_and_author_names(project: Project) -> None:
    _work(project, "rf:a", "A", "2025-01-01", ["Ann Lee"])
    _work(project, "rf:b", "B", "2025-02-01", ["Ann Lee"])
    _work(project, "rf:c", "C", "2025-03-01", ["Bo Wu"])
    _edge(project, "rf:b", "rf:a")
    _edge(project, "rf:c", "rf:a")
    _edge(project, "rf:c", "rf:b", live=0)  # a stale link is no citation
    got = hp.cited_here(project, ["rf:a", "rf:b", "rf:c"])
    assert got["rf:a"].count == 2 and got["rf:a"].self_count == 1
    assert got["rf:b"].count == 0
    # the same source as the Graph page
    graph = load_citation_graph(project)
    assert {k: v.count for k, v in got.items()} == {
        w: sum(1 for s, t in graph.edges if t == w) for w in got
    }


# ---------------------------------------------------------------- small facts


def test_human_share_ignores_uncoded_in_the_denominator() -> None:
    h = hp.human_share({"a": "none", "b": "none", "c": "sets-goal", "d": None})
    assert (h["coded"], h["none"], h["not_coded"]) == (3, 2, 1)
    assert h["share_none"] == pytest.approx(2 / 3)
    assert h["by_value"] == {"none": 2, "sets-goal": 1}
    assert hp.human_share({})["share_none"] is None


def test_month_counts_are_continuous_and_name_the_busiest() -> None:
    m = hp.month_counts(["2025-11", "2026-01", "2026-01", "2025-11", "2025-11", ""])
    assert m["months"] == ["2025-11", "2025-12", "2026-01"]
    assert m["counts"] == [3, 0, 2]
    assert m["busiest"] == {"month": "2025-11", "n": 3}
    assert hp.month_counts([])["months"] == []
    assert m["unknown_date"] == 1 and m["year_only"] == 0


def test_month_counts_account_for_year_only_and_unknown_dates() -> None:
    m = hp.month_counts(["2025-11", "2025", "2024", "", "garbage"])
    assert (m["year_only"], m["unknown_date"], sum(m["counts"])) == (2, 2, 1)
    only = hp.month_counts(["2025", ""])  # nothing dated to a month: still stated
    assert only["months"] == [] and (only["year_only"], only["unknown_date"]) == (1, 1)
    assert hp.month_counts([])["unknown_date"] == 0


def test_pipeline_strip_without_a_full_text_stage_states_it() -> None:
    ft = SimpleNamespace(stage_run=False, sought=0, assessed=0)
    prisma = SimpleNamespace(
        full_text=ft,
        identified_databases={"x": 10},
        identified_other={},
        screened=8,
        duplicates_removed=2,
        included=5,
    )
    sets = SimpleNamespace(included=("a", "b", "c"))
    strip = {
        s["key"]: s for s in hp.pipeline_strip(cast(Any, SimpleNamespace(prisma=prisma, sets=sets)))
    }
    assert strip["sought"]["not_run"] and strip["assessed"]["not_run"]
    assert strip["sought"]["n"] is None and strip["included"]["of"] == 8
    assert strip["included"]["n"] == 3


def test_self_loops_are_dropped_by_the_guard_itself() -> None:
    # built without make_graph, so the loop is still in the edges
    g = CitationGraph({"a": None, "b": None}, (("a", "a"), ("b", "a")))
    got = hp.cited_here_from(g, ["a", "b"])
    assert got["a"].count == 1 and got["a"].citers == ("b",)


# ---------------------------------------------------------------- on a screened project


def _field(project: Project, eid: str, name: str, value: str) -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_fields (extraction_id, field, value, reported_in, "
                "copy_marker, reproduced) VALUES (:e, :f, :v, 'x', 0, 0)"
            ),
            {"e": eid, "f": name, "v": value},
        )


def test_overview_facts_equal_their_sources(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    listed_miners: None,  # noqa: F811
) -> None:
    _ft_world(project, agent, human, mock_sources)
    flow = prisma_flow(project)
    base = hp.load_flow_data(project)
    inc = list(base.sets.included)
    assert len(inc) >= 3
    # two included works carry a human position; the first is excluded-at-FT-free, the third unread
    for i, (wid, val) in enumerate([(inc[0], "none"), (inc[1], "sets-goal")]):
        _miner_row(project, f"mm{i}", wid, "m-mapping@1")
        _field(project, f"mm{i}", "human_position", val)
    ex = next(r.work_id for r in base.rows if r.ft_outcome == "excluded")
    _miner_row(project, "mx", ex, "m-mapping@1")
    _field(project, "mx", "human_position", "none")  # excluded: must not count
    # citations among included works (held-out seeds, if any, are in the set like any other work)
    _edge(project, inc[1], inc[0])
    _edge(project, inc[2], inc[0])
    _edge(project, ex, inc[0])  # a non-included citer
    data = hp.load_flow_data(project)
    out = hp.overview_payload(project, data)

    lead = out["lead"]
    assert lead["included"] == len(inc) == flow.included_in_review
    assert lead["screened"] == flow.screened
    assert lead["identified"] == out["pipeline"][0]["n"]
    assert lead["read_in_full"] == len(data.sets.read_in_full) == 3
    assert (lead["human"]["coded"], lead["human"]["none"]) == (2, 1)
    assert lead["human"]["not_coded"] == len(inc) - 2
    assert lead["human"]["share_none"] == 0.5

    strip = {s["key"]: s for s in out["pipeline"]}
    assert strip["screened"]["n"] == flow.screened
    assert strip["screened"]["loss"]["duplicates"] == flow.duplicates_removed
    assert strip["sought"]["n"] == flow.full_text.sought
    assert strip["assessed"]["n"] == flow.full_text.assessed
    assert strip["assessed"]["loss"] == {
        "not_retrieved": flow.full_text.not_retrieved,
        "pending": flow.full_text.pending,
    }
    assert strip["included"]["n"] == len(inc)
    assert strip["included"]["loss"]["excluded_full_text"] == flow.full_text.excluded_total

    assert sum(out["composition"]["layer"].values()) == len(inc)
    assert out["composition"]["human"]["none"] == 1
    assert sum(out["composition"]["human"].values()) == len(inc)
    top = out["most_cited"][0]
    assert top["id"] == inc[0] and top["cited_here"] == 2
    assert out["cited_here"][inc[0]][0] == 2
    assert sum(out["papers_per_month"]["counts"]) <= len(inc)
    assert out["sets"]["not_read_yet"] == [w for w in inc if w not in {inc[0], inc[1]}]
    assert out["sets"]["mined_but_excluded"][0]["work_id"] == ex
    assert isinstance(out["next_actions"], list)
    # the line past PRISMA (parity HM-4) and the top-50 columns (CT-3)
    line = {s["key"]: s for s in out["line"]}
    assert list(line) == ["converted", "mined", "synthesised", "reported"]
    assert line["converted"]["n"] == flow.full_text.eligible
    assert line["mined"]["n"] == 3 and line["synthesised"]["n"] == 0
    assert top["year"] is None or isinstance(top["year"], int)
    assert {"external", "self_cited"} <= set(top) and len(out["most_cited"]) <= hp.MOST_CITED
    assert "line" in out["methods"] and "most_cited" in out["methods"]
    json.dumps(out)  # JSON-safe


def test_overview_without_a_listed_human_miner_leaves_values_uncoded(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    out = hp.overview_payload(project)
    assert out["lead"]["human"]["coded"] == 0
    assert out["lead"]["human"]["share_none"] is None
    assert out["lead"]["read_in_full"] == 0
    assert out["sets"]["not_read_yet"] == out["sets"]["included"]
