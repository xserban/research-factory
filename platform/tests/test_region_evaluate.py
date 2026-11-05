"""Deterministic bounded rule evaluation (slice 3d, plan Regions-A, task 2)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest
from sqlalchemy import event

from factory.errors import FactoryValidationError
from factory.model.protocol import ScreeningStage
from factory.regions import evaluate as evaluate_module
from factory.regions.evaluate import Evaluation, evaluate
from factory.regions.rules import (
    CitesRule,
    ConceptRule,
    CorpusRule,
    IdeaRule,
    LineageRule,
    MemberType,
    RegionRule,
    RuleSet,
    TermRule,
    TextRule,
)
from factory.regions.version import compress, members_text
from tests.region_helpers import RWorld, region_project, screened  # noqa: F401

W = MemberType.WORK
FT_INCLUDED = CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT)


def run(w: RWorld, rules: RuleSet, **kwargs: object) -> Evaluation:
    with w.project.index.connect() as conn:
        return evaluate(conn, w.project, rules, **kwargs)  # type: ignore[arg-type]


def ids(ev: Evaluation, kind: MemberType = W) -> list[str]:
    return [m for t, m in ev.members if t is kind]


def pin(w: RWorld, members: list[tuple[MemberType, str]], version: str, region: str) -> None:
    """Write a snapshot event for `version` holding `members` (the evaluator reads its blob)."""
    from factory.model.regions import RegionSnapshotTaken

    blob = w.project.blobs.put(compress(members_text(members)))
    basis = w.project.blobs.put_json({})
    counts = {MemberType.WORK: len(members)}
    payload = RegionSnapshotTaken(
        region_id=region,
        version=version,
        definition_event="ev_01JZ9Q3K5M7N8P0R2S4T6V8W1D",
        rules_hash="0" * 64,
        members_blob=blob,
        members_hash="1" * 64,
        basis_blob=basis,
        counts=counts,
        as_of="ev_01JZ9Q3K5M7N8P0R2S4T6V8W1D",
    )
    w.project.record(
        [w.project.events.make("region.snapshot_taken", payload, w.project.system_actor())]
    )


REG = "reg_01JZ9Q3K5M7N8P0R2S4T6V8W1R"


def test_corpus_included(region_project: RWorld) -> None:
    ev = run(region_project, RuleSet(include=(FT_INCLUDED,)))
    assert ids(ev) == sorted(w for w in region_project.included)
    assert ev.counts == {W: len(ev.members)}
    assert ids(run(region_project, RuleSet(include=(CorpusRule(outcome="all"),)))) == (
        region_project.corpus
    )


def test_lineage_ancestors_stated_only(region_project: RWorld) -> None:
    a, b, c, d = region_project.included[:4]
    rule = LineageRule(node=d, direction="ancestors", depth=2)
    # the builds-on relations are inferred and confirmed by a human, so they are followed
    assert ids(run(region_project, RuleSet(include=(rule,)))) == sorted([c, b])
    # one level reaches only the direct base
    one = LineageRule(node=d, direction="ancestors", depth=1)
    assert ids(run(region_project, RuleSet(include=(one,)))) == [c]
    down = LineageRule(node=a, direction="descendants", depth=1)
    assert ids(run(region_project, RuleSet(include=(down,)))) == [b]


def test_truncated_lineage_refuses(region_project: RWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    _a, _b, _c, d = region_project.included[:4]
    monkeypatch.setattr(evaluate_module, "REGION_MAX_MEMBERS", 1)
    rule = LineageRule(node=d, direction="ancestors", depth=3)
    with pytest.raises(FactoryValidationError) as caught:
        run(region_project, RuleSet(include=(FT_INCLUDED, rule)))
    issue = caught.value.issues[0]
    assert issue.field in ("rules.include[0]", "rules.include[1]")
    assert "over-bound" in issue.reason


def test_cites_min_k(region_project: RWorld) -> None:
    a, b, c, d = region_project.included[:4]
    outside = region_project.outside
    version = "R@" + "b" * 8
    pin(region_project, region_project.works(b, c), version, REG)
    citing_1 = CitesRule(base=version, direction="citing", min_k=1)
    # a cites b and c, d cites b, outside cites b and c
    assert ids(run(region_project, RuleSet(include=(citing_1,)))) == sorted([a, d, outside])
    citing_2 = CitesRule(base=version, direction="citing", min_k=2)
    assert ids(run(region_project, RuleSet(include=(citing_2,)))) == sorted([a, outside])
    cited = pin_base(region_project, [a, outside])
    ev = run(region_project, RuleSet(include=(CitesRule(base=cited, direction="cited"),)))
    assert ids(ev) == sorted([b, c])


def pin_base(w: RWorld, works: list[str]) -> str:
    version = "R@" + "c" * 8
    pin(w, w.works(*works), version, "reg_01JZ9Q3K5M7N8P0R2S4T6V8W2R")
    return version


def test_region_rule_reads_pinned_version(region_project: RWorld) -> None:
    a, b, _c, _d = region_project.included[:4]
    first, second = "R@" + "d" * 8, "R@" + "e" * 8
    pin(region_project, region_project.works(a), first, REG)
    pin(region_project, region_project.works(a, b), second, REG)  # a later snapshot, same region
    assert ids(run(region_project, RuleSet(include=(RegionRule(version=first),)))) == [a]
    assert ids(run(region_project, RuleSet(include=(RegionRule(version=second),)))) == [a, b]
    with pytest.raises(FactoryValidationError) as caught:
        run(region_project, RuleSet(include=(RegionRule(version="R@" + "0" * 8),)))
    assert caught.value.issues[0].reason == "unknown-version"


def test_idea_rule_includes_idea_node_and_members(region_project: RWorld) -> None:
    a, _b, c, _d = region_project.included[:4]
    ev = run(region_project, RuleSet(include=(IdeaRule(idea_id=region_project.idea),)))
    assert ids(ev, MemberType.IDEA) == [region_project.idea]
    assert ids(ev) == sorted([a, c])
    with pytest.raises(FactoryValidationError):
        run(region_project, RuleSet(include=(IdeaRule(idea_id="ida_01JZ9Q3K5M7N8P0R2S4T6V8W9Z"),)))


def test_concept_rule_stated_or_confirmed_uses(region_project: RWorld) -> None:
    _a, b, _c, _d = region_project.included[:4]
    ev = run(region_project, RuleSet(include=(ConceptRule(concept_id=region_project.concept),)))
    # lnk_3 is inferred, so d is not selected
    assert ids(ev) == [b]
    assert ids(ev, MemberType.IDEA) == [region_project.idea]
    with pytest.raises(FactoryValidationError):
        run(
            region_project,
            RuleSet(include=(ConceptRule(concept_id="cpt_01JZ9Q3K5M7N8P0R2S4T6V8W9Z"),)),
        )


def test_text_rule_and_of_ors(region_project: RWorld) -> None:
    from sqlalchemy import text

    a, _b, _c, _d = region_project.included[:4]
    with region_project.project.index.connect() as conn:
        rows = {
            str(r[0]): str(r[1])
            for r in conn.execute(text("SELECT work_id, data FROM works")).all()
        }
    import json

    title = json.loads(rows[a])["title"]
    word = title.split()[0].casefold()
    ev = run(region_project, RuleSet(include=(TextRule(blocks=((word, "zzzqqq"),)),)))
    assert a in ids(ev)
    none = run(region_project, RuleSet(include=(TextRule(blocks=((word,), ("zzzqqq",))),)))
    assert ids(none) == []


def test_exclude_and_within(region_project: RWorld) -> None:
    _a, _b, c, d = region_project.included[:4]
    everything = CorpusRule(outcome="all")
    ev = run(
        region_project,
        RuleSet(
            include=(everything,),
            exclude=(LineageRule(node=d, direction="ancestors", depth=1),),
            within=FT_INCLUDED,
        ),
    )
    assert ids(ev) == sorted(set(region_project.included) - {c})


def test_human_adds_and_removes_override(region_project: RWorld) -> None:
    a, _b, _c, _d = region_project.included[:4]
    rules = RuleSet(include=(FT_INCLUDED,))
    ev = run(
        region_project,
        rules,
        adds=[(W, "rf:added-00000001")],
        removes=[(W, a)],
    )
    assert "rf:added-00000001" in ids(ev) and a not in ids(ev)
    assert ev.basis[(W, "rf:added-00000001")] == ()
    # a human add outside `within` is cut by it (the ruling-3 formula)
    cut = run(
        region_project,
        RuleSet(include=(FT_INCLUDED,), within=FT_INCLUDED),
        adds=[(W, "rf:added-00000001")],
    )
    assert "rf:added-00000001" not in ids(cut)


def test_merged_work_maps_to_canonical(region_project: RWorld) -> None:
    from sqlalchemy import text

    a, b = region_project.included[:2]
    with region_project.project.index.connect() as conn:
        conn.execute(
            text(
                'INSERT INTO merges (merge_id, "primary", absorbed, rule, records, status) '
                "VALUES ('mrg_1', :p, :a, 'x', 2, 'active')"
            ),
            {"p": a, "a": f'["{b}"]'},
        )
        conn.execute(
            text("INSERT INTO merge_members (merge_id, work_id) VALUES ('mrg_1', :w)"),
            [{"w": a}, {"w": b}],
        )
        conn.commit()
    ev = run(region_project, RuleSet(include=(FT_INCLUDED,)))
    assert b not in ids(ev) and a in ids(ev)


def test_basis_lists_rule_indices(region_project: RWorld) -> None:
    a, _b, c, d = region_project.included[:4]
    rules = RuleSet(
        include=(
            FT_INCLUDED,
            LineageRule(node=d, direction="ancestors", depth=1),
        )
    )
    ev = run(region_project, rules)
    assert ev.basis[(W, c)] == (0, 1)
    assert ev.basis[(W, a)] == (0,)


def test_term_rule_refused_until_regions_c(region_project: RWorld) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        run(region_project, RuleSet(include=(TermRule(term_id="trm_x"),)))
    assert caught.value.issues[0].field == "rules.include[0]"
    assert caught.value.issues[0].reason == "term-rules-unavailable"


def test_no_seed_tables_read(region_project: RWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """The evaluators' own SQL; `final_outcomes` (the screening service) is the one sanctioned
    path to pass data and is stubbed with its precomputed result."""
    from factory.services.agreement import final_outcomes

    outcomes = final_outcomes(region_project.project)
    monkeypatch.setattr(evaluate_module, "final_outcomes", lambda project, **kw: outcomes)
    seen: list[str] = []
    engine = region_project.project.index._engine

    def capture(conn: object, cursor: object, statement: str, *rest: object) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        run(
            region_project,
            RuleSet(
                include=(
                    FT_INCLUDED,
                    LineageRule(node=region_project.included[3], direction="ancestors", depth=2),
                    IdeaRule(idea_id=region_project.idea),
                    ConceptRule(concept_id=region_project.concept),
                    TextRule(blocks=(("a",),)),
                )
            ),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert seen
    joined = " ".join(seen).lower()
    for table in ("seeds", "seed_split", "seed_explanations", "passes", "pass_sessions"):
        assert f" {table} " not in joined.replace("\n", " ").replace("(", " ").replace(")", " ")
