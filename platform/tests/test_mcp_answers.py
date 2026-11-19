"""The answer MCP tools and the `factory answers` commands (plan N2)."""

# ruff: noqa: F811
from typing import Any

import pytest
from mcp import Client
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp import sessions as mcp_sessions
from factory.mcp.server import build_server
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import SESSION, open_session

ACT = {"role": "asker", "model": "claude-opus-5-5", "skill": "rf-screen"}
QUOTE = {"anchor": "s3.p1", "quote": "Lorem ipsum"}


async def _call(settings: Settings, clock: FixedClock, tool: str, **args: Any) -> dict[str, Any]:
    async with open_session(settings, clock) as client:
        return await client.call(tool, project="demo", **args)


@pytest.mark.anyio
async def test_answer_tools_and_human_rating(
    settings: Settings, project: Project, clock: FixedClock, world: list[str]
) -> None:
    work = sorted(world)[0]
    digest = resolve_selection_cached(project, SelectionSpec()).digest
    bad = await _call(
        settings, clock, "answer_record", question="q", selection_digest=digest,
        sentences=[{"text": "t", "work_id": work, "anchor": "s3.p1", "quote": "invented"}],
        **ACT,
    )  # fmt: skip
    assert bad["ok"] is False and bad["errors"][0]["field"] == "sentences[0].quote"
    stale = await _call(
        settings, clock, "answer_record", question="q", selection_digest="0" * 64,
        sentences=[{"text": "t", "work_id": work, **QUOTE}], **ACT,
    )  # fmt: skip
    assert stale["ok"] is False and stale["errors"][0]["field"] == "selection_digest"
    good = await _call(
        settings, clock, "answer_record", question="Does it help?", selection_digest=digest,
        sentences=[{"text": "It does.", "work_id": work, **QUOTE}],
        unanswered="Long-term effects are not covered.", **ACT,
    )  # fmt: skip
    assert good["ok"] is True, good
    answer = good["data"]["info"]["answer_id"]
    assert good["data"]["sentences"][0]["paragraph"]
    listed = await _call(settings, clock, "answer_list")
    assert [a["answer_id"] for a in listed["data"]["answers"]] == [answer]

    runner = CliRunner()
    env = _env(settings.root)
    rated = runner.invoke(
        app, ["answers", "rate", answer, "sound", "--sentence", "0", "--note", "ok"], env=env
    )
    assert rated.exit_code == 0, rated.stdout
    assert runner.invoke(app, ["answers", "rate", answer, "great"], env=env).exit_code != 0
    shown = runner.invoke(app, ["answers", "show", answer], env=env)
    assert shown.exit_code == 0 and "[sound]" in shown.stdout and "Lorem ipsum" in shown.stdout
    assert "Long-term effects" in shown.stdout
    view = await _call(settings, clock, "answer_view", answer_id=answer)
    assert view["data"]["sentences"][0]["rating"] == "sound"
    assert "1 answer" in runner.invoke(app, ["answers", "list"], env=env).stdout


@pytest.mark.anyio
async def test_no_rating_tool_exists(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {"answer_record", "answer_view", "answer_list"} <= names
    assert not {n for n in names if n.startswith("answer_") and "rate" in n}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (
            "answer_record",
            {
                "question": "q",
                "selection_digest": "d",
                "sentences": [{"text": "t", "work_id": "w", **QUOTE}],
            },
        ),
        ("answer_list", {}),
        ("answer_view", {"answer_id": "ans_X"}),
    ],
)
async def test_pass_session_is_refused_every_answer_tool(
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
    extra = ACT if tool == "answer_record" else {}
    out = await _call(settings, clock, tool, **args, **extra)
    assert out["ok"] is False and out["errors"][0]["field"] == "session", out
