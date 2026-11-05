"""The `digest_get` and `conclusion_status` MCP tools: agent views, pass sessions refused."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.conclusions import BasisRef
from factory.services.conclusions import register_conclusion
from factory.services.context import Project
from factory.services.snapshots import snapshot
from factory.services.watch import watch_run
from tests.helpers import SourcesFor, open_session
from tests.living_helpers import agree, filler, screening_watch_setup, start_screening
from tests.screening_helpers import _draw
from tests.watch_helpers import ScriptedSource, adapters, by_text

AGENT = {"role": "screener", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
STATEMENT = "A linear mechanism suffices for every dense task."


def _cycle(project: Project, records: list[dict[str, Any]]) -> tuple[str, ...]:
    source = ScriptedSource(by_text({"attention": [records]}))
    summary = watch_run(project, sources=adapters(source), trigger="scheduler")
    assert summary is not None
    return summary.new_work_ids


@pytest.fixture
def living(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    clock: FixedClock,
) -> tuple[Project, str]:
    screening_watch_setup(project, agent, human, mock_sources)
    protocol_id, calibration = start_screening(project, agent)
    clock.advance(timedelta(days=8))
    new = _cycle(project, filler(3))
    target = next(w for w in sorted(new) if w not in calibration)
    agree(project, agent, target, protocol_id, "include")
    register_conclusion(project, human, STATEMENT, [BasisRef(kind="work", ref=target)], None)
    snapshot(project, human, trigger="human")
    clock.advance(timedelta(days=8))
    _cycle(project, filler(2, first=40))
    snapshot(project, human, trigger="human")
    return project, target


@pytest.mark.anyio
async def test_mcp_digest_get_is_agent_view(
    settings: Settings, clock: FixedClock, living: tuple[Project, str]
) -> None:
    project, _ = living
    before = len(read_all(project.paths.events_dir, project.catalog))
    async with open_session(settings, clock) as session:
        got = await session.call("digest_get", project="demo", since=None)
    assert got["ok"] is True, got
    [part] = got["data"]["projects"]
    assert part["slug"] == "demo" and part["new_candidates"]["items"]
    assert part["update_flow"] is not None and part["update_flow"]["changed_previous"] == []
    assert got["data"]["digest_id"] is None
    assert STATEMENT not in json.dumps(got) and "statement" not in json.dumps(got)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before  # never records


@pytest.mark.anyio
async def test_mcp_conclusion_status_has_no_statement(
    settings: Settings, clock: FixedClock, living: tuple[Project, str]
) -> None:
    async with open_session(settings, clock) as session:
        got = await session.call("conclusion_status", project="demo")
    assert got["ok"] is True, got
    [row] = got["data"]["conclusions"]
    assert row["conclusion_id"].startswith("ccl_") and row["state"] == "unchanged"
    assert STATEMENT not in json.dumps(got) and "statement" not in json.dumps(got)


@pytest.mark.anyio
async def test_mcp_living_tools_refused_to_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    from tests.helpers import _setup

    _setup(project, agent, human, mock_sources)
    _draw(project)
    async with open_session(settings, clock) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True, joined
        digest = await screener.call("digest_get", project="demo")
        status = await screener.call("conclusion_status", project="demo")
    for body in (digest, status):
        assert body["ok"] is False
        assert [e["field"] for e in body["errors"]] == ["session"]
