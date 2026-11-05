"""Decision 81 (restores 37 item 9). Once a pass is open, the agent bibliography shows a held-out
seed's work as any corpus work, whether the seed was admitted or only matched by search. Seed ids
and the identifiers a seed states stay withheld, so the work's own `doi` field reads `[withheld]`:
the residual marking of decisions 78 and 81, pinned here so that it is not lost. Before a pass the
tool is refused for every project, since that marker would name the seed during query design."""

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.exports.keys import bib_key
from factory.mcp.conventions import WITHHELD
from factory.model.screening import PassLabel
from factory.services import seeds as seeds_module
from factory.services.context import Project
from factory.services.exports import export_bibliography, select_works
from factory.services.screening import open_pass
from factory.services.search import get_work
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import _leaks, _setup, open_session
from tests.screening_helpers import _corpus, _draw, _settle

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _held(project: Project) -> Any:
    [held] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    return held


def _matched_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeds as a search left them: matched by DOI, no work id, no admission."""
    original = seeds_module._load_seeds

    def load(project: Project) -> Any:
        return [s.model_copy(update={"work_id": None}) for s in original(project)]

    monkeypatch.setattr(seeds_module, "_load_seeds", load)
    monkeypatch.setattr(seeds_module, "_admitted", lambda project: {})


def _fields(entry: str) -> list[str]:
    """The field names of one BibTeX entry, in order."""
    return [line.split("=")[0].strip() for line in entry.splitlines() if "=" in line]


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["admitted", "matched-by-search"])
async def test_mcp_export_shows_a_held_out_work_as_any_work(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    held = _held(project)
    target = str(held.work_id)
    work = get_work(project, target)
    assert work is not None
    if route == "matched-by-search":
        _matched_only(monkeypatch)
    everyone = select_works(project, "corpus")
    assert target in everyone
    async with open_session(settings, clock) as session:
        body = await session.call("export_bibliography", project="demo", scope="corpus")
        named = await session.call("export_bibliography", project="demo", ids=[target])
    text = body["data"]["text"]
    assert body["data"]["count"] == len(everyone) == text.count("@")
    assert work.title in text and bib_key(target) in text
    assert named["ok"] is True and work.title in named["data"]["text"]
    assert _leaks(text, {held.seed_id, str(held.doi)}) == []
    entries = {e.split("{", 1)[1].split(",", 1)[0]: e for e in text.split("@")[1:]}
    own = entries.pop(bib_key(target))
    ordinary = next(e for e in entries.values() if "doi" in e)
    assert _fields(own) == _fields(ordinary)
    assert WITHHELD in own  # the stated identifier: decisions 37 item 9 and 78


@pytest.mark.anyio
async def test_mcp_export_is_refused_until_a_pass_opens(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    held = _held(project)
    async with open_session(settings, clock) as session:
        body = await session.call("export_bibliography", project="demo", scope="corpus")
        named = await session.call("export_bibliography", project="demo", ids=[held.work_id])
        unknown = await session.call("export_bibliography", project="demo", ids=["rf:nope-0"])
    assert body["ok"] is False and body == named == unknown  # one message, whatever is asked
    assert [e["field"] for e in body["errors"]] == ["project"]
    assert WITHHELD not in str(body)
    assert "".join(export_bibliography(project, "bibtex", scope="corpus"))  # the CLI's service
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    async with open_session(settings, clock) as session:
        opened = await session.call("export_bibliography", project="demo", scope="corpus")
    assert opened["ok"] is True, opened


@pytest.mark.anyio
async def test_the_pre_pass_refusal_does_not_depend_on_seeds(
    settings: Settings,
    explore_project: Project,
    clock: FixedClock,
) -> None:
    """A project with no seeds at all is refused in the same words."""
    assert all_seeds(explore_project) == []
    async with open_session(settings, clock) as session:
        body = await session.call("export_bibliography", project="demo")
    assert body["ok"] is False and [e["field"] for e in body["errors"]] == ["project"]
    reason = body["errors"][0]["reason"].lower()
    assert "seed" not in reason and "held" not in reason
