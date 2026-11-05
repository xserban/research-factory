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
  also needs a registered hypothesis and every baseline reproduced or accepted. A baseline verdict
  is folded only when the runs it lists give it (the mean and the verdict are recomputed).
- A deviation is folded for a frozen design from a human (the kinds people record) or a system
  actor (the kinds the platform records); never from an agent.

Handlers are total: an event naming an unknown design changes nothing, never raises. Rows are
first-write-wins per id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.hypotheses.design import (
    access_hash,
    cell_hash,
    cell_in_design,
    config_hash,
    design_version,
    planned_cells,
    run_config,
)
from factory.hypotheses.reproduction import reproduced_value, reproduction_verdict
from factory.index.hypotheses import policy_of
from factory.index.projection import Handler
from factory.model.experiments import (
    AUTOMATIC_DEVIATIONS,
    BaselineAccepted,
    BaselineEvaluated,
    Cell,
    ExperimentAmended,
    ExperimentDesign,
    ExperimentDesigned,
    ExperimentDeviationRecorded,
    ExperimentFrozen,
    ExperimentUnlocked,
    XrunRegistered,
    XrunReported,
)
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec
from factory.modules.contract import PolicyKind

GATE = "experiments.freeze_unlock"


@dataclass(frozen=True)
class ExperimentTables:
    experiments: Table
    amendments: Table
    deviations: Table
    xruns: Table
    baselines: Table
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
        Column("baseline_values_json", String),
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
        Column("access_hash", String),
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
        Index("ix_xruns_access", "experiment_id", "access_hash"),
    )
    baselines = Table(
        "baseline_evaluations",
        metadata,
        Column("experiment_id", String, primary_key=True),
        Column("row_key", String, primary_key=True),
        Column("verdict", String, nullable=False),
        Column("reproduced", String),
        Column("reported", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("accepted_event_id", String),
    )
    return ExperimentTables(
        experiments,
        amendments,
        deviations,
        xruns,
        baselines,
        protocols,
        project,
        hypotheses,
        registrations,
    )


def _total(handler: Handler) -> Handler:
    """A handler that cannot raise on what a log holds: an event whose payload does not validate,
    or whose values the fold cannot compute with, changes nothing (the log may be edited by hand,
    and a rebuild must still finish)."""

    def total(conn: Connection, event: Event) -> None:
        try:
            handler(conn, event)
        except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError, IndexError):
            return

    return total


def experiment_handlers(t: ExperimentTables) -> dict[str, Handler]:
    return {k: _total(h) for k, h in _handlers(t).items()}


