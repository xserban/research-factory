"""`factory hub`: the hub v2 pages (plan hub-ui). Parses input, calls `services/hub_build`.

`hub build` is read-only on the project; it writes only under `--out`. The shared helpers of
`factory.cli.main` are imported inside the command, because that module imports this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from factory.services import hub_build

hub_app = typer.Typer(
    name="hub",
    help="The hub v2 pages: build them as static files.",
    no_args_is_help=True,
)


@hub_app.command("build")
def hub_build_cmd(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Project slug.")],
    out: Annotated[Path, typer.Option("--out", help="Directory to write the pages into.")],
    only: Annotated[
        str | None, typer.Option("--only", help="Comma-separated payload names to build.")
    ] = None,
    payloads_only: Annotated[
        bool,
        typer.Option(
            "--payloads-only",
            help="Write only data/<name>.json and .json.gz (the served hub's child build).",
        ),
    ] = False,
) -> None:
    """Write the static pages, assets and payloads to `--out` (opens from file://)."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    state.project = slug
    names = [n.strip() for n in only.split(",") if n.strip()] if only else None
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            report = hub_build.build_static(project, out, only=names, payloads_only=payloads_only)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    for line in hub_build.format_report(report):
        typer.echo(line)
    typer.echo(f"out: {out}")
    if report.errors:
        raise typer.Exit(1)
