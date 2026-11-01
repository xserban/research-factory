"""The hold-out split, the seed views and the post-search seed check (R-20, R-24)."""

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SPLIT_PROCEDURE, SeedKind, SeedMissExplained, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.search import register_query, run_query
from factory.services.seeds import (
    SeedRole,
    add_seeds,
    agent_seeds,
    all_seeds,
    draw_split,
    explain_seed_miss,
    seed_check,
    seed_recall,
    split_seeds,
)
from factory.sources.registry import SourceFactory
from tests.helpers import SESSION, arxiv_atom, openalex_item

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _item(n: int, year: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published=f"{year}-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )


def _resolved(
    project: Project,
    agent: Actor,
    mock_sources: SourcesFor,
    n: int,
    year: int = 2020,
    kind: SeedKind = SeedKind.POSITIVE,
) -> str:
    spec = SeedSpec(kind=kind, cite=f"Paper {n}", doi=f"10.1000/p{n}")
    sources = mock_sources(openalex=[_item(n, year)])
    [outcome] = add_seeds(project, agent, [spec], sources=sources).written
    return outcome.seed_id


def _unresolved(project: Project, agent: Actor, mock_sources: SourcesFor, n: int) -> str:
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Gone {n}", doi=f"10.1000/gone{n}")
    [outcome] = add_seeds(project, agent, [spec], sources=mock_sources()).written
    return outcome.seed_id


def _corpus(project: Project, mock_sources: SourcesFor, items: list[dict[str, Any]]) -> None:
    """Put the given OpenAlex records into the corpus through a non-probe search."""
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=items)
    query_id = register_query(project, project.human_actor(), spec, sources=sources)
    run_query(project, query_id, sources=sources)


def _positives(n: int) -> list[tuple[str, int | None]]:
    return [(f"SEED{i:02d}", 2020) for i in range(1, n + 1)]


# --- Pure split (R-20) ---


def test_split_is_reproducible_from_recorded_seed() -> None:
    seeds = _positives(9)
    assert draw_split(seeds, 7) == draw_split(seeds, 7)


def test_split_holds_out_about_a_third() -> None:
    held = [len(draw_split(_positives(n), 1)[1]) for n in (3, 4, 5, 9)]
    assert held == [1, 1, 2, 3]


def test_split_is_year_stratified() -> None:
    seeds = [
        ("SEED01", 2019),
        ("SEED02", 2019),
        ("SEED03", 2019),
        ("SEED04", 2021),
        ("SEED05", 2021),
        ("SEED06", 2021),
        ("SEED07", 2023),
        ("SEED08", 2023),
        ("SEED09", 2023),
    ]
    development, held_out = draw_split(seeds, 42)
    years = dict(seeds)
    assert sorted(years[seed] for seed in held_out) == [2019, 2021, 2023]
    assert len(development) + len(held_out) == 9
    assert development == sorted(development) and held_out == sorted(held_out)


def test_split_partitions_the_positives() -> None:
    seeds = [("SEED01", None), ("SEED02", 2020), ("SEED03", 2021), ("SEED04", None)]
    development, held_out = draw_split(seeds, 3)
    assert sorted(development + held_out) == ["SEED01", "SEED02", "SEED03", "SEED04"]


# --- Recorded split (service) ---


