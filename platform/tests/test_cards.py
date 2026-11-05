"""Cards and verified property assertions (slice 6, plan H-A, task 4)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.extraction.numbers import canonical
from factory.model.cards import InferredBasis, QuoteBasis, RowBasis
from factory.model.extraction import CardScope, Scope
from factory.model.lineage import LineageDecision
from factory.model.screening import Channel
from factory.services import cards as cards_service
from factory.services.cards import (
    AssertionInput,
    assert_properties,
    card_view,
    create_card,
    decide_assertion,
    effective_card_props,
    list_cards,
)
from factory.services.context import Project
from factory.services.document_read import ConversionRef
from factory.services.extraction_agreement import FinalRow
from factory.services.extraction_audit import (
    agreed_values,
    audit_evidence,
    extraction_audit_record,
    extraction_audit_report,
    extraction_audit_sample,
)
from factory.services.ideas import decide_idea, propose_idea
from factory.services.properties import (
    decide_property,
    merge_properties,
    propose_property,
    resolve_property,
)
from factory.services.question import current_question
from tests.card_helpers import (
    ATTENTION,
    DENSE,
    LONG_SEQ,
    TOP1,
    CardWorld,
    approve,
    cw,
    prop,
    quote_basis,
)
from tests.evidence_helpers import frow
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world

P1 = "linear attention"
P3 = "82.4% top-1"
P4 = "very long sequences degrade"


def _events(project: Project, *kinds: str) -> list[Any]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


def _refused(project: Project, field: str, reason: str, call: Callable[[], object]) -> None:
    before = len(_events(project, "card.created", "card.asserted", "card.assertion_decided"))
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert (e.value.issues[0].field, e.value.issues[0].reason) == (field, reason)
    after = len(_events(project, "card.created", "card.asserted", "card.assertion_decided"))
    assert after == before


def quote_item(w: CardWorld, key: str, value: Any, anchor: str, quote: str, **kw: Any) -> Any:
    return AssertionInput(
        property=key,
        value=value,
        basis_kind="quote",
        basis=quote_basis(w, anchor, quote),
        **kw,
    )


@pytest.fixture
def card(project: Project, agent: Actor, cw: CardWorld) -> str:
    return create_card(project, agent, "method", cw.source, "obd")


def test_quote_assertion_stated(project: Project, agent: Actor, cw: CardWorld, card: str) -> None:
    # acceptance 2-3
    r = assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    assert r.rejected == []
    assert r.accepted[0][0] == 0 and r.accepted[0][2] == "stated"
    view = card_view(project, card)
    assert view is not None
    [a] = view.assertions
    assert (a.property, a.value, a.effective, a.basis_kind) == (
        "pr:attention-kind",
        "linear",
        "stated",
        "quote",
    )
    assert view.hidden_counts == {}


def test_number_quote_assertion_canonicalised(
    project: Project, agent: Actor, cw: CardWorld, card: str
) -> None:
    item = quote_item(cw, "pr:top1", "82.4", "s1.p3", P3, unit="%")
    r = assert_properties(project, agent, card, [item])
    assert r.rejected == []
    [event] = _events(project, "card.asserted")
    assert event.payload["canonical"] == "82.4" and event.payload["unit"] == "%"


def test_rejections_and_partial_acceptance(
    project: Project, agent: Actor, cw: CardWorld, card: str
) -> None:  # acceptance 2
    good = quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)
    not_verbatim = quote_item(cw, "pr:attention-kind", "linear", "s1.p1", "linear attentions rock")
    number_absent = quote_item(cw, "pr:top1", "99.9", "s1.p3", P3, unit="%")
    enum_absent = quote_item(cw, "pr:attention-kind", "softmax", "s1.p1", P1)
    bad_anchor = quote_item(cw, "pr:attention-kind", "linear", "s9.p9", P1)
    r = assert_properties(
        project, agent, card, [good, not_verbatim, number_absent, enum_absent, bad_anchor]
    )
    assert [i for i, *_ in r.accepted] == [0]
    reasons = {i: [x.reason for x in issues] for i, issues in r.rejected}
    assert reasons == {
        1: ["quote-not-verbatim"],
        2: ["value-not-in-quote"],
        3: ["value-not-in-quote"],
        4: ["anchor-unknown"],
    }
    dumped = repr(r.model_dump(mode="json")["rejected"])
    assert "linear attentions rock" not in dumped and "We build on" not in dumped
    assert len(_events(project, "card.asserted")) == 1


def test_value_property_and_basis_refusals(
    project: Project, agent: Actor, cw: CardWorld, card: str
) -> None:
    unknown = quote_item(cw, "pr:no-such-key", "x", "s1.p1", P1)
    bad_value = quote_item(cw, "pr:attention-kind", "gridded", "s1.p1", P1)
    problem_only = quote_item(cw, "pr:dense-prediction", True, "s1.p1", P1)
    other_work = AssertionInput(
        property="pr:attention-kind",
        value="linear",
        basis_kind="quote",
        basis=QuoteBasis(
            work_id=cw.other, conversion_id=cw.conversion_id, anchor="s1.p1", quote=P1
        ),
    )
    mismatch = AssertionInput(
        property="pr:attention-kind", value="linear", basis_kind="quote", basis=None
    )
    r = assert_properties(
        project, agent, card, [unknown, bad_value, problem_only, other_work, mismatch]
    )
    got = {i: [(x.field, x.reason) for x in issues] for i, issues in r.rejected}
    assert got == {
        0: [("property", "unknown")],
        1: [("value", "value-not-allowed")],
        2: [("property", "not-applicable")],
        3: [("basis.conversion_id", "conversion-other-work")],
        4: [("basis", "basis-required")],
    }
    assert r.accepted == []


def test_unknown_card_is_refused_whole(project: Project, agent: Actor, cw: CardWorld) -> None:
    item = quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)
    _refused(
        project,
        "card_id",
        "unknown",
        lambda: assert_properties(project, agent, "mcd_01JZ9Q3K5M7N8P0R2S4T6V8W1Z", [item]),
    )


def _row(w: CardWorld, value: str = "82.4") -> FinalRow:
    return frow(w.source, "rk_0123456789ab", "LinAtt", value)


def test_row_basis_follows_final_row(
    project: Project,
    agent: Actor,
    cw: CardWorld,
    card: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # Review Focus 3
    rows = {(cw.source, "rk_0123456789ab"): _row(cw)}
    monkeypatch.setattr(cards_service, "_load_final_rows", lambda _p: rows)
    item = AssertionInput(
        property="pr:top1",
        value="82.4",
        unit="%",
        basis_kind="row",
        basis=RowBasis(work_id=cw.source, row_key="rk_0123456789ab", field="value"),
    )
    differs = item.model_copy(update={"value": "82.5"})
    unknown = item.model_copy(
        update={"basis": RowBasis(work_id=cw.source, row_key="rk_ffffffffffff", field="value")}
    )
    r = assert_properties(project, agent, card, [item, differs, unknown])
    assert [i for i, *_ in r.accepted] == [0] and r.accepted[0][2] == "stated"
    assert {i: x[0].reason for i, x in r.rejected} == {1: "value-differs", 2: "row-unknown"}
    assert card_view(project, card).assertions[0].effective == "stated"  # type: ignore[union-attr]
    # the row is re-resolved to another value: the assertion is stale, not silently updated
    rows[(cw.source, "rk_0123456789ab")] = _row(cw, "83.0")
    view = card_view(project, card, include_stale=True)
    assert view is not None
    [a] = view.assertions
    assert (a.effective, a.stale_reasons) == ("stale", ("row-changed",))
    assert a.value == "82.4"
    assert card_view(project, card).assertions == []  # type: ignore[union-attr]
    # and gone altogether
    rows.clear()
    assert card_view(project, card, include_stale=True).assertions[0].stale_reasons == (  # type: ignore[union-attr]
        "row-changed",
    )


def test_inferred_excluded_until_confirmed(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld, card: str
) -> None:  # acceptance 3
    item = AssertionInput(
        property="pr:long-sequences",
        value=True,
        basis_kind="inferred",
        basis=InferredBasis(note="the paper's scaling argument implies it"),
    )
    r = assert_properties(project, agent, card, [item])
    pas = r.accepted[0][1]
    assert r.accepted[0][2] == "inferred"
    default = card_view(project, card)
    assert default is not None and default.assertions == []
    assert default.hidden_counts == {"inferred": 1}
    shown = card_view(project, card, include_inferred=True)
    assert shown is not None and shown.assertions[0].effective == "inferred"
    assert list(effective_card_props(project, ["pr:long-sequences"], {"stated", "confirmed"})) == []
    decide_assertion(project, other_session_human, pas, "confirm", "checked in the paper")
    confirmed = card_view(project, card)
    assert confirmed is not None and confirmed.assertions[0].effective == "confirmed"
    [row] = list(effective_card_props(project, ["pr:long-sequences"], {"stated", "confirmed"}))
    assert (row.card_id, row.value_norm, row.effective) == (card, "true", "confirmed")


def test_agent_cannot_confirm(
    project: Project, agent: Actor, agent_other: Actor, cw: CardWorld, card: str
) -> None:
    inferred = AssertionInput(
        property="pr:long-sequences",
        value=True,
        basis_kind="inferred",
        basis=InferredBasis(note="reasoned"),
    )
    stated = quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)
    r = assert_properties(project, agent, card, [inferred, stated])
    pas_inferred = r.accepted[0][1]
    _refused(
        project,
        "actor",
        "human-only",
        lambda: decide_assertion(project, agent_other, pas_inferred, "confirm", "ok"),
    )
    same_session = Actor(kind="human", id="obd", user="obd", session=agent.session)
    _refused(
        project,
        "actor",
        "proposer-session",
        lambda: decide_assertion(project, same_session, pas_inferred, "confirm", "ok"),
    )


def test_confirm_applies_to_inferred_only(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld, card: str
) -> None:
    r = assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    pas = r.accepted[0][1]
    _refused(
        project,
        "decision",
        "not-inferred",
        lambda: decide_assertion(project, other_session_human, pas, "confirm", "ok"),
    )
    _refused(
        project,
        "assertion_id",
        "unknown",
        lambda: decide_assertion(
            project, other_session_human, "pas_01JZ9Q3K5M7N8P0R2S4T6V8W1Z", "reject", "ok"
        ),
    )
    decide_assertion(project, other_session_human, pas, "reject", "misread")
    view = card_view(project, card, include_stale=True, include_inferred=True)
    assert view is not None and view.assertions == []
    assert view.hidden_counts == {"rejected": 1}


def test_researcher_basis_human_only(
    project: Project, agent: Actor, human: Actor, cw: CardWorld
) -> None:
    q = current_question(project)
    assert q is not None
    problem = create_card(project, human, "problem", q.question_id, "obd")
    item = AssertionInput(property="pr:dense-prediction", value=True, basis_kind="researcher")
    r = assert_properties(project, agent, problem, [item])
    assert r.accepted == [] and r.rejected[0][1][0].field == "basis_kind"
    assert r.rejected[0][1][0].reason == "human-only"
    r = assert_properties(project, human, problem, [item])
    assert r.accepted[0][2] == "stated"
    [event] = [e for e in _events(project, "card.asserted") if e.actor.kind == "human"]
    assert event.payload["basis_kind"] == "researcher" and event.input_blob is None


def test_definition_change_stales_assertion(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld, card: str
) -> None:  # Review Focus 1
    item = quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)
    assert_properties(project, agent, card, [item])
    changed = prop(
        "pr:attention-kind",
        allowed=["linear", "softmax", "hybrid"],
        applies_to="method",
        value_aliases={"linear": ["linear attention"], "softmax": ["softmax attention"]},
    )
    propose_property(project, agent, changed, supersedes="pr:attention-kind")
    assert card_view(project, card).assertions[0].effective == "stated"  # type: ignore[union-attr]
    decide_property(project, other_session_human, "pr:attention-kind", "approve", "adds hybrid")
    assert card_view(project, card).assertions == []  # type: ignore[union-attr]
    stale = card_view(project, card, include_stale=True)
    assert stale is not None
    assert stale.assertions[0].stale_reasons == ("definition-changed",)
    assert card_view(project, card).hidden_counts == {"stale": 1}  # type: ignore[union-attr]
    assert list(effective_card_props(project, ["pr:attention-kind"], {"stated"})) == []
    assert_properties(project, agent, card, [item])  # re-asserting restores it
    again = card_view(project, card)
    assert again is not None and again.assertions[0].effective == "stated"


def test_property_rejection_stales_assertion(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld, card: str
) -> None:
    assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    decide_property(project, other_session_human, "pr:attention-kind", "reject", "dropped")
    view = card_view(project, card, include_stale=True)
    assert view is not None and view.assertions[0].stale_reasons == ("property-rejected",)


def test_new_assertion_supersedes_same_property(
    project: Project, agent: Actor, cw: CardWorld, card: str
) -> None:
    first = assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    second = assert_properties(
        project,
        agent,
        card,
        [quote_item(cw, "pr:attention-kind", "softmax", "s1.p2", "softmax attention")],
    )
    view = card_view(project, card)
    assert view is not None
    [a] = view.assertions
    assert a.assertion_id == second.accepted[0][1] and a.value == "softmax"
    [_, e2] = _events(project, "card.asserted")
    assert e2.payload["supersedes"] == first.accepted[0][1]


def test_card_subject_must_be_confirmed_idea(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld
) -> None:
    proposed = propose_idea(project, agent, "linear attention", cw.source, cw.lin.base, [cw.source])
    _refused(
        project,
        "subject",
        "idea-not-confirmed",
        lambda: create_card(project, agent, "method", proposed, "obd"),
    )
    _refused(
        project,
        "subject",
        "subject-unknown",
        lambda: create_card(project, agent, "method", "rf:nobody-1999-deadbeef", "obd"),
    )
    by_idea = create_card(project, agent, "method", cw.idea, "obd")
    assert create_card(project, agent, "method", cw.idea, "someone-else") == by_idea
    by_work = create_card(project, agent, "method", cw.source, "obd")
    assert by_work != by_idea and by_work.startswith("mcd_")
    assert len(_events(project, "card.created")) == 2


def test_problem_subject_is_current_question_or_task(
    project: Project, agent: Actor, cw: CardWorld
) -> None:
    q = current_question(project)
    assert q is not None
    pbd = create_card(project, agent, "problem", q.question_id, "obd")
    assert pbd.startswith("pbd_")
    task = create_card(project, agent, "problem", "high-resolution dense prediction", "obd")
    assert task != pbd
    assert create_card(project, agent, "problem", "high-resolution  dense prediction", "x") == task
    _refused(
        project,
        "subject",
        "subject-unknown",
        lambda: create_card(project, agent, "problem", "Q@00000000", "obd"),
    )
    assert {c.card_id for c in list_cards(project, "problem")} == {pbd, task}
    assert list_cards(project, "method") == []


def test_idea_not_live_and_document_superseded(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    cw: CardWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = create_card(project, agent, "method", cw.idea, "obd")
    assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    monkeypatch.setattr(
        cards_service,
        "default_conversion",
        lambda _p, _w: ConversionRef("doc_other", "cnv_01JZ9Q3K5M7N8P0R2S4T6V8WZZ"),
    )
    view = card_view(project, card, include_stale=True)
    assert view is not None and view.assertions[0].stale_reasons == ("document-superseded",)
    monkeypatch.undo()
    decide_idea(project, other_session_human, cw.idea, LineageDecision.REJECT, "not an idea")
    view = card_view(project, card, include_stale=True)
    assert view is not None and view.assertions[0].stale_reasons == ("idea-not-live",)


def test_merged_property_resolves_in_card_props(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld, card: str
) -> None:
    approve(
        project,
        agent,
        other_session_human,
        prop("pr:long-seqs", kind="bool", allowed=[], value_aliases={}, aliases=["long sequences"]),
    )
    merge_properties(project, other_session_human, "pr:long-seqs", "pr:long-sequences", "same")
    assert_properties(
        project,
        agent,
        card,
        [
            AssertionInput(
                property="pr:long-seqs",
                value=True,
                basis_kind="quote",
                basis=quote_basis(cw, "s1.p4", P4),
            )
        ],
    )
    [row] = list(effective_card_props(project, ["pr:long-sequences"], {"stated"}))
    assert row.property_key == "pr:long-sequences" and row.card_kind == "method"
    assert row.subject == cw.source


def test_card_audit_population_is_stated_quotes(
    project: Project,
    agent: Actor,
    human: Actor,
    cw: CardWorld,
    card: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # ruling 6
    monkeypatch.setattr(
        cards_service, "_load_final_rows", lambda _p: {(cw.source, "rk_0123456789ab"): _row(cw)}
    )
    r = assert_properties(
        project,
        agent,
        card,
        [
            quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1),
            quote_item(cw, "pr:long-sequences", True, "s1.p4", P4),
            AssertionInput(
                property="pr:top1",
                value="82.4",
                unit="%",
                basis_kind="row",
                basis=RowBasis(work_id=cw.source, row_key="rk_0123456789ab", field="value"),
            ),
            AssertionInput(
                property="pr:dense-prediction",
                value=True,
                basis_kind="inferred",
                basis=InferredBasis(note="x"),
            ),
        ],
    )
    assert len(r.accepted) == 3 and len(r.rejected) == 1  # dense-prediction is problem-only
    population = agreed_values(project, scope=CardScope.CARD)
    assert sorted(i.field for i in population) == ["pr:attention-kind", "pr:long-sequences"]
    sampled = extraction_audit_sample(project, human, random_seed=7, scope=CardScope.CARD)
    assert sampled.pack == "card" and len(sampled.items) == 2
    for item in sampled.items:
        extraction_audit_record(
            project,
            human,
            sampled.audit_id,
            item.work_id,
            item.row_key,
            item.field,
            item.field != "pr:long-sequences",
            "checked",
            Channel.CLI,
        )
    report = extraction_audit_report(project, scope=CardScope.CARD)
    assert report is not None
    assert (report.sample_size, report.labelled, report.incorrect) == (2, 2, 1)
    # evidence-scope audits are untouched
    assert extraction_audit_report(project) is None
    # a superseding assertion makes the sampled item outdated: it leaves the rate
    assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    again = extraction_audit_report(project, scope=CardScope.CARD)
    assert again is not None and (again.labelled, again.outdated) == (1, 1)
    # a fresh sample waits for a change; the changed set can be sampled again
    shown = audit_evidence(project, human, sampled.audit_id, Channel.CLI)
    assert [e.item.field for e in shown] == ["pr:long-sequences"]
    assert shown[0].quote == P4 and "very long sequences" in shown[0].element_text


def test_event_provenance(project: Project, agent: Actor, cw: CardWorld, card: str) -> None:
    assert_properties(
        project, agent, card, [quote_item(cw, "pr:attention-kind", "linear", "s1.p1", P1)]
    )
    for event in _events(project, "card.created", "card.asserted"):
        assert event.actor.model == "claude-opus-5-5"
        assert event.actor.skill and event.input_blob
        assert project.blobs.get(event.input_blob)


def test_assertion_input_forbids_status() -> None:
    with pytest.raises(Exception, match="status"):
        AssertionInput.model_validate(
            {"property": "pr:x-key", "value": "a", "basis_kind": "inferred", "status": "stated"}
        )
