"""`factory ledger` (slice 5, plan teams-D).

It parses input, calls a service and formats its answer. A command that writes is authorised by its
`TOOL_PERMISSIONS` row and leaves one access-log line on a server. The helpers of `factory.cli.main`
are imported inside each command, because that module imports this one to register the commands.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import typer

from factory.cli.admin import _member_call
from factory.services import ledger as ledger_service
from factory.services.context import Project


@contextmanager
def project_call(ctx: typer.Context, tool: str) -> Iterator[Project]:
    """The `--project` project (or the only one) for a command that writes: authorised, and left in
    the access log."""
    from factory.cli import main

    state = main._state(ctx)
    with main._reporting_errors():
        slug = main._resolve_project(state).paths.slug
    with _member_call(ctx, tool, slug) as project:
        yield project


def ledger_cmd(
    ctx: typer.Context,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Confirm your entry of the ledger as it stands.")
    ] = False,
    for_user: Annotated[
        str | None,
        typer.Option("--for", help="With --confirm: a deactivated user's entry (owner only)."),
    ] = None,
    reason: Annotated[
        str | None, typer.Option("--reason", help="Why, when confirming with --for.")
    ] = None,
) -> None:
    """The CRediT and AI-assistance statements, computed from the log, with each person's
    confirmation."""
    from factory.cli import main

    state = main._state(ctx)
    if not confirm:
        if for_user is not None or reason is not None:
            main._fail("--for and --reason need --confirm", 2)
        with main._reporting_errors():
            report = ledger_service.ledger_report(main._resolve_project(state))
    else:
        tool = "cli:ledger confirm" if for_user is None else "cli:ledger confirm-for"
        with project_call(ctx, tool) as project:
            report = ledger_service.confirm_ledger(
                project, project.human_actor(), user=for_user, reason=reason
            )
    typer.echo(ledger_service.render_ledger(report.ledger, report.confirmations), nl=False)
