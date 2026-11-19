"""The v2 spar MCP tools and the `factory chat` commands (plan spar-night N6). No real `claude`."""

# ruff: noqa: F811
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
from factory.services import spar_v2 as sv
from factory.services.access import TOOL_PERMISSIONS, Permission
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import install_skill
from tests.test_runner import FakeLauncher

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"


def act(role: str) -> dict[str, str]:
    return {"role": role, "model": "claude-sonnet-5-5", "skill": "rf-spar-v2"}


@pytest.fixture(autouse=True)
def v2_env(project: Project, monkeypatch: pytest.MonkeyPatch) -> FakeLauncher:
    install_skill(project.settings, "rf-spar-v2", "SPAR V2 SKILL BODY")
    monkeypatch.setattr(runner, "claude_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(runner, "_factory_executable", lambda: "/venv/bin/factory")
    launcher = FakeLauncher()
    monkeypatch.setattr(runner, "default_launcher", launcher)
    return launcher


async def _call(
    settings: Settings, clock: FixedClock, cap: UnitCap, tool: str, **args: Any
) -> dict[str, Any]:
    clock.advance(timedelta(seconds=1))
    server = build_server(settings, clock=clock, sources={}, cap=cap)
    async with Client(server) as client:
        result = await client.call_tool(tool, {"project": "demo", **args})
    block: Any = result.content[0]
    body = json.loads(block.text)
    assert isinstance(body, dict)
    return body


def _proposals(world: list[str]) -> list[dict[str, str]]:
    w = sorted(world)
    rows = [(w[0], "claims"), (w[0], "keyword"), (w[1], "claims"), (w[1], "vector")]
    return [
        {"work_id": wk, "source": src, "stance": "against", "anchor": ANCHOR, "quote": QUOTE}
        for wk, src in rows
    ]


@pytest.mark.anyio
async def test_a_role_run_is_served_its_assignment_once_and_writes_only_its_role(
    settings: Settings, project: Project, clock: FixedClock, world: list[str], v2_env: FakeLauncher
) -> None:
    request = cr.request_chat(
        project, project.human_actor(), "spar", SelectionSpec(), hypothesis="H", engine="v2",
        mode="prepare",
    ).request_id  # fmt: skip
    run = sv.advance(project, request, launcher=v2_env)
    assert run is not None
    cap = UnitCap(1, run)
    got = await _call(settings, clock, cap, "spar_role_next", **act("searcher"))
    assert got["ok"] is True, got
    task = got["data"]["batch"]
    assert task["role"] == "search" and task["request_id"] == request
    again = await _call(settings, clock, cap, "spar_role_next", **act("searcher"))
    assert again["ok"] is False and again["errors"][0]["field"] == "cap-reached"
    # the searcher opens the sheet for its request; the same call without the run is refused
    args: dict[str, Any] = {
        "hypothesis": "H", "proposals": _proposals(world), "mode": "prepare",
        "request_id": request, **act("searcher"),
    }  # fmt: skip
    refused = await _call(settings, clock, UnitCap(), "sheet_open", **args)
    assert refused["ok"] is False and refused["errors"][0]["field"] == "run"
    opened = await _call(settings, clock, cap, "sheet_open", **args)
    assert opened["ok"] is True, opened
    sheet = opened["data"]["info"]["sheet_id"]
    # a searcher run cannot argue, check, sweep or record a reading
    for tool, extra in (
        ("sheet_argue", {"sheet_id": sheet, "arguments": []}),
        ("sheet_check", {"checks": []}),
        ("spar_coverage_record", {"examined": []}),
        (
            "spar_reading_record",
            {"work_id": sorted(world)[0], "items": [], "sections_read": ["s1"]},
        ),
    ):
        out = await _call(settings, clock, cap, tool, **extra, **act("searcher"))
        assert out["ok"] is False, tool
    launcher_end = v2_env.processes[-1]
    launcher_end.release()
    assert runner.wait(run, 10)
    # the watcher started the first reader: its session reads the paper it was assigned
    reader_run = sv.progress(project, request).open_run
    assert reader_run is not None
    reader_cap = UnitCap(1, reader_run)
    first = await _call(settings, clock, reader_cap, "spar_role_next", **act("reader"))
    assert first["data"]["batch"]["role"] == "read"
    bad = await _call(
        settings, clock, reader_cap, "spar_reading_record", work_id=sorted(world)[0],
        items=[{"anchor": ANCHOR, "quote": "never said this", "stance": "for", "why": "w"}],
        sections_read=["s3"], **act("reader"),
    )  # fmt: skip
    assert bad["ok"] is False and bad["errors"][0]["field"] == "items[0].quote"
    good = await _call(
        settings, clock, reader_cap, "spar_reading_record", work_id=sorted(world)[0],
        items=[{"anchor": ANCHOR, "quote": QUOTE, "stance": "for", "why": "it says so"}],
        sections_read=["s3"], **act("reader"),
    )  # fmt: skip
    assert good["ok"] is True, good
    view = await _call(settings, clock, UnitCap(), "spar_readings_view", request_id=request)
    assert view["ok"] is True and view["data"]["readers"][0]["read"] is True
    v2_env.processes[-1].release()
    assert runner.wait(reader_run, 10)


def test_access_rows() -> None:
    for tool in ("spar_role_next", "spar_reading_record", "sheet_check", "spar_coverage_record"):
        assert TOOL_PERMISSIONS[tool] is Permission.WORK_RUN
    assert TOOL_PERMISSIONS["spar_readings_view"] is Permission.PROJECT_READ
    assert TOOL_PERMISSIONS["cli:chat advance"] is Permission.WORK_RUN


def test_cli_request_v2_list_and_advance(
    settings: Settings, project: Project, v2_env: FakeLauncher
) -> None:
    runner_ = CliRunner()
    env = {**_env(settings.root), "FACTORY_PLUGIN_DIR": str(settings.plugin_dir)}
    out = runner_.invoke(
        app,
        ["chat", "request", "spar", "Reflection helps", "--mode", "prepare", "--engine", "v2",
         "--max-sessions", "8"],
        env=env,
    )  # fmt: skip
    assert out.exit_code == 0 and "v2" in out.output, out.output
    bad = runner_.invoke(
        app, ["chat", "request", "spar", "h", "--engine", "v2", "--max-sessions", "2"], env=env
    )
    assert bad.exit_code != 0
    [row] = cr.list_requests(project)
    assert row.engine == "v2" and row.max_sessions == 8
    started = runner_.invoke(app, ["chat", "advance", row.request_id], env=env)
    assert started.exit_code == 0 and "started rnr_" in started.output, started.output
    listing = runner_.invoke(app, ["chat", "requests"], env=env)
    assert "v2 1/8 next search" in listing.output and "[taken]" in listing.output
    again = runner_.invoke(app, ["chat", "advance", row.request_id], env=env)
    assert again.exit_code == 2 and "open" in again.output  # one run at a time
    run = sv.progress(project, row.request_id).open_run
    assert run is not None
    v2_env.processes[-1].release()
    assert runner.wait(run, 10)
