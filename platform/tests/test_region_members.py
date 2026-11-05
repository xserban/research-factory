"""Member proposals and human decisions (slice 3d, plan Regions-B, task 1)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.regions import EdgeBasis, QuoteBasis, RegionKind
from factory.regions.rules import CorpusRule, MemberType, RuleSet
from factory.services.regions import (
    decide_member,
    define_region,
    pending_proposals,
    propose_member,
    region_members,
    snapshot_region,
)
from tests.contribution_helpers import ctr_a, ctr_b, world  # noqa: F401
from tests.intuition_helpers import live_conversion
from tests.lineage_helpers import Lineage, lin  # noqa: F401
from tests.region_helpers import RWorld, region_project, screened  # noqa: F401

W = MemberType.WORK
FT_INCLUDED = CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT)
QUOTE = "very long sequences degrade"


def edge_id(i: int) -> str:
    return f"cit:rex_{i:026d}:1"


def event_count(w: RWorld) -> int:
    with w.project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())


def quote_basis(w: RWorld, lin: Lineage, quote: str = QUOTE) -> QuoteBasis:
    cnv, _ = live_conversion(w.project, lin.source)
    return QuoteBasis(work_id=lin.source, conversion_id=cnv, anchor="s1.p4", quote=quote)


def included_region(w: RWorld, human: Actor, name: str = "included") -> str:
    return define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name=name,
        definition="Included works.",
        rules=RuleSet(include=(FT_INCLUDED,)),
    )


def region_without(w: RWorld, human: Actor, lin: Lineage) -> str:
    """A region of the full-text included works from which a human removed the source work."""
    assert lin.source in w.included
    region = included_region(w, human)
    decide_member(w.project, human, region, W, lin.source, "remove")
    return region


def members(w: RWorld, version: str) -> set[str]:
    return {m for _, m in region_members(w.project, version)}


def test_member_quote_must_verify(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    before = event_count(w)
    with pytest.raises(FactoryValidationError) as caught:
        propose_member(
            w.project,
            agent,
            region,
            W,
            lin.source,
            quote_basis(w, lin, QUOTE.replace("v", "w", 1)),
        )
    assert [i.field for i in caught.value.issues] == ["basis.quote"]
    assert event_count(w) == before
    assert pending_proposals(w.project, region) == []
    propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    assert len(pending_proposals(w.project, region)) == 1


def test_quote_basis_names_the_candidate(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    other = next(x for x in w.included if x != lin.source)
    with pytest.raises(FactoryValidationError) as caught:
        propose_member(w.project, agent, region, W, other, quote_basis(w, lin))
    assert [i.field for i in caught.value.issues] == ["basis.work_id"]


def test_edge_basis_must_touch_region(region_project: RWorld, human: Actor, agent: Actor) -> None:
    w = region_project
    _, b, _, d = w.included[:4]
    region = included_region(w, human)
    decide_member(w.project, human, region, W, d, "remove")
    before = event_count(w)
    with pytest.raises(FactoryValidationError) as caught:
        propose_member(w.project, agent, region, W, d, EdgeBasis(edge_id=edge_id(1)))
    assert [(i.field, i.reason) for i in caught.value.issues] == [
        ("basis.edge_id", "edge-not-incident")
    ]
    with pytest.raises(FactoryValidationError) as unknown:
        propose_member(w.project, agent, region, W, d, EdgeBasis(edge_id="cit:nope"))
    assert unknown.value.issues[0].reason == "edge-unknown"
    assert event_count(w) == before
    # d -> b touches d and a current member (b)
    propose_member(w.project, agent, region, W, d, EdgeBasis(edge_id=edge_id(2)))
    # in a region without b the same edge touches no member
    other = included_region(w, human, "without b")
    decide_member(w.project, human, other, W, b, "remove")
    decide_member(w.project, human, other, W, d, "remove")
    with pytest.raises(FactoryValidationError) as outside:
        propose_member(w.project, agent, other, W, d, EdgeBasis(edge_id=edge_id(2)))
    assert outside.value.issues[0].reason == "edge-not-in-region"


def test_concept_use_basis(region_project: RWorld, human: Actor, agent: Actor) -> None:
    w = region_project
    _, b, _, d = w.included[:4]
    region = included_region(w, human)
    decide_member(w.project, human, region, MemberType.CONCEPT, w.concept, "add")
    # lnk_1: b uses the concept (stated), lnk_3: d uses it but only inferred
    decide_member(w.project, human, region, W, b, "remove")
    decide_member(w.project, human, region, W, d, "remove")
    propose_member(w.project, agent, region, W, b, EdgeBasis(edge_id="lnk_1"))
    other = included_region(w, human, "no concept")
    decide_member(w.project, human, other, W, b, "remove")
    with pytest.raises(FactoryValidationError) as outside:
        propose_member(w.project, agent, other, W, b, EdgeBasis(edge_id="lnk_1"))
    assert outside.value.issues[0].reason == "edge-not-in-region"
    with pytest.raises(FactoryValidationError) as caught:
        propose_member(w.project, agent, region, W, d, EdgeBasis(edge_id="lnk_3"))
    assert caught.value.issues[0].reason == "edge-unknown"


def test_proposal_absent_until_added(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    first = snapshot_region(w.project, human, region)
    proposal = propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    assert snapshot_region(w.project, human, region) == first
    assert lin.source not in members(w, first)
    decide_member(w.project, human, region, W, lin.source, "add", proposal_id=proposal)
    second = snapshot_region(w.project, human, region)
    assert second != first and lin.source in members(w, second)
    assert pending_proposals(w.project, region) == []


def test_agent_cannot_decide(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    proposal = propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    before = event_count(w)
    for decision in ("add", "remove", "reject"):
        with pytest.raises(FactoryValidationError):
            decide_member(
                w.project,
                agent,
                region,
                W,
                lin.source,
                decision,  # type: ignore[arg-type]
                proposal_id=proposal,
            )
    assert event_count(w) == before


def test_remove_overrides_rule(region_project: RWorld, lin: Lineage, human: Actor) -> None:
    w = region_project
    region = region_without(w, human, lin)
    assert lin.source not in members(w, snapshot_region(w.project, human, region))


def test_reject_closes_proposal(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    proposal = propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    decide_member(w.project, human, region, W, lin.source, "reject", proposal_id=proposal)
    assert pending_proposals(w.project, region) == []
    assert lin.source not in members(w, snapshot_region(w.project, human, region))
    with pytest.raises(FactoryValidationError) as caught:
        decide_member(
            w.project, human, region, W, lin.source, "reject", proposal_id="rmp_" + "0" * 26
        )
    assert caught.value.issues[0].field == "proposal_id"


def test_decisions_enter_version_hash(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    first = snapshot_region(w.project, human, region)
    proposal = propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    decide_member(w.project, human, region, W, lin.source, "reject", proposal_id=proposal)
    # a rejection is not a decision in effect: the version does not move
    assert snapshot_region(w.project, human, region) == first
    decide_member(w.project, human, region, W, lin.source, "add")
    added = snapshot_region(w.project, human, region)
    assert added != first
    # a later rejection never undoes the add
    decide_member(w.project, human, region, W, lin.source, "reject")
    assert snapshot_region(w.project, human, region) == added


def test_duplicate_proposal_idempotent(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    first = propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    before = event_count(w)
    assert propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin)) == first
    assert event_count(w) == before


def test_agent_proposal_carries_provenance(
    region_project: RWorld, lin: Lineage, human: Actor, agent: Actor
) -> None:
    w = region_project
    region = region_without(w, human, lin)
    propose_member(w.project, agent, region, W, lin.source, quote_basis(w, lin))
    with w.project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT actor_kind, model, skill, input_blob FROM events "
                "WHERE type = 'region.member_proposed'"
            )
        ).one()
    assert row[0] == "agent" and row[1] and row[2] and row[3]
