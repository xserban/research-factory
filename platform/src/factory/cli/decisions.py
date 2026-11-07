"""`factory decide` (slice 8, plan A5): list, show and select.

Business logic stays in `services/decisions.py`; these commands parse input, call it and format the
answer. `select` is the person's act, written as a human with `channel = cli`; `--reconstructed`
marks a selection back-filled for a decision made before this slice. Without the full view the
output passes through the agent view's scrub (R-20). The shared helpers of `factory.cli.main` are
imported inside each command, because that module imports this one to register the group.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.decisions import DecisionLevel
from factory.model.screening import Channel
from factory.services import agent_view as agent_view_service
from factory.services import decisions as decisions_service
from factory.services.context import Project

decide_app = typer.Typer(
    name="decide",
    help="Suggested decisions and your selection: list, show, select.",
    no_args_is_help=True,
)

_MARK = {"proposed": "[ ]", "validated": "[x]", "rejected": "[-]", "added": "[+]"}


def _list_lines(rows: list[decisions_service.DecisionRow]) -> list[str]:
    if not rows:
        return ["no decisions"]
    return [
        f"{r.decision_id}  {r.level}  {r.subject}  {r.state}  "
        f"{r.selected}/{r.items} selected"
        + (f"  supersedes {r.supersedes}" if r.supersedes else "")
        + (f"  superseded by {r.superseded_by}" if r.superseded_by else "")
        for r in rows
    ]


def _show_lines(v: decisions_service.DecisionView) -> list[str]:
    lines = [f"{v.decision_id}  {v.level}  {v.subject}  {v.state}", f"    {v.explanation}"]
    if v.supersedes:
        lines.append(f"    supersedes: {v.supersedes}")
    if v.superseded_by:
        lines.append(f"    superseded by: {v.superseded_by}")
    for item in v.items:
        flag = "  (recommended)" if item.recommended else ""
        lines.append(f"  {_MARK[item.status]} {item.item_id}  {item.text}{flag}")
        if item.grounds:
            lines.append(f"        grounds: {', '.join(item.grounds)}")
    if v.selection is not None:
        s = v.selection
        kind = " (reconstructed)" if s.reconstructed else ""
        lines.append(f"  selected by {s.actor} via {s.channel} at {s.ts}{kind}")
        if s.note:
            lines.append(f"    note: {s.note}")
    return lines


def _echo(project: Project, lines: list[str]) -> None:
    from factory.cli.main import _full_view

    text = "\n".join(lines) + "\n"
    typer.echo(
        text if _full_view(project) else agent_view_service.scrubbed_text(project, text), nl=False
    )


@decide_app.command("list")
def decide_list_cmd(
    ctx: typer.Context,
    level: Annotated[
        str | None, typer.Option("--level", help="goal, questions, plan, seeds, probe or protocol.")
    ] = None,
    open_only: Annotated[
        bool, typer.Option("--open", help="Only decisions awaiting your selection.")
    ] = False,
) -> None:
    """Decisions with their state: open until selected, then selected, or superseded."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        try:
            chosen = None if level is None else DecisionLevel(level)
        except ValueError:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "level", "must be one of " + ", ".join(v.value for v in DecisionLevel)
                    )
                ]
            ) from None
        project = _resolve_project(state)
        rows = decisions_service.list_decisions(project, chosen, open_only)
    _echo(project, _list_lines(rows))


@decide_app.command("show")
def decide_show_cmd(
    ctx: typer.Context,
    decision_id: Annotated[str, typer.Argument(help="A decision, dec_.")],
) -> None:
    """One decision: the explanation, each item with its grounds and status, your selection."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = decisions_service.view_decision(project, decision_id)
    _echo(project, _show_lines(view))


@decide_app.command("select")
def decide_select_cmd(
    ctx: typer.Context,
    decision_id: Annotated[str, typer.Argument(help="A decision, dec_.")],
    item: Annotated[
        list[str] | None, typer.Option("--item", help="A suggested item to keep, such as I01.")
    ] = None,
    add: Annotated[
        list[str] | None, typer.Option("--add", help="An item of your own, as text.")
    ] = None,
    note: Annotated[
        str, typer.Option("--note", help="Why; needed when you keep none of the items.")
    ] = "",
    reconstructed: Annotated[
        bool, typer.Option("--reconstructed", help="Back-fill for a decision made earlier.")
    ] = False,
) -> None:
    """Record your selection as a human. Repeat `--item` and `--add`; the items you leave out are
    rejected. Selecting nothing needs a `--note`. A later selection replaces an earlier one."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        decisions_service.select(
            project,
            project.human_actor(),
            decision_id,
            item or [],
            add or [],
            note,
            Channel.CLI,
            reconstructed,
        )
        view = decisions_service.view_decision(project, decision_id)
    kept = [i.item_id for i in view.items if i.status == "validated"]
    own = [i.item_id for i in view.items if i.origin == "added"]
    typer.echo(f"selected {decision_id}: kept {', '.join(kept) or 'none'}; added {len(own)}")
