"""The versioned question: its hash, its validation rules, and its projection."""

import pytest
from pydantic import ValidationError

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.question import NonGoal, QuestionSpec, Slot, question_version
from factory.services.context import Project
from factory.services.project import init_project, project_status
from factory.services.question import (
    current_question,
    get_question,
    goals,
    record_question,
    state_goal,
)
from tests.helpers import SESSION


def _slots() -> tuple[Slot, ...]:
    return (
        Slot(name="population", value="vision transformers"),
        Slot(name="outcome", open="which accuracy metric", resolve_in="protocol"),
    )


def _non_goals(count: int = 3) -> tuple[NonGoal, ...]:
    return tuple(NonGoal(id=f"NG{i:02d}", text=f"not topic {i}") for i in range(1, count + 1))


def spec(
    *,
    primary_question: str = "Does linear attention match softmax on vision?",
    slots: tuple[Slot, ...] | None = None,
    non_goals: tuple[NonGoal, ...] | None = None,
    rationale: str = "Vision is the target domain.",
    objectives: str = "Compare accuracy and cost.",
    scheme_rationale: str = "PICO fits a comparison.",
) -> QuestionSpec:
    return QuestionSpec(
        scheme="PICO",
        primary_question=primary_question,
        slots=_slots() if slots is None else slots,
        non_goals=_non_goals() if non_goals is None else non_goals,
        rationale=rationale,
        objectives=objectives,
        scheme_rationale=scheme_rationale,
    )


def test_version_ignores_prose() -> None:
    base = spec()
    changed = spec(
        rationale="A different reason.",
        objectives="Other objectives.",
        scheme_rationale="Other scheme reason.",
    )
    assert question_version(base) == question_version(changed)
    assert question_version(base).startswith("Q@")


def test_version_changes_with_slot_value() -> None:
    other = spec(slots=(Slot(name="population", value="language models"), *_slots()[1:]))
    assert question_version(spec()) != question_version(other)


def test_version_is_order_independent() -> None:
    reordered = spec(slots=tuple(reversed(_slots())), non_goals=tuple(reversed(_non_goals())))
    assert question_version(spec()) == question_version(reordered)


@pytest.mark.parametrize("value", [" tbd ", "TBD", "Tbd "])
def test_tbd_slot_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Slot(name="population", value=value)


def test_open_slot_needs_resolve_in() -> None:
    with pytest.raises(ValidationError):
        Slot(name="outcome", open="which metric")


def test_slot_has_exactly_one_of_value_and_open() -> None:
    with pytest.raises(ValidationError):
        Slot(name="outcome")
    with pytest.raises(ValidationError):
        Slot(name="outcome", value="accuracy", open="which metric", resolve_in="protocol")


def test_duplicate_slot_names_rejected() -> None:
    with pytest.raises(ValidationError):
        spec(slots=(Slot(name="p", value="a"), Slot(name="p", value="b")))


def test_pilot_needs_three_non_goals(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    before = project_status(project).events_total
    with pytest.raises(FactoryValidationError) as e:
        record_question(project, agent, spec(non_goals=_non_goals(2)))
    assert e.value.issues[0].field == "non_goals"
    assert project_status(project).events_total == before


def test_exploratory_accepts_one_non_goal(
    settings: Settings, clock: FixedClock, agent: Actor
) -> None:
    project = init_project(settings, "explore", "exploratory", session=SESSION, clock=clock)
    state_goal(project, agent, "linear attention for vision")
    result = record_question(project, agent, spec(non_goals=_non_goals(1)))
    assert result.created is True


def test_open_slots_more_than_half_rejected_in_pilot(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    slots = (
        Slot(name="a", open="x", resolve_in="protocol"),
        Slot(name="b", open="y", resolve_in="protocol"),
        Slot(name="c", value="z"),
    )
    with pytest.raises(FactoryValidationError) as e:
        record_question(project, agent, spec(slots=slots))
    assert e.value.issues[0].field == "slots"


def test_question_needs_a_stated_goal(project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as e:
        record_question(project, agent, spec())
    assert e.value.issues[0].field == "raw_goal"


def test_goal_is_stored_verbatim(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "  i want to know if…\n")
    assert goals(project)[0].text == "  i want to know if…\n"


def test_blank_goal_rejected(project: Project, agent: Actor) -> None:
    before = project_status(project).events_total
    with pytest.raises(FactoryValidationError) as e:
        state_goal(project, agent, "  \n")
    assert e.value.issues[0].field == "text"
    assert project_status(project).events_total == before


def test_pilot_needs_rationale_and_objectives(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    with pytest.raises(FactoryValidationError) as e:
        record_question(project, agent, spec(objectives=" "))
    assert e.value.issues[0].field == "objectives"


def test_identical_resubmission_writes_nothing(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    first = record_question(project, agent, spec())
    before = project_status(project).events_total
    again = record_question(project, agent, spec())
    assert first.created is True
    assert again.created is False
    assert again.question_id == first.question_id
    assert project_status(project).events_total == before


def test_prose_only_change_keeps_the_version(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    first = record_question(project, agent, spec())
    result = record_question(project, agent, spec(rationale="A sharper reason."))
    assert result.question_id == first.question_id
    current = current_question(project)
    assert current is not None
    assert current.question_id == first.question_id
    assert current.supersedes is None
    assert current.spec.rationale == "A sharper reason."


def test_semantic_change_needs_reason_and_records_supersedes(
    project: Project, agent: Actor
) -> None:
    state_goal(project, agent, "linear attention for vision")
    first = record_question(project, agent, spec())
    changed = spec(primary_question="Does linear attention match softmax on language?")
    with pytest.raises(FactoryValidationError) as e:
        record_question(project, agent, changed)
    assert e.value.issues[0].field == "reason"

    second = record_question(project, agent, changed, reason="narrowed to language")
    assert second.created is True
    assert second.question_id != first.question_id
    current = current_question(project)
    assert current is not None
    assert current.question_id == second.question_id
    assert current.supersedes == first.question_id
    assert current.reason == "narrowed to language"
    old = get_question(project, first.question_id)
    assert old is not None and old.spec.primary_question == spec().primary_question


def test_agent_question_carries_input_blob(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    record_question(project, agent, spec())
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT input_blob FROM events WHERE type = 'question.recorded'"
        ).all()
    assert len(rows) == 1
    assert rows[0][0] is not None


def test_question_rebuild_equals_incremental(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    record_question(project, agent, spec())
    record_question(project, agent, spec(rationale="A sharper reason."))
    record_question(project, agent, spec(primary_question="Other?"), reason="changed")
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    current = current_question(project)
    assert current is not None and current.spec.primary_question == "Other?"
