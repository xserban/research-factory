"""Feed tools show a held-out seed's stated identifiers like any paper's (researcher ruling
2026-11-14; decisions 37 item 9, 81 and 123); only the seed's own id stays withheld. Other
tools keep withholding every stated identifier."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.decisions import DecisionLevel
from factory.model.seed import SeedKind, SeedSpec
from factory.services import feed_read as feed_read_service
from factory.services.context import Project
from factory.services.seeds import SeedRole, add_seeds, all_seeds, split_seeds
from factory.services.withholding import WITHHELD, held_out_tokens, seed_id_tokens
from tests.helpers import (
    SourcesFor,
    arxiv_atom,
    bind_ids,
    install_skill,
    open_session,
    openalex_item,
)

AGENT = {"role": "watcher", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _seed_six(project: Project, agent: Actor, mock_sources: SourcesFor) -> None:
    for n in range(1, 7):
        spec = SeedSpec(
            kind=SeedKind.POSITIVE,
            cite=f"Paper {n}",
            doi=f"10.1000/p{n}",
            arxiv=f"2401.0000{n}",
        )
        add_seeds(
            project,
            agent,
            [spec],
            sources=mock_sources(
                openalex=[
                    openalex_item(
                        title=f"Paper {n}",
                        author="Ada Zhou",
                        published="2020-01-01",
                        openalex_id=f"W{n}",
                        doi=f"10.1000/p{n}",
                    )
                ],
                arxiv=arxiv_atom([(f"2401.0000{n}v1", f"Paper {n}", 2020, "Ada Zhou")]),
            ),
            decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
        )
    split_seeds(project, random_seed=7)


def _held(project: Project) -> Any:
    [first, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    return first


def test_seed_id_tokens_are_the_seed_ids_only(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _seed_six(project, agent, mock_sources)
    held = {s.seed_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT}
    assert held
    assert seed_id_tokens(project) == held
    assert seed_id_tokens(project) < held_out_tokens(project, include_work_ids=False)


@pytest.mark.anyio
async def test_feed_tools_show_a_held_out_seeds_identifiers_but_not_its_seed_id(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_six(project, agent, mock_sources)
    held = _held(project)
    payload = {
        "items": [{"title": held.cite, "arxiv": held.arxiv, "doi": held.doi, "n": held.seed_id}]
    }
    fake = SimpleNamespace(model_dump=lambda mode="json": payload)
    monkeypatch.setattr(feed_read_service, "feed_list", lambda *_a, **_k: fake)
    async with open_session(settings, clock) as client:
        listing = await client.call("feed_list", project="demo", **AGENT)
    assert listing["ok"] is True, listing
    [item] = listing["data"]["items"]
    assert item["arxiv"] == held.arxiv and item["doi"] == held.doi
    assert item["n"] == WITHHELD


@pytest.mark.anyio
async def test_a_tool_that_withheld_before_still_withholds(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    install_skill(settings, "rf-screen")
    _seed_six(project, agent, mock_sources)
    held = _held(project)
    tokens = held_out_tokens(project, include_work_ids=False)
    arxiv = held.arxiv
    assert held.doi in tokens and arxiv in tokens
    async with open_session(settings, clock) as client:
        listing = await client.call("seed_list", project="demo", **AGENT)
    assert held.doi not in str(listing) and arxiv not in str(listing), listing
