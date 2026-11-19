"""`factory chat`: requests for a headless spar or ask (plan spar-night N3).

Business logic stays in `services/chat_requests.py`. The researcher orders a spar or an ask here
(`request` writes one `chat.requested` event as the human) and lists the orders with their derived
state (`requests`). A headless run (`factory runs start spar|ask`) takes the oldest open request of
its kind. For a Prepare spar the case for is a second request: `--parent <sht_ id> --mode prepare`.
The shared helpers of `factory.cli.main` are imported inside the commands, because that module
imports this one.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.services import chat_requests as chat_requests_service
from factory.services.selection import SelectionSpec

chat_app = typer.Typer(
    name="chat",
    help="Requests for a headless spar or ask: order one (human) and list them.",
    no_args_is_help=True,
)
request_app = typer.Typer(
    name="request", help="Order a spar or an ask (human).", no_args_is_help=True
)
chat_app.add_typer(request_app)

_LAYER = typer.Option("--layer", help="A layer to read; repeat for several. None: all.")
_INCLUDE = typer.Option("--include", help="A work to add to the selection; repeatable.")
_EXCLUDE = typer.Option("--exclude", help="A work to leave out; repeatable.")
_PARENT = typer.Option("--parent", help="An earlier sht_ or ans_ id this follows up.")
_NOTE = typer.Option("--note", help="A note for the run.")


def _spec(layers: list[str], include: list[str], exclude: list[str]) -> SelectionSpec:
    return SelectionSpec(layers=layers, include=include, exclude=exclude)


@request_app.command("spar")
def request_spar_cmd(
    ctx: typer.Context,
    hypothesis: Annotated[str, typer.Argument(help="The hypothesis to argue against and for.")],
    layer: Annotated[list[str] | None, _LAYER] = None,
    include: Annotated[list[str] | None, _INCLUDE] = None,
    exclude: Annotated[list[str] | None, _EXCLUDE] = None,
    mode: Annotated[str, typer.Option("--mode", help="explore (default) or prepare.")] = "explore",
    parent: Annotated[str | None, _PARENT] = None,
    note: Annotated[str | None, _NOTE] = None,
) -> None:
    """Order a spar as the researcher. Prepare writes only the case against; order the case for
    afterwards with `--parent <sheet> --mode prepare`."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        payload = chat_requests_service.request_chat(
            project,
            project.human_actor(),
            "spar",
            _spec(layer or [], include or [], exclude or []),
            hypothesis=hypothesis,
            mode=mode,
            parent=parent,
            note=note,
        )
    typer.echo(f"{payload.request_id} spar ({payload.mode}) ordered: {hypothesis}")


@request_app.command("ask")
def request_ask_cmd(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="The question to put to the papers.")],
    layer: Annotated[list[str] | None, _LAYER] = None,
    include: Annotated[list[str] | None, _INCLUDE] = None,
    exclude: Annotated[list[str] | None, _EXCLUDE] = None,
    mode: Annotated[str | None, typer.Option("--mode", help="Not used by an ask.")] = None,
    parent: Annotated[str | None, _PARENT] = None,
    note: Annotated[str | None, _NOTE] = None,
) -> None:
    """Order an ask as the researcher."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        payload = chat_requests_service.request_chat(
            project,
            project.human_actor(),
            "ask",
            _spec(layer or [], include or [], exclude or []),
            question=question,
            mode=mode,
            parent=parent,
            note=note,
        )
    typer.echo(f"{payload.request_id} ask ordered: {question}")


@chat_app.command("requests")
def requests_cmd(
    ctx: typer.Context,
    kind: Annotated[str | None, typer.Option("--kind", help="spar or ask.")] = None,
    state_filter: Annotated[
        str | None, typer.Option("--state", help="open, taken, done or failed.")
    ] = None,
) -> None:
    """Every request with its derived state and, when done, the sheet or answer."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = chat_requests_service.list_requests(project, kind=kind, state=state_filter)
    typer.echo(f"{len(rows)} request(s)")
    for r in rows:
        mode = f" {r.mode}" if r.mode else ""
        follow = f" (follows {r.parent})" if r.parent else ""
        result = f" -> {r.result}" if r.result else ""
        what = r.hypothesis or r.question
        typer.echo(f"{r.request_id} {r.kind}{mode} [{r.state}]{follow}{result}: {what}")
