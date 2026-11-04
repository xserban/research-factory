"""Supplied works in screening and seed recall (slice 4a rulings 8, 9; acceptance 7, 8, 10)."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.index.chase import considered_works
from factory.model.inbox import ResolveStatus
from factory.model.screening import PassLabel
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedMissExplained, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.check import check
from factory.services.context import Project
from factory.services.protocol import record_deviation
from factory.services.screening import open_pass, screen_next
from factory.services.search import register_query, run_query
from factory.services.seeds import (
    add_seeds,
    admit_seed,
    explain_seed_miss,
    seed_check,
    seed_recall,
    split_seeds,
)
from factory.services.tasks import complete_task
from tests.helpers import SourcesFor, _seed_item, _setup
from tests.inbox_helpers import Keyed, capture, link_item, resolve
from tests.test_screening_next import _draw

NOTE = "Ana says this one is central"


def _supply_after_setup(
    project: Project, human: Actor, n: int = 1, *, note: str | None = NOTE
) -> str:
    """Capture and resolve one new supplied work under a deviation; return its work id."""
    capture(project, human, f"10.2000/s{n}", note=note)
    deviation = record_deviation(project, human, description="Supplied link", reason="Colleague.")
    keyed = Keyed(openalex={f"doi:10.2000/s{n}": [link_item(n)]})
    [outcome] = resolve(project, human, keyed, deviation_id=deviation)
    assert outcome.status is ResolveStatus.NEW and outcome.work_id is not None
    return outcome.work_id


def test_screen_task_is_route_blind(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    """Review Focus 1. Passes at once by construction (records carry only id, title and
    abstract); kept as a guard against any route reaching task content."""
    _setup(project, agent, human, mock_sources, random_works=0)
    supplied = _supply_after_setup(project, other_session_human)
    _draw(project)

    records: dict[str, dict[str, str | None]] = {}
    served: list[str] = []
    for _ in range(30):
        result = screen_next(project, agent, PassLabel.A)
        if result.batch is None:
            break
        served.append(result.batch.model_dump_json())
        records.update({str(r["work_id"]): r for r in result.batch.records})
        complete_task(project, agent, result.batch.task_id)
    assert supplied in records
    database = next(w for w in records if w != supplied)
    assert set(records[supplied]) == set(records[database])
    for text in served:
        assert NOTE not in text
        assert "supplied" not in text
        assert "inb_" not in text


def test_supplied_work_enters_pass_b_extension(
    project: Project,
    agent: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5)
    _draw(project)
    open_pass(project, agent, PassLabel.B)
    supplied = _supply_after_setup(project, other_session_human)

    screen_next(project, agent, PassLabel.B)

    with project.index.connect() as conn:
        assert supplied in considered_works(conn)


# --- Seed recall (ruling 9, acceptance 10) ---


def _seeded(project: Project, human: Actor, mock_sources: SourcesFor) -> tuple[str, list[str]]:
    """Three positive seeds (papers 1-3), split; returns the held-out seed and the others' n."""
    for n in (1, 2, 3):
        spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
        add_seeds(project, human, [spec], sources=mock_sources(openalex=[_seed_item(n)]))
    split = split_seeds(project, random_seed=7)
    [held_out] = split.held_out
    return held_out, split.development


def _search(project: Project, human: Actor, mock_sources: SourcesFor, *ns: int) -> None:
    sources = mock_sources(openalex=[_seed_item(n) for n in ns])
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)


def _n(seed_id: str) -> int:
    return int(seed_id.removeprefix("SEED"))


def _supply_seed(project: Project, human: Actor, n: int) -> ResolveStatus | None:
    capture(project, human, f"10.1000/p{n}")
    [outcome] = resolve(project, human, Keyed(openalex={f"doi:10.1000/p{n}": [_seed_item(n)]}))
    return outcome.status


def test_supplied_seed_is_not_retrieved(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    held_out, development = _seeded(project, human, mock_sources)
    _search(project, human, mock_sources, *(_n(s) for s in development))
    assert seed_recall(project).held_out == 0.0
    _supply_seed(project, human, _n(held_out))

    checks = {c.seed_id: c for c in seed_check(project)}
    assert checks[held_out].status == "supplied"
    assert checks[held_out].found_by_search is False
    assert {checks[s].status for s in development} == {"retrieved"}
    recall = seed_recall(project)
    assert (recall.held_out, recall.development) == (0.0, 1.0)
    assert recall.held_out_admitted == 0
    # `check` counts the supplied-only seed as a miss, under its role.
    missing = [f for f in check(project).findings if f.code == "seed-missing"]
    assert [(f.role, f.refs) for f in missing] == [("held-out", [held_out])]


def test_seed_found_by_search_and_link_stays_retrieved(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    project = explore_project
    held_out, _development = _seeded(project, human, mock_sources)
    _search(project, human, mock_sources, 1, 2, 3)
    assert _supply_seed(project, human, _n(held_out)) is ResolveStatus.IN_CORPUS

    check = next(c for c in seed_check(project) if c.seed_id == held_out)
    assert (check.status, check.found_by_search) == ("retrieved", True)
    assert seed_recall(project).held_out == 1.0


def test_admitted_seed_is_retrieved_characterisation(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    """Pins today's behaviour: an admitted seed is `retrieved` (not a search find, so recall
    excludes it). Spec ruling 9 leaves open whether it should read differently; unchanged here."""
    project = explore_project
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi="10.1000/p7")
    [outcome] = add_seeds(project, human, [spec], sources=mock_sources()).written
    route = ProvenanceMethod.SEED_ADMISSION
    explain_seed_miss(project, human, outcome.seed_id, "not indexed", route)
    admit_seed(project, human, outcome.seed_id, sources=mock_sources(openalex=[_seed_item(7)]))
    check = next(c for c in seed_check(project) if c.seed_id == outcome.seed_id)
    assert (check.status, check.found_by_search) == ("retrieved", False)


def test_supplied_is_not_a_seed_miss_route(
    explore_project: Project, human: Actor, mock_sources: SourcesFor
) -> None:
    """Controller ruling: a search miss is remedied by admission, not by a supplied link."""
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi="10.1000/p7")
    [outcome] = add_seeds(explore_project, human, [spec], sources=mock_sources()).written
    with pytest.raises(FactoryValidationError) as caught:
        explain_seed_miss(
            explore_project, human, outcome.seed_id, "linked", ProvenanceMethod.SUPPLIED
        )
    assert caught.value.issues[0].field == "route"
    with pytest.raises(ValueError):
        SeedMissExplained(seed_id="SEED01", reason="x", route=ProvenanceMethod.SUPPLIED)
