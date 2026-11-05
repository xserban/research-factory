"""Experiment designs: drafting, amendment before the freeze, the freeze and deviations after it
(slice 6, plan XP-A; rulings 3, 4, 8 and 14 to 24 of the spec).

Invariants:
- A design is an `exp_` id with a version `E@` the platform computes from the design
  (`hypotheses.design.design_version`); no input carries an id, a version, a state or a flag.
  There is one live design per hypothesis; a new design replaces an unfrozen one and never a
  frozen one.
- Amendments are free until the freeze and recorded with a reason. After the freeze nothing can
  change the design: `amend_experiment` is refused and a change is a deviation, a human act that
  flags the outcome `deviated` when it is marked semantic and comes after the unlock (R-14).
- The freeze and the unlock are acts at the gate `experiments.freeze_unlock` (slice-M policy): a
  `human` policy needs a human, any other a session outside the designers' (R-51). The freeze
  records the access limit then in force; a later protocol amendment cannot raise it.
- The state is computed on read: `superseded`, then `unlocked`, `frozen`, else `draft`.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.extraction.numbers import normalise_text
from factory.hypotheses.design import design_issues, design_version
from factory.index.experiments import design_of
from factory.model.base import StrictModel
from factory.model.experiments import (
    AUTOMATIC_DEVIATIONS,
    BaselineAccepted,
    DeviationKind,
    ExperimentAmended,
    ExperimentDesign,
    ExperimentDesigned,
    ExperimentDeviationRecorded,
    ExperimentFrozen,
    ExperimentUnlocked,
)
from factory.model.project import RigorMode
from factory.services.context import Project
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import final_rows, key_value
from factory.services.hypotheses import hypothesis_view
from factory.services.hypothesis_gates import effective_plan, may_pass, project_mode
from factory.services.xrun_accounting import (
    BudgetView,
    access_counts,
    baseline_flags,
    baseline_verdicts,
    budget_view,
)

ExperimentState = Literal["draft", "frozen", "unlocked", "superseded"]


class DeviationView(StrictModel):
    event_id: str
    kind: str
    text: str
    semantic: bool
    after_unlock: bool


class ExperimentView(StrictModel):
    experiment_id: str
    hypothesis: str
    e_version: str
    design: ExperimentDesign
    state: ExperimentState
    deviations: list[DeviationView]
    flags: tuple[str, ...]
    event_id: str
    supersedes: str | None
    superseded_by: str | None
    designer_sessions: tuple[str, ...]
    access_limit: int | None
    """The confirmatory reads per primary cell fixed at the freeze; None before it."""
    frozen_event: str | None = None
    unlocked_event: str | None = None
    budget: BudgetView
    access: dict[str, int]
    """Primary cell hash to the completed confirmatory runs of that cell (ruling 18)."""


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


# --- Views --------------------------------------------------------------------------------------


def _state(row: Any) -> ExperimentState:
    if row.superseded_by is not None:
        return "superseded"
    if row.unlocked_event_id is not None:
        return "unlocked"
    return "frozen" if row.frozen_event_id is not None else "draft"


def _deviations(project: Project, experiment_id: str) -> list[DeviationView]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_id, kind, text, semantic, after_unlock FROM experiment_deviations "
                "WHERE experiment_id = :e ORDER BY event_id"
            ),
            {"e": experiment_id},
        ).all()
    return [
        DeviationView(
            event_id=str(r[0]),
            kind=str(r[1]),
            text=str(r[2]),
            semantic=bool(r[3]),
            after_unlock=bool(r[4]),
        )
        for r in rows
    ]


def _view(project: Project, row: Any) -> ExperimentView:
    experiment_id = str(row.experiment_id)
    deviations = _deviations(project, experiment_id)
    budget = budget_view(project, experiment_id)
    assert budget is not None
    flags: set[str] = set(baseline_flags(project, experiment_id))
    if any(d.semantic and d.after_unlock for d in deviations):
        flags.add("deviated")
    return ExperimentView(
        experiment_id=experiment_id,
        hypothesis=str(row.hypothesis),
        e_version=str(row.e_version),
        design=design_of(row.design_json),
        state=_state(row),
        deviations=deviations,
        flags=tuple(sorted(flags)),
        event_id=str(row.event_id),
        supersedes=None if row.supersedes is None else str(row.supersedes),
        superseded_by=None if row.superseded_by is None else str(row.superseded_by),
        designer_sessions=tuple(json.loads(str(row.designer_sessions_json))),
        access_limit=None if row.access_limit is None else int(row.access_limit),
        frozen_event=None if row.frozen_event_id is None else str(row.frozen_event_id),
        unlocked_event=None if row.unlocked_event_id is None else str(row.unlocked_event_id),
        budget=budget,
        access=access_counts(project, experiment_id),
    )


def experiment_view(project: Project, experiment_id: str) -> ExperimentView | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM experiments WHERE experiment_id = :e"), {"e": experiment_id}
        ).first()
    return None if row is None else _view(project, row)


def live_experiment(project: Project, hypothesis_id: str) -> ExperimentView | None:
    """The hypothesis's live (unsuperseded) design, if any."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM experiments WHERE hypothesis = :h AND superseded_by IS NULL"),
            {"h": hypothesis_id},
        ).first()
    return None if row is None else _view(project, row)


