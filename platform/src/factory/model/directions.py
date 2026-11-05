"""The failed-directions registry: reasons, conditions and the human `direction.closed` record
(slice 6, plan XP-B task 6; spec ruling 27; R-52, R-124).

Invariants enforced here (validated at the boundary, before any event is written):
- A registry row states why a direction failed (`DirectionReason`) and the conditions it failed
  under (`Conditions`): the design version, the datasets, the compute used, the models and the code
  commit. A row is "failed here", never "impossible", and is never removed.
- A closed direction is a human's record of a direction that never became a hypothesis: a short
  text, a reason, conditions and one to twenty keys it is searchable by. No input model carries an
  id; the platform issues it.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from factory.model.base import StrictModel
from factory.model.hypotheses import DIRECTION_ID_RE, Decimal0
from factory.model.screening import NonBlank

DIR_ID_RE = DIRECTION_ID_RE
MAX_DIRECTION_TEXT = 600
MAX_KEYS = 20


class DirectionReason(StrEnum):
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    BELOW_BASELINE = "below-baseline"
    BASELINE_NOT_REPRODUCED = "baseline-not-reproduced"
    BUDGET_EXHAUSTED = "compute-budget-exhausted"
    NO_RUNNABLE_CODE = "no-runnable-code"
    INFEASIBLE = "infeasible"
    DATA_UNAVAILABLE = "data-unavailable"
    DISCARDED_LEAD = "discarded-lead"
    OTHER = "other"


class Conditions(StrictModel):
    """What a direction failed under (R-124); every field is optional because a lead that was
    discarded, say, had no design."""

    e_version: Annotated[str, StringConstraints(pattern=r"^E@[0-9a-f]{8}$")] | None = None
    datasets: tuple[Annotated[NonBlank, Field(max_length=200)], ...] = ()
    gpu_hours_used: Decimal0 | None = None
    models: tuple[Annotated[NonBlank, Field(max_length=120)], ...] = ()
    code_commit: Annotated[NonBlank, Field(max_length=200)] | None = None


Key = Annotated[NonBlank, Field(max_length=200)]


class DirectionClosed(StrictModel):
    direction_id: Annotated[str, StringConstraints(pattern=DIR_ID_RE)]
    text: Annotated[NonBlank, Field(max_length=MAX_DIRECTION_TEXT)]
    reason: DirectionReason
    conditions: Conditions = Field(default_factory=Conditions)
    keys: tuple[Key, ...] = Field(min_length=1, max_length=MAX_KEYS)
