"""Hub lenses analytics (plan hub-ui, step 6): hand-computed fixtures."""

from __future__ import annotations

import json
import math

import pytest

from factory.services import hub_lenses as L
from factory.services.hub_lenses import LensWork as W


def w(i, y=None, m=None, layer=None, cited=0, **dims):
    return W(i, y, m, layer, dims, cited)


# 2x2: a1 b1 x3, a1 b2 x1, a2 b1 x1, a2 b2 x3, plus one work with no a
FIX = (
    [w(f"p{i}", a="a1", b="b1") for i in range(3)]
    + [w("q", a="a1", b="b2"), w("r", a="a2", b="b1")]
    + [w(f"s{i}", a="a2", b="b2") for i in range(3)]
    + [w("u", a=None, b="b1")]
)


def test_design_matrix_values_and_none():
    m = L.design_matrix(FIX, "a", "b")
    assert m.rows == ["a1", "a2", L.NOT_CODED] and m.cols == ["b1", "b2"]
    assert m.observed == [[3, 1], [1, 3], [1, 0]]
    assert m.n == 9 and m.row_not_coded == 1 and m.col_not_coded == 0
    assert m.row_totals == [4, 4, 1] and m.col_totals == [5, 4]
    assert m.expected[0][0] == pytest.approx(4 * 5 / 9)
    assert m.residuals[0][0] == pytest.approx((3 - 20 / 9) / math.sqrt(20 / 9))
    assert sum(map(sum, m.observed)) == m.n


def test_chains_columns_sum_and_rest():
    ws = [w("1", a="x", b="p"), w("2", a="x", b="q"), w("3", a="y", b="p"), w("4", a="z", b=None)]
    c = L.chains(ws, ["a", "b"], top_k=1)
    assert c.columns[0] == [("x", 2), (L.REST, 2)]
    assert c.columns[1] == [("p", 2), (L.REST, 2)]
    for col in c.columns:
        assert sum(n for _, n in col) == 4
    assert sum(n for _, _, n, _ in c.links[0]) == 4
    assert all(len(ids) == n for _, _, n, ids in c.links[0])
    assert any(k[:3] == ("x", "p", 1) for k in c.links[0])
    assert any(k[:3] == (L.REST, L.REST, 1) for k in c.links[0])


def test_trends_year_half_undated():
    ws = [
        w("1", 2024, 3, a="x"),
        w("2", 2024, 9, a="x"),
        w("3", 2024, 10, a="y"),
        w("4", None, None, a="x"),
    ]
    t = L.trends(ws, "a", "year")
    assert t.periods == ["2024"] and t.counts["2024"] == {"x": 2, "y": 1} and t.undated == 1
    assert t.shares["2024"]["y"] == pytest.approx(1 / 3)
    h = L.trends(ws, "a", "half")
    assert h.periods == ["2024H1", "2024H2"] and h.counts["2024H2"] == {"x": 1, "y": 1}
    with pytest.raises(ValueError):
        L.trends(ws, "a", "month")


def test_icicle_partitions():
    ws = [w("1", layer="core", a="x"), w("2", layer="core", a="y"), w("3", layer="ext", a=None)]
    root = L.icicle(ws, ["layer", "a"])
    assert root.count == 3 and [k.name for k in root.children] == ["core", "ext"]
    core = root.children[0]
    assert core.count == 2 and sum(k.count for k in core.children) == 2
    assert root.children[1].children[0].name == L.NOT_CODED


def test_influence_gini_and_cites():
    ws = [w("a", cited=0), w("b", cited=0), w("c", cited=0), w("d", cited=4)]
    inf = L.influence(ws)
    assert inf.total_citations == 4 and inf.items[0].id == "d" and inf.items[0].share == 1.0
    assert inf.gini == pytest.approx(0.75)
    assert L.influence([w("a"), w("b")]).gini is None
    inf2 = L.influence(ws, {"a": {"d", "x"}, "b": {"d"}, "z": {"d"}})
    assert inf2.items[0].cited_here == 2


