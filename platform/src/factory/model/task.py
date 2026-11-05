from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, Field

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

TASK_LEASE = timedelta(minutes=30)
TASK_KIND_RE = r"^[a-z][a-z_]*$"
TASK_ID_RE = rf"^tsk_{ULID_RE}$"
HYPOTHESIS_REVIEW_TASK_KIND = "hyp_review"
"""The kind of the critic review tasks of hypotheses (slice 6). Like the intuition layer's
tasks they are not part of the work the project counts."""
INTUITION_TASK_KIND = "intuition"
"""The kind of the intuition layer's tasks. Pass joins and task counts name it by value, as the
layer's modules may not be imported by them."""
DRAFT_VERIFY_TASK_KIND = "draft_verify"
"""The kind of the verification units (one sentence); left out of the task counts as the slots."""
DRAFT_VERIFY_TASK_KIND = "draft_verify"
"""The kind of the verification units (one sentence); not counted, as the slots are not."""
DRAFT_SLOT_TASK_KIND = "draft_slot"
"""The kind of the writing slot tasks (one outline section of a draft). Like the intuition layer's
tasks they are not part of the work the project counts."""
CONSOLIDATE_TASK_KIND = "consolidate"
"""The kind of the consolidation tasks (one per candidate cluster)."""


class TaskStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    COMPLETED = "completed"


class Task(StrictModel):
    """Read model of one task, as the projection holds it."""

    task_id: str
    kind: str
    status: TaskStatus
    content_blob: str
    refs: tuple[str, ...]
    created_at: datetime
    claimed_by: str | None
    claim_session: str | None
    lease_until: datetime | None


class TaskCreated(StrictModel):
    task_id: str = Field(pattern=TASK_ID_RE)
    kind: str = Field(pattern=TASK_KIND_RE)


class TaskClaimed(StrictModel):
    task_id: str = Field(pattern=TASK_ID_RE)
    lease_until: AwareDatetime


class TaskCompleted(StrictModel):
    task_id: str = Field(pattern=TASK_ID_RE)
    result_refs: tuple[str, ...] = ()


class TaskReleased(StrictModel):
    task_id: str = Field(pattern=TASK_ID_RE)
    reason: str
