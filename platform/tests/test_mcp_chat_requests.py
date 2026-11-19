"""The chat request MCP tools and the `factory chat` commands (plan spar-night N3)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from mcp import Client
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp.server import build_server
from factory.mcp.unit_cap import UnitCap
from factory.services import chat_requests as cr
from factory.services import runner
from factory.services.access import TOOL_PERMISSIONS, Permission
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.cli_helpers import _env
from tests.helpers import install_skill
from tests.test_runner import FakeLauncher

ACT = {"role": "asker", "model": "claude-sonnet-5-5", "skill": "rf-chat"}


@pytest.fixture(autouse=True)
def chat_env(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    install_skill(project.settings, "rf-chat", "CHAT SKILL BODY")
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")


async def _call(
    settings: Settings, clock: FixedClock, cap: UnitCap, tool: str, **args: Any
) -> dict[str, Any]:
    clock.advance(timedelta(seconds=1))  # events of different sessions fold in time order
    server = build_server(settings, clock=clock, sources={}, cap=cap)
    async with Client(server) as client:
        result = await client.call_tool(tool, {"project": "demo", **args})
    block: Any = result.content[0]
    body = json.loads(block.text)
    assert isinstance(body, dict)
    return body


@pytest.mark.anyio
async def test_next_serves_to_a_run_session_once_and_the_cap_stops_a_second(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    human = project.human_actor()
    first = cr.request_chat(project, human, "ask", SelectionSpec(), question="Q1").request_id
    cr.request_chat(project, human, "ask", SelectionSpec(), question="Q2")
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "ask", launcher=launcher)
    cap = UnitCap(1, run_id)
    got = await _call(settings, clock, cap, "chat_request_next", **ACT)
    assert got["ok"] is True, got
    batch = got["data"]["batch"]
    assert batch["request_id"] == first and batch["kind"] == "ask" and batch["question"] == "Q1"
    assert batch["selection"]["layers"] == [] and batch["state"] == "taken"
    second = await _call(settings, clock, cap, "chat_request_next", **ACT)
    assert second["ok"] is False and second["errors"][0]["field"] == "cap-reached"
    view = await _call(settings, clock, cap, "chat_request_view", request_id=first)
    assert view["ok"] is True and view["data"]["state"] == "taken"
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)


@pytest.mark.anyio
async def test_next_without_a_run_is_refused_and_serves_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    cr.request_chat(project, project.human_actor(), "ask", SelectionSpec(), question="Q")
    out = await _call(settings, clock, UnitCap(), "chat_request_next", **ACT)
    assert out["ok"] is False and out["errors"][0]["field"] == "run"
    assert cr.open_count(project, "ask") == 1


@pytest.mark.anyio
async def test_a_second_take_by_the_same_run_is_refused_and_nothing_open_says_so(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    cr.request_chat(project, project.human_actor(), "ask", SelectionSpec(), question="Q")
    launcher = FakeLauncher()
    run_id = runner.start_run(project, "ask", launcher=launcher)
    cap = UnitCap(5, run_id)
    first = await _call(settings, clock, cap, "chat_request_next", **ACT)
    assert first["ok"] is True and first["data"]["batch"] is not None
    out = await _call(settings, clock, cap, "chat_request_next", **ACT)
    assert out["ok"] is False  # one run, one request, even with a cap of 5
    for process in launcher.processes:
        process.release()
    assert runner.wait(run_id, 10)


def test_access_rows() -> None:
    assert TOOL_PERMISSIONS["chat_request_next"] is Permission.WORK_RUN
    assert TOOL_PERMISSIONS["chat_request_view"] is Permission.PROJECT_READ
    assert TOOL_PERMISSIONS["cli:chat request spar"] is Permission.HUMAN_CONFIRM
    assert TOOL_PERMISSIONS["cli:chat request ask"] is Permission.HUMAN_CONFIRM


def test_cli_request_and_list(settings: Settings, project: Project) -> None:
    runner_ = CliRunner()
    env = _env(settings.root)
    spar = runner_.invoke(
        app,
        ["chat", "request", "spar", "Reflection helps", "--layer", "core", "--mode", "prepare",
         "--note", "for the lead"],
        env=env,
    )  # fmt: skip
    assert spar.exit_code == 0, spar.output
    ask = runner_.invoke(app, ["chat", "request", "ask", "Does it help?"], env=env)
    assert ask.exit_code == 0, ask.output
    bad = runner_.invoke(app, ["chat", "request", "ask", "q", "--mode", "prepare"], env=env)
    assert bad.exit_code != 0
    listing = runner_.invoke(app, ["chat", "requests"], env=env)
    assert listing.exit_code == 0 and "2 request(s)" in listing.output
    assert "spar" in listing.output and "prepare" in listing.output and "open" in listing.output
    rows = cr.list_requests(project)
    assert [r.kind for r in rows] == ["spar", "ask"] and rows[0].selection["layers"] == ["core"]
    assert rows[0].note == "for the lead"
