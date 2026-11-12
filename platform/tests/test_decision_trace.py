"""A `dec_` id names a screening decision or a decision suggestion: the walk resolves both, and
`check` calls only an id of neither a broken link."""

from __future__ import annotations

from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.services.check import check
from factory.services.context import Project
from factory.services.question import record_question, state_goal
from factory.services.trace import dangling_refs, trace
from tests.experiment_helpers import inject, raw_event
from tests.helpers import bind_ids, pilot_question_spec

UNKNOWN = "dec_01M68X9EG0Q6G9K06D4MS3K7ZZ"


def _broken(project: Project) -> list[str]:
    return [r for f in check(project).findings if f.code == "broken-link" for r in f.refs]


def test_a_cited_decision_suggestion_is_resolved_not_broken(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "Compare attention on vision")
    ids = bind_ids(project, agent, DecisionLevel.QUESTIONS)
    record_question(project, agent, pilot_question_spec(), decision_ids=ids)

    assert _broken(project) == []
    assert dangling_refs(project, ids) == []
    node = trace(project, ids[0], direction="forward")
    assert node.kind == "decision" and node.label == "questions decision: test-setting"
    assert node.event_id.startswith("ev_")


def test_an_unknown_dec_id_is_still_a_broken_link(project: Project, human: Actor) -> None:
    payload = {"model": "m", "cutoff": "2020-01-01", "source": "s"}
    event = raw_event(project, "model.cutoff_declared", human, payload)
    inject(project, event.model_copy(update={"refs": [UNKNOWN]}))

    assert _broken(project) == [UNKNOWN]
    assert dangling_refs(project, [UNKNOWN]) == [UNKNOWN]
