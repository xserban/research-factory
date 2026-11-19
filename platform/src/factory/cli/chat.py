"""`factory chat`: requests for a headless spar or ask (plan spar-night N3).

Business logic stays in `services/chat_requests.py`. The researcher orders a spar or an ask here
(`request` writes one `chat.requested` event as the human) and lists the orders with their derived
state (`requests`). A headless run (`factory runs start spar|ask`) takes the oldest open request of
its kind. A v2 spar (`--engine v2`, the agentic spar of `services/spar_v2.py`) is worked by role
runs that `advance` starts one after another; `requests` shows its next role and session count.
For a Prepare spar the case for is a second request: `--parent <sht_ id> --mode prepare`.
The shared helpers of `factory.cli.main` are imported inside the commands, because that module
imports this one.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.errors import FactoryValidationError
from factory.services import chat_requests as chat_requests_service
from factory.services import runner
from factory.services import spar_v2 as spar_v2_service
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
    engine: Annotated[
        str,
        typer.Option("--engine", help="v1 (one run, default) or v2 (separate role runs)."),
    ] = "v1",
    max_sessions: Annotated[
        int | None,
        typer.Option("--max-sessions", help="v2: most role sessions (default 15, at least 5)."),
    ] = None,
) -> None:
    """Order a spar as the researcher. Prepare writes only the case against in v1; order the case
    for afterwards with `--parent <sheet> --mode prepare`. A v2 spar writes both cases in separate
    sessions; start it with `factory chat advance <request id>`."""
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
            engine=engine,
            max_sessions=max_sessions,
        )
    typer.echo(f"{payload.request_id} spar ({payload.mode}, {engine}) ordered: {hypothesis}")


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
        v2 = ""
        if r.engine == "v2":
            v2 = f" v2 {r.sessions}/{r.max_sessions or spar_v2_service.DEFAULT_MAX_SESSIONS}"
            if r.next_role:
                v2 += f" next {r.next_role}"
            if r.readers_cut:
                v2 += f" ({len(r.readers_cut)} readers cut)"
        typer.echo(f"{r.request_id} {r.kind}{mode}{v2} [{r.state}]{follow}{result}: {what}")


@chat_app.command("advance")
def advance_cmd(
    ctx: typer.Context,
    request_id: Annotated[str, typer.Argument(help="A v2 spar request (chr_ id).")],
    retry: Annotated[
        bool, typer.Option("--retry/--no-retry", help="Retry a failed role as a new run.")
    ] = True,
    wait: Annotated[
        bool, typer.Option("--wait", help="Stay until the request is done or a role fails.")
    ] = False,
) -> None:
    """Start the next role run of a v2 spar request (a failed role is retried). After a role run
    ends, the process that watches it starts the next role; with `--wait` this command stays and
    does that."""
    import time

    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            run_id = spar_v2_service.advance(project, request_id, retry=retry)
        except FactoryValidationError as exc:
            for issue in exc.issues:
                typer.echo(f"{issue.field}: {issue.reason}", err=True)
            raise typer.Exit(2) from exc
        if run_id is None:
            typer.echo(f"{request_id}: every role is done")
            return
        current = spar_v2_service.progress(project, request_id)
        typer.echo(f"started {run_id} ({current.next.role if current.next else 'done'})")
        while wait:
            running = spar_v2_service.progress(project, request_id)
            if running.open_run is not None:
                runner.wait_until_closed(project, running.open_run)
                time.sleep(1.0)  # the watcher starts the next role right after the run closes
                continue
            break
        if wait:
            final = chat_requests_service.view_request(project, request_id)
            typer.echo(
                f"{request_id}: {final.state}"
                + (f" at {final.next_role}" if final.next_role else "")
            )
