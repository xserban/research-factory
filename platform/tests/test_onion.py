"""The onion view (slice 7b, plan V-A, task 3)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.model.views import OnionFilter
from factory.services import onion
from factory.services.context import Project
from factory.services.depth import DepthIndex
from factory.services.onion import ONION_MAX_RING, VIEW_MAX_NODES, onion_view
from factory.services.views import to_json
from tests.onion_helpers import A, B, F, write_graph
from tests.region_helpers import add_queries, merge_works


@pytest.fixture
def g(project: Project, monkeypatch: pytest.MonkeyPatch) -> Project:
    write_graph(project)
    monkeypatch.setattr(onion, "included_works", lambda _p: list(F))
    return project


def _ids(view_ring: object) -> list[str]:
    return [n.work_id for n in view_ring.nodes]  # type: ignore[attr-defined]


def test_rings_on_fixture(g: Project) -> None:
    v = onion_view(g)
    assert [r.total for r in v.rings] == [3, 4, 5]
    assert sorted(_ids(v.rings[0])) == sorted(F)
    assert sorted(_ids(v.rings[1])) == sorted(A)
    assert sorted(_ids(v.rings[2])) == sorted(B)


def test_undirected_distance(g: Project) -> None:
    v = onion_view(g)
    ring1 = set(_ids(v.rings[1]))
    assert A[0] in ring1  # F1 cites A1
    assert A[1] in ring1  # A2 cites F2: the other direction
    assert A[2] in ring1  # builds-on F3 -> A3
    assert A[3] in ring1  # improves-on A4 -> F3


def test_inferred_edges_only_on_request(g: Project) -> None:
    assert [r.total for r in onion_view(g).rings] == [3, 4, 5]  # B5 is ring 2, via A4
    wide = onion_view(g, OnionFilter(include_inferred=True))
    assert [r.total for r in wide.rings] == [3, 5, 4]
    assert B[4] in _ids(wide.rings[1])  # F2 builds-on B5 (inferred) joins it to ring 1
    assert B[4] not in _ids(onion_view(g).rings[1])
    assert wide.meta.filter["include_inferred"] is True


def test_stale_and_rejected_never_count(g: Project) -> None:
    wide = onion_view(g, OnionFilter(include_inferred=True))
    # F1 -> B2 is stale and F3 -> B1 is rejected: B1 and B2 stay at ring 2 even when widened
    assert B[0] in _ids(wide.rings[2]) and B[1] in _ids(wide.rings[2])
    assert B[0] not in _ids(wide.rings[1]) and B[1] not in _ids(wide.rings[1])


def test_edge_types_restrict_the_edges(g: Project) -> None:
    v = onion_view(g, OnionFilter(edge_types=("cites",)))
    assert set(_ids(v.rings[1])) == {A[0], A[1]}
    assert set(_ids(v.rings[2])) == {B[0], B[1], B[2]}
    assert set(v.edges_considered) == {"cites"}


def test_ring_clamped_with_notice(g: Project) -> None:
    v = onion_view(g, OnionFilter(max_ring=9))
    assert len(v.rings) == ONION_MAX_RING + 1
    assert v.meta.notices[0].code == "ring-clamped"
    assert v.meta.filter["max_ring"] == ONION_MAX_RING


def test_negative_ring_refused(g: Project) -> None:
    with pytest.raises(FactoryValidationError) as err:
        onion_view(g, OnionFilter(max_ring=-1))
    assert err.value.issues[0].field == "max_ring"


def test_counts_complete_when_truncated(g: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    full = onion_view(g)
    monkeypatch.setattr(onion, "VIEW_MAX_NODES", 2)
    cut = onion_view(g)
    assert [r.total for r in cut.rings] == [r.total for r in full.rings]
    assert [r.by_depth for r in cut.rings] == [r.by_depth for r in full.rings]
    assert [len(r.nodes) for r in cut.rings] == [2, 2, 2]
    assert [r.truncated for r in cut.rings] == [True, True, True]
    assert cut.meta.truncated is True and full.meta.truncated is False
    assert VIEW_MAX_NODES == 500


def test_node_order_depth_then_id(g: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    index = DepthIndex(
        screened=frozenset(A),
        extracted=frozenset({A[3], A[1]}),
        verified=frozenset({A[2]}),
    )
    monkeypatch.setattr(onion, "depth_index", lambda _p, agent=False: index)
    ring = onion_view(g).rings[1]
    assert [(n.work_id, n.depth) for n in ring.nodes] == [
        (A[2], "verified"),
        (A[1], "extracted"),
        (A[3], "extracted"),
        (A[0], "screened"),
    ]
    assert ring.by_depth == {"indexed": 0, "screened": 1, "extracted": 2, "verified": 1}


def test_explicit_focus_and_unknown_focus_error(g: Project) -> None:
    v = onion_view(g, OnionFilter(focus=(A[0],), max_ring=1))
    assert _ids(v.rings[0]) == [A[0]]
    assert v.meta.filter["focus"] == [A[0]]
    for bad in (B[4], "rf:nope-00000000"):  # an external work; a work of no kind
        with pytest.raises(FactoryValidationError) as err:
            onion_view(g, OnionFilter(focus=(bad,)))
        assert err.value.issues[0].field == "focus"


@pytest.mark.parametrize(
    "flt",
    [
        OnionFilter(),
        OnionFilter(include_inferred=True),
        OnionFilter(edge_types=("cites",), max_ring=3),
        OnionFilter(edge_types=("builds-on", "improves-on")),
        OnionFilter(max_ring=1, focus=(A[0], B[0])),
    ],
)
def test_set_based_cites_path_agrees_with_the_batched_path(
    g: Project, monkeypatch: pytest.MonkeyPatch, flt: OnionFilter
) -> None:
    fast = to_json(onion_view(g, flt))
    monkeypatch.setattr(onion, "has_active_merges", lambda _conn: True)
    assert to_json(onion_view(g, flt)) == fast


def test_an_active_merge_reads_as_its_primary(g: Project) -> None:
    before = onion_view(g)
    merge_works(g, B[0], B[1])  # B2 is absorbed into B1
    after = onion_view(g)
    assert [r.total for r in after.rings] == [3, 4, 4]
    assert B[1] not in _ids(after.rings[2]) and B[0] in _ids(after.rings[2])
    assert before.rings[2].total == 5


def test_ideas_follow_a_merge_to_the_primary(g: Project) -> None:
    """A is a member of a confirmed idea; A is merged into B; the node B lists the idea."""
    with g.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO ideas (idea_id, name, name_item, origin, decision, event_id) "
                "VALUES ('ida_x', 'n', 'itm_x', :o, 'confirm', 'ev')"
            ),
            {"o": F[0]},
        )
        conn.execute(
            text("INSERT INTO idea_members (idea_id, work_id) VALUES ('ida_x', :w)"), {"w": B[1]}
        )
        conn.commit()
    plain = {n.work_id: n.ideas for n in onion_view(g).rings[2].nodes}
    assert plain[B[1]] == ["ida_x"] and plain[B[0]] == []
    merge_works(g, B[0], B[1])  # B2 is absorbed into B1
    merged = {n.work_id: n.ideas for n in onion_view(g).rings[2].nodes}
    assert merged[B[0]] == ["ida_x"]


PROBE_ONLY = "rf:p0-000000a0"


def _add_probe_only(project: Project) -> None:
    add_queries(project, {"qry_probe": "probe"})
    with project.index.connect() as conn:
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, '{}', 'ev')"),
            {"w": PROBE_ONLY},
        )
        conn.execute(
            text(
                "INSERT INTO provenance (work_id, run_id, query_id, source, method, raw_blob, at) "
                "VALUES (:w, 'run_qry_probe', 'qry_probe', 's', 'm', 'b', "
                "'2026-01-01T00:00:00+00:00')"
            ),
            {"w": PROBE_ONLY},
        )
        conn.commit()


def test_probe_only_work_is_not_a_corpus_work(g: Project) -> None:
    _add_probe_only(g)
    with pytest.raises(FactoryValidationError) as err:
        onion_view(g, OnionFilter(focus=(PROBE_ONLY,)))
    assert err.value.issues[0].field == "focus"


def test_scope_follows_the_corpus_not_the_works_table(g: Project) -> None:
    _add_probe_only(g)
    with g.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:w, 'paper', 'ev')"
            ),
            {"w": PROBE_ONLY},
        )
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, live, "
                "flags, event_id) VALUES ('cit:rex_z:1', 'cites', :s, :t, 'stated', 1, '[]', 'ev')"
            ),
            {"s": F[0], "t": PROBE_ONLY},
        )
        conn.commit()
    ring1 = {n.work_id: n for n in onion_view(g).rings[1].nodes}
    assert ring1[PROBE_ONLY].scope == "external"
    assert ring1[A[0]].scope == "corpus"


def test_node_fields(g: Project) -> None:
    node = onion_view(g).rings[0].nodes[0]
    assert node.title == f"Title of {node.work_id}"
    assert node.year == 2020 and node.scope == "corpus" and node.depth == "indexed"
    external = next(n for n in onion_view(g).rings[2].nodes if n.work_id == B[4])
    assert external.scope == "external" and external.title == "" and external.year is None


def test_no_seed_marker(g: Project) -> None:
    assert "seed" not in to_json(onion_view(g)).lower()


def test_view_writes_nothing(g: Project) -> None:
    path = g.paths.index_path
    before_hash, before = g.index.state_hash(), path.read_bytes()
    onion_view(g)
    assert g.index.state_hash() == before_hash
    assert path.read_bytes() == before
    with g.index.connect() as conn:
        left = conn.execute(text("SELECT name FROM sqlite_temp_master")).all()
    assert left == []


def test_deterministic(g: Project) -> None:
    assert to_json(onion_view(g)) == to_json(onion_view(g))


def test_edges_considered_counts_by_type(g: Project) -> None:
    v = onion_view(g, OnionFilter(max_ring=1))
    # edges incident to ring 0 (F1-F3), shown by default: F1->A1, A2->F2, F3->A3, A4->F3
    assert v.edges_considered == {"builds-on": 1, "cites": 2, "improves-on": 1}
