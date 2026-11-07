"""The decision MCP tools (slice 8, plan A4): parse, call the service, reply."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client
from mcp.server.elicitation import render_elicitation_schema

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.conventions import WITHHELD
from factory.mcp.elicit import _selection_form
from factory.mcp.server import build_server
from factory.model.screening import Channel
from factory.services import decisions as decisions_service
from factory.services.access import TOOL_PERMISSIONS, Permission
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import Session, SourcesFor, _setup, open_session

AGENT = {"role": "planner", "model": "claude-opus-5-5", "skill": "rf-screen"}
ITEMS = [
    {"item_id": "I01", "text": "Exclude preprints", "grounds": ["prb_1"]},
    {"item_id": "I02", "text": "Keep preprints"},
]


def _types(project: Project) -> list[str]:
    return [e.type for e in read_all(project.paths.events_dir, project.catalog)]


async def _suggest(client: Session, **over: object) -> dict[str, Any]:
    args: dict[str, object] = {
        "project": "demo",
        "level": "protocol",
        "subject": "exclusions",
        "explanation": "The exclusions set what leaves the corpus.",
        "items": ITEMS,
        **AGENT,
    }
    args.update(over)
    return await client.call("decision_suggest", **args)


@pytest.mark.anyio
async def test_suggest_list_and_view(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        out = await _suggest(client)
        assert out["ok"] is True, out
        decision_id = out["data"]["decision_id"]
        listed = await client.call("decision_list", project="demo", open_only=True)
        viewed = await client.call("decision_view", project="demo", decision_id=decision_id)
        none_open = await client.call("decision_list", project="demo", level="goal")
    assert [r["decision_id"] for r in listed["data"]["items"]] == [decision_id]
    assert listed["data"]["items"][0]["state"] == "open"
    assert [i["status"] for i in viewed["data"]["items"]] == ["proposed", "proposed"]
    assert viewed["data"]["selection"] is None
    assert none_open["data"]["items"] == []


@pytest.mark.anyio
async def test_suggest_reports_every_bad_field_and_writes_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    items = [{"item_id": "I01", "text": ""}, {"item_id": "x", "text": "ok"}]
    async with open_session(settings, clock) as client:
        bad_level = await _suggest(client, level="nope", items=items)
        dup = await _suggest(client, items=[ITEMS[0], ITEMS[0]])
        research = await _suggest(
            client, items=[{"item_id": "I01", "text": "Use X", "recommended": True}]
        )
        unknown = await _suggest(client, supersedes="dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    fields = [e["field"] for e in bad_level["errors"]]
    assert "level" in fields and "items.0.text" in fields and "items.1.item_id" in fields
    assert dup["ok"] is False and research["ok"] is False
    assert unknown["errors"] == [{"field": "supersedes", "reason": "unknown decision"}]
    assert "decision.suggested" not in _types(project)


@pytest.mark.anyio
async def test_suggest_scrubs_a_held_out_seed_without_a_signal_and_views_scrub_it(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.doi is not None
    async with open_session(settings, clock) as client:
        scrubbed = await _suggest(client, items=[{"item_id": "I01", "text": f"See {held.doi}"}])
        ok = await _suggest(client)
        decision_id = ok["data"]["decision_id"]
        # A human adds text that names the held-out seed; the agent view must not show it.
        decisions_service.select(
            project, human, decision_id, ["I01"], [f"Check {held.doi}"], "", Channel.CLI
        )
        viewed = await client.call("decision_view", project="demo", decision_id=decision_id)
    assert scrubbed["ok"] is True and set(scrubbed["data"]) == {"decision_id"}
    assert held.doi not in json.dumps(scrubbed)
    text = json.dumps(viewed)
    assert held.doi not in text and WITHHELD in text


@pytest.mark.anyio
async def test_select_is_refused_without_elicitation_and_writes_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        made = await _suggest(client)
        decision_id = made["data"]["decision_id"]
        out = await client.call("decision_select", project="demo", decision_id=decision_id)
        unknown = await client.call(
            "decision_select", project="demo", decision_id="dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
        )
        await _suggest(client, supersedes=decision_id)
        superseded = await client.call("decision_select", project="demo", decision_id=decision_id)
    assert out["ok"] is False
    assert [e["field"] for e in out["errors"]] == ["elicit"]
    assert [e["field"] for e in superseded["errors"]] == ["decision_id"]
    assert superseded["errors"][0]["reason"].startswith("superseded by ")
    assert unknown["errors"] == [{"field": "decision_id", "reason": "unknown"}]
    assert "decision.selected" not in _types(project)


@pytest.mark.anyio
async def test_select_takes_no_item_ids(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools["decision_select"].input_schema["properties"]) == {"project", "decision_id"}


def test_selection_form_is_a_multi_select_with_free_text() -> None:
    schema = render_elicitation_schema(_selection_form(["I01", "I02"]))
    assert schema["properties"]["selected"]["items"]["enum"] == ["I01", "I02"]
    assert schema["properties"]["selected"]["type"] == "array"
    assert schema["properties"]["added"]["type"] == "string"
    assert schema["properties"]["note"]["type"] == "string"


def test_permissions() -> None:
    assert TOOL_PERMISSIONS["decision_suggest"] is Permission.WORK_RUN
    assert TOOL_PERMISSIONS["decision_select"] is Permission.HUMAN_CONFIRM
    assert TOOL_PERMISSIONS["decision_list"] is Permission.PROJECT_READ
    assert TOOL_PERMISSIONS["decision_view"] is Permission.PROJECT_READ
    assert TOOL_PERMISSIONS["cli:decide select"] is Permission.HUMAN_CONFIRM
