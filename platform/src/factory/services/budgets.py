"""Declared budgets and computed consumption (slice 5 ruling 17; plan teams-D rulings 4 to 6).

Invariants:
- Consumption is counted from the log, never typed (R-05). Weeks are ISO weeks in UTC.
- A budget binds the user it names; a project budget binds everyone together. `remaining` is the
  least of those, `tasks:*` included for any task unit, and None when nothing binds.
- Only `project:govern` sets a budget, through `access.authorize`: an agent never holds it.
- `require_budget` writes nothing. Callers ask before their first write, under the lock that
  covers the claim when there is one, so two sessions cannot both take the last task.
- Reported usage is read for display only.
- `budget-exhausted` here and `compute-budget-*` in slice 6 are different things (decision 75).
"""

from datetime import UTC, datetime, timedelta

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.budgets import BUDGET_TABLES, consumed, live_budgets, reported_totals
from factory.model.budgets import (
    ALL_TASKS,
    TASKS_PREFIX,
    Budget,
    BudgetLine,
    BudgetSet,
    BudgetStatus,
    Period,
)
from factory.services.access import Permission, authorize
from factory.services.context import Principal, Project
from factory.services.lab import lab_exists, open_lab, payload_of, refuse, user_record
from factory.services.modules.task_kinds import default_task_kinds

EMPTY_NOTICE = "no budget is declared and no usage has been reported on this project"
_KNOWN_KINDS = "unit names no task kind of this platform"


def task_unit(kind: str) -> str:
    return f"{TASKS_PREFIX}{kind}"


def actor_principal(project: Project, actor: Actor) -> Principal:
    """The principal an actor acts for, who is charged."""
    return Principal(actor.user, actor.credential, project.principal.channel)


def set_budget(
    project: Project, actor: Actor, *, user: str | None, unit: str, limit: int, period: Period
) -> str:
    """Declare a budget and return its id. It supersedes the budget of the same scope and unit.

    Refused, with nothing written: without `project:govern`; for a unit or limit out of range; for
    a task kind the platform does not have; and for a person the lab does not hold as active."""
    budget_id = project.ids.new("bdg")
    payload = payload_of(
        BudgetSet, budget_id=budget_id, scope_user=user, unit=unit, limit=limit, period=period
    )
    if unit.startswith(TASKS_PREFIX) and unit != ALL_TASKS:
        kind = unit.removeprefix(TASKS_PREFIX)
        if default_task_kinds().describe(kind) is None:
            raise refuse("unit", _KNOWN_KINDS)
    lab = (
        open_lab(project.settings, session=project.session, clock=project.clock)
        if lab_exists(project.settings)
        else None
    )
    with project.writing():
        principal = actor_principal(project, actor)
        authorize(project, principal, actor.kind, Permission.PROJECT_GOVERN, lab=lab)
        if lab is not None and user is not None:
            record = user_record(lab, user)
            if record is None or not record.active:
                raise refuse("scope_user", f"no active user {user!r} in the lab registry")
        project.record([project.events.make("budget.set", payload, actor)])
    return budget_id


def budgets(project: Project) -> list[Budget]:
    """The budgets in force."""
    project.index.sync()
    with project.index.connect() as conn:
        return live_budgets(conn, BUDGET_TABLES)


def _window(period: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    """The period holding `now`: all time, or its ISO week in UTC, Monday 00:00 included."""
    if period == "total":
        return None, None
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=7)


def consumption(
    project: Project, *, user: str | None, unit: str, period: str, now: datetime
) -> int:
    """How much of `unit` was consumed in the period holding `now`, by `user` or by everyone."""
    since, until = _window(period, now)
    project.index.sync()
    with project.index.connect() as conn:
        return consumed(conn, BUDGET_TABLES, user=user, unit=unit, since=since, until=until)


def _used(project: Project, budget: Budget, now: datetime) -> int:
    return consumption(
        project, user=budget.scope_user, unit=budget.unit, period=budget.period, now=now
    )


def _binding(project: Project, user: str, unit: str) -> list[Budget]:
    units = {unit, ALL_TASKS} if unit.startswith(TASKS_PREFIX) else {unit}
    return [
        budget
        for budget in budgets(project)
        if budget.unit in units and budget.scope_user in (None, user)
    ]


def _tightest(project: Project, user: str, unit: str, now: datetime) -> tuple[int, str] | None:
    """What is left of the tightest budget binding `user` on `unit`, and that budget's unit."""
    left = [
        (max(b.limit - _used(project, b, now), 0), b.unit) for b in _binding(project, user, unit)
    ]
    return min(left, default=None)


def remaining(project: Project, user: str, unit: str, now: datetime) -> int | None:
    """How much of `unit` the user may still consume; None when no budget binds them."""
    tightest = _tightest(project, user, unit, now)
    return None if tightest is None else tightest[0]


def exhausted_unit(project: Project, principal: Principal, unit: str) -> str | None:
    """The unit of the budget that stops `principal` consuming `unit`, if one does."""
    tightest = _tightest(project, principal.user, unit, project.clock.now())
    if tightest is None or tightest[0] > 0:
        return None
    return tightest[1]


def budget_issue(unit: str) -> ValidationIssue:
    return ValidationIssue("budget", f"budget-exhausted: {unit}")


def require_budget(project: Project, principal: Principal, unit: str) -> None:
    """Refuse, writing nothing, when a budget binding `principal` on `unit` is spent."""
    spent = exhausted_unit(project, principal, unit)
    if spent is not None:
        raise FactoryValidationError([budget_issue(spent)])


def budget_status(project: Project) -> BudgetStatus:
    """Every budget in force with its computed consumption, and the usage agents reported, shown as
    reported and never enforced. Empty, with a notice, on a fresh project."""
    now = project.clock.now()
    lines = []
    for budget in budgets(project):
        used = _used(project, budget, now)
        left = max(budget.limit - used, 0)
        lines.append(BudgetLine(budget=budget, consumed=used, remaining=left))
    with project.index.connect() as conn:
        usage = reported_totals(conn, BUDGET_TABLES)
    notice = EMPTY_NOTICE if not lines and not usage else None
    return BudgetStatus(budgets=lines, reported_usage=usage, notice=notice)
