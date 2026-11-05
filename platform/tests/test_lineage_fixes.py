# ruff: noqa: F401, F811
"""Fix round 1 of G2-D: dedup merges on read, `no_stated_base` reads, one basis read per call,
`cited_by_at_least` honouring the filter."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.lineage.graph import GraphFilter
from factory.model.lineage import EdgeType, RelationProposal
from factory.services import relations
from factory.services.context import Project
from factory.services.contributions import final_items
from factory.services.lineage import (
    graph_node,
    graph_query,
    graph_status,
    index_neighbours,
    iter_edges,
    iter_nodes,
    no_stated_base,
)
from factory.services.relations import propose_relation
from tests.lineage_graph_helpers import record, stand_in_basis, write_fixture
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world

P = {n: f"rf:p{n}-{n:08x}" for n in range(1, 10)}
REL7 = "rel_01HZX3K4M5N6P7Q8R9S0000107"
MERGE = "mrg_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ALL = GraphFilter(include_inferred=True, include_stale=True)


@pytest.fixture
def gp(project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> Project:
    stand_in_basis(monkeypatch)
    write_fixture(project, agent)
    return project


def _works(project: Project, *ids: str) -> None:
    with project.index.connect() as conn:
        for work in ids:
            conn.execute(
                text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, :d, 'x')"),
                {"w": work, "d": json.dumps({"title": "An invented title"})},
            )
        conn.commit()


def _merge(project: Project, primary: str, *absorbed: str) -> None:
    record(
        project,
        "dedup.merged",
        {
            "merge_id": MERGE,
            "primary": primary,
            "absorbed": sorted(absorbed),
            "rule": "doi",
            "records": 2,
        },
        project.system_actor(),
    )


def _unmerge(project: Project) -> None:
    record(
        project,
        "dedup.reverted",
        {"merge_id": MERGE, "reason": "test", "manual": False},
        project.system_actor(),
    )


# --- 1. works absorbed by a dedup merge read as their primary ---


def test_edges_of_an_absorbed_work_appear_on_the_primary(gp: Project) -> None:
    primary, absorbed = P[2], P[6]  # p6 improves on p5 and cites p5
    _works(gp, primary, absorbed)
    flt = ALL

    def seen() -> tuple[list[str], list[str], list[str]]:
        nb = index_neighbours(gp, flt)
        out = nb(primary, "out", frozenset(EdgeType))
        into = nb(P[5], "in", frozenset({EdgeType.IMPROVES_ON, EdgeType.CITES}))
        return (
            sorted(e.edge_id for e in out if e.edge_type is not EdgeType.BUILDS_ON),
            sorted(e.source for e in into),
            sorted(n.node_id for n in iter_nodes(gp, flt)),
        )

    before = seen()
    assert absorbed in before[2] and REL7 not in before[0]
    _merge(gp, primary, absorbed)
    after = seen()
    assert REL7 in after[0]  # the absorbed work's improves-on edge is now the primary's
    assert absorbed not in after[1] and primary in after[1]
    assert absorbed not in after[2] and primary in after[2]
    assert absorbed not in {e.source for e in iter_edges(gp, flt)}
    assert absorbed not in {e.target for e in iter_edges(gp, flt)}
    node = graph_node(gp, absorbed, flt)
    assert node is not None and node.node_id == primary and node.scope == "corpus"
    status = graph_status(gp)
    assert status.nodes["paper-corpus"] == 1 and status.nodes["paper-external"] == 7
    _unmerge(gp)
    assert seen() == before
    assert graph_status(gp).nodes == {"idea": 2, "paper-corpus": 2, "paper-external": 7}


def test_edge_to_an_absorbed_work_is_retargeted(gp: Project) -> None:
    primary, absorbed = P[3], P[4]  # p5 builds on p3; p4 builds on p3 (confirmed)
    _works(gp, primary)
    _merge(gp, primary, absorbed)
    into = index_neighbours(gp)(primary, "in", frozenset({EdgeType.BUILDS_ON}))
    assert {e.source for e in into} >= {P[5]}
    ends = {e.target for e in iter_edges(gp)} | {e.source for e in iter_edges(gp)}
    assert absorbed not in ends


# --- 2. no_stated_base: links are read by key, the outside-corpus case ---


def test_no_stated_base_outside_corpus_and_absorbed_duplicate(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    assert lin.source in no_stated_base(project).no_relation
    with project.index.connect() as conn:
        conn.execute(text("DELETE FROM works WHERE work_id = :w"), {"w": lin.target5})
        conn.commit()
    outside = no_stated_base(project)
    assert lin.source in outside.target_outside_corpus
    # the cited work is a duplicate of a corpus work: it reads as that work, so it is in the corpus
    keeper = lin.target3
    _merge(project, keeper, lin.target5)
    merged = no_stated_base(project)
    assert lin.source in merged.no_relation and lin.source not in merged.target_outside_corpus


# --- 3. one basis read per service call ---


def test_basis_parameters_are_read_once_per_call(
    project: Project, agent: Actor, lin: Lineage, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=lin.source, target=lin.target5, edge_type="builds-on", basis_item=lin.base
        ),
    )
    calls: list[int] = []
    real = relations.final_items

    def counting(p: Project) -> list[object]:
        calls.append(1)
        return real(p)  # type: ignore[return-value]

    monkeypatch.setattr(relations, "final_items", counting)
    graph_query(project, "ancestors", node=lin.source, depth=3)
    assert len(calls) <= 1
    calls.clear()
    graph_status(project)
    assert len(calls) <= 1
    calls.clear()
    graph_node(project, lin.source)
    assert calls == []  # a node lookup needs no relation status
    calls.clear()
    graph_query(project, "path", node=lin.source, target=lin.target5)
    assert len(calls) <= 1


def test_unstubbed_graph_query_timing(
    project: Project, agent: Actor, lin: Lineage, capsys: pytest.CaptureFixture[str]
) -> None:
    propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=lin.source, target=lin.target5, edge_type="builds-on", basis_item=lin.base
        ),
    )
    start = time.perf_counter()
    graph_query(project, "ancestors", node=lin.source, depth=3)
    elapsed = time.perf_counter() - start
    final_items(project)  # warm
    start = time.perf_counter()
    items = len(final_items(project))
    read = time.perf_counter() - start
    with capsys.disabled():
        print(
            f"\nunstubbed graph_query: {elapsed:.3f}s; one final_items read: {read:.3f}s "
            f"for {items} items"
        )
    assert elapsed < 5


# --- 5. cited_by_at_least honours the filter ---


def test_cited_by_at_least_honours_the_filter(gp: Project) -> None:
    assert graph_query(gp, "cited_by_at_least", k=3).nodes
    off = graph_query(
        gp, "cited_by_at_least", k=3, flt=GraphFilter(edge_types=(EdgeType.BUILDS_ON,))
    )
    assert off.nodes == []
