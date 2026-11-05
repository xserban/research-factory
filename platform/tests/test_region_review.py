"""Human review of region versions (slice 3d, plan Regions-A, task 4)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.regions import RegionKind
from factory.regions.rules import CorpusRule, MemberType, RuleSet
from factory.services.regions import (
    decide_member,
    define_region,
    review_region,
    review_state,
    snapshot_region,
)
from tests.helpers import SESSION
from tests.region_helpers import RWorld, region_project, screened  # noqa: F401

RULES = RuleSet(include=(CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT),))


def make(w: RWorld, author: Actor) -> tuple[str, str]:
    region = define_region(
        w.project, author, kind=RegionKind.REGION, name="r", definition="d", rules=RULES
    )
    return region, snapshot_region(w.project, author, region)


def test_agent_cannot_review(region_project: RWorld, human: Actor, agent_other: Actor) -> None:
    _, version = make(region_project, human)
    with pytest.raises(FactoryValidationError) as caught:
        review_region(region_project.project, agent_other, version, "reviewed")
    assert caught.value.issues[0].field == "actor"
    assert review_state(region_project.project, version) == "unreviewed"


def test_writer_session_never_reviews(region_project: RWorld, human: Actor, agent: Actor) -> None:
    _, version = make(region_project, agent)
    with pytest.raises(FactoryValidationError) as caught:
        review_region(region_project.project, human, version, "reviewed")  # same session
    assert "session" in [i.field for i in caught.value.issues]


def test_wrong_needs_note(region_project: RWorld, human: Actor) -> None:
    _, version = make(region_project, human)
    with pytest.raises(FactoryValidationError) as caught:
        review_region(region_project.project, human, version, "wrong")
    assert caught.value.issues[0].field == "note"
    with pytest.raises(FactoryValidationError) as unknown:
        review_region(region_project.project, human, "R@" + "0" * 8, "reviewed")
    assert unknown.value.issues[0].field == "version"


def test_self_review_flagged(region_project: RWorld, human: Actor) -> None:
    w = region_project
    _, version = make(w, human)
    review_region(w.project, human, version, "reviewed")
    with w.project.index.connect() as conn:
        flagged = conn.execute(text("SELECT self_reviewed FROM region_reviews")).scalar_one()
    assert flagged == 1 and review_state(w.project, version) == "reviewed"


def test_second_human_must_review(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region, version = make(w, human)
    ann = Actor(kind="human", id="ann", user="ann", session=SESSION)
    decide_member(w.project, ann, region, MemberType.WORK, "rf:x-00000001", "add")
    with pytest.raises(FactoryValidationError) as caught:
        review_region(w.project, human, version, "reviewed")
    assert caught.value.issues[0].field == "reviewer"
    review_region(w.project, ann, version, "reviewed")
    with w.project.index.connect() as conn:
        assert conn.execute(text("SELECT self_reviewed FROM region_reviews")).scalar_one() == 0


def test_repeat_review_supersedes(region_project: RWorld, human: Actor) -> None:
    w = region_project
    _, version = make(w, human)
    review_region(w.project, human, version, "reviewed")
    review_region(w.project, human, version, "wrong", "members drift")
    assert review_state(w.project, version) == "wrong"


def test_new_snapshot_supersedes_old_version_state(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region, first = make(w, human)
    review_region(w.project, human, first, "reviewed")
    decide_member(w.project, human, region, MemberType.WORK, "rf:added-00000001", "add")
    second = snapshot_region(w.project, human, region)
    assert review_state(w.project, first) == "superseded"
    assert review_state(w.project, second) == "unreviewed"
