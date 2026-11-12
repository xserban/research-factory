"""Run costs (plan restart-and-costs, C2): the cost report, token growth, CLI and hub page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.model.runner import RunnerStarted
from factory.services import run_costs, site_costs
from factory.services.context import Project
from factory.services.run_costs import CostGroup, CostReport, TurnPoint
from tests.cli_helpers import _env
from tests.test_run_costs import RUN_A, RUN_B, _assistant, _finish, _log_bytes, _result

RUN_C = "rnr_01CRZ3NDEKTSV4RRFFQ69G5FAV"
RUN_D = "rnr_01DRZ3NDEKTSV4RRFFQ69G5FAV"


def _start(
    project: Project,
    run_id: str,
    stage: str,
    before: dict[str, int],
    model: str = "claude-test",
) -> None:
    payload = RunnerStarted(
        run_id=run_id,
        stage=stage,
        model=model,
        allowed_tools=("mcp__factory__screen_next",),
        prompt_blob=project.blobs.put(b"prompt"),
        unit_cap=25,
        counts_before=before,
        command=("claude", "-p"),
    )
    project.record([project.events.make("runner.started", payload, project.system_actor())])


def _run(
    project: Project,
    run_id: str,
    stage: str,
    units: int,
    lines: list[str],
    model: str = "claude-test",
    before: int = 10,
) -> None:
    """A finished run that served `units` units, with the given log."""
    blob = project.blobs.put(_log_bytes(lines))
    _start(project, run_id, stage, {stage: before}, model)
    _finish(project, run_id, {stage: before - units}, blob)


def _log(cost: float, turns: int, duration_ms: int = 1000) -> list[str]:
    """A complete log with `turns` assistant messages of 10 input, 5 output, 100 read, 20 write
    tokens each, and a result line with `cost` and `duration_ms`."""
    lines = [_assistant(f"m{i}", 10, 5, 100, 20) for i in range(turns)]
    result = json.loads(_result(cost))
    result["duration_ms"] = duration_ms
    result["num_turns"] = turns
    lines.append(json.dumps(result))
    return lines


def test_groups_by_stage_and_model_with_per_unit_figures(project: Project) -> None:
    _run(project, RUN_A, "screen", 4, _log(0.5, 3))
    _run(project, RUN_B, "screen", 6, _log(1.5, 3))
    _run(project, RUN_C, "screen", 0, _log(0.25, 3), model="claude-other")
    report = run_costs.cost_report(project)

    assert isinstance(report, CostReport)
    assert report.cost_source == "reported-by-cli"
    assert report.caveat and "not as a bill" in report.caveat
    assert report.runs == 3 and report.total_units == 10
    assert report.total_reported_cost_usd == pytest.approx(2.25)
    assert [(g.stage, g.model) for g in report.groups] == [
        ("screen", "claude-other"),
        ("screen", "claude-test"),
    ]
    other, test = report.groups
    assert other.runs == 1 and other.units == 0
    assert other.reported_cost_usd == pytest.approx(0.25)
    assert other.cost_per_unit_usd is None
    assert other.tokens_per_unit == {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
    }
    assert test.runs == 2 and test.complete_runs == 2
    assert test.units == 10
    assert test.reported_cost_usd == pytest.approx(2.0)
    assert test.cost_per_unit_usd == pytest.approx(0.2)
    # Per unit: 2 runs, 10 input tokens per turn, 3 turns each: 60 input over 10 units.
    assert test.tokens_per_unit["input"] == pytest.approx(60 / 10)
    assert test.tokens_per_unit["output"] == pytest.approx(30 / 10)
    assert test.tokens_per_unit["cache_read"] == pytest.approx(600 / 10)
    assert test.tokens_per_unit["cache_write"] == pytest.approx(120 / 10)
    assert test.miner is None


def test_miner_stage_is_a_group_of_its_own(project: Project) -> None:
    _run(project, RUN_A, "mine:m-alpha", 2, _log(0.4, 2))
    _run(project, RUN_B, "mine:m-beta", 2, _log(0.8, 2))
    report = run_costs.cost_report(project)
    assert [g.stage for g in report.groups] == ["mine:m-alpha", "mine:m-beta"]
    assert [g.miner for g in report.groups] == ["m-alpha", "m-beta"]


def test_medians_over_complete_runs(project: Project) -> None:
    _run(project, RUN_A, "screen", 2, _log(0.1, 1, duration_ms=1000))
    _run(project, RUN_B, "screen", 2, _log(0.1, 2, duration_ms=2000))
    _run(project, RUN_C, "screen", 2, _log(0.1, 9, duration_ms=9000))
    _run(project, RUN_D, "screen", 2, _log(0.1, 3, duration_ms=3000))
    group = run_costs.cost_report(project).groups[0]
    assert group.complete_runs == 4
    assert group.median_turns == pytest.approx(2.5)
    assert group.median_duration_ms == pytest.approx(2500.0)


def test_an_incomplete_run_is_counted_but_not_in_the_medians(project: Project) -> None:
    _run(project, RUN_A, "screen", 2, _log(0.1, 2, duration_ms=1000))
    _run(project, RUN_B, "screen", 2, [_assistant("m1", 1, 1, 0, 0)])
    group = run_costs.cost_report(project).groups[0]
    assert group.runs == 2 and group.complete_runs == 1
    assert group.median_turns == pytest.approx(2.0)
    assert group.median_duration_ms == pytest.approx(1000.0)


def test_stage_filter_narrows_the_report(project: Project) -> None:
    _run(project, RUN_A, "screen", 2, _log(0.1, 1))
    _run(project, RUN_B, "extract", 2, _log(0.2, 1))
    report = run_costs.cost_report(project, stage="extract")
    assert report.runs == 1
    assert [g.stage for g in report.groups] == ["extract"]


def test_empty_project_gives_an_empty_report(project: Project) -> None:
    report = run_costs.cost_report(project)
    assert report.runs == 0 and report.groups == []
    assert report.total_reported_cost_usd is None


def test_token_growth_is_the_mean_context_per_turn(project: Project) -> None:
    first = [
        _assistant("a1", 10, 1, 100, 0),
        _assistant("a2", 20, 1, 300, 0),
        _result(0.1),
    ]
    second = [_assistant("b1", 30, 1, 500, 0), _result(0.1)]
    _run(project, RUN_A, "screen", 1, first)
    _run(project, RUN_B, "screen", 1, second)
    _run(project, RUN_C, "extract", 1, [_assistant("c1", 1, 1, 1, 0), _result(0.1)])

    growth = run_costs.token_growth(project, "screen")
    assert [(p.turn, p.runs) for p in growth] == [(1, 2), (2, 1)]
    assert isinstance(growth[0], TurnPoint)
    assert growth[0].mean_context_tokens == pytest.approx((110 + 530) / 2)
    assert growth[1].mean_context_tokens == pytest.approx(320)
    assert run_costs.token_growth(project, "appraise") == []


def test_the_page_states_the_caveat_and_shows_the_figures(project: Project, tmp_path: Path) -> None:
    _run(project, RUN_A, "screen", 4, _log(0.5, 3))
    site_costs.build_costs(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "not as a bill" in page
    assert "reported-by-cli" in page
    assert "claude-test" in page and "0.5000" in page
    assert "Token growth: screen" in page
    assert "<polyline" in page


def test_the_page_says_so_when_there_are_no_runs(project: Project, tmp_path: Path) -> None:
    site_costs.build_costs(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "No headless run is recorded" in page
    assert "not as a bill" in page


def test_the_page_escapes_a_malicious_model_label(project: Project, tmp_path: Path) -> None:
    _run(project, RUN_A, "screen", 2, _log(0.1, 1), model="<img src=x onerror=alert(1)>")
    site_costs.build_costs(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<img src=x" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_the_page_escapes_a_malicious_stage_label(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A stage key is validated when recorded, so the label is supplied by the report instead.
    evil = "<script>alert('x')</script>"
    group = CostGroup(
        stage=evil,
        miner=None,
        model="claude-test",
        runs=1,
        complete_runs=1,
        units=1,
        reported_cost_usd=0.1,
        cost_per_unit_usd=0.1,
        median_turns=1.0,
        median_duration_ms=1000.0,
        tokens_per_unit={"input": 1.0, "output": 1.0, "cache_read": 0.0, "cache_write": 0.0},
    )
    report = CostReport(
        cost_source="reported-by-cli",
        caveat=run_costs.CAVEAT,
        runs=1,
        total_units=1,
        total_reported_cost_usd=0.1,
        groups=[group],
    )
    monkeypatch.setattr(site_costs, "cost_report", lambda _project, runs=None: report)
    monkeypatch.setattr(
        site_costs,
        "token_growth",
        lambda _project, _stage, runs=None: [TurnPoint(turn=1, runs=1, mean_context_tokens=110.0)],
    )
    site_costs.build_costs(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(" in page


def test_line_chart_is_empty_without_points_and_draws_a_polyline() -> None:
    from factory.services.site_charts import line_chart

    assert line_chart([], "turn", "tokens") == ""
    svg = line_chart([(1.0, 100.0), (2.0, 250.0)], "turn", "tokens")
    assert "<polyline" in svg and "<svg" in svg
    single = line_chart([(1.0, 5.0)], "turn", "tokens")
    assert "<polyline" in single


def test_cli_prints_the_report_and_json(project: Project) -> None:
    from factory.cli.main import app

    _run(project, RUN_A, "screen", 4, _log(0.5, 2))
    runner = CliRunner()
    env = _env(project.settings.root)
    text = runner.invoke(app, ["--project", project.paths.slug, "costs"], env=env)
    assert text.exit_code == 0, text.output
    assert "not as a bill" in text.output
    assert "screen claude-test" in text.output
    as_json = runner.invoke(app, ["--project", project.paths.slug, "costs", "--json"], env=env)
    assert as_json.exit_code == 0, as_json.output
    loaded: Any = json.loads(as_json.output)
    assert loaded["cost_source"] == "reported-by-cli"
    assert loaded["groups"][0]["units"] == 4
    narrowed = runner.invoke(
        app,
        ["--project", project.paths.slug, "costs", "--stage", "extract", "--json"],
        env=env,
    )
    assert json.loads(narrowed.output)["runs"] == 0


def test_the_costs_row_is_read_only() -> None:
    from factory.services.access import TOOL_PERMISSIONS, Permission

    assert TOOL_PERMISSIONS["cli:costs"] is Permission.PROJECT_READ


def test_the_costs_product_reads_runner_events() -> None:
    from factory.services.site import products

    costs = next(p for p in products() if p.id == "costs")
    assert costs.inputs == ("runner.%",)
    assert costs.group == "Overview" and costs.entry == "index.html"
