"""`factory bench level` (plan tiers-and-autonomy, C9): benchmark metrics of one study.

It parses input, calls `services.level_bench` and formats the answer. It writes nothing. The
helpers of `factory.cli.main` are imported inside the command, because that module imports this
one to register the group.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.services import level_bench

bench_app = typer.Typer(
    name="bench",
    help="Benchmark metrics for comparing tiers and autonomy levels (read-only).",
    no_args_is_help=True,
)


@bench_app.command("level")
def level_cmd(
    ctx: typer.Context,
    project: Annotated[
        str | None, typer.Argument(help="Project slug (default: the --project option).")
    ] = None,
    fmt: Annotated[str, typer.Option("--format", help="json or table.")] = "table",
) -> None:
    """Print the level metrics of a study: counts, time, runs, tokens, recall, agreement, gates."""
    from factory.cli.main import _fail, _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    if fmt not in ("json", "table"):
        _fail(f"--format: expected json or table, got {fmt!r}", 2)
    if project is not None:
        state.project = project
    with _reporting_errors():
        metrics = level_bench.level_metrics(_resolve_project(state))
    typer.echo(metrics.model_dump_json() if fmt == "json" else level_bench.render_table(metrics))
