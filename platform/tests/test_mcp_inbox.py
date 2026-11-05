"""The inbox and discovery MCP tools (slice 4a): parse, call a service, reply."""

from __future__ import annotations

import json

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.conventions import WITHHELD
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.discovery import DiscoveryReport, Route, agent_view
from factory.services.screening import join_pass, open_pass
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import SESSION, SourcesFor, _setup, install_skill, open_session
from tests.inbox_helpers import Keyed, link_item
from tests.test_screening_next import _draw

AGENT = {"role": "searcher", "model": "claude-opus-5-5", "skill": "rf-search"}
DOI = "https://doi.org/10.2000/s1"
FRESH = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"
TOOLS = ("inbox_add", "inbox_resolve", "inbox_list", "report_discovery")


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


def _added(project: Project) -> list[dict[str, object]]:
    events = read_all(project.paths.events_dir, project.catalog)
    return [{"actor": e.actor.kind, **e.payload} for e in events if e.type == "inbox.link_added"]


@pytest.mark.anyio
async def test_human_relay_records_channel_mcp(
    settings: Settings, explore_project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call(
            "inbox_add", project="demo", items=[{"link": DOI, "note": "from Ana"}], channel="mcp"
        )
    assert out["ok"] is True, out
    assert len(out["data"]["written"]) == 1
    [added] = _added(explore_project)
    assert (added["actor"], added["channel"], added["note"]) == ("human", "mcp", "from Ana")


@pytest.mark.anyio
async def test_agent_capture_needs_basis(
    settings: Settings, explore_project: Project, clock: FixedClock
) -> None:
    install_skill(settings, "rf-search")
    items = [{"link": DOI}, {"link": DOI, "basis": {"kind": "knowledge"}}, {"link": 5}]
    async with open_session(settings, clock) as client:
        out = await client.call("inbox_add", project="demo", items=items, **AGENT)
    assert out["ok"] is True, out
    data = out["data"]
    assert len(data["written"]) == 1
    fields = [[i["field"] for i in r["issues"]] for r in data["rejected"]]
    assert fields == [["items.0.basis"], ["items.2.link"]]
    [added] = _added(explore_project)
    assert (added["actor"], added["channel"]) == ("agent", "mcp")


@pytest.mark.anyio
async def test_bad_channel_refused(
    settings: Settings, explore_project: Project, clock: FixedClock
) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call("inbox_add", project="demo", items=[{"link": DOI}], channel="x")
    assert out == {"ok": False, "errors": [{"field": "channel", "reason": "agent or mcp"}]}
    assert _added(explore_project) == []


@pytest.mark.anyio
async def test_resolve_list_and_report(
    settings: Settings, explore_project: Project, clock: FixedClock
) -> None:
    keyed = Keyed(openalex={"doi:10.2000/s1": [link_item(1)]})
    async with open_session(settings, clock, sources=keyed.sources()) as client:
        await client.call("inbox_add", project="demo", items=[{"link": DOI}], channel="mcp")
        resolved = await client.call("inbox_resolve", project="demo")
        listed = await client.call("inbox_list", project="demo", status="resolved")
        report = await client.call("report_discovery", project="demo")
    assert resolved["ok"] is True, resolved
    [item] = resolved["data"]["items"]
    assert (item["status"], item["errors"]) == ("new", [])
    assert [i["last_outcome"] for i in listed["data"]["items"]] == ["new"]
    assert report["data"]["by_first_route"] == {
        "supplied-human": {"identified": 1, "ta-included": 0, "in-evidence": 0}
    }


@pytest.mark.anyio
async def test_pass_session_refused_by_every_inbox_tool(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    join_pass(project, agent, PassLabel.A)
    _session(monkeypatch, SESSION)
    args: dict[str, dict[str, object]] = {
        "inbox_add": {"items": [{"link": DOI}], "channel": "mcp"},
        "inbox_resolve": {},
        "inbox_list": {},
        "report_discovery": {},
    }
    async with open_session(settings, clock) as client:
        for tool in TOOLS:
            out = await client.call(tool, project="demo", **args[tool])
            assert out["ok"] is False, tool
            assert out["errors"][0]["field"] == "session", tool
    _session(monkeypatch, FRESH)
    async with open_session(settings, clock) as client:
        out = await client.call("inbox_list", project="demo")
    assert out["ok"] is True, out


@pytest.mark.anyio
async def test_list_omits_the_link_until_a_pass_opens(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    """Role-blind: a `[withheld]` link would name a held-out seed during query design. The
    identifier fields repeat the link, so they go with it."""
    _setup(project, agent, human, mock_sources, random_works=0)
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    items = [{"link": f"https://doi.org/{held.doi}"}, {"link": DOI}]
    async with open_session(settings, clock) as client:
        added = await client.call("inbox_add", project="demo", items=items, channel="mcp")
        assert added["ok"] is True and len(added["data"]["written"]) == 2, added
        before = await client.call("inbox_list", project="demo")
    assert before["ok"] is True, before
    assert WITHHELD not in json.dumps(before)
    for item in before["data"]["items"]:
        assert not {"link", "identifier_value", "identifier_version"} & set(item)
        assert item["status"] == "open"
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    async with open_session(settings, clock) as client:
        after = await client.call("inbox_list", project="demo")
    assert {i["link"] for i in after["data"]["items"]} >= {DOI}


def test_agent_view_reports_seed_admission_as_other() -> None:
    counts = {"identified": 2, "ta-included": 1, "in-evidence": 0}
    report = DiscoveryReport(
        levels=("identified", "ta-included", "in-evidence"),
        by_first_route={Route.DATABASE: counts, Route.SEED_ADMISSION: counts},
        by_first_actor={"human": counts},
        overlaps={"database+seed-admission": 1},
        totals=counts,
    )
    view = agent_view(report)
    assert view["by_first_route"] == {"database": counts, "other": counts}
    assert view["overlaps"] == {"database+other": 1}
    assert "seed" not in str(view)
