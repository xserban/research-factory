"""R-20 (fix round 2): held-out seeds are matched to corpus works by DOI or arXiv id, as
`seed_check` does, and the agent export hides every such work and its merge group."""

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services import seeds as seeds_module
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.exports import held_out_work_ids, select_works
from factory.services.search import get_work
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import open_session
from tests.test_chase_service import _corpus, _settle
from tests.test_prisma import _merge_items

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _held(project: Project) -> Any:
    [held] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    return held


def _unresolved(monkeypatch: pytest.MonkeyPatch, **spec: Any) -> None:
    """Seeds as the lookup left them unresolved: no work id, no admission; `spec` overrides."""
    original = seeds_module._load_seeds

    def load(project: Project) -> Any:
        return [
            s.model_copy(update={"work_id": None, "spec": s.spec.model_copy(update=spec)})
            for s in original(project)
        ]

    monkeypatch.setattr(seeds_module, "_load_seeds", load)
    monkeypatch.setattr(seeds_module, "_admitted", lambda project: {})


@pytest.mark.anyio
async def test_doi_only_held_out_seed_is_hidden(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    held = _held(project)
    assert held.work_id is not None
    target = held.work_id
    everyone = select_works(project, "corpus")
    _unresolved(monkeypatch)
    assert held_out_work_ids(project) == {target}
    async with open_session(settings, clock) as session:
        body = await session.call("export_bibliography", project="demo", scope="corpus")
        named = await session.call("export_bibliography", project="demo", ids=[target])
    assert body["data"]["count"] == len(everyone) - 1
    work = get_work(project, target)
    assert work is not None and work.title not in body["data"]["text"]
    assert named["ok"] is False and named["errors"][0]["field"] == "ids"


def test_arxiv_only_held_out_seed_is_matched(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(project, agent, human, mock_sources)
    held = _held(project)
    target = held.work_id
    _unresolved(monkeypatch, doi=None, arxiv="2001.00001")
    original = seeds_module.list_works

    def with_arxiv(p: Project) -> Any:
        return [
            w.model_copy(
                update={"identifiers": w.identifiers.model_copy(update={"arxiv": "2001.00001"})}
            )
            if w.id == target
            else w
            for w in original(p)
        ]

    monkeypatch.setattr(seeds_module, "list_works", with_arxiv)
    assert held_out_work_ids(project) == {target}


def test_merge_group_hidden_when_only_a_member_is_held_out(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _corpus(project, agent, human, mock_sources, extra=_merge_items())
    dedup_run(project)
    [merge] = active_merges(project)
    member = merge.absorbed[0]
    hidden = seeds_module.merge_closure(project, frozenset({member}))
    assert hidden == {merge.primary, *merge.absorbed}
    kept = select_works(project, "corpus", exclude_work_ids=hidden)
    assert not hidden & set(kept)
