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
