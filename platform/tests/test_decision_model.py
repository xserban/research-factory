"""Decision events: payload invariants (slice 8, plan A1)."""

from typing import Any

import pytest
from pydantic import ValidationError

from factory.model.decisions import (
    TECHNICAL_SUBJECTS,
    DecisionItem,
    DecisionLevel,
    DecisionSelected,
    DecisionSuggested,
)
from factory.model.screening import Channel

DEC = "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
DEC2 = "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0Y"


def item(item_id: str = "I01", **over: Any) -> DecisionItem:
    return DecisionItem(**{"item_id": item_id, "text": "Exclude preprints", **over})


def suggested(**over: Any) -> DecisionSuggested:
    body: dict[str, Any] = {
        "decision_id": DEC,
        "level": DecisionLevel.PROTOCOL,
        "subject": "criteria-exclusion",
        "explanation": "The exclusion criteria set what leaves the corpus; here is why.",
        "items": (item("I01"), item("I02")),
    }
    body.update(over)
    return DecisionSuggested(**body)


def test_levels() -> None:
    assert [lv.value for lv in DecisionLevel] == [
        "goal",
        "questions",
        "plan",
        "seeds",
        "probe",
        "protocol",
    ]


def test_valid_suggestion_with_and_without_grounds() -> None:
    p = suggested(items=(item("I01", grounds=("prb_x", "dec_y")), item("I02")))
    assert p.items[1].grounds == ()
    assert p.supersedes is None


@pytest.mark.parametrize("bad", ["", "   "])
def test_item_text_and_explanation_non_blank(bad: str) -> None:
    with pytest.raises(ValidationError):
        item(text=bad)
    with pytest.raises(ValidationError):
        suggested(explanation=bad)


@pytest.mark.parametrize("bad", ["1", "i01", "I1", "X01", "A01"])
def test_item_id_shape(bad: str) -> None:
    with pytest.raises(ValidationError):
        item(bad)


def test_needs_an_item_and_unique_ids() -> None:
    with pytest.raises(ValidationError):
        suggested(items=())
    with pytest.raises(ValidationError, match="unique"):
        suggested(items=(item("I01"), item("I01")))


def test_decision_id_and_subject_shape() -> None:
    with pytest.raises(ValidationError):
        suggested(decision_id="led_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    with pytest.raises(ValidationError):
        suggested(subject="Criteria Exclusion")


def test_cannot_supersede_itself() -> None:
    with pytest.raises(ValidationError):
        suggested(supersedes=DEC)
    assert suggested(supersedes=DEC2).supersedes == DEC2


def test_recommended_refused_on_research_subjects() -> None:
    with pytest.raises(ValidationError, match="research subject"):
        suggested(items=(item("I01", recommended=True),))


@pytest.mark.parametrize("subject", sorted(TECHNICAL_SUBJECTS))
def test_recommended_allowed_on_technical_subjects(subject: str) -> None:
    p = suggested(subject=subject, items=(item("I01", recommended=True),))
    assert p.items[0].recommended


def test_technical_subjects_are_the_stated_set() -> None:
    assert {"tooling", "ordering", "fix", "model-choice", "setting"} == TECHNICAL_SUBJECTS


def test_selection_forms() -> None:
    assert DecisionSelected(decision_id=DEC, selected=("I01",)).channel is Channel.MCP
    assert DecisionSelected(decision_id=DEC, added=("my own",)).added == ("my own",)
    none = DecisionSelected(decision_id=DEC, note="none fits the aim")
    assert none.selected == () and none.added == ()


def test_empty_selection_needs_a_note() -> None:
    with pytest.raises(ValidationError, match="note"):
        DecisionSelected(decision_id=DEC)
    with pytest.raises(ValidationError):
        DecisionSelected(decision_id=DEC, note="  ")


def test_selected_ids_unique_and_well_formed() -> None:
    with pytest.raises(ValidationError, match="unique"):
        DecisionSelected(decision_id=DEC, selected=("I01", "I01"))
    with pytest.raises(ValidationError):
        DecisionSelected(decision_id=DEC, selected=("x",))


def test_added_text_non_blank_and_reconstructed_flag() -> None:
    with pytest.raises(ValidationError):
        DecisionSelected(decision_id=DEC, added=(" ",))
    assert DecisionSelected(decision_id=DEC, selected=("I01",), reconstructed=True).reconstructed


def test_extra_fields_refused() -> None:
    with pytest.raises(ValidationError):
        DecisionSelected(decision_id=DEC, selected=("I01",), who="me")  # type: ignore[call-arg]
