"""`factory search slice`: the plan writes nothing; --run records every slice (IDEA-75)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.search import run_query
from tests.cli_helpers import _env
from tests.test_pubmed_slices import _parent, _world, small_cap  # noqa: F401

runner = CliRunner()


@pytest.mark.usefixtures("small_cap")
def test_plan_then_run(
    explore_project: Project, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, _ = _world(25)
    monkeypatch.setattr("factory.cli.main.default_sources", lambda: sources)
    parent = _parent(explore_project, sources)
    run_query(explore_project, parent, sources=sources)
    before = len(read_all(explore_project.paths.events_dir, explore_project.catalog))

    plan = runner.invoke(
        app,
        ["search", "slice", parent, "--first-year", "2020"],
        env=_env(settings.root),
    )
    assert plan.exit_code == 0, plan.output
    assert "5 slices, total 25 of 25" in plan.stdout
    assert len(read_all(explore_project.paths.events_dir, explore_project.catalog)) == before

    done = runner.invoke(
        app,
        ["search", "slice", parent, "--first-year", "2020", "--run"],
        env=_env(settings.root),
    )
    assert done.exit_code == 0, done.output
    assert "5 runs; slice total 25, unsplit 25" in done.stdout
