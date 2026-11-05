"""`uses` links: proposal, classification, cycles, human decisions (slice 3c, G3-B, task 4)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.model.intuition import ConceptInput, LinkStatus, UseBasisInput
from factory.model.screening import Channel
from factory.services.concepts import (
    LinkResult,
    decide_concept_link,
    decide_concept_source,
    define_concept,
    list_concept_links,
    propose_concept_link,
)
from factory.services.context import Project
from tests.intuition_helpers import (
    IWorld,
    concept_source,
    ctr_a,
    ctr_b,
    defined,
    iw,
    lin,
    record_event,
    reviewer,
    rows,
    screened,
    source_decided,
    world,
)

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}
ALL = [s for s in LinkStatus]


def make(
    project: Project, iw: IWorld, name: str, *, source: Any = None, approve: bool = False
) -> str:
    entry = ConceptInput.model_validate({"name": name, "source": source})
    return define_concept(project, iw.human, entry, approve_source=approve and source is not None)


def basis(**kw: Any) -> UseBasisInput:
    return UseBasisInput.model_validate(kw)


def quote_basis(iw: IWorld, quote: str = "Unlike softmax attention") -> UseBasisInput:
    return basis(quote=iw.quote("s1.p2", quote))


def make_cited(project: Project, iw: IWorld, name: str, *, approve: bool) -> str:
    """A concept whose source is the work entry 5 of the source paper resolves to. That work is
    a G1 lookup, not a corpus work, so the events are written at payload level (the service
    would refuse a corpus-paper source outside the corpus)."""
    cid = f"cpt_{project.ids.ulid()}"
    source = concept_source("corpus-paper", "The cited paper", iw.lin.target5)
    record_event(
        project, "concept.defined", defined(cid, name=name, source=source, author="human"), iw.human
    )
    if approve:
        record_event(
            project,
            "concept.source_decided",
            source_decided(cid, "approve", source["digest"]),
            iw.human,
        )
    return cid


def _refuse(call: Callable[[], object], field: str, reason: str | None = None) -> Any:
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert e.value.issues[0].field == field, e.value.issues
    if reason is not None:
        assert e.value.issues[0].reason == reason, e.value.issues
    return e.value


def _link_events(project: Project) -> int:
    return len(rows(project, "SELECT 1 FROM events WHERE type LIKE 'concept.link%'"))


def test_quote_with_name_is_stated(project: Project, iw: IWorld) -> None:  # acceptance 7
    cid = make(project, iw, "softmax attention")
    r = propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    assert (r.status, r.status_reason, r.existing) == ("stated", "name-in-quote", False)
    assert r.link_id.startswith("cul_")


def test_alias_in_quote_is_stated(project: Project, iw: IWorld) -> None:
    entry = ConceptInput.model_validate({"name": "kernel map", "aliases": ["Softmax  Attention"]})
    cid = define_concept(project, iw.human, entry)
    r = propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    assert r.status_reason == "name-in-quote"


def test_citation_of_approved_source_is_stated(project: Project, iw: IWorld) -> None:
    cid = make_cited(project, iw, "base idea", approve=True)
    r = propose_concept_link(project, iw.writer, iw.source, cid, basis(reference=f"{iw.lin.rex}:5"))
    assert (r.status, r.status_reason) == ("stated", "cites-approved-source")


def test_other_links_inferred_and_absent_from_default(project: Project, iw: IWorld) -> None:
    named = make(project, iw, "softmax attention", source=TEXTBOOK, approve=True)
    approved = make_cited(project, iw, "base idea", approve=True)
    unapproved = make_cited(project, iw, "other idea", approve=False)
    textbook = make(project, iw, "third idea", source=TEXTBOOK, approve=True)
    cases = {
        "name-not-in-quote": (named, quote_basis(iw, "our module is linear")),
        "citation-not-approved-source": (approved, basis(reference=f"{iw.lin.rex}:3")),
        "source-unapproved": (unapproved, basis(reference=f"{iw.lin.rex}:5")),
        "source-not-in-corpus": (textbook, basis(reference=f"{iw.lin.rex}:5")),
    }
    for reason, (cid, b) in cases.items():
        r = propose_concept_link(project, iw.writer, iw.source, cid, b)
        assert (r.status, r.status_reason) == ("inferred", reason)
    bare = propose_concept_link(
        project, iw.writer, iw.source, named, basis(), note="I think the paper uses it"
    )
    assert (bare.status, bare.status_reason) == ("inferred", "no-basis")
    assert list_concept_links(project).items == []
    listed = list_concept_links(project, statuses=ALL, include_hidden=True)
    assert len(listed.items) == 5 and all(i.class_ == "interpretation" for i in listed.items)
    assert {i.label for i in listed.items} == {"interpretation · inferred"}
    assert listed.hidden.links_inferred == 5
    [noted] = [i for i in listed.items if i.link_id == bare.link_id]
    assert noted.note == "I think the paper uses it" and noted.note_label == "agent-note"


def test_unresolved_citation_is_inferred(project: Project, iw: IWorld) -> None:
    cid = make_cited(project, iw, "base idea", approve=True)
    unresolved = next(
        n for n in range(1, 7) if propose_check(project, iw, cid, n) == "citation-unresolved"
    )
    assert unresolved


def propose_check(project: Project, iw: IWorld, cid: str, n: int) -> str | None:
    from factory.services.intuition_sources import entry_link

    link = entry_link(project, f"{iw.lin.rex}:{n}")
    if link is None or link[0] != "unresolved":
        return None
    r = propose_concept_link(
        project, iw.writer, iw.source, cid, basis(reference=f"{iw.lin.rex}:{n}")
    )
    return r.status_reason


def test_reproposal_after_approval_records_new_stated_link(
    project: Project, iw: IWorld
) -> None:  # Review Focus 4
    cid = make_cited(project, iw, "base idea", approve=False)
    ref = basis(reference=f"{iw.lin.rex}:5")
    first = propose_concept_link(project, iw.writer, iw.source, cid, ref)
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    second = propose_concept_link(project, iw.writer, iw.source, cid, ref)
    assert (first.status, second.status, second.existing) == ("inferred", "stated", False)
    assert first.link_id != second.link_id
    both = list_concept_links(project, statuses=ALL)
    assert {i.link_id for i in both.items} == {first.link_id, second.link_id}
    assert [i.link_id for i in list_concept_links(project).items] == [second.link_id]


def test_identical_proposal_is_idempotent(project: Project, iw: IWorld) -> None:
    cid = make(project, iw, "softmax attention")
    first = propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    before = _link_events(project)
    again = propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    assert again.existing is True and again.link_id == first.link_id
    assert _link_events(project) == before
    # a rejected link is not returned: the same proposal records a new one
    other = propose_concept_link(project, iw.writer, iw.source, cid, basis(), note="n")
    decide_concept_link(project, iw.human, other.link_id, "reject", "no", Channel.CLI)
    renewed = propose_concept_link(project, iw.writer, iw.source, cid, basis(), note="n")
    assert renewed.existing is False and renewed.link_id != other.link_id


def test_quote_from_another_work_refused(project: Project, iw: IWorld) -> None:
    cid = make(project, iw, "softmax attention")
    _refuse(
        lambda: propose_concept_link(project, iw.writer, iw.other, cid, quote_basis(iw)),
        "basis.quote.work_id",
        "not-from-work",
    )
    _refuse(
        lambda: propose_concept_link(
            project, iw.writer, iw.other, cid, basis(reference=f"{iw.lin.rex}:5")
        ),
        "basis.reference",
        "not-from-work",
    )
    assert _link_events(project) == 0


def test_idea_members_may_supply_the_quote(project: Project, iw: IWorld) -> None:
    cid = make(project, iw, "softmax attention")
    r = propose_concept_link(project, iw.writer, iw.idea1, cid, quote_basis(iw))
    assert r.status == "stated"
    assert rows(project, "SELECT from_kind, from_node FROM concept_uses") == [("idea", iw.idea1)]


def test_non_verbatim_quote_and_bad_nodes_refused(project: Project, iw: IWorld) -> None:
    cid = make(project, iw, "softmax attention")
    _refuse(
        lambda: propose_concept_link(
            project, iw.writer, iw.source, cid, quote_basis(iw, "not in the paper at all")
        ),
        "basis.quote.quote",
    )
    _refuse(
        lambda: propose_concept_link(
            project, iw.writer, "int_01HZX3K4M5N6P7Q8R9S0T1V2WA", cid, basis(), note="n"
        ),
        "from_node",
    )
    _refuse(
        lambda: propose_concept_link(
            project, iw.writer, "rf:nobody-00000000", cid, basis(), note="n"
        ),
        "from_node",
    )
    _refuse(
        lambda: propose_concept_link(
            project, iw.writer, iw.source, "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ", basis(), note="n"
        ),
        "concept_id",
        "concept-unknown",
    )
    assert _link_events(project) == 0


def test_no_basis_needs_note(project: Project, iw: IWorld) -> None:
    cid = make(project, iw, "softmax attention")
    _refuse(lambda: propose_concept_link(project, iw.writer, iw.source, cid, basis()), "note")
    _refuse(
        lambda: propose_concept_link(project, iw.writer, iw.source, cid, basis(), note=" "), "note"
    )


def test_concept_cycle_refused(project: Project, iw: IWorld) -> None:  # acceptance 7
    c1, c2, c3 = (make(project, iw, f"idea {i}") for i in (1, 2, 3))
    propose_concept_link(project, iw.writer, c1, c2, basis(), note="n")
    propose_concept_link(project, iw.writer, c2, c3, basis(), note="n")
    err = _refuse(
        lambda: propose_concept_link(project, iw.writer, c3, c1, basis(), note="n"),
        "concept_id",
        "cycle",
    )
    assert len(err.issues) == 1
    _refuse(
        lambda: propose_concept_link(project, iw.writer, c1, c1, basis(), note="n"),
        "concept_id",
        "self-link",
    )
    # a rejected link no longer counts
    [first] = rows(project, f"SELECT link_id FROM concept_uses WHERE from_node = '{c1}'")
    decide_concept_link(project, iw.human, str(first[0]), "reject", "no", Channel.CLI)
    assert propose_concept_link(project, iw.writer, c3, c1, basis(), note="n").status == "inferred"


def test_concept_links_take_no_quote_or_reference(project: Project, iw: IWorld) -> None:
    c1, c2 = make(project, iw, "idea 1"), make(project, iw, "idea 2")
    _refuse(
        lambda: propose_concept_link(project, iw.writer, c1, c2, quote_basis(iw)),
        "basis.quote",
        "not-from-work",
    )
    _refuse(
        lambda: propose_concept_link(
            project, iw.writer, c1, c2, basis(reference=f"{iw.lin.rex}:5")
        ),
        "basis.reference",
        "not-from-work",
    )


def test_concept_to_concept_is_always_inferred(project: Project, iw: IWorld) -> None:
    c1, c2 = make(project, iw, "idea 1"), make(project, iw, "idea 2")
    r = propose_concept_link(project, iw.writer, c1, c2, basis(), note="n")
    assert (r.status, r.status_reason) == ("inferred", "concept-to-concept")


def test_only_human_confirms_and_reject_supersedes(project: Project, iw: IWorld) -> None:  # R-51
    cid = make(project, iw, "softmax attention", source=TEXTBOOK, approve=True)
    r = propose_concept_link(project, iw.writer, iw.source, cid, basis(), note="n")
    before = _link_events(project)
    _refuse(
        lambda: decide_concept_link(project, iw.writer, r.link_id, "confirm", "ok", Channel.MCP),
        "actor",
    )
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    _refuse(
        lambda: decide_concept_link(project, relay, r.link_id, "confirm", "ok", Channel.MCP),
        "actor",
    )
    assert _link_events(project) == before
    decide_concept_link(project, iw.human, r.link_id, "confirm", "checked", Channel.CLI)
    [(status,)] = rows(project, "SELECT status FROM concept_uses")
    assert status == "confirmed"
    shown = list_concept_links(project)
    assert [(i.status, i.label, i.decided_by) for i in shown.items] == [
        ("confirmed", "interpretation · confirmed", iw.human.user)
    ]
    decide_concept_link(project, iw.human, r.link_id, "reject", "on reflection no", Channel.CLI)
    assert list_concept_links(project).items == []
    assert list_concept_links(project).hidden.links_rejected == 1
    assert [
        i.status for i in list_concept_links(project, statuses=[LinkStatus.REJECTED]).items
    ] == ["rejected"]


def test_decision_refusals(project: Project, iw: IWorld) -> None:
    cid = make(project, iw, "softmax attention")
    stated = propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    _refuse(
        lambda: decide_concept_link(
            project, iw.human, stated.link_id, "confirm", "ok", Channel.CLI
        ),
        "decision",
        "not-inferred",
    )
    inferred = propose_concept_link(project, iw.writer, iw.source, cid, basis(), note="n")
    _refuse(
        lambda: decide_concept_link(
            project, iw.human, inferred.link_id, "confirm", " ", Channel.CLI
        ),
        "rationale",
    )
    _refuse(
        lambda: decide_concept_link(
            project, iw.human, "cul_01HZX3K4M5N6P7Q8R9S0T1V2WZ", "reject", "no", Channel.CLI
        ),
        "link_id",
    )
    decide_concept_link(project, iw.human, inferred.link_id, "confirm", "ok", Channel.CLI)
    _refuse(
        lambda: decide_concept_link(
            project, iw.human, inferred.link_id, "confirm", "ok", Channel.CLI
        ),
        "decision",
        "not-inferred",
    )
    decide_concept_link(project, iw.human, inferred.link_id, "reject", "no", Channel.CLI)
    _refuse(
        lambda: decide_concept_link(
            project, iw.human, inferred.link_id, "reject", "no", Channel.CLI
        ),
        "decision",
        "already-rejected",
    )
    decide_concept_link(project, iw.human, stated.link_id, "reject", "no", Channel.CLI)


def test_links_of_a_hidden_concept_are_hidden_by_default(project: Project, iw: IWorld) -> None:
    cid = define_concept(
        project,
        iw.writer,
        ConceptInput.model_validate({"name": "softmax attention", "source": TEXTBOOK}),
    )
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    r = propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    assert [i.link_id for i in list_concept_links(project).items] == [r.link_id]
    first = rows(project, "SELECT definition_event FROM concepts")[0][0]
    define_concept(
        project,
        iw.writer,
        ConceptInput.model_validate(
            {
                "name": "softmax attention",
                "concept_id": cid,
                "supersedes": first,
                "source": {"kind": "survey", "citation": "Another"},
            }
        ),
    )
    assert list_concept_links(project).items == []  # endpoint hidden, no earlier event edited
    assert len(list_concept_links(project, include_hidden=True).items) == 1


def test_list_filters_by_concept_and_pages(project: Project, iw: IWorld) -> None:
    c1 = make(project, iw, "softmax attention", source=TEXTBOOK, approve=True)
    c2 = make(project, iw, "idea 2", source=TEXTBOOK, approve=True)
    made = [
        propose_concept_link(project, iw.writer, iw.source, c1, quote_basis(iw)).link_id,
        propose_concept_link(project, iw.writer, iw.idea1, c1, quote_basis(iw)).link_id,
        propose_concept_link(project, iw.writer, iw.source, c2, quote_basis(iw, "linear")).link_id,
    ]
    mine = list_concept_links(project, statuses=ALL, concept_id=c1)
    assert {i.link_id for i in mine.items} == set(made[:2])
    first = list_concept_links(project, statuses=ALL, limit=2)
    second = list_concept_links(project, statuses=ALL, cursor=first.next_cursor, limit=2)
    assert len(first.items) == 2 and first.next_cursor is not None
    assert [i.link_id for i in second.items] + [i.link_id for i in first.items] == sorted(made)[
        2:
    ] + sorted(made)[:2]


def test_agent_event_provenance(project: Project, iw: IWorld) -> None:  # acceptance 1
    cid = make(project, iw, "softmax attention")
    propose_concept_link(project, iw.writer, iw.source, cid, quote_basis(iw))
    [ev] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "concept.link_proposed"
    ]
    assert ev.actor.model == "claude-opus-5-5" and ev.actor.skill and ev.input_blob
    assert ev.payload["status"] == "stated" and ev.payload["basis_kind"] == "quote"
