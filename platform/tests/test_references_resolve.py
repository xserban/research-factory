"""Decisions on reference links (ruling 3, 14a): proposals, confirmations, rejections, quotes.

Every entry and work is invented.
"""

from __future__ import annotations

from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.references import Decision, LinkState, ReferenceExtracted
from factory.services import reference_resolve
from factory.services import references as references_service
from factory.services.check import LEVELS, _findings_as
from factory.services.context import Project
from factory.services.reference_resolve import decide_reference, entry_digest, entry_text
from factory.services.references import (
    ReferenceItem,
    current_extraction,
    extract_references,
    list_references,
    reference_counts,
)
from tests.document_helpers import (
    StubConverter,
    event_bytes,
    events_of_type,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.references_service_helpers import (
    Lookups,
    bib_html,
    converted_work,
    corpus_works,
    oa_item,
    second_agent,
)

ENTRIES = [
    "B. Lee. Efficient reed transformers v2. Reed Conference, 2021.",
    "P. Ostrander. Moss growth under filtered light v2. Bryology Today, 2008.",
    "A. Zhou. Paper 2. Journal of Tests, 2020. doi:10.1000/p2.",
]
ENTRY_QUOTE = "Efficient reed transformers v2"
CAND_QUOTE = "Efficient Reed Transformers"
MOSS_QUOTES = ("Moss growth under filtered light v2", "Moss growth under filtered light")


@pytest.fixture
def extraction(project: Project, corpus: None, agent: Actor) -> str:
    lookups = Lookups(
        openalex=[
            oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501"),
            oa_item("Moss growth under filtered light", "Pia Ostrander", 2008, "W502"),
            oa_item("Moss growth under filtered lights", "Pia Ostrander", 2008, "W503"),
        ]
    )
    converted_work(project, ENTRIES, ["x"])
    [result] = extract_references(project, agent, None, sources=lookups.sources()).extractions
    return result.extraction_id


def _item(project: Project, ordinal: int) -> ReferenceItem:
    page = list_references(project, state=None, work_id=None, after=0, limit=10)
    return next(i for i in page.items if i.ordinal == ordinal)


def _decide(
    project: Project,
    actor: Actor,
    rex: str,
    ordinal: int,
    decision: Decision,
    *,
    quotes: tuple[str, str] = (ENTRY_QUOTE, CAND_QUOTE),
    work_id: str | None = None,
    rationale: str = "Same paper; the entry adds a version suffix.",
) -> None:
    decide_reference(
        project, actor, rex, ordinal, decision, rationale=rationale, quotes=quotes, work_id=work_id
    )


def _decisions(project: Project) -> list[dict[str, Any]]:
    return [e.payload for e in events_of_type(project, "reference.resolution_decided")]


def test_states_before_any_decision(project: Project, extraction: str) -> None:
    assert _item(project, 1).state is LinkState.UNCONFIRMED
    assert _item(project, 2).state is LinkState.AMBIGUOUS
    assert len(_item(project, 2).candidates) == 2
    assert _item(project, 3).state is LinkState.RESOLVED


def test_entry_text_is_re_derived_and_checked(project: Project, extraction: str) -> None:
    text = entry_text(project, extraction, 1)
    assert text == ENTRIES[0]
    [extracted] = events_of_type(project, "reference.extracted")
    assert extracted.payload["entries"][0]["entry_sha256"] == entry_digest(text)  # type: ignore[index]
    with pytest.raises(FactoryValidationError):
        entry_text(project, extraction, 9)


def test_entry_text_refuses_a_hash_mismatch(project: Project, extraction: str) -> None:
    [extracted] = events_of_type(project, "reference.extracted")
    payload = dict(extracted.payload)
    rex = project.ids.new("rex")
    entries = [dict(e) for e in payload["entries"]]  # type: ignore[union-attr]
    entries[0]["entry_sha256"] = "0" * 64
    payload.update(extraction_id=rex, entries=entries)
    project.record(
        [
            project.events.make(
                "reference.extracted",
                ReferenceExtracted.model_validate(payload),
                project.system_actor(),
            )
        ]
    )
    with pytest.raises(FactoryValidationError) as err:
        entry_text(project, rex, 1)
    assert err.value.issues[0].field == "entry_sha256"
    assert ENTRIES[0] not in str(err.value)


def test_agent_cannot_confirm(project: Project, extraction: str, agent: Actor) -> None:
    for decision in (Decision.CONFIRM, Decision.REJECT):
        with pytest.raises(FactoryValidationError):
            _decide(project, agent, extraction, 1, decision)
    assert _decisions(project) == []


def test_proposal_does_not_change_state_or_create_candidate(
    project: Project, extraction: str, agent: Actor
) -> None:
    before = corpus_works(project)
    counts = reference_counts(project)
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    item = _item(project, 1)
    assert item.state is LinkState.UNCONFIRMED and item.proposal == "propose-confirm"
    assert reference_counts(project) == counts
    assert corpus_works(project) == before
    [event] = events_of_type(project, "reference.resolution_decided")
    assert event.input_blob is not None and event.payload["confirmed_by"] is None
    assert event.payload["quotes"] == [
        {"side": "entry", "text": ENTRY_QUOTE},
        {"side": "candidate", "text": CAND_QUOTE},
    ]
    assert event.payload["work_id"] == item.base_work_id


def test_second_agent_confirm_in_pilot_only(
    project: Project, extraction: str, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = second_agent(agent)
    # no proposal yet: a second agent has nothing to second
    with pytest.raises(FactoryValidationError):
        _decide(project, checker, extraction, 1, Decision.CONFIRM)
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    # the proposer's own session cannot confirm
    with pytest.raises(FactoryValidationError):
        _decide(project, agent, extraction, 1, Decision.CONFIRM)
    with monkeypatch.context() as patch:
        patch.setattr(reference_resolve, "indexed_rigor_mode", lambda _p: RigorMode.SYSTEMATIC)
        with pytest.raises(FactoryValidationError):
            _decide(project, checker, extraction, 1, Decision.CONFIRM)
    _decide(project, checker, extraction, 1, Decision.CONFIRM)
    item = _item(project, 1)
    assert item.state is LinkState.RESOLVED and item.confidence == "confirmed"
    assert _decisions(project)[-1]["confirmed_by"] == "second-agent"


def test_ambiguous_link_refuses_second_agent(
    project: Project, extraction: str, agent: Actor
) -> None:
    work = _item(project, 2).candidates[0][0]
    quotes = ("Moss growth under filtered light", "Moss growth under filtered light")
    _decide(project, agent, extraction, 2, Decision.PROPOSE_CONFIRM, quotes=quotes, work_id=work)
    with pytest.raises(FactoryValidationError):
        _decide(
            project,
            second_agent(agent),
            extraction,
            2,
            Decision.CONFIRM,
            quotes=quotes,
            work_id=work,
        )


def test_human_confirms_ambiguous_without_proposal(
    project: Project, extraction: str, human: Actor
) -> None:
    work = _item(project, 2).candidates[1][0]
    quotes = ("Moss growth under filtered light", "Moss growth under filtered light")
    with pytest.raises(FactoryValidationError):  # an ambiguous confirmation names its work
        _decide(project, human, extraction, 2, Decision.CONFIRM, quotes=quotes)
    _decide(project, human, extraction, 2, Decision.CONFIRM, quotes=quotes, work_id=work)
    item = _item(project, 2)
    assert item.state is LinkState.RESOLVED and item.work_id == work
    [event] = events_of_type(project, "reference.resolution_decided")
    assert event.input_blob is None and event.payload["confirmed_by"] == "human"


def test_human_reject_after_confirm_supersedes(
    project: Project, extraction: str, human: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    assert _item(project, 1).state is LinkState.RESOLVED
    _decide(project, human, extraction, 1, Decision.REJECT, rationale="Different venue.")
    item = _item(project, 1)
    assert item.state is LinkState.UNRESOLVED and item.decision == "reject"
    assert reference_counts(project).unresolved == 1


def test_decision_quotes_must_be_verbatim(project: Project, extraction: str, human: Actor) -> None:
    bad = [
        ("Efficient reed transformers v3", CAND_QUOTE),
        (ENTRY_QUOTE, "Efficient Reed Transformers v2"),
        ("", CAND_QUOTE),
        (ENTRY_QUOTE, "Paper 2"),
    ]
    for quotes in bad:
        with pytest.raises(FactoryValidationError):
            _decide(project, human, extraction, 1, Decision.CONFIRM, quotes=quotes)
    assert _decisions(project) == []
    # the candidate's author line is quotable too
    _decide(project, human, extraction, 1, Decision.CONFIRM, quotes=("B. Lee.", "Bo Lee"))


def test_invalid_decisions_write_nothing(project: Project, extraction: str, human: Actor) -> None:
    other = _item(project, 3).work_id
    cases: list[dict[str, Any]] = [
        {"ordinal": 3},  # resolved by identifier: nothing to decide
        {"ordinal": 1, "work_id": other},  # not a candidate of the link
        {"ordinal": 1, "rationale": "   "},
        {"ordinal": 1, "rex": "rex_01HZX3K4M5N6P7Q8R9S0TVWXZ0"},
        {"ordinal": 7},
    ]
    for case in cases:
        with pytest.raises(FactoryValidationError):
            _decide(
                project,
                human,
                case.get("rex", extraction),
                case["ordinal"],
                Decision.CONFIRM,
                work_id=case.get("work_id"),
                rationale=case.get("rationale", "Same."),
            )
    assert _decisions(project) == []


def test_decision_on_superseded_extraction_refused(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    from tests.document_helpers import StubConverter, make_registry, run_convert

    run_convert(project, make_registry(StubConverter(version="2.0+stub")))
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    extract_references(project, agent, None, sources=lookups.sources())
    with pytest.raises(FactoryValidationError):
        _decide(project, human, extraction, 1, Decision.CONFIRM)


def test_agent_binding_decision_refused_after_human_decision(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    _decide(project, agent, extraction, 1, Decision.PROPOSE_REJECT)
    for decision in (Decision.REJECT, Decision.CONFIRM):
        with pytest.raises(FactoryValidationError):
            _decide(project, second_agent(agent), extraction, 1, decision)
    item = _item(project, 1)
    assert item.state is LinkState.RESOLVED and item.confirmed_by == "human"


def test_any_earlier_proposal_of_the_session_blocks_its_confirmation(
    project: Project, extraction: str, agent: Actor
) -> None:
    checker = second_agent(agent)
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, checker, extraction, 1, Decision.PROPOSE_CONFIRM)
    with pytest.raises(FactoryValidationError):
        _decide(project, agent, extraction, 1, Decision.CONFIRM)
    assert _item(project, 1).state is LinkState.UNCONFIRMED


# --- Re-extraction (final review 3 and 4) ---


def _reextract(project: Project, agent: Actor, version: str = "2.0+stub") -> str:
    """A genuine re-extraction: a new conversion of the same document, same entry text."""
    run_convert(project, make_registry(StubConverter(version=version)))
    lookups = Lookups(
        openalex=[
            oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501"),
            oa_item("Moss growth under filtered light", "Pia Ostrander", 2008, "W502"),
            oa_item("Moss growth under filtered lights", "Pia Ostrander", 2008, "W503"),
        ]
    )
    [result] = extract_references(project, agent, None, sources=lookups.sources()).extractions
    return result.extraction_id


def test_named_extraction_of_a_current_work_is_refused(
    project: Project, extraction: str, agent: Actor
) -> None:
    work = _item(project, 1).citing_work
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as caught:
        extract_references(project, agent, [work], sources=Lookups().sources())
    assert [i.field for i in caught.value.issues] == ["work_ids"]
    assert work in caught.value.issues[0].reason
    assert event_bytes(project) == before
    assert current_extraction(project, work) == extraction


def test_a_refused_work_stops_the_whole_call(
    project: Project, extraction: str, agent: Actor
) -> None:
    work = _item(project, 1).citing_work
    other = next(w for w in promoted_works(project) if w != work)
    fetched_document(project, other, bib_html(ENTRIES[:1], ["x"]))
    run_convert(project, make_registry())
    before = len(events_of_type(project, "reference.extracted"))
    with pytest.raises(FactoryValidationError):
        extract_references(project, agent, [other, work], sources=Lookups().sources())
    assert len(events_of_type(project, "reference.extracted")) == before


def test_human_confirmation_carries_to_the_new_extraction(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    rex = _reextract(project, agent)
    item = _item(project, 1)
    assert item.extraction_id == rex and item.state is LinkState.RESOLVED
    assert item.confidence == "confirmed" and item.confirmed_by == "human"
    assert item.work_id == item.base_work_id
    [carried] = events_of_type(project, "reference.resolved")[-1].payload["carried"]
    assert carried["from_extraction"] == extraction and carried["decision"] == "confirm"
    assert carried["ordinal"] == 1 and carried["from_ordinal"] == 1


def test_summary_states_count_the_carried_decision(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    run_convert(project, make_registry(StubConverter(version="2.0+stub")))
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    [result] = extract_references(project, agent, None, sources=lookups.sources()).extractions
    assert result.states[LinkState.UNCONFIRMED] == 0
    assert result.states[LinkState.RESOLVED] == 2


def test_human_rejection_carries_and_an_agent_cannot_reopen_it(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    """The review's scenario, on a genuine re-extraction."""
    _decide(project, human, extraction, 1, Decision.REJECT)
    rex = _reextract(project, agent)
    item = _item(project, 1)
    assert item.state is LinkState.UNRESOLVED and item.work_id is None
    assert item.decision == "reject" and item.confirmed_by == "human"
    _decide(project, agent, rex, 1, Decision.PROPOSE_CONFIRM)
    with pytest.raises(FactoryValidationError):
        _decide(project, second_agent(agent), rex, 1, Decision.CONFIRM)
    assert _item(project, 1).state is LinkState.UNRESOLVED


def test_a_carried_decision_survives_a_second_extraction_and_a_rebuild(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    _reextract(project, agent)
    _reextract(project, agent, "3.0+stub")
    assert _item(project, 1).confirmed_by == "human"
    before = project.index.rebuild()
    assert project.index.rebuild() == before
    assert _item(project, 1).confirmed_by == "human"


def test_the_human_can_change_a_carried_decision(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    rex = _reextract(project, agent)
    _decide(project, human, rex, 1, Decision.REJECT)
    assert _item(project, 1).state is LinkState.UNRESOLVED


def test_an_agent_decision_does_not_carry(project: Project, extraction: str, agent: Actor) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), extraction, 1, Decision.CONFIRM)
    assert _item(project, 1).confirmed_by == "second-agent"
    _reextract(project, agent)
    item = _item(project, 1)
    assert item.state is LinkState.UNCONFIRMED
    assert item.decision is None and item.proposal is None


def test_a_session_that_proposed_on_an_earlier_extraction_cannot_confirm(
    project: Project, extraction: str, agent: Actor
) -> None:
    """Sessions are judged per entry across the work's extractions, by `entry_sha256`."""
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    rex = _reextract(project, agent)
    third = second_agent(agent).model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W2A"})
    _decide(project, third, rex, 1, Decision.PROPOSE_CONFIRM)
    with pytest.raises(FactoryValidationError) as caught:
        _decide(project, agent, rex, 1, Decision.CONFIRM)
    assert "proposed or decided" in caught.value.issues[0].reason
    _decide(project, second_agent(agent), rex, 1, Decision.CONFIRM)
    assert _item(project, 1).confirmed_by == "second-agent"


def test_a_lost_human_decision_is_a_finding_naming_the_extraction(
    project: Project,
    extraction: str,
    human: Actor,
    agent: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entry's text differs in the new conversion, so its decision cannot follow it."""
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    _decide(project, human, extraction, 2, Decision.REJECT, quotes=MOSS_QUOTES)
    assert "references-decision-lost" not in _codes(project, RigorMode.SYSTEMATIC)
    real = references_service.entry_digest
    monkeypatch.setattr(
        references_service,
        "entry_digest",
        lambda raw: real(raw + " changed") if "Efficient reed" in raw else real(raw),
    )
    rex = _reextract(project, agent)
    assert _item(project, 1).decision is None
    assert _item(project, 2).decision == "reject"
    [finding] = [
        f
        for f in _findings_as(project, RigorMode.SYSTEMATIC)
        if f.code == "references-decision-lost"
    ]
    assert finding.refs == [rex] or tuple(finding.refs) == (rex,)
    assert finding.message.startswith("1 ")
    assert LEVELS["references-decision-lost"] == ("warning", "warning", "error")


def _codes(project: Project, mode: RigorMode) -> set[str]:
    return {f.code for f in _findings_as(project, mode)}


# --- Clearing a human decision (re-review 2) ---


def _reextract_nothing_found(project: Project, agent: Actor, version: str) -> str:
    """A re-extraction whose lookups return nothing: the link's base is unresolved."""
    run_convert(project, make_registry(StubConverter(version=version)))
    summary = extract_references(project, agent, None, sources=Lookups().sources())
    return summary.extractions[0].extraction_id


def _clear(project: Project, actor: Actor, rex: str, ordinal: int = 1) -> None:
    decide_reference(
        project, actor, rex, ordinal, Decision.CLEAR, rationale="Decided in error.", quotes=("", "")
    )


def test_a_human_clears_a_carried_confirmation_on_an_unresolved_base(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    """The reviewer's case: the lookup returned nothing, so the link has no candidate at all."""
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    rex = _reextract_nothing_found(project, agent, "2.0+stub")
    item = _item(project, 1)
    assert item.base_state is LinkState.UNRESOLVED and item.candidates == []
    assert item.state is LinkState.RESOLVED and item.confirmed_by == "human"
    before = len(_decisions(project))
    _clear(project, human, rex)
    assert len(_decisions(project)) == before + 1
    assert _decisions(project)[-1]["decision"] == "clear"
    item = _item(project, 1)
    assert item.state is LinkState.UNRESOLVED and item.work_id is None
    assert item.decision is None and item.confirmed_by is None
    _reextract_nothing_found(project, agent, "3.0+stub")
    assert events_of_type(project, "reference.resolved")[-1].payload["carried"] == []
    assert _item(project, 1).decision is None
    assert project.index.rebuild() == project.index.rebuild()
    assert _item(project, 1).decision is None


def test_a_cleared_rejection_restores_the_recorded_link(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.REJECT)
    rex = _reextract(project, agent)
    _clear(project, human, rex)
    item = _item(project, 1)
    assert item.state is LinkState.UNCONFIRMED and item.work_id == item.base_work_id
    _reextract(project, agent, "3.0+stub")
    assert _item(project, 1).state is LinkState.UNCONFIRMED


def test_a_cleared_decision_is_not_reported_lost(
    project: Project,
    extraction: str,
    human: Actor,
    agent: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    rex = _reextract(project, agent)
    _clear(project, human, rex)
    real = references_service.entry_digest
    monkeypatch.setattr(
        references_service,
        "entry_digest",
        lambda raw: real(raw + " changed") if "Efficient reed" in raw else real(raw),
    )
    _reextract(project, agent, "3.0+stub")
    assert "references-decision-lost" not in _codes(project, RigorMode.SYSTEMATIC)


def test_only_a_human_clears_and_only_a_human_decision(
    project: Project, extraction: str, human: Actor, agent: Actor
) -> None:
    with pytest.raises(FactoryValidationError):
        _clear(project, human, extraction)  # nothing to clear
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError):
        _clear(project, agent, extraction)
    assert event_bytes(project) == before
