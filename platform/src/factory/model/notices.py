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

from pydantic import Field

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
