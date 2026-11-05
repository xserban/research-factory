"""Defining concepts, deciding sources (slice 3c, plan G3-B, task 3)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.model.screening import Channel
from factory.services.concepts import (
    concept_history,
    concept_view,
    decide_concept_source,
    define_concept,
    list_concepts,
    visible_concepts,
)
from factory.services.context import Project
from factory.services.intuition_sources import stale_sources
from tests.contribution_helpers import with_references
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
)

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}


def concept(**kw: Any) -> Any:
    from factory.model.intuition import ConceptInput

    return ConceptInput.model_validate({"name": "random features", **kw})


def ids(listing: Any) -> list[str]:
    return [i.concept_id for i in listing.items]


def _events(project: Project) -> int:
    return len(rows(project, "SELECT 1 FROM events WHERE type LIKE 'concept.%'"))


def _refuse(call: Callable[[], object], field: str, reason: str | None = None) -> Any:
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert e.value.issues[0].field == field, e.value.issues
    if reason is not None:
        assert e.value.issues[0].reason == reason, e.value.issues
    return e.value


def test_agent_proposal_with_own_source_stays_hidden(project: Project, iw: IWorld) -> None:
    """Acceptance 6."""
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    view = concept_view(project, cid)
    assert view is not None
    assert view.review_state == "unreviewed" and view.source_state == "proposed"
    assert not view.visible and view.author == "agent"
    assert cid not in ids(list_concepts(project))
    assert list_concepts(project).hidden.unapproved == 1
    assert ids(list_concepts(project, include_hidden=True)) == [cid]


def test_agent_event_provenance(project: Project, iw: IWorld) -> None:  # acceptance 1
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    [ev] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "concept.defined"
    ]
    assert ev.actor.model == iw.writer.model and ev.actor.skill and ev.input_blob
    assert ev.payload["concept_id"] == cid and ev.payload["author"] == "agent"


def test_agent_cannot_approve(project: Project, iw: IWorld) -> None:
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    before = _events(project)
    _refuse(
        lambda: decide_concept_source(project, iw.writer, cid, "approve", "", Channel.MCP), "actor"
    )
    _refuse(
        lambda: define_concept(
            project, iw.writer, concept(name="x", source=TEXTBOOK), approve_source=True
        ),
        "actor",
    )
    assert _events(project) == before


def test_writer_session_relay_cannot_approve(project: Project, iw: IWorld) -> None:
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    _refuse(lambda: decide_concept_source(project, relay, cid, "approve", "", Channel.MCP), "actor")


def test_human_define_with_approval_is_visible_and_human_authored(
    project: Project, iw: IWorld
) -> None:
    cid = define_concept(project, iw.human, concept(source=TEXTBOOK), approve_source=True)
    view = concept_view(project, cid)
    assert view is not None and view.visible and view.author == "human"
    assert view.source_state == "approved" and view.label == "interpretation · unreviewed"
    assert view.flags == ["unverifiable-source"]
    assert cid in ids(list_concepts(project))
    assert rows(project, "SELECT type FROM events WHERE type LIKE 'concept.%' ORDER BY id") == [
        ("concept.defined",),
        ("concept.source_decided",),
    ]


def test_approve_source_needs_a_source(project: Project, iw: IWorld) -> None:
    _refuse(lambda: define_concept(project, iw.human, concept(), approve_source=True), "source")
    assert _events(project) == 0


def test_concept_without_text_or_source_is_allowed(project: Project, iw: IWorld) -> None:
    cid = define_concept(project, iw.writer, concept())
    view = concept_view(project, cid)
    assert view is not None and view.text is None and view.source is None
    assert view.source_state == "none"


def test_unverifiable_source_refuses_quotes_and_is_flagged(
    project: Project, iw: IWorld
) -> None:  # ruling B3
    quote = iw.quote()
    _refuse(
        lambda: define_concept(project, iw.writer, concept(source=TEXTBOOK, quotes=[quote])),
        "quotes",
        "unverifiable-source",
    )
    _refuse(
        lambda: define_concept(project, iw.writer, concept(quotes=[quote])), "quotes", "no-source"
    )
    assert _events(project) == 0
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    view = concept_view(project, cid)
    assert view is not None and "unverifiable-source" in view.flags


def test_corpus_source_quotes_must_come_from_source_work(project: Project, iw: IWorld) -> None:
    source = {"kind": "corpus-paper", "citation": "Other paper", "work_id": iw.other}
    err = _refuse(
        lambda: define_concept(project, iw.writer, concept(source=source, quotes=[iw.quote()])),
        "quotes[0].work_id",
        "not-source-work",
    )
    assert _events(project) == 0
    assert len(err.issues) == 1


def test_corpus_source_work_must_be_in_the_corpus(project: Project, iw: IWorld) -> None:
    source = {"kind": "corpus-paper", "citation": "X", "work_id": "rf:nope-00000000"}
    _refuse(
        lambda: define_concept(project, iw.writer, concept(source=source)),
        "source.work_id",
        "work-unknown",
    )


def test_verified_quotes_are_stored_and_verifiable(project: Project, iw: IWorld) -> None:
    source = {"kind": "corpus-paper", "citation": "The source paper", "work_id": iw.source}
    cid = define_concept(project, iw.writer, concept(source=source, quotes=[iw.quote()]))
    view = concept_view(project, cid)
    assert view is not None and view.flags == []
    assert [q.anchor for q in view.quotes] == ["s1.p4"] and view.quotes[0].document_id == iw.doc
    assert view.source is not None and view.source.verifiable
    _refuse(
        lambda: define_concept(
            project,
            iw.writer,
            concept(name="other", source=source, quotes=[iw.quote(quote="not in the paper")]),
        ),
        "quotes[0].quote",
    )


def test_name_or_alias_collision_refused_with_existing_id(
    project: Project, iw: IWorld
) -> None:  # ruling B4
    cid = define_concept(project, iw.writer, concept(aliases=["RFF"]))
    err = _refuse(
        lambda: define_concept(project, iw.writer, concept(name="  RANDOM  Features ")), "name"
    )
    assert err.issues[0].reason == f"concept-exists:{cid}"
    err = _refuse(
        lambda: define_concept(project, iw.writer, concept(name="other", aliases=["a", "rff"])),
        "aliases[1]",
    )
    assert err.issues[0].reason == f"concept-exists:{cid}"
    _refuse(
        lambda: define_concept(project, iw.writer, concept(name="rff")), "name"
    )  # a name equal to an alias
    assert _events(project) == 1


def test_shape_limits_are_reported_together(project: Project, iw: IWorld) -> None:
    err = _refuse(
        lambda: define_concept(
            project,
            iw.writer,
            concept(name="n" * 121, aliases=[f"a{i}" for i in range(11)], text="t" * 601),
        ),
        "name",
    )
    assert {i.field for i in err.issues} == {"name", "aliases", "text"}
    assert _events(project) == 0


def test_text_over_600_refused_and_nothing_written(project: Project, iw: IWorld) -> None:
    _refuse(lambda: define_concept(project, iw.writer, concept(text="x" * 601)), "text")
    assert _events(project) == 0
    assert define_concept(project, iw.writer, concept(text="x" * 600))


def test_redefinition_must_name_live_definition(project: Project, iw: IWorld) -> None:  # ruling B5
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    first = rows(project, "SELECT definition_event FROM concepts")[0][0]
    _refuse(
        lambda: define_concept(project, iw.writer, concept(concept_id=cid, text="v2")),
        "supersedes",
        "not-current-definition",
    )
    _refuse(
        lambda: define_concept(
            project, iw.writer, concept(concept_id=cid, text="v2", supersedes="ev_nope")
        ),
        "supersedes",
        "not-current-definition",
    )
    _refuse(
        lambda: define_concept(project, iw.writer, concept(supersedes=first, name="y")),
        "supersedes",
    )
    _refuse(
        lambda: define_concept(
            project,
            iw.writer,
            concept(concept_id="cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ", supersedes=first),
        ),
        "concept_id",
        "concept-unknown",
    )
    assert (
        define_concept(
            project,
            iw.writer,
            concept(concept_id=cid, text="v2", supersedes=first, source=TEXTBOOK),
        )
        == cid
    )
    view = concept_view(project, cid)
    assert view is not None and view.text == "v2"
    kinds = [(h.kind, h.state) for h in concept_history(project, cid)]
    assert kinds == [("recorded", None), ("recorded", None), ("superseded-by", "superseded")]


def test_agent_redefines_only_agent_written_concepts(project: Project, iw: IWorld) -> None:
    cid = define_concept(project, iw.human, concept(source=TEXTBOOK), approve_source=True)
    first = rows(project, "SELECT definition_event FROM concepts")[0][0]
    _refuse(
        lambda: define_concept(
            project, iw.writer, concept(concept_id=cid, supersedes=first, text="v2")
        ),
        "concept_id",
        "human-written",
    )
    assert define_concept(
        project, iw.human, concept(concept_id=cid, supersedes=first, text="v2", source=TEXTBOOK)
    )


def test_agent_redefinition_with_new_source_hides_concept(
    project: Project, iw: IWorld
) -> None:  # Review Focus 3
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    assert cid in ids(list_concepts(project))
    first = rows(project, "SELECT definition_event FROM concepts")[0][0]
    before = _events(project)
    new_source = {"kind": "survey", "citation": "A survey"}
    define_concept(project, iw.writer, concept(concept_id=cid, supersedes=first, source=new_source))
    assert _events(project) == before + 1  # no earlier event touched
    assert cid not in ids(list_concepts(project))
    view = concept_view(project, cid)
    assert view is not None and view.source_state == "proposed" and not view.visible


def test_redefinition_keeping_source_stays_visible_unreviewed(project: Project, iw: IWorld) -> None:
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    first = rows(project, "SELECT definition_event FROM concepts")[0][0]
    define_concept(
        project, iw.writer, concept(concept_id=cid, supersedes=first, source=TEXTBOOK, text="v2")
    )
    view = concept_view(project, cid)
    assert view is not None and view.visible and view.source_state == "approved"


def test_reject_needs_note_and_keeps_concept_hidden(project: Project, iw: IWorld) -> None:
    cid = define_concept(project, iw.writer, concept(source=TEXTBOOK))
    _refuse(
        lambda: decide_concept_source(project, iw.human, cid, "reject", " ", Channel.CLI), "note"
    )
    decide_concept_source(project, iw.human, cid, "reject", "wrong book", Channel.CLI)
    view = concept_view(project, cid)
    assert view is not None and view.source_state == "rejected" and not view.visible
    assert cid not in ids(list_concepts(project))
    assert [h.kind for h in concept_history(project, cid)] == ["recorded", "source-decided"]
    assert concept_history(project, cid)[1].state == "reject"
    # a later approval of the same source overrides the rejection
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    assert cid in ids(list_concepts(project))


def test_decide_source_refusals(project: Project, iw: IWorld) -> None:
    bare = define_concept(project, iw.writer, concept(name="bare"))
    _refuse(
        lambda: decide_concept_source(project, iw.human, bare, "approve", "", Channel.CLI), "source"
    )
    _refuse(
        lambda: decide_concept_source(
            project, iw.human, "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ", "approve", "", Channel.CLI
        ),
        "concept_id",
    )


def test_visible_concepts_lists_only_visible_briefs(project: Project, iw: IWorld) -> None:
    shown = define_concept(
        project, iw.human, concept(source=TEXTBOOK, aliases=["RFF"]), approve_source=True
    )
    define_concept(project, iw.writer, concept(name="hidden", source=TEXTBOOK))
    briefs = visible_concepts(project)
    assert [(b.concept_id, b.name, b.aliases) for b in briefs] == [
        (shown, "random features", ["RFF"])
    ]


def test_concept_quote_source_stale_flag(project: Project, iw: IWorld) -> None:
    source = {"kind": "corpus-paper", "citation": "The source paper", "work_id": iw.source}
    cid = define_concept(project, iw.writer, concept(source=source, quotes=[iw.quote()]))
    assert stale_sources(project) == {}
    with_references(project, iw.writer, iw.source, version="v4")
    assert stale_sources(project) == {cid: (iw.doc,)}
    assert stale_sources(project, only=["cpt_other"]) == {}
    view = concept_view(project, cid)
    assert view is not None and "source-stale" in view.flags


def test_list_pages_by_id(project: Project, iw: IWorld) -> None:
    made = [
        define_concept(
            project, iw.human, concept(name=f"c{i}", source=TEXTBOOK), approve_source=True
        )
        for i in range(3)
    ]
    from factory.services import concepts as svc

    first = svc.list_concepts(project, limit=2)
    assert ids(first) == made[:2] and first.next_cursor == made[1]
    second = svc.list_concepts(project, cursor=first.next_cursor, limit=2)
    assert ids(second) == made[2:] and second.next_cursor is None