def test_association_hand_check():
    perfect = [w(f"p{i}", a="x", b="u") for i in range(5)] + [
        w(f"q{i}", a="y", b="v") for i in range(5)
    ]
    (pair,) = L.association(perfect, ["a", "b"])
    assert pair.n == 10 and pair.v == pytest.approx(1.0)
    indep = [w(f"{a}{b}{i}", a=a, b=b) for a in "xy" for b in "uv" for i in range(3)]
    assert L.association(indep, ["a", "b"])[0].v == pytest.approx(0.0)
    # 2x2 [[3,1],[1,3]]: chi2 = 2, n = 8, phi2 = 0.25, corr = 0.25 - 1/7, rc = kc = 2 - 1/7
    ws = [w(f"i{i}", a="x", b="u") for i in range(3)] + [w("j", a="x", b="v"), w("k", a="y", b="u")]
    ws += [w(f"l{i}", a="y", b="v") for i in range(3)]
    expect = math.sqrt((0.25 - 1 / 7) / (1 - 1 / 7))
    assert L.association(ws, ["a", "b"])[0].v == pytest.approx(expect)


def test_association_uses_only_coded_and_sorts():
    ws = [w("1", a="x", b="u", c=None), w("2", a="y", b="v", c=None), w("3", a="x", b="u", c="k")]
    ps = L.association(ws, ["a", "b", "c"])
    by = {(p.a, p.b): p for p in ps}
    assert by[("a", "b")].n == 3 and by[("a", "c")].n == 1 and by[("a", "c")].v is None
    assert ps[0].v is not None and ps[-1].v is None


def test_adoption():
    recs = [
        ("w1", "s1", "t1", 2024, 2),
        ("w1", "s1", "t1", 2024, 3),
        ("w2", "s1", "t1", 2025, 8),
        ("w2", "s2", "t2", 2025, 8),
        ("w3", "s1", "t9", None, None),
    ]
    a = L.technique_adoption(recs, {"t1": "One", "t2": "Two"})
    assert a.first_seen == {"t1": "2024H1", "t2": "2025H2"}
    assert [c.works for c in a.cells if c.technique == "t1" and c.period == "2024H1"] == [1]
    assert a.works_with_records == 3 and a.undated_records == 1 and a.labels["t1"] == "One"
    assert "3 works" in a.coverage_note and a.unlisted == []
    assert [c.ids for c in a.cells if c.technique == "t1" and c.period == "2024H1"] == [["w1"]]


def test_similar_ordering_and_breakdown():
    ws = [
        w("t", 2024, 2, "core", technique="A", architecture="X", span=None, human="h"),
        w("m1", 2024, 5, "core", technique="A", architecture="X", span=None, human="h"),
        w("m2", 2024, 11, "core", technique="A", architecture="Y", span=None, human="z"),
        w("m3", 2020, 1, "ext", technique="B", architecture="Y", span=None, human="z"),
        w("m0", 2020, 1, "ext", technique="B", architecture="Y", span=None, human="z"),
    ]
    cites = {"t": {"c1", "c2"}, "m3": {"c2", "c9"}, "m0": {"c2"}, "m2": {"c1", "c2"}}
    r = L.similar(ws, cites, "t", k=10)
    ids = [s.id for s in r]
    top = {s.id: s for s in r}
    assert top["m1"].score == 5 and top["m1"].matched_dims == [
        "technique",
        "architecture",
        "human",
        "layer",
        "half",
    ]
    assert (
        top["m2"].matched_dims == ["technique", "layer"]
        and top["m2"].shared_cites == ["c1", "c2"]
        and top["m2"].score == 4
    )
    assert top["m0"].score == 1 and top["m0"].shared_cites == ["c2"]
    assert ids == ["m1", "m2", "m0", "m3"]  # ties m0, m3 by id
    assert len(L.similar(ws, cites, "t", k=2)) == 2


def test_payload_json_safe():
    p = L.lenses_payload(
        FIX,
        matrix_dims=("a", "b"),
        chain_dims=["a", "b"],
        trend_dim="a",
        icicle_dims=["a", "b"],
        assoc_dims=["a", "b"],
        adoption_records=[("w1", "s", "t", 2024, 1)],
    )
    assert json.loads(json.dumps(p))["n"] == 9


