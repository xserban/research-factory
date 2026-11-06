"""Budgets and what they are measured against (slice 5 ruling 17; plan teams-D rulings 4 and 5).

`budgets` holds every budget that folded, each marked when superseded. `task_claims`,
`source_requests` and `request_starts` are lookups over the log, indexed so that consumption is one
count. `task_usage` holds what agents reported on completing a task.

Invariants:
- Handlers are total: a malformed payload, or an event that fails a guard, changes nothing, on
  rebuild too.
- Only an owner, in their own name, sets a budget (`governs`). A repeated `budget_id` is ignored.
- A claim is charged only when it takes the task, by the rule of `index/tasks.py`, so a claim that
  lost a race or was written by hand on a held task costs nobody anything. The handler runs before
  the task's own, since it asks what the task's state was.
- A task claim is charged to the claiming event's user. A source request is charged to the user of
  the run's or the fetch's starting event; a probe has no such event, so to its page's own user.
- A page is charged once per `(run, ordinal)`, as the page table counts it, and only for a known
  run. An attempt is charged once per `attempt_id`. A researcher-supplied attempt requested nothing.
- Usage is kept only for a completion that counts, and is never read by enforcement.
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.ledger import governs
from factory.index.members import MemberTables
from factory.index.projection import Handler
from factory.index.search import SearchTables
from factory.index.tasks import claim_takes, completion_counts
from factory.model.budgets import (
    ALL_TASKS,
    REQUESTS_FULLTEXT,
    REQUESTS_SEARCH,
    TASKS_PREFIX,
    Budget,
    BudgetSet,
)
from factory.model.fulltext import Attempted, FetchStarted, Route
from factory.model.probe import ProbePageArchived
from factory.model.search import SearchPageArchived, SearchRunStarted
from factory.model.task import TaskClaimed, TaskCompleted

SEARCH_KIND = "search"
FULLTEXT_KIND = "fulltext"


@dataclass(frozen=True)
class BudgetTables:
    budgets: Table
    task_claims: Table
    source_requests: Table
    request_starts: Table
    task_usage: Table


def budget_tables(metadata: MetaData) -> BudgetTables:
    budgets = Table(
        "budgets",
        metadata,
        Column("budget_id", String, primary_key=True),
        Column("scope_user", String),
        Column("unit", String, nullable=False),
        Column("limit_value", Integer, nullable=False),
        Column("period", String, nullable=False),
        Column("event_id", String, nullable=False),
        Column("superseded_by", String),
    )
    claims = Table(
        "task_claims",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("user", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("ts", String, nullable=False),
    )
    requests = Table(
        "source_requests",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("request_key", String, nullable=False, unique=True),
        Column("user", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("ts", String, nullable=False),
    )
    Index("ix_task_claims_user_kind_ts", claims.c.user, claims.c.kind, claims.c.ts)
    Index("ix_task_claims_kind_ts", claims.c.kind, claims.c.ts)
    Index("ix_task_claims_ts", claims.c.ts)
    Index("ix_source_requests_user_kind_ts", requests.c.user, requests.c.kind, requests.c.ts)
    Index("ix_source_requests_kind_ts", requests.c.kind, requests.c.ts)
    return BudgetTables(
        budgets=budgets,
        task_claims=claims,
        source_requests=requests,
        request_starts=Table(
            "request_starts",
            metadata,
            Column("start_id", String, primary_key=True),
            Column("user", String, nullable=False),
        ),
        task_usage=Table(
            "task_usage",
            metadata,
            Column("event_id", String, primary_key=True),
            Column("task_id", String, nullable=False),
            Column("user", String, nullable=False),
            Column("input_tokens", Float),
            Column("output_tokens", Float),
            Column("cost_usd", Float),
        ),
    )


BUDGET_TABLES = budget_tables(MetaData())
"""A handle for the services' reads, as the projection's tables are built per index."""


def live_budgets(conn: Connection, tables: BudgetTables) -> list[Budget]:
    """The budgets in force, the project's first, then by user and unit."""
    t = tables.budgets
    rows = conn.execute(
        select(t.c.budget_id, t.c.scope_user, t.c.unit, t.c.limit_value, t.c.period)
        .where(t.c.superseded_by.is_(None))
        .order_by(t.c.scope_user, t.c.unit)
    )
    return [
        Budget(budget_id=r[0], scope_user=r[1], unit=r[2], limit=r[3], period=r[4]) for r in rows
    ]


def consumed(
    conn: Connection,
    tables: BudgetTables,
    *,
    user: str | None,
    unit: str,
    since: datetime | None,
    until: datetime | None,
) -> int:
    """How much of `unit` was used in `[since, until)`, by `user` or, when None, by everyone."""
    is_task = unit.startswith(TASKS_PREFIX)
    table = tables.task_claims if is_task else tables.source_requests
    query = select(func.count()).select_from(table)
    if unit == REQUESTS_SEARCH:
        query = query.where(table.c.kind == SEARCH_KIND)
    elif unit == REQUESTS_FULLTEXT:
        query = query.where(table.c.kind == FULLTEXT_KIND)
    elif unit != ALL_TASKS:
        query = query.where(table.c.kind == unit.removeprefix(TASKS_PREFIX))
    if user is not None:
        query = query.where(table.c.user == user)
    if since is not None:
        query = query.where(table.c.ts >= format_ts(since))
    if until is not None:
        query = query.where(table.c.ts < format_ts(until))
    return int(conn.execute(query).scalar_one())


