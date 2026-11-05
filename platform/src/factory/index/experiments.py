"""Projection of experiment designs, their freeze and unlock, and deviations (slice 6, plan XP-A).

`experiments` keeps one row per design: the live design JSON (amended while unfrozen), the sessions
that designed or amended it (the proposers of the gate), the freeze and unlock events and the
nonce. `experiment_amendments` and `experiment_deviations` keep one row per event.

An act is folded only when it is consistent with the rules the service enforces; an event that
fails them stays in the log, visibly unfolded, and changes nothing else (no service writes one, so
it was written by hand):
- A design is folded for a hypothesis of kind `experiment` that has no live design, or when it
  supersedes the live, unfrozen design of the same hypothesis; its `E@` equals the hash of its
  design. A frozen design is never superseded and never amended.
- A freeze and an unlock are folded only when the policy recorded equals the policy in force at
  that point of the log (the `protocols` and `project` tables), a `human` policy has a human actor,
  any other has a session outside the designers', and the autonomy label is the actor's. An unlock
  also needs a registered hypothesis.
- A deviation is folded for a frozen design from a human (the kinds people record) or a system
  actor (the kinds the platform records); never from an agent.

Handlers are total: an event naming an unknown design changes nothing, never raises. Rows are
first-write-wins per id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.hypotheses.design import (
    cell_hash,
    cell_in_design,
    config_hash,
    design_version,
    planned_cells,
    run_config,
)
from factory.index.hypotheses import policy_of
from factory.index.projection import Handler
from factory.model.experiments import (
    AUTOMATIC_DEVIATIONS,
    ExperimentAmended,
    ExperimentDesign,
    ExperimentDesigned,
    ExperimentDeviationRecorded,
    ExperimentFrozen,
    ExperimentUnlocked,
    XrunRegistered,
)
from factory.modules.contract import PolicyKind

GATE = "experiments.freeze_unlock"


@dataclass(frozen=True)
class ExperimentTables:
    experiments: Table
    amendments: Table
    deviations: Table
    xruns: Table
    protocols: Table
    project: Table
    hypotheses: Table
    registrations: Table
    """Tables of other projections the fold reads: the policy in force and the hypotheses."""


def experiment_tables(
    metadata: MetaData,
    protocols: Table,
    project: Table,
    hypotheses: Table,
    registrations: Table,
) -> ExperimentTables:
    experiments = Table(
        "experiments",
        metadata,
        Column("experiment_id", String, primary_key=True),
        Column("hypothesis", String, nullable=False),
        Column("e_version", String, nullable=False),
        Column("design_json", String, nullable=False),
        Column("designer_sessions_json", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("event_id", String, nullable=False),
        Column("frozen_event_id", String),
        Column("frozen_policy", String),
        Column("frozen_autonomy", String),
        Column("access_limit", Integer),
        Column("unlocked_event_id", String),
        Column("nonce", String),
        Column("unlock_policy", String),
        Column("unlock_autonomy", String),
        Index("ix_experiments_hypothesis", "hypothesis"),
    )
    amendments = Table(
        "experiment_amendments",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("experiment_id", String, nullable=False),
        Column("e_version", String, nullable=False),
        Column("reason", String, nullable=False),
        Column("semantic", Integer, nullable=False),
    )
    deviations = Table(
        "experiment_deviations",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("experiment_id", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("text", String, nullable=False),
        Column("semantic", Integer, nullable=False),
        Column("after_unlock", Integer, nullable=False),
        Index("ix_experiment_deviations_exp", "experiment_id"),
    )
    xruns = Table(
        "xruns",
        metadata,
        Column("run_id", String, primary_key=True),
        Column("experiment_id", String, nullable=False),
        Column("e_version", String, nullable=False),
        Column("cell_hash", String, nullable=False),
        Column("arm", String, nullable=False),
        Column("split", String, nullable=False),
        Column("seed", Integer, nullable=False),
        Column("universe_json", String, nullable=False),
        Column("config_hash", String, nullable=False),
        Column("exploratory", Integer, nullable=False),
        Column("event_id", String, nullable=False),
        Column("reported_event_id", String),
        Column("exit_status", Integer),
        Column("gpu_hours", String),
        Column("metrics_json", String),
        Column("flags_json", String),
        Column("env_differs", Integer),
        Column("nonce_ok", Integer),
        Index("ix_xruns_cell", "experiment_id", "cell_hash"),
    )
    return ExperimentTables(
        experiments, amendments, deviations, xruns, protocols, project, hypotheses, registrations
    )


def experiment_handlers(t: ExperimentTables) -> dict[str, Handler]:
    return {
        "experiment.designed": _designed(t),
        "experiment.amended": _amended(t),
        "experiment.frozen": _frozen(t),
        "experiment.unlocked": _unlocked(t),
        "experiment.deviation_recorded": _deviation(t),
        "xrun.registered": _xrun_registered(t),
    }


def act_is_consistent(
    conn: Connection,
    t: ExperimentTables,
    event: Event,
    recorded: PolicyKind,
    autonomy: str,
    proposers: set[str],
) -> bool:
    """Whether the actor of `event` may have passed the freeze or unlock gate under the policy in
    force: the recorded policy equals it, the autonomy label is the actor's, a `human` policy needs
    a human and any other needs a session outside `proposers`."""
    if event.actor.kind not in ("human", "agent"):
        return False
    if autonomy != ("human" if event.actor.kind == "human" else "agent"):
        return False
    if recorded is not policy_of(conn, t.protocols, t.project, GATE):
        return False
    if recorded is PolicyKind.HUMAN:
        return event.actor.kind == "human"
    return event.actor.session not in proposers


def _sessions(raw: object) -> set[str]:
    return {str(s) for s in json.loads(str(raw))}


def _designed(t: ExperimentTables) -> Handler:
    def designed(conn: Connection, event: Event) -> None:
        p = ExperimentDesigned.model_validate(event.payload)
        if event.actor.kind not in ("agent", "human") or p.e_version != design_version(p.design):
            return
        kind = conn.execute(
            select(t.hypotheses.c.kind).where(t.hypotheses.c.hypothesis_id == p.design.hypothesis)
        ).scalar()
        if kind != "experiment":
            return
        live = conn.execute(
            select(t.experiments.c.experiment_id, t.experiments.c.frozen_event_id).where(
                t.experiments.c.hypothesis == p.design.hypothesis,
                t.experiments.c.superseded_by.is_(None),
            )
        ).all()
        if p.supersedes is None:
            if live:
                return
        else:
            if [str(r[0]) for r in live] != [p.supersedes] or live[0][1] is not None:
                return
        inserted = conn.execute(
            sqlite_insert(t.experiments)
            .values(
                experiment_id=p.experiment_id,
                hypothesis=p.design.hypothesis,
                e_version=p.e_version,
                design_json=canonical_json(p.design.model_dump(mode="json")).decode(),
                designer_sessions_json=canonical_json([event.actor.session]).decode(),
                supersedes=p.supersedes,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["experiment_id"])
        )
        if inserted.rowcount and p.supersedes is not None:
            conn.execute(
                update(t.experiments)
                .where(t.experiments.c.experiment_id == p.supersedes)
                .values(superseded_by=p.experiment_id)
            )

    return designed


def _amended(t: ExperimentTables) -> Handler:
    def amended(conn: Connection, event: Event) -> None:
        p = ExperimentAmended.model_validate(event.payload)
        if event.actor.kind not in ("agent", "human") or p.e_version != design_version(p.design):
            return
        row = conn.execute(
            select(
                t.experiments.c.hypothesis,
                t.experiments.c.frozen_event_id,
                t.experiments.c.superseded_by,
                t.experiments.c.designer_sessions_json,
            ).where(t.experiments.c.experiment_id == p.experiment_id)
        ).first()
        if row is None or row[1] is not None or row[2] is not None:
            return
        if str(row[0]) != p.design.hypothesis:
            return
        sessions = sorted(_sessions(row[3]) | {event.actor.session})
        conn.execute(
            update(t.experiments)
            .where(t.experiments.c.experiment_id == p.experiment_id)
            .values(
                e_version=p.e_version,
                design_json=canonical_json(p.design.model_dump(mode="json")).decode(),
                designer_sessions_json=canonical_json(list(sessions)).decode(),
            )
        )
        conn.execute(
            sqlite_insert(t.amendments)
            .values(
                event_id=event.id,
                experiment_id=p.experiment_id,
                e_version=p.e_version,
                reason=p.reason,
                semantic=int(p.semantic),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return amended


def _frozen(t: ExperimentTables) -> Handler:
    def frozen(conn: Connection, event: Event) -> None:
        p = ExperimentFrozen.model_validate(event.payload)
        row = conn.execute(
            select(
                t.experiments.c.e_version,
                t.experiments.c.frozen_event_id,
                t.experiments.c.superseded_by,
                t.experiments.c.designer_sessions_json,
            ).where(t.experiments.c.experiment_id == p.experiment_id)
        ).first()
        if row is None or row[1] is not None or row[2] is not None or str(row[0]) != p.e_version:
            return
        if not act_is_consistent(conn, t, event, p.policy, p.autonomy, _sessions(row[3])):
            return
        conn.execute(
            update(t.experiments)
            .where(t.experiments.c.experiment_id == p.experiment_id)
            .values(
                frozen_event_id=event.id,
                frozen_policy=p.policy.value,
                frozen_autonomy=p.autonomy,
                access_limit=p.test_access_limit,
            )
        )

    return frozen


def _unlocked(t: ExperimentTables) -> Handler:
    def unlocked(conn: Connection, event: Event) -> None:
        p = ExperimentUnlocked.model_validate(event.payload)
        row = conn.execute(
            select(
                t.experiments.c.e_version,
                t.experiments.c.hypothesis,
                t.experiments.c.frozen_event_id,
                t.experiments.c.unlocked_event_id,
                t.experiments.c.superseded_by,
                t.experiments.c.designer_sessions_json,
            ).where(t.experiments.c.experiment_id == p.experiment_id)
        ).first()
        if row is None or row[2] is None or row[3] is not None or row[4] is not None:
            return
        if str(row[0]) != p.e_version:
            return
        registered = conn.execute(
            select(t.registrations.c.hypothesis_id).where(
                t.registrations.c.hypothesis_id == str(row[1])
            )
        ).first()
        if registered is None:
            return
        if not act_is_consistent(conn, t, event, p.policy, p.autonomy, _sessions(row[5])):
            return
        conn.execute(
            update(t.experiments)
            .where(t.experiments.c.experiment_id == p.experiment_id)
            .values(
                unlocked_event_id=event.id,
                nonce=p.nonce,
                unlock_policy=p.policy.value,
                unlock_autonomy=p.autonomy,
            )
        )

    return unlocked


def _deviation(t: ExperimentTables) -> Handler:
    def deviation(conn: Connection, event: Event) -> None:
        p = ExperimentDeviationRecorded.model_validate(event.payload)
        automatic = p.kind in AUTOMATIC_DEVIATIONS
        if event.actor.kind != ("system" if automatic else "human"):
            return
        row = conn.execute(
            select(t.experiments.c.frozen_event_id, t.experiments.c.unlocked_event_id).where(
                t.experiments.c.experiment_id == p.experiment_id
            )
        ).first()
        if row is None or row[0] is None:
            return
        conn.execute(
            sqlite_insert(t.deviations)
            .values(
                event_id=event.id,
                experiment_id=p.experiment_id,
                kind=p.kind,
                text=p.text,
                semantic=int(p.semantic),
                after_unlock=int(row[1] is not None),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return deviation


def _xrun_registered(t: ExperimentTables) -> Handler:
    """A run is folded for a frozen design of the same `E@`, with the configuration and hashes
    the platform computes from the design and the cell, a confirmatory cell only after the unlock
    and a post hoc cell only on the dev split, and while fewer than `max_runs` runs exist."""

    def registered(conn: Connection, event: Event) -> None:
        p = XrunRegistered.model_validate(event.payload)
        if event.actor.kind not in ("agent", "human"):
            return
        row = conn.execute(
            select(
                t.experiments.c.design_json,
                t.experiments.c.e_version,
                t.experiments.c.frozen_event_id,
                t.experiments.c.unlocked_event_id,
                t.experiments.c.superseded_by,
            ).where(t.experiments.c.experiment_id == p.experiment_id)
        ).first()
        if row is None or row[2] is None or row[4] is not None or str(row[1]) != p.e_version:
            return
        design = design_of(row[0])
        planned = p.cell in planned_cells(design)
        config = run_config(design, p.cell)
        if (
            p.cell_hash != cell_hash(p.cell)
            or p.config != config
            or p.config_hash != config_hash(config)
            or p.exploratory == planned
        ):
            return
        if not planned and (p.cell.split != "dev" or not cell_in_design(design, p.cell)):
            return
        if p.cell.needs_unlock and row[3] is None:
            return
        existing = conn.execute(
            select(func.count())
            .select_from(t.xruns)
            .where(t.xruns.c.experiment_id == p.experiment_id)
        ).scalar_one()
        if int(existing) >= design.budget.max_runs:
            return
        conn.execute(
            sqlite_insert(t.xruns)
            .values(
                run_id=p.run_id,
                experiment_id=p.experiment_id,
                e_version=p.e_version,
                cell_hash=p.cell_hash,
                arm=p.cell.arm,
                split=p.cell.split,
                seed=p.cell.seed,
                universe_json=canonical_json([list(c) for c in p.cell.universe]).decode(),
                config_hash=p.config_hash,
                exploratory=int(p.exploratory),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["run_id"])
        )

    return registered


def design_of(raw: object) -> ExperimentDesign:
    return ExperimentDesign.model_validate(json.loads(str(raw)))
