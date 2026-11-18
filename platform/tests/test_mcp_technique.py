# ruff: noqa: F401, F811
"""The technique MCP tools: read-only, labelled exploratory, refused to a pass session, withheld."""

from __future__ import annotations

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp.server import build_server
from factory.services.access import TOOL_PERMISSIONS
from factory.services.context import Project
from tests.helpers import open_session
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world

TOOLS = (
    "technique_landscape",
    "technique_view",
    "technique_neighbors",
    "technique_gaps",
    "technique_combinations",
    "technique_challenges",
)


@pytest.mark.anyio
async def test_the_tools_are_read_only_and_registered(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(t in names for t in TOOLS)
    banned = ("record", "propose", "decide", "confirm", "write")
    assert not [t for t in names if t.startswith("technique_") and any(b in t for b in banned)]
    assert all(TOOL_PERMISSIONS[t].value == "project:read" for t in TOOLS)


@pytest.mark.anyio
async def test_an_empty_landscape_is_labelled_and_an_unknown_approach_is_refused(
    settings: Settings, project: Project, clock: FixedClock, lin: Lineage
) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call("technique_landscape", project="demo")
        assert out["ok"] is True, out
        data = out["data"]
        assert data["exploratory"] is True and data["class"] == "interpretation"
        assert "exploratory" in data["notice"] and data["approaches"] == []
        assert data["lens"]["layer"] == "core"
        bad = await client.call("technique_view", project="demo", approach="nope")
        assert bad["ok"] is False and bad["errors"][0]["field"] == "approach"
        stage = await client.call("technique_landscape", project="demo", stage="nope")
        assert stage["ok"] is False
        gaps = await client.call("technique_gaps", project="demo", from_stage="a", to_stage="b")
        assert gaps["ok"] is False
        combos = await client.call("technique_combinations", project="demo")
        assert combos["ok"] is True and combos["data"]["exploratory"] is True
        assert combos["data"]["total"] == 0
