"""Check rules and the recommendation figure of suggest and select (slice 8, plan task A8)."""

from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.model.project import RigorMode
from factory.model.question import QuestionRecorded, question_version
from factory.model.screening import Channel
from factory.services import decisions as decisions_service
from factory.services.check import _findings_as
from factory.services.context import Project
from factory.services.decision_check import recommendation_figure
from factory.services.project import project_status
from factory.services.question import record_question, state_goal
from tests.experiment_helpers import inject, raw_event
from tests.helpers import bind_ids, pilot_question_spec

CODES = {"record-without-selection", "selection-not-acted", "ungrounded-item"}


def _mine(project: Project, mode: RigorMode) -> dict[str, tuple[str, list[str]]]:
    return {f.code: (f.severity, f.refs) for f in _findings_as(project, mode) if f.code in CODES}


def _suggest(
    project: Project, agent: Actor, level: DecisionLevel, *items: DecisionItem, subject: str
) -> str:
    return decisions_service.suggest(project, agent, level, subject, "Why this step.", items)


def test_a_record_written_while_exploratory_stays_a_warning_in_every_mode(
    explore_project: Project, agent: Actor
) -> None:
    project = explore_project
    state_goal(project, agent, "Compare attention on vision")
    result = record_question(project, agent, pilot_question_spec())
    for mode in (RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC):
        found = _mine(project, mode)["record-without-selection"]
        assert found == ("warning", [result.question_id])


def test_a_record_written_while_binding_was_required_is_an_error_after(
    project: Project, agent: Actor
) -> None:
    spec = pilot_question_spec()
    question_id = question_version(spec)
    payload = QuestionRecorded(question_id=question_id, spec=spec, decision_ids=())
    inject(project, raw_event(project, "question.recorded", agent, payload.model_dump(mode="json")))
    for mode, severity in (
        (RigorMode.EXPLORATORY, "warning"),
        (RigorMode.PILOT, "error"),
        (RigorMode.SYSTEMATIC, "error"),
    ):
        found = _mine(project, mode)["record-without-selection"]
        assert found == (severity, [question_id])


def test_a_record_citing_a_selection_has_no_finding_and_closes_the_selection(
    project: Project, agent: Actor
) -> None:
    state_goal(project, agent, "Compare attention on vision")
    ids = bind_ids(project, agent, DecisionLevel.QUESTIONS)
    assert _mine(project, RigorMode.PILOT) == {"selection-not-acted": ("warning", ids)}
    record_question(project, agent, pilot_question_spec(), decision_ids=ids)
    assert _mine(project, RigorMode.PILOT) == {}


def test_goal_and_plan_selections_feed_no_record_and_are_not_flagged(
    project: Project, agent: Actor
) -> None:
    bind_ids(project, agent, DecisionLevel.GOAL)
    bind_ids(project, agent, DecisionLevel.PLAN)
    assert _mine(project, RigorMode.PILOT) == {}


def test_ungrounded_items_are_counted_until_the_set_is_superseded(
    project: Project, agent: Actor
) -> None:
    first = _suggest(
        project,
        agent,
        DecisionLevel.GOAL,
        DecisionItem(item_id="I01", text="One"),
        DecisionItem(item_id="I02", text="Two", grounds=("prb_1",)),
        subject="goal-wording",
    )
    assert _mine(project, RigorMode.PILOT) == {"ungrounded-item": ("warning", [first])}
    second = decisions_service.suggest(
        project,
        agent,
        DecisionLevel.GOAL,
        "goal-wording",
        "Revised.",
        (DecisionItem(item_id="I01", text="One", grounds=("prb_1",)),),
        supersedes=first,
    )
    assert second != first
    assert _mine(project, RigorMode.PILOT) == {}


def test_recommendation_share_counts_selections_that_took_every_recommended_item(
    project: Project, agent: Actor, human: Actor
) -> None:
    assert recommendation_figure(project).share is None
    items = (
        DecisionItem(item_id="I01", text="A", recommended=True, grounds=("g",)),
        DecisionItem(item_id="I02", text="B", grounds=("g",)),
    )
    taken = _suggest(project, agent, DecisionLevel.PROTOCOL, *items, subject="tooling")
    declined = _suggest(project, agent, DecisionLevel.PROTOCOL, *items, subject="tooling")
    _suggest(project, agent, DecisionLevel.PROTOCOL, *items, subject="tooling")  # still open
    decisions_service.select(project, human, taken, ["I01"], [], "", Channel.CLI)
    decisions_service.select(project, human, declined, ["I02"], [], "", Channel.CLI)
    figure = recommendation_figure(project)
    assert (figure.with_recommendation, figure.followed_in_full, figure.share) == (2, 1, 0.5)
    status = project_status(project).decisions
    assert (status.open, status.selected, status.recommendation_followed) == (1, 2, 0.5)