def list_experiments(project: Project) -> list[ExperimentView]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT * FROM experiments ORDER BY experiment_id")).all()
    return [_view(project, r) for r in rows]


# --- Validation ---------------------------------------------------------------------------------


def _baseline_issues(
    project: Project, design: ExperimentDesign, conditions: dict[str, str]
) -> list[ValidationIssue]:
    """Each baseline names a final evidence row whose values for the hypothesis's conditions equal
    them (`not-a-final-row`, `conditions-differ`)."""
    if not design.baselines:
        return []
    rows = {r.row_key: r for r in final_rows(project)}
    try:
        _protocol, _schema, pack = require_schema(project)
    except FactoryValidationError:
        pack = None
    issues: list[ValidationIssue] = []
    for i, baseline in enumerate(design.baselines):
        row = rows.get(baseline.row_key)
        if row is None:
            issues.append(ValidationIssue(f"baselines.{i}.row_key", "not-a-final-row"))
            continue
        for key, wanted in conditions.items():
            field = row.fields.get(key)
            if field is None:
                issues.append(ValidationIssue(f"baselines.{i}.row_key", "conditions-differ"))
                break
            seen = {normalise_text(str(field.value))}
            if pack is not None:
                seen.add(normalise_text(key_value(pack.field(key), field)))
            if normalise_text(wanted) not in seen:
                issues.append(ValidationIssue(f"baselines.{i}.row_key", "conditions-differ"))
                break
    return issues


def _design_checks(project: Project, design: ExperimentDesign) -> list[ValidationIssue]:
    """Every rule that needs the project: the plan's minimum seeds and access limit, the
    hypothesis (an experiment hypothesis that is not yet evaluated, abandoned or superseded, whose
    metric the primary metric is) and the baselines."""
    plan = effective_plan(project)
    assert plan.min_seeds is not None
    issues = design_issues(design, min_seeds=plan.min_seeds)
    if design.test_access_limit is not None and design.test_access_limit > plan.test_access_limit:
        issues.append(ValidationIssue("test_access_limit", "above-plan"))
    hypothesis = hypothesis_view(project, design.hypothesis)
    if hypothesis is None:
        issues.append(ValidationIssue("hypothesis", "unknown"))
        return issues
    if hypothesis.spec.kind != "experiment":
        issues.append(ValidationIssue("hypothesis", "not-an-experiment"))
    if hypothesis.state not in ("draft", "reviewed", "registered"):
        issues.append(ValidationIssue("hypothesis", f"state-{hypothesis.state}"))
    primaries = [m for m in design.metrics if m.primary]
    if primaries:
        wanted = hypothesis.spec.metric
        primary = primaries[0]
        if (
            normalise_text(primary.name) != normalise_text(wanted.name)
            or primary.direction != wanted.direction
        ):
            issues.append(ValidationIssue("metrics", "not-hypothesis-metric"))
    issues.extend(_baseline_issues(project, design, hypothesis.spec.conditions))
    return issues


def _require_author(actor: Actor) -> None:
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human drafts a design")


def _input_blob(project: Project, actor: Actor, body: JsonValue) -> str | None:
    return project.blobs.put_json(body) if actor.kind == "agent" else None


