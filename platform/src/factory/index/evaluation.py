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
- a literature hypothesis (its evidence report cannot be recomputed from tables): every comparison
  names a work inside the window and live rows of it, and the outcome, counts, flags (the rule's,
  the cut-offs, the autonomy label), level and hash are the ones those comparisons give.
- an evaluation with the inputs hash and evaluator version of the live one is not folded again;
- an evaluation of a retired evaluator (`RETIRED_EVALUATORS`) cannot be recomputed and folds on
  structure, so that a version change erases nothing; `check` reports it.

Handlers are total: an event that does not validate, or names something unknown, changes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
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
from factory.hypotheses.literature import literature_hash
from factory.hypotheses.rules import apply_literature_rule, favour_of
from factory.index.experiments import design_of
from factory.index.hypotheses import cutoff_flags_of
from factory.index.projection import Handler
from factory.model.experiments import Cell
from factory.model.hypotheses import (
    HypothesisEvaluated,
    HypothesisSpec,
    LiteratureComparison,
    LiteratureDirection,
    LiteratureTest,
    RETIRED_EVALUATORS,
)


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
        Column("evaluator_version", String, nullable=False),
        Column("supersedes", String),
        Column("payload_json", String, nullable=False),
        Index("ix_hypothesis_evaluations_hyp", "hypothesis_id"),
    )
    return EvaluationTables(evaluations)


