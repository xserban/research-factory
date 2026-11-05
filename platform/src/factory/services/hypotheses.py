"""Hypotheses: drafting, states, the revision rule and abandonment (slice 6, plan H-C; rulings 3,
5, 6 and 12).

Invariants:
- A hypothesis is a `hyp_` id with a version `H@` the platform computes from the decision-relevant
  fields of its spec (`model.hypotheses.hypothesis_version`); an agent never sets a version, a state
  or a flag. A revision is a new `hyp_` that names the one it supersedes.
- A draft may be superseded freely. A registered hypothesis may be superseded only while no
  evaluation exists for it and no confirmatory result references its design: otherwise the old one
  must be evaluated or abandoned (`evidence-exists`, R-52). The evaluation and confirmatory tests
  are provider hooks (`EVALUATION_SOURCES`, `CONFIRMATORY_SOURCES`) that plans XP-A and XP-B fill;
  until then neither exists.
- The state is computed on read from the events and the hooks: `abandoned`, then `superseded`,
  then `evaluated`, `registered`, `reviewed`, else `draft`.
- Abandonment and conclusion are human acts; a conclusion needs an evaluation and is labelled as
  interpretation by the surfaces; it never changes an outcome.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection
from datetime import date
from typing import Any, Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.hypotheses import (
    AbandonReason,
    HypothesisAbandoned,
    HypothesisConcluded,
    HypothesisDrafted,
    HypothesisRegistered,
    HypothesisSpec,
    LiteratureTest,
    MethodRef,
    ModelCutoffDeclared,
    falsifier_text,
    hypothesis_version,
)
from factory.packs import NON_COMPARABLE_KEYS
from factory.services.context import Project
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import final_rows
from factory.services.hypothesis_gates import effective_plan, may_pass, project_mode
from factory.services.ideas import idea_view, resolve_idea
from factory.services.leads import card_keys, lead_view

HypothesisState = Literal["draft", "reviewed", "registered", "evaluated", "abandoned", "superseded"]
Autonomy = Literal["human", "agent"]

Provider = Callable[[Project, str], bool]
EVALUATION_SOURCES: list[Provider] = []
"""Tests for "a `hypothesis.evaluated` event exists for this hypothesis"; plan XP-B fills it."""
CONFIRMATORY_SOURCES: list[Provider] = []
"""Tests for "a confirmatory run references this hypothesis's design"; plan XP-A fills it."""


class HypothesisView(StrictModel):
    hypothesis_id: str
    h_version: str
    spec: HypothesisSpec
    falsifier: str
    state: HypothesisState
    reviews: list[str]
    registration: str | None
    flags: tuple[str, ...]
    autonomy: Autonomy | None
    event_id: str
    supersedes: str | None
    superseded_by: str | None
    drafter_session: str
    drafter_model: str | None = None
    abandon_reason: str | None = None
    conclusion: str | None = None


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def has_evaluation(project: Project, hypothesis_id: str) -> bool:
    return any(source(project, hypothesis_id) for source in EVALUATION_SOURCES)


def has_confirmatory_evidence(project: Project, hypothesis_id: str) -> bool:
    """Whether a confirmatory result references the hypothesis's design; False until plan XP-A
    registers its test."""
    return any(source(project, hypothesis_id) for source in CONFIRMATORY_SOURCES)


def _has_evidence(project: Project, hypothesis_id: str) -> bool:
    return has_evaluation(project, hypothesis_id) or has_confirmatory_evidence(
        project, hypothesis_id
    )


# --- Validation ---------------------------------------------------------------------------


def _comparability_keys(project: Project) -> set[str]:
    try:
        _protocol, schema, pack = require_schema(project)
    except FactoryValidationError:
        return set()
    keys = schema.comparability_keys or pack.default_comparability_keys
    return {k for k in keys if k not in NON_COMPARABLE_KEYS}


def _exists(project: Project, table: str, column: str, value: str) -> bool:
    with project.index.connect() as conn:
        found = conn.execute(
            text(f"SELECT 1 FROM {table} WHERE {column} = :v"),
            {"v": value},
        ).first()
    return found is not None


def _method_issues(
    project: Project, name: str, ref: MethodRef, final_keys: set[str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if ref.card is not None:
        with project.index.connect() as conn:
            kind = conn.execute(
                text("SELECT kind FROM cards WHERE card_id = :c"), {"c": ref.card}
            ).scalar()
        if kind is None:
            issues.append(ValidationIssue(f"{name}.card", "unknown"))
        elif str(kind) != "method":
            issues.append(ValidationIssue(f"{name}.card", "not-a-method-card"))
    if ref.idea is not None and idea_view(project, resolve_idea(project, ref.idea)) is None:
        issues.append(ValidationIssue(f"{name}.idea", "unknown"))
    if ref.row_key is not None and ref.row_key not in final_keys:
        issues.append(ValidationIssue(f"{name}.row_key", "not-a-final-row"))
    return issues


def _spec_issues(project: Project, spec: HypothesisSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    plan = effective_plan(project)
    if spec.lead is None:
        if plan.require_lead:
            issues.append(ValidationIssue("lead", "a lead is required; promote one first"))
    else:
        lead = lead_view(project, spec.lead)
        if lead is None:
            issues.append(ValidationIssue("lead", "unknown"))
        elif lead.state != "promoted":
            issues.append(ValidationIssue("lead", "lead-not-promoted"))
    refs = (("treatment", spec.treatment), ("baseline", spec.baseline))
    final_keys = (
        {r.row_key for r in final_rows(project)} if any(r.row_key for _, r in refs) else set()
    )
    for name, ref in refs:
        issues.extend(_method_issues(project, name, ref, final_keys))
    if spec.conditions:
        known = _comparability_keys(project)
        issues.extend(
            ValidationIssue(f"conditions.{key}", "not-a-comparability-key")
            for key in sorted(spec.conditions)
            if key not in known
        )
    issues.extend(
        ValidationIssue(f"alternatives.{i}", "unknown")
        for i, other in enumerate(spec.alternatives)
        if not _exists(project, "hypotheses", "hypothesis_id", other)
    )
    return issues


def _supersede_issues(project: Project, supersedes: str) -> list[ValidationIssue]:
    old = hypothesis_view(project, supersedes)
    if old is None:
        return [ValidationIssue("supersedes", "unknown")]
    if old.state == "abandoned":
        return [ValidationIssue("supersedes", "abandoned")]
    if old.superseded_by is not None:
        return [ValidationIssue("supersedes", "already-superseded")]
    if _has_evidence(project, supersedes):
        return [ValidationIssue("supersedes", "evidence-exists")]
    return []


# --- Drafting -----------------------------------------------------------------------------


def draft_hypothesis(
    project: Project, actor: Actor, spec: HypothesisSpec, *, supersedes: str | None = None
) -> tuple[str, str]:
    """Record a hypothesis draft and return `(hyp_ id, H@)`. Refused, with nothing written: an
    actor that is neither an agent nor a human (`actor`); a lead that is missing where the plan
    requires one, unknown or not promoted (`lead`); a method card that is unknown or not a method
    card, an idea that is unknown, a row that is not a final evidence row (`treatment.*`,
    `baseline.*`); a condition key that is not a comparability key of the evidence schema
    (`conditions.<k>`: `not-a-comparability-key`); an unknown alternative; a hypothesis to supersede
    that is unknown, abandoned, already superseded or has evidence (`supersedes`:
    `evidence-exists`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human drafts a hypothesis")
    with project.index.exclusive():
        project.index.sync()
        issues = _spec_issues(project, spec)
        if supersedes is not None:
            issues.extend(_supersede_issues(project, supersedes))
        if issues:
            raise FactoryValidationError(issues)
        hypothesis_id = project.ids.new("hyp")
        version = hypothesis_version(spec)
        payload = HypothesisDrafted(
            hypothesis_id=hypothesis_id, spec=spec, h_version=version, supersedes=supersedes
        )
        input_blob = (
            project.blobs.put_json({"spec": spec.model_dump(mode="json"), "supersedes": supersedes})
            if actor.kind == "agent"
            else None
        )
        refs = [hypothesis_id]
        refs += [r for r in (spec.lead, supersedes) if r is not None]
        project.record(
            [
                project.events.make(
                    "hypothesis.drafted", payload, actor, refs=refs, input_blob=input_blob
                )
            ]
        )
    return hypothesis_id, version


# --- Views --------------------------------------------------------------------------------


def _state(project: Project, row: Any, reviews: list[str], registration: str | None) -> str:
    if row.abandoned_event_id is not None:
        return "abandoned"
    if row.superseded_by is not None:
        return "superseded"
    if has_evaluation(project, str(row.hypothesis_id)):
        return "evaluated"
    if registration is not None:
        return "registered"
    return "reviewed" if reviews else "draft"


def eligible_reviews(project: Project, hypothesis_id: str, h_version: str) -> list[Any]:
    """The reviews of this version by a critic independent of the drafter and the lead author
    (the projector's session test) and, when the plan asks for a distinct critic model, on another
    model than the drafter's. Oldest first."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.*, h.drafter_model FROM hypothesis_reviews r JOIN hypotheses h "
                "ON h.hypothesis_id = r.hypothesis_id WHERE r.hypothesis_id = :h "
                "AND r.h_version = :v AND r.eligible = 1 ORDER BY r.event_id"
            ),
            {"h": hypothesis_id, "v": h_version},
        ).all()
    if not effective_plan(project).critic_distinct_model:
        return list(rows)
    return [r for r in rows if r.critic_model is None or r.critic_model != r.drafter_model]


def _reviews_of(project: Project, hypothesis_id: str, h_version: str) -> list[str]:
    return [str(r.event_id) for r in eligible_reviews(project, hypothesis_id, h_version)]


def _registration_of(project: Project, hypothesis_id: str) -> tuple[str | None, Autonomy | None]:
    """The folded registration event of the hypothesis and its autonomy label."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT event_id, autonomy FROM hypothesis_registrations WHERE hypothesis_id = :h"
            ),
            {"h": hypothesis_id},
        ).first()
    if row is None:
        return None, None
    return str(row[0]), row[1]


