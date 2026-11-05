"""Scale of the graph queries (slice 3b, plan G2-D, ruling 10).

A synthetic projection of 50,000 papers, 500,000 `cites` and 20,000 lineage edges is written
directly into the index tables of an empty, synced project (no rebuild is triggered). The
queries must stay bounded: each finishes within 2 s without loading the graph.
"""

from __future__ import annotations

import json
import random
import resource
import time
import tracemalloc
from collections.abc import Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import text

from factory.lineage.graph import Graph, GraphEdge, GraphFilter, graph_neighbours
from factory.lineage.paths import MAX_DEPTH, ancestors
from factory.model.lineage import EdgeStatus, EdgeType
from factory.services.context import Project
from factory.services.lineage import graph_query, graph_status, index_neighbours

pytestmark = pytest.mark.slow

PAPERS = 50_000
CITES_PER_PAPER = 10
CHAIN = 10_000
RANDOM_LINEAGE = 10_000
LIMIT_SECONDS = 2.0
T = TypeVar("T")


def _paper(i: int) -> str:
    return f"rf:s{i}-{i:08x}"


def _rel(i: int) -> str:
    return f"rel_{i:026d}"


def _populate(project: Project) -> None:
    rng = random.Random(7)
    nodes = [{"n": _paper(i), "e": "ev"} for i in range(PAPERS)]
    cites: list[dict[str, Any]] = []
    for i in range(PAPERS):
        for ordinal, j in enumerate(rng.sample(range(PAPERS), CITES_PER_PAPER), start=1):
            if j == i:
                continue
            rex = f"rex_{i:026d}"
            cites.append(
                {
                    "id": f"cit:{rex}:{ordinal}",
                    "type": "cites",
                    "s": _paper(i),
                    "t": _paper(j),
                    "st": "stated",
                    "b": f"{rex}:{ordinal}",
                    "rex": rex,
                    "o": ordinal,
                    "d": None,
                }
            )
    lineage: list[tuple[int, str, str]] = []
    for k in range(CHAIN):  # a long chain, so ancestors reach MAX_DEPTH
        lineage.append((k + 1, _paper(k + 1), _paper(k)))
    for k in range(RANDOM_LINEAGE):
        i = rng.randrange(1, PAPERS)
        lineage.append((CHAIN + k + 1, _paper(i), _paper(rng.randrange(0, i))))
    relations = [{"id": _rel(n), "s": s, "t": t, "e": "ev"} for n, s, t in lineage]
    with project.index.connect() as conn:
        conn.execute(
            text("INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:n, 'paper', :e)"),
            nodes,
        )
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, basis, "
                "reference_extraction_id, ordinal, live, decision, flags, event_id) VALUES "
                "(:id, :type, :s, :t, :st, :b, :rex, :o, 1, :d, '[]', 'ev')"
            ),
            cites,
        )
        conn.execute(
            text(
                "INSERT INTO relations (relation_id, source_work, target, edge_type, basis_item, "
                "status, flags, decision, event_id) VALUES "
                "(:id, :s, :t, 'builds-on', NULL, 'inferred', '[]', 'confirm', :e)"
            ),
            relations,
        )
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, basis, "
                "live, decision, flags, event_id) SELECT relation_id, 'builds-on', source_work, "
                "target, 'inferred', NULL, 1, 'confirm', '[]', 'ev' FROM relations"
            )
        )
        conn.commit()


def _timed(fn: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def test_scale_bounded(project: Project) -> None:
    project.index.sync()
    _populate(project)
    project.index.sync()  # no event arrived, so nothing is rebuilt
    flt = GraphFilter()
    tracemalloc.start()
    deep = _paper(CHAIN)

    lookup = index_neighbours(project, flt)
    result, t_ancestors = _timed(lambda: ancestors(lookup, deep, MAX_DEPTH))
    assert result.depth == MAX_DEPTH and not result.truncated
    assert t_ancestors < LIMIT_SECONDS

    found, t_path = _timed(
        lambda: graph_query(project, "path", node=deep, target=_paper(CHAIN - 5))
    )
    assert len(found.nodes) == 6 and t_path < LIMIT_SECONDS

    status, t_status = _timed(lambda: graph_status(project))
    assert status.nodes["paper-external"] == PAPERS
    assert status.edges["builds-on"]["confirmed"] == CHAIN + RANDOM_LINEAGE
    assert t_status < LIMIT_SECONDS

    queried, t_query = _timed(lambda: graph_query(project, "ancestors", node=deep, depth=MAX_DEPTH))
    assert t_query < LIMIT_SECONDS

    # the result equals the pure helper run on the sampled subgraph loaded in memory
    sample = {deep, *(n["id"] for n in queried.nodes)}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT edge_id, source, target FROM graph_edges "
                "WHERE edge_type = 'builds-on' AND source IN (SELECT value FROM json_each(:s))"
            ),
            {"s": json.dumps(sorted(sample))},
        ).all()
    reference = Graph(
        (),
        tuple(
            GraphEdge(
                str(r[0]),
                EdgeType.BUILDS_ON,
                str(r[1]),
                str(r[2]),
                EdgeStatus.CONFIRMED,
                None,
                (),
                False,
            )
            for r in rows
        ),
        flt,
    )
    expected = ancestors(graph_neighbours(reference), deep, MAX_DEPTH)
    assert [n["id"] for n in queried.nodes] == list(expected.nodes)

    traced_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert traced_peak < 100 * 2**20  # the queries hold a few pages, never the graph
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        f"\nscale: ancestors {t_ancestors:.3f}s path {t_path:.3f}s status {t_status:.3f}s "
        f"query {t_query:.3f}s query-phase peak {traced_peak / 2**20:.1f} MiB "
        f"(process peak RSS incl. building the data {peak / 2**20:.0f} MiB)"
    )
