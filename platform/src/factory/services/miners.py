"""Lifecycle of registered miners: state, proposer and retirement (slice M, M-D).

Invariants:
- A miner's state is computed from the log (the projection of `miner.registered`,
  `miner.retired`, the calibration events); nothing stores a state.
- The proposer of a miner version is the actor of its first registration; a later registration of
  the same spec writes nothing, so the proposer never changes.
- Retirement is an event; a retired miner's rows stay and `check` and the methods report it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import ValidationError

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, ActorKind
from factory.model.miners import MINER_NAME_RE, MinerRetired
from factory.services.context import Project
from factory.services.mining import MinerRow, registered_row

__all__ = ["MinerProposer", "MinerState", "miner_state", "proposer", "retire_miner"]


class MinerState(StrEnum):
    REGISTERED = "registered"
    CALIBRATING = "calibrating"
    CALIBRATED = "calibrated"
    FAILED = "failed"
    RETIRED = "retired"


@dataclass(frozen=True)
class MinerProposer:
    """The registering actor of a miner version: `(actor.kind, actor.session)` (ruling 1)."""

    kind: ActorKind
    session: str


def _registered(project: Project, name: str, version: int) -> MinerRow:
    row = registered_row(project, name, version)
    if row is None:
        raise FactoryValidationError(
            [ValidationIssue("version", f"miner {name} version {version} is not registered")]
        )
    return row


def proposer(project: Project, name: str, version: int) -> MinerProposer:
    """The proposer of a registered version. Raises on field `version` when it is not registered."""
    row = _registered(project, name, version)
    return MinerProposer(row.proposer_kind, row.proposer_session)


def miner_state(project: Project, name: str, version: int) -> MinerState:
    """The lifecycle state of a registered version: `retired` once retired, else `registered`
    until a calibration is drawn (later tasks refine the others)."""
    row = _registered(project, name, version)
    return MinerState.RETIRED if row.retired else MinerState.REGISTERED


def retire_miner(project: Project, actor: Actor, name: str, version: int, reason: str) -> None:
    """Retire a registered miner version (any state). Refused, with nothing written: for a system
    actor (`actor`); a built-in miner (`name`); an unregistered version (`version`); a blank or
    over-long reason (`reason`). Retiring a retired version again writes nothing."""
    if actor.kind == "system":
        raise FactoryValidationError(
            [ValidationIssue("actor", "an agent or a human retires a miner")]
        )
    if re.match(MINER_NAME_RE, name) is None:
        raise FactoryValidationError(
            [ValidationIssue("name", "a built-in miner cannot be retired")]
        )
    with project.index.exclusive():
        project.index.sync()
        row = _registered(project, name, version)
        if row.retired:
            return
        try:
            payload = MinerRetired(name=name, version=version, reason=reason.strip())
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(map(str, e["loc"])) or "reason", str(e["msg"]))
                    for e in exc.errors()
                ]
            ) from exc
        event = project.events.make(
            "miner.retired",
            payload,
            actor,
            refs=(row.miner_id,),
            input_blob=(
                project.blobs.put_json(payload.model_dump(mode="json"))
                if actor.kind == "agent"
                else None
            ),
        )
        project.record([event])
