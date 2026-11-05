"""intuition_next and recording of interpretations (slice 3c, plan G3-A, task 4)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.intuition import InterpretationInput
from factory.services.context import Project
from factory.services.ideas import merge_ideas, propose_idea
from factory.services.interpretations import (
    INTUITION_KIND,
    intuition_next,
    record_interpretation,
    target_issue,
)
from factory.services.tasks import get_task
from tests.helpers import S3
from tests.intuition_helpers import (
    IWorld,
    cite_src,
    ctr_a,
    ctr_b,
    iw,
    lin,
    rows,
    screened,
    world,
    writer_actor,
)


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _layer_events(project: Project) -> int:
    return len([e for e in _events(project) if e.type.startswith("interpretation.")])


def _refuse(
    project: Project, call: Callable[[], object], *expected: tuple[str, str]
) -> list[tuple[str, str]]:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        call()
    got = [(i.field, i.reason) for i in e.value.issues]
    assert len(_events(project)) == before
    for item in expected:
        assert item in got, (item, got)
    return got


def _served(project: Project, iw: IWorld) -> str:
    batch = intuition_next(project, iw.writer).batch
    assert batch is not None
    return batch.task_id


def test_next_serves_confirmed_ideas_with_member_items(project: Project, iw: IWorld) -> None:
    served = intuition_next(project, iw.writer)
    b = served.batch
    assert b is not None and b.target == min(iw.idea1, iw.idea2) and b.target_kind == "idea"
    assert b.max_chars == 600 and b.max_sources == 5 and "not evidence" in b.instructions
    assert served.remaining == 1 and served.skipped == []
    assert {i.item_kind for i in b.items} <= {"base-idea", "addition", "result", "limitation"}
    assert b.items and all(i.work_id in b.members and i.quote for i in b.items)
    task = get_task(project, b.task_id)
    assert task is not None and task.kind == INTUITION_KIND and task.claim_session == S3
    assert task.refs == (b.target,)
    assert project.blobs.get_json(task.content_blob)["items"][0]["quote"] == b.items[0].quote  # type: ignore[index,call-overload]


def test_next_serves_again_a_held_task_then_the_next_target(project: Project, iw: IWorld) -> None:
    first = intuition_next(project, iw.writer).batch
    again = intuition_next(project, iw.writer).batch
    assert first is not None and again is not None and again.task_id == first.task_id
    other = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2B", "intuiter-b")
    second = intuition_next(project, other)
    assert second.batch is not None and second.batch.target != first.target
    assert second.remaining == 0
    assert intuition_next(project, writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2C", "c")).batch is None


def test_next_skips_targets_with_live_interpretation(project: Project, iw: IWorld) -> None:
    task_id = _served(project, iw)
    target = get_task(project, task_id).refs[0]  # type: ignore[union-attr]
    record_interpretation(project, iw.writer, iw.entry(target), task_id=task_id)
    nxt = intuition_next(project, iw.writer).batch
    assert nxt is not None and nxt.target != target
    named = intuition_next(project, iw.writer, targets=[target])
    assert named.batch is None
    assert [(s.target, s.reason) for s in named.skipped] == [(target, "has-live-interpretation")]


def test_named_targets_and_their_refusals(project: Project, iw: IWorld) -> None:
    """Review Focus 3."""
    merged = propose_idea(
        project, iw.writer.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W2D"}),
        "linear attention", iw.source, iw.lin.base, [iw.source],
    )  # fmt: skip
    from factory.model.lineage import LineageDecision
    from factory.services.ideas import decide_idea

    decide_idea(project, iw.human, merged, LineageDecision.CONFIRM, "checked")
    merge_ideas(project, iw.human, merged, iw.idea1, "same idea")
    n = intuition_next(
        project,
        iw.writer,
        targets=[iw.third, merged, iw.lin.target5, "ida_01HZX3K4M5N6P7Q8R9S0TVWXYZ", iw.third],
    )
    assert n.batch is not None and n.batch.target == iw.third and n.batch.target_kind == "paper"
    assert n.batch.members == [iw.third]
    assert {(s.target, s.reason) for s in n.skipped} == {
        (merged, "merged"),
        (iw.lin.target5, "external"),
        ("ida_01HZX3K4M5N6P7Q8R9S0TVWXYZ", "unknown"),
    }


def test_task_open_is_reported_for_a_named_target_held_by_another(
    project: Project, iw: IWorld
) -> None:
    b = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert b is not None
    other = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2B", "intuiter-b")
    n = intuition_next(project, other, targets=[iw.idea1])
    assert n.batch is None and [(s.target, s.reason) for s in n.skipped] == [
        (iw.idea1, "task-open")
    ]


def test_only_an_agent_is_served(project: Project, iw: IWorld) -> None:
    _refuse(
        project,
        lambda: intuition_next(project, iw.human),
        ("actor", "only an agent is served a task"),
    )


def test_target_issue_reasons(project: Project, iw: IWorld) -> None:
    ghost = "ida_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
    proposed = propose_idea(
        project, iw.writer, "linear attention", iw.source, iw.lin.base, [iw.source]
    )
    reasons = {
        t: (None if (i := target_issue(project, t)) is None else i.reason)
        for t in (
            iw.idea1,
            iw.third,
            proposed,
            ghost,
            iw.lin.target5,
            "int_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
        )
    }
    assert reasons == {
        iw.idea1: None,
        iw.third: None,
        proposed: "idea-not-confirmed",
        ghost: "node-unknown",
        iw.lin.target5: "node-external",
        "int_01HZX3K4M5N6P7Q8R9S0TVWXYZ": "not-an-evidence-node",
    }


def test_record_writes_one_event_with_provenance(project: Project, iw: IWorld) -> None:
    """Acceptance 1."""
    b = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert b is not None
    entry = iw.entry(iw.idea1)
    iid = record_interpretation(project, iw.writer, entry, task_id=b.task_id)
    [ev] = [e for e in _events(project) if e.type == "interpretation.recorded"]
    assert ev.payload["interpretation_id"] == iid and ev.payload["author"] == "agent"
    assert ev.actor.model and ev.actor.skill and ev.actor.skill.startswith("rf-intuition@")
    task = get_task(project, b.task_id)
    assert task is not None and task.status.value == "completed"
    assert ev.input_blob is not None
    blob = project.blobs.get_json(ev.input_blob)
    assert blob == {"task_input": task.content_blob, "call": entry.model_dump(mode="json")}  # type: ignore[comparison-overlap]
    [(state,)] = rows(
        project, f"SELECT review_state FROM interpretations WHERE interpretation_id = '{iid}'"
    )
    assert state == "unreviewed"
    assert ev.payload["sources"][0]["document_id"] == iw.doc  # type: ignore[index,call-overload]


def test_refusals_write_nothing(project: Project, iw: IWorld) -> None:
    """Acceptance 2: nothing is written and no document text is in the error."""
    t = _served(project, iw)
    target = get_task(project, t).refs[0]  # type: ignore[union-attr]
    bad_quote = iw.quote(quote="very long sequences improve")
    for bad in (
        iw.entry(target, sources=[]),
        iw.entry(target, text="a" * 601),
        iw.entry("ida_01HZX3K4M5N6P7Q8R9S0TVWXYZ"),
        iw.entry(target, sources=[bad_quote]),
        iw.entry(target, sources=[cite_src(reference="rex_01HZX3K4M5N6P7Q8R9S0TVWXYZ:9")]),
    ):
        with pytest.raises(FactoryValidationError) as e:
            record_interpretation(project, iw.writer, bad, task_id=t)
        assert "degrade" not in str(e.value) and "improve" not in str(e.value)
    assert _layer_events(project) == 0
    task = get_task(project, t)
    assert task is not None and task.status.value == "claimed"


def test_all_issues_reported_together(project: Project, iw: IWorld) -> None:
    t = _served(project, iw)
    target = get_task(project, t).refs[0]  # type: ignore[union-attr]
    got = _refuse(
        project,
        lambda: record_interpretation(
            project,
            iw.writer,
            iw.entry(target, text="a" * 601, sources=[iw.quote(), iw.quote(quote="not there")]),
            task_id=t,
        ),
        ("text", "at most 600 characters"),
        ("sources[1].quote", "quote-not-in-anchor"),
    )
    assert len(got) == 2


def test_agent_needs_held_task_matching_target(project: Project, iw: IWorld) -> None:
    t = _served(project, iw)
    target = get_task(project, t).refs[0]  # type: ignore[union-attr]
    other_target = iw.idea2 if target == iw.idea1 else iw.idea1
    _refuse(
        project,
        lambda: record_interpretation(project, iw.writer, iw.entry(target)),
        ("task_id", "an agent records against a task it holds"),
    )
    _refuse(
        project,
        lambda: record_interpretation(project, iw.writer, iw.entry(other_target), task_id=t),
        ("task_id", "the task is for another target"),
    )
    stranger = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2B", "intuiter-b")
    _refuse(
        project,
        lambda: record_interpretation(project, stranger, iw.entry(target), task_id=t),
        ("task_id", "not actively claimed by this session"),
    )
    _refuse(
        project,
        lambda: record_interpretation(
            project, iw.writer, iw.entry(target), task_id="tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
        ),
        ("task_id", "unknown task"),
    )


def test_human_writes_without_task_author_human(project: Project, iw: IWorld) -> None:
    iid = record_interpretation(project, iw.human, iw.entry(iw.third))
    [ev] = [e for e in _events(project) if e.type == "interpretation.recorded"]
    assert ev.actor.model is None and ev.actor.kind == "human" and ev.payload["author"] == "human"
    assert ev.payload["interpretation_id"] == iid and ev.payload["task_id"] is None
    assert ev.input_blob is not None
    assert project.blobs.get_json(ev.input_blob) == {
        "call": iw.entry(iw.third).model_dump(mode="json")
    }  # type: ignore[comparison-overlap]
    _refuse(
        project,
        lambda: record_interpretation(
            project, iw.human, iw.entry(iw.third), task_id="tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
        ),
        ("task_id", "a human records without a task"),
    )


def test_system_actor_refused(project: Project, iw: IWorld) -> None:
    _refuse(
        project,
        lambda: record_interpretation(project, project.system_actor(), iw.entry()),
        ("actor", "only an agent or a human records an interpretation"),
    )


def test_agent_supersedes_own_unreviewed_only(project: Project, iw: IWorld) -> None:
    """Ruling A6."""
    human_int = record_interpretation(project, iw.human, iw.entry(iw.idea1))
    t1 = intuition_next(project, iw.writer, targets=[iw.idea2]).batch
    assert t1 is not None
    first = record_interpretation(project, iw.writer, iw.entry(iw.idea2), task_id=t1.task_id)
    # a second writer session may supersede the first agent-written, unreviewed one
    again = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2B", "intuiter-b")
    # (the target has a live interpretation, so a task is created directly for the supersession)
    from factory.services.tasks import TaskSpec, claim_next, create_tasks

    created = create_tasks(
        project, again, [TaskSpec(INTUITION_KIND, {"target": iw.idea2}, refs=(iw.idea2,))]
    )
    claimed = claim_next(project, again, INTUITION_KIND)
    assert claimed is not None and created.written == [claimed.task_id]
    _refuse(
        project,
        lambda: record_interpretation(
            project, again, iw.entry(iw.idea1, supersedes=human_int), task_id=claimed.task_id
        ),
        ("task_id", "the task is for another target"),
    )
    got = _refuse(
        project,
        lambda: record_interpretation(
            project, again, iw.entry(iw.idea2, supersedes=human_int), task_id=claimed.task_id
        ),
        ("supersedes", "target-differs"),
    )
    assert got
    new = record_interpretation(
        project, again, iw.entry(iw.idea2, supersedes=first), task_id=claimed.task_id
    )
    assert rows(
        project,
        "SELECT review_state, superseded_by FROM interpretations "
        f"WHERE interpretation_id = '{first}'",
    ) == [("superseded", new)]
    assert rows(
        project, f"SELECT review_state FROM interpretations WHERE interpretation_id = '{new}'"
    ) == [("unreviewed",)]


def test_agent_cannot_supersede_reviewed_or_human_written(project: Project, iw: IWorld) -> None:
    from factory.services.tasks import TaskSpec, claim_next, create_tasks
    from tests.intuition_helpers import record_event, reviewed

    human_int = record_interpretation(project, iw.human, iw.entry(iw.idea1))
    b = intuition_next(project, iw.writer, targets=[iw.idea2]).batch
    assert b is not None
    agent_int = record_interpretation(project, iw.writer, iw.entry(iw.idea2), task_id=b.task_id)
    record_event(project, "interpretation.reviewed", reviewed(agent_int, "reviewed"))
    other = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W2B", "intuiter-b")
    for target, prior in ((iw.idea1, human_int), (iw.idea2, agent_int)):
        create_tasks(project, other, [TaskSpec(INTUITION_KIND, {"target": target}, refs=(target,))])
        task = claim_next(
            project, other, INTUITION_KIND, accept=lambda c, t=target: c["target"] == t
        )  # type: ignore[index,misc]
        assert task is not None
        entry = iw.entry(target, supersedes=prior)
        _refuse(
            project,
            lambda e=entry, k=task.task_id: record_interpretation(project, other, e, task_id=k),
            ("supersedes", "human-act"),
        )


def test_supersedes_must_exist_be_live_and_not_the_writers_own_session(
    project: Project, iw: IWorld
) -> None:
    b = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert b is not None
    ghost = "int_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
    _refuse(
        project,
        lambda: record_interpretation(
            project, iw.writer, iw.entry(iw.idea1, supersedes=ghost), task_id=b.task_id
        ),
        ("supersedes", "interpretation-unknown"),
    )
    first = record_interpretation(project, iw.human, iw.entry(iw.idea1))
    second = record_interpretation(project, iw.human, iw.entry(iw.idea1, supersedes=first))
    assert second
    _refuse(
        project,
        lambda: record_interpretation(project, iw.human, iw.entry(iw.idea1, supersedes=first)),
        ("supersedes", "interpretation-superseded"),
    )
