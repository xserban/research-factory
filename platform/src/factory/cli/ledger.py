"""`factory ledger` and `factory budget` (slice 5, plan teams-D).

It parses input, calls a service and formats its answer. A command that writes is authorised by its
`TOOL_PERMISSIONS` row and leaves one access-log line on a server. The helpers of `factory.cli.main`
are imported inside each command, because that module imports this one to register the commands.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Annotated

import typer

from factory.cli.admin import _member_call
from factory.model.budgets import BudgetLine, BudgetStatus
from factory.services import budgets as budget_service
from factory.services import ledger as ledger_service
from factory.services.context import Project

budget_app = typer.Typer(
    name="budget", help="Declared budgets and computed consumption.", no_args_is_help=True
)


class PeriodChoice(StrEnum):
    TOTAL = "total"
    WEEK = "week"


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


@budget_app.command("set")
def budget_set(
    ctx: typer.Context,
    unit: Annotated[
        str,
        typer.Option("--unit", help="tasks:<kind>, tasks:*, requests:search or requests:fulltext."),
    ],
    limit: Annotated[int, typer.Option("--limit", help="The most that may be consumed.")],
    period: Annotated[PeriodChoice, typer.Option("--period", help="total or week.")],
    user: Annotated[
        str | None, typer.Option("--user", help="One person; the whole project without it.")
    ] = None,
) -> None:
    """Declare a budget (owner). It replaces the budget of the same scope and unit."""
    with project_call(ctx, "cli:budget set") as project:
        budget_id = budget_service.set_budget(
            project,
            project.human_actor(),
            user=user,
            unit=unit,
            limit=limit,
            period="week" if period is PeriodChoice.WEEK else "total",
        )
    typer.echo(budget_id)


def _budget_line(line: BudgetLine) -> str:
    budget = line.budget
    scope = "project" if budget.scope_user is None else budget.scope_user
    return (
        f"{budget.budget_id} {scope} {budget.unit}: {line.consumed} of {budget.limit} "
        f"({budget.period}), {line.remaining} left"
    )


def _status_lines(status: BudgetStatus) -> list[str]:
    if status.notice is not None:
        return [status.notice]
    lines = [_budget_line(line) for line in status.budgets]
    lines += [f"reported {name}: {value:g}" for name, value in status.reported_usage.items()]
    return lines


@budget_app.command("status")
def budget_status(ctx: typer.Context) -> None:
    """Each budget with its computed consumption, and the usage agents reported."""
    from factory.cli import main

    with main._reporting_errors():
        status = budget_service.budget_status(main._resolve_project(main._state(ctx)))
    for line in _status_lines(status):
        typer.echo(line)
