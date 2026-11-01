"""The `factory` command: parse arguments, call a service, format output. No business logic here."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.mcp.server import run
from factory.model.identity import IdGenerator
from factory.model.work import ProvenanceMethod
from factory.services import project as project_service
from factory.services import protocol as protocol_service
from factory.services import seeds as seeds_service
from factory.services.context import Project, list_projects, open_project

app = typer.Typer(
    name="factory",
    help="Research Factory platform CLI.",
    no_args_is_help=True,
    add_completion=False,
)
seeds_app = typer.Typer(
    name="seeds",
    help="List the seeds with their hold-out roles, draw the split, explain a miss.",
    invoke_without_command=True,
    no_args_is_help=False,
)
protocol_app = typer.Typer(name="protocol", help="Confirm PRESS reviews.", no_args_is_help=True)
app.add_typer(seeds_app)
app.add_typer(protocol_app)


@dataclass
class CliState:
    settings: Settings
    project: str | None
    session: str
    clock: Clock


def _state(ctx: typer.Context) -> CliState:
    state = ctx.obj
    if not isinstance(state, CliState):
        raise RuntimeError("CLI state missing; the root callback did not run")
    return state


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


@contextmanager
def _reporting_errors() -> Iterator[None]:
    """Turn service errors into stderr lines and exit 1. Nothing is written on these paths."""
    try:
        yield
    except FactoryValidationError as exc:
        for issue in exc.issues:
            typer.echo(f"{issue.field}: {issue.reason}", err=True)
        raise typer.Exit(1) from None
    except ProjectNotFoundError as exc:
        _fail(str(exc), 1)


def _resolve_project(state: CliState) -> Project:
    """Open the `--project` slug, or the only project under the root. Ambiguity is exit 2."""
    if state.project is not None:
        try:
            return open_project(
                state.settings, state.project, session=state.session, clock=state.clock
            )
        except ProjectNotFoundError:
            _fail(f"unknown project: {state.project}", 1)
    slugs = list_projects(state.settings)
    if not slugs:
        _fail("no project; run factory init", 2)
    if len(slugs) > 1:
        _fail(f"several projects: {', '.join(slugs)}; pass --project", 2)
    return open_project(state.settings, slugs[0], session=state.session, clock=state.clock)


@app.callback()
def main(
    ctx: typer.Context,
    root: Annotated[
        Path | None,
        typer.Option(help="Factory root directory.", envvar="FACTORY_ROOT"),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Project slug.", envvar="FACTORY_PROJECT"),
    ] = None,
) -> None:
    clock = SystemClock()
    with _reporting_errors():
        settings = Settings.load(root=root)
    ctx.obj = CliState(
        settings=settings,
        project=project,
        session=IdGenerator(clock).ulid(),
        clock=clock,
    )


@app.command()
def init(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="New project slug.")],
    mode: Annotated[str, typer.Option("--mode", help="Rigor mode.")] = "pilot",
) -> None:
    """Create a project."""
    state = _state(ctx)
    with _reporting_errors():
        project_service.init_project(
            state.settings, slug, mode, session=state.session, clock=state.clock
        )
    typer.echo(f"initialised {slug} ({mode})")


@app.command()
def rebuild(ctx: typer.Context) -> None:
    """Rebuild the project index from the event log and print its state hash."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        digest = project.index.rebuild()
    typer.echo(f"state {digest}")