def cutoff_flags(project: Project, hypothesis_id: str) -> tuple[str, ...]:
    """The R-53 flags of a literature hypothesis, computed on read over the drafter's model and
    every critic's: `cutoff-unknown` when a model has no declared cut-off, `contaminated` when a
    cut-off is on or after the window start. An experiment hypothesis has none (its evidence is
    generated after registration)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT spec_json, drafter_model FROM hypotheses WHERE hypothesis_id = :h"),
            {"h": hypothesis_id},
        ).first()
        if row is None:
            return ()
        spec = HypothesisSpec.model_validate(json.loads(str(row[0])))
        if not isinstance(spec.test, LiteratureTest):
            return ()
        models = {str(row[1])} if row[1] is not None else set()
        critics = conn.execute(
            text(
                "SELECT DISTINCT critic_model FROM hypothesis_reviews "
                "WHERE hypothesis_id = :h AND critic_model IS NOT NULL"
            ),
            {"h": hypothesis_id},
        ).scalars()
        models.update(str(m) for m in critics)
        cutoffs = {
            str(m): str(c)
            for m, c in conn.execute(text("SELECT model, cutoff FROM model_cutoffs")).all()
        }
    flags: set[str] = set()
    start = spec.test.window_start.isoformat()
    for model in models:
        if model not in cutoffs:
            flags.add("cutoff-unknown")
        elif cutoffs[model] >= start:
            flags.add("contaminated")
    return tuple(sorted(flags))


def _flags_of(project: Project, hypothesis_id: str) -> tuple[str, ...]:
    return cutoff_flags(project, hypothesis_id)


def _view(project: Project, row: Any) -> HypothesisView:
    spec = HypothesisSpec.model_validate(json.loads(str(row.spec_json)))
    hypothesis_id = str(row.hypothesis_id)
    reviews = _reviews_of(project, hypothesis_id, str(row.h_version))
    registration, autonomy = _registration_of(project, hypothesis_id)
    return HypothesisView(
        hypothesis_id=hypothesis_id,
        h_version=str(row.h_version),
        spec=spec,
        falsifier=falsifier_text(spec, confidence=effective_plan(project).confidence),
        state=_state(project, row, reviews, registration),
        reviews=reviews,
        registration=registration,
        flags=_flags_of(project, hypothesis_id),
        autonomy=autonomy,
        event_id=str(row.event_id),
        supersedes=None if row.supersedes is None else str(row.supersedes),
        superseded_by=None if row.superseded_by is None else str(row.superseded_by),
        drafter_session=str(row.drafter_session),
        drafter_model=None if row.drafter_model is None else str(row.drafter_model),
        abandon_reason=None if row.abandon_reason is None else str(row.abandon_reason),
        conclusion=None if row.conclusion_text is None else str(row.conclusion_text),
    )


def hypothesis_view(project: Project, hypothesis_id: str) -> HypothesisView | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM hypotheses WHERE hypothesis_id = :h"), {"h": hypothesis_id}
        ).first()
    return None if row is None else _view(project, row)


def list_hypotheses(
    project: Project, *, states: Collection[str] | None = None
) -> list[HypothesisView]:
    """Hypotheses in id order, optionally only those whose state is in `states`."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT * FROM hypotheses ORDER BY hypothesis_id")).all()
    views = [_view(project, r) for r in rows]
    return views if states is None else [v for v in views if v.state in states]


