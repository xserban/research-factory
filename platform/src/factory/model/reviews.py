"""Review requests (slice 5 ruling 14): a proposal its requester may not apply alone.

Pure: `services/reviews.py` decides when an event is written, `index/reviews.py` when one counts.

Invariants:
- A review's state is never stored: `ReviewState` is computed on read from the two events, the
  event that consumed it and the current protocol.
- Approval executes nothing. The proposal is data, and the ordinary tool consumes it.
- `required_role` is a role that may decide: `owner` or `maintainer`.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, REVIEW_REQUEST_ID_RE
from factory.model.lab import Reason
from factory.model.members import ProjectRole
from factory.model.protocol import PROTOCOL_ID_RE, CriterionEffect, ProtocolSpec
from factory.model.screening import Channel

MAX_TARGET_LENGTH = 200
ReviewDecision = Literal["approve", "reject", "withdraw"]
ReviewRequestId = Annotated[str, Field(pattern=REVIEW_REQUEST_ID_RE)]
DECIDING_ROLES = frozenset({ProjectRole.OWNER, ProjectRole.MAINTAINER})


class ReviewKind(StrEnum):
    PROTOCOL_AMEND = "protocol-amend"
    PROTOCOL_RECORD = "protocol-record"
    DEVIATION = "deviation"


class ReviewState(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CONSUMED = "consumed"
    STALE = "stale"


class ProtocolAmendProposal(StrictModel):
    """What `protocol_amend` takes."""

    spec: ProtocolSpec
    reason: Reason
    semantic: bool
    effects: dict[str, CriterionEffect] = Field(default_factory=dict)


class ProtocolRecordProposal(StrictModel):
    """What `protocol_record` takes."""

    spec: ProtocolSpec
    ready: bool = False


class DeviationProposal(StrictModel):
    """What `protocol_deviation` takes."""

    description: str = Field(min_length=1)
    reason: Reason
    affects: tuple[str, ...] = ()


Proposal = ProtocolAmendProposal | ProtocolRecordProposal | DeviationProposal

PROPOSAL_MODELS: Mapping[ReviewKind, type[Proposal]] = {
    ReviewKind.PROTOCOL_AMEND: ProtocolAmendProposal,
    ReviewKind.PROTOCOL_RECORD: ProtocolRecordProposal,
    ReviewKind.DEVIATION: DeviationProposal,
}
"""The model each kind's proposal is validated by, before it is written and whenever it is read."""

REVIEW_GATES: Mapping[ReviewKind, str] = {
    ReviewKind.PROTOCOL_AMEND: "protocol.amend",
    ReviewKind.PROTOCOL_RECORD: "protocol.record",
    ReviewKind.DEVIATION: "protocol.deviation",
}
"""The team gate each kind asks to pass; `services.access.TEAM_GATES` gives its role."""


class ReviewRequested(StrictModel):
    """`target` is the current `P@` of an amendment or deviation, and the project's slug for a
    protocol record. `target_version` is the protocol current when the request was filed, None
    when there was none: a later protocol makes the request stale."""

    review_request_id: ReviewRequestId
    kind: ReviewKind
    target: str = Field(min_length=1, max_length=MAX_TARGET_LENGTH)
    target_version: str | None = Field(default=None, pattern=PROTOCOL_ID_RE)
    proposal_blob: str = Field(pattern=BLOB_REF_RE)
    required_role: ProjectRole
    reason: Reason

    @field_validator("required_role")
    @classmethod
    def _role_decides(cls, value: ProjectRole) -> ProjectRole:
        if value not in DECIDING_ROLES:
            raise ValueError("must be owner or maintainer")
        return value


class ReviewDecided(StrictModel):
    review_request_id: ReviewRequestId
    decision: ReviewDecision
    rationale: Reason
    channel: Channel
