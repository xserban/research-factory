"""`factory costs` (plan restart-and-costs, C2): the run-cost report of the project, per stage,
model and miner, with `--stage` to narrow it and `--json` for the model's own fields.

It parses input, calls `services.run_costs` and formats the answer. It writes nothing. The helpers
of `factory.cli.main` are imported inside the command, because that module imports this one to
register the group. The root `--project` option selects the project, as for every command.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.services import run_costs

costs_app = typer.Typer(
    name="costs",
    help="Run costs per stage, model and miner: runs, units, cost, per unit, tokens, growth.",
    invoke_without_command=True,
)


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f} USD"


def _num(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:,.1f}{unit}"


@costs_app.callback(invoke_without_command=True)
def costs_cmd(
    ctx: typer.Context,
    stage: Annotated[
        str | None, typer.Option("--stage", help="Only this stage key (e.g. screen, mine:<id>).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the CostReport as JSON.")] = False,
) -> None:
    """Print the cost report. The cost is the API-equivalent price of the tokens, not a bill."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = run_costs.cost_report(project, stage=stage)
    if as_json:
        typer.echo(report.model_dump_json())
        return
    typer.echo(report.caveat)
    typer.echo(
        f"cost source: {report.cost_source} · runs: {report.runs} · units: {report.total_units} · "
        f"reported cost: {_money(report.total_reported_cost_usd)}"
    )
    for g in report.groups:
        seconds = None if g.median_duration_ms is None else g.median_duration_ms / 1000
        typer.echo(
            f"{g.stage} {g.model}: runs {g.runs} (complete {g.complete_runs}), units {g.units}, "
            f"cost {_money(g.reported_cost_usd)}, per unit {_money(g.cost_per_unit_usd)}, "
            f"median turns {_num(g.median_turns)}, median duration {_num(seconds, ' s')}"
        )
        per = g.tokens_per_unit
        typer.echo(
            "  tokens per unit: "
            + ", ".join(
                f"{kind} {_num(per.get(kind))}"
                for kind in ("input", "output", "cache_read", "cache_write")
            )
        )
