"""Links, overlap, diff and regions_of (slice 3d, plan Regions-B, task 2)."""

# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.regions import RegionKind
from factory.regions.rules import CorpusRule, MemberType, RuleSet
from factory.services.regions import (
    decide_member,
    define_region,
    diff,
    link_regions,
    overlap,
    regions_of,
    snapshot_region,
    subregion_violations,
)
from tests.region_helpers import RWorld, region_project, screened  # noqa: F401

W = MemberType.WORK
FT_INCLUDED = CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT)


def make(w: RWorld, human: Actor, name: str, rules: RuleSet | None = None) -> str:
    return define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name=name,
        definition=name,
        rules=rules or RuleSet(include=(FT_INCLUDED,)),
    )


def test_subregion_verified_at_write(region_project: RWorld, human: Actor, agent: Actor) -> None:
    w = region_project
    small, big = make(w, human, "small"), make(w, human, "big")
    decide_member(w.project, human, small, W, w.included[0], "remove")
    decide_member(w.project, human, big, W, w.extra, "add")
    v_small, v_big = (
        snapshot_region(w.project, human, small),
        snapshot_region(w.project, human, big),
    )
    link_regions(w.project, human, "subregion-of", v_small, v_big)
    with w.project.index.connect() as conn:
        before = int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())
    with pytest.raises(FactoryValidationError) as caught:
        link_regions(w.project, human, "subregion-of", v_big, v_small)
    assert [i.field for i in caught.value.issues] == ["source"]
    with pytest.raises(FactoryValidationError):
        link_regions(w.project, agent, "related", v_big, v_small, "agents do not link")
    with pytest.raises(FactoryValidationError) as unknown:
        link_regions(w.project, human, "related", v_big, "R@00000000")
    assert unknown.value.issues[0].field == "target"
    with w.project.index.connect() as conn:
        assert int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one()) == before
    link_regions(w.project, human, "related", v_big, v_small, "same topic")
    assert subregion_violations(w.project) == []


def test_subregion_violation_found_later(region_project: RWorld, human: Actor) -> None:
    w = region_project
    child, parent = make(w, human, "child"), make(w, human, "parent")
    link_regions(
        w.project,
        human,
        "subregion-of",
        snapshot_region(w.project, human, child),
        snapshot_region(w.project, human, parent),
    )
    assert subregion_violations(w.project) == []
    decide_member(w.project, human, parent, W, w.included[0], "remove")
    snapshot_region(w.project, human, parent)
    [(link, source, target)] = subregion_violations(w.project)
    assert (source, target) == (child, parent) and link.startswith("ev_")


def test_overlap_counts_and_jaccard(region_project: RWorld, human: Actor) -> None:
    w = region_project
    a, b = make(w, human, "a"), make(w, human, "b")
    decide_member(w.project, human, a, W, w.included[0], "remove")
    decide_member(w.project, human, b, W, w.extra, "add")
    va, vb = snapshot_region(w.project, human, a), snapshot_region(w.project, human, b)
    result = overlap(w.project, va, vb)
    n = len(w.included)
    assert result.shared == {W: n - 1}
    assert result.only_a == {} and result.only_b == {W: 2}
    assert result.jaccard == {W: (n - 1) / (n + 1)}
    mirrored = overlap(w.project, vb, va)
    assert mirrored.only_a == {W: 2} and mirrored.jaccard == result.jaccard
    with pytest.raises(FactoryValidationError):
        overlap(w.project, va, "R@00000000")


def test_diff_paginated_deterministic(region_project: RWorld, human: Actor) -> None:
    w = region_project
    a, b = make(w, human, "a"), make(w, human, "b")
    decide_member(w.project, human, a, W, w.included[0], "remove")
    decide_member(w.project, human, b, W, w.extra, "add")
    va, vb = snapshot_region(w.project, human, a), snapshot_region(w.project, human, b)
    full = diff(w.project, va, vb)
    assert [m for _, m in full.added] == sorted([w.included[0], w.extra])
    assert full.removed == [] and full.total_added == 2 and full.total_removed == 0
    pages = [diff(w.project, va, vb, offset=o, limit=1) for o in (0, 1, 2)]
    assert [p.added for p in pages[:2]] == [[x] for x in full.added]
    assert pages[2].added == [] and pages[2].removed == []
    back = diff(w.project, vb, va)
    assert back.added == [] and back.removed == full.added


def test_regions_of_uses_index(region_project: RWorld, human: Actor) -> None:
    w = region_project
    a, b = make(w, human, "a"), make(w, human, "b")
    decide_member(w.project, human, b, W, w.extra, "add")
    va, vb = snapshot_region(w.project, human, a), snapshot_region(w.project, human, b)
    seen: list[str] = []

    def spy(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: Any
    ) -> None:
        seen.append(str(statement))

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        found = regions_of(w.project, W, w.extra)
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    assert [m.region_id for m in found] == [b] and found[0].version == vb
    assert sum("region_members" in s for s in seen) == 1
    both = regions_of(w.project, W, w.included[0])
    assert [m.region_id for m in both] == sorted([a, b])
    assert {m.version for m in both} == {va, vb}
    assert all(m.review_state == "unreviewed" and m.adopted_from is None for m in both)
    assert "rules" in both[0].basis
    assert regions_of(w.project, W, "rf:nowhere-00000000") == []


def test_older_definition_reaching_a_barred_purpose_withholds_the_region(
    region_project: RWorld, human: Actor
) -> None:
    from factory.regions.rules import RunRule
    from factory.services.regions import agent_region_state, region_withheld
    from tests.region_helpers import add_queries

    w = region_project
    add_queries(w.project, {"qry_imp": "import"})
    region = make(w, human, "once barred", RuleSet(include=(RunRule(query_id="qry_imp"),)))
    snapshot_region(w.project, human, region)
    define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name="now clean",
        definition="now clean",
        rules=RuleSet(include=(FT_INCLUDED,)),
        region_id=region,
    )
    assert region_withheld(w.project, region)
    state = agent_region_state(w.project, region)
    assert state.counts_withheld and state.live_counts == {}