@app.command()
def status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print ProjectStatus as JSON.")] = False,
) -> None:
    """Show a project's rigor mode, event counts and task queue."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = project_service.project_status(project)
    if as_json:
        typer.echo(report.model_dump_json())
        return
    typer.echo(f"project: {report.slug}")
    typer.echo(f"rigor mode: {report.rigor_mode.value}")
    typer.echo(f"events: {report.events_total}")
    typer.echo(f"question: {report.question or 'none'}")
    protocol = report.protocol
    if protocol is None:
        typer.echo("protocol: none")
    else:
        typer.echo(
            f"protocol: {protocol.protocol_id} ({protocol.status.value}, PRESS {protocol.press})"
        )
    seeds = report.seeds
    drawn = "split drawn" if seeds.split_drawn else "not split"
    typer.echo(
        f"seeds: {seeds.positive} positive ({drawn}), {seeds.negative} negative, "
        f"{seeds.unresolved} unresolved"
    )
    tasks = report.tasks
    typer.echo(
        f"tasks: open {tasks.open} / claimed {tasks.claimed} / "
        f"expired {tasks.expired} / completed {tasks.completed}"
    )
    typer.echo(f"works: {report.works} (records {report.records}, merges {report.merges_active})")
    search = report.search
    typer.echo(
        f"searches: {search.runs} runs (complete {search.complete} / partial {search.partial} / "
        f"failed {search.failed} / interrupted {search.interrupted})"
    )
    for short in search.shortfalls:
        typer.echo(
            f"shortfall: {short.run_id} {short.source} "
            f"{short.retrieved_count}/{short.reported_count} \u2014 {short.note or 'no note'}"
        )


@seeds_app.callback()
def seeds(ctx: typer.Context) -> None:
    """Print every seed with its hold-out role. Held-out roles are shown to humans only."""
    if ctx.invoked_subcommand is not None:
        return
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        records = seeds_service.all_seeds(project)
        checks = {check.seed_id: check.status for check in seeds_service.seed_check(project)}
    header = ["id", "kind", "role", "resolution", "check"]
    rows = [
        [
            record.seed_id,
            record.kind.value,
            record.role.value,
            record.work_id
            or (f"unresolved: {record.unresolved_reason}" if record.unresolved_reason else "-"),
            checks.get(record.seed_id, "-"),
        ]
        for record in records
    ]
    table = [header, *rows]
    widths = [max(len(row[column]) for row in table) for column in range(len(header))]
    for row in table:
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        )


@seeds_app.command("split")
def seeds_split(
    ctx: typer.Context,
    random_seed: Annotated[
        int | None,
        typer.Option("--random-seed", help="The seed of the draw; omitted, 32 random bits."),
    ] = None,
) -> None:
    """Draw and record the hold-out split of the positive seeds."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = seeds_service.split_seeds(project, random_seed=random_seed)
    typer.echo(f"split drawn with random seed {drawn.random_seed}")


@seeds_app.command("explain")
def seeds_explain(
    ctx: typer.Context,
    seed_id: Annotated[str, typer.Argument(help="A positive seed, such as SEED03.")],
    route: Annotated[str, typer.Option(help="The admission route planned for the seed.")],
    reason: Annotated[str, typer.Option(help="Why the seed was not retrieved.")],
) -> None:
    """Record why a positive seed was not retrieved, and the route planned for it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            method = ProvenanceMethod(route)
        except ValueError:
            choices = ", ".join(
                m.value for m in ProvenanceMethod if m is not ProvenanceMethod.DATABASE
            )
            raise FactoryValidationError(
                [ValidationIssue("route", f"must be one of: {choices}")]
            ) from None
        seeds_service.explain_seed_miss(project, project.human_actor(), seed_id, reason, method)
    typer.echo(f"explained {seed_id} ({route})")


@protocol_app.command("confirm-press")
def protocol_confirm_press(
    ctx: typer.Context,
    review_id: Annotated[str, typer.Argument(help="The PRESS review to confirm.")],
    response: Annotated[
        list[str] | None,
        typer.Option("--response", help="A response to one finding; give one per finding."),
    ] = None,
) -> None:
    """A human's confirmation of a PRESS review, one response per finding in order."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        protocol_service.confirm_press(
            project, project.human_actor(), review_id, list(response or [])
        )
    typer.echo(f"confirmed {review_id}")


@app.command()
def serve(ctx: typer.Context) -> None:
    """Run the MCP server on stdio."""
    run(_state(ctx).settings)
