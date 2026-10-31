import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.clock import format_ts, parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.task import (
    TASK_KIND_RE,
    TASK_LEASE,
    Task,
    TaskClaimed,
    TaskCompleted,
    TaskCreated,
    TaskReleased,
    TaskStatus,
)
from factory.services.context import Project
from factory.services.results import BatchResult, ItemError

_TASK_COLUMNS = (
    "task_id, kind, status, content_blob, refs, created_at, claimed_by, claim_session, lease_until"
)


@dataclass(frozen=True)
class TaskSpec:
    kind: str
    content: JsonValue
    refs: tuple[str, ...] = ()


class TaskCounts(StrictModel):
    """Open tasks; claims whose lease is live or has lapsed; completed tasks."""

    open: int
    claimed: int
    expired: int
    completed: int


def create_tasks(project: Project, actor: Actor, specs: Sequence[TaskSpec]) -> BatchResult[str]:
    """Write every valid spec in one append. Returns the new task IDs in input order."""
    rejected: list[ItemError] = []
    events = []
    task_ids: list[str] = []
    for index, spec in enumerate(specs):
        issues = _spec_issues(spec)
        if issues:
            rejected.append(ItemError(index=index, issues=issues))
            continue
        task_id = project.ids.new("tsk")
        blob = project.blobs.put_json(spec.content)
        events.append(
            project.events.make(
                "task.created",
                TaskCreated(task_id=task_id, kind=spec.kind),
                actor,
                refs=spec.refs,
                input_blob=blob,
            )
        )
        task_ids.append(task_id)
    if events:
        project.record(events)
    return BatchResult[str](written=task_ids, rejected=rejected)


def claim_next(
    project: Project, actor: Actor, kind: str, lease: timedelta = TASK_LEASE
) -> Task | None:
    """Claim the lowest-ID claimable task of `kind`, or return None when none can be claimed."""
    project.index.sync()
    now = _now(project)
    for task_id, content_blob in _claimable(project, kind, now):
        project.record(
            [
                project.events.make(
                    "task.claimed",
                    TaskClaimed(task_id=task_id, lease_until=now + lease),
                    actor,
                    refs=(task_id,),
                    input_blob=content_blob,
                )
            ]
        )
        # Another session may have claimed it first; the projection decides who holds it.
        claimed = get_task(project, task_id)
        if claimed is not None and claimed.claim_session == actor.session:
            return claimed
    return None


def complete_task(
    project: Project, actor: Actor, task_id: str, result_refs: Sequence[str] = ()
) -> None:
    refs = tuple(result_refs)
    if any(not ref for ref in refs):
        raise FactoryValidationError([ValidationIssue("result_refs", "must be non-empty strings")])
    task = _require_holder(project, actor, task_id)
    project.record(
        [
            project.events.make(
                "task.completed",
                TaskCompleted(task_id=task_id, result_refs=refs),
                actor,
                refs=(task_id,),
                input_blob=task.content_blob,
            )
        ]
    )


def release_task(project: Project, actor: Actor, task_id: str, reason: str) -> None:
    task = _require_holder(project, actor, task_id)
    project.record(
        [
            project.events.make(
                "task.released",
                TaskReleased(task_id=task_id, reason=reason),
                actor,
                refs=(task_id,),
                input_blob=task.content_blob,
            )
        ]
    )


def get_task(project: Project, task_id: str) -> Task | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = (
            conn.execute(
                text(f"SELECT {_TASK_COLUMNS} FROM tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    lease = row["lease_until"]
    return Task(
        task_id=str(row["task_id"]),
        kind=str(row["kind"]),
        status=TaskStatus(row["status"]),
        content_blob=str(row["content_blob"]),
        refs=tuple(json.loads(row["refs"])),
        created_at=parse_ts(str(row["created_at"])),
        claimed_by=_opt_str(row["claimed_by"]),
        claim_session=_opt_str(row["claim_session"]),
        lease_until=parse_ts(str(lease)) if lease is not None else None,
    )


def task_content(project: Project, task: Task) -> JsonValue:
    return project.blobs.get_json(task.content_blob)


def task_counts(project: Project) -> TaskCounts:
    project.index.sync()
    now = _now(project)
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT status, lease_until FROM tasks")).all()
    counts = {"open": 0, "claimed": 0, "expired": 0, "completed": 0}
    for status, lease_until in rows:
        if status == TaskStatus.OPEN.value:
            counts["open"] += 1
        elif status == TaskStatus.COMPLETED.value:
            counts["completed"] += 1
        elif parse_ts(str(lease_until)) <= now:
            counts["expired"] += 1
        else:
            counts["claimed"] += 1
    return TaskCounts(**counts)


def _now(project: Project) -> datetime:
    """The clock truncated to milliseconds: the timestamp an event written now will carry."""
    now = project.clock.now()
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def _spec_issues(spec: TaskSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if re.fullmatch(TASK_KIND_RE, spec.kind) is None:
        issues.append(ValidationIssue("kind", "must be lowercase words joined by underscores"))
    try:
        canonical_json(spec.content)
    except (TypeError, ValueError):
        issues.append(ValidationIssue("content", "must be JSON-serialisable"))
    if any(not ref for ref in spec.refs):
        issues.append(ValidationIssue("refs", "must be non-empty strings"))
    return issues


def _claimable(project: Project, kind: str, now: datetime) -> list[tuple[str, str]]:
    """Open tasks of `kind`, plus claims whose lease has lapsed, in task-ID order.

    Timestamps share one fixed-width text form, so comparing the text is chronological.
    """
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id, content_blob FROM tasks "
                "WHERE kind = :kind AND (status = :open "
                "OR (status = :claimed AND lease_until <= :now)) ORDER BY task_id"
            ),
            {
                "kind": kind,
                "open": TaskStatus.OPEN.value,
                "claimed": TaskStatus.CLAIMED.value,
                "now": format_ts(now),
            },
        ).all()
    return [(str(task_id), str(blob)) for task_id, blob in rows]


def _require_holder(project: Project, actor: Actor, task_id: str) -> Task:
    """The task, if this session holds a live claim on it; otherwise a validation error."""
    task = get_task(project, task_id)
    if task is None:
        raise FactoryValidationError([ValidationIssue("task_id", "unknown task")])
    now = _now(project)
    held = (
        task.status == TaskStatus.CLAIMED
        and task.claim_session == actor.session
        and task.lease_until is not None
        and task.lease_until > now
    )
    if not held:
        raise FactoryValidationError(
            [ValidationIssue("task_id", "not actively claimed by this session")]
        )
    return task


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
