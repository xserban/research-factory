# ruff: noqa: F401, F811
"""Review lifecycle, human supersession, listing and history (slice 3c, plan G3-A, task 5)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.intuition import ReviewState
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.interpretations import (
    InterpretationView,
    interpretation_history,
    intuition_next,
    list_interpretations,
    record_interpretation,
    review_counts,
    review_interpretation,
    supersede_interpretation,
)
from tests.contribution_helpers import with_references
from tests.helpers import S3
from tests.intuition_helpers import (
    IWorld,
    ctr_a,
    ctr_b,
    iw,
    lin,
    reviewer,
    rows,
    screened,
    world,
    writer_actor,
)


def _agent_int(project: Project, iw: IWorld, target: str | None = None) -> str:
    target = target or iw.idea1
    batch = intuition_next(project, iw.writer, targets=[target]).batch
    assert batch is not None
    return record_interpretation(project, iw.writer, iw.entry(target), task_id=batch.task_id)


def _view(project: Project, iid: str, *states: ReviewState) -> InterpretationView:
    listed = list_interpretations(project, states=states or list(ReviewState))
    [found] = [v for v in listed.items if v.interpretation_id == iid]
    return found


def _refuse(call: Callable[[], object], field: str, reason: str | None = None) -> None:
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert e.value.issues[0].field == field, e.value.issues
    if reason is not None:
        assert e.value.issues[0].reason == reason


def _events(project: Project) -> int:
    return len(rows(project, "SELECT 1 FROM events WHERE type LIKE 'interpretation.%'"))


def test_agent_cannot_review(project: Project, iw: IWorld) -> None:
    """Acceptance 4."""
    iid = _agent_int(project, iw)
    before = _events(project)
    _refuse(
        lambda: review_interpretation(project, iw.writer, iid, "reviewed", "", Channel.MCP),
        "actor",
    )
    assert _events(project) == before


def test_writer_session_cannot_review_even_as_the_relayed_human(
    project: Project, iw: IWorld
) -> None:
    iid = _agent_int(project, iw)
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    before = _events(project)
    _refuse(
        lambda: review_interpretation(project, relay, iid, "reviewed", "", Channel.MCP), "actor"
    )
    assert _events(project) == before


def test_mcp_channel_is_refused_at_the_service(project: Project, iw: IWorld) -> None:
    """No MCP tool reviews (spec): a relay is refused and leaves no screening-table row."""
    iid = _agent_int(project, iw)
    relay = iw.human.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W3A"})
    before = _events(project)
    _refuse(
        lambda: review_interpretation(project, relay, iid, "reviewed", "", Channel.MCP),
        "channel",
    )
    assert _events(project) == before
    assert (
        rows(project, f"SELECT session FROM label_sessions WHERE session = '{relay.session}'") == []
    )
    review_interpretation(project, relay, iid, "reviewed", "", Channel.CLI)


def test_history_lists_a_review_the_fold_dropped(project: Project, iw: IWorld) -> None:
    """Acceptance 3: the history lists all events, including a dropped one (folded = false)."""
    from tests.intuition_helpers import record_event, reviewed

    iid = _agent_int(project, iw)
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    record_event(
        project, "interpretation.reviewed", reviewed(iid, "reviewed", channel="mcp"), relay
    )
    history = interpretation_history(project, iid)
    assert [(h.kind, h.folded) for h in history] == [("recorded", True), ("reviewed", False)]
    assert _view(project, iid).review_state == "unreviewed"


def test_wrong_needs_note_and_is_hidden_but_traceable(project: Project, iw: IWorld) -> None:
    """Acceptance 5."""
    iid = _agent_int(project, iw)
    _refuse(
        lambda: review_interpretation(project, iw.human, iid, "wrong", "  ", Channel.CLI), "note"
    )
    review_interpretation(
        project, iw.human, iid, "wrong", "conflates kernel and feature map", Channel.CLI
    )
    listed = list_interpretations(project)
    assert iid not in [v.interpretation_id for v in listed.items]
    assert listed.hidden.wrong == 1 and listed.hidden.superseded == 0
    assert [h.kind for h in interpretation_history(project, iid)] == ["recorded", "reviewed"]
    assert _view(project, iid, ReviewState.WRONG).review_state == "wrong"


def test_repeated_review_supersedes_previous(project: Project, iw: IWorld) -> None:
    """Acceptance 3: reviewed then wrong then reviewed; the live state is the fold, history all."""
    iid = _agent_int(project, iw)
    review_interpretation(project, iw.human, iid, "reviewed", "ok", Channel.CLI)
    review_interpretation(project, iw.human, iid, "wrong", "no", Channel.CLI)
    assert _view(project, iid, ReviewState.WRONG).review_state == "wrong"
    review_interpretation(project, iw.human, iid, "reviewed", "on reflection", Channel.CLI)
    assert _view(project, iid).review_state == "reviewed"
    history = interpretation_history(project, iid)
    assert [(h.kind, h.state) for h in history] == [
        ("recorded", None),
        ("reviewed", "reviewed"),
        ("reviewed", "wrong"),
        ("reviewed", "reviewed"),
    ]
    assert history[2].note == "no" and history[0].actor == iw.writer.id


def test_unknown_and_superseded_cannot_be_reviewed(project: Project, iw: IWorld) -> None:
    _refuse(
        lambda: review_interpretation(
            project, iw.human, "int_01HZX3K4M5N6P7Q8R9S0TVWXYZ", "reviewed", "", Channel.CLI
        ),
        "interpretation_id",
        "unknown-interpretation",
    )
    first = _agent_int(project, iw)
    supersede_interpretation(project, iw.human, first, "A replacement.", [iw.quote()])
    before = _events(project)
    _refuse(
        lambda: review_interpretation(project, iw.human, first, "reviewed", "", Channel.CLI),
        "interpretation_id",
        "superseded",
    )
    assert _events(project) == before


def test_human_supersede_writes_human_replacement(project: Project, iw: IWorld) -> None:
    first = _agent_int(project, iw)
    review_interpretation(project, iw.human, first, "reviewed", "", Channel.CLI)
    new = supersede_interpretation(project, iw.human, first, "A replacement.", [iw.quote()])
    assert _view(project, first, ReviewState.SUPERSEDED).review_state == "superseded"
    created = _view(project, new)
    assert created.author == "human" and created.target == iw.idea1 and created.writer == "obd"
    assert [h.kind for h in interpretation_history(project, first)] == [
        "recorded",
        "reviewed",
        "superseded-by",
    ]
    assert list_interpretations(project).hidden.superseded == 1


def test_supersede_is_a_human_act_and_needs_a_known_live_id(project: Project, iw: IWorld) -> None:
    first = _agent_int(project, iw)
    _refuse(lambda: supersede_interpretation(project, iw.writer, first, "x", [iw.quote()]), "actor")
    _refuse(
        lambda: supersede_interpretation(
            project, iw.human, "int_01HZX3K4M5N6P7Q8R9S0TVWXYZ", "x", [iw.quote()]
        ),
        "interpretation_id",
        "unknown-interpretation",
    )
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    _refuse(
        lambda: supersede_interpretation(project, relay, first, "x", [iw.quote()]),
        "supersedes",
        "writer-session",
    )


def test_self_review_one_human_flagged_two_humans_refused(project: Project, iw: IWorld) -> None:
    """Review Focus 5, ruling A7."""
    mine = record_interpretation(project, iw.human, iw.entry(iw.idea1))
    review_interpretation(project, iw.human, mine, "reviewed", "", Channel.CLI)
    assert _view(project, mine).self_reviewed is True
    assert _agent_review_flag(project, iw) is False
    # a second human acts in the project
    alice = reviewer(project, "alice")
    theirs = record_interpretation(project, alice, iw.entry(iw.idea2))
    _refuse(
        lambda: review_interpretation(project, alice, theirs, "reviewed", "", Channel.CLI),
        "reviewer",
    )
    _refuse(
        lambda: review_interpretation(project, iw.human, mine, "wrong", "x", Channel.CLI),
        "reviewer",
    )
    review_interpretation(project, iw.human, theirs, "reviewed", "", Channel.CLI)
    assert _view(project, theirs).self_reviewed is False


def _agent_review_flag(project: Project, iw: IWorld) -> bool:
    iid = _agent_int(project, iw, iw.idea2)
    review_interpretation(project, iw.human, iid, "reviewed", "", Channel.CLI)
    return _view(project, iid).self_reviewed


def test_unreviewed_items_carry_label_and_class(project: Project, iw: IWorld) -> None:
    iid = _agent_int(project, iw)
    v = _view(project, iid)
    assert v.label == "interpretation · unreviewed" and v.class_ == "interpretation"
    dumped = v.model_dump(mode="json", by_alias=True)
    assert dumped["class"] == "interpretation"
    assert v.writer == f"{iw.writer.id} ({iw.writer.model})" and v.input_blob is not None
    assert (
        v.sources[0].quote == "very long sequences degrade" and v.sources[0].document_id == iw.doc
    )


def test_source_stale_does_not_change_state(project: Project, iw: IWorld) -> None:
    """Acceptance 10."""
    iid = _agent_int(project, iw)
    review_interpretation(project, iw.human, iid, "reviewed", "", Channel.CLI)
    assert _view(project, iid).source_stale == []
    with_references(project, iw.writer, iw.source, version="v4")
    v = _view(project, iid)
    assert v.review_state == "reviewed" and v.source_stale == [iw.doc]


def test_list_paginates_and_hidden_counts_follow_target_filter(
    project: Project, iw: IWorld
) -> None:
    ids = [record_interpretation(project, iw.human, iw.entry(iw.idea1)) for _ in range(3)]
    other = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    review_interpretation(project, reviewer(project, "obd"), other, "wrong", "n", Channel.CLI)
    page1 = list_interpretations(project, target=iw.idea1, limit=2)
    assert [v.interpretation_id for v in page1.items] == sorted(ids)[:2]
    assert page1.next_cursor is not None
    page2 = list_interpretations(project, target=iw.idea1, cursor=page1.next_cursor, limit=2)
    assert [v.interpretation_id for v in page2.items] == sorted(ids)[
        2:
    ] and page2.next_cursor is None
    assert list_interpretations(project, target=iw.idea1).hidden.wrong == 0
    assert list_interpretations(project, target=iw.idea2).hidden.wrong == 1
    assert list_interpretations(project).hidden.wrong == 1


def test_review_counts_are_computed(project: Project, iw: IWorld) -> None:
    a = _agent_int(project, iw)
    b = record_interpretation(project, iw.human, iw.entry(iw.idea1))
    c = record_interpretation(project, iw.human, iw.entry(iw.idea2))
    alice = reviewer(project, "alice")
    review_interpretation(project, alice, a, "reviewed", "", Channel.CLI)
    review_interpretation(project, alice, b, "wrong", "n", Channel.CLI)
    supersede_interpretation(project, alice, c, "better", [iw.quote()])
    assert review_counts(project) == {
        ReviewState.UNREVIEWED: 1,
        ReviewState.REVIEWED: 1,
        ReviewState.WRONG: 1,
        ReviewState.SUPERSEDED: 1,
    }
