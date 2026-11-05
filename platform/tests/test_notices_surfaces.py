"""The `notices` and `versions` CLI groups and the `notice_list` / `notice_assess` MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.notices import NoticeKind
from factory.services.context import Project
from tests.helpers import SourcesFor, open_session
from tests.notice_helpers import (
    NoticeWorld,
    StatusScript,
    check_in_cycle,
    crossref_notices,
    declare_schema,
    dependent_world,
    notice_record,
    numbered_records,
    status_factories,
)
from tests.test_cli import _env
from tests.watch_helpers import ScriptedSource, adapters, by_text

runner = CliRunner()
AGENT = {"role": "watcher", "model": "claude-sonnet-5-5", "skill": "rf-screen"}


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    built = dependent_world(project, agent, human, mock_sources, numbered_records(3))
    declare_schema(project, agent)
    retracted, corrected = built.included[0], built.included[1]
    d1, d2 = built.doi(retracted), built.doi(corrected)
    assert d1 is not None and d2 is not None
    crossref = StatusScript(
        "crossref",
        crossref_notices(
            {
                d1: [notice_record(d1, NoticeKind.RETRACTION, "10.2000/r1")],
                d2: [notice_record(d2, NoticeKind.CORRECTION, "10.2000/c1")],
            }
        ),
    )
    check_in_cycle(project, status_factories(crossref=crossref, openalex=StatusScript("openalex")))
    return built


def _ids(world: NoticeWorld) -> dict[str, str]:
    events = read_all(world.project.paths.events_dir, world.project.catalog)
    return {
        str(e.payload["kind"]): str(e.payload["notice_id"])
        for e in events
        if e.type == "notice.observed"
    }


def test_cli_notices_list_and_assess(world: NoticeWorld, settings: Settings) -> None:
    ids = _ids(world)
    code, out, _ = _cli(settings.root, "notices", "list")
    assert code == 0 and out.count("unassessed") == 2
    assert "date not stated by source" in out or "10" in out
    code, _, err = _cli(
        settings.root,
        "notices",
        "assess",
        ids["correction"],
        "--decision",
        "affects",
        "--rationale",
        "table corrected",
    )
    assert code == 1 and "fields" in err  # affects needs a field
    code, out, _ = _cli(
        settings.root,
        "notices",
        "assess",
        ids["correction"],
        "--decision",
        "affects",
        "--field",
        "value",
        "--rationale",
        "table corrected",
    )
    assert code == 0 and "assessed" in out
    code, out, _ = _cli(settings.root, "notices", "list")
    assert "affects" in out and out.count("unassessed") == 1
    events = read_all(world.project.paths.events_dir, world.project.catalog)
    [assessed] = [e for e in events if e.type == "notice.assessed"]
    assert assessed.actor.kind == "human"


def test_cli_versions_list_empty(world: NoticeWorld, settings: Settings) -> None:
    code, out, _ = _cli(settings.root, "versions", "list")
    assert code == 0 and out.strip() == ""


@pytest.mark.anyio
async def test_mcp_notice_list_hides_held_out_and_assess_is_relayed(
    world: NoticeWorld,
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _ids(world)
    held_out = world.included[0]  # the retracted work is a held-out seed's work
    monkeypatch.setattr(
        "factory.mcp.server.seeds_service.held_out_work_ids", lambda _p: frozenset({held_out})
    )
    source = ScriptedSource(by_text({}))
    async with open_session(settings, clock, dict(adapters(source))) as session:
        listed = await session.call("notice_list", project="demo", **AGENT)
        hidden = await session.call(
            "notice_assess",
            project="demo",
            notice_id=ids["retraction"],
            decision="exclude",
            rationale="retracted",
        )
        shown = await session.call(
            "notice_assess",
            project="demo",
            notice_id=ids["correction"],
            decision="no-effect",
            rationale="typo only",
        )
    assert listed["ok"] is True, listed
    data: dict[str, Any] = listed["data"]
    assert data["count"] == 1 and data["notices"][0]["kind"] == "correction"
    assert held_out not in str(listed) and ids["retraction"] not in str(listed)
    # A notice of a held-out work is unknown to the agent, exactly as a missing one is.
    assert hidden["ok"] is False and hidden["errors"][0]["field"] == "notice_id"
    assert shown["ok"] is True
    events = read_all(world.project.paths.events_dir, world.project.catalog)
    [assessed] = [e for e in events if e.type == "notice.assessed"]
    assert assessed.actor.kind == "human"