def registered_hypothesis(conn: Connection, hypothesis_id: str) -> Any:
    """The hypothesis row and its registration when it is registered, not abandoned and not
    superseded; else None."""
    return conn.execute(
        text(
            "SELECT h.h_version, h.kind, h.spec_json, r.autonomy, r.level, r.min_seeds "
            "FROM hypotheses h "
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
        min_seeds=int(hyp[5]),
        level=hyp[4],
    )


def live_evaluation(conn: Connection, hypothesis_id: str) -> Any:
    """The latest folded evaluation of a hypothesis (event id and inputs hash), else None."""
    return conn.execute(
        text(
            "SELECT event_id, inputs_hash, evaluator_version FROM hypothesis_evaluations "
            "WHERE hypothesis_id = :h ORDER BY event_id DESC LIMIT 1"
        ),
        {"h": hypothesis_id},
    ).first()


def _row_values(conn: Connection, work_id: str, row_key: str) -> set[str | None] | None:
    """The canonical values of the live rows of a key in a work, None when it has no such row."""
    rows = conn.execute(
        text(
            "SELECT f.canonical FROM extraction_rows r JOIN extraction_fields f "
            "ON f.extraction_id = r.extraction_id AND f.field = 'value' "
            "WHERE r.work_id = :w AND r.row_key = :k AND r.superseded_by IS NULL"
        ),
        {"w": work_id, "k": row_key},
    ).all()
    return {None if r[0] is None else str(r[0]) for r in rows} or None


def _comparison_holds(
    conn: Connection, c: LiteratureComparison, spec: HypothesisSpec, window_start: str
) -> bool:
    """The work exists inside the window and both rows are live rows of it. The side it favours
    is recomputed when the passes agree on each value; where they differ a resolution decides, and
    `check` recomputes that one."""
    published = conn.execute(
        text("SELECT json_extract(data, '$.dates.published') FROM works WHERE work_id = :w"),
        {"w": c.work_id},
    ).first()
    if published is None or published[0] is None or str(published[0]) < window_start:
        return False
    treatment = _row_values(conn, c.work_id, c.treatment_row)
    baseline = _row_values(conn, c.work_id, c.baseline_row)
    if treatment is None or baseline is None:
        return False
    if len(treatment) == 1 and len(baseline) == 1:
        t, b = next(iter(treatment)), next(iter(baseline))
        if t is not None and b is not None:
            margin = Decimal(spec.prediction.margin)
            return favour_of(Decimal(t), Decimal(b), spec.metric.direction, margin) == c.favour
    return True


def literature_consistent(conn: Connection, p: HypothesisEvaluated, hyp: Any) -> bool:
    """Whether a literature evaluation is what the log gives, as far as tables can say: the
    evidence report cannot be recomputed here, so each comparison is checked against the works and
    extraction tables, and the outcome, counts, flags, level and hash are recomputed from them."""
    spec = HypothesisSpec.model_validate(json.loads(str(hyp[2])))
    rule, test = spec.decision_rule, spec.test
    if not isinstance(rule, LiteratureDirection) or not isinstance(test, LiteratureTest):
        return False
    if p.experiment_id is not None or p.e_version is not None or p.runs:
        return False
    if (p.mean, p.ci_low, p.ci_high) != (None, None, None) or p.level != hyp[4]:
        return False
    works = [c.work_id for c in p.comparisons]
    if len(set(works)) != len(works) or p.works != tuple(sorted(works)) or p.n != len(works):
        return False
    start = test.window_start.isoformat()
    if not all(_comparison_holds(conn, c, spec, start) for c in p.comparisons):
        return False
    result = apply_literature_rule(rule, [c.favour for c in p.comparisons])
    flags = set(result.flags) | set(cutoff_flags_of(conn, p.hypothesis_id))
    if str(hyp[3]) == "agent":
        flags.add("autonomy:agent")
    flags |= set(p.flags) & {"method-unresolved"}
    return (
        p.outcome == result.outcome
        and dict(p.counts) == dict(result.counts)
        and p.flags == tuple(sorted(flags))
        and p.inputs_hash == literature_hash(spec, p.h_version, p.comparisons, p.flags)
    )


def _structurally_sound(conn: Connection, p: HypothesisEvaluated, hyp: Any) -> bool:
    """An evaluation of a retired evaluator cannot be recomputed: it folds if what it names exists
    (the level fixed at registration, the design, reported runs of it, known works), so a rebuild
    after a version change keeps it, and `check` reports it as `evaluation-stale`."""
    if p.level != hyp[4]:
        return False
    if str(hyp[1]) == "experiment":
        inputs = read_experiment_inputs(conn, p.hypothesis_id)
        if inputs is None or (p.experiment_id, p.e_version) != (
            inputs.experiment_id,
            inputs.e_version,
        ):
            return False
        reported = {r.run_id for r in inputs.runs if r.reported_event_id is not None}
        return set(p.runs) <= reported
    known = {
        str(w)
        for w in conn.execute(
            text("SELECT work_id FROM works WHERE work_id IN (SELECT value FROM json_each(:w))"),
            {"w": json.dumps(list(p.works))},
        ).scalars()
    }
    return not p.runs and set(p.works) <= known


def _evaluated(t: EvaluationTables) -> Handler:
    def evaluated(conn: Connection, event: Event) -> None:
        p = HypothesisEvaluated.model_validate(event.payload)
        if event.actor.kind != "system" or event.actor.id.startswith("runner-"):
            return
        hyp = registered_hypothesis(conn, p.hypothesis_id)
        if hyp is None or str(hyp[0]) != p.h_version:
            return
        if p.evaluator_version in RETIRED_EVALUATORS:
            if not _structurally_sound(conn, p, hyp):
                return
        elif str(hyp[1]) == "experiment":
            inputs = read_experiment_inputs(conn, p.hypothesis_id)
            if inputs is None or compute_experiment(inputs) != p:
                return
        elif not literature_consistent(conn, p, hyp):
            return
        live = live_evaluation(conn, p.hypothesis_id)
        if live is not None and (str(live[1]), str(live[2])) == (
            p.inputs_hash,
            p.evaluator_version,
        ):
            return
        conn.execute(
            sqlite_insert(t.evaluations)
            .values(
                event_id=event.id,
                hypothesis_id=p.hypothesis_id,
                outcome=p.outcome,
                flags_json=canonical_json(list(p.flags)).decode(),
                inputs_hash=p.inputs_hash,
                evaluator_version=p.evaluator_version,
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
