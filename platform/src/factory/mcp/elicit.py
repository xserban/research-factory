"""Asking the human through the client (slice 5 ruling 11; plan ruling 3).

The platform asks a person and never a model. The form shows the model's proposal; what is written
is what the person answered.

Invariants:
- A tool asks before it takes any lock, and from its worker thread, so a person who takes an hour
  to answer holds nothing up.
- An answer that is not an accept, or a failed exchange, is a refusal: nothing is written.
- On stdio nothing is asked, whatever the client declares, so stdio stays as it was.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal, cast

from anyio import from_thread
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel, Field, create_model

from factory.errors import FactoryValidationError, ValidationIssue
from factory.mcp.sessions import ToolContext, current_call
from factory.model.screening import Channel


@dataclass(frozen=True)
class ElicitOutcome:
    accepted: bool
    values: dict[str, str]


def declares_elicitation(context: ToolContext | None) -> bool:
    if context is None:
        return False
    capabilities = context.client_capabilities
    if capabilities is None or capabilities.elicitation is None:
        return False
    declared = capabilities.elicitation
    return declared.form is not None or declared.url is None  # an empty object means form


def _form(proposed: Mapping[str, str], choices: Mapping[str, Sequence[str]]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for name, value in proposed.items():
        allowed = choices.get(name)
        if allowed is None:
            fields[name] = (str, Field(default=value))
        elif value in allowed:
            fields[name] = (cast(Any, Literal)[tuple(allowed)], Field(default=value))
        else:
            fields[name] = (cast(Any, Literal)[tuple(allowed)], Field())
    return create_model("Confirmation", **fields)


async def elicit_confirmation(
    ctx: ToolContext,
    title: str,
    proposed: Mapping[str, str],
    choices: Mapping[str, Sequence[str]],
) -> ElicitOutcome:
    """Ask the person to accept or change `proposed`. `choices` closes a field to its listed
    values; a field not named there is free text."""
    lines = [title, *(f"{name}: {value}" for name, value in proposed.items())]
    try:
        answer = await ctx.elicit("\n".join(lines), _form(proposed, choices))
    except (ValueError, MCPError):
        return ElicitOutcome(False, {})
    if answer.action != "accept":
        return ElicitOutcome(False, {})
    return ElicitOutcome(True, {name: str(v) for name, v in answer.data.model_dump().items()})


def confirm_human_act(
    title: str,
    proposed: Mapping[str, str],
    choices: Mapping[str, Sequence[str]] | None = None,
) -> tuple[Channel, dict[str, str]]:
    """The channel and values of a human act in the running tool call. Over HTTP to a client that
    declares elicitation, the person's answer and `elicit`, or a refusal on field `elicit`.
    Otherwise the values as sent and `mcp`, a relay; the service says whether a relay may stand."""
    call = current_call()
    context = call.context
    if call.principal.credential is None or context is None or not declares_elicitation(context):
        return Channel.MCP, dict(proposed)
    ask = partial(elicit_confirmation, context, title, proposed, choices or {})
    outcome = from_thread.run(ask)
    if not outcome.accepted:
        raise FactoryValidationError([ValidationIssue("elicit", "the person did not accept")])
    return Channel.ELICIT, outcome.values
