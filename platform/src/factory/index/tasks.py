from typing import Any

from pydantic import JsonValue, ValidationError
from sqlalchemy import Column, MetaData, String, Table, insert, select, update
from sqlalchemy.engine import Connection, Row

from factory.canonical import canonical_json
from factory.clock import format_ts, parse_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.task import TaskClaimed, TaskCompleted, TaskCreated, TaskReleased, TaskStatus

# Projector rules use only event data (event.ts), never the wall clock. Handlers are total:
# an event that does not apply is ignored and leaves the row unchanged.


def tasks_table(metadata: MetaData) -> Table:
    return Table(
        "tasks",
        metadata,
        Column("task_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        Column("status", String, nullable=False),
        Column("content_blob", String, nullable=False),
        Column("refs", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("claimed_by", String),
        Column("claim_session", String),
        Column("lease_until", String),
    )


def task_handlers(table: Table) -> dict[str, Handler]:
    return {
        "task.created": _task_created(table),
        "task.claimed": _task_claimed(table),
        "task.completed": _task_completed(table),
        "task.released": _task_released(table),
    }


_Current = Row[Any, Any, Any]


def _current(conn: Connection, table: Table, task_id: str) -> _Current | None:
    return conn.execute(
        select(table.c.status, table.c.claim_session, table.c.lease_until).where(
            table.c.task_id == task_id
        )
    ).one_or_none()


def _held_by_actor(row: _Current, event: Event) -> bool:
    return (
        row.status == TaskStatus.CLAIMED.value
        and row.claim_session == event.actor.session
        and row.lease_until is not None
        and event.ts < parse_ts(row.lease_until)
    )


def _takes(row: _Current, event: Event) -> bool:
    """Whether a claim takes the task: it is open, or held on a lease this claim outlasts."""
    expired = (
        row.status == TaskStatus.CLAIMED.value
        and row.lease_until is not None
        and parse_ts(row.lease_until) <= event.ts
    )
    return row.status == TaskStatus.OPEN.value or expired


def claim_takes(conn: Connection, table: Table, task_id: str, event: Event) -> str | None:
    """The kind of the task a `task.claimed` about to fold takes, or None when it takes nothing."""
    row = _current(conn, table, task_id)
    if row is None or not _takes(row, event):
        return None
    return str(conn.execute(select(table.c.kind).where(table.c.task_id == task_id)).scalar_one())


def completion_counts(conn: Connection, table: Table, task_id: str, event: Event) -> bool:
    """Whether a `task.completed` about to fold completes the task."""
    row = _current(conn, table, task_id)
    return row is not None and _held_by_actor(row, event)


def _task_created(table: Table) -> Handler:
    def task_created(conn: Connection, event: Event) -> None:
        try:
            payload = TaskCreated.model_validate(event.payload)
        except ValidationError:
            return
        # A task's content is the event's input blob; without one the event does not create a task.
        if event.input_blob is None or _current(conn, table, payload.task_id) is not None:
            return
        refs: list[JsonValue] = [*event.refs]
        conn.execute(
            insert(table).values(
                task_id=payload.task_id,
                kind=payload.kind,
                status=TaskStatus.OPEN.value,
                content_blob=event.input_blob,
                refs=canonical_json(refs).decode(),
                created_at=format_ts(event.ts),
                claimed_by=None,
                claim_session=None,
                lease_until=None,
            )
        )

    return task_created


def _task_claimed(table: Table) -> Handler:
    def task_claimed(conn: Connection, event: Event) -> None:
        try:
            payload = TaskClaimed.model_validate(event.payload)
        except ValidationError:
            return
        row = _current(conn, table, payload.task_id)
        if row is None or not _takes(row, event):
            return
        conn.execute(
            update(table)
            .where(table.c.task_id == payload.task_id)
            .values(
                status=TaskStatus.CLAIMED.value,
                claimed_by=event.actor.id,
                claim_session=event.actor.session,
                lease_until=format_ts(payload.lease_until),
            )
        )

    return task_claimed


def _task_completed(table: Table) -> Handler:
    def task_completed(conn: Connection, event: Event) -> None:
        try:
            payload = TaskCompleted.model_validate(event.payload)
        except ValidationError:
            return
        row = _current(conn, table, payload.task_id)
        if row is None or not _held_by_actor(row, event):
            return
        conn.execute(
            update(table)
            .where(table.c.task_id == payload.task_id)
            .values(status=TaskStatus.COMPLETED.value)
        )

    return task_completed


def _task_released(table: Table) -> Handler:
    def task_released(conn: Connection, event: Event) -> None:
        try:
            payload = TaskReleased.model_validate(event.payload)
        except ValidationError:
            return
        row = _current(conn, table, payload.task_id)
        if row is None or not _held_by_actor(row, event):
            return
        conn.execute(
            update(table)
            .where(table.c.task_id == payload.task_id)
            .values(
                status=TaskStatus.OPEN.value,
                claimed_by=None,
                claim_session=None,
                lease_until=None,
            )
        )

    return task_released
