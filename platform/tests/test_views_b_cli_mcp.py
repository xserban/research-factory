"""`view_coverage`, `view_timeline`, `view_horizon` and `factory view coverage|timeline|horizon`
(slice 7b, plan V-B, task 5).

The tools are agent paths: refused to a session that has joined a pass, refused before a screening
pass has opened (role-blind, one neutral message), scrubbed of held-out identifiers without hiding
any work. The commands are the researcher's: complete, and usable at any time.
"""

# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.services.context import Project
from factory.services.evidence_groups import group_index
from factory.services.horizon import horizon_view, timeline_view
from factory.services.view_coverage import coverage_view
from factory.services.views import to_json
from factory.views import render
from tests.cli_helpers import _env
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.helpers import open_session
from tests.test_mcp_lineage import _session
from tests.views_b_helpers import VbWorld, ext_b, vb_world  # noqa: F401

runner = CliRunner()
TOOLS = ("view_coverage", "view_timeline", "view_horizon")


def _args(project: Project, tool: str) -> dict[str, Any]:
    if tool != "view_timeline":
        return {"project": "demo"}
    gid = next(g.group_id for g in group_index(project) if dict(g.key)["task"] == "classification")
    return {"project": "demo", "group_id": gid}


@pytest.mark.anyio
@pytest.mark.parametrize("tool", TOOLS)
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    vb_world: VbWorld,
    ext_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
) -> None:
    args = _args(project, tool)
    _session(monkeypatch, ext_a.session)  # this session read an extraction pass
    async with open_session(settings, clock) as client:
        out = await client.call(tool, **args)
    assert out["ok"] is False and out["errors"][0]["field"] == "session"


@pytest.mark.anyio
@pytest.mark.parametrize("tool", TOOLS)
async def test_refused_until_a_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, tool: str
) -> None:
    args = (
        {"project": "demo", "group_id": "grp_000000000000"}
        if tool == "view_timeline"
        else {"project": "demo"}
    )
    async with open_session(settings, clock) as client:
        out = await client.call(tool, **args)
    assert out["ok"] is False
    assert out["errors"] == [{"field": "view", "reason": "not available yet"}]


@pytest.mark.anyio
async def test_returns_the_service_views(
    settings: Settings, project: Project, clock: FixedClock, vb_world: VbWorld
) -> None:
    async with open_session(settings, clock) as client:
        cov = await client.call("view_coverage", project="demo")
        hor = await client.call("view_horizon", project="demo")
        tim = await client.call("view_timeline", **_args(project, "view_timeline"))
    assert cov["ok"] and hor["ok"] and tim["ok"], (cov, hor, tim)
    assert cov["data"] == coverage_view(project).model_dump(mode="json")
    assert hor["data"] == horizon_view(project).model_dump(mode="json")
    gid = tim["data"]["group_id"]
    assert tim["data"] == timeline_view(project, gid).model_dump(mode="json")
    assert cov["data"]["cells"]


@pytest.mark.anyio
async def test_unknown_group_is_a_structured_error(
    settings: Settings, project: Project, clock: FixedClock, vb_world: VbWorld
) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call("view_timeline", project="demo", group_id="grp_000000000000")
    assert out["ok"] is False and out["errors"][0]["field"] == "group_id"


@pytest.mark.anyio
async def test_empty_views_on_a_screened_project_without_evidence_or_edges(
    settings: Settings, project: Project, clock: FixedClock, screened: list[str]
) -> None:
    with project.index.connect() as conn:
        opened = conn.execute(text("SELECT COUNT(*) FROM passes")).scalar_one()
    async with open_session(settings, clock) as client:
        cov = await client.call("view_coverage", project="demo")
        hor = await client.call("view_horizon", project="demo")
    assert opened > 0 and cov["ok"] and hor["ok"], (cov, hor)
    assert cov["data"]["cells"] == {} and hor["data"]["new_edges"] == {}
    assert "coverage-empty" in [n["code"] for n in cov["data"]["meta"]["notices"]]
    assert "horizon-empty" in [n["code"] for n in hor["data"]["meta"]["notices"]]


@pytest.mark.anyio
@pytest.mark.parametrize("tool", TOOLS)
async def test_output_is_scrubbed_without_hiding_work_ids(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    vb_world: VbWorld,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
) -> None:
    """Decision 37.9: only seed ids and stated identifiers are stripped; works stay ordinary."""
    args = _args(project, tool)
    calls: list[bool] = []
    real = mcp_server._held_out_tokens

    def spy(project: Project, include_work_ids: bool = True) -> set[str]:
        calls.append(include_work_ids)
        return real(project, include_work_ids)

    monkeypatch.setattr(mcp_server, "_held_out_tokens", spy)
    async with open_session(settings, clock) as client:
        out = await client.call(tool, **args)
    assert out["ok"] and calls and not any(calls)
    if tool == "view_timeline":
        blob = json.dumps(out["data"])
        assert vb_world.works[0] in blob  # a work id is shown as an ordinary corpus work


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_cli_works_on_a_fresh_project(settings: Settings, project: Project) -> None:
    for sub in ("coverage", "horizon"):
        code, out, err = _run(settings.root, "view", sub)
        assert code == 0, err
        assert "as_of" in out and "corpus-horizon" in out
    code, _, err = _run(settings.root, "view", "timeline", "grp_000000000000")
    assert code != 0 and "group_id" in err


def test_cli_outputs_equal_the_service(
    settings: Settings, project: Project, vb_world: VbWorld
) -> None:
    gid = _args(project, "view_timeline")["group_id"]
    cases = [
        (("coverage",), coverage_view, render.coverage_markdown, render.coverage_csv),
        (("horizon",), horizon_view, render.horizon_markdown, render.horizon_csv),
    ]
    for args, build, markdown, csv_ in cases:
        view = build(project)
        assert _run(settings.root, "view", *args, "--format", "json")[1] == to_json(view)
        assert _run(settings.root, "view", *args)[1] == markdown(view)
        assert _run(settings.root, "view", *args, "--format", "csv")[1] == csv_(view)
    tview = timeline_view(project, gid)
    assert _run(settings.root, "view", "timeline", gid, "--format", "json")[1] == to_json(tview)
    assert _run(settings.root, "view", "timeline", gid)[1] == render.timeline_markdown(tview)
    assert _run(settings.root, "view", "timeline", gid, "--format", "csv")[1] == (
        render.timeline_csv(tview)
    )


def test_cli_is_the_researchers_complete_view_before_any_pass(
    settings: Settings, project: Project
) -> None:
    code, out, err = _run(settings.root, "view", "coverage")
    assert code == 0, err
    assert out.startswith("# Coverage map")


def test_cli_writes_a_file_and_refuses_bad_format(
    settings: Settings, project: Project, tmp_path: Path
) -> None:
    target = tmp_path / "coverage.md"
    code, out, err = _run(settings.root, "view", "coverage", "--out", str(target))
    assert code == 0, err
    assert target.read_text().startswith("# Coverage map") and str(target) in out
    code, _, err = _run(settings.root, "view", "horizon", "--format", "svg")
    assert code != 0 and "format" in err
