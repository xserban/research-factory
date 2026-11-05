"""Per-group reads of the final evidence rows (slice 7b, plan V-B, task 1).

Declares: `group_index`, `rows_of_group`, `final_rows_for`. A reader of the
index; it writes no event and no table.

Invariants:
- `rows_of_group(p, group_id(k))` equals `grouped_rows(p).groups[k]` and `group_index` lists
  exactly the keys of `grouped_rows(p).groups`, with counts from `independence_counts`. The
  evidence report keeps reading `grouped_rows`; nothing here changes it.
- `rows_of_group` finds the candidate works from the key cells of live rows (a SQL scan, normalised
  as a group key is) and runs the plan-D fold for those works only. A work's final rows depend on
  its own rows, so the restricted fold equals the filter of the full one. The scan reads cells,
  not rows with their fields; the fold still reads the ledger of the scope once per call
  (`group_index` folds once and keeps only the summaries).
- A group id naming no current group is refused (field `group_id`); nothing is written.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from itertools import product

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.extraction import Scope
from factory.model.views import GroupSummary
from factory.services.context import Project
from factory.services.evidence_report import group_id
from factory.services.extraction import require_schema
from factory.services.extraction_agreement import (
    NON_COMPARABLE_KEYS,
    FinalRow,
    GroupKey,
    cell_key,
    final_rows_restricted,
    group_rows,
    grouped_rows,
    independence_counts,
)


def summarise(key: GroupKey, rows: Sequence[FinalRow]) -> GroupSummary:
    """The summary of one group from its rows (counts as `independence_counts` makes them)."""
    counts = independence_counts(rows)
    return GroupSummary(
        group_id=group_id(key),
        key=list(key),
        works=len({r.work_id for r in rows}),
        rows=len(rows),
        independent=counts.independent,
        copied=counts.copied,
    )


def group_index(project: Project) -> list[GroupSummary]:
    """One summary per comparability group, ordered by key. Empty without a schema."""
    grouped = grouped_rows(project)
    return [summarise(key, grouped.groups[key]) for key in sorted(grouped.groups)]


def final_rows_for(project: Project, work_ids: Collection[str]) -> list[FinalRow]:
    """The final rows of the given works (plan-D fold restricted to them), by work then key."""
    return final_rows_restricted(project, work_ids)


def rows_of_group(project: Project, gid: str) -> list[FinalRow]:
    """Exactly the rows `grouped_rows` puts in group `gid`; unknown id -> field `group_id`."""
    return key_and_rows(project, gid)[1]


def key_and_rows(project: Project, gid: str) -> tuple[GroupKey, list[FinalRow]]:
    """The key of group `gid` and its rows (see `rows_of_group`)."""
    project.index.sync()
    try:
        _, schema, pack = require_schema(project)
    except FactoryValidationError:
        raise _unknown(gid) from None
    keys = [
        k
        for k in (schema.comparability_keys or pack.default_comparability_keys)
        if k not in NON_COMPARABLE_KEYS
    ]
    found = _candidates(project, keys, gid)
    if found is None:
        raise _unknown(gid)
    key, works = found
    rows = final_rows_restricted(project, works)
    return key, group_rows(rows, pack, keys).groups.get(key, [])


def _unknown(gid: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("group_id", f"unknown group {gid}")])


def _candidates(project: Project, keys: list[str], gid: str) -> tuple[GroupKey, set[str]] | None:
    """The group key whose id is `gid` and the works that may hold a final row in it: those with,
    for every key field, a live row whose cell normalises to the key's value. A superset of the
    group's works (a human may have chosen the other pass's cell), never a subset."""
    if not keys:
        return None
    _, _, pack = require_schema(project)
    cells: dict[str, dict[str, set[str]]] = {}
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.work_id, f.field, f.value, f.unit, f.canonical "
                "FROM extraction_rows r JOIN extraction_fields f "
                "ON f.extraction_id = r.extraction_id "
                "WHERE r.scope = :scope AND r.superseded_by IS NULL "
                "AND f.field IN (SELECT value FROM json_each(:keys)) "
                "ORDER BY r.work_id, f.field"
            ),
            {"scope": Scope.EVIDENCE.value, "keys": json.dumps(keys)},
        )
        for work, name, value, unit, canonical in rows:
            norm = cell_key(pack.field(str(name)), str(value), unit, canonical)
            cells.setdefault(str(work), {}).setdefault(str(name), set()).add(norm)
    found: GroupKey | None = None
    works: set[str] = set()
    for work, by_field in cells.items():
        if any(k not in by_field for k in keys):
            continue
        for combo in product(*(sorted(by_field[k]) for k in keys)):
            key: GroupKey = tuple(zip(keys, combo, strict=True))
            if group_id(key) == gid:
                found = key
                works.add(work)
    return None if found is None else (found, works)


__all__ = [
    "GroupSummary",
    "final_rows_for",
    "group_index",
    "key_and_rows",
    "rows_of_group",
    "summarise",
]
