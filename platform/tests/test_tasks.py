from datetime import timedelta
from typing import cast

import pytest
from pydantic import JsonValue

from factory.clock import FixedClock
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.task import (
    TASK_LEASE,
    TaskClaimed,
    TaskCompleted,
    TaskCreated,
    TaskStatus,
)
from factory.services.context import Project
from factory.services.project import project_status
from factory.services.tasks import (
    TaskCounts,
    TaskSpec,
    claim_next,
    complete_task,
    create_tasks,
    get_task,
    release_task,
    task_content,
    task_counts,
)
from tests.helpers import S2, SESSION, T0

ONE_MS = timedelta(milliseconds=1)


def test_create_and_claim_returns_content(project: Project, agent: Actor) -> None:
    res = create_tasks(project, project.system_actor(), [TaskSpec("demo", {"q": 1}, ("rf:x",))])
    task = claim_next(project, agent, "demo")
    assert task is not None and task.task_id == res.written[0] and task.refs == ("rf:x",)
    assert task_content(project, task) == {"q": 1}
    assert task.lease_until == T0 + TASK_LEASE


def test_batch_partial_success(project: Project) -> None:
    res = create_tasks(
        project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("Bad Kind", 1)]
    )
    assert len(res.written) == 1
    assert res.rejected[0].index == 1
    assert res.rejected[0].issues[0].field == "kind"


def test_each_invalid_item_reports_its_field(project: Project) -> None:
    res = create_tasks(
        project,
        project.system_actor(),
        [
            TaskSpec("demo", cast(JsonValue, {1, 2})),
            TaskSpec("demo", 1, ("",)),
            TaskSpec("Bad", 1),
        ],
    )
    assert res.written == []
    assert [(e.index, e.issues[0].field) for e in res.rejected] == [
        (0, "content"),
        (1, "refs"),
        (2, "kind"),
    ]
    assert project_status(project).events_total == 1


def test_claim_next_filters_by_kind(project: Project, agent: Actor) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    assert claim_next(project, agent, "other") is None


