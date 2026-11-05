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

from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Literal

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


# --- Read-time effects (pure) ---

Flag = Literal["retracted", "correction-pending", "concern", "none"]
Synthesis = Literal["excluded", "labelled", "normal"]

_FLAG_ORDER: tuple[Flag, ...] = ("none", "concern", "correction-pending", "retracted")
_SYNTHESIS_ORDER: tuple[Synthesis, ...] = ("normal", "labelled", "excluded")
_REMOVABLE = frozenset({NoticeKind.RETRACTION, NoticeKind.WITHDRAWAL})


class StaleMark(StrictModel):
    """An `affects` assessment that makes rows carrying `fields` doubtful: the rows recorded
    before the assessment's event (`assessed_at`, an event id), as an amendment judges only the
    rows recorded before it (decision 50)."""

    assessed_at: str
    fields: tuple[str, ...]


class WorkNoticeState(StrictModel):
    """What the notices about one work mean for its rows, claims and edges, computed at read time.

    `flag` is the strongest of the work's live notices; `synthesis` says whether its rows leave
    the synthesis (`excluded`), stay with a label (`labelled`) or are untouched (`normal`).
    `stale_fields` is the union of the fields named by `affects` assessments, with the assessing
    events in `stale_marks`. `assessed` is true when every live notice has an assessment (a
    reinstated retraction needs none)."""

    work_id: str
    flag: Flag
    synthesis: Synthesis
    stale_fields: tuple[str, ...]
    notices: tuple[str, ...]
    assessed: bool
    stale_marks: tuple[StaleMark, ...] = ()


def notice_state(
    observed: Sequence[NoticeObserved],
    assessed: Sequence[tuple[str, NoticeAssessed]],
) -> dict[str, WorkNoticeState]:
    """Per-work states from notices (in observation order) and assessments as (event id, payload).

    Pure. The latest assessment of a notice (greatest event id) wins. A reinstatement supersedes
    the retractions and withdrawals of the same work observed before it, so the work's state
    reverts to what the remaining notices give. Several live notices combine to the strongest flag
    and the strongest synthesis. Only works with a notice appear.
    """
    latest: dict[str, tuple[str, NoticeAssessed]] = {}
    for event_id, payload in assessed:
        current = latest.get(payload.notice_id)
        if current is None or event_id > current[0]:
            latest[payload.notice_id] = (event_id, payload)

    all_ids: dict[str, list[str]] = {}
    for notice in observed:
        all_ids.setdefault(notice.work_id, []).append(notice.notice_id)
    live = live_notices(observed)

    states: dict[str, WorkNoticeState] = {}
    for work_id, ids in all_ids.items():
        flag: Flag = "none"
        synthesis: Synthesis = "normal"
        marks: list[StaleMark] = []
        every_one_assessed = True
        for notice in live[work_id]:
            current = latest.get(notice.notice_id)
            decision = None if current is None else current[1].decision
            n_flag, n_synthesis = _effect(notice.kind, decision)
            if decision is None:
                every_one_assessed = False
            if decision is AssessmentDecision.AFFECTS and current is not None:
                marks.append(StaleMark(assessed_at=current[0], fields=current[1].fields))
            flag = max(flag, n_flag, key=_FLAG_ORDER.index)
            synthesis = max(synthesis, n_synthesis, key=_SYNTHESIS_ORDER.index)
        states[work_id] = WorkNoticeState(
            work_id=work_id,
            flag=flag,
            synthesis=synthesis,
            stale_fields=tuple(sorted({f for m in marks for f in m.fields})),
            notices=tuple(ids),
            assessed=every_one_assessed,
            stale_marks=tuple(sorted(marks, key=lambda m: m.assessed_at)),
        )
    return states


def live_notices(observed: Sequence[NoticeObserved]) -> dict[str, list[NoticeObserved]]:
    """Each work's notices that still count, in observation order: a reinstatement removes the
    retractions and withdrawals of its work observed before it and is not itself kept."""
    live: dict[str, list[NoticeObserved]] = {}
    for notice in observed:
        bucket = live.setdefault(notice.work_id, [])
        if notice.kind is NoticeKind.REINSTATEMENT:
            bucket[:] = [n for n in bucket if n.kind not in _REMOVABLE]
        else:
            bucket.append(notice)
    return live


def unassessed_notices(
    observed: Sequence[NoticeObserved], assessed: Sequence[tuple[str, NoticeAssessed]]
) -> list[NoticeObserved]:
    """The live notices no human has assessed, in observation order."""
    done = {a.notice_id for _, a in assessed}
    return [
        n for notices in live_notices(observed).values() for n in notices if n.notice_id not in done
    ]


def _effect(kind: NoticeKind, decision: AssessmentDecision | None) -> tuple[Flag, Synthesis]:
    """The flag and synthesis one notice gives, by its kind and the decision on it (spec ruling
    12). A decision that does not answer the kind counts as no decision."""
    if kind in _REMOVABLE:
        if decision is AssessmentDecision.KEEP_FLAGGED:
            return "retracted", "labelled"
        return "retracted", "excluded"
    if kind is NoticeKind.EXPRESSION_OF_CONCERN:
        if decision is AssessmentDecision.EXCLUDE:
            return "concern", "excluded"
        return "concern", "labelled"
    if kind is NoticeKind.CORRECTION:
        if decision in (AssessmentDecision.NO_EFFECT, AssessmentDecision.AFFECTS):
            return "none", "normal"
        return "correction-pending", "labelled"
    return "none", "normal"
