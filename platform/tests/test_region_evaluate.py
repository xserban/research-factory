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
from tests.region_helpers import (  # noqa: F401
    MERGE_ID,
    RWorld,
    cite,
    merge_works,
    region_project,
    screened,
)

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
                "VALUES (:m, :p, :a, 'x', 2, 'active')"
            ),
            {"m": MERGE_ID, "p": a, "a": f'["{b}"]'},
        )
        conn.execute(
            text("INSERT INTO merge_members (merge_id, work_id) VALUES (:m, :w)"),
            [{"m": MERGE_ID, "w": a}, {"m": MERGE_ID, "w": b}],
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


def test_term_rule_unknown_term_refused(region_project: RWorld) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        run(region_project, RuleSet(include=(TermRule(term_id="trm_x"),)))
    assert caught.value.issues[0].field == "rules.include[0].term_id"
    assert caught.value.issues[0].reason == "term-unknown"


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


def test_cites_maps_merged_works_at_the_join(region_project: RWorld) -> None:
    w = region_project
    a, a2, m1, m2, x = (*w.included[:2], *w.included[2:4], w.extra)
    merge_works(w.project, a, a2)  # a2 is absorbed into a
    # X cites the absorbed a2, while the base holds the primary a
    cite(w.project, x, a2, "x1")
    base = "R@" + "7" * 8
    pin(w, w.works(a), base, REG)
    citing = run(w, RuleSet(include=(CitesRule(base=base, direction="citing"),)))
    assert x in ids(citing)
    # a cites m1 and the absorbed a2 cites m2: with min_k = 2 the merged work cites both
    cite(w.project, a, m1, "x2")
    cite(w.project, a2, m2, "x3")
    pair = "R@" + "8" * 8
    pin(w, w.works(m1, m2), pair, "reg_01JZ9Q3K5M7N8P0R2S4T6V8W2R")
    two = run(w, RuleSet(include=(CitesRule(base=pair, direction="citing", min_k=2),)))
    assert a in ids(two) and a2 not in ids(two)
    # the other direction: works cited by at least two members of a base holding a and a2
    both = "R@" + "9" * 8
    pin(w, w.works(a, a2), both, "reg_01JZ9Q3K5M7N8P0R2S4T6V8W3R")
    cite(w.project, a, w.outside, "x4")
    cite(w.project, a2, w.outside, "x5")
    cited = run(w, RuleSet(include=(CitesRule(base=both, direction="cited", min_k=2),)))
    assert w.outside not in ids(cited)  # one merged work cites it, not two


def test_human_remove_holds_after_the_work_is_absorbed(region_project: RWorld) -> None:
    w = region_project
    a, b = w.included[:2]
    merge_works(w.project, a, b)
    ev = run(w, RuleSet(include=(FT_INCLUDED,)), removes=[(W, b)])
    assert a not in ids(ev) and b not in ids(ev)
    added = run(w, RuleSet(include=(FT_INCLUDED,)), removes=[(W, a)], adds=[(W, b)])
    assert a not in ids(added)  # the remove of the primary also covers the absorbed add


def test_pinned_member_absorbed_later_still_matches(region_project: RWorld) -> None:
    w = region_project
    a, b = w.included[:2]
    version = "R@" + "6" * 8
    pin(w, w.works(b), version, REG)
    merge_works(w.project, a, b)  # b is absorbed after the pin
    inside = run(w, RuleSet(include=(FT_INCLUDED,), within=RegionRule(version=version)))
    assert ids(inside) == [a]
    outside = run(w, RuleSet(include=(FT_INCLUDED,), exclude=(RegionRule(version=version),)))
    assert a not in ids(outside) and b not in ids(outside)


def _add_concept_user(w: RWorld, link: str, node: str, kind: str) -> None:
    from sqlalchemy import text

    with w.project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO concept_uses (link_id, from_node, from_kind, concept_id, basis_kind, "
                "basis_digest, proposed_status, status, status_reason, proposer_kind, "
                "proposer_session, event_id) VALUES (:l, :n, :k, :c, 'quote', 'd', 'stated', "
                "'stated', 'x', 'human', 's', 'ev')"
            ),
            {"l": link, "n": node, "k": kind, "c": w.concept},
        )
        conn.commit()


