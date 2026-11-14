"""The score of a miner's calibration pass against human gold (slice M ruling 16; M-D ruling 4).

Pure: a function of the gold rows, the agent's rows and the pack. Nothing here reads the index,
the log or a clock, and nothing is typed in: every number is computed (R-05).

Definitions (per unit, rows matched by `row_key`):
- record recall: gold rows with an agent row of the same key, over gold rows;
- field agreement: over the matched rows, the compared fields on which gold and agent agree (plan
  D's `same_field` rule: normalised value, unit, `reported_in`, `reproduced`), over the compared
  fields present in either row (a field one side omits disagrees);
- unmatched slots (IDEA-69 (2)): per unit, the larger of its unmatched gold rows and unmatched
  agent rows; two rows with different keys on one unit (the passes chose different categories)
  are one slot, not two;
- field agreement over all rows: the agreed fields over the compared fields of the matched rows
  plus the unmatched ones: per unit, the larger of the compared fields present in its unmatched
  gold rows and in its unmatched agent rows (they never agree). It equals field agreement when
  every row matches;
- precision: matched rows over agent rows (extra agent rows lower it; it is reported, never gated,
  as specificity, R-31);
- verification rate: rows the platform accepted over rows the calibration pass submitted (given by
  the caller, which reads them from the recorded input).

A rate over an empty denominator is None, never 0 or 1.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from factory.model.extraction import StoredField
from factory.packs import Pack
from factory.services.extraction_agreement import check_overlap_threshold, same_field


class ScoredRow(Protocol):
    """What scoring reads of a row: its key and verified fields (a gold row or a recorded one)."""

    @property
    def row_key(self) -> str: ...

    @property
    def fields(self) -> Mapping[str, StoredField]: ...


@dataclass(frozen=True)
class CalibrationScore:
    gold_rows: int
    agent_rows: int
    matched: int
    recall: float | None
    field_agreement: float | None
    precision: float | None
    verification_rate: float | None
    unmatched: int = 0
    field_agreement_all: float | None = None
    evidence_overlap: float | None = None
    """The threshold free-quote fields were compared under (IDEA-52), or None: exact."""


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _compared(pack: Pack) -> tuple[str, ...]:
    return pack.compared_fields or tuple(f.name for f in pack.fields)


def _present(rows: Sequence[ScoredRow], names: Sequence[str]) -> int:
    """The compared fields present over `rows`."""
    return sum(name in row.fields for row in rows for name in names)


def score(
    gold: Mapping[str, Sequence[ScoredRow]],
    agent: Mapping[str, Sequence[ScoredRow]],
    pack: Pack,
    *,
    verified: int | None = None,
    submitted: int | None = None,
    evidence_overlap: float | None = None,
) -> CalibrationScore:
    """Score `agent` rows against `gold` rows, both by unit (work id). Units are those of `gold`;
    agent rows of a unit with no gold entry count as extra. `verified` and `submitted` give the
    verification rate (None leaves it None). With `evidence_overlap` (a threshold, off by default),
    a free-quote field also agrees when the two quotes rest on the same evidence (IDEA-52); the
    threshold is recorded in the result; one outside `0 < t <= 1` is refused."""
    check_overlap_threshold(evidence_overlap)
    names = _compared(pack)
    gold_rows = sum(len(rows) for rows in gold.values())
    agent_rows = sum(len(rows) for rows in agent.values())
    matched = 0
    compared = 0
    equal = 0
    unmatched = 0
    missed = 0
    for work, wanted in gold.items():
        offered = agent.get(work, ())
        found = {row.row_key: row for row in offered}
        keys = {row.row_key for row in wanted}
        lone_gold = [row for row in wanted if row.row_key not in found]
        lone_agent = [row for row in offered if row.row_key not in keys]
        unmatched += max(len(lone_gold), len(lone_agent))
        missed += max(_present(lone_gold, names), _present(lone_agent, names))
        for row in wanted:
            other = found.get(row.row_key)
            if other is None:
                continue
            matched += 1
            for name in names:
                a, b = row.fields.get(name), other.fields.get(name)
                if a is None and b is None:
                    continue
                compared += 1
                if (
                    a is not None
                    and b is not None
                    and same_field(pack.field(name), a, b, evidence_overlap=evidence_overlap)
                ):
                    equal += 1
    return CalibrationScore(
        gold_rows=gold_rows,
        agent_rows=agent_rows,
        matched=matched,
        recall=_ratio(matched, gold_rows),
        field_agreement=_ratio(equal, compared),
        unmatched=unmatched,
        field_agreement_all=_ratio(equal, compared + missed),
        evidence_overlap=evidence_overlap,
        precision=_ratio(matched, agent_rows),
        verification_rate=(
            None if verified is None or submitted is None else _ratio(verified, submitted)
        ),
    )
