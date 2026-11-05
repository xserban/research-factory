"""Review of concept definitions (slice 3c, plan G3-B, task 3; ruling B2)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.model.intuition import ConceptInput, ConceptState
from factory.model.screening import Channel
from factory.services.concepts import (
    concept_history,
    concept_review_counts,
    concept_view,
    decide_concept_source,
    define_concept,
    list_concepts,
    review_concept,
)
from factory.services.context import Project
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

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}


def concept(**kw: Any) -> ConceptInput:
    return ConceptInput.model_validate({"name": "random features", **kw})


def ids(listing: Any) -> list[str]:
    return [i.concept_id for i in listing.items]


def _refuse(call: Callable[[], object], field: str, reason: str | None = None) -> None:
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert e.value.issues[0].field == field, e.value.issues
    if reason is not None:
        assert e.value.issues[0].reason == reason


def _approved(project: Project, iw: IWorld, **kw: Any) -> str:
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK, **kw))
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    return cid


def _events(project: Project) -> int:
    return len(rows(project, "SELECT 1 FROM events WHERE type = 'concept.reviewed'"))


def test_agent_cannot_review_concept(project: Project, iw: IWorld) -> None:
    cid = _approved(project, iw)
    _refuse(lambda: review_concept(project, iw.writer, cid, "reviewed", "", Channel.MCP), "actor")
    assert _events(project) == 0


def test_writer_session_cannot_review_even_as_the_relayed_human(
    project: Project, iw: IWorld
) -> None:
    cid = _approved(project, iw)
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    _refuse(lambda: review_concept(project, relay, cid, "reviewed", "", Channel.MCP), "actor")
    assert _events(project) == 0


def test_approved_agent_concept_shown_unreviewed_until_reviewed(
    project: Project, iw: IWorld
) -> None:
    cid = _approved(project, iw)
    view = concept_view(project, cid)
    assert view is not None and view.label == "interpretation · unreviewed"
    assert cid in ids(list_concepts(project))
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    view = concept_view(project, cid)
    assert view is not None and view.review_state == "reviewed"
    assert view.label == "interpretation · reviewed" and view.visible


def test_wrong_hides_concept_and_needs_note(project: Project, iw: IWorld) -> None:
    cid = _approved(project, iw)
    _refuse(lambda: review_concept(project, iw.human, cid, "wrong", " ", Channel.CLI), "note")
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    review_concept(project, iw.human, cid, "wrong", "misstates the bound", Channel.CLI)
    assert cid not in ids(list_concepts(project))
    assert list_concepts(project).hidden.wrong == 1
    shown = list_concepts(project, include_hidden=True)
    assert ids(shown) == [cid] and shown.items[0].review_state == "wrong"
    kinds = [(h.kind, h.state) for h in concept_history(project, cid)]
    assert kinds == [
        ("recorded", None),
        ("source-decided", "approve"),
        ("reviewed", "reviewed"),
        ("reviewed", "wrong"),
    ]


def test_redefinition_resets_review(project: Project, iw: IWorld) -> None:
    cid = _approved(project, iw)
    first = rows(project, "SELECT definition_event FROM concepts")[0][0]
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    define_concept(
        project, iw.writer, concept(concept_id=cid, supersedes=first, source=TEXTBOOK, text="v2")
    )
    view = concept_view(project, cid)
    assert view is not None and view.review_state == "unreviewed" and view.visible
    # a review naming the superseded definition is refused
    _refuse(
        lambda: review_concept(
            project, iw.human, cid, "reviewed", "", Channel.CLI, definition=first
        ),
        "definition",
        "not-current-definition",
    )
    review_concept(
        project,
        iw.human,
        cid,
        "reviewed",
        "",
        Channel.CLI,
        definition=rows(project, "SELECT definition_event FROM concepts")[0][0],
    )
    view = concept_view(project, cid)
    assert view is not None and view.review_state == "reviewed"


def test_review_refusals(project: Project, iw: IWorld) -> None:
    _refuse(
        lambda: review_concept(
            project, iw.human, "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ", "reviewed", "", Channel.CLI
        ),
        "concept_id",
    )


def test_self_review_one_human_flagged_two_humans_refused(
    project: Project, iw: IWorld
) -> None:  # A7 applied to human-written definitions
    cid = define_concept(project, iw.human, concept(source=TEXTBOOK), approve_source=True)
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)
    view = concept_view(project, cid)
    assert view is not None and "self-reviewed" in view.flags
    # a second human acts in the project: the author may no longer review their own text
    other = reviewer(project, "second-human")
    cid2 = define_concept(project, other, concept(name="second", source=TEXTBOOK))
    _refuse(lambda: review_concept(project, other, cid2, "reviewed", "", Channel.CLI), "reviewer")
    review_concept(project, iw.human, cid2, "reviewed", "", Channel.CLI)
    view2 = concept_view(project, cid2)
    assert view2 is not None and "self-reviewed" not in view2.flags


def test_mcp_relay_refused_from_a_pass_session(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _approved(project, iw)
    monkeypatch.setattr("factory.services.concepts._joined_a_pass", lambda p, s: True)
    _refuse(lambda: review_concept(project, iw.human, cid, "reviewed", "", Channel.MCP), "channel")
    assert _events(project) == 0
    review_concept(project, iw.human, cid, "reviewed", "", Channel.CLI)  # the CLI is no relay


def test_mcp_relay_bars_the_session_from_later_passes(project: Project, iw: IWorld) -> None:
    cid = _approved(project, iw)
    relay = iw.human.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W3A"})
    review_concept(project, relay, cid, "reviewed", "", Channel.MCP)
    assert (relay.session,) in rows(project, "SELECT session FROM label_sessions")


def test_review_counts_are_computed(project: Project, iw: IWorld) -> None:
    a = _approved(project, iw)
    _approved(project, iw, name="second")
    c = define_concept(project, iw.writer, concept(name="third"))
    review_concept(project, iw.human, a, "reviewed", "", Channel.CLI)
    counts = concept_review_counts(project)
    assert counts == {
        ConceptState.UNREVIEWED: 2,
        ConceptState.REVIEWED: 1,
        ConceptState.WRONG: 0,
        ConceptState.MERGED: 0,
    }
    assert c
