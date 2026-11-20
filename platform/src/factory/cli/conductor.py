"""`factory conductor start|advance|status` (plan tiers-and-autonomy, C8).

It parses input, calls `services.conductor` and formats the answer. `start` takes the plan of the
project's declared tier (`factory.tiers.resolve.plan_for`, lane L2); `advance` takes one step
(starts at most one outside `claude -p` run); `status` reads only. The helpers of `factory.cli.main`
are imported inside the commands, because that module imports this one to register the group.
"""

from __future__ import annotations

import importlib
from typing import Annotated, Any

import typer

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services import conductor as conductor_service
from factory.services.project import project_levels

conductor_app = typer.Typer(
    name="conductor",
    help="Run a tier's plan one step at a time through headless role runs.",
    no_args_is_help=True,
)

_JSON = typer.Option("--json", help="Print the status as JSON.")


def _echo(status: conductor_service.ConductorStatus, as_json: bool) -> None:
    typer.echo(status.model_dump_json() if as_json else "\n".join(status.lines))


@conductor_app.command("start")
def start_cmd(ctx: typer.Context) -> None:
    """Begin a conductor run of the plan of the project's tier (refused for a legacy project)."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        tier = project_levels(project).tier
        if tier is None:
            raise FactoryValidationError([ValidationIssue("tier", "the project declared no tier")])
        try:
            resolve: Any = importlib.import_module("factory.tiers.resolve")
        except ModuleNotFoundError as exc:
            raise FactoryValidationError(
                [ValidationIssue("plan", "tier plans are not available in this build")]
            ) from exc
        run = conductor_service.begin_conductor(project, resolve.plan_for(tier))
    typer.echo(
        f"{run.conductor_id} started: {run.tier} at {run.autonomy_level}; steps "
        f"{', '.join(run.steps)}; budget {run.budget.max_runs} runs, "
        f"{run.budget.max_minutes} minutes"
    )


@conductor_app.command("advance")
def advance_cmd(
    ctx: typer.Context,
    retry: Annotated[
        bool, typer.Option("--retry", help="Start a failed or lost role run again (new session).")
    ] = False,
    as_json: Annotated[bool, _JSON] = False,
) -> None:
    """Take the conductor one step: close its finished run, check the stop rules, start at most one
    role run. Run it again once the run has ended."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        status = conductor_service.advance(_resolve_project(state), retry=retry)
    _echo(status, as_json)


@conductor_app.command("status")
def status_cmd(ctx: typer.Context, as_json: Annotated[bool, _JSON] = False) -> None:
    """Where the conductor is and why it stopped (read-only)."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        status = conductor_service.conductor_status(_resolve_project(state))
    _echo(status, as_json)
