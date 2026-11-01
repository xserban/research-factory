"""The raw goal and the versioned question.

`state_goal` appends the goal verbatim; `record_question` checks a spec against the project's
rigor mode and the goal, then records it. Writes happen under the index's exclusive lock, so the
read of the current version and the write that follows cannot interleave with another writer.
A spec identical to the current one writes nothing.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Row

from factory.clock import parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.project import RigorMode
from factory.model.question import (
    GoalStated,
    QuestionRecorded,
    QuestionSpec,
    question_version,
)
from factory.services.context import Project


class QuestionResult(StrictModel):
    """`created` is true when a `question.recorded` event was written, false if unchanged.
    `goal_event_id` is the goal written with it, when a raw goal was given."""

    question_id: str
    created: bool
    goal_event_id: str | None = None


class QuestionVersion(StrictModel):
    question_id: str
    spec: QuestionSpec
    supersedes: str | None
    reason: str | None
    recorded_at: datetime


class Goal(StrictModel):
    text: str
    at: datetime
    actor_id: str


_VERSION_COLUMNS = "question_id, spec, supersedes, reason, at"


def state_goal(project: Project, actor: Actor, text: str) -> str:
    """Record the raw goal exactly as given and return the event id."""
    if not text.strip():
        raise FactoryValidationError(
            [ValidationIssue("text", "must contain a non-whitespace character")]
        )
    payload = GoalStated(text=text)
    # An agent's goal keeps its input, so what the agent was given can be audited later.
    input_blob = project.blobs.put_json({"text": text}) if actor.kind == "agent" else None
    event = project.events.make("question.goal_stated", payload, actor, input_blob=input_blob)
    project.record([event])
    return event.id


def record_question(
    project: Project,
    actor: Actor,
    spec: QuestionSpec,
    *,
    reason: str | None = None,
    raw_goal: str | None = None,
) -> QuestionResult:
    """Record a question version, or its prose, or nothing when the spec is unchanged.

    `raw_goal`, when given, is the goal verbatim and is written with the question, in the same
    write. It counts as the goal the question needs, so a first question may come with its goal.
    Every check runs before anything is written: a refused question writes no goal either.
    """
    if raw_goal is not None and not raw_goal.strip():
        raise FactoryValidationError(
            [ValidationIssue("raw_goal", "must contain a non-whitespace character")]
        )
    with project.index.exclusive():
        project.index.sync()
        if raw_goal is None and _goal_count(project) == 0:
            raise FactoryValidationError(
                [ValidationIssue("raw_goal", "state the goal with question.goal_stated first")]
            )
        issues = _rigor_issues(spec, _rigor_mode(project))
        if issues:
            raise FactoryValidationError(issues)

        current = current_question(project)
        unchanged = current is not None and current.spec == spec
        clean_reason = reason.strip() if reason is not None and reason.strip() else None
        question_id = current.question_id if unchanged and current else question_version(spec)
        supersedes: str | None = None
        if current is not None and not unchanged and question_id != current.question_id:
            if clean_reason is None:
                raise FactoryValidationError(
                    [ValidationIssue("reason", "required when the question's version changes")]
                )
            supersedes = current.question_id

        events: list[Event] = []
        goal_event_id: str | None = None
        if raw_goal is not None:
            goal = _goal_event(project, actor, raw_goal)
            events.append(goal)
            goal_event_id = goal.id
        if not unchanged:
            events.append(
                _question_event(project, actor, spec, question_id, supersedes, clean_reason)
            )
        if events:
            project.record(events)
        return QuestionResult(
            question_id=question_id,
            created=not unchanged,
            goal_event_id=goal_event_id,
        )


def _goal_event(project: Project, actor: Actor, text: str) -> Event:
    payload = GoalStated(text=text)
    # An agent's goal keeps its input, so what the agent was given can be audited later.
    input_blob = project.blobs.put_json({"text": text}) if actor.kind == "agent" else None
    return project.events.make("question.goal_stated", payload, actor, input_blob=input_blob)


def _question_event(
    project: Project,
    actor: Actor,
    spec: QuestionSpec,
    question_id: str,
    supersedes: str | None,
    reason: str | None,
) -> Event:
    payload = QuestionRecorded(
        question_id=question_id,
        supersedes=supersedes,
        reason=reason,
        spec=spec,
    )
    input_blob = (
        project.blobs.put_json({"spec": spec.model_dump(mode="json"), "reason": reason})
        if actor.kind == "agent"
        else None
    )
    return project.events.make("question.recorded", payload, actor, input_blob=input_blob)


def current_question(project: Project) -> QuestionVersion | None:
    """The latest recorded version, by event order."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            sql_text(f"SELECT {_VERSION_COLUMNS} FROM questions ORDER BY event_id DESC LIMIT 1")
        ).one_or_none()
    return None if row is None else _version(row)


def get_question(project: Project, question_id: str) -> QuestionVersion | None:
    """The latest recorded prose of a version, or None if no such version was recorded."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            sql_text(
                f"SELECT {_VERSION_COLUMNS} FROM questions WHERE question_id = :qid "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            {"qid": question_id},
        ).one_or_none()
    return None if row is None else _version(row)


def goals(project: Project) -> list[Goal]:
    """Every stated goal, in event order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            sql_text("SELECT text, at, actor_id FROM goals ORDER BY event_id")
        ).all()
    return [
        Goal(text=str(goal), at=parse_ts(str(at)), actor_id=str(actor_id))
        for goal, at, actor_id in rows
    ]


def _version(row: Row[Any]) -> QuestionVersion:
    question_id, spec, supersedes, reason, at = tuple(row)
    return QuestionVersion(
        question_id=str(question_id),
        spec=QuestionSpec.model_validate_json(str(spec)),
        supersedes=None if supersedes is None else str(supersedes),
        reason=None if reason is None else str(reason),
        recorded_at=parse_ts(str(at)),
    )


def _goal_count(project: Project) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(sql_text("SELECT COUNT(*) FROM goals")).scalar_one())


def _rigor_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        value = conn.execute(
            sql_text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))


def _rigor_issues(spec: QuestionSpec, mode: RigorMode) -> list[ValidationIssue]:
    """Requirements that depend on the rigor mode. Exploratory work asks less."""
    minimum = 1 if mode is RigorMode.EXPLORATORY else 3
    issues: list[ValidationIssue] = []
    if len(spec.non_goals) < minimum:
        issues.append(
            ValidationIssue("non_goals", f"{mode.value} needs at least {minimum} non-goal(s)")
        )
    if mode is RigorMode.EXPLORATORY:
        return issues
    open_slots = sum(1 for slot in spec.slots if slot.open is not None)
    if 2 * open_slots > len(spec.slots):
        issues.append(ValidationIssue("slots", "at most half of the slots may be open"))
    if not spec.rationale.strip():
        issues.append(ValidationIssue("rationale", "must not be empty in pilot or systematic"))
    if not spec.objectives.strip():
        issues.append(ValidationIssue("objectives", "must not be empty in pilot or systematic"))
    return issues
