"""The critic review of a hypothesis: an artefact-only task and engineered independence (slice 6,
plan H-C; rulings 7, 8 and 13; R-51).

Invariants:
- The critic is served the artefact and nothing of its proposer: the spec without prose, the
  statement, the lead's triggers (references, stored builder rows, verified quotes) and the
  computed prior-failure list. The lead's text, the lead's `input_blob` and the drafter's rationale
  are never part of the task, and the review event's `input_blob` is the task content exactly.
- A critic is refused, before anything is served, when its session is the drafter's or the lead
  author's (a subagent shares its session and is refused too), and, when the plan asks for a
  distinct critic model, when its model is the drafter's. The projector re-tests the session rules,
  so a review written by hand by the drafter is kept but never counts.
- Every checklist item is answered; a failing item forces `revise` or `reject`. A review of a
  version that has since been superseded is refused.
- Review tasks are tasks of kind `hyp_review`, one per hypothesis version, served oldest first.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.hypotheses import (
    BUILDER_KINDS,
    CHECKLIST,
    HASHED_FIELDS,
    HypothesisReviewed,
    ReviewInput,
    ReviewTask,
    ReviewTrigger,
)
from factory.model.task import HYPOTHESIS_REVIEW_TASK_KIND, Task, TaskStatus
from factory.services.budgets import require_for, task_unit
from factory.services.context import Project
from factory.services.finders import ref_quote
from factory.services.hypotheses import (
    HypothesisView,
    hypothesis_keys,
    hypothesis_view,
    list_hypotheses,
)
from factory.services.hypothesis_gates import effective_plan
from factory.services.leads import lead_view, prior_for
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    complete_task,
    create_tasks,
    require_holder,
    task_content,
)

_QUOTED = ("claim", "item")


class ServedReview(StrictModel):
    """A review task served to a critic: the task id to answer with, and the task."""

    task_id: str
    task: ReviewTask


def critic_refusal(project: Project, actor: Actor, view: HypothesisView) -> ValidationIssue | None:
    """Why `actor` may not review `view`, or None (see the module invariants)."""
    if actor.kind not in ("agent", "human"):
        return ValidationIssue("actor", "only an agent or a human reviews")
    if actor.session == view.drafter_session:
        return ValidationIssue("actor", "drafter-session")
    lead = None if view.spec.lead is None else lead_view(project, view.spec.lead)
    if lead is not None and actor.session == lead.author_session:
        return ValidationIssue("actor", "lead-author-session")
    if (
        effective_plan(project).critic_distinct_model
        and actor.model is not None
        and actor.model == view.drafter_model
    ):
        return ValidationIssue("actor", "same-model")
    return None


def _spec_without_prose(view: HypothesisView) -> dict[str, Any]:
    dump = view.spec.model_dump(mode="json")
    return {name: dump[name] for name in HASHED_FIELDS}


def _triggers(project: Project, view: HypothesisView) -> list[ReviewTrigger]:
    lead = None if view.spec.lead is None else lead_view(project, view.spec.lead)
    if lead is None:
        return []
    return [
        ReviewTrigger(
            kind=t.kind,
            ref=t.ref,
            row=t.row if t.kind in BUILDER_KINDS else None,
            quote=ref_quote(project, t.ref) if t.kind.value in _QUOTED else None,
        )
        for t in lead.triggers
    ]


def build_review_task(project: Project, view: HypothesisView) -> ReviewTask:
    """The artefact-only content of the review of `view`; the prior is computed now."""
    prior, total = prior_for(project, hypothesis_keys(project, view), exclude=view.hypothesis_id)
    return ReviewTask(
        hypothesis_id=view.hypothesis_id,
        h_version=view.h_version,
        spec_without_prose=_spec_without_prose(view),
        statement=view.spec.statement,
        triggers=_triggers(project, view),
        prior=prior,
        prior_total=total,
        checklist=list(CHECKLIST),
    )


def _task_for(project: Project, hypothesis_id: str, h_version: str) -> str | None:
    """The unfinished review task of this hypothesis version, if one exists."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT task_id, content_blob FROM tasks WHERE kind = :k AND status != :done"),
            {"k": HYPOTHESIS_REVIEW_TASK_KIND, "done": TaskStatus.COMPLETED.value},
        ).all()
    for task_id, blob in rows:
        content = project.blobs.get_json(str(blob))
        if (
            isinstance(content, dict)
            and content.get("hypothesis_id") == hypothesis_id
            and content.get("h_version") == h_version
        ):
            return str(task_id)
    return None