# --- Designing and amending ---------------------------------------------------------------------


def design_experiment(
    project: Project,
    actor: Actor,
    design: ExperimentDesign,
    *,
    supersedes: str | None = None,
) -> tuple[str, str]:
    """Record a design and return `(exp_ id, E@)`. Refused, with nothing written: an actor that is
    neither agent nor human (`actor`); a hypothesis that is unknown, not an experiment or already
    evaluated, abandoned or superseded (`hypothesis`); any rule of `design_issues`; a primary
    metric other than the hypothesis's (`metrics`); a baseline that is not a final row or whose
    comparability values differ from the hypothesis's conditions (`baselines.<i>.row_key`); a
    hypothesis that already has a live design unless `supersedes` names it and it is unfrozen
    (`hypothesis`: `design-exists`; `supersedes`)."""
    _require_author(actor)
    with project.index.exclusive():
        project.index.sync()
        issues = _design_checks(project, design)
        live = live_experiment(project, design.hypothesis)
        if supersedes is None:
            if live is not None:
                issues.append(ValidationIssue("hypothesis", "design-exists"))
        else:
            old = experiment_view(project, supersedes)
            if old is None:
                issues.append(ValidationIssue("supersedes", "unknown"))
            elif old.hypothesis != design.hypothesis:
                issues.append(ValidationIssue("supersedes", "other-hypothesis"))
            elif old.superseded_by is not None:
                issues.append(ValidationIssue("supersedes", "already-superseded"))
            elif old.state != "draft":
                issues.append(ValidationIssue("supersedes", "frozen"))
        if issues:
            raise FactoryValidationError(issues)
        experiment_id = project.ids.new("exp")
        version = design_version(design)
        payload = ExperimentDesigned(
            experiment_id=experiment_id,
            design=design,
            e_version=version,
            supersedes=supersedes,
        )
        blob = _input_blob(project, actor, payload.model_dump(mode="json"))
        refs = [experiment_id, design.hypothesis] + ([supersedes] if supersedes else [])
        project.record(
            [project.events.make("experiment.designed", payload, actor, refs=refs, input_blob=blob)]
        )
    return experiment_id, version


def amend_experiment(
    project: Project,
    actor: Actor,
    experiment_id: str,
    design: ExperimentDesign,
    reason: str,
    semantic: bool,
) -> str:
    """Replace the design of an unfrozen experiment and return the event id; `E@` is recomputed.
    Refused, with nothing written: an unknown or superseded experiment (`experiment_id`); a frozen
    one (`experiment_id`: `frozen`; a change after the freeze is a deviation); a design for another
    hypothesis (`design.hypothesis`); a blank or long reason (`reason`); any rule of
    `design_experiment`."""
    _require_author(actor)
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        issues: list[ValidationIssue] = []
        if view is None:
            raise _refuse("experiment_id", "unknown")
        if view.state == "superseded":
            issues.append(ValidationIssue("experiment_id", "superseded"))
        elif view.state != "draft":
            issues.append(ValidationIssue("experiment_id", "frozen"))
        if design.hypothesis != view.hypothesis:
            issues.append(ValidationIssue("design.hypothesis", "differs"))
        if not reason.strip() or len(reason) > 300:
            issues.append(ValidationIssue("reason", "between 1 and 300 characters"))
        if not issues:
            issues.extend(_design_checks(project, design))
        if issues:
            raise FactoryValidationError(issues)
        payload = ExperimentAmended(
            experiment_id=experiment_id,
            design=design,
            e_version=design_version(design),
            reason=reason.strip(),
            semantic=semantic,
        )
        blob = _input_blob(project, actor, payload.model_dump(mode="json"))
        event = project.events.make(
            "experiment.amended", payload, actor, refs=[experiment_id], input_blob=blob
        )
        project.record([event])
    return event.id


# --- Freeze and unlock --------------------------------------------------------------------------


