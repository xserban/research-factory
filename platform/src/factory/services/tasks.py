import json
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.clock import format_ts, parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.task import (
    INTUITION_TASK_KIND,
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
    """Open tasks; claims whose lease is live or has lapsed; completed tasks; and abandoned
    tasks (open or claimed extraction tasks a newer task of their unit replaced), counted in
    none of the other open/claimed/expired figures."""

    open: int
    claimed: int
    expired: int
    completed: int
    abandoned: int = 0


def create_tasks(project: Project, actor: Actor, specs: Sequence[TaskSpec]) -> BatchResult[str]:
    """Write every valid spec in one append. Returns the new task IDs in input order."""
    events, result = build_task_events(project, actor, specs)
    if events:
        project.record(events)
    return result


def build_task_events(
    project: Project, actor: Actor, specs: Sequence[TaskSpec]
) -> tuple[list[Event], BatchResult[str]]:
    """The `task.created` events of the valid specs, not yet recorded, with the outcome that
    recording them yields. A caller that must write other events with them records both at once."""
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
    return events, BatchResult[str](written=task_ids, rejected=rejected)


def claim_next(
    project: Project,
    actor: Actor,
    kind: str,
    lease: timedelta = TASK_LEASE,
    *,
    accept: Callable[[JsonValue], bool] | None = None,
    task_ids: Collection[str] | None = None,
) -> Task | None:
    """Claim the lowest-ID claimable task of `kind`, or return None when none can be claimed.

    `accept`, when given, sees each candidate's content and may pass over it; `task_ids`, when
    given, limits the candidates to those tasks. A passed-over task stays open and nothing is
    written for it."""
    project.index.sync()
    now = _now(project)
    for task_id, content_blob in _claimable(project, kind, now):
        if task_ids is not None and task_id not in task_ids:
            continue
        if accept is not None and not accept(project.blobs.get_json(content_blob)):
            continue
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
    task = require_holder(project, actor, task_id)
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
    _require_outcome(project, task_id, TaskStatus.COMPLETED)


def release_task(project: Project, actor: Actor, task_id: str, reason: str) -> None:
    task = require_holder(project, actor, task_id)
    lease_until = task.lease_until
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
    # Ignored only if this session still holds the same claim: a release applied and then
    # reclaimed by another session is a success.
    current = get_task(project, task_id)
    if (
        current is not None
        and current.status == TaskStatus.CLAIMED
        and current.claim_session == actor.session
        and current.lease_until == lease_until
    ):
        raise FactoryValidationError(
            [ValidationIssue("task_id", "lease expired before the event was recorded")]
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
    """Counts of every task by status, the intuition layer's tasks left out (they are not part of
    the work the project counts). Extraction tasks that a newer task of their unit
    replaced stay open in the log but are never served again: they are counted as `abandoned`,
    not as open, claimed or expired."""
    from factory.services.extraction import abandoned_task_ids  # extraction imports this module

    project.index.sync()
    now = _now(project)
    abandoned = abandoned_task_ids(project)
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT task_id, status, lease_until FROM tasks WHERE kind != :layer"),
            {"layer": INTUITION_TASK_KIND},
        ).all()
    counts = {"open": 0, "claimed": 0, "expired": 0, "completed": 0, "abandoned": 0}
    for task_id, status, lease_until in rows:
        if task_id in abandoned:
            counts["abandoned"] += 1
        elif status == TaskStatus.OPEN.value:
            counts["open"] += 1
        elif status == TaskStatus.COMPLETED.value:
            counts["completed"] += 1
        elif parse_ts(str(lease_until)) <= now:
            counts["expired"] += 1
        else:
            counts["claimed"] += 1
    return TaskCounts(**counts)


def session_in_layer(project: Project, session: str) -> bool:
    """Whether `session` worked for the intuition layer: it claimed an intuition task, or wrote a
    `concept.defined` or `concept.link_proposed` event (the concept tools claim no task). One
    query over `events` by type and session; a session that did so cannot join a pass."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM events e WHERE e.session = :s AND (e.type IN "
                "('concept.defined', 'concept.link_proposed') OR (e.type = 'task.claimed' AND "
                "e.input_blob IN (SELECT content_blob FROM tasks WHERE kind = :k))) LIMIT 1"
            ),
            {"s": session, "k": INTUITION_TASK_KIND},
        ).first()
    return row is not None


def session_served_kind(project: Project, session: str, kind: str) -> bool:
    """Whether `session` ever claimed a task of `kind` (read from the claim events and the task's
    kind, so it survives the task's completion)."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM events e JOIN tasks t ON t.content_blob = e.input_blob "
                "WHERE e.type = 'task.claimed' AND e.session = :s AND t.kind = :k LIMIT 1"
            ),
            {"s": session, "k": kind},
        ).first()
    return row is not None


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


def require_holder(project: Project, actor: Actor, task_id: str) -> Task:
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


def _require_outcome(project: Project, task_id: str, expected: TaskStatus) -> None:
    """The projector re-checks the lease at the event's own timestamp; surface a disagreement.

    The event stays in the log (append-only); the projector ignored it.
    """
    task = get_task(project, task_id)
    if task is None or task.status != expected:
        raise FactoryValidationError(
            [ValidationIssue("task_id", "lease expired before the event was recorded")]
        )


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
