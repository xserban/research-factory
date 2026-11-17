"""The `search_slice` MCP tool: plan without writing, run with a report (IDEA-75)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.search import run_query
from tests.test_pubmed_slices import _parent, _world, small_cap  # noqa: F401

AGENT = {"role": "screener-a", "model": "claude-opus-5-5", "skill": "rf-screen"}


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


def _data(res: CallToolResult) -> dict[str, Any]:
    body = _body(res)
    assert body["ok"] is True, body
    data: dict[str, Any] = body["data"]
    return data


@pytest.mark.anyio
@pytest.mark.usefixtures("small_cap")
async def test_search_slice_plans_then_runs(
    settings: Settings, explore_project: Project, clock: FixedClock
) -> None:
    sources, _ = _world(25)
    parent = _parent(explore_project, sources)
    run_query(explore_project, parent, sources=sources)
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=sources)
    async with Client(server) as client:
        planned = _data(
            await client.call_tool(
                "search_slice",
                {"project": "demo", "query_id": parent, "first_year": 2020, **AGENT},
            )
        )
        assert planned["parent_count"] == 25 and planned["slice_total"] == 25
        counts = [s["count"] for s in planned["slices"] if s["count"]]
        assert counts == [6, 6, 6, 6, 1]
        done = _data(
            await client.call_tool(
                "search_slice",
                {"project": "demo", "query_id": parent, "first_year": 2020, "run": True, **AGENT},
            )
        )
        assert len(done["runs"]) == 5
        assert done["report"]["difference"] == 0
