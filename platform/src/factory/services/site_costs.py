# ruff: noqa: E501
"""The run-costs product (plan restart-and-costs, C2): one table per stage, model and miner, and a
token-growth chart per stage. Every number is computed by `services.run_costs`; the caveat on
what the figures are travels with the page. All text is escaped by the table and note helpers."""

from __future__ import annotations

from pathlib import Path

from factory.services.context import Project
from factory.services.run_costs import CostGroup, cost_report, runs_with_logs, token_growth
from factory.services.site_charts import line_chart
from factory.services.site_widgets import REPORT_CSS, note, section, table

HEADERS = [
    "stage",
    "model",
    "runs",
    "complete",
    "units",
    "reported cost (USD)",
    "cost per unit (USD)",
    "median turns",
    "median duration (s)",
    "input per unit",
    "output per unit",
    "cache read per unit",
    "cache write per unit",
]


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _num(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def _row(group: CostGroup) -> list[object]:
    per = group.tokens_per_unit
    return [
        group.stage,
        group.model,
        group.runs,
        group.complete_runs,
        group.units,
        _money(group.reported_cost_usd),
        _money(group.cost_per_unit_usd),
        _num(group.median_turns),
        _num(None if group.median_duration_ms is None else group.median_duration_ms / 1000),
        _num(per.get("input"), 0),
        _num(per.get("output"), 0),
        _num(per.get("cache_read"), 0),
        _num(per.get("cache_write"), 0),
    ]


def build_costs(project: Project, out: Path) -> None:
    from factory.services.site import page

    runs = runs_with_logs(project)  # each log is read and parsed once
    report = cost_report(project, runs=runs)
    if not report.groups:
        body = (
            "<h1>Run costs</h1>"
            + note(report.caveat)
            + "<p class=dim>No headless run is recorded for this project yet.</p>"
        )
    else:
        stages = sorted({g.stage for g in report.groups})
        charts = []
        for stage in stages:
            points = [
                (float(p.turn), p.mean_context_tokens)
                for p in token_growth(project, stage, runs=runs)
            ]
            svg = line_chart(points, "turn", "input + cache read tokens")
            if svg:
                charts.append(section(f"Token growth: {stage}", svg))
        body = (
            "<h1>Run costs</h1>"
            + note(report.caveat)
            + f"<p class=dim>cost source: {report.cost_source} · runs: {report.runs} · units: "
            f"{report.total_units} · reported cost: {_money(report.total_reported_cost_usd)} USD</p>"
            + section(
                "Per stage, model and miner",
                table(HEADERS, [_row(g) for g in report.groups]),
            )
            + section(
                "What the columns mean",
                "<ul><li><b>Units</b>: the records or tasks the run served, counted by the MCP "
                "unit counter when it wrote one, else from the queue counts.</li>"
                "<li><b>Reported cost</b>: the total of the runs that reported a cost.</li>"
                "<li><b>Cost per unit</b>: the reported cost of the runs that reported a cost "
                "and served units, divided by those units; a priced run with no units is in the "
                "total but not in this figure.</li>"
                "<li><b>Per unit</b> token columns: tokens of each kind over the units of the "
                "runs that served any.</li>"
                "<li><b>Token growth</b>: each turn re-reads the transcript, so the input and "
                "cache-read tokens of a turn grow with its position in the run.</li></ul>",
            )
            + "".join(charts)
        )
    (out / "index.html").write_text(page("Run costs", body, REPORT_CSS), encoding="utf-8")
