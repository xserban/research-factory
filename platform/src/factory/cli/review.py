"""`factory review deferred list|decide`: the human's deferred review of agent-closed acts
(contract C6). Parse, call `services/deferred_review`, format. Registered under the `review`
group by `factory.cli.team`.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.model.screening import Channel
from factory.services import deferred_review

deferred_app = typer.Typer(
    name="deferred",
    help="Agent-closed acts waiting for a human (human only).",
    no_args_is_help=True,
)


@deferred_app.command("list")
def deferred_list_cmd(ctx: typer.Context) -> None:
    """The sampled agent-closed acts no human has labelled yet."""
    from factory.cli import main

    state = main._state(ctx)
    with main._reporting_errors():
        project = main._resolve_project(state)
        items = deferred_review.deferred_items(project)
    if not items:
        typer.echo("no deferred review")
        return
    for item in items:
        typer.echo(f"{item.audit_id} {item.act_event_id} {item.gate_id} trust={item.trust_state}")


@deferred_app.command("decide")
def deferred_decide_cmd(
    ctx: typer.Context,
    audit_id: Annotated[str, typer.Argument(help="The gate audit holding the act.")],
    act: Annotated[str, typer.Argument(help="The agent-closed act event.")],
    verdict: Annotated[str, typer.Argument(help="correct or overturn.")],
    note: Annotated[str | None, typer.Option("--note", help="Why, if overturned.")] = None,
) -> None:
    """A human's decision on one deferred act; an overturn counts in the trust ledger."""
    from factory.cli import main

    if verdict not in ("correct", "overturn"):
        main._fail("verdict: must be correct or overturn", 2)
    state = main._state(ctx)
    with main._reporting_errors():
        project = main._resolve_project(state)
        deferred_review.decide_deferred(
            project, project.human_actor(), audit_id, act, verdict, note, Channel.CLI
        )
    typer.echo(f"decided {act} in {audit_id} ({verdict})")
