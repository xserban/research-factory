"""The versioned question: its hash, its validation rules, and its projection."""

import pytest
from pydantic import ValidationError

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.question import NonGoal, QuestionSpec, Slot, SubQuestion, question_version
from factory.services.context import Project
from factory.services.project import init_project, project_status
from factory.services.question import (
    current_question,
    get_question,
    goals,
    record_question,
    state_goal,
)
from tests.helpers import SESSION, bind_ids


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
        record_question(
            project,
            agent,
            spec(non_goals=_non_goals(2)),
        )
    assert e.value.issues[0].field == "non_goals"
    assert project_status(project).events_total == before


def test_exploratory_accepts_one_non_goal(
    settings: Settings, clock: FixedClock, agent: Actor
) -> None:
    project = init_project(settings, "explore", "exploratory", session=SESSION, clock=clock)
    state_goal(project, agent, "linear attention for vision")
    result = record_question(
        project,
        agent,
        spec(non_goals=_non_goals(1)),
        decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS),
    )
    assert result.created is True


def test_open_slots_more_than_half_rejected_in_pilot(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    slots = (
        Slot(name="a", open="x", resolve_in="protocol"),
        Slot(name="b", open="y", resolve_in="protocol"),
        Slot(name="c", value="z"),
    )
    with pytest.raises(FactoryValidationError) as e:
        record_question(
            project,
            agent,
            spec(slots=slots),
        )
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
        record_question(
            project,
            agent,
            spec(objectives=" "),
        )
    assert e.value.issues[0].field == "objectives"


def test_identical_resubmission_writes_nothing(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    first = record_question(
        project, agent, spec(), decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    before = project_status(project).events_total
    again = record_question(
        project, agent, spec(), decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    assert first.created is True
    assert again.created is False
    assert again.question_id == first.question_id
    assert project_status(project).events_total == before


def test_prose_only_change_keeps_the_version(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    first = record_question(
        project, agent, spec(), decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    result = record_question(
        project,
        agent,
        spec(rationale="A sharper reason."),
        decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS),
    )
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
    first = record_question(
        project, agent, spec(), decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    changed = spec(primary_question="Does linear attention match softmax on language?")
    with pytest.raises(FactoryValidationError) as e:
        record_question(project, agent, changed)
    assert e.value.issues[0].field == "reason"

    second = record_question(
        project,
        agent,
        changed,
        reason="narrowed to language",
        decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS),
    )
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
    record_question(
        project, agent, spec(), decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT input_blob FROM events WHERE type = 'question.recorded'"
        ).all()
    assert len(rows) == 1
    assert rows[0][0] is not None


def test_question_rebuild_equals_incremental(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "linear attention for vision")
    record_question(
        project, agent, spec(), decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS)
    )
    record_question(
        project,
        agent,
        spec(rationale="A sharper reason."),
        decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS),
    )
    record_question(
        project,
        agent,
        spec(primary_question="Other?"),
        reason="changed",
        decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS),
    )
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    current = current_question(project)
    assert current is not None and current.spec.primary_question == "Other?"


def test_raw_goal_with_rigor_failure_writes_nothing(project: Project, agent: Actor) -> None:
    # Invalid input writes nothing: a refused question takes its goal with it.
    before = project_status(project).events_total
    with pytest.raises(FactoryValidationError) as refused:
        record_question(
            project,
            agent,
            spec(non_goals=()),
            raw_goal="Compare attention",
        )
    assert [issue.field for issue in refused.value.issues] == ["non_goals"]
    assert project_status(project).events_total == before
    assert goals(project) == []
    assert current_question(project) is None


def test_raw_goal_and_question_are_written_together(project: Project, agent: Actor) -> None:
    result = record_question(
        project,
        agent,
        spec(),
        raw_goal="Compare attention on vision",
        decision_ids=bind_ids(project, agent, DecisionLevel.QUESTIONS),
    )
    assert result.created is True
    assert result.goal_event_id is not None
    assert [goal.text for goal in goals(project)] == ["Compare attention on vision"]
    assert current_question(project) is not None
    assert project_status(project).events_by_type["question.goal_stated"] == 1
    assert project_status(project).events_by_type["question.recorded"] == 1


def test_blank_raw_goal_refused_before_any_write(project: Project, agent: Actor) -> None:
    before = project_status(project).events_total
    with pytest.raises(FactoryValidationError) as refused:
        record_question(
            project,
            agent,
            spec(),
            raw_goal="   ",
        )
    assert [issue.field for issue in refused.value.issues] == ["raw_goal"]
    assert project_status(project).events_total == before


def test_spec_without_sub_questions_hashes_as_before() -> None:
    """The key is left out of the hashed form when empty, so old events keep their version."""
    import hashlib

    from factory.canonical import canonical_json

    base = spec()
    legacy = {
        "scheme": base.scheme,
        "primary_question": base.primary_question,
        "slots": [
            [s.name, s.value, s.open, s.resolve_in]
            for s in sorted(base.slots, key=lambda s: s.name)
        ],
        "non_goals": [[g.id, g.text] for g in sorted(base.non_goals, key=lambda g: g.id)],
    }
    expected = "Q@" + hashlib.sha256(canonical_json(legacy)).hexdigest()[:8]
    assert question_version(base) == expected


def test_old_event_without_sub_questions_folds_unchanged() -> None:
    base = spec()
    old = base.model_dump(mode="json")
    del old["sub_questions"]
    assert QuestionSpec.model_validate(old) == base


def test_sub_questions_change_the_version_but_serves_does_not() -> None:
    one = (SubQuestion(id="SQ1", text="Which metric?", serves="KR1"),)
    other_serves = (SubQuestion(id="SQ1", text="Which metric?", serves="KR2"),)
    other_text = (SubQuestion(id="SQ1", text="Which cost?"),)
    base = question_version(spec())
    with_one = question_version(spec().model_copy(update={"sub_questions": one}))
    assert with_one != base
    assert with_one == question_version(spec().model_copy(update={"sub_questions": other_serves}))
    assert with_one != question_version(spec().model_copy(update={"sub_questions": other_text}))


def test_sub_question_ids_unique_and_well_formed() -> None:
    first = SubQuestion(id="SQ1", text="a")
    with pytest.raises(ValidationError):
        QuestionSpec.model_validate(
            {**spec().model_dump(), "sub_questions": [first.model_dump(), first.model_dump()]}
        )
    for bad in ("SQ", "SQ123", "RQ1"):
        with pytest.raises(ValidationError):
            SubQuestion(id=bad, text="a")
    with pytest.raises(ValidationError):
        SubQuestion(id="SQ1", text="  ")
