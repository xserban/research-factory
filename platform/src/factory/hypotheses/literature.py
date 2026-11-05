"""Work-level comparisons for a literature hypothesis (slice 6, plan XP-B, ruling 5). Pure.

Invariants:
- A work compares the two methods when it was published on or after the window start (an
  undated work is not in the window) and has, in one evidence group that meets every requirement
  of the hypothesis (`group_holds`: its conditions and its metric, ruling 16), an independent row
  for each method with a canonical value. A group with no metric key meets no metric requirement.
- With several rows of one method in one work the one with the smallest row key is used, so the
  same facts always give the same comparison; a work is counted once.
- Which method a work favours is `rules.favour_of`: the oriented difference beyond the margin.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from factory.extraction.numbers import normalise_text
from factory.hypotheses.rules import Favour, favour_of


@dataclass(frozen=True)
class LitRow:
    work_id: str
    row_key: str
    method_name: str | None
    value: str | None
    independent: bool


Group = tuple[Sequence[tuple[str, str]], Sequence[LitRow]]
"""An evidence group: its comparability key and its rows."""
Requirement = tuple[str, frozenset[str]]
"""A key of an evidence group and the normalised values it may hold."""


def group_holds(key: Sequence[tuple[str, str]], requirements: Sequence[Requirement]) -> bool:
    """Whether a group's key meets every requirement; a key the group lacks does not."""
    values = dict(key)
    return all(k in values and normalise_text(values[k]) in forms for k, forms in requirements)


def compare_works(
    groups: Sequence[Group],
    *,
    treatment: str,
    baseline: str,
    requirements: Sequence[Requirement],
    window_start: str,
    dates: Mapping[str, str],
    direction: str,
    margin: Decimal,
) -> dict[str, tuple[str, str, Favour]]:
    """Work id to (treatment row key, baseline row key, favoured side) for each comparing work."""
    out: dict[str, tuple[str, str, Favour]] = {}
    for key, rows in groups:
        if not group_holds(key, requirements):
            continue
        by_work: dict[str, list[LitRow]] = {}
        for row in rows:
            if row.independent and row.value is not None:
                by_work.setdefault(row.work_id, []).append(row)
        for work in sorted(by_work):
            if work in out or dates.get(work, "") < window_start:
                continue
            t = sorted((r for r in by_work[work] if r.method_name == treatment), key=_key)
            b = sorted((r for r in by_work[work] if r.method_name == baseline), key=_key)
            if t and b and t[0].value is not None and b[0].value is not None:
                out[work] = (
                    t[0].row_key,
                    b[0].row_key,
                    favour_of(Decimal(t[0].value), Decimal(b[0].value), direction, margin),
                )
    return out


def _key(row: LitRow) -> str:
    return row.row_key
