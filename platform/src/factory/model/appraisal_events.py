"""Event payloads of appraisal (schema 1). Split from `model/appraisal.py`, which the protocol
imports: these need the screening types, which import the protocol."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.model.appraisal import (
    APPRAISAL_AUDIT_ID_RE,
    APPRAISAL_ITEM_RE,
    APPRAISAL_QUOTE_MAX,
    DIGEST_RE,
    Answer,
)
from factory.model.base import StrictModel
from factory.model.identity import CONVERSION_ID_RE
from factory.model.screening import Anchor, NonBlank, PassLabel
from factory.model.task import TASK_ID_RE


class AnswerInput(StrictModel):
    """One agent-span answer as the agent returns it."""

    item: str = Field(pattern=APPRAISAL_ITEM_RE)
    answer: Answer
    anchor: Anchor = None
    quote: str | None = Field(default=None, max_length=APPRAISAL_QUOTE_MAX)


class AppraisalRecorded(StrictModel):
    """One pass's answers for one work. `instrument` is `name@version`, `digest` the hash of the
    protocol section when the answers were given; `conversion_id` the document read."""

    task_id: str = Field(pattern=TASK_ID_RE)
    work_id: str
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    instrument: str
    digest: str = Field(pattern=DIGEST_RE)
    pass_label: PassLabel
    session: str
    model: str
    answers: tuple[AnswerInput, ...]
    finished: bool = False
    reason: str | None = None


class AppraisalJudged(StrictModel):
    """A human's judgement item. A later act on the same (work, item) supersedes the earlier,
    which stays in the log."""

    work_id: str
    item: str = Field(pattern=APPRAISAL_ITEM_RE)
    answer: Answer
    rationale: NonBlank
    digest: str = Field(pattern=DIGEST_RE)


class AppraisalResolved(StrictModel):
    """A human's choice between the two passes' answers on one span item (`a`, `b`), or
    `neither`, which records `unclear`."""

    work_id: str
    item: str = Field(pattern=APPRAISAL_ITEM_RE)
    choice: Literal["a", "b", "neither"]
    reason: NonBlank
    digest: str = Field(pattern=DIGEST_RE)


class AppraisalAuditSampled(StrictModel):
    """The (work, item) pairs drawn from the final span answers, with the seed that drew them."""

    audit_id: str = Field(pattern=APPRAISAL_AUDIT_ID_RE)
    random_seed: int
    digest: str = Field(pattern=DIGEST_RE)
    items: tuple[tuple[str, str], ...]


class AppraisalAuditLabelled(StrictModel):
    audit_id: str = Field(pattern=APPRAISAL_AUDIT_ID_RE)
    work_id: str
    item: str = Field(pattern=APPRAISAL_ITEM_RE)
    correct: bool
    note: str = ""
