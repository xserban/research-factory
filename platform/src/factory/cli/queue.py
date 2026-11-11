"""`factory queue` (plan 2026-11-11-feed-hub, steps H4 and H5): the papers added from the feed with
their stage and the open units of work per task kind (read-only), `queue process` (start the
headless runner for a stage) and `queue runs` (list the runs).

It parses input, calls `factory.services.work_queue` and formats its answer. Each command's
`TOOL_PERMISSIONS` row (`cli:queue`, `cli:queue process`, `cli:queue runs`) is applied through
`factory.cli.main`, which imports this module to register the group; its helpers are imported
inside the functions for that reason.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

import typer

from factory.errors import FactoryValidationError
from factory.services import runner, work_queue
from factory.services.context import Project

ProjectOpt = Annotated[str | None, typer.Option("--project", help="Project slug.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print the queue as JSON.")]
_TITLE_WIDTH = 50

queue_app = typer.Typer(
    name="queue",
    help="The work queue: show it, process a stage with the headless runner, list the runs.",
    invoke_without_command=True,
)


def _cut(text: str, width: int) -> str:
    if text == "":
        return "-"
    return text if len(text) <= width else text[: width - 1] + "…"


def _open(ctx: typer.Context, slug: str | None) -> Project:
    from factory.cli import main

    state = main._state(ctx)
    target = state if slug is None else replace(state, project=slug)
    return main._resolve_project(target)


@queue_app.callback()
def queue_cmd(
    ctx: typer.Context,
    project: ProjectOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """The papers added from the feed, each with its stage, then the open units per task kind."""
    if ctx.invoked_subcommand is not None:
        return
    from factory.cli import main

    state = main._state(ctx)
    target = state if project is None else replace(state, project=project)
    opened: Project = main._resolve_project(target)
    work = work_queue.queue(opened)
    if as_json:
        typer.echo(work.model_dump_json())
        return
    if not work.items:
        typer.echo("no paper has been added from the feed yet")
    else:
        typer.echo(f"{'entry':<16}  {'stage':<13}  {'title':<{_TITLE_WIDTH}}  detail")
        for item in work.items:
            flag = " (stopped)" if item.stopped else ""
            typer.echo(
                f"{item.entry_id:<16}  {item.stage:<13}  "
                f"{_cut(item.title, _TITLE_WIDTH):<{_TITLE_WIDTH}}  {item.detail}{flag}"
            )
    typer.echo("pending work:")
    if not work.pending:
        typer.echo("  none defined")
    for kind, count in sorted(work.pending.items()):
        typer.echo(f"  {kind:<20} {count}")


@queue_app.command("process")
def queue_process_cmd(
    ctx: typer.Context,
    stage: Annotated[str, typer.Option("--stage", help="screen or extract.")],
    project: ProjectOpt = None,
    cap: Annotated[
        int, typer.Option("--cap", help="Units the run may handle before it stops.")
    ] = runner.DEFAULT_UNIT_CAP,
    wait: Annotated[bool, typer.Option("--wait", help="Block until the process exits.")] = False,
) -> None:
    """Start the headless `claude -p` runner for one stage of the project."""
    opened = _open(ctx, project)
    try:
        run_id = runner.start_run(opened, stage, unit_cap=cap)
    except FactoryValidationError as exc:
        for issue in exc.issues:
            typer.echo(f"{issue.field}: {issue.reason}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"started {run_id} ({stage}, cap {cap})")
    if wait:
        runner.wait(run_id)
        for view in runner.run_status(opened, limit=1):
            typer.echo(f"{view.run_id}: {view.status}")
        return
    typer.echo(
        "the process runs in the background; use --wait (or the hub) so its end is recorded "
        "here, otherwise it is closed as lost on the next `queue runs`"
    )


@queue_app.command("runs")
def queue_runs_cmd(
    ctx: typer.Context,
    project: ProjectOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """List the open and recent runs of the project."""
    opened = _open(ctx, project)
    views = runner.run_status(opened)
    if as_json:
        typer.echo("[" + ",".join(v.model_dump_json() for v in views) + "]")
        return
    if not views:
        typer.echo("no run yet")
    for v in views:
        typer.echo(
            f"{v.run_id}  {v.stage:<8}  {v.status:<9}  cap {v.unit_cap:<3}  "
            f"before {sum(v.counts_before.values())}  "
            f"after {'-' if v.counts_after is None else sum(v.counts_after.values())}"
        )