def test_active_lease_blocks_other_sessions_until_expiry(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    assert claim_next(project, agent, "demo") is not None
    clock.advance(ONE_MS)
    assert claim_next(project_other_session, agent_other, "demo") is None
    clock.advance(TASK_LEASE + timedelta(seconds=1))
    assert task_counts(project).expired == 1
    assert claim_next(project_other_session, agent_other, "demo") is not None


def test_only_the_holder_can_complete(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    assert t is not None
    clock.advance(ONE_MS)
    with pytest.raises(FactoryValidationError) as err:
        complete_task(project_other_session, agent_other, t.task_id)
    assert err.value.issues[0].field == "task_id"
    clock.advance(ONE_MS)
    complete_task(project, agent, t.task_id, ["dec_x"])
    assert get_task(project, t.task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]


def test_complete_after_expiry_is_rejected(
    project: Project, agent: Actor, clock: FixedClock
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    assert t is not None
    clock.advance(TASK_LEASE)  # the lease ends exactly now: no longer held
    with pytest.raises(FactoryValidationError) as err:
        complete_task(project, agent, t.task_id)
    assert err.value.issues[0].field == "task_id"
    assert get_task(project, t.task_id).status == TaskStatus.CLAIMED  # type: ignore[union-attr]


def test_release_makes_task_claimable_again(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    assert t is not None
    release_task(project, agent, t.task_id, "needs more context")
    released = get_task(project, t.task_id)
    assert released is not None
    assert (released.status, released.claimed_by, released.claim_session, released.lease_until) == (
        TaskStatus.OPEN,
        None,
        None,
        None,
    )
    clock.advance(ONE_MS)
    again = claim_next(project_other_session, agent_other, "demo")
    assert again is not None
    assert (again.task_id, again.claim_session) == (t.task_id, S2)


def test_release_by_non_holder_is_rejected(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    assert t is not None
    clock.advance(ONE_MS)
    with pytest.raises(FactoryValidationError) as err:
        release_task(project_other_session, agent_other, t.task_id, "mine now")
    assert err.value.issues[0].field == "task_id"
    assert get_task(project, t.task_id).status == TaskStatus.CLAIMED  # type: ignore[union-attr]


def test_concurrent_claims_first_wins(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
) -> None:
    ids = create_tasks(
        project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("demo", 2)]
    ).written
    blob = get_task(project, ids[0]).content_blob  # type: ignore[union-attr]
    # Both sessions claim task 1 without syncing; the project's claim sorts first.
    project.writer.append(
        [
            project.events.make(
                "task.claimed",
                TaskClaimed(task_id=ids[0], lease_until=clock.now() + TASK_LEASE),
                agent,
                input_blob=blob,
            )
        ]
    )
    clock.advance(ONE_MS)
    project_other_session.writer.append(
        [
            project_other_session.events.make(
                "task.claimed",
                TaskClaimed(task_id=ids[0], lease_until=clock.now() + TASK_LEASE),
                agent_other,
                input_blob=blob,
            )
        ]
    )
    t = get_task(project, ids[0])
    assert t is not None and t.claim_session == SESSION
    assert claim_next(project_other_session, agent_other, "demo").task_id == ids[1]  # type: ignore[union-attr]


def test_projector_ignores_events_that_do_not_apply(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    assert t is not None
    other_blob = project.blobs.put_json(2)
    unknown = "tsk_" + "0" * 26
    project.writer.append(
        [
            # A second task.created for an existing id: the row must not change.
            project.events.make(
                "task.created",
                TaskCreated(task_id=t.task_id, kind="demo"),
                project.system_actor(),
                input_blob=other_blob,
            ),
            # A claim on a task that does not exist.
            project.events.make(
                "task.claimed",
                TaskClaimed(task_id=unknown, lease_until=clock.now() + TASK_LEASE),
                agent,
                input_blob=other_blob,
            ),
        ]
    )
    clock.advance(ONE_MS)
    # A completion by a session that does not hold the claim.
    project_other_session.writer.append(
        [
            project_other_session.events.make(
                "task.completed",
                TaskCompleted(task_id=t.task_id),
                agent_other,
                input_blob=t.content_blob,
            )
        ]
    )
    after = get_task(project, t.task_id)
    assert after is not None
    assert (after.status, after.claim_session, after.content_blob) == (
        TaskStatus.CLAIMED,
        SESSION,
        t.content_blob,
    )
    assert get_task(project, unknown) is None
    assert project.index.state_hash() == project.index.rebuild()


def test_task_flow_rebuild_equals_incremental(project: Project, agent: Actor) -> None:
    ids = create_tasks(
        project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("demo", 2)]
    ).written
    first = claim_next(project, agent, "demo")
    assert first is not None
    complete_task(project, agent, first.task_id)
    second = claim_next(project, agent, "demo")
    assert second is not None and second.task_id == ids[1]
    release_task(project, agent, second.task_id, "handing back")
    assert project.index.state_hash() == project.index.rebuild()
    assert task_counts(project) == TaskCounts(open=1, claimed=0, expired=0, completed=1)


def test_unknown_task_is_rejected(project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        complete_task(project, agent, "tsk_" + "0" * 26)
    assert err.value.issues[0].field == "task_id"


def test_claim_next_moves_past_a_task_lost_to_another_session(
    project: Project,
    project_other_session: Project,
    agent: Actor,
    agent_other: Actor,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = create_tasks(
        project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("demo", 2)]
    ).written
    first = get_task(project, ids[0])
    assert first is not None
    assert claim_next(project, agent, "demo") is not None  # this session takes ids[0]
    clock.advance(ONE_MS)
    # The other session's listing is stale: it still shows ids[0] as claimable.
    stale = [(ids[0], first.content_blob), (ids[1], first.content_blob)]
    monkeypatch.setattr("factory.services.tasks._claimable", lambda *_: stale)
    won = claim_next(project_other_session, agent_other, "demo")
    assert won is not None and won.task_id == ids[1] and won.claim_session == S2


def test_empty_result_ref_is_rejected_and_writes_nothing(project: Project, agent: Actor) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    assert t is not None
    with pytest.raises(FactoryValidationError) as err:
        complete_task(project, agent, t.task_id, [""])
    assert err.value.issues[0].field == "result_refs"
    assert get_task(project, t.task_id).status == TaskStatus.CLAIMED  # type: ignore[union-attr]