def _add_concept(
    w: RWorld, cid: str, source: str = "approved", review: str = "reviewed", into: str | None = None
) -> None:
    from sqlalchemy import text

    with w.project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO concepts (concept_id, name, name_folded, author, author_user, "
                "writer_session, definition_event, source_state, review_state, self_reviewed, "
                "merged_into, event_id) VALUES (:c, :c, :c, 'human', 'obd', 's', 'ev', :s, :r, "
                "0, :i, 'ev')"
            ),
            {"c": cid, "s": source, "r": review, "i": into},
        )
        conn.commit()


def test_concept_nodes_are_typed_as_concepts(region_project: RWorld) -> None:
    other = "cpt_01JZ9Q3K5M7N8P0R2S4T6V8W2K"
    _add_concept(region_project, other)
    _add_concept_user(region_project, "lnk_9", other, "concept")
    ev = run(region_project, RuleSet(include=(ConceptRule(concept_id=region_project.concept),)))
    assert ids(ev, MemberType.CONCEPT) == [other]
    assert other not in ids(ev)


def test_concept_rule_respects_review_and_merges(region_project: RWorld) -> None:
    from sqlalchemy import text

    w = region_project
    rule = RuleSet(include=(ConceptRule(concept_id=w.concept),))
    with w.project.index.connect() as conn:
        conn.execute(
            text("UPDATE concepts SET review_state = 'wrong' WHERE concept_id = :c"),
            {"c": w.concept},
        )
        conn.commit()
    with pytest.raises(FactoryValidationError) as caught:
        run(w, rule)
    assert caught.value.issues[0].reason == "concept-not-visible"


def test_merged_ideas_and_concepts_resolve_to_live_ids(region_project: RWorld) -> None:
    from sqlalchemy import text

    w = region_project
    gone_idea = "ida_01JZ9Q3K5M7N8P0R2S4T6V8W3I"
    gone_concept = "cpt_01JZ9Q3K5M7N8P0R2S4T6V8W3K"
    with w.project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO ideas (idea_id, name, name_item, origin, decision, merged_into, "
                "event_id) VALUES (:i, 'old', 'itm', 'rf:x', 'confirm', :into, 'ev')"
            ),
            {"i": gone_idea, "into": w.idea},
        )
        conn.execute(
            text(
                "INSERT INTO concept_merges (from_concept, into_concept, active, merge_event) "
                "VALUES (:f, :t, 1, 'ev')"
            ),
            {"f": gone_concept, "t": w.concept},
        )
        conn.commit()
    _add_concept(w, gone_concept, into=w.concept)
    _add_concept_user(w, "lnk_8", gone_idea, "idea")
    _add_concept_user(w, "lnk_7", gone_concept, "concept")
    ev = run(w, RuleSet(include=(ConceptRule(concept_id=w.concept),)))
    assert gone_idea not in ids(ev, MemberType.IDEA) and w.idea in ids(ev, MemberType.IDEA)
    assert ids(ev, MemberType.CONCEPT) == [w.concept]
    # a human add of the merged idea reads as its survivor
    added = run(w, RuleSet(include=(FT_INCLUDED,)), adds=[(MemberType.IDEA, gone_idea)])
    assert ids(added, MemberType.IDEA) == [w.idea]


def test_concept_users_must_themselves_be_visible(region_project: RWorld) -> None:
    from sqlalchemy import text

    w = region_project
    wrong, unapproved, fine = (f"cpt_01JZ9Q3K5M7N8P0R2S4T6V8W{c}K" for c in "456")
    with w.project.index.connect() as conn:
        for cid, source, review in (
            (wrong, "approved", "wrong"),
            (unapproved, "pending", "unreviewed"),
            (fine, "approved", "reviewed"),
        ):
            conn.execute(
                text(
                    "INSERT INTO concepts (concept_id, name, name_folded, author, author_user, "
                    "writer_session, definition_event, source_state, review_state, "
                    "self_reviewed, event_id) VALUES (:c, :c, :c, 'human', 'obd', 's', 'ev', "
                    ":s, :r, 0, 'ev')"
                ),
                {"c": cid, "s": source, "r": review},
            )
        conn.commit()
    for n, node in enumerate((wrong, unapproved, fine)):
        _add_concept_user(w, f"lnk_c{n}", node, "concept")
    ev = run(w, RuleSet(include=(ConceptRule(concept_id=w.concept),)))
    assert ids(ev, MemberType.CONCEPT) == [fine]
