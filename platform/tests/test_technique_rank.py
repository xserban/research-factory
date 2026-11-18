"""Ranking of combination and gap candidates (IDEA-78 ranking): pure builders on plain inputs."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.model.technique_graph import Lens
from factory.services import technique_graph as tg
from factory.services import technique_rank as tr
from factory.services.technique_graph import Inputs, RawRow, StageInfo, WorkMeta

CATALOGUE = {
    "lit-01": ("literature-review", "Citation chasing", "Follows citations."),
    "lit-02": ("literature-review", "Keyword search", "Searches keywords."),
    "ide-01": ("ideation-hypothesis", "Tournament", "Ranks ideas."),
    "ide-02": ("ideation-hypothesis", "Debate", "Agents argue."),
    "exp-01": ("experiment-design", "Tree search", "Searches variants."),
    "exp-02": ("experiment-design", "Citation chasing", "Same name, other stage."),
    "wri-01": ("paper-writing", "Drafting", "Drafts text."),
    "exp-03": ("experiment-design", "Staged experiment tree search", "One stage's version."),
    "imp-01": (
        "implementation-execution",
        "Staged agentic tree search over experiment scripts",
        "Another stage's version.",
    ),
    "oth-01": ("other", "Misc", "Other."),
}


def row(work: str, approach: str, evidence: str | None = "own-ablation") -> RawRow:
    return RawRow(
        approach=approach,
        stage=CATALOGUE[approach][0],
        work_id=work,
        extraction_id=f"rex-{work}-{approach}",
        status="core",
        evidence=evidence,
        described_as=None,
        quote=f"quote {work} {approach}",
        anchor="s1.p1",
        parameters=None,
    )


def inputs(rows: list[RawRow], cites: tuple[tuple[str, str, str], ...] = ()) -> Inputs:
    ids = sorted({r.work_id for r in rows})
    return Inputs(
        catalogue=CATALOGUE,
        rows=tuple(rows),
        stages=(StageInfo("ideation-hypothesis", "m", 1, 0, None, None),),
        works={w: WorkMeta(w, "2024-01-01", 2024, "core") for w in ids},
        cites=cites,
    )


def users(approach: str, works: str, evidence: str | None = "own-ablation") -> list[RawRow]:
    return [row(f"rf:{w}", approach, evidence) for w in works]


def combos(data: Inputs, **kw: object) -> tg.Candidates:  # type: ignore[name-defined]
    args: dict[str, object] = {
        "min_works": 2, "max_co_works": 0, "stage": None, "limit": None,
    }  # fmt: skip
    args.update(kw)
    return tg.build_combinations(data, Lens(), **args)  # type: ignore[arg-type]


BASE = [
    *users("ide-01", "abc"),
    *users("ide-02", "def"),
    *users("exp-01", "ghij"),
    *users("wri-01", "klm"),
    *users("lit-01", "nop", evidence=None),
]


def test_components_are_returned_and_documented() -> None:
    out = combos(inputs(BASE))
    c = next(c for c in out.combinations if (c.a.id, c.b.id) == ("exp-01", "ide-01"))
    s = c.score
    assert s is not None and s.rank_by == "composite"
    assert s.popularity_raw == 3 and 0 < s.popularity <= 1
    assert s.stage_relation == "adjacent"  # ideation then experiment in the lifecycle order
    assert s.stage is not None and s.stage == tr.STAGE_FACTORS["adjacent"]
    assert s.bridge_links == 0 and s.bridge == 0.0
    assert s.evidence == 1.0
    assert s.generic is not None and 0 <= s.generic <= 1
    assert set(s.weights) == set(tr.COMBINATION_WEIGHTS)
    assert s.value == s.composite
    assert abs(sum(tr.COMBINATION_WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(tr.GAP_WEIGHTS.values()) - 1.0) < 1e-9


def test_stage_relations_same_adjacent_distant_and_unordered() -> None:
    assert tr.stage_relation("ideation-hypothesis", "ideation-hypothesis") == "same"
    assert tr.stage_relation("literature-review", "ideation-hypothesis") == "adjacent"
    assert tr.stage_relation("literature-review", "paper-writing") == "distant"
    assert tr.stage_relation("other", "paper-writing") == "unordered"
    assert tr.stage_relation("zzz", "yyy") == "unordered"


def test_popularity_ranking_prefers_established_pairs_and_ties_break_by_id() -> None:
    out = combos(inputs(BASE), rank_by="popularity")
    first = out.combinations[0]
    assert min(first.works_a, first.works_b) == 3
    keys = [(-min(c.works_a, c.works_b), c.a.id, c.b.id) for c in out.combinations]
    assert keys == sorted(keys)
    assert [c.rank for c in out.combinations] == list(range(1, out.total + 1))


def test_composite_differs_from_popularity_when_the_bridge_matters() -> None:
    cites = tuple(("rf:a", f"rf:{w}", f"e{w}") for w in "kl")  # ide-01 users cite wri-01 users
    data = inputs(BASE, cites)
    pop = combos(data, rank_by="popularity")
    comp = combos(data, rank_by="composite")
    ids = lambda o: [(c.a.id, c.b.id) for c in o.combinations]  # noqa: E731
    assert ids(pop) != ids(comp)
    top = comp.combinations[0]
    assert (top.a.id, top.b.id) == ("ide-01", "wri-01")
    assert top.score is not None and top.score.bridge_links == 2 and top.score.bridge > 0


def test_bridge_counts_both_directions_once_per_link() -> None:
    cites = (("rf:a", "rf:k", "e1"), ("rf:l", "rf:b", "e2"), ("rf:a", "rf:z", "e3"))
    out = combos(inputs(BASE, cites), rank_by="bridge")
    top = out.combinations[0]
    assert (top.a.id, top.b.id) == ("ide-01", "wri-01") and top.score
    assert top.score.bridge_links == 2


def test_each_single_component_can_rank_and_unknown_is_refused() -> None:
    data = inputs(BASE)
    for key in ("popularity", "stage", "bridge", "evidence", "generic", "composite"):
        out = combos(data, rank_by=key)
        assert out.parameters["rank_by"] == key and out.total > 0
        assert out.combinations[0].score is not None
        assert out.combinations[0].score.rank_by == key
    with pytest.raises(FactoryValidationError):
        combos(data, rank_by="novelty")


def test_evidence_share_counts_not_stated_as_unsupported() -> None:
    out = combos(inputs(BASE), rank_by="evidence")
    top = out.combinations[0]
    assert top.score is not None and top.score.evidence == 1.0
    lit = next(c for c in out.combinations if "lit-01" in (c.a.id, c.b.id))
    assert lit.score is not None and lit.score.evidence == 0.5


def test_generic_factor_penalises_ubiquitous_approaches() -> None:
    rows = [*users("ide-01", "abcdef"), *users("ide-02", "abcdef"), *users("exp-01", "abc")]
    rows += users("wri-01", "abc") + users("lit-01", "abc")
    out = combos(inputs(rows), max_co_works=9, rank_by="generic")
    by = {(c.a.id, c.b.id): c.score for c in out.combinations}
    assert by[("exp-01", "wri-01")] is not None
    assert by[("exp-01", "wri-01")].generic > by[("ide-01", "ide-02")].generic  # type: ignore[union-attr]


def test_cross_stage_duplicate_names_are_flagged_not_hidden() -> None:
    rows = [*users("lit-01", "abc"), *users("exp-02", "def")]
    out = combos(inputs(rows))
    assert out.total == 1
    assert out.combinations[0].score is not None
    assert "same-name-across-stages" in out.combinations[0].score.flags


def test_top_limit_and_total_and_determinism() -> None:
    data = inputs(BASE)
    full = combos(data)
    cut = combos(data, top=3)
    assert cut.total == full.total and len(cut.combinations) == 3
    assert cut.combinations == full.combinations[:3]
    assert combos(data).model_dump_json() == combos(data).model_dump_json()
    with pytest.raises(FactoryValidationError):
        combos(data, top=0)


def test_statement_labelling_and_supporting_works_and_quotes_for_the_top_few() -> None:
    out = combos(inputs(BASE))
    for i, c in enumerate(out.combinations):
        assert "not co-used in this corpus (exploratory, pass-A rows)" in c.statement
        assert "hypothesis to check" in c.label
        assert c.support_a and c.support_b
        assert set(c.support_a) <= {f"rf:{w}" for w in "abcdefghijklmnop"}
        if i < tr.QUOTE_TOP:
            assert c.quote_a is not None and c.quote_a.quote and c.quote_a.anchor
            assert c.quote_b is not None and c.quote_b.work_id in c.support_b
        else:
            assert c.quote_a is None and c.quote_b is None


def test_a_co_used_pair_does_not_claim_it_is_not_co_used() -> None:
    rows = [*BASE, row("rf:a", "exp-01")]
    out = combos(inputs(rows), max_co_works=1, stage="experiment-design")
    c = next(c for c in out.combinations if (c.a.id, c.b.id) == ("exp-01", "ide-01"))
    assert "not co-used" not in c.statement and "co-used by 1 work" in c.statement


def test_empty_results() -> None:
    out = combos(inputs([]))
    assert out.total == 0 and out.combinations == () and out.exploratory is True
    assert combos(inputs(BASE), min_works=99).total == 0


def test_the_quote_prefers_a_supportive_row() -> None:
    rows = [
        row("rf:a", "ide-01", None),
        row("rf:b", "ide-01", "own-ablation"),
        row("rf:c", "ide-01"),
    ]
    rows += users("wri-01", "def")
    out = combos(inputs(rows))
    assert out.combinations[0].quote_a is not None
    assert out.combinations[0].quote_a.evidence == "own-ablation"


# --- gaps ------------------------------------------------------------------------------------


def gaps(data: Inputs, **kw: object) -> tg.Candidates:  # type: ignore[name-defined]
    args: dict[str, object] = {
        "from_stage": "ideation-hypothesis", "to_stage": "experiment-design",
        "min_works": 2, "max_to_share": 0.5, "limit": None,
    }  # fmt: skip
    args.update(kw)
    return tg.build_gaps(data, Lens(), **args)  # type: ignore[arg-type]


GAPROWS = [
    *users("ide-01", "abcd"),
    *users("ide-02", "ef"),
    *users("exp-01", "ax"),
]


def test_gap_components_and_ordering() -> None:
    out = gaps(inputs(GAPROWS))
    top = out.gaps[0]
    assert top.score is not None and top.rank == 1
    assert set(top.score.weights) == set(tr.GAP_WEIGHTS)
    assert top.score.popularity_raw == len(top.works)
    assert top.score.strength == pytest.approx(1 - len(top.works_with_to_stage) / len(top.works))
    assert [g.approach.id for g in out.gaps] == ["ide-01", "ide-02"]  # 4 works beat 2, both gaps


def test_gap_bridge_counts_citations_to_to_stage_works() -> None:
    cites = (("rf:e", "rf:a", "e1"), ("rf:f", "rf:x", "e2"), ("rf:a", "rf:x", "e3"))
    out = gaps(inputs(GAPROWS, cites), rank_by="bridge")
    by = {g.approach.id: g.score for g in out.gaps}
    assert by["ide-02"] is not None and by["ide-02"].bridge_links == 2  # e -> a, f -> x
    assert by["ide-01"] is not None and by["ide-01"].bridge_links == 1  # a -> x
    assert out.gaps[0].approach.id == "ide-02" and out.gaps[0].rank == 1


def test_gap_rank_by_limit_labels_statement_and_quote() -> None:
    data = inputs(GAPROWS)
    for key in ("popularity", "strength", "bridge", "composite"):
        out = gaps(data, rank_by=key)
        assert out.parameters["rank_by"] == key
    with pytest.raises(FactoryValidationError):
        gaps(data, rank_by="stage")
    out = gaps(data, top=1)
    assert out.total == 2 and len(out.gaps) == 1
    g = out.gaps[0]
    assert "hypothesis to check" in g.label
    assert "no row at experiment-design" in g.statement or "have a row at" in g.statement
    assert "exploratory, pass-A rows" in g.statement
    assert g.quote is not None and g.quote.work_id in g.works


def test_gaps_empty_and_deterministic() -> None:
    assert gaps(inputs([])).total == 0
    d = inputs(GAPROWS)
    assert gaps(d).model_dump_json() == gaps(d).model_dump_json()


def test_a_pairs_score_does_not_depend_on_the_threshold_when_the_pool_maximum_is_fixed() -> None:
    rows = [*BASE, *users("lit-02", "qr")]  # a two-work approach drops out at min_works=3
    wide = combos(inputs(rows), min_works=2)
    narrow = combos(inputs(rows), min_works=3)
    by_wide = {(c.a.id, c.b.id): c.score for c in wide.combinations}
    assert narrow.total < wide.total
    for c in narrow.combinations:
        assert by_wide[(c.a.id, c.b.id)] == c.score
    kept = [(c.a.id, c.b.id) for c in wide.combinations if min(c.works_a, c.works_b) >= 3]
    assert kept == [(c.a.id, c.b.id) for c in narrow.combinations]


# --- log-scale bridge and name lookalikes ------------------------------------------------------


def test_bridge_is_log_scaled_and_does_not_saturate_at_one_link_per_work() -> None:
    import math

    assert tr.bridge_norm(0, 5) == 0.0 and tr.bridge_norm(3, 0) == 0.0
    assert tr.bridge_norm(1, 3) == pytest.approx(math.log(2) / math.log(4))
    assert tr.bridge_norm(2, 3) < 1.0  # the old min(1, links/works) gave 0.67; 3 of 3 is 1.0
    assert tr.bridge_norm(2, 3) > tr.bridge_norm(1, 3)
    assert tr.bridge_norm(30, 100) < 1.0  # the old form gave 0.3, a link per 3 works
    assert tr.bridge_norm(99, 3) == 1.0  # capped
    cites = tuple(("rf:a", f"rf:{w}", f"e{w}") for w in "kl")
    top = combos(inputs(BASE, cites), rank_by="bridge").combinations[0]
    assert top.score is not None and top.score.bridge == pytest.approx(math.log(3) / math.log(4))


def test_gap_bridge_is_log_scaled() -> None:
    import math

    cites = (("rf:e", "rf:a", "e1"), ("rf:f", "rf:x", "e2"), ("rf:a", "rf:x", "e3"))
    out = gaps(inputs(GAPROWS, cites), rank_by="bridge")
    by = {g.approach.id: g.score for g in out.gaps}
    assert by["ide-02"] is not None and by["ide-02"].bridge == pytest.approx(
        math.log(3) / math.log(3)
    )
    assert by["ide-01"] is not None and by["ide-01"].bridge == pytest.approx(
        math.log(2) / math.log(5)
    )


def test_name_tokens_and_jaccard() -> None:
    assert tr.name_tokens("The Staged tree-search of an Agent, by id") == frozenset(
        {"staged", "tree", "search", "agent"}
    )
    a = tr.name_tokens("Staged experiment tree search")
    b = tr.name_tokens("Staged agentic tree search over experiment scripts")
    assert tr.jaccard(a, b) == pytest.approx(4 / 6)
    assert tr.jaccard(frozenset(), frozenset()) == 0.0


LOOK = [*users("exp-03", "abc"), *users("imp-01", "def"), *users("wri-01", "ghi")]


def test_lookalike_names_in_other_stages_are_flagged_with_id_and_value() -> None:
    out = combos(inputs(LOOK))
    by = {(c.a.id, c.b.id): c for c in out.combinations}
    c = by[("exp-03", "imp-01")]
    assert c.score is not None and "lookalike-across-stages" in c.score.flags
    seen = {(lk.of, lk.approach_id, lk.stage) for lk in c.score.lookalikes}
    assert ("exp-03", "imp-01", "implementation-execution") in seen
    assert all(lk.jaccard >= 0.3 for lk in c.score.lookalikes)
    assert "lookalike of imp-01 in implementation-execution: possibly the same technique" in (
        c.statement
    )
    # the unrelated approach is flagged only through the pair that contains a lookalike
    other = by[("exp-03", "wri-01")]
    assert other.score is not None and "lookalike-across-stages" in other.score.flags
    assert {lk.of for lk in other.score.lookalikes} == {"exp-03"}


def test_unrelated_names_carry_no_lookalike_flag() -> None:
    out = combos(inputs(BASE))
    for c in out.combinations:
        assert c.score is not None
        assert "lookalike-across-stages" not in c.score.flags and c.score.lookalikes == ()
        assert "lookalike of" not in c.statement


def test_lookalike_is_deterministic_and_never_changes_the_order_or_score() -> None:
    data = inputs(LOOK)
    assert combos(data).model_dump_json() == combos(data).model_dump_json()
    flagged = combos(data)
    plain = [(c.a.id, c.b.id, c.score.composite if c.score else None) for c in flagged.combinations]
    ranked = sorted(plain, key=lambda t: (-(t[2] or 0), t[0], t[1]))
    assert plain == ranked
    c = flagged.combinations[0]
    assert c.score is not None
    expected = tr.combination_score(
        rank_by="composite",
        works_a=c.works_a,
        works_b=c.works_b,
        pool_max=3,
        stage_a=c.a.stage,
        stage_b=c.b.stage,
        links=c.score.bridge_links,
        evidence_a=1.0,
        evidence_b=1.0,
        total_works=9,
    )
    assert expected.composite == c.score.composite