def reported_totals(conn: Connection, tables: BudgetTables) -> dict[str, float]:
    """The sums of what agents reported, leaving out what no one reported."""
    t = tables.task_usage
    row = conn.execute(
        select(func.sum(t.c.input_tokens), func.sum(t.c.output_tokens), func.sum(t.c.cost_usd))
    ).one()
    names = ("input_tokens", "output_tokens", "cost_usd")
    return {name: float(value) for name, value in zip(names, row, strict=True) if value is not None}


def _budget_set(tables: BudgetTables, members: MemberTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = BudgetSet.model_validate(event.payload)
        except ValidationError:
            return
        if not governs(conn, members, event.actor):
            return
        t = tables.budgets
        known = select(t.c.budget_id).where(t.c.budget_id == payload.budget_id)
        if conn.execute(known).first() is not None:
            return
        scope = (
            t.c.scope_user.is_(None)
            if payload.scope_user is None
            else t.c.scope_user == payload.scope_user
        )
        conn.execute(
            update(t)
            .where(scope, t.c.unit == payload.unit, t.c.superseded_by.is_(None))
            .values(superseded_by=payload.budget_id)
        )
        conn.execute(
            insert(t).values(
                budget_id=payload.budget_id,
                scope_user=payload.scope_user,
                unit=payload.unit,
                limit_value=payload.limit,
                period=payload.period,
                event_id=event.id,
                superseded_by=None,
            )
        )

    return fold


def _claimed(tables: BudgetTables, tasks: Table) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = TaskClaimed.model_validate(event.payload)
        except ValidationError:
            return
        kind = claim_takes(conn, tasks, payload.task_id, event)
        if kind is not None:
            conn.execute(
                insert(tables.task_claims).values(
                    event_id=event.id, user=event.actor.user, kind=kind, ts=format_ts(event.ts)
                )
            )

    return fold


def _completed(tables: BudgetTables, tasks: Table) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = TaskCompleted.model_validate(event.payload)
        except ValidationError:
            return
        usage = payload.reported_usage
        if usage is None or not completion_counts(conn, tasks, payload.task_id, event):
            return
        conn.execute(
            insert(tables.task_usage).values(
                event_id=event.id,
                task_id=payload.task_id,
                user=event.actor.user,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cost_usd=usage.get("cost_usd"),
            )
        )

    return fold


def _started(tables: BudgetTables, start_id: str, user: str, conn: Connection) -> None:
    conn.execute(
        sqlite_insert(tables.request_starts)
        .values(start_id=start_id, user=user)
        .on_conflict_do_nothing(index_elements=["start_id"])
    )


def _starter(conn: Connection, tables: BudgetTables, start_id: str) -> str | None:
    t = tables.request_starts
    found = conn.execute(select(t.c.user).where(t.c.start_id == start_id)).scalar_one_or_none()
    return None if found is None else str(found)


def _charge(
    conn: Connection, tables: BudgetTables, event: Event, key: str, user: str, kind: str
) -> None:
    conn.execute(
        sqlite_insert(tables.source_requests)
        .values(event_id=event.id, request_key=key, user=user, kind=kind, ts=format_ts(event.ts))
        .on_conflict_do_nothing(index_elements=["request_key"])
    )


def _run_started(tables: BudgetTables, search: SearchTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = SearchRunStarted.model_validate(event.payload)
        except ValidationError:
            return
        runs = search.runs
        known = select(runs.c.run_id).where(runs.c.run_id == payload.run_id)
        if conn.execute(known).first() is not None:
            _started(tables, payload.run_id, event.actor.user, conn)

    return fold


def _page(tables: BudgetTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = SearchPageArchived.model_validate(event.payload)
        except ValidationError:
            return
        user = _starter(conn, tables, payload.run_id)
        if user is not None:
            key = f"{payload.run_id}:{payload.ordinal}"
            _charge(conn, tables, event, key, user, SEARCH_KIND)

    return fold


def _probe_page(tables: BudgetTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = ProbePageArchived.model_validate(event.payload)
        except ValidationError:
            return
        key = f"{payload.probe_id}:{payload.query_id}:{payload.role}:{payload.ordinal}"
        _charge(conn, tables, event, key, event.actor.user, SEARCH_KIND)

    return fold


def _fetch_started(tables: BudgetTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = FetchStarted.model_validate(event.payload)
        except ValidationError:
            return
        _started(tables, payload.fetch_id, event.actor.user, conn)

    return fold


def _attempted(tables: BudgetTables) -> Handler:
    def fold(conn: Connection, event: Event) -> None:
        try:
            payload = Attempted.model_validate(event.payload)
        except ValidationError:
            return
        if payload.route in (Route.RESEARCHER, Route.LAB_LIBRARY):
            return  # no request reached a source
        started = None if payload.fetch_id is None else _starter(conn, tables, payload.fetch_id)
        user = event.actor.user if started is None else started
        _charge(conn, tables, event, payload.attempt_id, user, FULLTEXT_KIND)

    return fold


def budget_handlers(tables: BudgetTables, members: MemberTables) -> dict[str, Handler]:
    return {"budget.set": _budget_set(tables, members)}


def consumption_before(tables: BudgetTables, tasks: Table) -> dict[str, Handler]:
    """Handlers that run before the event's own: they ask the state the event finds."""
    return {"task.claimed": _claimed(tables, tasks), "task.completed": _completed(tables, tasks)}


def consumption_after(tables: BudgetTables, search: SearchTables) -> dict[str, Handler]:
    """Handlers that run after the event's own: a run counts only once its fold has taken it."""
    return {
        "search.run_started": _run_started(tables, search),
        "search.page_archived": _page(tables),
        "probe.page_archived": _probe_page(tables),
        "fulltext.fetch_started": _fetch_started(tables),
        "fulltext.attempted": _attempted(tables),
    }