def freeze_experiment(project: Project, actor: Actor, experiment_id: str) -> str:
    """Freeze the design (an act at the gate `experiments.freeze_unlock`) and return the event id.
    `E@` is then fixed and records the confirmatory reads per primary cell then allowed. Refused,
    with nothing written: an unknown, superseded or already frozen experiment (`experiment_id`); a
    design that no longer passes `design_experiment`'s checks under the plan now in force; an
    agent at a `human` gate (`actor`); a designer's session under an `agent` policy
    (`session`)."""
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        if view is None:
            raise _refuse("experiment_id", "unknown")
        if view.state != "draft":
            raise _refuse("experiment_id", f"state-{view.state}")
        issues = _design_checks(project, view.design)
        if issues:
            raise FactoryValidationError(issues)
        verdict = may_pass(
            project,
            actor,
            "experiments.freeze_unlock",
            proposer_sessions=set(view.designer_sessions),
        )
        verdict.raise_if_refused()
        limit = view.design.test_access_limit or effective_plan(project).test_access_limit
        payload = ExperimentFrozen(
            experiment_id=experiment_id,
            e_version=view.e_version,
            policy=verdict.policy.kind,
            autonomy=verdict.autonomy,
            test_access_limit=limit,
        )
        blob = _input_blob(project, actor, payload.model_dump(mode="json"))
        event = project.events.make(
            "experiment.frozen", payload, actor, refs=[experiment_id], input_blob=blob
        )
        project.record([event])
    return event.id


def _unlock_issues(project: Project, view: ExperimentView) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    hypothesis = hypothesis_view(project, view.hypothesis)
    if hypothesis is None or hypothesis.state != "registered":
        issues.append(ValidationIssue("hypothesis", "hypothesis-not-registered"))
    if view.state != "frozen":
        issues.append(ValidationIssue("experiment_id", "not-frozen"))
    verdicts = baseline_verdicts(project, view.experiment_id)
    if any(
        verdicts.get(b.row_key, "pending") not in ("reproduced", "accepted")
        for b in view.design.baselines
    ):
        issues.append(ValidationIssue("baselines", "baseline-unresolved"))
    if project_mode(project) is RigorMode.SYSTEMATIC:
        kinds = {c.kind for c in view.design.controls}
        if kinds != {"positive", "negative"}:
            issues.append(ValidationIssue("controls", "controls-missing"))
    return issues


def unlock_experiment(project: Project, actor: Actor, experiment_id: str) -> str:
    """Unlock confirmatory runs (an act at the gate `experiments.freeze_unlock`) and return the
    event id. The 128-bit nonce is generated here and stored in the event; confirmatory results
    must carry it. Refused, with nothing written: an unknown experiment (`experiment_id`); a
    hypothesis that is not registered (`hypothesis`: `hypothesis-not-registered`); a design that is
    not frozen or is already unlocked (`experiment_id`); a baseline neither reproduced nor accepted
    (`baselines`: `baseline-unresolved`); in systematic mode, a design without a positive and a
    negative control (`controls`: `controls-missing`); the gate's refusals, as in the freeze."""
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        if view is None:
            raise _refuse("experiment_id", "unknown")
        if view.state == "unlocked":
            raise _refuse("experiment_id", "state-unlocked")
        issues = _unlock_issues(project, view)
        if issues:
            raise FactoryValidationError(issues)
        verdict = may_pass(
            project,
            actor,
            "experiments.freeze_unlock",
            proposer_sessions=set(view.designer_sessions),
        )
        verdict.raise_if_refused()
        payload = ExperimentUnlocked(
            experiment_id=experiment_id,
            e_version=view.e_version,
            nonce=secrets.token_hex(16),
            policy=verdict.policy.kind,
            autonomy=verdict.autonomy,
        )
        blob = _input_blob(project, actor, {"experiment_id": experiment_id})
        event = project.events.make(
            "experiment.unlocked", payload, actor, refs=[experiment_id], input_blob=blob
        )
        project.record([event])
    return event.id


def unlock_nonce(project: Project, experiment_id: str) -> str | None:
    """The nonce of an unlocked experiment, for the human surface that prints it once."""
    project.index.sync()
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT nonce FROM experiments WHERE experiment_id = :e"), {"e": experiment_id}
        ).scalar()
    return None if value is None else str(value)


# --- Deviations ---------------------------------------------------------------------------------


