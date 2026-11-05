"""The lineage MCP tools (plan G2-C, task 6): propose only; no tool decides, confirms or merges."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.services.context import Project
from tests.helpers import Session, install_skill, open_session
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world
from tests.test_extraction_next import SESSION_A

SESSION_E = "01JZ9Q3K5M7N8P0R2S4T6V8W1E"
AGENT = {"role": "lineage", "model": "claude-opus-5-5", "skill": "rf-lineage"}


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


async def _idea(client: Session, **args: object) -> dict[str, Any]:
    """`Session.call` takes `name` itself, which `idea_propose` also takes: go underneath."""
    result = await client._client.call_tool("idea_propose", args)
    block = result.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


@pytest.mark.anyio
async def test_tool_list_has_proposals_and_no_decisions(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert "relation_propose" in names and "idea_propose" in names
    banned = ("decide", "confirm", "merge", "reject")
    assert not [
        n for n in names if n.startswith(("relation_", "idea_")) and any(b in n for b in banned)
    ]


@pytest.mark.anyio
async def test_relation_propose_returns_the_platform_status(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-lineage")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await client.call(
            "relation_propose",
            project="demo",
            source_work=lin.source,
            target=lin.target5,
            edge_type="builds-on",
            basis_item=lin.base,
            **AGENT,
        )
        assert out["ok"] is True, out
        assert out["data"]["status"] == "stated" and out["data"]["written"] is True
        inferred = await client.call(
            "relation_propose",
            project="demo",
            source_work=lin.source,
            target=lin.target3,
            edge_type="builds-on",
            basis_item=lin.base,
            **AGENT,
        )
    assert inferred["data"]["status"] == "inferred"
    assert inferred["data"]["status_reason"] == "target-differs"
    [first, _second] = _of(project, "relation.proposed")
    assert first.actor.skill is not None and first.actor.skill.startswith("rf-lineage@")
    assert first.input_blob is not None


@pytest.mark.anyio
async def test_status_argument_is_refused_and_writes_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-lineage")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await client.call(
            "relation_propose",
            project="demo",
            source_work=lin.source,
            target=lin.target5,
            edge_type="builds-on",
            basis_item=lin.base,
            status="stated",
            **AGENT,
        )
    assert out["ok"] is False and out["errors"][0]["field"] == "status"
    assert _of(project, "relation.proposed") == []


@pytest.mark.anyio
async def test_bad_input_is_a_structured_error(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-lineage")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await client.call(
            "relation_propose",
            project="demo",
            source_work=lin.source,
            target=lin.target5,
            edge_type="cites",
            **AGENT,
        )
    assert out["ok"] is False and out["errors"][0]["field"].startswith("relation")
    assert _of(project, "relation.proposed") == []


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-lineage")
    _session(monkeypatch, ctr_a.session)  # this session read a contribution pass
    async with open_session(settings, clock) as client:
        rel = await client.call(
            "relation_propose",
            project="demo",
            source_work=lin.source,
            target=lin.target5,
            edge_type="builds-on",
            basis_item=lin.base,
            **AGENT,
        )
        idea = await _idea(
            client,
            project="demo",
            name="linear attention",
            origin=lin.source,
            name_item=lin.base,
            members=[lin.source],
            **AGENT,
        )
    for out in (rel, idea):
        assert out["ok"] is False and out["errors"][0]["field"] == "session"
    assert _of(project, "relation.proposed", "idea.proposed") == []


@pytest.mark.anyio
async def test_idea_propose_writes_an_unconfirmed_idea(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-lineage")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        out = await _idea(
            client,
            project="demo",
            name="Linear attention",
            origin=lin.source,
            name_item=lin.base,
            members=[lin.source],
            **AGENT,
        )
        bad = await _idea(
            client,
            project="demo",
            name="Gated attention",
            origin=lin.source,
            name_item=lin.base,
            members=[lin.source],
            **AGENT,
        )
    assert out["ok"] is True and out["data"]["idea_id"].startswith("ida_")
    assert bad["ok"] is False and bad["errors"][0]["field"] == "name"
    [event] = _of(project, "idea.proposed")
    assert event.actor.kind == "agent" and event.input_blob is not None
