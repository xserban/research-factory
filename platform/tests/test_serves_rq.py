"""The optional `serves_rq` field on leads and hypotheses (design note 2026-11-23, part 1).

The field is optional, schema version 1; an event without it reads as absent. A recorded
sub-question set bounds the ids; with none recorded any well-formed id is accepted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionLevel
from factory.model.hypotheses import DEFAULT_SERVES_RQ, LeadInput, LeadRecorded
from factory.model.question import SubQuestion
from factory.services import hub_build as hb
from factory.services import hub_hypotheses as hh
from factory.services.cards import create_card
from factory.services.context import Project
from factory.services.hypotheses import draft_hypothesis, hypothesis_view
from factory.services.leads import lead_view, record_lead
from factory.services.question import record_question, state_goal
from tests.helpers import bind_ids, pilot_question_spec
from tests.hypothesis_helpers import (
    DRAFTER,
    LEAD_AUTHOR,
    LEAD_TEXT,
    card_trigger,
    exploratory_card,
    lead_input,
    make_spec,
    promoted_lead,
)

TRIGGER = card_trigger("mcd_01JZ9Q3K5M7N8P0R2S4T6V8W0X")


def test_model_accepts_and_omits_the_field() -> None:
    assert LeadInput(text=LEAD_TEXT, triggers=(TRIGGER,)).serves_rq is None
    assert LeadInput(text=LEAD_TEXT, triggers=(TRIGGER,), serves_rq="RQ4").serves_rq == "RQ4"
    with pytest.raises(ValidationError):
        LeadInput(text=LEAD_TEXT, triggers=(TRIGGER,), serves_rq="not a question id")
    assert DEFAULT_SERVES_RQ == ("RQ4", "RQ5")


def test_old_payload_without_the_field_reads_as_absent() -> None:
    old = {"lead_id": "led_01JZ9Q3K5M7N8P0R2S4T6V8W0X", "text": "t", "triggers": []}
    assert LeadRecorded.model_validate(old).serves_rq is None


def test_lead_records_and_reads_back_the_field(project: Project, human: Actor) -> None:
    card = exploratory_card(project, human)
    plain = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(card)))
    view = lead_view(project, plain)
    assert view is not None and view.serves_rq is None
    item = LeadInput(text=LEAD_TEXT, triggers=(card_trigger(card),), serves_rq="RQ2")
    served = lead_view(project, record_lead(project, LEAD_AUTHOR, item))
    assert served is not None and served.serves_rq == "RQ2"


def test_hypothesis_records_and_reads_back_the_field(project: Project, human: Actor) -> None:
    card = exploratory_card(project, human)
    lead = promoted_lead(project, human, card_trigger(card))
    plain, version = draft_hypothesis(project, DRAFTER, make_spec(lead=lead))
    served, served_version = draft_hypothesis(
        project, DRAFTER, make_spec(lead=lead), serves_rq="RQ5"
    )
    assert version == served_version  # the field is a link, not part of H@
    first = hypothesis_view(project, plain)
    second = hypothesis_view(project, served)
    assert first is not None and first.serves_rq is None
    assert second is not None and second.serves_rq == "RQ5"


def test_unknown_id_is_refused_when_sub_questions_are_recorded(
    project: Project, agent: Actor
) -> None:
    state_goal(project, agent, "Compare attention on vision")
    spec = pilot_question_spec().model_copy(
        update={"sub_questions": (SubQuestion(id="SQ1", text="Which metric?"),)}
    )
    record_question(
        project, agent, spec, decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    card = create_card(project, DRAFTER, "problem", "Dense prediction under a memory bound", "obd")
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as e:
        record_lead(
            project,
            LEAD_AUTHOR,
            LeadInput(text=LEAD_TEXT, triggers=(card_trigger(card),), serves_rq="SQ9"),
        )
    assert e.value.issues[0].field == "serves_rq"
    with pytest.raises(FactoryValidationError) as e2:
        draft_hypothesis(project, DRAFTER, make_spec(), serves_rq="SQ9")
    assert any(i.field == "serves_rq" for i in e2.value.issues)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    ok = record_lead(
        project,
        LEAD_AUTHOR,
        LeadInput(text=LEAD_TEXT, triggers=(card_trigger(card),), serves_rq="SQ1"),
    )
    view = lead_view(project, ok)
    assert view is not None and view.serves_rq == "SQ1"


def test_hub_payload_groups_by_the_field(project: Project, human: Actor) -> None:
    card = exploratory_card(project, human)
    record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(card)))
    record_lead(
        project,
        LEAD_AUTHOR,
        LeadInput(text=LEAD_TEXT, triggers=(card_trigger(card),), serves_rq="RQ2"),
    )
    lead = promoted_lead(project, human, card_trigger(card))
    draft_hypothesis(project, DRAFTER, make_spec(lead=lead), serves_rq="RQ2")
    payload = hh.build(hb.HubContext(project))
    groups = {g["id"]: g for g in payload["rq"]}
    assert next(iter(groups)) == "default"
    assert groups["default"]["label"] == "RQ4, RQ5 (default)"
    assert groups["default"]["leads"] == 2  # the plain lead and the promoted one
    assert groups["default"]["hypotheses"] == 0
    assert groups["RQ2"]["leads"] == 1 and groups["RQ2"]["hypotheses"] == 1
    assert [i["serves_rq"] for i in payload["hypotheses"]["items"]] == ["RQ2"]
