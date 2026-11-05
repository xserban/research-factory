"""Notices of retraction, correction and the like about a known work (slice 4b, living-C).

A notice is observed from source metadata, never typed by an agent. Its effects are computed at
read time from `notice.observed` and `notice.assessed` events by a single pure function; nothing
here is stored as a derived status.

Invariants:
- A notice's identity is `(work_id, kind, notice_doi or source)`; the projection keeps the first
  observation of an identity and ignores repeats.
- `notice_date` is None when the source does not state it (an OpenAlex-only retraction).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.work import RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE

NTC_ID_RE = rf"^ntc_{ULID_RE}$"


class NoticeKind(StrEnum):
    RETRACTION = "retraction"
    WITHDRAWAL = "withdrawal"
    CORRECTION = "correction"
    EXPRESSION_OF_CONCERN = "expression-of-concern"
    REINSTATEMENT = "reinstatement"


class NoticeObserved(StrictModel):
    """A notice about a work, read from a source's metadata in a status run (system actor)."""

    notice_id: str = Field(pattern=NTC_ID_RE)
    work_id: str = Field(pattern=WORK_ID_RE)
    kind: NoticeKind
    notice_date: date | None = None
    notice_doi: str | None = None
    source: str = Field(min_length=1)
    run_id: str = Field(pattern=RUN_ID_RE)
    raw_blob: str = Field(pattern=BLOB_REF_RE)

    @property
    def identity(self) -> str:
        """The third part of the notice's identity: its own DOI, else the source that reported."""
        return self.notice_doi or self.source


class AssessmentDecision(StrEnum):
    """A human's reading of a notice. `exclude` and `keep-flagged` answer a retraction,
    withdrawal or expression of concern; `no-effect` and `affects` answer a correction."""

    EXCLUDE = "exclude"
    KEEP_FLAGGED = "keep-flagged"
    NO_EFFECT = "no-effect"
    AFFECTS = "affects"


class NoticeAssessed(StrictModel):
    """A human assessment of one notice; a later one for the same notice supersedes it.

    `fields` names the extraction fields a correction affects (non-empty exactly for `affects`);
    that they are fields of a declared schema is checked by the service, which knows the protocol.
    """

    notice_id: str = Field(pattern=NTC_ID_RE)
    decision: AssessmentDecision
    fields: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _fields_iff_affects(self) -> NoticeAssessed:
        if (self.decision is AssessmentDecision.AFFECTS) != bool(self.fields):
            raise ValueError("fields are given exactly when the decision is affects")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("fields must be unique")
        if not self.rationale.strip():
            raise ValueError("a rationale is required")
        return self
