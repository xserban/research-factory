"""Round yield and the comparison with `search_chase` (slice 3a, acceptance 8, 10, 11).

Every entry and work is invented; the fixtures are those of `test_snowball_round`.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.references import Direction, LinkState
from factory.services.agreement import Outcome, final_outcomes
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.references import list_references
from factory.services.search import list_works
from factory.services.snowball import (
    RoundResult,
    RoundYield,
    round_yield,
    snowball_compare,
    snowball_round,
)
from tests import test_snowball_round as rounds
from tests.references_service_helpers import oa_item
from tests.test_screening_next import _decide
from tests.test_snowball_round import NO_SOURCE, _lookups, _sources

world = rounds.world
planned = rounds.planned

REED = oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")
CHASED = oa_item("Tidal reeds and lattices", "Ines Varga", 2022, "W900")
CITING = oa_item("Reeds revisited", "Cai Wu", 2024, "W901")


def _screen(project: Project, agent: Actor, verdicts: dict[str, str]) -> None:
    current = current_protocol(project)
    assert current is not None
    for work, verdict in verdicts.items():
        criterion = "EX01" if verdict == "exclude" else None
        for label in ("A", "B"):
            _decide(
                project, agent, work, label, "screening", verdict, criterion, current.protocol_id
            )


def _pending(project: Project) -> list[str]:
    return sorted(w for w, o in final_outcomes(project).items() if o is Outcome.PENDING)


def _backward(project: Project, agent: Actor) -> tuple[RoundResult, str]:
    """A recorded backward round; returns it and the work id of the OpenAlex candidate."""
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
    assert result.round_id is not None
    reed = next(c.work_id for c in result.candidates if c.openalex == "W501")
    assert reed is not None
    return result, reed


def _chase_sources(**kw: Any) -> Any:
    return _lookups(**kw).sources()


def _work_of(project: Project, openalex: str) -> str:
    return next(w.id for w in list_works(project) if w.identifiers.openalex == openalex)


# --- Yield ---


def test_yield_counts_new_after_dedup_and_included(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result, reed = _backward(project, agent)
    assert result.round_id is not None
    assert round_yield(project, result.round_id) == RoundYield(
        retrieved=3, new_after_dedup=3, included=None
    )
    others = [w for w in _pending(project) if w != reed]
    _screen(project, agent, {reed: "include"})
    assert round_yield(project, result.round_id).included is None  # two still pending
    _screen(project, agent, dict.fromkeys(others, "exclude"))
    assert round_yield(project, result.round_id) == RoundYield(
        retrieved=3, new_after_dedup=3, included=1
    )
    # a forward round retrieving one corpus work and one new work: one is new after dedup
    forward = snowball_round(
        project,
        agent,
        Direction.FORWARD,
        sources=_chase_sources(citing=[REED, CITING]),
        dry_run=False,
    )
    assert forward.round_id is not None
    retrieved = len(forward.runs) * 2
    assert round_yield(project, forward.round_id) == RoundYield(
        retrieved=retrieved, new_after_dedup=1, included=None
    )
    _screen(project, agent, dict.fromkeys(_pending(project), "include"))
    assert round_yield(project, forward.round_id).included == 1


def test_yield_of_unknown_round_is_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        round_yield(project, "snw_01HZX3K4M5N6P7Q8R9S0TVWXYZ")


# --- Comparison ---


def _document_set(project: Project) -> set[str]:
    page = list_references(project, state=LinkState.RESOLVED, work_id=None, after=0, limit=100)
    return {i.work_id for i in page.items if i.work_id is not None}


def test_compare_lists_one_mechanism_only(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result, reed = _backward(project, agent)
    assert result.round_id is not None
    _screen(project, agent, dict.fromkeys(_pending(project), "include"))
    before = snowball_compare(project, result.round_id)
    assert before.metadata_only == [] and before.both == [] and before.chase_rounds == []
    assert set(before.document_only) == _document_set(project)
    assert {reed, NO_SOURCE} <= set(before.document_only)

    chase = search_chase(
        project,
        agent,
        [ChaseDirection.BACKWARD, ChaseDirection.FORWARD],
        sources=_chase_sources(cited=[REED, CHASED], citing=[CITING]),
    )
    cmp = snowball_compare(project, result.round_id)
    chased = _work_of(project, "W900")
    assert cmp.chase_rounds == [chase.round_id]
    assert cmp.both == [reed]
    assert cmp.metadata_only == [chased]  # forward (`cites:`) runs are left out
    assert cmp.document_only == sorted(_document_set(project) - {reed})
    assert cmp.document_only == sorted(cmp.document_only)


def test_compare_counts_match_tables(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result, _ = _backward(project, agent)
    assert result.round_id is not None
    _screen(project, agent, dict.fromkeys(_pending(project), "include"))
    chase = search_chase(
        project,
        agent,
        [ChaseDirection.BACKWARD],
        sources=_chase_sources(cited=[REED, CHASED]),
    )
    cmp = snowball_compare(project, result.round_id)
    with project.index.connect() as conn:
        (extractions,) = conn.execute(
            text("SELECT extraction_ids FROM snowball_rounds WHERE round_id = :r"),
            {"r": result.round_id},
        ).one()
        document = {
            str(w)
            for (w,) in conn.execute(
                text(
                    "SELECT l.work_id FROM reference_links l, json_each(:x) j "
                    "WHERE l.extraction_id = j.value AND l.state = 'resolved' "
                    "AND l.work_id IS NOT NULL"
                ),
                {"x": extractions},
            ).all()
        }
        metadata = {
            str(w)
            for (w,) in conn.execute(
                text(
                    "SELECT p.work_id FROM provenance p JOIN queries q ON q.query_id = p.query_id "
                    "JOIN events e ON e.type = 'query.registered' "
                    "AND json_extract(e.refs, '$[0]') = q.query_id "
                    "WHERE q.text LIKE 'cited_by:%' AND EXISTS "
                    "(SELECT 1 FROM json_each(e.refs) WHERE json_each.value = :c)"
                ),
                {"c": chase.round_id},
            ).all()
        }
    assert len(cmp.both) == len(document & metadata)
    assert len(cmp.document_only) == len(document - metadata)
    assert len(cmp.metadata_only) == len(metadata - document)
    assert set(cmp.both) | set(cmp.document_only) == document
    assert set(cmp.both) | set(cmp.metadata_only) == metadata


def test_compare_refuses_forward_and_unknown_rounds(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    forward = snowball_round(
        project, agent, Direction.FORWARD, sources=_chase_sources(citing=[CITING]), dry_run=False
    )
    assert forward.round_id is not None
    for round_id in (forward.round_id, "snw_01HZX3K4M5N6P7Q8R9S0TVWXYZ"):
        with pytest.raises(FactoryValidationError) as caught:
            snowball_compare(project, round_id)
        assert [i.field for i in caught.value.issues] == ["round_id"]
