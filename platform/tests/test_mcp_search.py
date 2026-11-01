"""The `search_run` and `dedup_run` MCP tools, over the real adapters on mock transports."""

import json
from datetime import timedelta
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.search import QueryKind, QuerySpec
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.search import register_query, run_query
from factory.sources.registry import SourceFactory
from tests.helpers import arxiv_atom, openalex_item, ready_protocol

AGENT = {"role": "screener-a", "model": "claude-opus-5-5", "skill": "rf-screen"}


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


def _sources(mock_sources: Any) -> dict[str, SourceFactory]:
    return dict(
        mock_sources(
            openalex=[
                openalex_item(
                    title="Linear attention",
                    author="Ada Zhou",
                    published="2023-01-05",
                    openalex_id="W5001",
                )
            ],
        )
    )


@pytest.mark.anyio
async def test_search_run_tool(
    settings: Settings, explore_project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=_sources(mock_sources))
    async with Client(server) as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert "search_run" in names and "dedup_run" in names
        res = await client.call_tool(
            "search_run",
            {"project": "demo", "source": "openalex", "query": "linear attention", **AGENT},
        )
        body = _body(res)

    assert body["ok"] is True
    data = body["data"]
    assert data["source"] == "openalex" and data["status"] == "complete"
    assert data["retrieved_count"] == 1 and data["new_works"] == 1
    [registered] = [
        e
        for e in read_all(explore_project.paths.events_dir, explore_project.catalog)
        if e.type == "query.registered"
    ]
    assert registered.actor.kind == "agent"
    assert registered.actor.id == "screener-a"
    assert registered.actor.model == "claude-opus-5-5"
    assert registered.input_blob is not None


@pytest.mark.anyio
async def test_search_run_validation_error(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=_sources(mock_sources))
    async with Client(server) as client:
        res = await client.call_tool(
            "search_run", {"project": "demo", "source": "pubmed", "query": "x", **AGENT}
        )
        body = _body(res)
    assert body["ok"] is False
    assert body["errors"][0]["field"] == "source"


@pytest.mark.anyio
async def test_search_run_rejects_unknown_kind_and_purpose(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=_sources(mock_sources))
    async with Client(server) as client:
        bad_kind = _body(
            await client.call_tool(
                "search_run",
                {
                    "project": "demo",
                    "source": "openalex",
                    "query": "x",
                    "kind": "semantic",
                    **AGENT,
                },
            )
        )
        bad_purpose = _body(
            await client.call_tool(
                "search_run",
                {
                    "project": "demo",
                    "source": "openalex",
                    "query": "x",
                    "purpose": "vibes",
                    **AGENT,
                },
            )
        )
    assert bad_kind["ok"] is False and bad_kind["errors"][0]["field"] == "kind"
    assert bad_purpose["ok"] is False and bad_purpose["errors"][0]["field"] == "purpose"


@pytest.mark.anyio
async def test_search_run_unknown_resume_run(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=_sources(mock_sources))
    async with Client(server) as client:
        body = _body(
            await client.call_tool(
                "search_run",
                {
                    "project": "demo",
                    "source": "openalex",
                    "query": "x",
                    "resume_run": "run_01JZ9Q3K5M7N8P0R2S4T6V8W0X",
                    **AGENT,
                },
            )
        )
    assert body["ok"] is False and body["errors"][0]["field"] == "resume_run"


@pytest.mark.anyio
async def test_search_run_refuses_to_resume_a_complete_run(
    settings: Settings, explore_project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    # Only a partial or failed run can be resumed; a complete one is refused, and no query is
    # registered on the way.
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="linear attention")
    sources = _sources(mock_sources)
    query_id = register_query(explore_project, explore_project.human_actor(), spec, sources=sources)
    first = run_query(explore_project, query_id, sources=sources)
    clock.advance(timedelta(milliseconds=1))

    server = build_server(settings, clock=clock, sources=sources)
    async with Client(server) as client:
        body = _body(
            await client.call_tool(
                "search_run",
                {
                    "project": "demo",
                    "source": "openalex",
                    "query": "linear attention",
                    "resume_run": first.run_id,
                    **AGENT,
                },
            )
        )
    assert body["ok"] is False and body["errors"][0]["field"] == "resume_run"
    registered = [
        e
        for e in read_all(explore_project.paths.events_dir, explore_project.catalog)
        if e.type == "query.registered"
    ]
    assert len(registered) == 1


