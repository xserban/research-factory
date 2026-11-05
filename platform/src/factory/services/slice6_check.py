"""Check findings of slice 6: cards, leads, hypotheses, experiments, evaluations (plan XP-B task 7;
spec "Check findings"). Read-only.

Invariants:
- Each hit names artefacts by identifier and gives a count; no message carries a statement, a
  lead's text, a rationale, a conclusion or any document text.
- A project with no property, card, contradiction, lead, hypothesis or experiment has none of
  these findings. Severity by mode is the level table of the module that owns the code.
- `evaluation-stale` compares the stored conclusive evaluation with the recomputation from the log
  (outcome, inputs hash and evaluator version) and lists evaluation events that did not fold (a
  hand-written one, or one of an evaluator no longer known); `xrun-reported-without-registration` is structurally impossible (the
  projector folds a report only for a registered run) and is the broken-chain check.
- `card-imported-unverified` is not emitted: cross-project card import is not built (Later).
"""

from __future__ import annotations

from sqlalchemy import text

from factory.modules.contract import CheckHit
from factory.services.cards import card_view, list_cards
from factory.services.context import Project
from factory.services.evaluation import latest_evaluation, recompute
from factory.services.experiments import list_experiments
from factory.services.hypotheses import list_hypotheses
from factory.services.leads import list_leads
from factory.services.xrun_accounting import baseline_verdicts, budget_view

_PAGE = 500


def _hit(code: str, refs: list[str], noun: str) -> CheckHit | None:
    if not refs:
        return None
    ordered = tuple(sorted(set(refs)))
    return CheckHit(code, ordered, f"{len(ordered)} {noun}")


def _strings(project: Project, sql: str) -> list[str]:
    with project.index.connect() as conn:
        return [str(r) for r in conn.execute(text(sql)).scalars()]


def _cards(project: Project) -> list[CheckHit | None]:
    inferred: list[str] = []
    stale: list[str] = []
    offset = 0
    while page := list_cards(project, limit=_PAGE, offset=offset):
        offset += _PAGE
        for card in page:
            view = card_view(project, card.card_id, include_inferred=True, include_stale=True)
            if view is None:
                continue
            for a in view.assertions:
                if a.effective == "inferred":
                    inferred.append(a.assertion_id)
                elif a.effective == "stale":
                    stale.append(a.assertion_id)
    return [
        _hit(
            "property-proposed-unapproved",
            _strings(
                project,
                "SELECT key FROM properties WHERE state = 'proposed' AND decision_event_id IS NULL",
            ),
            "proposed propert(ies) no human has decided",
        ),
        _hit(
            "assertion-inferred-unconfirmed", inferred, "inferred assertion(s) no human confirmed"
        ),
        _hit("assertion-stale", stale, "live assertion(s) that are stale"),
        _hit(
            "contradiction-unconfirmed",
            _strings(project, "SELECT contradiction_id FROM contradictions WHERE decision IS NULL"),
            "proposed contradiction(s) no human has decided",
        ),
    ]


def _hypotheses(project: Project) -> list[CheckHit | None]:
    views = list_hypotheses(project)
    live = [v for v in views if v.state not in ("abandoned", "superseded")]
    designed = set(
        _strings(project, "SELECT hypothesis FROM experiments WHERE superseded_by IS NULL")
    )
    registered_untested = [
        v.hypothesis_id
        for v in live
        if v.state == "registered"
        and v.spec.kind == "experiment"
        and v.hypothesis_id not in designed
    ]
    return [
        _hit(
            "lead-undecided",
            [lead.lead_id for lead in list_leads(project, states=["open"])],
            "lead(s) not yet decided",
        ),
        _hit(
            "hypothesis-unreviewed",
            [v.hypothesis_id for v in live if v.state == "draft"],
            "hypothesis draft(s) without a critic's review",
        ),
        _hit(
            "hypothesis-registered-untested",
            registered_untested,
            "registered experiment hypothesis(es) with no design",
        ),
        _hit(
            "hypothesis-cutoff-unknown",
            [v.hypothesis_id for v in live if "cutoff-unknown" in v.flags],
            "literature hypothesis(es) whose drafter or critic has no declared cut-off",
        ),
        _hit(
            "hypothesis-contaminated",
            [v.hypothesis_id for v in live if "contaminated" in v.flags],
            "literature hypothesis(es) whose drafter or critic cut-off is on or after the window",
        ),
        _hit(
            "hypothesis-evaluated-unconcluded",
            [v.hypothesis_id for v in live if v.state == "evaluated" and v.conclusion is None],
            "evaluated hypothesis(es) without a human conclusion",
        ),
    ]


