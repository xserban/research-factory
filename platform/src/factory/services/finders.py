"""Finders: numeric conflicts, claim contradictions and gaps (slice 6, plan H-B).

Computed candidates for a reader to weigh, never conclusions (decision 68). Invariants:
- Builders are read-only and deterministic. Their outputs carry ids, counts, canonical values
  and stored quotes only, never document text beyond a stored quote.
- A numeric conflict is a pair of independent rows of one normalised method and variant in one
  comparability group, from different works, whose values differ by more than the tolerance
  against the larger magnitude. A copied row is never independent, so it never conflicts with the
  row it copies. Nothing is compared across groups.
- Conflicts are derived group by group from the evidence report's `method_conflicts`, in the order
  `(group_id, method, row_a, row_b)`.
"""

from __future__ import annotations

import itertools
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from factory.errors import FactoryValidationError, ValidationIssue
from factory.extraction.numbers import normalise_text, parse_printed
from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.evidence_report import EvidenceRow, evidence_report

CONFLICT_RELATIVE_TOLERANCE = Decimal("0.01")
"""Relative tolerance against the larger magnitude (ruling 4); `hypothesis_plan.conflict_tolerance`
overrides it once plan H-C adds that section."""
LIMIT_MAX = 500
_PLACES = Decimal("0.0001")


class ConflictPair(StrictModel):
    group_id: str
    method: str
    variant: str | None
    row_a: str
    row_b: str
    work_a: str
    work_b: str
    value_a: str
    value_b: str
    relative_difference: str
    differs_in: list[str]
    trace_ids: tuple[str, str]


class ConflictPage(StrictModel):
    conflicts: list[ConflictPair]
    groups_scanned: int
    next_after: str | None


def _refuse(field_name: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, reason)])


def _number(row: EvidenceRow) -> Decimal | None:
    cell = row.value
    if isinstance(cell.value, bool):
        return None
    try:
        d = Decimal(cell.canonical) if cell.canonical is not None else parse_printed(cell.value)
    except InvalidOperation:
        return None
    return d if d is not None and d.is_finite() else None


def _differs(a: EvidenceRow, b: EvidenceRow) -> list[str]:
    keys = set(a.regime) | set(b.regime)
    return sorted(k for k in keys if a.regime.get(k) != b.regime.get(k))


def _cursor(pair: ConflictPair) -> str:
    return f"{pair.group_id}:{pair.method}:{pair.row_a}:{pair.row_b}"


def _cursor_key(after: str) -> tuple[str, str, str, str]:
    head, _, rest = after.partition(":")
    parts = rest.rsplit(":", 2)
    if not head or len(parts) != 3:
        raise _refuse("after", "malformed")
    return head, parts[0], parts[1], parts[2]


def find_conflicts(
    project: Project,
    *,
    group_id: str | None = None,
    limit: int = 50,
    after: str | None = None,
) -> ConflictPage:
    """Numeric conflicts in the evidence report, one page after the cursor `after`.

    `groups_scanned` counts the groups with a method conflict that the call examined. Refused,
    with nothing written: a `limit` outside 1..500, a malformed cursor."""
    if not 1 <= limit <= LIMIT_MAX:
        raise _refuse("limit", f"between 1 and {LIMIT_MAX}")
    start = None if after is None else _cursor_key(after)
    report = evidence_report(project)
    found: list[ConflictPair] = []
    scanned = 0
    for group in sorted(report.groups, key=lambda g: g.group_id):
        if group_id is not None and group.group_id != group_id:
            continue
        if not group.method_conflicts:
            continue
        scanned += 1
        by_key = {(r.row_key, r.work_id): r for r in group.rows if r.independent}
        for conflict in group.method_conflicts:
            wanted = set(conflict.rows)
            members = [r for r in by_key.values() if r.row_key in wanted]
            for a, b in itertools.combinations(sorted(members, key=lambda r: r.row_key), 2):
                pair = _pair(group.group_id, conflict.method, conflict.variant, a, b)
                if pair is not None:
                    found.append(pair)
    found.sort(key=lambda p: (p.group_id, p.method, p.row_a, p.row_b))
    if start is not None:
        found = [p for p in found if (p.group_id, p.method, p.row_a, p.row_b) > start]
    window = found[:limit]
    more = len(found) > limit
    return ConflictPage(
        conflicts=window,
        groups_scanned=scanned,
        next_after=_cursor(window[-1]) if window and more else None,
    )


def _pair(
    gid: str, method: str, variant: str | None, a: EvidenceRow, b: EvidenceRow
) -> ConflictPair | None:
    if a.work_id == b.work_id:
        return None
    if normalise_text(a.value.unit or "") != normalise_text(b.value.unit or ""):
        return None
    na, nb = _number(a), _number(b)
    if na is None or nb is None:
        return None
    larger = max(abs(na), abs(nb))
    if larger == 0:
        return None
    relative = abs(na - nb) / larger
    if relative <= CONFLICT_RELATIVE_TOLERANCE:
        return None
    return ConflictPair(
        group_id=gid,
        method=method,
        variant=variant,
        row_a=a.row_key,
        row_b=b.row_key,
        work_a=a.work_id,
        work_b=b.work_id,
        value_a=format(na.normalize(), "f"),
        value_b=format(nb.normalize(), "f"),
        relative_difference=str(relative.quantize(_PLACES, rounding=ROUND_HALF_UP)),
        differs_in=_differs(a, b),
        trace_ids=(a.value.trace_id, b.value.trace_id),
    )
