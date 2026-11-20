"""A PRESS review comes from another session than the protocol's author (lane L14), in pilot and
systematic projects and at any non-attended level; exploratory attended projects keep the old rule.
"""

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionLevel
from factory.model.protocol import PressElement, PressFinding
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.protocol import press_review, record_protocol
from tests.helpers import SESSION, bind_ids, pilot_protocol_spec, record_pilot_question, reviewer_of

FINDING = PressFinding(element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor")


def _draft(project: Project, agent: Actor, human: Actor) -> str:
    question_id = record_pilot_question(project, agent)
    spec = pilot_protocol_spec(question_id, None, reviewer=human.id)
    return record_protocol(
        project,
        agent,
        spec,
        ready=False,
        decision_ids=bind_ids(project, agent, DecisionLevel.PROTOCOL),
    ).protocol_id


def _reviews(project: Project) -> int:
    return sum(
        1
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "protocol.press_reviewed"
    )


def test_pilot_refuses_the_authors_session(project: Project, agent: Actor, human: Actor) -> None:
    protocol_id = _draft(project, agent, human)
    assert agent.session == SESSION
    with pytest.raises(FactoryValidationError) as refused:
        press_review(project, agent, protocol_id, (FINDING,))
    [issue] = refused.value.issues
    assert issue.field == "session"
    assert issue.reason.startswith("same-session-as-author")
    assert _reviews(project) == 0
    assert press_review(project, reviewer_of(agent), protocol_id, (FINDING,)).startswith("prs_")
    assert _reviews(project) == 1


def test_exploratory_attended_is_unchanged(
    explore_project: Project, agent: Actor, human: Actor
) -> None:
    protocol_id = _draft(explore_project, agent, human)
    assert press_review(explore_project, agent, protocol_id, (FINDING,)).startswith("prs_")


def test_a_non_attended_level_refuses_even_exploratory(
    settings: Settings, clock: FixedClock, agent: Actor, human: Actor
) -> None:
    project = init_project(
        settings,
        "supervised",
        "exploratory",
        session=SESSION,
        clock=clock,
        autonomy_level="supervised",
    )
    protocol_id = _draft(project, agent, human)
    with pytest.raises(FactoryValidationError) as refused:
        press_review(project, agent, protocol_id, (FINDING,))
    assert [i.field for i in refused.value.issues] == ["session"]
    assert _reviews(project) == 0
    assert press_review(project, reviewer_of(agent), protocol_id, (FINDING,)).startswith("prs_")
