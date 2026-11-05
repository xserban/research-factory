"""The onion view on projects with nothing to expand (real events, no direct index writes)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.services.context import Project
from factory.services.onion import onion_view
from factory.services.views import to_json
from tests.cli_helpers import _env
from tests.extraction_helpers import screened  # noqa: F401
from tests.helpers import open_session

runner = CliRunner()


def test_fresh_project_returns_empty_rings_with_a_notice(project: Project) -> None:
    view = onion_view(project)
    assert [r.total for r in view.rings] == [0, 0, 0]
    assert "focus-empty" in [n.code for n in view.meta.notices]
    assert view.edges_considered == {"builds-on": 0, "cites": 0, "improves-on": 0}


def test_screened_project_without_edges(project: Project, screened: list[str]) -> None:
    view = onion_view(project)
    assert [r.total for r in view.rings] == [len(screened), 0, 0]
    assert "focus-empty" not in [n.code for n in view.meta.notices]
    assert to_json(onion_view(project, agent=True))


def test_cli_on_both(settings: Settings, project: Project) -> None:
    result = runner.invoke(app, ["view", "onion", "--format", "json"], env=_env(settings.root))
    assert result.exit_code == 0, result.stderr


def test_cli_on_screened(settings: Settings, project: Project, screened: list[str]) -> None:
    result = runner.invoke(app, ["view", "onion"], env=_env(settings.root))
    assert result.exit_code == 0, result.stderr


@pytest.mark.anyio
async def test_mcp_on_screened_project(
    settings: Settings, project: Project, screened: list[str], clock: FixedClock
) -> None:
    with project.index.connect() as conn:
        opened = conn.execute(text("SELECT COUNT(*) FROM passes")).scalar_one()
    async with open_session(settings, clock) as client:
        out = await client.call("view_onion", project="demo")
    assert opened > 0
    assert out["ok"] is True, out
    assert [r["total"] for r in out["data"]["rings"]][1:] == [0, 0]
