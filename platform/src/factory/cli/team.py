"""`factory workspace` and `factory project` (slice 5, plan teams-B).

They parse input, call a service and format its answer. `main._resolve_project` authorises each by
its `TOOL_PERMISSIONS` row. The shared helpers of `factory.cli.main` are imported inside each
command, because that module imports this one to register the commands.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

import typer

from factory.services import workspace as workspace_service
from factory.services.access import set_visibility
from factory.services.context import Project
from factory.services.reviews import ReviewView

project_app = typer.Typer(name="project", help="The project itself.", no_args_is_help=True)


@contextmanager
def _project(ctx: typer.Context) -> Iterator[Project]:
    from factory.cli import main

    state = main._state(ctx)
    with main._reporting_errors():
        yield main._resolve_project(state)


def review_line(view: ReviewView) -> str:
    return (
        f"{view.review_request_id}  {view.kind.value}  {view.state.value}  "
        f"{view.requester}  needs {view.required_role.value}  {view.reason}"
    )


def workspace_lines(built: workspace_service.Workspace) -> list[str]:
    """The workspace as text: a heading per list, its items below."""
    roles = ", ".join(sorted(role.value for role in built.roles)) or "none"
    lines = [f"user: {built.user}", f"roles: {roles}"]
    if built.notice is not None:
        lines.append(built.notice)
    lines.append(f"sessions: {len(built.sessions)}")
    lines.extend(f"  {s.session}  {s.events} events" for s in built.sessions)
    lines.append(f"open tasks: {len(built.open_tasks)}")
    lines.extend(f"  {task}" for task in built.open_tasks)
    lines.append(f"proposals: {len(built.proposals)}")
    lines.extend(f"  {item}" for item in built.proposals)
    lines.append(f"reviews requested: {len(built.reviews_requested)}")
    lines.extend(f"  {review_line(view)}" for view in built.reviews_requested)
    lines.append(f"reviews to decide: {len(built.reviews_to_decide)}")
    lines.extend(f"  {review_line(view)}" for view in built.reviews_to_decide)
    return lines


def workspace_cmd(
    ctx: typer.Context,
    user: Annotated[
        str | None, typer.Option("--user", help="Whose workspace; default: your own.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the Workspace as JSON.")] = False,
) -> None:
    """A person's sessions, tasks, proposals and reviews on this project."""
    with _project(ctx) as project:
        built = workspace_service.workspace(project, user or project.principal.user)
    if as_json:
        typer.echo(built.model_dump_json())
        return
    for line in workspace_lines(built):
        typer.echo(line)


@project_app.command("visibility")
def project_visibility_cmd(
    ctx: typer.Context,
    value: Annotated[
        Literal["lab", "private"], typer.Argument(help="`lab` or `private` (members only).")
    ],
) -> None:
    """Set who reads this project (owner)."""
    with _project(ctx) as project:
        set_visibility(project, project.human_actor(), value)
    typer.echo(f"visibility {value}")
