"""Claim-level contradictions proposed by an agent and decided by a human (slice 6, plan H-B).

Invariants:
- A proposal names two refs, each a claim (`clm_`), a contribution item (`ext_`) or an m-claims
  row of a work (`row:<work_id>#<row_key>`), and a non-blank note of at most 500 characters. The
  platform fills works and stored quotes (and, for a row, its verified anchor) from the
  refs; refs are stored in sorted order, so a pair has one form.
- The status is never set by an agent: `ContradictionDecided` is a human act (a service and
  projector rule, not a payload rule), and carries a non-blank rationale.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.extraction import CLAIM_ID_RE, EXTRACTION_ID_RE
from factory.model.identity import ULID_RE
from factory.model.screening import NonBlank
from factory.model.work_ids import WORK_ID_RE

CONTRADICTION_ID_RE = rf"^ctr_{ULID_RE}$"
ROW_REF_PREFIX = "row:"
ROW_REF_RE = r"row:rf:\S+-[0-9a-f]{8}#\S.*"
"""A row ref is `row:<work_id>#<row_key>`: an m-claims row of a work (night feature N10)."""
REF_RE = rf"^(?:{CLAIM_ID_RE[1:-1]}|{EXTRACTION_ID_RE[1:-1]}|{ROW_REF_RE})$"
MAX_NOTE = 500
MAX_RATIONALE = 2000


def row_ref(work_id: str, row_key: str) -> str:
    """The ref of the m-claims row `row_key` of `work_id`."""
    return f"{ROW_REF_PREFIX}{work_id}#{row_key}"


def parse_row_ref(ref: str) -> tuple[str, str] | None:
    """`(work_id, row_key)` of a row ref; None for any other ref."""
    if not ref.startswith(ROW_REF_PREFIX):
        return None
    work_id, _, key = ref[len(ROW_REF_PREFIX) :].partition("#")
    return (work_id, key) if key else None


Ref = Annotated[str, StringConstraints(pattern=REF_RE)]
ContradictionId = Annotated[str, StringConstraints(pattern=CONTRADICTION_ID_RE)]
Note = Annotated[NonBlank, Field(max_length=MAX_NOTE)]
WorkId = Annotated[str, StringConstraints(pattern=WORK_ID_RE)]


class ContradictionInput(StrictModel):
    """What an agent states: two refs and a note. Nothing else can be set."""

    ref_a: Ref
    ref_b: Ref
    note: Note


class ContradictionProposed(StrictModel):
    contradiction_id: ContradictionId
    ref_a: Ref
    ref_b: Ref
    work_a: WorkId
    work_b: WorkId
    quote_a: NonBlank
    quote_b: NonBlank
    note: Note
    anchor_a: str | None = None
    anchor_b: str | None = None
    """The anchor the quote of a row ref was verified in; None for older events and other refs."""

    @model_validator(mode="after")
    def _sorted_distinct(self) -> ContradictionProposed:
        if not self.ref_a < self.ref_b:
            raise ValueError("refs are distinct and stored in sorted order")
        return self


class ContradictionDecided(StrictModel):
    contradiction_id: ContradictionId
    decision: Literal["confirm", "reject"]
    rationale: Annotated[NonBlank, Field(max_length=MAX_RATIONALE)]
