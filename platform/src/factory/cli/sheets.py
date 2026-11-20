"""`factory sheets`: argument sheets of the papers chat (plan chat T7).

Business logic stays in `services/sheets.py`. Agents open sheets and record arguments through the
MCP tools; here the researcher reads a sheet and rates its arguments (`rate` writes one
`sheet.argument_rated` event as the human) and writes the balance (`balance`, one
`sheet.balance_recorded` event as the human; no MCP tool writes it). The shared helpers of
`factory.cli.main` are imported inside the commands, because that module imports this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from factory.services import sheet_diff as diff_service
from factory.services import sheet_export as export_service
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
        if a.linked_claim:
            k = a.linked_claim
            typer.echo(f'  rests on {a.claim_row_key}: {k.claim_type} | {k.about}: "{k.quote}"')
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


def write_brief(out: Path, brief: str, force: bool) -> None:
    """Write `brief` to `out`; refuses an existing file without `force`, and reports a missing
    directory or any OS error as a structured message (exit 1), never a traceback."""
    from factory.cli.main import _reporting_errors
    from factory.errors import FactoryValidationError, ValidationIssue

    with _reporting_errors():
        if out.exists() and not force:
            raise FactoryValidationError(
                [ValidationIssue("out", f"{out} exists; pass --force to overwrite it")]
            )
        try:
            out.write_text(brief, encoding="utf-8")
        except OSError as exc:
            raise FactoryValidationError(
                [ValidationIssue("out", f"cannot write {out}: {exc.strerror or exc}")]
            ) from exc


_FORCE = Annotated[bool, typer.Option("--force", help="Overwrite an existing --out file.")]


@sheets_app.command("export")
def sheets_export_cmd(
    ctx: typer.Context,
    sheet: Annotated[str, typer.Argument(help="A sht_ id.")],
    out: Annotated[Path | None, typer.Option("--out", help="Write here instead of stdout.")] = None,
    force: _FORCE = False,
) -> None:
    """The sheet as a Markdown brief: the researcher's balance first, then the arguments with
    quotes, paragraphs and ratings, then the references. Read-only."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        brief = export_service.export_sheet(project, sheet)
    if out is None:
        typer.echo(brief, nl=False)
    else:
        write_brief(out, brief, force)
        typer.echo(f"{sheet} exported to {out}")


def _diff_line(a: sheets_service.ArgumentView) -> str:
    return f"  [{a.stance}] {a.work_id} {a.anchor}: {a.claim}"


@sheets_app.command("diff")
def sheets_diff_cmd(
    ctx: typer.Context,
    old: Annotated[str, typer.Argument(help="The earlier sht_ id.")],
    new: Annotated[str, typer.Argument(help="The later sht_ id, usually its re-spar.")],
) -> None:
    """The arguments of the later sheet against the earlier one: added, dropped and kept, matched
    by work, anchor and stance. An earlier rating of a kept argument is shown as a suggestion
    only; nothing is rated. Read-only."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        diff = diff_service.sheet_diff(project, old, new)
    typer.echo(f"{old} -> {new}")
    typer.echo(f"Added ({len(diff.added)})")
    for a in diff.added:
        typer.echo(_diff_line(a))
    typer.echo(f"Dropped ({len(diff.dropped)})")
    for a in diff.dropped:
        typer.echo(_diff_line(a))
    typer.echo(f"Kept ({len(diff.kept)})")
    for k in diff.kept:
        typer.echo(_diff_line(k.new))
        if k.suggested_rating is not None:
            note = f" ({k.suggested_note})" if k.suggested_note else ""
            typer.echo(f"    suggested from the earlier sheet: {k.suggested_rating}{note}")
        elif k.changed:
            was = f"; earlier rating {k.old_rating} (context only)" if k.old_rating else ""
            typer.echo(f"    changed at the same place: the quote differs{was}")
    typer.echo(diff.suggestion_label)
