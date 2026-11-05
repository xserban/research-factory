"""Leads: resolved triggers, prior failures, decisions under the gate policy (slice 6, H-C 1)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.hypotheses import (
    DiscardReason,
    LeadDecided,
    LeadInput,
    Trigger,
    TriggerKind,
)
from factory.modules.contract import PolicyKind
from factory.services import leads as leads_service
from factory.services.context import Project
from factory.services.leads import decide_lead, lead_view, list_leads, prior_for, record_lead
from factory.services.matching import match
from tests.card_helpers import cw
from tests.finder_helpers import MatchWorld, mw
from tests.hypothesis_helpers import (
    CRITIC,
    DRAFTER,
    LEAD_AUTHOR,
    LEAD_TEXT,
    OTHER,
    card_trigger,
    exploratory_card,
    lead_input,
)
from tests.intuition_helpers import IWorld, iw
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world

LEAD_GATE = "hypotheses.lead_decide"


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def _record(project: Project, mw: MatchWorld, actor: Actor = LEAD_AUTHOR) -> str:
    return record_lead(project, actor, lead_input(LEAD_TEXT, card_trigger(mw.ok)))


def test_lead_without_trigger_refused() -> None:  # acceptance 8
    with pytest.raises(ValidationError):
        LeadInput(text=LEAD_TEXT, triggers=())


def test_text_length_limit() -> None:
    trigger = card_trigger("mcd_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    with pytest.raises(ValidationError):
        LeadInput(text="x" * 601, triggers=(trigger,))
    with pytest.raises(ValidationError):
        LeadInput(text="   ", triggers=(trigger,))
    assert LeadInput(text="x" * 600, triggers=(trigger,))


def test_trigger_shape_is_checked_per_kind() -> None:
    with pytest.raises(ValidationError):
        Trigger(kind=TriggerKind.CARD, ref="not-a-card")
    with pytest.raises(ValidationError):
        Trigger(kind=TriggerKind.CARD, ref="mcd_01JZ9Q3K5M7N8P0R2S4T6V8W0X", row={"a": 1})
    with pytest.raises(ValidationError):
        Trigger(kind=TriggerKind.MATCH, ref="0123456789abcdef")  # a builder trigger needs its row


def test_dangling_trigger_refused(project: Project, mw: MatchWorld) -> None:
    unknown = card_trigger("mcd_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    with pytest.raises(FactoryValidationError) as err:
        record_lead(project, DRAFTER, lead_input(LEAD_TEXT, card_trigger(mw.ok), unknown))
    assert [(i.field, i.reason) for i in err.value.issues] == [("triggers.1", "unknown")]
    assert list_leads(project) == []
    gone = Trigger(kind=TriggerKind.WORK, ref="rf:nobody2020-nothing-1-00000000")
    with pytest.raises(FactoryValidationError) as err:
        record_lead(project, DRAFTER, lead_input(LEAD_TEXT, gone))
    assert err.value.issues[0].field == "triggers.0"


def test_resolved_triggers_of_several_kinds(project: Project, mw: MatchWorld) -> None:
    work = Trigger(kind=TriggerKind.WORK, ref=mw.cw.source)
    idea = Trigger(kind=TriggerKind.IDEA, ref=mw.cw.idea)
    lead_id = record_lead(project, DRAFTER, lead_input(LEAD_TEXT, work, idea, card_trigger(mw.ok)))
    view = lead_view(project, lead_id)
    assert view is not None and view.state == "open"
    assert [t.kind for t in view.triggers] == [TriggerKind.WORK, TriggerKind.IDEA, TriggerKind.CARD]


def _match_trigger(project: Project, mw: MatchWorld, **change: object) -> Trigger:
    page = match(project, mw.problem)
    row = next(r for r in page.rows if r.card_id == mw.ok)
    stored = {"problem_id": mw.problem, **row.model_dump(mode="json"), **change}
    return Trigger(kind=TriggerKind.MATCH, ref=page.match_key, row=stored)  # type: ignore[arg-type]


def test_builder_trigger_must_match_current_row(project: Project, mw: MatchWorld) -> None:
    good = _match_trigger(project, mw)
    lead_id = record_lead(project, DRAFTER, lead_input(LEAD_TEXT, good))
    stored = lead_view(project, lead_id)
    assert stored is not None and stored.triggers[0].row == good.row  # what the proposer saw
    stale = _match_trigger(project, mw, satisfied=[])
    with pytest.raises(FactoryValidationError) as err:
        record_lead(project, DRAFTER, lead_input(LEAD_TEXT, stale))
    assert [(i.field, i.reason) for i in err.value.issues] == [("triggers.0", "trigger-stale")]
    wrong_key = good.model_copy(update={"ref": "0" * 16})
    with pytest.raises(FactoryValidationError):
        record_lead(project, DRAFTER, lead_input(LEAD_TEXT, wrong_key))


def test_prior_lists_a_discarded_lead_sharing_a_card(
    project: Project, human: Actor, mw: MatchWorld
) -> None:  # acceptance 8 (the hypothesis part is in test_hypotheses)
    first = _record(project, mw)
    assert lead_view(project, first).prior == ()  # type: ignore[union-attr]
    decide_lead(project, human, first, "discard", DiscardReason.PRIOR_FAILURE, "tried and failed")
    second = record_lead(project, DRAFTER, lead_input(LEAD_TEXT, card_trigger(mw.ok)))
    view = lead_view(project, second)
    assert view is not None and view.prior == (first,) and view.prior_total == 1
    # the same property reached through another card of the problem shares a key
    other = record_lead(project, DRAFTER, lead_input(LEAD_TEXT, card_trigger(mw.unknown)))
    assert first in lead_view(project, other).prior  # type: ignore[union-attr]
    # an open or promoted lead is not a failure
    promoted = _record(project, mw)
    decide_lead(project, human, promoted, "promote")
    assert promoted not in lead_view(project, _record(project, mw)).prior  # type: ignore[union-attr]


def test_prior_capped_with_total(
    project: Project, mw: MatchWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = [f"hyp_{i:026d}" for i in range(60)]
    monkeypatch.setattr(leads_service, "PRIOR_SOURCES", [lambda _p, _k: ids])
    prior, total = prior_for(project, [mw.ok])
    assert (len(prior), total) == (50, 60) and prior == sorted(ids)[:50]
    view = lead_view(project, _record(project, mw))
    assert view is not None and len(view.prior) == 50 and view.prior_total == 60


def test_discard_needs_reason(project: Project, human: Actor, mw: MatchWorld) -> None:
    lead_id = _record(project, mw)
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, human, lead_id, "discard")
    assert err.value.issues[0].field == "reason"
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, human, lead_id, "discard", DiscardReason.OTHER)
    assert err.value.issues[0].field == "note"
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, human, lead_id, "park", DiscardReason.DUPLICATE)
    assert err.value.issues[0].field == "reason"
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, human, "led_01JZ9Q3K5M7N8P0R2S4T6V8W0X", "park")
    assert err.value.issues[0].field == "lead_id"
    assert lead_view(project, lead_id).state == "open"  # type: ignore[union-attr]
    decide_lead(project, human, lead_id, "discard", DiscardReason.OTHER, "see the note")
    assert lead_view(project, lead_id).state == "discarded"  # type: ignore[union-attr]


def test_decisions_supersede_and_nothing_is_deleted(
    project: Project, human: Actor, mw: MatchWorld
) -> None:
    lead_id = _record(project, mw)
    decide_lead(project, human, lead_id, "park")
    assert lead_view(project, lead_id).state == "parked"  # type: ignore[union-attr]
    decide_lead(project, human, lead_id, "promote")
    view = lead_view(project, lead_id)
    assert view is not None and view.state == "promoted"
    assert len(_events(project, "lead.decided")) == 2
    assert [v.lead_id for v in list_leads(project, states=["promoted"])] == [lead_id]
    assert list_leads(project, states=["parked"]) == []


def test_human_policy_refuses_agent(project: Project, mw: MatchWorld) -> None:
    lead_id = _record(project, mw)
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, OTHER, lead_id, "promote")
    assert err.value.issues[0].field == "actor"
    assert err.value.issues[0].reason == f"gate {LEAD_GATE} is human: an agent cannot pass it"
    assert _events(project, "lead.decided") == []


def test_author_cannot_decide_own_lead(explore_project: Project, human: Actor) -> None:  # acc. 8
    project = explore_project  # exploratory preset: an agent passes `hypotheses.lead_decide`
    card = exploratory_card(project, human)
    lead_id = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(card)))
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, LEAD_AUTHOR, lead_id, "promote")
    assert err.value.issues[0].field == "session"
    decide_lead(project, OTHER, lead_id, "promote")
    view = lead_view(project, lead_id)
    assert view is not None and view.state == "promoted"
    [event] = _events(project, "lead.decided")
    assert event.payload["policy"] == "agent" and event.actor.kind == "agent"


def test_projector_ignores_inconsistent_decisions(project: Project, mw: MatchWorld) -> None:
    lead_id = _record(project, mw)
    # by hand: an agent claims the gate is `agent` although the pilot policy is `human`
    forged = LeadDecided(lead_id=lead_id, decision="promote", policy=PolicyKind.AGENT)
    project.record(
        [
            project.events.make(
                "lead.decided",
                forged,
                OTHER,
                input_blob=project.blobs.put_json({"forged": True}),
            )
        ]
    )
    assert lead_view(project, lead_id).state == "open"  # type: ignore[union-attr]


def test_event_provenance(project: Project, mw: MatchWorld) -> None:
    item = lead_input(LEAD_TEXT, card_trigger(mw.ok), framework="scamper")
    lead_id = record_lead(project, LEAD_AUTHOR, item)
    [event] = _events(project, "lead.recorded")
    assert event.actor.model == "model-lead" and event.actor.skill == "rf-ideate@1a2b3c4d"
    assert event.input_blob is not None
    assert project.blobs.get_json(event.input_blob) == item.model_dump(mode="json")
    assert event.payload["lead_id"] == lead_id and lead_id in event.refs
    assert lead_view(project, lead_id).framework == "scamper"  # type: ignore[union-attr]


def test_interpretation_and_concept_triggers_resolve(project: Project, iw: IWorld) -> None:
    from factory.model.intuition import ConceptInput
    from factory.services.concepts import define_concept
    from factory.services.interpretations import record_interpretation

    interpretation = record_interpretation(project, iw.human, iw.entry())
    concept = define_concept(
        project,
        iw.human,
        ConceptInput.model_validate(
            {
                "name": "random features",
                "source": {"kind": "textbook", "citation": "Textbook, chapter 3"},
            }
        ),
    )
    ghost_i = "int_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
    ghost_c = "cpt_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
    lead = record_lead(
        project,
        LEAD_AUTHOR,
        lead_input(
            LEAD_TEXT,
            Trigger(kind=TriggerKind.INTERPRETATION, ref=interpretation),
            Trigger(kind=TriggerKind.CONCEPT, ref=concept),
        ),
    )
    assert lead_view(project, lead) is not None
    with pytest.raises(FactoryValidationError) as err:
        record_lead(
            project,
            LEAD_AUTHOR,
            lead_input(
                LEAD_TEXT,
                Trigger(kind=TriggerKind.INTERPRETATION, ref=ghost_i),
                Trigger(kind=TriggerKind.CONCEPT, ref=ghost_c),
            ),
        )
    assert [(i.field, i.reason) for i in err.value.issues] == [
        ("triggers.0", "unknown"),
        ("triggers.1", "unknown"),
    ]


def test_blank_decision_note_is_a_structured_error(
    project: Project, human: Actor, mw: MatchWorld
) -> None:
    lead_id = _record(project, mw)
    with pytest.raises(FactoryValidationError) as err:
        decide_lead(project, human, lead_id, "park", None, "   ")
    assert [(i.field, i.reason) for i in err.value.issues] == [("note", "must not be blank")]
    assert lead_view(project, lead_id).state == "open"  # type: ignore[union-attr]
