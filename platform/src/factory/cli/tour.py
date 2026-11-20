"""`factory tour`: the tutorial stage list with this project's progress, or one stage card.

Read-only and thin: the text is `factory.learn` data and the progress comes from
`services/learn_progress`. The helpers of `factory.cli.main` are imported inside the command,
because that module imports this one. With no project to read, the stages are printed with the
state `unknown` and the first step of each as its next step.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Any

import typer

from factory.learn.model import Ref, RefKind
from factory.learn.stages import STAGES, stage_card
from factory.services.context import list_projects
from factory.services.hub_learn import learn_payload


class TourFormat(StrEnum):
    TABLE = "table"
    JSON = "json"


def _ref(ref: Ref) -> str:
    return f"factory {ref.name}" if ref.kind is RefKind.CLI else ref.name


def _no_progress() -> dict[str, Any]:
    return {
        "stages": [
            {
                "id": s.id,
                "title": s.title,
                "progress": {"state": "unknown", "next_step": s.steps[0].text},
            }
            for s in STAGES
        ]
    }


def _card_lines(stage: dict[str, Any]) -> list[str]:
    card = stage_card(stage["id"])
    assert card is not None
    lines = [f"{card.title} ({card.id})", card.goal, ""]
    p = stage["progress"]
    lines += [f"state: {p['state']}", f"next: {p['next_step']}", ""]
    lines.append("only you:")
    lines += [f"  - {g}" for g in card.gates]
    lines.append("steps:")
    for n, s in enumerate(card.steps, 1):
        refs = ", ".join(_ref(r) for r in s.refs)
        lines.append(f"  {n}. [{s.actor.value}] {s.text}" + (f" ({refs})" if refs else ""))
    lines += ["done looks like:", f"  {card.done.condition}"]
    lines.append("  shown by: " + ", ".join(_ref(r) for r in card.done.shown_by))
    lines.append("common mistakes:")
    lines += [f"  - {m}" for m in card.mistakes]
    lines.append("rules behind it:")
    lines += [f"  - {m}" for m in card.rigour]
    lines.append(f"hub page: {card.page.name}")
    return lines


def tour_cmd(
    ctx: typer.Context,
    project: Annotated[
        str | None, typer.Option("--project", help="Project slug, for the progress column.")
    ] = None,
    stage: Annotated[
        int | None, typer.Option("--stage", help="Show one stage card, numbered from 1.")
    ] = None,
    fmt: Annotated[TourFormat, typer.Option("--format", help="table or json.")] = TourFormat.TABLE,
) -> None:
    """Print the nine stages with your progress, or one stage card with `--stage N`."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    if stage is not None and not 1 <= stage <= len(STAGES):
        raise typer.BadParameter(f"--stage must be 1 to {len(STAGES)}")
    state = _state(ctx)
    if project is not None:
        state.project = project
    with _reporting_errors():
        if state.project is None and not list_projects(state.settings):
            data = _no_progress()
        else:
            data = learn_payload(_resolve_project(state))
    stages = data["stages"]
    if stage is not None:
        stages = [stages[stage - 1]]
    if fmt is TourFormat.JSON:
        typer.echo(json.dumps(stages if stage is None else stages[0], indent=2, sort_keys=True))
        return
    if stage is not None:
        for line in _card_lines(stages[0]):
            typer.echo(line)
        return
    for n, s in enumerate(stages, 1):
        p = s["progress"]
        typer.echo(f"{n}. {s['title']} [{p['state']}]")
        typer.echo(f"   {p['next_step']}")