# --- Prior failures -----------------------------------------------------------------------


def hypothesis_keys(project: Project, view: HypothesisView) -> set[str]:
    """The keys a hypothesis shares with a lead: its lead's keys, the cards, ideas and properties
    of its methods and the evidence rows it names."""
    keys: set[str] = set()
    if view.spec.lead is not None:
        with project.index.connect() as conn:
            rows = conn.execute(
                text("SELECT key FROM lead_keys WHERE lead_id = :l"), {"l": view.spec.lead}
            ).scalars()
            keys.update(str(k) for k in rows)
    for ref in (view.spec.treatment, view.spec.baseline):
        if ref.card is not None:
            keys |= card_keys(project, ref.card)
        if ref.idea is not None:
            keys |= {ref.idea, resolve_idea(project, ref.idea)}
        if ref.row_key is not None:
            keys.add(ref.row_key)
    return keys


def hypothesis_prior(project: Project, keys: Collection[str]) -> list[str]:
    """Every hypothesis, in any state, that shares a key with `keys` (ruling 2)."""
    wanted = set(keys)
    return [
        v.hypothesis_id for v in list_hypotheses(project) if hypothesis_keys(project, v) & wanted
    ]


# --- Human acts ---------------------------------------------------------------------------


def _human_only(actor: Actor) -> None:
    if actor.kind != "human":
        raise _refuse("actor", "human-only")


