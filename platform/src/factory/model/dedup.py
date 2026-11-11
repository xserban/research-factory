"""Dedup payloads: a merge of works, and the reversal of one.

Merges are events, never edits: `dedup.merged` opens a merge and `dedup.reverted` closes it.
Written by `factory.services.dedup`, folded by `factory.index.dedup`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.work_ids import WORK_ID_RE

MERGE_ID_RE = rf"^mrg_{ULID_RE}$"


class MergeStatus(StrEnum):
    ACTIVE = "active"
    REVERTED = "reverted"


class PairDecision(StrEnum):
    SAME = "same"
    DIFFERENT = "different"


class PairDecided(StrictModel):
    """The researcher's ruling on a candidate version pair (`work_a < work_b`)."""

    work_a: str = Field(pattern=WORK_ID_RE)
    work_b: str = Field(pattern=WORK_ID_RE)
    decision: PairDecision
    rationale: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    basis: str = Field(min_length=1)
    score: float | None = None

    @model_validator(mode="after")
    def _pair_is_ordered(self) -> Self:
        if not self.work_a < self.work_b:
            raise ValueError("work_a must sort before work_b")
        return self


class DedupMerged(StrictModel):
    """Works that the cascade judged to be one paper: `primary` absorbs the rest."""

    merge_id: str = Field(pattern=MERGE_ID_RE)
    primary: str = Field(pattern=WORK_ID_RE)
    absorbed: tuple[str, ...] = Field(min_length=1)
    rule: str
    records: int = Field(ge=1)

    @model_validator(mode="after")
    def _absorbed_is_sorted_and_excludes_primary(self) -> Self:
        if list(self.absorbed) != sorted(self.absorbed):
            raise ValueError("absorbed must be sorted")
        if self.primary in self.absorbed:
            raise ValueError("a work cannot absorb itself")
        return self


class DedupReverted(StrictModel):
    """A merge is undone. Manual reversals also keep the cascade from rebuilding it."""

    merge_id: str = Field(pattern=MERGE_ID_RE)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    manual: bool
