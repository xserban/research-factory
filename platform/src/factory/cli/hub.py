"""`factory hub`: the hub v2 pages (plan hub-ui). Parses input, calls `services/hub_build`.

`hub build` is read-only on the project; it writes only under `--out`. The shared helpers of
`factory.cli.main` are imported inside the command, because that module imports this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

import factory.mcp.server  # noqa: F401  (registers the server builder for the tool catalog)
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.hub_facets import FacetPick
from factory.services import hub_build, hub_facets

hub_app = typer.Typer(
    name="hub",
    help="The hub v2 pages: build them as static files.",
    no_args_is_help=True,
)

facets_app = typer.Typer(
    name="facets",
    help="The facets of the hub: set them (the researcher) or show them.",
    no_args_is_help=True,
)
hub_app.add_typer(facets_app)


def parse_facet(text: str) -> FacetPick:
    """`miner:field` or `miner:field=Label` as a pick; raises typer.BadParameter otherwise."""
    spec, _, label = text.partition("=")
    miner, sep, name = spec.partition(":")
    if not sep or not miner or not name:
        raise typer.BadParameter(f"{text!r}: write miner:field or miner:field=Label")
    try:
        return FacetPick(miner=miner, field=name, label=label.strip() or None)
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(".".join(str(x) for x in e["loc"]) or "facet", e["msg"])
                for e in exc.errors()
            ]
        ) from None


@facets_app.command("set")
def facets_set_cmd(
    ctx: typer.Context,
    facet: Annotated[
        list[str],
        typer.Option(
            "--facet",
            help="An enum field of a listed miner as miner:field or miner:field=Label; repeat "
            "for each facet, in the order the hub shows them.",
        ),
    ],
) -> None:
    """Record the hub's facets (the researcher's act); the latest list replaces the earlier."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        picks = [parse_facet(f) for f in facet]
        project = _resolve_project(state)
        event_id = hub_facets.set_facets(project, project.human_actor(), picks)
    typer.echo(f"recorded {len(picks)} facets ({event_id})")


@facets_app.command("show")
def facets_show_cmd(ctx: typer.Context) -> None:
    """The facets the hub shows now: key, label, miner and field, in order."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        facets = hub_facets.facets_of(project)
    for f in facets:
        typer.echo(f"{f.key}\t{f.label}\t{f.miner}:{f.field}")


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
