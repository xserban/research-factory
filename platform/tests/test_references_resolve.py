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
from factory.services.context import Project
from factory.services.reference_resolve import decide_reference, entry_digest, entry_text
from factory.services.references import (
    ReferenceItem,
    extract_references,
    list_references,
    reference_counts,
)
from tests.document_helpers import events_of_type
from tests.references_service_helpers import (
    Lookups,
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
    monkeypatch.setattr(reference_resolve, "_rigor_mode", lambda _p: RigorMode.SYSTEMATIC)
    with pytest.raises(FactoryValidationError):
        _decide(project, checker, extraction, 1, Decision.CONFIRM)
    monkeypatch.undo()
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
