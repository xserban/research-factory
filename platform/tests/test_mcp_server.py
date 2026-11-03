import json
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp.server import build_server
from factory.services.context import Project


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


@pytest.mark.anyio
async def test_project_status_tool(settings: Settings, project: Project, clock: FixedClock) -> None:
    server = build_server(settings, clock=clock)
    async with Client(server) as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert names == [
            "project_status",
            "search_run",
            "search_chase",
            "dedup_run",
            "question_record",
            "seed_add",
            "seed_list",
            "probe_run",
            "protocol_record",
            "protocol_press_review",
            "protocol_amend",
            "screen_next",
            "screen_record",
            "screen_agreement",
            "calibration_label",
            "audit_sample",
            "audit_record",
            "protocol_deviation",
            "report_prisma",
            "report_methods",
            "trace",
            "check",
        ]
        res = await client.call_tool("project_status", {"project": "demo"})
        body = _body(res)
    assert body["ok"] is True
    assert body["data"]["slug"] == "demo"
    assert body["data"]["rigor_mode"] == "pilot"


@pytest.mark.anyio
async def test_unknown_project_returns_structured_error(
    settings: Settings, clock: FixedClock
) -> None:
    server = build_server(settings, clock=clock)
    async with Client(server) as client:
        res = await client.call_tool("project_status", {"project": "ghost"})
        body = _body(res)
    assert body == {"ok": False, "errors": [{"field": "project", "reason": "unknown project"}]}


@pytest.mark.anyio
async def test_malformed_slug_returns_structured_error(
    settings: Settings, clock: FixedClock
) -> None:
    server = build_server(settings, clock=clock)
    async with Client(server) as client:
        res = await client.call_tool("project_status", {"project": "Bad_Slug"})
        body = _body(res)
    assert body["ok"] is False
    assert body["errors"][0]["field"] == "project"
