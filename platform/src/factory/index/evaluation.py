"""Projection of hypothesis evaluations (slice 6, plan XP-B; R-121).

`hypothesis_evaluations` keeps one row per folded `hypothesis.evaluated` event: the outcome, the
flags, the inputs hash, the event it supersedes and the whole payload. The latest row of a
hypothesis is its live evaluation; none is removed.

An evaluation is folded only if the platform could have written it (a hand-written event stays in
the log, unfolded, and changes nothing else):
- the actor is `system` and not a runner (a runner submits results and nothing else);
- the hypothesis is registered and neither abandoned nor superseded;
- an experiment hypothesis: its live frozen design is the one named, and the payload equals,
  field for field, the evaluation recomputed here from the tables as they stand at that point of
  the log (`hypotheses.evaluate.compute_experiment`), the same function the service uses;
- a literature hypothesis (its evidence report cannot be recomputed from tables): the outcome and
  flags equal the rule applied to the counts in the payload, and the works listed are as many as
  the comparisons counted.
- an evaluation whose inputs hash equals that of the live one is not folded again.

Handlers are total: an event that does not validate, or names something unknown, changes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column, Index, MetaData, String, Table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.events.envelope import Event
from factory.hypotheses.evaluate import (
    DeviationRow,
    ExperimentInputs,
    RunRow,
    compute_experiment,
)
from factory.hypotheses.rules import apply_literature_rule
from factory.hypotheses.tquantiles import Level
from factory.index.experiments import design_of
from factory.index.projection import Handler
from factory.model.experiments import Cell
from factory.model.hypotheses import (
    HypothesisEvaluated,
    HypothesisSpec,
    LiteratureDirection,
    LiteratureTest,
)
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec

MIN_SEEDS_BY_MODE = {RigorMode.EXPLORATORY: 2, RigorMode.PILOT: 3, RigorMode.SYSTEMATIC: 5}
"""The plan defaults of `services.hypothesis_gates.effective_plan`, spelled once for the fold."""


@dataclass(frozen=True)
class EvaluationTables:
    evaluations: Table


def evaluation_tables(metadata: MetaData) -> EvaluationTables:
    evaluations = Table(
        "hypothesis_evaluations",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("hypothesis_id", String, nullable=False),
        Column("outcome", String, nullable=False),
        Column("flags_json", String, nullable=False),
        Column("inputs_hash", String, nullable=False),
        Column("supersedes", String),
        Column("payload_json", String, nullable=False),
        Index("ix_hypothesis_evaluations_hyp", "hypothesis_id"),
    )
    return EvaluationTables(evaluations)


def plan_in_force(conn: Connection) -> tuple[int, Level]:
    """Minimum seeds and confidence level of the latest protocol recorded so far, with the mode's
    default for a field it leaves open."""
    mode_raw = conn.execute(text("SELECT rigor_mode FROM project LIMIT 1")).scalar()
    mode = RigorMode(str(mode_raw)) if mode_raw is not None else RigorMode.PILOT
    row = conn.execute(text("SELECT spec FROM protocols ORDER BY event_id DESC LIMIT 1")).first()
    plan = None if row is None else ProtocolSpec.model_validate_json(str(row[0])).hypothesis_plan
    min_seeds = plan.min_seeds if plan is not None and plan.min_seeds is not None else None
    level: Level = "0.95" if plan is None else plan.confidence
    return (min_seeds if min_seeds is not None else MIN_SEEDS_BY_MODE[mode]), level


def registered_hypothesis(conn: Connection, hypothesis_id: str) -> Any:
    """The hypothesis row and its registration when it is registered, not abandoned and not
    superseded; else None."""
    return conn.execute(
        text(
            "SELECT h.h_version, h.kind, h.spec_json, r.autonomy FROM hypotheses h "
            "JOIN hypothesis_registrations r ON r.hypothesis_id = h.hypothesis_id "
            "WHERE h.hypothesis_id = :h AND h.abandoned_event_id IS NULL "
            "AND h.superseded_by IS NULL"
        ),
        {"h": hypothesis_id},
    ).first()


def read_experiment_inputs(conn: Connection, hypothesis_id: str) -> ExperimentInputs | None:
    """Everything the outcome of an experiment hypothesis depends on, read from the tables as they
    stand. None when the hypothesis is not a registered experiment hypothesis with a frozen live
    design."""
    hyp = registered_hypothesis(conn, hypothesis_id)
    if hyp is None or str(hyp[1]) != "experiment":
        return None
    exp = conn.execute(
        text(
            "SELECT experiment_id, e_version, design_json, frozen_autonomy, unlock_autonomy "
            "FROM experiments WHERE hypothesis = :h AND superseded_by IS NULL "
            "AND frozen_event_id IS NOT NULL ORDER BY event_id DESC LIMIT 1"
        ),
        {"h": hypothesis_id},
    ).first()
    if exp is None:
        return None
    experiment_id = str(exp[0])
    runs = tuple(
        RunRow(
            run_id=str(r[0]),
            cell=Cell(
                universe=tuple((str(k), str(v)) for k, v in json.loads(str(r[1]))),
                seed=int(r[2]),
                arm=str(r[3]),
                split=r[4],
            ),
            reported_event_id=None if r[5] is None else str(r[5]),
            exit_status=None if r[6] is None else int(r[6]),
            metrics=None
            if r[7] is None
            else {str(k): str(v) for k, v in json.loads(str(r[7])).items()},
            flags=frozenset() if r[8] is None else frozenset(json.loads(str(r[8]))),
        )
        for r in conn.execute(
            text(
                "SELECT run_id, universe_json, seed, arm, split, reported_event_id, exit_status, "
                "metrics_json, flags_json FROM xruns WHERE experiment_id = :e ORDER BY run_id"
            ),
            {"e": experiment_id},
        ).all()
    )
    deviations = tuple(
        DeviationRow(str(r[0]), bool(r[1]), bool(r[2]))
        for r in conn.execute(
            text(
                "SELECT kind, semantic, after_unlock FROM experiment_deviations "
                "WHERE experiment_id = :e ORDER BY event_id"
            ),
            {"e": experiment_id},
        ).all()
    )
    accepted = (
        conn.execute(
            text(
                "SELECT 1 FROM baseline_evaluations WHERE experiment_id = :e "
                "AND accepted_event_id IS NOT NULL LIMIT 1"
            ),
            {"e": experiment_id},
        ).first()
        is not None
    )
    min_seeds, level = plan_in_force(conn)
    return ExperimentInputs(
        hypothesis_id=hypothesis_id,
        h_version=str(hyp[0]),
        spec=HypothesisSpec.model_validate(json.loads(str(hyp[2]))),
        experiment_id=experiment_id,
        e_version=str(exp[1]),
        design=design_of(exp[2]),
        runs=runs,
        deviations=deviations,
        baseline_accepted=accepted,
        autonomy=tuple(str(a) for a in (hyp[3], exp[3], exp[4]) if a is not None),
        min_seeds=min_seeds,
        level=level,
    )


def live_evaluation(conn: Connection, hypothesis_id: str) -> Any:
    """The latest folded evaluation of a hypothesis (event id and inputs hash), else None."""
    return conn.execute(
        text(
            "SELECT event_id, inputs_hash FROM hypothesis_evaluations "
            "WHERE hypothesis_id = :h ORDER BY event_id DESC LIMIT 1"
        ),
        {"h": hypothesis_id},
    ).first()


def literature_consistent(p: HypothesisEvaluated, spec: HypothesisSpec) -> bool:
    """Whether a literature evaluation is what the rule gives for its own counts."""
    rule = spec.decision_rule
    if not isinstance(rule, LiteratureDirection) or not isinstance(spec.test, LiteratureTest):
        return False
    c = p.counts
    k, j, n = c.get("favour_treatment", -1), c.get("favour_baseline", -1), c.get("n", -1)
    ties = c.get("ties", -1)
    if min(k, j, n, ties) < 0 or k + j + ties != n or n != len(p.works) or p.n != n:
        return False
    favour = ["treatment"] * k + ["baseline"] * j + ["tie"] * ties
    result = apply_literature_rule(rule, favour)  # type: ignore[arg-type]
    return (
        p.outcome == result.outcome
        and set(result.flags) <= set(p.flags)
        and p.runs == ()
        and p.experiment_id is None
    )


def _evaluated(t: EvaluationTables) -> Handler:
    def evaluated(conn: Connection, event: Event) -> None:
        p = HypothesisEvaluated.model_validate(event.payload)
        if event.actor.kind != "system" or event.actor.id.startswith("runner-"):
            return
        hyp = registered_hypothesis(conn, p.hypothesis_id)
        if hyp is None or str(hyp[0]) != p.h_version:
            return
        if str(hyp[1]) == "experiment":
            inputs = read_experiment_inputs(conn, p.hypothesis_id)
            if inputs is None or compute_experiment(inputs) != p:
                return
        elif not literature_consistent(p, HypothesisSpec.model_validate(json.loads(str(hyp[2])))):
            return
        live = live_evaluation(conn, p.hypothesis_id)
        if live is not None and str(live[1]) == p.inputs_hash:
            return
        conn.execute(
            sqlite_insert(t.evaluations)
            .values(
                event_id=event.id,
                hypothesis_id=p.hypothesis_id,
                outcome=p.outcome,
                flags_json=canonical_json(list(p.flags)).decode(),
                inputs_hash=p.inputs_hash,
                supersedes=None if live is None else str(live[0]),
                payload_json=canonical_json(p.model_dump(mode="json")).decode(),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return evaluated


def evaluation_handlers(t: EvaluationTables) -> dict[str, Handler]:
    def total(handler: Handler) -> Handler:
        def run(conn: Connection, event: Event) -> None:
            try:
                handler(conn, event)
            except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError, IndexError):
                return

        return run

    return {"hypothesis.evaluated": total(_evaluated(t))}
