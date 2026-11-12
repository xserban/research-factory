"""The feed MCP tools: registered, no react or send tool, `feed_list` refused to a pass session."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.dedup import dedup_run
from tests.helpers import SourcesFor, _setup, open_session
from tests.screening_helpers import _draw
from tests.watch_helpers import ScriptedSource, adapters, by_text

AGENT = {"role": "watcher", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
FEED_TOOLS = {"feed_list", "feed_run", "feed_status"}


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


@pytest.mark.anyio
async def test_feed_tools_are_registered_without_react_or_send(
    settings: Settings, clock: FixedClock
) -> None:
    server = build_server(settings, clock=clock)
    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names >= FEED_TOOLS
    assert "feed_react" not in names and "feed_send" not in names


@pytest.mark.anyio
async def test_feed_list_refused_to_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    dedup_run(project)
    source = ScriptedSource(by_text({}))
    async with open_session(settings, clock, dict(adapters(source))) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True, joined
        listing = await screener.call("feed_list", project="demo", **AGENT)
    assert _fields(listing) == ["session"]