def _handlers(t: ExperimentTables) -> dict[str, Handler]:
    return {
        "experiment.designed": _designed(t),
        "experiment.amended": _amended(t),
        "experiment.frozen": _frozen(t),
        "experiment.unlocked": _unlocked(t),
        "experiment.deviation_recorded": _deviation(t),
        "xrun.registered": _xrun_registered(t),
        "xrun.reported": _xrun_reported(t),
        "baseline.evaluated": _baseline_evaluated(t),
        "baseline.accepted": _baseline_accepted(t),
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


def plan_access_limit(conn: Connection, t: ExperimentTables) -> int:
    """`hypothesis_plan.test_access_limit` of the latest protocol recorded so far, else 1."""
    row = conn.execute(
        select(t.protocols.c.spec).order_by(t.protocols.c.event_id.desc()).limit(1)
    ).first()
    if row is None:
        return 1
    plan = ProtocolSpec.model_validate_json(str(row[0])).hypothesis_plan
    return 1 if plan is None else plan.test_access_limit


def mode_in_force(conn: Connection, t: ExperimentTables) -> RigorMode:
    """The rigor mode of the project (the `project` table), pilot if it is not there yet."""
    row = conn.execute(select(t.project.c.rigor_mode).limit(1)).first()
    return RigorMode(str(row[0])) if row else RigorMode.PILOT


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
        designers = {event.actor.session}
        if p.supersedes is not None:  # whoever drafted the replaced design still proposed this one
            earlier = conn.execute(
                select(t.experiments.c.designer_sessions_json).where(
                    t.experiments.c.experiment_id == p.supersedes
                )
            ).scalar_one()
            designers |= _sessions(earlier)
        inserted = conn.execute(
            sqlite_insert(t.experiments)
            .values(
                experiment_id=p.experiment_id,
                hypothesis=p.design.hypothesis,
                e_version=p.e_version,
                design_json=canonical_json(p.design.model_dump(mode="json")).decode(),
                designer_sessions_json=canonical_json(list(sorted(designers))).decode(),
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
                t.experiments.c.design_json,
            ).where(t.experiments.c.experiment_id == p.experiment_id)
        ).first()
        if row is None or row[1] is not None or row[2] is not None or str(row[0]) != p.e_version:
            return
        # the allowance is the design's or the plan's at this point of the log, never the payload's
        frozen_design = design_of(row[4])
        if p.test_access_limit != (frozen_design.test_access_limit or plan_access_limit(conn, t)):
            return
        if set(p.baseline_values) != {b.row_key for b in frozen_design.baselines}:
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
                baseline_values_json=canonical_json(dict(p.baseline_values)).decode(),
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
        design = design_of(
            conn.execute(
                select(t.experiments.c.design_json).where(
                    t.experiments.c.experiment_id == p.experiment_id
                )
            ).scalar_one()
        )
        if mode_in_force(conn, t) is RigorMode.SYSTEMATIC and {c.kind for c in design.controls} != {
            "positive",
            "negative",
        }:
            return  # systematic mode: a positive and a negative control (R-54)
        for baseline in design.baselines:
            verdict = conn.execute(
                select(t.baselines.c.verdict, t.baselines.c.accepted_event_id).where(
                    t.baselines.c.experiment_id == p.experiment_id,
                    t.baselines.c.row_key == baseline.row_key,
                )
            ).first()
            if verdict is None or (verdict[0] != "reproduced" and verdict[1] is None):
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
                t.experiments.c.hypothesis,
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
        if p.cell.is_reproduction and p.cell.split == "confirmatory":
            registered = conn.execute(
                select(t.registrations.c.hypothesis_id).where(
                    t.registrations.c.hypothesis_id == str(row[5])
                )
            ).first()
            if registered is None:  # it reads the test split: the hypothesis is registered first
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
                access_hash=access_hash(p.cell),
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


def run_cell(row: object) -> Cell:
    """The cell a registered run was registered against."""
    r = row._mapping  # type: ignore[attr-defined]
    return Cell(
        universe=tuple((str(k), str(v)) for k, v in json.loads(str(r["universe_json"]))),
        seed=int(r["seed"]),
        arm=str(r["arm"]),
        split=r["split"],
    )


def report_flags(design: ExperimentDesign, p: XrunReported, *, reused: bool) -> tuple[str, ...]:
    """The flags a report carries, computed from the design and the access count (never typed)."""
    flags: set[str] = set()
    if p.exit_status != 0:
        flags.add("failed")
    if p.code_commit != design.code.commit or p.environment != design.environment:
        flags.add("environment-differs")
    if reused:
        flags.add("test-reused")
    return tuple(sorted(flags))


def _xrun_reported(t: ExperimentTables) -> Handler:
    """A report is folded for a registered, unreported run from a human or a `system` runner; its
    metrics are the design's (all of them unless the run failed); a gated (confirmatory) run must
    carry the unlock nonce. Flags are recomputed here, not taken from the payload."""

    def reported(conn: Connection, event: Event) -> None:
        p = XrunReported.model_validate(event.payload)
        if event.actor.kind not in ("human", "system"):
            return
        if event.actor.kind == "system" and not event.actor.id.startswith("runner-"):
            return  # the platform writes verdicts and deviations, never a result
        run = conn.execute(select(t.xruns).where(t.xruns.c.run_id == p.run_id)).first()
        if run is None or run.reported_event_id is not None:
            return
        exp = conn.execute(
            select(
                t.experiments.c.design_json, t.experiments.c.nonce, t.experiments.c.access_limit
            ).where(t.experiments.c.experiment_id == run.experiment_id)
        ).first()
        if exp is None:
            return
        design = design_of(exp[0])
        cell = run_cell(run)
        wanted = {m.name for m in design.metrics}
        if not set(p.metrics) <= wanted or (p.exit_status == 0 and set(p.metrics) != wanted):
            return
        if cell.needs_unlock and (exp[1] is None or p.nonce != str(exp[1])):
            return
        reused = False
        if run.access_hash is not None:
            prior = conn.execute(
                select(func.count())
                .select_from(t.xruns)
                .where(
                    t.xruns.c.experiment_id == run.experiment_id,
                    t.xruns.c.access_hash == run.access_hash,
                    t.xruns.c.reported_event_id.is_not(None),
                    t.xruns.c.metrics_json.is_not(None),
                    t.xruns.c.metrics_json != "{}",
                )
            ).scalar_one()
            reused = bool(p.metrics) and int(prior) >= int(exp[2] or 1)
        flags = report_flags(design, p, reused=reused)
        conn.execute(
            update(t.xruns)
            .where(t.xruns.c.run_id == p.run_id)
            .values(
                reported_event_id=event.id,
                exit_status=p.exit_status,
                gpu_hours=p.gpu_hours,
                metrics_json=canonical_json({k: v.value for k, v in p.metrics.items()}).decode(),
                flags_json=canonical_json(list(flags)).decode(),
                env_differs=int("environment-differs" in flags),
                nonce_ok=1 if cell.needs_unlock else None,
            )
        )

    return reported


def _reproduction_run(
    conn: Connection, t: ExperimentTables, p: BaselineEvaluated, run_id: str
) -> Any:
    """A reported, planned reproduction run of the baseline in `p`, else None."""
    run = conn.execute(select(t.xruns).where(t.xruns.c.run_id == run_id)).first()
    if (
        run is None
        or run.experiment_id != p.experiment_id
        or run.arm != f"reproduction:{p.row_key}"
        or run.exploratory
        or run.reported_event_id is None
    ):
        return None
    return run


def _baseline_evaluated(t: ExperimentTables) -> Handler:
    """A verdict is folded once per baseline, from a `system` actor, and only if it is the one the
    runs give: every run it lists is a completed, planned reproduction run of that baseline, and
    the mean and the verdict recomputed from them equal the ones recorded. A hand-written verdict
    changes nothing."""

    def evaluated(conn: Connection, event: Event) -> None:
        p = BaselineEvaluated.model_validate(event.payload)
        if event.actor.kind != "system":
            return
        exp = conn.execute(
            select(
                t.experiments.c.design_json,
                t.experiments.c.frozen_event_id,
                t.experiments.c.baseline_values_json,
            ).where(t.experiments.c.experiment_id == p.experiment_id)
        ).first()
        if exp is None or exp[1] is None:
            return
        design = design_of(exp[0])
        if json.loads(str(exp[2])).get(p.row_key) != p.reported:
            return  # the reported value is the one frozen with the design
        baseline = next((b for b in design.baselines if b.row_key == p.row_key), None)
        if baseline is None or (p.tolerance, p.tolerance_kind) != (
            baseline.tolerance,
            baseline.tolerance_kind,
        ):
            return
        metric = next(m.name for m in design.metrics if m.primary)
        values: list[str] = []
        used: set[int] = set()
        for run_id in p.runs:
            run = _reproduction_run(conn, t, p, run_id)
            if run is None or run.exit_status != 0 or run.metrics_json is None or run.seed in used:
                return
            earlier = conn.execute(
                select(func.count())
                .select_from(t.xruns)
                .where(
                    t.xruns.c.experiment_id == p.experiment_id,
                    t.xruns.c.arm == f"reproduction:{p.row_key}",
                    t.xruns.c.exploratory == 0,
                    t.xruns.c.seed == run.seed,
                    t.xruns.c.exit_status == 0,
                    t.xruns.c.reported_event_id < run.reported_event_id,
                )
            ).scalar_one()
            if int(earlier):  # the first completed run of a seed is the one used (no best-of-n)
                return
            used.add(int(run.seed))
            values.append(str(json.loads(str(run.metrics_json))[metric]))
        left_out: set[int] = set()
        for run_id in p.excluded_runs:
            run = _reproduction_run(conn, t, p, run_id)
            if run is None or run.exit_status == 0:
                return
            left_out.add(int(run.seed))
        if used & left_out or used | left_out != set(design.seeds):
            return  # every declared seed is either in the mean or a seed that only failed
        reproduced = reproduced_value(values)
        if reproduced != p.reproduced:
            return
        if reproduction_verdict(p.reported, reproduced, p.tolerance, p.tolerance_kind) != p.verdict:
            return
        conn.execute(
            sqlite_insert(t.baselines)
            .values(
                experiment_id=p.experiment_id,
                row_key=p.row_key,
                verdict=p.verdict,
                reproduced=p.reproduced,
                reported=p.reported,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["experiment_id", "row_key"])
        )

    return evaluated


def _baseline_accepted(t: ExperimentTables) -> Handler:
    """An acceptance is a human act on a baseline whose verdict is not `reproduced`; the first
    one wins. (The gate `experiments.accept_baseline` is `human` in every mode.)"""

    def accepted(conn: Connection, event: Event) -> None:
        p = BaselineAccepted.model_validate(event.payload)
        if event.actor.kind != "human":
            return
        conn.execute(
            update(t.baselines)
            .where(
                t.baselines.c.experiment_id == p.experiment_id,
                t.baselines.c.row_key == p.row_key,
                t.baselines.c.verdict != "reproduced",
                t.baselines.c.accepted_event_id.is_(None),
            )
            .values(accepted_event_id=event.id)
        )

    return accepted


def design_of(raw: object) -> ExperimentDesign:
    return ExperimentDesign.model_validate(json.loads(str(raw)))