def make_deviation_event(
    project: Project,
    actor: Actor,
    view: ExperimentView,
    kind: DeviationKind,
    note: str,
    semantic: bool,
) -> Event:
    payload = ExperimentDeviationRecorded(
        experiment_id=view.experiment_id,
        kind=kind,
        text=note.strip(),
        semantic=semantic,
        after_unlock=view.state == "unlocked",
    )
    return project.events.make(
        "experiment.deviation_recorded", payload, actor, refs=[view.experiment_id]
    )


def record_deviation(
    project: Project,
    actor: Actor,
    experiment_id: str,
    kind: DeviationKind,
    note: str,
    semantic: bool,
) -> str:
    """Record a departure from a frozen design (R-14) and return the event id. A human records
    the kinds people record; the platform's own kinds (`budget-overrun`, `test-reuse`) are written
    by a `system` actor only and `baseline-accepted` only by `accept_baseline`. After the unlock a
    semantic deviation flags the design `deviated`. Refused, with nothing written: an unknown
    experiment (`experiment_id`); one that is not frozen (`experiment_id`: `not-frozen`, change it
    with an amendment); the wrong actor for the kind (`actor`); a blank or long note (`note`)."""
    issues: list[ValidationIssue] = []
    automatic = kind in AUTOMATIC_DEVIATIONS
    if automatic and actor.kind != "system":
        issues.append(ValidationIssue("actor", "platform-only"))
    elif not automatic and actor.kind != "human":
        issues.append(ValidationIssue("actor", "human-only"))
    if kind == "baseline-accepted":
        issues.append(ValidationIssue("kind", "use-accept-baseline"))
    if not note.strip() or len(note) > 600:
        issues.append(ValidationIssue("note", "between 1 and 600 characters"))
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        if view is None:
            issues.append(ValidationIssue("experiment_id", "unknown"))
        elif view.state in ("draft", "superseded"):
            issues.append(ValidationIssue("experiment_id", "not-frozen"))
        if issues or view is None:
            raise FactoryValidationError(issues)
        event = make_deviation_event(project, actor, view, kind, note, semantic)
        project.record([event])
    return event.id


# --- Accepting a baseline that did not reproduce ------------------------------------------------


def accept_baseline(
    project: Project, actor: Actor, experiment_id: str, row_key: str, rationale: str
) -> str:
    """Accept a baseline whose reproduction failed (an act at the gate
    `experiments.accept_baseline`, human in every mode) and return the event id. It writes the
    acceptance and a `baseline-accepted` deviation, unblocks the unlock, and flags every outcome of
    the design `baseline-not-reproduced` (R-122). Refused, with nothing written: an agent
    (`actor`); an unknown experiment (`experiment_id`) or one that is not frozen; a row that is
    not a baseline of the design (`row_key`: `not-a-baseline`), has no verdict yet (`pending`),
    reproduced (`reproduced`) or is already accepted (`accepted`); a blank or long rationale
    (`rationale`)."""
    with project.index.exclusive():
        project.index.sync()
        view = experiment_view(project, experiment_id)
        issues: list[ValidationIssue] = []
        if view is None:
            raise _refuse("experiment_id", "unknown")
        if view.state in ("draft", "superseded"):
            issues.append(ValidationIssue("experiment_id", "not-frozen"))
        verdict = baseline_verdicts(project, experiment_id).get(row_key)
        if verdict is None:
            issues.append(ValidationIssue("row_key", "not-a-baseline"))
        elif verdict != "not-reproduced":
            issues.append(ValidationIssue("row_key", verdict))
        if not rationale.strip() or len(rationale) > 300:
            issues.append(ValidationIssue("rationale", "between 1 and 300 characters"))
        if issues:
            raise FactoryValidationError(issues)
        may_pass(
            project,
            actor,
            "experiments.accept_baseline",
            proposer_sessions=set(view.designer_sessions),
        ).raise_if_refused()
        accepted = project.events.make(
            "baseline.accepted",
            BaselineAccepted(
                experiment_id=experiment_id, row_key=row_key, rationale=rationale.strip()
            ),
            actor,
            refs=[experiment_id, row_key],
        )
        deviation = make_deviation_event(
            project,
            actor,
            view,
            "baseline-accepted",
            f"baseline {row_key} accepted without reproduction: {rationale.strip()}"[:600],
            False,
        )
        project.record([accepted, deviation])
    return accepted.id
