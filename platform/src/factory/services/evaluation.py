"""Evaluation of registered hypotheses: the computed outcome and its qualifying flags (slice 6,
plan XP-B; spec rulings 16, 17, 22, 23; R-121).

Invariants:
- The outcome is computed from recorded results and the rule fixed at registration; this module
  has no input for an outcome and writes `hypothesis.evaluated` only as the `system` actor. No tool
  or command passes one. The projector folds the event only if it equals the recomputation.
- An experiment hypothesis is evaluated on the confirmatory split of the primary universe
  (`hypotheses.evaluate`); a literature hypothesis on the final independent rows of works published
  on or after the window start that compare the two methods in a group matching its conditions.
  The unit of the latter is the work.
- `evaluate_hypothesis` is idempotent: with unchanged inputs it writes nothing and returns the live
  event; with changed inputs it writes a new event that supersedes the earlier one (none is
  removed). Evaluation is automatic after the ingestion that completes the last primary cell and
  otherwise a researcher's request (`request_incomplete` records an `incomplete` result).
- `has_live_evaluation` fills `services.hypotheses.EVALUATION_SOURCES` at import (the revision rule
  and conclusion fail open without it); `services.hypotheses` imports this module where it reads
  the list.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import cast

from pydantic import JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.errors import FactoryValidationError, ValidationIssue
from factory.hypotheses.evaluate import compute_experiment
from factory.hypotheses.literature import LitRow, compare_works
from factory.hypotheses.rules import Favour, apply_literature_rule
from factory.hypotheses.tquantiles import Level
from factory.index.evaluation import read_experiment_inputs
from factory.model.base import StrictModel
from factory.model.hypotheses import (
    EVALUATOR_VERSION,
    HypothesisEvaluated,
    LiteratureDirection,
    LiteratureTest,
    MethodRef,
)
from factory.services import hypotheses as hypothesis_service
from factory.services.context import Project
from factory.services.evidence_report import EvidenceRow, evidence_report


class EvaluationView(StrictModel):
    event_id: str
    supersedes: str | None
    payload: HypothesisEvaluated


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def evaluations_of(project: Project, hypothesis_id: str) -> list[EvaluationView]:
    """Every folded evaluation of a hypothesis, oldest first; the last is the live one."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_id, supersedes, payload_json FROM hypothesis_evaluations "
                "WHERE hypothesis_id = :h ORDER BY event_id"
            ),
            {"h": hypothesis_id},
        ).all()
    return [
        EvaluationView(
            event_id=str(r[0]),
            supersedes=None if r[1] is None else str(r[1]),
            payload=HypothesisEvaluated.model_validate(json.loads(str(r[2]))),
        )
        for r in rows
    ]


def latest_evaluation(project: Project, hypothesis_id: str) -> EvaluationView | None:
    found = evaluations_of(project, hypothesis_id)
    return found[-1] if found else None


def has_live_evaluation(project: Project, hypothesis_id: str) -> bool:
    """Whether a conclusive evaluation exists (an `incomplete` one is a progress report)."""
    return any(e.payload.outcome != "incomplete" for e in evaluations_of(project, hypothesis_id))


if has_live_evaluation not in hypothesis_service.EVALUATION_SOURCES:
    hypothesis_service.EVALUATION_SOURCES.append(has_live_evaluation)


# --- Recomputation ------------------------------------------------------------------------


def _method_name(ref: MethodRef, rows: Sequence[EvidenceRow]) -> str | None:
    if ref.name is not None:
        return ref.name
    if ref.row_key is not None:
        return next((r.method_name for r in rows if r.row_key == ref.row_key), None)
    return None


def _published(project: Project, work_ids: Sequence[str]) -> dict[str, str]:
    if not work_ids:
        return {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, json_extract(data, '$.dates.published') FROM works "
                "WHERE work_id IN (SELECT value FROM json_each(:w))"
            ),
            {"w": json.dumps(sorted(set(work_ids)))},
        ).all()
    return {str(w): str(d) for w, d in rows if d is not None}


