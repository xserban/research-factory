"""Declared budgets (slice 5 ruling 17; plan teams-D rulings 4 to 6).

The platform never calls a model, so it counts what it can see: tasks claimed and outbound source
requests. Pure: `services/budgets.py` decides when an event is written, `index/budgets.py` when one
counts. `budget.set` and `budget-exhausted` are this slice's; slice 6's compute budget is named
`compute-budget-*` (decision 75).

Invariants:
- Only the limit is declared. Consumption is always computed from events (R-05).
- Agent-reported usage is shown, labelled reported, and never enforced.
"""

from typing import Annotated, Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.lab import UserId

BUDGET_ID_RE = rf"^bdg_{ULID_RE}$"
MAX_BUDGET_LIMIT = 10**9
"""The largest limit a budget may declare, well inside SQLite's integer range."""

TASKS_PREFIX = "tasks:"
ALL_TASKS = "tasks:*"
REQUESTS_SEARCH = "requests:search"
REQUESTS_FULLTEXT = "requests:fulltext"
UNIT_RE = r"^(tasks:(\*|[a-z][a-z_]{0,63})|requests:(search|fulltext))$"

Period = Literal["total", "week"]
BudgetLimit = Annotated[int, Field(ge=0, le=MAX_BUDGET_LIMIT)]


class BudgetSet(StrictModel):
    """A limit on one unit for one user, or for the project when `scope_user` is None. It supersedes
    the previous budget of the same `(scope_user, unit)`, whatever that one's period."""

    budget_id: str = Field(pattern=BUDGET_ID_RE)
    scope_user: UserId | None
    unit: str = Field(pattern=UNIT_RE)
    limit: BudgetLimit
    period: Period


class Budget(StrictModel):
    """A budget in force."""

    budget_id: str
    scope_user: str | None
    unit: str
    limit: int
    period: Period


class BudgetLine(StrictModel):
    """A budget in force with what has been consumed of it in the current period."""

    budget: Budget
    consumed: int
    remaining: int


class BudgetStatus(StrictModel):
    """Every budget in force, and the usage agents reported, which is shown and never enforced.
    `notice` says why the view is empty on a project with neither."""

    budgets: list[BudgetLine]
    reported_usage: dict[str, float]
    notice: str | None
