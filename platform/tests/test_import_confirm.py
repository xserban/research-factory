"""Confirmation of fuzzy and ambiguous import matches under the slice-3a policy (Import-B task 2).

Every record and work is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.references import Decision, LinkState
from factory.services import import_resolve
from factory.services.context import Project
from factory.services.import_resolve import decide_import, record_states, resolve_import
from tests.document_helpers import events_of_type
from tests.import_helpers import bib_entry, import_bib
from tests.references_service_helpers import Lookups, oa_item, second_agent

WHY = "Same paper; the export adds a version suffix."


@pytest.fixture
def imported(project: Project, corpus: None, tmp_path: Path) -> str:
    """An import with a fuzzy record (1), an ambiguous one (2) and an identifier one (3)."""
    lookups = Lookups(
        openalex=[
            oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501"),
            oa_item("Moss growth under filtered light", "Pia Ostrander", 2008, "W502"),
            oa_item("Moss growth under filtered lights", "Pia Ostrander", 2008, "W503"),
            oa_item("Sedge Mapping Methods", "Ana Kim", 2015, "W504", doi="10.9999/sedge.1"),
        ]
    )
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo"),
            bib_entry("b", "Moss growth under filtered light v2", year=2008, author="Ostrander, P"),
            bib_entry(
                "c", "Sedge Mapping Methods", year=2015, author="Kim, A", doi="10.9999/sedge.1"
            ),
        ],
    )
    resolve_import(project, imp, sources=lookups.sources())
    assert record_states(project, imp) == {
        1: LinkState.UNCONFIRMED,
        2: LinkState.AMBIGUOUS,
        3: LinkState.RESOLVED,
    }
    return imp


def _decided(project: Project) -> list[dict[str, object]]:
    return [dict(e.payload) for e in events_of_type(project, "import.resolution_decided")]


def _states(project: Project, imp: str) -> dict[int, LinkState]:
    return record_states(project, imp)


def _row(project: Project, imp: str, ordinal: int) -> tuple[str | None, str | None, str | None]:
    from sqlalchemy import text

    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT work_id, confidence, confirmed_by FROM import_records "
                "WHERE import_id = :i AND ordinal = :o"
            ),
            {"i": imp, "o": ordinal},
        ).one()
    return (row[0], row[1], row[2])


def test_human_confirms_fuzzy(project: Project, imported: str, human: Actor) -> None:
    decide_import(project, human, imported, 1, Decision.CONFIRM, rationale=WHY)
    assert _states(project, imported)[1] is LinkState.RESOLVED
    work, confidence, by = _row(project, imported, 1)
    assert work is not None and confidence == "confirmed" and by == "human"
    [payload] = _decided(project)
    assert payload["quotes"] == ["Efficient Reed Transformers v2", "Efficient Reed Transformers"]
    assert payload["confirmed_by"] == "human" and payload["work_id"] == work


def test_agent_cannot_confirm_in_systematic(
    project: Project, imported: str, agent: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    decide_import(project, agent, imported, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    monkeypatch.setattr(import_resolve, "_rigor_mode", lambda _p: RigorMode.SYSTEMATIC)
    before = len(_decided(project))
    with pytest.raises(FactoryValidationError):
        decide_import(project, second_agent(agent), imported, 1, Decision.CONFIRM, rationale=WHY)
    assert len(_decided(project)) == before
    assert _states(project, imported)[1] is LinkState.UNCONFIRMED


def test_agent_alone_cannot_confirm_in_pilot(project: Project, imported: str, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        decide_import(project, agent, imported, 1, Decision.CONFIRM, rationale=WHY)
    assert "proposal" in str(err.value)
    assert _decided(project) == []


def test_second_agent_may_confirm_in_pilot(
    project: Project, imported: str, agent: Actor, agent_other: Actor
) -> None:
    decide_import(project, agent_other, imported, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    assert _states(project, imported)[1] is LinkState.UNCONFIRMED  # a proposal changes nothing
    decide_import(project, second_agent(agent), imported, 1, Decision.CONFIRM, rationale=WHY)
    assert _states(project, imported)[1] is LinkState.RESOLVED
    assert _row(project, imported, 1)[2] == "second-agent"
    assert _decided(project)[-1]["confirmed_by"] == "second-agent"


def test_proposing_session_cannot_confirm(project: Project, imported: str, agent: Actor) -> None:
    decide_import(project, agent, imported, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    with pytest.raises(FactoryValidationError):
        decide_import(project, agent, imported, 1, Decision.CONFIRM, rationale=WHY)


def test_resolving_session_cannot_confirm(
    project: Project, corpus: None, tmp_path: Path, agent: Actor, agent_other: Actor
) -> None:
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo")],
    )
    resolve_import(project, imp, sources=lookups.sources(), actor=agent)
    decide_import(project, agent_other, imp, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    with pytest.raises(FactoryValidationError) as err:
        decide_import(project, agent, imp, 1, Decision.CONFIRM, rationale=WHY)
    assert "session" in str(err.value)
    assert _states(project, imp)[1] is LinkState.UNCONFIRMED


def test_human_decision_is_final_for_agents(
    project: Project, imported: str, human: Actor, agent_other: Actor, agent: Actor
) -> None:
    decide_import(project, agent_other, imported, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    decide_import(project, human, imported, 1, Decision.REJECT, rationale=WHY)
    with pytest.raises(FactoryValidationError):
        decide_import(project, second_agent(agent), imported, 1, Decision.CONFIRM, rationale=WHY)


def test_ambiguous_needs_named_candidate(project: Project, imported: str, human: Actor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        decide_import(project, human, imported, 2, Decision.CONFIRM, rationale=WHY)
    assert err.value.issues[0].field == "work_id"
    with pytest.raises(FactoryValidationError):
        decide_import(
            project, human, imported, 2, Decision.CONFIRM, rationale=WHY, work_id="rf:nope-x-1"
        )
    assert _decided(project) == []
    with project.index.connect() as conn:
        from sqlalchemy import text

        candidates = conn.execute(
            text("SELECT candidates FROM import_records WHERE import_id = :i AND ordinal = 2"),
            {"i": imported},
        ).scalar_one()
    import json

    chosen = json.loads(candidates)[0]["work_id"]
    decide_import(project, human, imported, 2, Decision.CONFIRM, rationale=WHY, work_id=chosen)
    assert _states(project, imported)[2] is LinkState.RESOLVED
    assert _row(project, imported, 2)[0] == chosen


def test_only_unconfirmed_or_ambiguous_are_decided(
    project: Project, imported: str, human: Actor
) -> None:
    with pytest.raises(FactoryValidationError):
        decide_import(project, human, imported, 3, Decision.CONFIRM, rationale=WHY)
    with pytest.raises(FactoryValidationError):
        decide_import(project, human, imported, 9, Decision.REJECT, rationale=WHY)
    with pytest.raises(FactoryValidationError):
        decide_import(project, human, imported, 1, Decision.REJECT, rationale=" ")
    assert _decided(project) == []


def test_reject_supersedes_confirm(project: Project, imported: str, human: Actor) -> None:
    decide_import(project, human, imported, 1, Decision.CONFIRM, rationale=WHY)
    decide_import(project, human, imported, 1, Decision.REJECT, rationale="Different paper.")
    assert _states(project, imported)[1] is LinkState.UNRESOLVED
    before = project.index.state_hash()
    assert project.index.rebuild() == before


def test_reresolve_discards_decisions_in_the_live_view(
    project: Project, imported: str, human: Actor
) -> None:
    decide_import(project, human, imported, 1, Decision.CONFIRM, rationale=WHY)
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    resolve_import(project, imported, sources=lookups.sources())
    assert _states(project, imported)[1] is LinkState.UNCONFIRMED
    assert len(_decided(project)) == 1  # the event stays; only the live view starts again


def test_agent_decision_keeps_its_input_blob(project: Project, imported: str, agent: Actor) -> None:
    decide_import(project, agent, imported, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    [event] = events_of_type(project, "import.resolution_decided")
    assert event.input_blob is not None
