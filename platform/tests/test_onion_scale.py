"""Scale of the onion view (slice 7b, plan V-A, review focus 4, acceptance 17).

A synthetic projection of 100,000 works and 1,000,000 `cites` edges is written straight into the
index tables of an empty, synced project. Ring 2 around a few focus works must finish within 5 s
without loading the graph.
"""

from __future__ import annotations

import random
import time

import pytest
from sqlalchemy import text

from factory.model.views import OnionFilter
from factory.services.onion import onion_view
from tests.helpers import Project

pytestmark = pytest.mark.slow

WORKS = 100_000
EDGES = 1_000_000
LIMIT_SECONDS = 5.0
FOCUS = 100


def _w(i: int) -> str:
    return f"rf:s{i}-{i:08x}"


def test_onion_scale(project: Project) -> None:
    project.index.sync()
    rng = random.Random(11)
    nodes = [{"n": _w(i)} for i in range(WORKS)]
    edges = [
        {
            "id": f"cit:rex_{i:026d}:1",
            "s": _w(rng.randrange(WORKS)),
            "t": _w(rng.randrange(WORKS)),
        }
        for i in range(EDGES)
    ]
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:n, 'paper', 'e')"
            ),
            nodes,
        )
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:n, '{}', 'e')"), nodes
        )
        conn.execute(
            text(
                "INSERT INTO provenance (work_id, run_id, query_id, source, method, raw_blob, at) "
                "VALUES (:n, 'run_x', 'qry_x', 's', 'm', 'b', '2026-01-01T00:00:00+00:00')"
            ),
            nodes,
        )
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, live, "
                "flags, event_id) VALUES (:id, 'cites', :s, :t, 'stated', 1, '[]', 'e')"
            ),
            edges,
        )
        conn.commit()
    # the default focus on a 10^5-work corpus: outcomes are read from ids, never from records
    started = time.perf_counter()
    default = onion_view(project)
    elapsed_default = time.perf_counter() - started
    assert elapsed_default < LIMIT_SECONDS, elapsed_default
    assert default.rings[0].total == 0
    # a focus of 100 works, ring 2 over 10^6 edges
    focus = tuple(_w(i) for i in range(FOCUS))
    started = time.perf_counter()
    view = onion_view(project, OnionFilter(max_ring=2, focus=focus))
    elapsed = time.perf_counter() - started
    assert elapsed < LIMIT_SECONDS, elapsed
    assert [r.distance for r in view.rings] == [0, 1, 2]
    assert view.rings[2].total > view.rings[1].total > view.rings[0].total == FOCUS
    assert all(len(r.nodes) <= 500 for r in view.rings)
