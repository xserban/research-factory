"""`factory resume` (plan restart-and-costs, R3): resume the interrupted work of a project, or of
every project with `--all`; `--dry-run` prints the plan and writes nothing.

It parses input, calls `factory.services.resume` and formats its answer. The command's
`TOOL_PERMISSIONS` row (`cli:resume`) is applied through `factory.cli.main`, which imports this
module to register the command; its helpers are imported inside the function for that reason.

The command runs in the foreground: a resumed pipeline or run is waited for (with its time
limit) before the command returns, so the process does not exit under it; with `--all` the
projects go one after another.

Exit codes: 0 when nothing is to do, or the work started; 1 when something was refused; 2 for
invalid input (nothing is written on that path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer

from factory.errors import FactoryError
from factory.services import resume as resume_service
from factory.services.access import authorize_command
from factory.services.context import Project, list_projects, open_project

if TYPE_CHECKING:
    from factory.cli.main import CliState


def _print_plan(plan: resume_service.ResumePlan) -> None:
    typer.echo("plan:")
    if plan.is_empty:
        typer.echo("  nothing interrupted")
        return
    if plan.blocked:
        typer.echo(f"  blocked: {plan.blocked}")
    for run_id in plan.failed_to_start:
        typer.echo(f"  run {run_id} never started (launcher failed): not resumed")
    for line in plan.waiting:
        typer.echo(f"  waiting (not resumed): {line}")
    if plan.reconcile:
        typer.echo(f"  reconciled (process gone): {', '.join(plan.reconcile)}")
    for lease in plan.leases:
        typer.echo(f"  leases lapsed, released by expiry: {lease.kind} x{lease.count}")
    if plan.pipeline is not None:
        typer.echo(
            f"  pipeline {plan.pipeline.resumes} resumed from stage {plan.pipeline.from_stage} "
            f"({', '.join(plan.pipeline.stages)})"
        )
    if plan.run is not None:
        typer.echo(
            f"  run {plan.run.resumes} resumed: stage {plan.run.stage} with model {plan.run.model}"
        )
        if plan.run.adopted:
            typer.echo("    (adopted driver: the resumed run uses the full tools of the stage)")
    if plan.queued:
        typer.echo(f"  queued (resumed by a later call): {', '.join(plan.queued)}")
    for item in plan.stale_passes:
        where = item.stage if item.module == "screening" else item.scope
        typer.echo(
            f"  stale pass (not resumed): {item.module} {where} {item.label}, "
            f"{item.pending} pending, session {item.session} last active {item.last_activity}"
        )
    a = plan.automatic
    if a.resolve or a.fetch or a.convert:
        typer.echo(
            f"  automatic steps undone: resolve {a.resolve}, fetch {a.fetch}, convert {a.convert}"
        )


def _print_result(result: resume_service.ResumeResult) -> bool:
    """Print what started and what was refused; True when something was refused."""
    for run_id in result.reconciled:
        typer.echo(f"reconciled run {run_id}")
    if result.pipeline_id is not None:
        typer.echo(f"started pipeline {result.pipeline_id}")
    if result.run_id is not None:
        typer.echo(f"started run {result.run_id}")
    for reason in result.refused:
        typer.echo(f"refused: {reason}", err=True)
    if not (result.reconciled or result.pipeline_id or result.run_id or result.refused):
        typer.echo("nothing started")
    return bool(result.refused)


def _one(project: Project, cap: int | None, dry_run: bool) -> bool:
    """Plan (or resume) one project; True when something was refused."""
    outcome = resume_service.resume(project, dry_run=dry_run, unit_cap=cap, foreground=True)
    if isinstance(outcome, resume_service.ResumePlan):
        _print_plan(outcome)
        typer.echo("dry run: nothing written")
        return False
    _print_plan(outcome.plan)
    return _print_result(outcome)


def _resume_all(state: CliState, cap: int | None, dry_run: bool) -> bool:
    """Every project the running command is allowed on; a refusal is printed and the others go on.
    The checks are those of `feed run --all`: `authorize_command` per project."""
    refused = False
    for slug in list_projects(state.settings):
        try:
            opened = open_project(state.settings, slug, session=state.session, clock=state.clock)
            authorize_command(opened, opened.principal, state.tool)
        except FactoryError as exc:
            typer.echo(f"{slug}: {exc}", err=True)
            refused = True
            continue
        typer.echo(f"project {slug}")
        try:
            refused = _one(opened, cap, dry_run) or refused
        except FactoryError as exc:
            typer.echo(f"{slug}: {exc}", err=True)
            refused = True
    return refused


def resume_cmd(
    ctx: typer.Context,
    all_projects: Annotated[
        bool, typer.Option("--all", help="Every project the command is allowed on.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the plan; write and start nothing.")
    ] = False,
    cap: Annotated[
        int | None, typer.Option("--cap", help="Unit cap for a resumed run or pipeline.")
    ] = None,
) -> None:
    """Resume the interrupted work: expired leases, interrupted runs and pipelines, stale passes
    are reported. Exit 0 nothing to do or started, 1 something refused, 2 invalid input."""
    from factory.cli.main import _authorized, _selected_project, _state

    state = _state(ctx)
    if cap is not None and cap < 1:
        typer.echo("cap: must be at least 1", err=True)
        raise typer.Exit(2)
    if all_projects:
        refused = _resume_all(state, cap, dry_run)
    else:
        project = _authorized(state, _selected_project(state))
        refused = _one(project, cap, dry_run)
    raise typer.Exit(1 if refused else 0)