def _recompute_literature(project: Project, hypothesis_id: str) -> HypothesisEvaluated | None:
    view = hypothesis_service.hypothesis_view(project, hypothesis_id)
    if view is None or view.state in ("draft", "reviewed", "abandoned", "superseded"):
        return None
    spec = view.spec
    rule, test = spec.decision_rule, spec.test
    if not isinstance(rule, LiteratureDirection) or not isinstance(test, LiteratureTest):
        return None
    report = evidence_report(project)
    all_rows = [r for g in report.groups for r in g.rows]
    treatment = _method_name(spec.treatment, all_rows)
    baseline = _method_name(spec.baseline, all_rows)
    start = test.window_start.isoformat()
    compared: dict[str, tuple[str, str, Favour]] = {}
    if treatment is not None and baseline is not None:
        compared = compare_works(
            [
                (
                    g.key,
                    [
                        LitRow(
                            r.work_id, r.row_key, r.method_name, r.value.canonical, r.independent
                        )
                        for r in g.rows
                    ],
                )
                for g in report.groups
            ],
            treatment=treatment,
            baseline=baseline,
            conditions=spec.conditions,
            window_start=start,
            dates=_published(project, sorted({r.work_id for r in all_rows})),
            direction=spec.metric.direction,
            margin=Decimal(spec.prediction.margin),
        )
    result = apply_literature_rule(rule, [f for _, _, f in compared.values()])
    flags = set(result.flags) | set(hypothesis_service.cutoff_flags(project, hypothesis_id))
    if treatment is None or baseline is None:
        flags.add("method-unresolved")
    if view.autonomy == "agent":
        flags.add("autonomy:agent")
    level = _registered_level(project, hypothesis_id)
    body: dict[str, JsonValue] = {
        "h": view.h_version,
        "rule": rule.model_dump(mode="json"),
        "margin": spec.prediction.margin,
        "window": start,
        "compared": [[w, *compared[w][:2]] for w in sorted(compared)],
        "favour": [compared[w][2] for w in sorted(compared)],
        "flags": cast(JsonValue, sorted(flags)),
    }
    return HypothesisEvaluated(
        hypothesis_id=hypothesis_id,
        h_version=view.h_version,
        outcome=result.outcome,
        n=len(compared),
        level=level,
        counts=dict(result.counts),
        flags=tuple(sorted(flags)),
        works=tuple(sorted(compared)),
        inputs_hash=hashlib.sha256(canonical_json(body)).hexdigest()[:16],
        evaluator_version=EVALUATOR_VERSION,
    )


def _registered_level(project: Project, hypothesis_id: str) -> Level:
    with project.index.connect() as conn:
        level: Level = conn.execute(
            text("SELECT level FROM hypothesis_registrations WHERE hypothesis_id = :h"),
            {"h": hypothesis_id},
        ).scalar_one()
    return level


def recompute(project: Project, hypothesis_id: str) -> HypothesisEvaluated | None:
    """The evaluation the log gives now for a registered hypothesis, without writing it; None for
    a hypothesis that is not registered (or an experiment hypothesis with no frozen design). The
    function `check` compares with the stored one."""
    project.index.sync()
    with project.index.connect() as conn:
        kind = conn.execute(
            text("SELECT kind FROM hypotheses WHERE hypothesis_id = :h"), {"h": hypothesis_id}
        ).scalar()
        if kind is None:
            return None
        if str(kind) == "experiment":
            inputs = read_experiment_inputs(conn, hypothesis_id)
            return None if inputs is None else compute_experiment(inputs)
    return _recompute_literature(project, hypothesis_id)


# --- Writing --------------------------------------------------------------------------------


def evaluate_hypothesis(
    project: Project, hypothesis_id: str, *, request_incomplete: bool = False
) -> str:
    """Evaluate a registered hypothesis and return the id of the live `hypothesis.evaluated` event.
    The outcome is computed; there is nothing to pass. With unchanged inputs nothing is written.
    Refused, with nothing written: an unknown hypothesis (`hypothesis_id`: `unknown`); one that is
    not registered, or abandoned or superseded (`state`: `not-registered`); an experiment
    hypothesis with no frozen design (`experiment_id`: `no-frozen-design`); a result that is
    `incomplete` without `request_incomplete` (`runs`: `incomplete`)."""
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            kind = conn.execute(
                text("SELECT kind FROM hypotheses WHERE hypothesis_id = :h"),
                {"h": hypothesis_id},
            ).scalar()
        if kind is None:
            raise _refuse("hypothesis_id", "unknown")
        view = hypothesis_service.hypothesis_view(project, hypothesis_id)
        assert view is not None
        if view.registration is None or view.state in ("abandoned", "superseded"):
            raise _refuse("state", "not-registered")
        payload = recompute(project, hypothesis_id)
        if payload is None:
            raise _refuse("experiment_id", "no-frozen-design")
        if payload.outcome == "incomplete" and not request_incomplete:
            raise _refuse("runs", "incomplete")
        live = latest_evaluation(project, hypothesis_id)
        if live is not None and live.payload.inputs_hash == payload.inputs_hash:
            return live.event_id
        refs = [hypothesis_id] + ([] if payload.experiment_id is None else [payload.experiment_id])
        event = project.events.make(
            "hypothesis.evaluated", payload, project.system_actor(), refs=refs
        )
        project.record([event])
    return event.id


def auto_evaluate(project: Project, experiment_id: str) -> str | None:
    """After an ingestion: evaluate the hypothesis of the design once its last primary cell has a
    completed run, unless a conclusive evaluation already exists. Returns the event id or None."""
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            hypothesis = conn.execute(
                text(
                    "SELECT hypothesis FROM experiments WHERE experiment_id = :e "
                    "AND superseded_by IS NULL"
                ),
                {"e": experiment_id},
            ).scalar()
        if hypothesis is None:
            return None
        hypothesis_id = str(hypothesis)
        view = hypothesis_service.hypothesis_view(project, hypothesis_id)
        if view is None or view.registration is None or view.state in ("abandoned", "superseded"):
            return None
        live = latest_evaluation(project, hypothesis_id)
        if live is not None and live.payload.outcome != "incomplete":
            return None
        payload = recompute(project, hypothesis_id)
        if payload is None or payload.outcome == "incomplete":
            return None
        return evaluate_hypothesis(project, hypothesis_id)
