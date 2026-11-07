"""Human acts by channel: what is refused, and what is counted (slice 5 ruling 11, R-111).

Invariants:
- A refusal writes nothing and is one issue on field `channel`. `index/human_channel.py` holds the
  rules, which the folds apply as well.
- Counts are read from the log, never typed. A project with no human act reads no event file.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import bindparam, text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.index.human_channel import elicit_forged, relay_barred
from factory.model.screening import Channel
from factory.services.context import Project

HumanAct = Literal["sign-off", "audit-label", "label", "resolve"]

HUMAN_ACT_EVENTS: tuple[str, ...] = (
    "calibration.labelled",
    "audit.labelled",
    "gate.audit_labelled",
    "screening.disagreement_resolved",
    "extraction.resolved",
    "extraction.audit_labelled",
    "miner.calibration_labelled",
    "notice.assessed",
    "review.decided",
    "decision.selected",
)
"""The acts a person makes that a relay can carry. `review.decided` lands with teams-B."""

_NEEDS_THE_PERSON: frozenset[HumanAct] = frozenset({"sign-off", "audit-label"})


def require_human_channel(project: Project, actor: Actor, channel: Channel, act: HumanAct) -> None:
    """Refuse a `systematic` relay of a sign-off or audit label (cli or elicit only), and an
    `elicit` that no authenticated person made. The caller holds the write lock."""
    with project.index.connect() as conn:
        barred = act in _NEEDS_THE_PERSON and relay_barred(conn, actor, channel)
    if barred:
        raise FactoryValidationError(
            [ValidationIssue("channel", "in systematic mode this act needs the cli or elicitation")]
        )
    if elicit_forged(actor, channel):
        raise FactoryValidationError(
            [ValidationIssue("channel", "elicit is an authenticated person's channel")]
        )


@dataclass(frozen=True)
class HumanActCounts:
    relayed: int = 0
    elicited: int = 0


def human_act_counts(project: Project) -> HumanActCounts:
    """How many human acts came as relays (`channel = mcp`) and by elicitation."""
    query = text(
        "SELECT 1 FROM events WHERE actor_kind = 'human' AND type IN :types LIMIT 1"
    ).bindparams(bindparam("types", expanding=True))
    with project.index.connect() as conn:
        if conn.execute(query, {"types": list(HUMAN_ACT_EVENTS)}).first() is None:
            return HumanActCounts()
    channels = [
        event.payload.get("channel")
        for event in read_all(project.paths.events_dir, project.catalog)
        if event.type in HUMAN_ACT_EVENTS and event.actor.kind == "human"
    ]
    return HumanActCounts(
        relayed=channels.count(Channel.MCP.value), elicited=channels.count(Channel.ELICIT.value)
    )
