"""The critic review: an artefact-only task and engineered independence (slice 6, H-C task 5)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.hypotheses import (
    CHECKLIST,
    HypothesisReviewed,
    ReviewInput,
    TriggerKind,
)
from factory.model.hypothesis_plan import HypothesisPlan
from factory.services.context import Project
from factory.services.hypotheses import draft_hypothesis, hypothesis_view
from factory.services.hypothesis_review import record_review, review_next
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.tasks import get_task
from tests.hypothesis_helpers import (
    CRITIC,
    DRAFTER,
    HW,
    LEAD_AUTHOR,
    LEAD_TEXT,
    OTHER,
    RATIONALE,
    STATEMENT,
    agent_actor,
    hw,
    make_spec,
)
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_finder_gaps import gw


def _events(project: Project, *types: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


def verdict(recommend: str = "register", **fails: str) -> ReviewInput:
    items = {item: "pass" for item in CHECKLIST}
    items.update({k.replace("_", "-"): v for k, v in fails.items()})
    return ReviewInput.model_validate(
        {"items": items, "notes": {"falsifiable": "the rule is complete"}, "recommend": recommend}
    )


def test_review_payload_is_artefact_only(project: Project, hw: HW) -> None:  # Review Focus 1
    served = review_next(project, CRITIC)
    assert served is not None and served.task.hypothesis_id == hw.hid
    task = get_task(project, served.task_id)
    assert task is not None
    blob = project.blobs.get(task.content_blob).decode()
    assert STATEMENT in blob and hw.version in blob
    assert LEAD_TEXT not in blob and RATIONALE not in blob
    [lead_event] = _events(project, "lead.recorded")
    assert lead_event.input_blob is not None
    assert project.blobs.get(lead_event.input_blob).decode() not in blob
    assert served.task.checklist == list(CHECKLIST)
    assert [(t.kind, t.ref) for t in served.task.triggers] == [(TriggerKind.WORK, hw.works[0])]
    assert "lead" not in served.task.spec_without_prose
    assert set(served.task.spec_without_prose) == {
        "kind",
        "treatment",
        "baseline",
        "metric",
        "conditions",
        "prediction",
        "decision_rule",
        "test",
    }


def test_critic_independence(project: Project, human: Actor, hw: HW) -> None:  # Review Focus 2
    before = len(_events(project, "task.created", "task.claimed"))
    subagent = agent_actor(DRAFTER.session, "model-sub", "drafter-subagent", "rf-critic@1a2b3c4d")
    for actor, reason in (
        (DRAFTER, "drafter-session"),
        (subagent, "drafter-session"),  # a subagent shares its parent's session
        (LEAD_AUTHOR, "lead-author-session"),
    ):
        with pytest.raises(FactoryValidationError) as err:
            review_next(project, actor)
        assert [(i.field, i.reason) for i in err.value.issues] == [("actor", reason)]
    assert len(_events(project, "task.created", "task.claimed")) == before  # nothing was served
    assert review_next(project, CRITIC) is not None


def test_same_model_refused_when_the_plan_asks_for_a_distinct_critic(
    project: Project, human: Actor, hw: HW
) -> None:
    current = current_protocol(project)
    assert current is not None
    plan = HypothesisPlan(critic_distinct_model=True)
    amend_protocol(
        project,
        human,
        current.spec.model_copy(update={"hypothesis_plan": plan}),
        reason="systematic critic",
        semantic=True,
        effects={},
    )
    sibling = agent_actor(OTHER.session, "model-drafter", "critic-b", "rf-critic@1a2b3c4d")
    with pytest.raises(FactoryValidationError) as err:
        review_next(project, sibling)
    assert [(i.field, i.reason) for i in err.value.issues] == [("actor", "same-model")]
    assert review_next(project, CRITIC) is not None


def test_nothing_waiting_and_no_second_serving(project: Project, hw: HW) -> None:
    first = review_next(project, CRITIC)
    assert first is not None
    assert review_next(project, CRITIC) is None  # its claim is live until the lease lapses
    assert review_next(project, OTHER) is None  # held by the critic: passed over
    record_review(project, CRITIC, first.task_id, verdict())
    assert review_next(project, OTHER) is None  # reviewed: nothing waits


def test_failing_item_forces_revise_or_reject(project: Project, hw: HW) -> None:
    served = review_next(project, CRITIC)
    assert served is not None
    with pytest.raises(FactoryValidationError) as err:
        record_review(project, CRITIC, served.task_id, verdict("register", measurable="fail"))
    assert [(i.field, i.reason) for i in err.value.issues] == [("recommend", "inconsistent")]
    assert _events(project, "hypothesis.reviewed") == []
    record_review(project, CRITIC, served.task_id, verdict("revise", measurable="fail"))
    with pytest.raises(ValidationError):
        ReviewInput.model_validate({"items": {"falsifiable": "pass"}, "recommend": "register"})
    with pytest.raises(ValidationError):
        ReviewInput.model_validate(
            {
                "items": dict.fromkeys(CHECKLIST, "pass"),
                "notes": {"falsifiable": "x" * 301},
                "recommend": "register",
            }
        )


def test_review_of_superseded_version_refused(project: Project, human: Actor, hw: HW) -> None:
    served = review_next(project, CRITIC)
    assert served is not None
    new, _ = draft_hypothesis(
        project,
        DRAFTER,
        make_spec(lead=hw.lead, prediction={"direction": "treatment-better", "margin": "2"}),
        supersedes=hw.hid,
    )
    with pytest.raises(FactoryValidationError) as err:
        record_review(project, CRITIC, served.task_id, verdict())
    assert [(i.field, i.reason) for i in err.value.issues] == [("h_version", "superseded")]
    nxt = review_next(project, CRITIC)  # the newer draft is served next
    assert nxt is not None and nxt.task.hypothesis_id == new


def test_review_needs_the_held_task(project: Project, hw: HW) -> None:
    served = review_next(project, CRITIC)
    assert served is not None
    with pytest.raises(FactoryValidationError) as err:
        record_review(project, OTHER, served.task_id, verdict())
    assert err.value.issues[0].field == "task_id"


def test_review_event_provenance(project: Project, hw: HW) -> None:
    served = review_next(project, CRITIC)
    assert served is not None
    event_id = record_review(project, CRITIC, served.task_id, verdict())
    [event] = _events(project, "hypothesis.reviewed")
    task = get_task(project, served.task_id)
    assert task is not None and task.status.value == "completed"
    assert event.id == event_id and event.input_blob == task.content_blob  # served content exactly
    assert event.actor.model == "model-critic" and event.actor.skill == "rf-critic@1a2b3c4d"
    assert event.payload["critic_session"] == CRITIC.session
    view = hypothesis_view(project, hw.hid)
    assert view is not None and view.state == "reviewed" and view.reviews == [event_id]


def test_a_review_by_the_drafter_written_by_hand_does_not_count(project: Project, hw: HW) -> None:
    forged = HypothesisReviewed(
        hypothesis_id=hw.hid,
        h_version=hw.version,
        items=dict.fromkeys(CHECKLIST, "pass"),
        recommend="register",
        critic_session=DRAFTER.session,
        critic_model=DRAFTER.model,
        task_id="tsk_01JZ9Q3K5M7N8P0R2S4T6V8W0X",
    )
    project.record(
        [
            project.events.make(
                "hypothesis.reviewed",
                forged,
                DRAFTER,
                input_blob=project.blobs.put_json({"forged": True}),
            )
        ]
    )
    view = hypothesis_view(project, hw.hid)
    assert view is not None and view.state == "draft" and view.reviews == []
