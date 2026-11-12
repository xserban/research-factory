"""The `watch_status` and `watch_run` MCP tools: agent provenance, pass sessions refused."""

from __future__ import annotations

from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.dedup import dedup_run
from tests.helpers import SourcesFor, _setup, open_session
from tests.screening_helpers import _draw
from tests.watch_helpers import ScriptedSource, adapters, by_text, record, watch_ready

AGENT = {"role": "watcher", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
A = [record("Alpha methods for sparse graphs", author="Ana Li", year=2021)]
B = [record("Beta bounds on federated drift", author="Bo Chen", year=2022)]


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


@pytest.mark.anyio
async def test_mcp_watch_run_records_agent_provenance(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    watch_ready(project, agent, human, mock_sources)
    source = ScriptedSource(by_text({"attention": [A], "transformers": [B]}))
    async with open_session(settings, clock, dict(adapters(source))) as session:
        status = await session.call("watch_status", project="demo")
        assert status["ok"] is True and status["data"]["sources"][0]["due"] is True
        ran = await session.call("watch_run", project="demo", **AGENT)
        assert ran["ok"] is True, ran
        cycle = ran["data"]["cycle"]
        assert cycle["status"] == "complete" and cycle["new_works"] == 2
        assert "new_work_ids" not in cycle
        again = await session.call("watch_run", project="demo", **AGENT)
        assert again["ok"] is True and again["data"] == {"cycle": None}
    events = read_all(project.paths.events_dir, project.catalog)
    [started] = [e for e in events if e.type == "watch.cycle_started"]
    assert started.actor.kind == "agent" and started.actor.model == AGENT["model"]
    assert started.actor.skill is not None and started.input_blob is not None
    assert started.payload["trigger"] == "agent"
    runs = [e for e in events if e.type == "search.run_started" and e.refs[-1].startswith("wcy_")]
    assert len(runs) == 2 and {e.actor.kind for e in runs} == {"agent"}


@pytest.mark.anyio
async def test_mcp_watch_refused_to_pass_session(
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
    before = len(read_all(project.paths.events_dir, project.catalog))
    source = ScriptedSource(by_text({}))
    async with open_session(settings, clock, dict(adapters(source))) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True, joined
        joined_events = len(read_all(project.paths.events_dir, project.catalog))
        status = await screener.call("watch_status", project="demo")
        ran = await screener.call("watch_run", project="demo", **AGENT)
    assert _fields(status) == ["session"] and _fields(ran) == ["session"]
    assert len(read_all(project.paths.events_dir, project.catalog)) == joined_events >= before
    assert source.specs == []
