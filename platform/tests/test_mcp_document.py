"""The `document_read` MCP tool (plan 2B2, task 6): a page, the gates, and the tool list.

Reading is the only document tool. Conversion is the researcher's act (`factory document convert`),
so no convert tool is registered. A refused call writes nothing.
"""

import json
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from tests.document_helpers import ARTICLE, fetched_document, make_registry, promoted_works
from tests.helpers import _setup, open_session
from tests.test_screening_next import _draw

AGENT = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
SENTENCE = "Ut enim ad minim veniam"
PAGE_FIELDS = {
    "work_id",
    "document_id",
    "conversion_id",
    "route",
    "quality",
    "source_version",
    "converter",
    "converter_version",
    "markdown_hash",
    "segments",
    "next_after",
    "total_segments",
}


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


@pytest.mark.usefixtures("corpus")
@pytest.mark.anyio
async def test_document_read_returns_a_page(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    convert_documents(project, make_registry())
    server = build_server(settings, clock=clock)

    async with Client(server) as client:
        body = _body(await client.call_tool("document_read", {"project": "demo", "work_id": work}))

    assert body["ok"] is True, body
    data = body["data"]
    assert set(data) == PAGE_FIELDS
    assert data["work_id"] == work
    assert data["converter"] == "latexml-html"
    assert data["total_segments"] > 0
    assert any(SENTENCE in segment["text"] for segment in data["segments"])


@pytest.mark.anyio
async def test_document_read_refused_for_a_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Any,
    agent: Any,
    human: Any,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    async with open_session(settings, clock) as screener:
        await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        body = await screener.call("document_read", project="demo", work_id="rf:any-00000000")

    assert _fields(body) == ["session"]


@pytest.mark.anyio
async def test_document_read_refused_for_a_work_not_included(
    settings: Settings, project: Project, clock: FixedClock, corpus_leaving: str
) -> None:
    server = build_server(settings, clock=clock)

    async with Client(server) as client:
        body = _body(
            await client.call_tool("document_read", {"project": "demo", "work_id": corpus_leaving})
        )

    assert _fields(body) == ["work_id"]


@pytest.mark.anyio
async def test_document_read_is_listed_and_no_convert_tool_is_registered(
    settings: Settings, clock: FixedClock
) -> None:
    server = build_server(settings, clock=clock)

    async with Client(server) as client:
        names = [t.name for t in (await client.list_tools()).tools]

    assert "document_read" in names
    assert not [name for name in names if "convert" in name]
