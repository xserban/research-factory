"""`factory queue` (plan 2026-11-11-feed-hub, step H4): the papers added from the feed with their
stage, and the open units of work per task kind. Read-only.

It parses input, calls `factory.services.work_queue` and formats its answer. The command's
`TOOL_PERMISSIONS` row (`cli:queue`) is applied through `factory.cli.main`, which imports this
module to register the command; its helpers are imported inside the function for that reason.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

import typer

from factory.services import work_queue
from factory.services.context import Project

ProjectOpt = Annotated[str | None, typer.Option("--project", help="Project slug.")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print the queue as JSON.")]
_TITLE_WIDTH = 50


def _cut(text: str, width: int) -> str:
    if text == "":
        return "-"
    return text if len(text) <= width else text[: width - 1] + "…"


def queue_cmd(
    ctx: typer.Context,
    project: ProjectOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """The papers added from the feed, each with its stage, then the open units per task kind."""
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
