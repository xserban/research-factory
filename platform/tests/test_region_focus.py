"""Foci bound to question slots (slice 3d, plan Regions-A, task 5)."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.protocol import ScreeningStage
from factory.model.question import QuestionSpec, Slot
from factory.model.regions import Facet, RegionKind
from factory.regions.rules import CorpusRule, RuleSet
from factory.services.context import Project
from factory.services.question import record_question
from tests.helpers import bind_ids, pilot_question_spec, record_pilot_question

RULES = RuleSet(include=(CorpusRule(outcome="all", stage=ScreeningStage.TITLE_ABSTRACT),))


def focus(project: Project, human: Actor, qid: str, slot: str, **kw: object) -> str:
    from factory.services.regions import define_region

    return define_region(
        project,
        human,
        kind=RegionKind.FOCUS,
        name=f"focus {slot}",
        definition="A focus.",
        rules=RULES,
        facet=Facet(question_id=qid, slot=slot),
        **kw,  # type: ignore[arg-type]
    )


def test_focus_needs_existing_slot(project: Project, human: Actor) -> None:
    qid = record_pilot_question(project, human)
    assert focus(project, human, qid, "population").startswith("reg_")
    with pytest.raises(FactoryValidationError) as caught:
        focus(project, human, qid, "nonexistent")
    assert (caught.value.issues[0].field, caught.value.issues[0].reason) == (
        "facet.slot",
        "slot-unknown",
    )
    with pytest.raises(FactoryValidationError) as unknown:
        focus(project, human, "Q@" + "0" * 8, "population")
    assert unknown.value.issues[0].field == "facet.question_id"


def test_second_focus_on_slot_refused(project: Project, human: Actor) -> None:
    qid = record_pilot_question(project, human)
    first = focus(project, human, qid, "population")
    with pytest.raises(FactoryValidationError) as caught:
        focus(project, human, qid, "population")
    assert caught.value.issues[0].reason == f"focus-exists:{first}"
    # another slot is free, and redefining the first focus is not a second focus
    assert focus(project, human, qid, "outcome")
    focus(project, human, qid, "population", region_id=first)


def test_second_focus_across_question_versions_refused(project: Project, human: Actor) -> None:
    qid = record_pilot_question(project, human)
    first = focus(project, human, qid, "population")
    spec = pilot_question_spec("Does linear attention match softmax on video?")
    newer = record_question(
        project,
        human,
        spec,
        reason="narrowed",
        decision_ids=bind_ids(project, human, DecisionLevel.QUESTIONS),
    ).question_id
    assert newer != qid
    with pytest.raises(FactoryValidationError) as caught:
        focus(project, human, newer, "population")
    assert caught.value.issues[0].reason == f"focus-exists:{first}"


def test_focus_slot_missing_after_question_change(project: Project, human: Actor) -> None:
    from factory.services.regions import foci, focus_slot_missing

    qid = record_pilot_question(project, human)
    region = focus(project, human, qid, "population")
    assert focus_slot_missing(project) == []
    spec = pilot_question_spec()
    renamed = QuestionSpec(
        **{
            **spec.model_dump(),
            "slots": (Slot(name="cohort", value="vision transformers"), spec.slots[1]),
        }
    )
    record_question(
        project,
        human,
        renamed,
        reason="renamed the slot",
        decision_ids=bind_ids(project, human, DecisionLevel.QUESTIONS),
    )
    assert focus_slot_missing(project) == [region]
    assert [f.region_id for f in foci(project)] == [region]


def test_region_kind_needs_no_facet(project: Project, human: Actor) -> None:
    from factory.services.regions import define_region

    qid = record_pilot_question(project, human)
    with pytest.raises(FactoryValidationError) as caught:
        define_region(
            project,
            human,
            kind=RegionKind.REGION,
            name="r",
            definition="d",
            rules=RULES,
            facet=Facet(question_id=qid, slot="population"),
        )
    assert caught.value.issues[0].field == "facet"
    with pytest.raises(FactoryValidationError) as missing:
        define_region(project, human, kind=RegionKind.FOCUS, name="f", definition="d", rules=RULES)
    assert missing.value.issues[0].field == "facet"
    assert define_region(
        project, human, kind=RegionKind.REGION, name="r", definition="d", rules=RULES
    )
