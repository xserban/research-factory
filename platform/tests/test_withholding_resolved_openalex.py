"""IDEA-19: seed tools also withhold the OpenAlex id a held-out seed resolved to."""

from __future__ import annotations

import pytest

from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.seed import SeedKind, SeedSpec, normalize_openalex
from factory.services import seeds as seeds_service
from factory.services.context import Project
from factory.services.seeds import SeedRecord, SeedRole, add_seeds, all_seeds, split_seeds
from factory.services.withholding import held_out_tokens
from tests.helpers import SourcesFor, bind_ids, openalex_item


def _seed_six(project: Project, agent: Actor, mock_sources: SourcesFor) -> None:
    for n in range(1, 7):
        add_seeds(
            project,
            agent,
            [SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")],
            sources=mock_sources(
                openalex=[
                    openalex_item(
                        title=f"Paper {n}",
                        author="Ada Zhou",
                        published="2020-01-01",
                        openalex_id=f"W{n}",
                        doi=f"10.1000/p{n}",
                    )
                ]
            ),
            decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
        )
    split_seeds(project, random_seed=7)


def _ids(project: Project, role: SeedRole) -> list[tuple[SeedRecord, str]]:
    n = [
        (s, f"W{int(s.seed_id.removeprefix('SEED'))}") for s in all_seeds(project) if s.role is role
    ]
    assert n
    return n


def test_resolved_openalex_id_only_with_work_ids(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _seed_six(project, agent, mock_sources)
    with_ids = {t.lower() for t in held_out_tokens(project, include_work_ids=True)}
    without = {t.lower() for t in held_out_tokens(project, include_work_ids=False)}
    for seed, oa in _ids(project, SeedRole.HELD_OUT):
        assert seed.openalex is None  # stated by DOI only
        assert normalize_openalex(oa).lower() in with_ids
        assert normalize_openalex(oa).lower() not in without
    for _seed, oa in _ids(project, SeedRole.DEVELOPMENT):
        assert normalize_openalex(oa).lower() not in with_ids


def test_held_out_seed_without_work_adds_nothing(
    project: Project,
    agent: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_six(project, agent, mock_sources)
    full = held_out_tokens(project, include_work_ids=True)
    records = [s.model_copy(update={"work_id": None}) for s in all_seeds(project)]
    monkeypatch.setattr(seeds_service, "all_seeds", lambda _p: records)
    bare = held_out_tokens(project, include_work_ids=True)
    assert bare < full
    for _seed, oa in _ids(project, SeedRole.HELD_OUT):
        assert normalize_openalex(oa).lower() not in {t.lower() for t in bare}