async def _resume(
    settings: Settings, clock: FixedClock, sources: dict[str, SourceFactory], **args: Any
) -> dict[str, Any]:
    server = build_server(settings, clock=clock, sources=sources)
    async with Client(server) as client:
        return _body(await client.call_tool("search_run", {"project": "demo", **args, **AGENT}))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changed",
    [{"source": "other"}, {"query": "something else"}, {"kind": "filter"}],
    ids=["source", "query", "kind"],
)
async def test_search_run_refuses_a_resume_that_restates_the_query_differently(
    settings: Settings,
    explore_project: Project,
    clock: FixedClock,
    fake_sources: Any,
    changed: dict[str, str],
) -> None:
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="linear attention")
    seeded = fake_sources(fail_after=1)
    query_id = register_query(explore_project, explore_project.human_actor(), spec, sources=seeded)
    partial = run_query(explore_project, query_id, sources=seeded)
    clock.advance(timedelta(milliseconds=1))

    args = {"source": "fake", "query": "linear attention", "resume_run": partial.run_id}
    body = await _resume(
        settings, clock, {**fake_sources(), "other": fake_sources()["fake"]}, **{**args, **changed}
    )

    assert body["ok"] is False
    assert [e["field"] for e in body["errors"]] == ["resume_run"]
    events = read_all(explore_project.paths.events_dir, explore_project.catalog)
    assert [e.type for e in events].count("search.run_started") == 1  # nothing was written


@pytest.mark.anyio
async def test_search_run_resumes_a_partial_run_through_the_tool(
    settings: Settings, explore_project: Project, clock: FixedClock, fake_sources: Any
) -> None:
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="linear attention")
    seeded = fake_sources(fail_after=1)
    query_id = register_query(explore_project, explore_project.human_actor(), spec, sources=seeded)
    partial = run_query(explore_project, query_id, sources=seeded)
    assert partial.status == "partial"
    clock.advance(timedelta(milliseconds=1))

    body = await _resume(
        settings,
        clock,
        fake_sources(),
        source="fake",
        query="linear attention",
        resume_run=partial.run_id,
    )

    assert body["ok"] is True
    assert body["data"]["status"] == "complete" and body["data"]["query_id"] == query_id
    registered = [
        e
        for e in read_all(explore_project.paths.events_dir, explore_project.catalog)
        if e.type == "query.registered"
    ]
    assert len(registered) == 1  # resuming reuses the query


@pytest.mark.anyio
async def test_dedup_run_tool(
    settings: Settings, explore_project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    sources = dict(
        mock_sources(
            openalex=[
                openalex_item(
                    title="Linear attention in transformers",
                    author="Ada Zhou",
                    published="2024-06-01",
                    openalex_id="W5002",
                    doi="10.1000/x",
                )
            ],
            arxiv=arxiv_atom(
                [("2301.00001v1", "Linear attention in transformers", 2024, "Ada Zhou")]
            ),
        )
    )
    for source, text_ in (("openalex", "linear"), ("arxiv", "linear")):
        spec = QuerySpec(source=source, kind=QueryKind.KEYWORD, text=text_)
        query_id = register_query(
            explore_project, explore_project.human_actor(), spec, sources=sources
        )
        run_query(explore_project, query_id, sources=sources)
        clock.advance(timedelta(milliseconds=1))

    server = build_server(settings, clock=clock, sources=sources)
    async with Client(server) as client:
        body = _body(await client.call_tool("dedup_run", {"project": "demo", **AGENT}))

    assert body["ok"] is True
    data = body["data"]
    assert len(data["created"]) == 1 and data["reverted"] == []
    assert (data["works"], data["canonical"]) == (2, 1)
    # The service is idempotent: the same merge is not recorded twice.
    assert dedup_run(explore_project).created == []


@pytest.mark.anyio
async def test_dedup_run_requires_a_valid_agent(
    settings: Settings, project: Project, clock: FixedClock, mock_sources: Any
) -> None:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=_sources(mock_sources))
    async with Client(server) as client:
        body = _body(
            await client.call_tool(
                "dedup_run",
                {
                    "project": "demo",
                    "role": "screener-a",
                    "model": "",
                    "skill": "rf-screen",
                },
            )
        )
    assert body["ok"] is False and body["errors"][0]["field"] == "model"


@pytest.mark.anyio
@pytest.mark.parametrize("purpose", ["chase", "seed", "probe"])
async def test_search_run_refuses_every_purpose_but_search_and_writes_nothing(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: Any,
    purpose: str,
) -> None:
    # Final review, finding 1: only probes and seed lookups make other queries, through their tools.
    ready_protocol(project, agent, human, mock_sources)
    before = len(read_all(project.paths.events_dir, project.catalog))
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=_sources(mock_sources))
    async with Client(server) as client:
        body = _body(
            await client.call_tool(
                "search_run",
                {
                    "project": "demo",
                    "source": "openalex",
                    "query": "attention",
                    "purpose": purpose,
                    **AGENT,
                },
            )
        )
    assert body["ok"] is False
    assert [error["field"] for error in body["errors"]] == ["purpose"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
