"""Curation: reviewed proposals made from audit findings (IDEA-15, plan SV task 4, PD-8).

Invariants enforced here (validated at the boundary, before any event is written):
- A proposal (`cur_`) has a kind (`amendment`, `worked-example`, `skill-revision`), a short text,
  one to twenty lesson ids it answers and an optional target. The platform issues the id.
- A decision accepts or rejects a proposal, with a rationale. An accepted `amendment` may link the
  `protocol.amended` event that carried it out; accepting changes no protocol by itself (R-34).

This module is pure. The fold (`factory.index.curation`) refuses a decision by a non-human, by the
proposer, or a second decision on one proposal.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from factory.events.envelope import EVENT_ID_RE
from factory.model.base import StrictModel
from factory.model.identity import ULID_RE
from factory.model.screening import NonBlank

CUR_ID_RE = rf"^cur_{ULID_RE}$"
MAX_TEXT = 1000
MAX_LESSONS = 20


class CurationKind(StrEnum):
    AMENDMENT = "amendment"
    WORKED_EXAMPLE = "worked-example"
    SKILL_REVISION = "skill-revision"


class CurationDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


LessonId = Annotated[NonBlank, Field(max_length=200)]


class CurationProposed(StrictModel):
    cur_id: Annotated[str, StringConstraints(pattern=CUR_ID_RE)]
    kind: CurationKind
    text: Annotated[NonBlank, Field(max_length=MAX_TEXT)]
    lessons: tuple[LessonId, ...] = Field(min_length=1, max_length=MAX_LESSONS)
    target: Annotated[NonBlank, Field(max_length=200)] | None = None


class CurationDecided(StrictModel):
    cur_id: Annotated[str, StringConstraints(pattern=CUR_ID_RE)]
    decision: CurationDecision
    rationale: NonBlank
    amendment_event: Annotated[str, StringConstraints(pattern=EVENT_ID_RE)] | None = None

    @model_validator(mode="after")
    def _link_only_when_accepted(self) -> CurationDecided:
        if self.amendment_event is not None and self.decision is not CurationDecision.ACCEPTED:
            raise ValueError("an amendment is linked only when the proposal is accepted")
        return self
