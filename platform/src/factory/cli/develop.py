"""`factory develop render` (slice 8, plan A9): a level of the develop stage as Markdown.

Business logic stays in `services/develop_render.py`. The command records `document.rendered`
(unless the level's document is unchanged) and prints the Markdown, or writes it to `--out`.
Without the full view the text passes through the agent view's scrub (R-20). The shared helpers
of `factory.cli.main` are imported inside the command, because that module imports this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.decisions import DecisionLevel
from factory.services import agent_view as agent_view_service
from factory.services import develop_render as render_service

develop_app = typer.Typer(
    name="develop",
    help="The develop stage: render a level as a formal document.",
    no_args_is_help=True,
)


@develop_app.command("render")
def develop_render_cmd(
    ctx: typer.Context,
    level: Annotated[
        str, typer.Option("--level", help="goal, questions, plan, seeds, probe or protocol.")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", help="Write the Markdown to this file.")
    ] = None,
) -> None:
    """Render one level from its decision events and record the version."""
    from factory.cli.main import _full_view, _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        try:
            chosen = DecisionLevel(level)
        except ValueError:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "level", "must be one of " + ", ".join(v.value for v in DecisionLevel)
                    )
                ]
            ) from None
        project = _resolve_project(state)
        result = render_service.render_level(project, chosen)
    markdown = (
        result.markdown
        if _full_view(project)
        else agent_view_service.scrubbed_text(project, result.markdown)
    )
    note = "unchanged" if result.unchanged else "recorded"
    if out is None:
        typer.echo(markdown, nl=False)
        typer.echo(f"\n[{result.level} version {result.version}, {note}]", err=True)
        return
    out.write_text(markdown, encoding="utf-8")
    typer.echo(f"{result.level} version {result.version} ({note}) written to {out}")