def _held(project: Project, actor: Actor, task_id: str) -> Task | None:
    """The task if this session holds its claim, so a critic resumes without waiting out the
    lease; else None."""
    try:
        return require_holder(project, actor, task_id)
    except FactoryValidationError:
        return None


def review_next(project: Project, actor: Actor) -> ServedReview | None:
    """Serve the oldest draft without an eligible review to `actor`, or None when none is waiting.

    Refused (field `actor`; reasons `drafter-session`, `lead-author-session`, `same-model`) when
    drafts wait and `actor` may review none of them, so an ineligible session is turned away
    before it sees any artefact. A draft whose task another session holds is passed over; one this
    session already holds is served again as it stands, its lease unchanged."""
    with project.index.exclusive():
        project.index.sync()
        waiting = list_hypotheses(project, states=["draft"])
        if waiting:
            require_for(project, actor, task_unit(HYPOTHESIS_REVIEW_TASK_KIND))
        first_refusal: ValidationIssue | None = None
        for view in waiting:
            refusal = critic_refusal(project, actor, view)
            if refusal is not None:
                first_refusal = first_refusal or refusal
                continue
            task_id = _task_for(project, view.hypothesis_id, view.h_version)
            if task_id is None:
                content = build_review_task(project, view).model_dump(mode="json")
                result = create_tasks(
                    project,
                    project.system_actor(),
                    [
                        TaskSpec(
                            kind=HYPOTHESIS_REVIEW_TASK_KIND,
                            content=content,
                            refs=(view.hypothesis_id, view.h_version),
                        )
                    ],
                )
                task_id = result.written[0]
            claimed = claim_next(project, actor, HYPOTHESIS_REVIEW_TASK_KIND, task_ids={task_id})
            claimed = claimed or _held(project, actor, task_id)
            if claimed is None:
                continue
            task = ReviewTask.model_validate(task_content(project, claimed))
            return ServedReview(task_id=claimed.task_id, task=task)
        if first_refusal is not None:
            raise FactoryValidationError([first_refusal])
    return None


def record_review(project: Project, actor: Actor, task_id: str, review: ReviewInput) -> str:
    """Record the critic's review of a served task and return the event id. Refused, with
    nothing written: a task this session does not hold (`task_id`); a task of another kind
    (`task_id`); a version that has been superseded or whose hypothesis is gone (`h_version`:
    `superseded`); an ineligible critic (`actor`); a failing item with the recommendation
    `register` (`recommend`: `inconsistent`)."""
    with project.index.exclusive():
        project.index.sync()
        task = require_holder(project, actor, task_id)
        if task.kind != HYPOTHESIS_REVIEW_TASK_KIND:
            raise FactoryValidationError([ValidationIssue("task_id", "not a review task")])
        served = ReviewTask.model_validate(task_content(project, task))
        view = hypothesis_view(project, served.hypothesis_id)
        if (
            view is None
            or view.h_version != served.h_version
            or view.state not in ("draft", "reviewed")
        ):
            raise FactoryValidationError([ValidationIssue("h_version", "superseded")])
        issues: list[ValidationIssue] = []
        refusal = critic_refusal(project, actor, view)
        if refusal is not None:
            issues.append(refusal)
        if review.recommend == "register" and "fail" in review.items.values():
            issues.append(ValidationIssue("recommend", "inconsistent"))
        if issues:
            raise FactoryValidationError(issues)
        payload = HypothesisReviewed(
            hypothesis_id=view.hypothesis_id,
            h_version=view.h_version,
            items=review.items,
            notes=review.notes,
            recommend=review.recommend,
            critic_session=actor.session,
            critic_model=actor.model,
            task_id=task_id,
        )
        event = project.events.make(
            "hypothesis.reviewed",
            payload,
            actor,
            refs=[view.hypothesis_id, task_id],
            input_blob=task.content_blob,
        )
        project.record([event])
        complete_task(project, actor, task_id, result_refs=[event.id])
    return event.id
