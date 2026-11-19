"""`factory sheets`: argument sheets of the papers chat (plan chat T7).

Business logic stays in `services/sheets.py`. Agents open sheets and record arguments through the
MCP tools; here the researcher reads a sheet and rates its arguments (`rate` writes one
`sheet.argument_rated` event as the human) and writes the balance (`balance`, one
`sheet.balance_recorded` event as the human; no MCP tool writes it). The shared helpers of
`factory.cli.main` are imported inside the commands, because that module imports this one.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.services import sheets as sheets_service

sheets_app = typer.Typer(
    name="sheets",
    help="Argument sheets: list, show, rate an argument and write the balance (human).",
    no_args_is_help=True,
)


@sheets_app.command("list")
def sheets_list_cmd(ctx: typer.Context) -> None:
    """Every sheet with its mode, section state and argument count."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = sheets_service.list_sheets(project)
    for s in rows:
        sections = f"against {'closed' if s.against_closed else 'open'}, "
        sections += f"for {'closed' if s.for_closed else 'open'}"
        typer.echo(f"{s.sheet_id} {s.mode} ({sections}; {s.arguments} argument(s)): {s.hypothesis}")


@sheets_app.command("show")
def sheets_show_cmd(
    ctx: typer.Context, sheet: Annotated[str, typer.Argument(help="A sht_ id.")]
) -> None:
    """One sheet: arguments with their verified quotes, then the computed coverage."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = sheets_service.view_sheet(project, sheet)
    typer.echo(f"{view.info.sheet_id} {view.info.mode}: {view.info.hypothesis}")
    if view.balance is not None:
        b = view.balance
        lean = f" [{b.lean}]" if b.lean else ""
        typer.echo(f"\nbalance (researcher's, {view.balance_history} recorded){lean}: {b.text}")
        if b.note:
            typer.echo(f"  further evidence needed: {b.note}")
    else:
        typer.echo("\nbalance: none recorded (the researcher writes it: factory sheets balance)")
    for a in view.arguments:
        rated = f" [{a.rating}]" if a.rating else " [unrated]"
        typer.echo(
            f"\n{a.argument_id} {a.stance} · {a.work_id} · {a.strength} (judgement){rated}\n"
            f'  claim: {a.claim}\n  [{a.anchor}] "{a.quote}"'
        )
    c = view.coverage
    typer.echo(
        f"\ncoverage: {c.total} works; tier 1/2/3 = "
        f"{c.by_tier[1]}/{c.by_tier[2]}/{c.by_tier[3]}; sources {c.by_source}; "
        f"arguments {c.arguments}; works argued {c.works_argued}; "
        f"tier-1 without argument: {len(c.tier1_unargued)}; unrated: {c.unrated}"
    )
    typer.echo(view.balance_label)


@sheets_app.command("rate")
def sheets_rate_cmd(
    ctx: typer.Context,
    argument: Annotated[str, typer.Argument(help="An arg_ id.")],
    rating: Annotated[str, typer.Argument(help="sound, weak or wrong.")],
    note: Annotated[str, typer.Option("--note", help="Why.")] = "",
) -> None:
    """Rate one argument as the researcher; the latest rating stands."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        sheets_service.rate_argument(project, project.human_actor(), argument, rating, note)
    typer.echo(f"{argument} rated {rating}")


@sheets_app.command("balance")
def sheets_balance_cmd(
    ctx: typer.Context,
    sheet: Annotated[str, typer.Argument(help="A sht_ id.")],
    text: Annotated[str, typer.Option("--text", help="Your balance of the evidence.")],
    lean: Annotated[
        str | None, typer.Option("--lean", help="against, mixed, for or undecided.")
    ] = None,
    note: Annotated[
        str | None, typer.Option("--note", help="What further evidence is needed.")
    ] = None,
) -> None:
    """Write the balance of a sheet as the researcher; both sections must be closed; the latest
    stands."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        sheets_service.record_balance(project, project.human_actor(), sheet, text, lean, note)
    typer.echo(f"{sheet} balance recorded")
