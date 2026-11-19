"""The sheet MCP tools and the `factory sheets` commands (plan chat T7)."""

# ruff: noqa: F811
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp import sessions as mcp_sessions
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import SESSION, open_session

ACT = {"role": "spar-a", "model": "claude-opus-5-5", "skill": "rf-screen"}
PROP = {"anchor": "s3.p1", "quote": "Lorem ipsum"}


async def _call(settings: Settings, clock: FixedClock, tool: str, **args: Any) -> dict[str, Any]:
    async with open_session(settings, clock) as client:
        return await client.call(tool, project="demo", **args)


@pytest.mark.anyio
async def test_sheet_tools_and_human_rating(
    settings: Settings, project: Project, clock: FixedClock, world: list[str], tmp_path: Path
) -> None:
    work = sorted(world)[0]
    opened = await _call(
        settings,
        clock,
        "sheet_open",
        hypothesis="Reflection helps",
        proposals=[{"work_id": work, "source": "claims", "stance": "against", **PROP}],
        **ACT,
    )
    assert opened["ok"] is True, opened
    sheet = opened["data"]["info"]["sheet_id"]
    assert opened["data"]["coverage"]["total"] == len(world)

    bad = await _call(
        settings,
        clock,
        "sheet_argue",
        sheet_id=sheet,
        arguments=[
            {
                "stance": "against",
                "work_id": work,
                "anchor": "s3.p1",
                "quote": "invented",
                "claim": "c",
                "strength": "weak",
            }
        ],
        **ACT,
    )
    assert bad["ok"] is False and bad["errors"][0]["field"] == "arguments[0].quote"
    early = await _call(
        settings, clock, "sheet_argue", sheet_id=sheet,
        arguments=[{"stance": "for", "work_id": work, "claim": "c", "strength": "weak", **PROP}],
        **ACT,
    )  # fmt: skip
    assert early["ok"] is False and early["errors"][0]["field"] == "stance"

    good = await _call(
        settings, clock, "sheet_argue", sheet_id=sheet,
        arguments=[
            {"stance": "against", "work_id": work, "claim": "c", "strength": "weak", **PROP}
        ],
        **ACT,
    )  # fmt: skip
    assert good["ok"] is True, good
    argument = good["data"]["recorded"][0]["argument_id"]
    closed = await _call(settings, clock, "sheet_close", sheet_id=sheet, section="against", **ACT)
    assert closed["ok"] is True, closed
    listed = await _call(settings, clock, "sheet_list")
    assert [s["sheet_id"] for s in listed["data"]["sheets"]] == [sheet]

    runner = CliRunner()
    env = _env(settings.root)
    rated = runner.invoke(app, ["sheets", "rate", argument, "sound", "--note", "ok"], env=env)
    assert rated.exit_code == 0, rated.stdout
    shown = runner.invoke(app, ["sheets", "show", sheet], env=env)
    assert shown.exit_code == 0 and "[sound]" in shown.stdout and "judgement" in shown.stdout
    assert "No balance is stated" in shown.stdout
    view = await _call(settings, clock, "sheet_view", sheet_id=sheet)
    assert view["data"]["arguments"][0]["rating"] == "sound"
    assert runner.invoke(app, ["sheets", "rate", argument, "great"], env=env).exit_code != 0
    assert "against closed" in runner.invoke(app, ["sheets", "list"], env=env).stdout


@pytest.mark.anyio
async def test_balance_is_cli_only_and_the_view_shows_it_first(
    settings: Settings, project: Project, clock: FixedClock, world: list[str]
) -> None:
    work = sorted(world)[0]
    opened = await _call(
        settings, clock, "sheet_open", hypothesis="Reflection helps",
        proposals=[{"work_id": work, "source": "claims", "stance": "against", **PROP}], **ACT,
    )  # fmt: skip
    sheet = opened["data"]["info"]["sheet_id"]
    claim = {"work_id": work, "claim": "c", "strength": "weak", **PROP}
    for stance in ("against", "for"):
        done = await _call(
            settings, clock, "sheet_argue", sheet_id=sheet,
            arguments=[{"stance": stance, **claim}], **ACT,
        )  # fmt: skip
        assert done["ok"] is True, done
        closed = await _call(settings, clock, "sheet_close", sheet_id=sheet, section=stance, **ACT)
        assert closed["ok"] is True, closed
    runner = CliRunner()
    env = _env(settings.root)
    early = await _call(settings, clock, "sheet_view", sheet_id=sheet)
    assert early["data"]["balance"] is None and early["data"]["balance_history"] == 0
    wrote = runner.invoke(
        app,
        [
            "sheets",
            "balance",
            sheet,
            "--text",
            "Mixed.",
            "--lean",
            "mixed",
            "--note",
            "a replication",
        ],
        env=env,
    )
    assert wrote.exit_code == 0, wrote.stdout
    bad = runner.invoke(app, ["sheets", "balance", sheet, "--text", "x", "--lean", "yes"], env=env)
    assert bad.exit_code != 0
    view = await _call(settings, clock, "sheet_view", sheet_id=sheet)
    data = view["data"]
    assert list(data)[:2] == ["balance", "balance_history"]
    assert data["balance"]["text"] == "Mixed." and data["balance"]["lean"] == "mixed"
    assert data["balance_history"] == 1
    shown = runner.invoke(app, ["sheets", "show", sheet], env=env)
    assert shown.stdout.index("balance (researcher's") < shown.stdout.index("claim:")
    # no MCP tool writes the balance: test_mcp_server pins the exact tool list


_ARGUE = [{"stance": "against", "work_id": "w", "claim": "c", "strength": "weak", **PROP}]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("sheet_open", {"hypothesis": "h", "proposals": []}),
        ("sheet_argue", {"sheet_id": "sht_X", "arguments": _ARGUE}),
        ("sheet_close", {"sheet_id": "sht_X", "section": "against"}),
        ("sheet_list", {}),
        ("sheet_view", {"sheet_id": "sht_X"}),
    ],
)
async def test_pass_session_is_refused_every_sheet_tool(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    args: dict[str, Any],
) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return SESSION  # the session that screened: a pass member

    monkeypatch.setattr(mcp_sessions, "IdGenerator", Ids)
    extra = {} if tool in ("sheet_list", "sheet_view") else ACT
    out = await _call(settings, clock, tool, **args, **extra)
    assert out["ok"] is False and out["errors"][0]["field"] == "session", out
