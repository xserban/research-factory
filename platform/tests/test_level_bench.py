"""Level benchmark metrics (plan tiers-and-autonomy, C9): the service and `factory bench level`."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.services import level_bench
from factory.services.cli_access import CLI_READS
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.test_run_costs import RUN_A, _finish, _log_bytes, _start, _synthetic_log


def _one_run(project: Project) -> None:
    blob = project.blobs.put(_log_bytes(_synthetic_log()))
    _start(project, RUN_A, "screen", {"screen": 10})
    _finish(project, RUN_A, {"screen": 6}, blob)


def test_empty_project_gives_none_not_zero(project: Project) -> None:
    metrics = level_bench.level_metrics(project)
    assert metrics.project == "demo"
    assert metrics.rigor_mode == "pilot"
    assert metrics.runner_runs == 0
    assert metrics.reported_cost_usd is None
    assert metrics.recall_development is None
    assert metrics.recall_held_out is None
    assert metrics.overturn_rate is None
    assert metrics.gates_closed == {}
    assert metrics.events >= 1
    assert "overturn_rate" in metrics.unavailable
    assert "project" in metrics.events_by_family


def test_runs_tokens_and_cost_come_from_the_run_logs(project: Project) -> None:
    _one_run(project)
    metrics = level_bench.level_metrics(project)
    assert metrics.runner_runs == 1
    assert metrics.runner_runs_complete == 1
    assert metrics.reported_cost_usd == pytest.approx(0.5)
    assert metrics.input_tokens == 14
    assert metrics.output_tokens == 14
    assert metrics.cache_read_tokens == 600
    assert metrics.cache_write_tokens == 70
    assert metrics.events_by_family["runner"] == 2
    assert metrics.elapsed_seconds is not None and metrics.elapsed_seconds >= 0


def test_metrics_write_no_event(project: Project) -> None:
    before = level_bench.level_metrics(project).events
    level_bench.level_metrics(project)
    assert level_bench.level_metrics(project).events == before


def test_table_marks_missing_figures(project: Project) -> None:
    text = level_bench.render_table(level_bench.level_metrics(project))
    assert "overturn rate" in text
    line = next(row for row in text.splitlines() if row.startswith("overturn rate"))
    assert line.rstrip().endswith("-")


def test_command_is_a_registered_read() -> None:
    assert "cli:bench level" in CLI_READS


def test_cli_json_and_table(project: Project) -> None:
    _one_run(project)
    runner = CliRunner()
    env = _env(project.settings.root)
    as_json = runner.invoke(app, ["bench", "level", "demo", "--format", "json"], env=env)
    assert as_json.exit_code == 0, as_json.output
    loaded: Any = json.loads(as_json.output)
    assert loaded["runner_runs"] == 1
    table = runner.invoke(app, ["bench", "level", "demo"], env=env)
    assert table.exit_code == 0, table.output
    assert "runner runs" in table.output
    bad = runner.invoke(app, ["bench", "level", "demo", "--format", "xml"], env=env)
    assert bad.exit_code == 2