def abandon_hypothesis(
    project: Project, actor: Actor, hypothesis_id: str, reason: AbandonReason, note: str
) -> str:
    """Abandon a hypothesis (a human act) and return the event id. Refused, with nothing written:
    a non-human actor (`actor`); an unknown or already abandoned hypothesis (`hypothesis_id`); a
    blank or long note (`note`)."""
    _human_only(actor)
    with project.index.exclusive():
        project.index.sync()
        view = hypothesis_view(project, hypothesis_id)
        issues: list[ValidationIssue] = []
        if view is None:
            issues.append(ValidationIssue("hypothesis_id", "unknown"))
        elif view.state == "abandoned":
            issues.append(ValidationIssue("hypothesis_id", "already-abandoned"))
        if not note.strip() or len(note) > 300:
            issues.append(ValidationIssue("note", "between 1 and 300 characters"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "hypothesis.abandoned",
            HypothesisAbandoned(hypothesis_id=hypothesis_id, reason=reason, note=note.strip()),
            actor,
            refs=[hypothesis_id],
        )
        project.record([event])
    return event.id


def conclude_hypothesis(project: Project, actor: Actor, hypothesis_id: str, text_: str) -> str:
    """Record a human conclusion (interpretation text, at most 1,200 characters) on an evaluated
    hypothesis and return the event id. It never changes the outcome. Refused, with nothing
    written: a non-human actor (`actor`); an unknown hypothesis (`hypothesis_id`); one with no
    evaluation (`state`: `not-evaluated`); a blank or long text (`text`)."""
    _human_only(actor)
    with project.index.exclusive():
        project.index.sync()
        view = hypothesis_view(project, hypothesis_id)
        issues: list[ValidationIssue] = []
        if view is None:
            issues.append(ValidationIssue("hypothesis_id", "unknown"))
        elif not has_evaluation(project, hypothesis_id):
            issues.append(ValidationIssue("state", "not-evaluated"))
        if not text_.strip() or len(text_) > 1200:
            issues.append(ValidationIssue("text", "between 1 and 1200 characters"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "hypothesis.concluded",
            HypothesisConcluded(hypothesis_id=hypothesis_id, text=text_.strip()),
            actor,
            refs=[hypothesis_id],
        )
        project.record([event])
    return event.id


# --- Registration and cut-offs -------------------------------------------------------------


def _proposer_sessions(project: Project, view: HypothesisView) -> set[str]:
    sessions = {view.drafter_session}
    lead = None if view.spec.lead is None else lead_view(project, view.spec.lead)
    if lead is not None:
        sessions.add(lead.author_session)
    return sessions


def _replacement_issues(project: Project, old_id: str) -> list[ValidationIssue]:
    """Registering a replacement supersedes the hypothesis it names: that one must still be
    live and must have no evidence (R-52)."""
    old = hypothesis_view(project, old_id)
    if old is None or old.state == "abandoned":
        return [ValidationIssue("supersedes", "abandoned")]
    if old.superseded_by is not None:
        return [ValidationIssue("supersedes", "already-superseded")]
    if _has_evidence(project, old_id):
        return [ValidationIssue("supersedes", "evidence-exists")]
    return []


def register_hypothesis(project: Project, actor: Actor, hypothesis_id: str) -> str:
    """Register a draft (the act at the gate `hypotheses.register`) and return the event id. `H@`
    is then frozen. Refused, with nothing written: an unknown hypothesis or one that is not a
    draft or reviewed (`hypothesis_id`); no eligible review recommending `register` for the
    current version, except under the exploratory mode where the review is optional but, if there
    is one, must not say no (`review`: `review-required`, `not-recommended`); an agent at a `human`
    gate (`actor`); the proposer's session under an `agent` policy (`session`); and, in systematic
    mode, a literature hypothesis flagged `cutoff-unknown` or `contaminated`
    (`test.window_start`)."""
    from factory.model.project import RigorMode

    with project.index.exclusive():
        project.index.sync()
        view = hypothesis_view(project, hypothesis_id)
        if view is None:
            raise _refuse("hypothesis_id", "unknown")
        issues: list[ValidationIssue] = []
        if view.state not in ("draft", "reviewed"):
            issues.append(ValidationIssue("hypothesis_id", f"state-{view.state}"))
        if view.supersedes is not None:
            issues.extend(_replacement_issues(project, view.supersedes))
        reviews = eligible_reviews(project, hypothesis_id, view.h_version)
        mode = project_mode(project)
        review_id: str | None = None
        if reviews:
            if reviews[-1].recommend == "register":
                review_id = str(reviews[-1].event_id)
            else:
                issues.append(ValidationIssue("review", "not-recommended"))
        elif mode is not RigorMode.EXPLORATORY:
            issues.append(ValidationIssue("review", "review-required"))
        flags = cutoff_flags(project, hypothesis_id)
        if mode is RigorMode.SYSTEMATIC:
            issues.extend(ValidationIssue("test.window_start", flag) for flag in flags)
        if issues:
            raise FactoryValidationError(issues)
        verdict = may_pass(
            project,
            actor,
            "hypotheses.register",
            proposer_sessions=_proposer_sessions(project, view),
        )
        verdict.raise_if_refused()
        payload = HypothesisRegistered(
            hypothesis_id=hypothesis_id,
            h_version=view.h_version,
            review_event_id=review_id,
            policy=verdict.policy.kind,
            autonomy=verdict.autonomy,
            flags=flags,
        )
        input_blob = (
            project.blobs.put_json(payload.model_dump(mode="json"))
            if actor.kind == "agent"
            else None
        )
        refs = [hypothesis_id] + ([review_id] if review_id else [])
        event = project.events.make(
            "hypothesis.registered", payload, actor, refs=refs, input_blob=input_blob
        )
        project.record([event])
    return event.id


def declare_cutoff(project: Project, actor: Actor, model: str, cutoff: date, source: str) -> str:
    """Record a model's training cut-off (a human act) and return the event id; the latest
    declaration per model wins. Refused, with nothing written: a non-human actor (`actor`); a blank
    model or source (`model`, `source`)."""
    _human_only(actor)
    issues = [
        ValidationIssue(name, "must not be blank")
        for name, value in (("model", model), ("source", source))
        if not value.strip()
    ]
    if issues:
        raise FactoryValidationError(issues)
    event = project.events.make(
        "model.cutoff_declared",
        ModelCutoffDeclared(model=model.strip(), cutoff=cutoff, source=source.strip()),
        actor,
        refs=[],
    )
    project.record([event])
    return event.id
