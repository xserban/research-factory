"""`factory library` (slice 5, plan deploy-C): the lab library and adoption.

It parses input, calls a service and formats its answer. A command that writes is authorised by its
`TOOL_PERMISSIONS` row. The helpers of `factory.cli.main` are imported inside each command, because
that module imports this one to register the commands.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import typer

from factory.cli.ledger import project_call
from factory.model.screening import Channel
from factory.services import lab_library as lab_library_service
from factory.services.context import Project

library_app = typer.Typer(
    name="library", help="The lab library and adoption.", no_args_is_help=True
)

WorkArg = Annotated[str, typer.Argument(help="Work id (rf:...).")]


@contextmanager
def _read(ctx: typer.Context) -> Iterator[Project]:
    from factory.cli import main

    state = main._state(ctx)
    with main._reporting_errors():
        yield main._resolve_project(state)


@library_app.command("status")
def library_status_cmd(ctx: typer.Context) -> None:
    """Documents, adoptions, project-local files not yet consolidated, and references no library
    serves."""
    with _read(ctx) as project:
        counts = lab_library_service.library_status(project)
    for name, count in counts.items():
        typer.echo(f"{name}: {count}")


@library_app.command("adoptable")
def library_adoptable_cmd(ctx: typer.Context, work_id: WorkArg) -> None:
    """Documents of a promoted work that other readable projects hold in the lab library."""
    with _read(ctx) as project:
        found = lab_library_service.adoptable(project, work_id)
    if not found:
        typer.echo("nothing to adopt")
    for item in found:
        typer.echo(
            f"{item.source_project}  {item.document_id}  {item.route}  {item.quality}  "
            f"{item.provenance}  licence {item.licence_status}  "
            f"{item.conversions} conversion(s)  source "
            f"{'confirmed' if item.confirmed else 'unconfirmed'}"
        )


@library_app.command("adopt")
def library_adopt_cmd(
    ctx: typer.Context,
    work_id: WorkArg,
    source_project: Annotated[str, typer.Argument(help="Slug of the project that holds it.")],
    source_doc: Annotated[str, typer.Argument(help="Its document id (doc_...).")],
) -> None:
    """Adopt another project's document of a promoted work, with its conversions."""
    with project_call(ctx, "cli:library adopt") as project:
        document_id = lab_library_service.adopt(
            project, project.human_actor(), work_id, source_project, source_doc
        )
    typer.echo(f"adopted {document_id}")


@library_app.command("confirm-source")
def library_confirm_source_cmd(
    ctx: typer.Context,
    source_project: Annotated[str, typer.Argument(help="Slug of the source project.")],
    reason: Annotated[str, typer.Option("--reason", help="Why (required).")],
) -> None:
    """Confirm a project as a source of researcher-supplied documents (owner, once)."""
    with project_call(ctx, "cli:library confirm-source") as project:
        event_id = lab_library_service.confirm_source(
            project, project.human_actor(), source_project, reason, Channel.CLI
        )
    typer.echo(f"confirmed {source_project} ({event_id})")


@library_app.command("consolidate")
def library_consolidate_cmd(ctx: typer.Context) -> None:
    """Move this project's local library files into the lab library, verifying each by hash."""
    with project_call(ctx, "cli:library consolidate") as project:
        report = lab_library_service.consolidate(project)
    typer.echo(f"moved {report.moved}, already in the lab library {report.already}")
    for ref in report.kept:
        typer.echo(f"kept (failed verification): {ref}", err=True)
    if report.kept:
        raise typer.Exit(1)
