"""Relations and ideas of the lineage graph: value types and event payloads (slice 3b, G2-C).

Invariants enforced here (validated at the boundary, before any event is written):
- The agent proposes, the platform classifies: `RelationProposal` has no status field and refuses
  one; `RelationProposed` carries the computed status, reason, resolved target and flags.
- A `stated` relation names its basis item, the reference extraction and cited entry the target
  was resolved from, and its resolved target equals the proposed one; an `inferred` relation
  names why; a relation without a basis item is `no-basis` and carries a non-blank note.
- An idea's members are unique, sorted and contain its origin; a merge names two distinct ideas.
- Decisions carry a non-blank rationale. That only a human decides is a service and projector
  rule, not a payload rule.
- Free text is bounded: a relation note <= 500 characters, an idea name <= 200.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.chase import WorkId
from factory.model.extraction import EXTRACTION_ID_RE
from factory.model.identity import ULID_RE
from factory.model.screening import NonBlank

REL_ID_RE = rf"^rel_{ULID_RE}$"
IDEA_ID_RE = rf"^ida_{ULID_RE}$"
_TARGET_RE = rf"^(?:rf:\S+-[0-9a-f]{{8}}|ida_{ULID_RE})$"
MAX_CLASSIFIER = 40
MAX_NOTE = 500
MAX_IDEA_NAME = 200

RelationId = Annotated[str, StringConstraints(pattern=REL_ID_RE)]
IdeaId = Annotated[str, StringConstraints(pattern=IDEA_ID_RE)]
ItemId = Annotated[str, StringConstraints(pattern=EXTRACTION_ID_RE)]
Target = Annotated[str, StringConstraints(pattern=_TARGET_RE)]
Rationale = Annotated[NonBlank, Field(max_length=2000)]
Flag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]


class EdgeType(StrEnum):
    CITES = "cites"
    BUILDS_ON = "builds-on"
    IMPROVES_ON = "improves-on"


RelationType = Literal["builds-on", "improves-on"]
ProposalStatus = Literal["stated", "inferred"]


class EdgeStatus(StrEnum):
    STATED = "stated"
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    STALE = "stale"
    REJECTED = "rejected"


DEFAULT_STATUSES = frozenset({EdgeStatus.STATED, EdgeStatus.CONFIRMED})
"""The statuses a default view shows (R-xx(e)); every other status is on request, labelled."""


class StatusReason(StrEnum):
    NO_BASIS = "no-basis"
    NO_CITED_ENTRY = "no-cited-entry"
    LINK_UNCONFIRMED = "link-unconfirmed"
    TARGET_DIFFERS = "target-differs"


class LineageDecision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


class RelationProposal(StrictModel):
    """A relation proposal as an agent (or human) states it; it cannot set a status."""

    source_work: WorkId
    target: Target
    edge_type: RelationType
    basis_item: ItemId | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)


class RelationProposed(StrictModel):
    relation_id: RelationId
    source_work: WorkId
    target: Target
    edge_type: RelationType
    basis_item: ItemId | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    status: ProposalStatus
    status_reason: StatusReason | None = None
    resolved_target: str | None = None
    reference_extraction_id: str | None = None
    cited_entry: int | None = Field(default=None, ge=1)
    flags: tuple[Flag, ...] = ()
    classifier: Annotated[NonBlank, Field(max_length=MAX_CLASSIFIER)]
    supersedes: RelationId | None = None

    @model_validator(mode="after")
    def _status_is_consistent(self) -> Self:
        if self.status == "stated":
            if self.basis_item is None or self.reference_extraction_id is None:
                raise ValueError("a stated relation names its basis item and reference extraction")
            if self.cited_entry is None:
                raise ValueError("a stated relation names its cited entry")
            if self.resolved_target != self.target:
                raise ValueError("a stated relation resolves to its target")
            if self.status_reason is not None:
                raise ValueError("a stated relation has no status reason")
            return self
        if self.status_reason is None:
            raise ValueError("an inferred relation names its reason")
        if self.basis_item is None:
            if self.status_reason is not StatusReason.NO_BASIS:
                raise ValueError("a relation without a basis item is no-basis")
            if self.note is None or not self.note.strip():
                raise ValueError("a relation without a basis item needs a note")
        elif self.status_reason is StatusReason.NO_BASIS:
            raise ValueError("no-basis is for a relation without a basis item")
        return self


class RelationDecided(StrictModel):
    relation_id: RelationId
    decision: LineageDecision
    rationale: Rationale


class IdeaProposed(StrictModel):
    idea_id: IdeaId
    name: Annotated[NonBlank, Field(max_length=MAX_IDEA_NAME)]
    name_item: ItemId
    origin: WorkId
    members: tuple[WorkId, ...] = Field(min_length=1)
    supersedes: IdeaId | None = None

    @model_validator(mode="after")
    def _members_are_a_sorted_set_with_origin(self) -> Self:
        if list(self.members) != sorted(set(self.members)):
            raise ValueError("members must be unique and sorted")
        if self.origin not in self.members:
            raise ValueError("members must include the origin")
        return self


class IdeaDecided(StrictModel):
    idea_id: IdeaId
    decision: LineageDecision
    rationale: Rationale


class IdeaMerged(StrictModel):
    from_idea: IdeaId
    into: IdeaId
    reason: Rationale
    proposal: str | None = None
    """The consolidation proposal (`cnp_...`) this merge carries out, when it came from one."""

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if self.from_idea == self.into:
            raise ValueError("an idea cannot be merged into itself")
        return self


class IdeaUnmerged(IdeaMerged):
    """Reverts the latest merge of `from_idea`, which went into `into`."""
