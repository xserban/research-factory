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


@dataclass(frozen=True)
class SelectionAnswer:
    """What the person ticked and wrote: item ids, one added text per non-blank line, a note."""

    selected: tuple[str, ...]
    added: tuple[str, ...]
    note: str


def _selection_form(item_ids: Sequence[str]) -> type[BaseModel]:
    choice = cast(Any, Literal)[tuple(item_ids)]
    fields: dict[str, Any] = {
        "selected": (cast(Any, list)[choice], Field(default_factory=list)),
        "added": (str, Field(default="")),
        "note": (str, Field(default="")),
    }
    return create_model("DecisionSelection", **fields)


async def elicit_selection(
    ctx: ToolContext, title: str, explanation: str, items: Sequence[tuple[str, str]]
) -> SelectionAnswer | None:
    """Ask the person to tick items (a multi-select over the item ids), add items of their own
    (free text, one per line) and give a note. None when the person did not accept or the
    exchange failed."""
    lines = [title, explanation, *(f"{item_id}: {text}" for item_id, text in items)]
    form = _selection_form([item_id for item_id, _ in items])
    try:
        answer = await ctx.elicit("\n".join(lines), form)
    except (ValueError, MCPError):
        return None
    if answer.action != "accept":
        return None
    data = answer.data.model_dump()
    ticked = tuple(dict.fromkeys(str(v) for v in data["selected"]))
    added = tuple(line.strip() for line in str(data["added"]).splitlines() if line.strip())
    return SelectionAnswer(ticked, added, str(data["note"]).strip())


def elicit_human_selection(
    title: str, explanation: str, items: Sequence[tuple[str, str]]
) -> SelectionAnswer:
    """The person's selection in the running tool call, asked through the client and never
    relayed. Refused on field `elicit`, with nothing asked, when the call has no credential
    (stdio, or an unauthenticated connection) or the client does not declare elicitation; refused
    too when the person declines or cancels."""
    call = current_call()
    context = call.context
    if call.principal.credential is None or context is None or not declares_elicitation(context):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "elicit",
                    "a selection is made by the person through an elicitation form: this "
                    "connection has no credential or the client does not support elicitation; "
                    "use `factory decide select`",
                )
            ]
        )
    ask = partial(elicit_selection, context, title, explanation, items)
    answer = from_thread.run(ask)
    if answer is None:
        raise FactoryValidationError([ValidationIssue("elicit", "the person did not accept")])
    return answer
