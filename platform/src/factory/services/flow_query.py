"""The filtered, paged reading of the work ledger (flow transparency, task 7).

Invariants:
- Read-only: nothing is written, and the rows are those of `flow_ledger`, unchanged.
- A row is selected under the conditions `flow_by_source` counts it under: a title/abstract
  outcome only for a screened row (canonical, not a non-canonical promoted work), and a full-text
  state or outcome for any row that has one. A filtered total therefore reconciles with the flow
  table.
- Every filter is validated before the page is cut. An unknown step, an outcome not of its step,
  an unknown source group or criterion, an outcome without a step, a criterion without a step or
  with an outcome other than `excluded`, a malformed cursor and a non-positive limit each raise
  `FactoryValidationError` with the field named, and nothing is returned.
- Pages are offsets in the ledger order (by work id): the cursor is the decimal offset of the next
  row, as `mcp.conventions.paginate` reads it.
"""

import re
from typing import Final

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.flow_ledger import LedgerRow, flow_ledger

PAGE_LIMIT: Final = 50
TITLE_ABSTRACT: Final = "title-abstract"
FULL_TEXT_RETRIEVAL: Final = "full-text-retrieval"
FULL_TEXT: Final = "full-text"

STEPS: Final[dict[str, frozenset[str]]] = {
    TITLE_ABSTRACT: frozenset({"included", "excluded", "pending"}),
    FULL_TEXT_RETRIEVAL: frozenset({"retrieved", "attempted-failed", "not-sought"}),
    FULL_TEXT: frozenset({"included", "excluded", "pending", "awaiting"}),
}


class FlowPage(StrictModel):
    """One page of ledger rows; `next_cursor` continues the listing, None on the last page."""

    items: list[LedgerRow]
    next_cursor: str | None


def _state_at(row: LedgerRow, step: str) -> str | None:
    """The state of a row at a step, as `flow_by_source` buckets it; None when it has none."""
    if step == TITLE_ABSTRACT:
        if row.noncanonical_promoted or row.canonical_id is not None:
            return None
        if row.ta_outcome is not None and row.ta_outcome.value in {"included", "excluded"}:
            return row.ta_outcome.value
        return "pending"
    if step == FULL_TEXT_RETRIEVAL:
        return row.ft_state
    return row.ft_outcome


def _selected(
    row: LedgerRow,
    source_group: str | None,
    step: str | None,
    outcome: str | None,
    criterion: str | None,
) -> bool:
    if source_group is not None and row.source_group != source_group:
        return False
    if step is None:
        return True
    state = _state_at(row, step)
    if state is None or (outcome is not None and state != outcome):
        return False
    if criterion is not None:
        mine = row.ta_criterion if step == TITLE_ABSTRACT else row.ft_criterion
        return state == "excluded" and mine == criterion
    return True


def _check_filters(
    rows: list[LedgerRow],
    source_group: str | None,
    step: str | None,
    outcome: str | None,
    criterion: str | None,
) -> list[ValidationIssue]:
    """The filters that need the ledger's own values (source groups and criteria it holds)."""
    issues: list[ValidationIssue] = []
    if source_group is not None:
        groups = sorted({row.source_group for row in rows})
        if source_group not in groups:
            issues.append(
                ValidationIssue("source_group", f"must be one of {', '.join(groups) or 'none'}")
            )
    if criterion is not None:
        criteria = sorted(
            {c for row in rows for c in (row.ta_criterion, row.ft_criterion) if c is not None}
        )
        if criterion not in criteria:
            issues.append(
                ValidationIssue("criterion", f"must be one of {', '.join(criteria) or 'none'}")
            )
    return issues


def _check_shape(
    step: str | None, outcome: str | None, criterion: str | None, cursor: str | None, limit: int
) -> list[ValidationIssue]:
    """The filters that need no ledger: the step names, outcomes, cursor and limit."""
    issues: list[ValidationIssue] = []
    if step is not None and step not in STEPS:
        issues.append(ValidationIssue("step", f"must be among {', '.join(STEPS)}"))
    elif outcome is not None:
        if step is None:
            issues.append(ValidationIssue("outcome", "needs a step"))
        elif outcome not in STEPS[step]:
            issues.append(ValidationIssue("outcome", f"must be among {', '.join(STEPS[step])}"))
    if criterion is not None:
        if step is None:
            issues.append(ValidationIssue("criterion", "needs a step"))
        elif outcome is not None and outcome != "excluded":
            issues.append(ValidationIssue("criterion", "needs the outcome excluded"))
    if cursor is not None and re.fullmatch(r"[0-9]+", cursor) is None:
        issues.append(ValidationIssue("cursor", "must be a decimal offset"))
    if limit < 1:
        issues.append(ValidationIssue("limit", "must be at least 1"))
    return issues


def flow_works(
    project: Project,
    *,
    source_group: str | None = None,
    step: str | None = None,
    outcome: str | None = None,
    criterion: str | None = None,
    cursor: str | None = None,
    limit: int = PAGE_LIMIT,
) -> FlowPage:
    """The ledger rows matching the filters, one page at a time (at most `PAGE_LIMIT`).

    `step` is `title-abstract`, `full-text-retrieval` or `full-text`; `outcome` is one of that
    step's states; `criterion` needs a step and selects the rows excluded at it by that criterion.
    Raises `FactoryValidationError` on any invalid filter.
    """
    issues = _check_shape(step, outcome, criterion, cursor, limit)
    if issues:
        raise FactoryValidationError(issues)
    rows = flow_ledger(project)
    issues = _check_filters(rows, source_group, step, outcome, criterion)
    if issues:
        raise FactoryValidationError(issues)
    start = 0 if cursor is None else int(cursor)
    size = min(limit, PAGE_LIMIT)
    selected = [row for row in rows if _selected(row, source_group, step, outcome, criterion)]
    page = selected[start : start + size]
    following = str(start + size) if start + size < len(selected) else None
    return FlowPage(items=page, next_cursor=following)


__all__ = [
    "FULL_TEXT",
    "FULL_TEXT_RETRIEVAL",
    "PAGE_LIMIT",
    "STEPS",
    "TITLE_ABSTRACT",
    "FlowPage",
    "flow_works",
]