def test_split_records_seed_and_procedure(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    result = split_seeds(project, random_seed=7)
    assert result.random_seed == 7
    assert sorted(result.development + result.held_out) == ["SEED01", "SEED02", "SEED03"]
    assert len(result.held_out) == 1
    [event] = [e for e in _events(project) if e.type == "seed.split_drawn"]
    assert event.actor.kind == "system"
    assert event.payload["random_seed"] == 7
    assert event.payload["procedure"] == SPLIT_PROCEDURE == "year-stratified-thirds-v1"


def test_default_seed_is_drawn_within_32_bits(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    result = split_seeds(project)
    assert 0 <= result.random_seed < 2**32


def test_split_requires_resolved_positives(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    _unresolved(project, agent, mock_sources, 9)
    with pytest.raises(FactoryValidationError) as caught:
        split_seeds(project, random_seed=1)
    assert [issue.field for issue in caught.value.issues] == ["seeds"]
    assert not any(e.type == "seed.split_drawn" for e in _events(project))


def test_split_needs_three_positives_in_pilot_five_in_systematic(
    settings: Settings, clock: FixedClock, agent: Actor, mock_sources: SourcesFor
) -> None:
    pilot = init_project(settings, "pilot-one", "pilot", session=SESSION, clock=clock)
    for n in range(1, 3):
        _resolved(pilot, agent, mock_sources, n)
    with pytest.raises(FactoryValidationError) as too_few:
        split_seeds(pilot, random_seed=1)
    assert [issue.field for issue in too_few.value.issues] == ["seeds"]

    systematic = init_project(settings, "sys-one", "systematic", session=SESSION, clock=clock)
    for n in range(1, 5):
        _resolved(systematic, agent, mock_sources, n)
    with pytest.raises(FactoryValidationError):
        split_seeds(systematic, random_seed=1)
    _resolved(systematic, agent, mock_sources, 5)
    assert len(split_seeds(systematic, random_seed=1).development) >= 1


def test_split_drawn_once(project: Project, agent: Actor, mock_sources: SourcesFor) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    split_seeds(project, random_seed=1)
    with pytest.raises(FactoryValidationError) as caught:
        split_seeds(project, random_seed=2)
    assert [issue.field for issue in caught.value.issues] == ["split"]


def test_split_rejects_a_seed_outside_32_bits(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    with pytest.raises(FactoryValidationError) as caught:
        split_seeds(project, random_seed=2**32)
    assert [issue.field for issue in caught.value.issues] == ["random_seed"]
    assert not any(e.type == "seed.split_drawn" for e in _events(project))


# --- Views (R-20: held-out seeds never reach the agent) ---


def test_agent_view_never_contains_held_out(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    _resolved(project, agent, mock_sources, 8, kind=SeedKind.NEGATIVE)
    before = {view.seed_id for view in agent_seeds(project)}
    assert before == {"SEED01", "SEED02", "SEED03", "NEG01"}
    result = split_seeds(project, random_seed=5)
    after = {view.seed_id for view in agent_seeds(project)}
    assert after == set(result.development) | {"NEG01"}
    assert not after & set(result.held_out)
    roles = {record.seed_id: record.role for record in all_seeds(project)}
    for seed_id in result.held_out:
        assert roles[seed_id] is SeedRole.HELD_OUT
    for seed_id in result.development:
        assert roles[seed_id] is SeedRole.DEVELOPMENT
    assert roles["NEG01"] is SeedRole.UNSPLIT


def test_late_positive_is_development_and_flagged(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    result = split_seeds(project, random_seed=5)
    late = _resolved(project, agent, mock_sources, 7)
    views = {view.seed_id: view for view in agent_seeds(project)}
    assert views[late].late is True
    assert all(not views[seed].late for seed in result.development)
    roles = {record.seed_id: record.role for record in all_seeds(project)}
    assert roles[late] is SeedRole.LATE
    assert late not in result.held_out


def test_agent_view_before_split_shows_all_seeds_unflagged(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _resolved(project, agent, mock_sources, 1)
    _unresolved(project, agent, mock_sources, 2)
    views = agent_seeds(project)
    assert [(v.seed_id, v.late, v.work_id is None) for v in views] == [
        ("SEED01", False, False),
        ("SEED02", False, True),
    ]
    assert {record.role for record in all_seeds(project)} == {SeedRole.UNSPLIT}


# --- Seed check and recall (R-24) ---


def test_seed_check_retrieved_explained_missing(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in (1, 2, 3):
        _resolved(project, agent, mock_sources, n)
    _corpus(project, mock_sources, [_item(1, 2020)])
    explain_seed_miss(project, agent, "SEED02", "behind a paywall", ProvenanceMethod.HAND_SEARCH)
    checks = {check.seed_id: check for check in seed_check(project)}
    assert checks["SEED01"].status == "retrieved"
    assert checks["SEED01"].matched_work is not None
    assert checks["SEED02"].status == "explained"
    assert checks["SEED02"].matched_work is None
    assert checks["SEED03"].status == "missing"
    assert len(checks) == 3


def test_seed_check_matches_a_bridged_identifier(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    body = arxiv_atom([("2301.01234v1", "Preprint title", 2023, "Ada Zhou")])
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Zhou 2023", arxiv="2301.01234")
    sources = mock_sources(arxiv=body)
    add_seeds(project, agent, [spec], sources=sources)
    published = openalex_item(
        title="Published title",
        author="Ada Zhou",
        published="2024-01-01",
        openalex_id="W77",
        doi="https://doi.org/10.48550/arXiv.2301.01234",
    )
    _corpus(project, mock_sources, [published])
    [check] = seed_check(project)
    assert check.status == "retrieved"


def test_explanation_route_cannot_be_database(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in (1, 2, 3):
        _resolved(project, agent, mock_sources, n)
    with pytest.raises(FactoryValidationError) as caught:
        explain_seed_miss(project, agent, "SEED01", "why", ProvenanceMethod.DATABASE)
    assert [issue.field for issue in caught.value.issues] == ["route"]
    with pytest.raises(ValueError):
        SeedMissExplained(seed_id="SEED01", reason="why", route=ProvenanceMethod.DATABASE)


def test_explain_refuses_unknown_and_negative_seeds(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _resolved(project, agent, mock_sources, 1, kind=SeedKind.NEGATIVE)
    with pytest.raises(FactoryValidationError) as caught:
        explain_seed_miss(project, agent, "NEG01", "why", ProvenanceMethod.HAND_SEARCH)
    assert [issue.field for issue in caught.value.issues] == ["seed_id"]
    with pytest.raises(FactoryValidationError):
        explain_seed_miss(project, agent, "SEED99", "why", ProvenanceMethod.HAND_SEARCH)


def test_recall_reported_separately_for_development_and_held_out(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    assert seed_recall(project).development is None
    for n in range(1, 7):
        _resolved(project, agent, mock_sources, n, year=2020 + n % 3)
    assert seed_recall(project).held_out is None
    split_seeds(project, random_seed=11)
    roles = {record.seed_id: record.role for record in all_seeds(project)}
    dev_items = [
        _item(int(seed[4:]), 2020 + int(seed[4:]) % 3)
        for seed, role in roles.items()
        if role is SeedRole.DEVELOPMENT
    ]
    _corpus(project, mock_sources, dev_items)
    recall = seed_recall(project)
    assert recall.development == 1.0
    assert recall.held_out == 0.0


def test_split_projection_rebuild_equals_incremental(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    for n in range(1, 4):
        _resolved(project, agent, mock_sources, n)
    _corpus(project, mock_sources, [_item(1, 2020)])
    split_seeds(project, random_seed=9)
    explain_seed_miss(project, agent, "SEED02", "why", ProvenanceMethod.CITATION_CHASE)
    before = project.index.state_hash()
    assert project.index.rebuild() == before


def _events(project: Project) -> list[Any]:
    return read_all(project.paths.events_dir, project.catalog)
