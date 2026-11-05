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
from sqlalchemy import text

from factory.canonical import population_digest
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, ActorKind
from factory.mining.calibration import sample_size
from factory.mining.compile import miner_digest
from factory.model.extraction import MinerScope
from factory.model.miner_calibration import CalibrationUnit, MinerCalibrationDrawn
from factory.model.miners import MINER_NAME_RE, MinerRetired
from factory.quality.stats import draw_uniform
from factory.services import audit_core
from factory.services.context import Project
from factory.services.extraction import started_works
from factory.services.gates import rigor_mode
from factory.services.mining import MinerRow, population, registered_row, require_listed

__all__ = [
    "CalibrationRow",
    "MinerProposer",
    "MinerState",
    "calibration_by_id",
    "calibration_of",
    "draw_miner_calibration",
    "miner_state",
    "proposer",
    "retire_miner",
]


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


# --- Calibration draw ---


@dataclass(frozen=True)
class CalibrationRow:
    """A drawn calibration as the projection holds it."""

    calibration_id: str
    name: str
    version: int
    digest: str
    units: tuple[CalibrationUnit, ...]
    random_seed: int
    population: int
    population_digest: str
    protocol_id: str
    event_id: str


def _calibration(project: Project, where: str, params: dict[str, object]) -> CalibrationRow | None:
    project.index.sync()
    with project.index.connect() as conn:
        head = conn.execute(
            text(
                "SELECT calibration_id, name, version, digest, random_seed, population, "
                "population_digest, protocol_id, event_id FROM miner_calibrations "
                f"WHERE {where} ORDER BY event_id LIMIT 1"
            ),
            params,
        ).one_or_none()
        if head is None:
            return None
        units = conn.execute(
            text(
                "SELECT work_id, conversion_id FROM miner_calibration_units "
                "WHERE calibration_id = :c ORDER BY work_id"
            ),
            {"c": str(head[0])},
        ).all()
    return CalibrationRow(
        calibration_id=str(head[0]),
        name=str(head[1]),
        version=int(head[2]),
        digest=str(head[3]),
        units=tuple(CalibrationUnit(work_id=str(w), conversion_id=str(c)) for w, c in units),
        random_seed=int(head[4]),
        population=int(head[5]),
        population_digest=str(head[6]),
        protocol_id=str(head[7]),
        event_id=str(head[8]),
    )


def calibration_of(project: Project, name: str, version: int) -> CalibrationRow | None:
    """The calibration drawn for `(name, version)`, or None (one per version, ruling 5)."""
    return _calibration(project, "name = :n AND version = :v", {"n": name, "v": version})


def calibration_by_id(project: Project, calibration_id: str) -> CalibrationRow | None:
    return _calibration(project, "calibration_id = :c", {"c": calibration_id})


def draw_miner_calibration(
    project: Project,
    actor: Actor,
    name: str,
    version: int,
    *,
    random_seed: int | None = None,
) -> MinerCalibrationDrawn:
    """Draw and record the calibration sample of a listed miner version (ruling 2); return the
    event payload.

    The sample is `draw_uniform` over the selector's population less the units a production pass
    of this miner already holds, of `max(regime.calibration_size, floor)` units capped at the
    population; the seed and the population digest are recorded.

    Refused, with nothing written: for a non-human actor (`actor`); a seed outside 0..2**32-1
    (`random_seed`); a miner the protocol does not list (`miners`, `protocol`); a retired version
    (`miner`); a version already drawn (`calibration`); an empty population (`population`)."""
    seed, seed_issues = audit_core.validate_seed(random_seed)
    issues: list[ValidationIssue] = list(seed_issues)
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", "calibration samples are drawn by a human"))
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        project.index.sync()
        protocol, _, spec = require_listed(project, name, version)
        row = _registered(project, name, version)
        if row.retired:
            raise FactoryValidationError(
                [ValidationIssue("miner", f"miner {name} version {version} is retired")]
            )
        if calibration_of(project, name, version) is not None:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "calibration",
                        "this version has a calibration; a retry is a new version (ruling 5)",
                    )
                ]
            )
        mined = started_works(project, scope=MinerScope(name))
        candidates = [(w, c) for w, c in population(project, spec.selector) if w not in mined]
        if not candidates:
            raise FactoryValidationError(
                [ValidationIssue("population", "no unit is left to calibrate on")]
            )
        size = sample_size(rigor_mode(project), spec.regime, len(candidates))
        drawn = draw_uniform(candidates, size, seed, key=lambda unit: unit[0])
        payload = MinerCalibrationDrawn(
            calibration_id=project.ids.new("mcl"),
            name=name,
            version=version,
            digest=miner_digest(spec),
            units=tuple(CalibrationUnit(work_id=w, conversion_id=c) for w, c in drawn),
            random_seed=seed,
            population=len(candidates),
            population_digest=population_digest(candidates),
            protocol_id=protocol.protocol_id,
        )
        project.record(
            [project.events.make("miner.calibration_drawn", payload, actor, refs=(row.miner_id,))]
        )
    return payload
