"""screen_record: boundary validation, supersession, task completion and staleness (R-16, R-30)."""

import math
from collections.abc import Mapping
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.model.protocol import CriterionEffect, protocol_version
from factory.model.screening import Framing, PassLabel, ScreeningItem, ScreeningPhase, Verdict
from factory.model.task import Task, TaskStatus
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import (
    INSTRUCTIONS,
    SCREEN_BATCH,
    ScreenBatch,
    ScreenBatchContent,
    join_pass,
    live_decisions,
    screen_next,
    screen_record,
    stale_screening_decisions,
)
from factory.services.search import list_works
from factory.services.tasks import TaskSpec, claim_next, create_tasks, get_task, task_content
from tests.test_screening_next import (
    SourcesFor,
    _draw,
    _events,
    _of_type,
    _pass_calibration_under,
    _queued,
    _serve_calibration,
    _setup,
)


def _batch(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> ScreenBatch:
    """An ordinary pass A batch held by the agent, served once the calibration gate has passed."""
    protocol_id = _setup(project, agent, human, mock_sources)
    items = _draw(project)
    _serve_calibration(project, agent, math.ceil(len(items) / SCREEN_BATCH))
    _pass_calibration_under(project, agent, human, protocol_id)
    batch = screen_next(project, agent, PassLabel.A).batch
    assert batch is not None
    assert batch.phase is ScreeningPhase.SCREENING
    assert len(batch.records) >= 3
    return batch


def _item(
    record: Mapping[str, Any],
    verdict: Verdict = Verdict.INCLUDE,
    criterion: str | None = None,
    quote: str | None = None,
) -> ScreeningItem:
    return ScreeningItem(
        work_id=str(record["work_id"]),
        verdict=verdict,
        criterion=criterion,
        quote=str(record["title"]) if quote is None else quote,
        rationale="it fits",
    )


def _decisions_of(project: Project, task_id: str) -> list[Event]:
    """The decision events a task's records produced, in recording order."""
    return [
        e
        for e in _of_type(project, "screening.decision_recorded")
        if e.payload["task_id"] == task_id
    ]


def _live_of(project: Project, task_id: str) -> list[Any]:
    return [d for d in live_decisions(project, PassLabel.A) if d.task_id == task_id]


def _status(project: Project, task_id: str) -> TaskStatus | None:
    task: Task | None = get_task(project, task_id)
    return None if task is None else task.status


def _loosen(project: Project, agent: Actor, cid: str) -> str:
    """Amend the current protocol so that criterion `cid` is loosened; returns the new version."""
    current = current_protocol(project)
    assert current is not None
    criteria = tuple(
        c.model_copy(update={"rule": f"exclude only severe topic {cid}"}) if c.id == cid else c
        for c in current.spec.criteria
    )
    loosened = current.spec.model_copy(update={"criteria": criteria})
    amend_protocol(
        project,
        agent,
        loosened,
        reason=f"loosen {cid}",
        semantic=True,
        effects={cid: CriterionEffect.LOOSENED},
    )
    return protocol_version(loosened)


def _narrow_task(project: Project, agent: Actor) -> str:
    """A pass A task, claimed by the agent, whose batch lists only IN01 and has no abstract."""
    protocol = current_protocol(project)
    assert protocol is not None
    work = list_works(project)[0]
    content = ScreenBatchContent(
        pass_label=PassLabel.A,
        framing=Framing.INCLUSION,
        instructions=INSTRUCTIONS[Framing.INCLUSION],
        protocol_id=protocol.protocol_id,
        criteria=[
            {"id": "IN01", "statement": "vision", "rule": "include vision", "kind": "inclusion"}
        ],
        worked_examples=[],
        records=[{"work_id": work.id, "title": work.title, "abstract": None}],
        phase=ScreeningPhase.SCREENING,
    )
    content_json = content.model_dump(mode="json")
    [task_id] = create_tasks(
        project, agent, [TaskSpec(kind="screen_a", content=content_json)]
    ).written
    claimed = claim_next(project, agent, "screen_a", accept=lambda c: c == content_json)
    assert claimed is not None and claimed.task_id == task_id
    return task_id


# --- Boundary validation: a refusal or a rejected item writes nothing ---


def test_unknown_criterion_rejected_nothing_written(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    events_before = len(_events(project))

    result = screen_record(
        project, agent, batch.task_id, [_item(batch.records[0], Verdict.EXCLUDE, "EX09")]
    )

    assert result.written == []
    assert [e.index for e in result.rejected] == [0]
    assert result.rejected[0].issues[0].field == "items.0.criterion"
    assert len(_events(project)) == events_before


def test_exclusion_without_criterion_or_rationale_rejected(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    records = batch.records[:3]
    items = [
        ScreeningItem.model_construct(
            work_id=str(records[0]["work_id"]),
            verdict=Verdict.EXCLUDE,
            criterion=None,
            quote=str(records[0]["title"]),
            rationale="r",
        ),
        ScreeningItem.model_construct(
            work_id=str(records[1]["work_id"]),
            verdict=Verdict.EXCLUDE,
            criterion="IN01",
            quote=str(records[1]["title"]),
            rationale="r",
        ),
        ScreeningItem.model_construct(
            work_id=str(records[2]["work_id"]),
            verdict=Verdict.EXCLUDE,
            criterion="EX01",
            quote=str(records[2]["title"]),
            rationale=" ",
        ),
    ]

    result = screen_record(project, agent, batch.task_id, items)

    assert result.written == []
    assert [e.index for e in result.rejected] == [0, 1, 2]
    assert result.rejected[0].issues[0].field == "items.0"
    assert result.rejected[1].issues[0].field == "items.1"
    assert result.rejected[2].issues[0].field == "items.2"
    assert _decisions_of(project, batch.task_id) == []


def test_batch_records_valid_items_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    first, second, third = batch.records[:3]

    result = screen_record(
        project,
        agent,
        batch.task_id,
        [_item(first), _item(second), _item(third, quote="not in the record at all")],
    )

    assert len(result.written) == 2
    assert [e.index for e in result.rejected] == [2]
    assert result.rejected[0].issues[0].field == "items.2.quote"
    assert len(_decisions_of(project, batch.task_id)) == 2
    assert _status(project, batch.task_id) is TaskStatus.CLAIMED


def test_quote_not_in_record_rejected(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)

    result = screen_record(
        project,
        agent,
        batch.task_id,
        [_item(batch.records[0], quote="a phrase the record never says")],
    )

    assert result.written == []
    assert result.rejected[0].issues[0].field == "items.0.quote"
    assert _decisions_of(project, batch.task_id) == []


def test_missing_abstract_allows_title_quote_and_cannot_assess(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    record = batch.records[0]
    assert record["abstract"] is None

    result = screen_record(
        project, agent, batch.task_id, [_item(record, Verdict.CANNOT_ASSESS, "IN01")]
    )

    assert len(result.written) == 1
    assert result.rejected == []
    [decision] = _live_of(project, batch.task_id)
    assert decision.verdict is Verdict.CANNOT_ASSESS
    assert decision.verdict.promotes


def test_criterion_not_applicable_at_title_abstract_rejected(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources)
    join_pass(project, agent, PassLabel.A)
    task_id = _narrow_task(project, agent)
    record = {"work_id": list_works(project)[0].id, "title": list_works(project)[0].title}

    rejected = screen_record(project, agent, task_id, [_item(record, Verdict.EXCLUDE, "EX01")])

    assert rejected.written == []
    assert rejected.rejected[0].issues[0].field == "items.0.criterion"
    assert _status(project, task_id) is TaskStatus.CLAIMED

    accepted = screen_record(project, agent, task_id, [_item(record, criterion="IN01")])

    assert len(accepted.written) == 1
    assert _status(project, task_id) is TaskStatus.COMPLETED


# --- Refusals of the whole call ---


def test_record_refused_for_task_of_other_pass_or_session(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _batch(project, agent, human, mock_sources)
    agent_other = agent_other.model_copy(update={"model": "claude-sonnet-5-0"})

    # agent_other claims a pass B batch. This session may not record on it: not its claim.
    other_b = screen_next(project, agent_other, PassLabel.B).batch
    assert other_b is not None
    events_before = len(_events(project))
    with pytest.raises(FactoryValidationError):
        screen_record(project, agent, other_b.task_id, [_item(other_b.records[0])])
    assert len(_events(project)) == events_before

    # This session holds a pass B task, but it joined pass A: refused.
    held = claim_next(project, agent, "screen_b")
    assert held is not None and held.task_id != other_b.task_id
    held_content = ScreenBatchContent.model_validate(task_content(project, held))
    events_before = len(_events(project))
    with pytest.raises(FactoryValidationError):
        screen_record(project, agent, held.task_id, [_item(held_content.records[0])])
    assert len(_events(project)) == events_before


# --- Supersession, completion and provenance ---


def test_rerecord_supersedes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    record = batch.records[0]
    first = screen_record(project, agent, batch.task_id, [_item(record)])
    second = screen_record(project, agent, batch.task_id, [_item(record, Verdict.EXCLUDE, "EX01")])

    assert len(first.written) == len(second.written) == 1
    decisions = _decisions_of(project, batch.task_id)
    assert [d.payload["decision_id"] for d in decisions] == [*first.written, *second.written]
    assert decisions[1].payload["supersedes"] == first.written[0]
    [live] = _live_of(project, batch.task_id)
    assert live.decision_id == second.written[0]
    assert live.verdict is Verdict.EXCLUDE


def test_task_completes_when_all_records_decided(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    *head, last = batch.records
    first = screen_record(project, agent, batch.task_id, [_item(r) for r in head])
    assert _status(project, batch.task_id) is TaskStatus.CLAIMED

    second = screen_record(project, agent, batch.task_id, [_item(last)])

    assert _status(project, batch.task_id) is TaskStatus.COMPLETED
    [done] = [
        e for e in _of_type(project, "task.completed") if e.payload["task_id"] == batch.task_id
    ]
    assert done.payload["result_refs"] == [*first.written, *second.written]


def test_agent_decision_carries_model_skill_input_blob(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    item = _item(batch.records[0])

    result = screen_record(project, agent, batch.task_id, [item])

    [event] = _decisions_of(project, batch.task_id)
    assert event.actor.kind == "agent"
    assert event.actor.model == agent.model
    assert event.actor.skill is not None
    assert event.input_blob is not None
    assert project.blobs.get_json(event.input_blob) == {
        "task_id": batch.task_id,
        "items": [item.model_dump(mode="json")],
    }
    assert event.refs == (result.written[0],)


# --- Staleness after an amendment ---


def test_amendment_requeues_stale_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    record = batch.records[0]
    recorded = screen_record(
        project, agent, batch.task_id, [_item(record, Verdict.EXCLUDE, "EX03")]
    )
    [decision_id] = recorded.written
    assert stale_screening_decisions(project) == set()

    new_id = _loosen(project, agent, "EX03")
    _pass_calibration_under(project, agent, human, new_id)

    assert stale_screening_decisions(project) == {decision_id}
    with pytest.raises(FactoryValidationError):
        screen_record(project, agent, batch.task_id, [_item(record)])

    served: set[str] = set()
    for _ in range(20):
        next_batch = screen_next(project, agent, PassLabel.A).batch
        if next_batch is None:
            break
        assert next_batch.protocol_id == new_id
        served |= {str(r["work_id"]) for r in next_batch.records}
    assert str(record["work_id"]) in served
    assert str(record["work_id"]) in _queued(project, new_id)


def test_record_checks_actor_items_and_task_kind(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    batch = _batch(project, agent, human, mock_sources)
    first = batch.records[0]
    events_before = len(_events(project))

    with pytest.raises(FactoryValidationError):
        screen_record(project, human, batch.task_id, [_item(first)])
    assert len(_events(project)) == events_before

    result = screen_record(
        project,
        agent,
        batch.task_id,
        [
            _item(first),
            _item(first, Verdict.EXCLUDE, "EX01"),
            _item({"work_id": "rf:absent", "title": str(first["title"])}),
        ],
    )
    assert len(result.written) == 1
    assert [e.index for e in result.rejected] == [1, 2]
    assert result.rejected[0].issues[0].field == "items.1.work_id"
    assert result.rejected[1].issues[0].field == "items.2.work_id"

    create_tasks(project, agent, [TaskSpec(kind="survey", content={"x": 1})])
    survey = claim_next(project, agent, "survey")
    assert survey is not None
    with pytest.raises(FactoryValidationError):
        screen_record(project, agent, survey.task_id, [_item(first)])