def test_payload_matrices_for_every_pair_and_icicle_dims():
    p = L.lenses_payload(
        FIX,
        matrix_dims=("a", "b"),
        chain_dims=["a", "b"],
        trend_dim="a",
        icicle_dims=["a", "b"],
        assoc_dims=["a", "b"],
        matrix_pair_dims=("a", "b", "layer"),
    )
    assert set(p["matrices"]) == {"a|b", "b|a", "a|layer", "layer|a", "b|layer", "layer|b"}
    m = p["matrices"]["a|b"]
    assert m["row_dim"] == "a" and m["col_dim"] == "b" and m["n"] == 9
    assert p["matrices"]["b|a"]["observed"] != [] and p["matrix"] == m
    assert p["icicle"]["dims"] == ["a", "b"]
    assert all(len(ids) == n for col in p["chains"]["links"] for _, _, n, ids in col)


# ---------------------------------------------------------------- results grid, citation rate


def test_results_grid_counts_own_system_rows_by_stage_and_approach() -> None:
    rows = {
        "w1": [
            {"stage": "s1", "approach": "a1", "system_role": "own-system", "evidence_grade": "g1"},
            {"stage": "s1", "approach": "a1", "system_role": "own-system", "evidence_grade": "g2"},
            {"stage": "s1", "approach": "a2", "system_role": "baseline", "evidence_grade": "g1"},
        ],
        "w2": [{"stage": "s2", "approach": "a1", "system_role": "own-system", "value_kind": "k"}],
        "w3": [],
    }
    out = L.results_grid(rows, {"w1": 5, "w2": 1})
    assert out["rows"] == 4 and out["own"] == 3 and out["works_with_rows"] == 2
    assert out["left_out"] == 2  # w1 had 5 rows, 3 are read
    assert out["stages"] == ["s1", "s2"] and out["approaches"] == ["a1"]
    assert out["cells"] == [
        {"stage": "s1", "approach": "a1", "n": 2, "works": ["w1"]},
        {"stage": "s2", "approach": "a1", "n": 1, "works": ["w2"]},
    ]
    assert out["bars"]["system_role"] == [["own-system", 3], ["baseline", 1]]
    assert out["bars"]["evidence_grade"] == [["g1", 2], ["g2", 1]]
    assert out["bars"]["value_kind"] == [["k", 1]]
    json.dumps(out)


def test_results_grid_without_rows_is_empty_and_json_safe() -> None:
    out = L.results_grid({})
    assert out["rows"] == 0 and out["cells"] == [] and out["left_out"] == 0
    json.dumps(out)


def _wc(i: str, year: int | None, by: int | None, per: float | None, ext: int | None = None):
    from factory.services.citations import WorkCitations

    return WorkCitations(i, i, year, by, 0 if by is not None else None, (), per, ext)


def test_citation_rate_ranks_included_works_and_keeps_two_counts_apart() -> None:
    works = [
        _wc("a", 2020, 4, 1.0, ext=900),
        _wc("b", 2024, 3, 1.5),
        _wc("c", 2020, 0, 0.0, ext=5),
        _wc("x", 2020, 9, 9.0),  # not included
        _wc("u", None, 2, None),  # no year: unknown, never zero
    ]
    out = L.citation_rate(
        works,
        {"a", "b", "c", "u"},
        extractions=7,
        entries=70,
        resolved_links=30,
        works_total=10,
        as_of_year=2025,
        top=2,
    )
    assert [r["id"] for r in out["rows"]] == ["b", "a"]
    assert out["rows"][1]["external"] == 900 and out["rows"][1]["cited_by"] == 4
    assert out["unknown"] == 1 and out["included"] == 4
    assert (out["extractions"], out["entries"], out["resolved_links"]) == (7, 70, 30)
    assert out["as_of_year"] == 2025
    json.dumps(out)


def test_citation_rate_without_extractions_has_no_year_and_no_rows() -> None:
    out = L.citation_rate(
        [_wc("a", 2020, None, None)],
        {"a"},
        extractions=0,
        entries=0,
        resolved_links=0,
        works_total=1,
        as_of_year=2025,
    )
    assert out["rows"] == [] and out["as_of_year"] is None and out["unknown"] == 1