def _experiments(project: Project) -> list[CheckHit | None]:
    live = [e for e in list_experiments(project) if e.state != "superseded"]
    unresolved = [
        e.experiment_id
        for e in live
        if e.state == "frozen"
        and any(
            v in ("pending", "not-reproduced")
            for v in baseline_verdicts(project, e.experiment_id).values()
        )
    ]
    over = [
        e.experiment_id for e in live if (b := budget_view(project, e.experiment_id)) and b.over
    ]
    no_controls = [
        e.experiment_id
        for e in live
        if e.state != "draft"
        and not ({c.kind for c in e.design.controls} >= {"positive", "negative"})
    ]
    return [
        _hit(
            "experiment-not-frozen",
            [e.experiment_id for e in live if e.state == "draft"],
            "experiment design(s) not yet frozen",
        ),
        _hit("baseline-unresolved", unresolved, "frozen design(s) with an unresolved baseline"),
        _hit(
            "xrun-environment-differs",
            _strings(project, "SELECT run_id FROM xruns WHERE env_differs = 1"),
            "run(s) whose commit or environment differs from the design's",
        ),
        _hit(
            "xrun-reported-without-registration",
            _strings(
                project,
                "SELECT x.run_id FROM xruns x LEFT JOIN experiments e "
                "ON e.experiment_id = x.experiment_id WHERE x.reported_event_id IS NOT NULL "
                "AND (e.experiment_id IS NULL OR e.frozen_event_id IS NULL)",
            ),
            "run(s) reported against no frozen design",
        ),
        _hit("compute-budget-exceeded", over, "design(s) whose GPU-hours exceed the budget"),
        _hit(
            "test-access-exceeded",
            _strings(project, "SELECT run_id FROM xruns WHERE flags_json LIKE '%test-reused%'"),
            "run(s) that read a confirmatory cell beyond the access limit",
        ),
        _hit(
            "controls-missing",
            no_controls,
            "frozen design(s) without both a positive and a negative control",
        ),
    ]


def _evaluations(project: Project) -> list[CheckHit | None]:
    stale: list[str] = []
    for v in list_hypotheses(project):
        live = latest_evaluation(project, v.hypothesis_id)
        if live is None or live.payload.outcome == "incomplete":
            continue
        now = recompute(project, v.hypothesis_id)
        if now is None or (now.outcome, now.inputs_hash, now.evaluator_version) != (
            live.payload.outcome,
            live.payload.inputs_hash,
            live.payload.evaluator_version,
        ):
            stale.append(v.hypothesis_id)
    unfolded = _strings(
        project,
        "SELECT id FROM events WHERE type = 'hypothesis.evaluated' "
        "AND id NOT IN (SELECT event_id FROM hypothesis_evaluations)",
    )
    return [
        _hit("evaluation-stale", stale, "evaluation(s) that the log no longer gives"),
        _hit("evaluation-stale", unfolded, "evaluation event(s) in the log that did not fold"),
    ]


def slice6_hits(project: Project) -> list[CheckHit]:
    project.index.sync()
    groups = [_cards(project), _hypotheses(project), _experiments(project), _evaluations(project)]
    return [hit for group in groups for hit in group if hit is not None]
