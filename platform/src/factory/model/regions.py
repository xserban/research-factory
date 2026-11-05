"""Event payloads of regions (slice 3d, plan Regions-A).

Invariants:
- A region is cited only by its pinned version `R@`; the definition prose is bounded and never part
  of the version hash.
- `RegionSnapshotTaken` carries computed fields only (counts, hashes, blob refs); no actor types a
  number.
- A focus names exactly one `(question_id, slot)`; a region of kind `region` names none.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, CONVERSION_ID_RE, ULID_RE
from factory.model.question import QUESTION_ID_RE
from factory.model.screening import NonBlank, anchor_form
from factory.model.work_ids import WORK_ID_RE
from factory.regions.rules import REGION_VERSION_RE, MemberType, RuleSet

REGION_ID_RE = rf"^reg_{ULID_RE}$"
EVENT_ID_PATTERN = rf"^ev_{ULID_RE}$"
REGION_DEFINITION_MAX_CHARS = 600
REGION_NAME_MAX_CHARS = 120
REVIEW_NOTE_MAX_CHARS = 600
PROPOSAL_ID_RE = rf"^rmp_{ULID_RE}$"
PROPOSAL_NOTE_MAX_CHARS = 300


class RegionKind(StrEnum):
    FOCUS = "focus"
    REGION = "region"


class Facet(StrictModel):
    question_id: str = Field(pattern=QUESTION_ID_RE)
    slot: str = Field(min_length=1)


class RegionDefined(StrictModel):
    region_id: str = Field(pattern=REGION_ID_RE)
    kind: RegionKind
    facet: Facet | None = None
    name: str = Field(min_length=1, max_length=REGION_NAME_MAX_CHARS)
    definition: str = Field(min_length=1, max_length=REGION_DEFINITION_MAX_CHARS)
    rules: RuleSet
    supersedes: str | None = Field(default=None, pattern=EVENT_ID_PATTERN)
    author: Literal["agent", "human"]

    @model_validator(mode="after")
    def _facet_iff_focus(self) -> Self:
        if (self.kind is RegionKind.FOCUS) != (self.facet is not None):
            raise ValueError("a focus needs a facet and a region takes none")
        return self


class RegionSnapshotTaken(StrictModel):
    region_id: str = Field(pattern=REGION_ID_RE)
    version: str = Field(pattern=REGION_VERSION_RE)
    definition_event: str = Field(pattern=EVENT_ID_PATTERN)
    rules_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: tuple[str, ...] = ()
    members_blob: str = Field(pattern=BLOB_REF_RE)
    members_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    basis_blob: str = Field(pattern=BLOB_REF_RE)
    counts: dict[MemberType, int]
    as_of: str = Field(pattern=EVENT_ID_PATTERN)


class RegionReviewed(StrictModel):
    version: str = Field(pattern=REGION_VERSION_RE)
    state: Literal["reviewed", "wrong"]
    note: str | None = Field(default=None, max_length=REVIEW_NOTE_MAX_CHARS)
    self_reviewed: bool

    @model_validator(mode="after")
    def _wrong_needs_note(self) -> Self:
        if self.state == "wrong" and not (self.note and self.note.strip()):
            raise ValueError("a wrong review states why")
        return self


class RegionMemberDecided(StrictModel):
    """A human adds a member to a region or removes one; the latest decision per member binds."""

    region_id: str = Field(pattern=REGION_ID_RE)
    member_type: MemberType
    member: str = Field(pattern=r"^[^\s]+$")
    decision: Literal["add", "remove", "reject"]
    """`reject` closes a proposal and never changes membership."""
    note: str | None = Field(default=None, max_length=REVIEW_NOTE_MAX_CHARS)
    proposal_id: str | None = Field(default=None, pattern=PROPOSAL_ID_RE)
    """The proposal this decision answers, when it answers one."""


class QuoteBasis(StrictModel):
    """A verbatim quote of the candidate work, anchored in one of its conversions."""

    kind: Literal["quote"] = "quote"
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)]
    conversion_id: Annotated[str, StringConstraints(pattern=CONVERSION_ID_RE)]
    anchor: str
    quote: NonBlank

    @model_validator(mode="after")
    def _anchor_form(self) -> Self:
        anchor_form(self.anchor)
        return self


class EdgeBasis(StrictModel):
    """A live graph edge or concept use incident to the candidate and to a current member."""

    kind: Literal["edge"] = "edge"
    edge_id: str = Field(pattern=r"^[^\s]+$", max_length=200)


MemberBasis = Annotated[QuoteBasis | EdgeBasis, Field(discriminator="kind")]


class RegionMemberProposed(StrictModel):
    """An agent's (or anyone's) proposal of one member with a verified basis. It never enters a
    snapshot until a human adds the member; `note` is an agent note and is never counted."""

    proposal_id: str = Field(pattern=PROPOSAL_ID_RE)
    region_id: str = Field(pattern=REGION_ID_RE)
    member_type: MemberType
    member: str = Field(pattern=r"^[^\s]+$")
    basis: MemberBasis
    note: str | None = Field(default=None, max_length=PROPOSAL_NOTE_MAX_CHARS)


class RegionLinked(StrictModel):
    """A declared link between two pinned versions. `subregion-of` means source members are a
    subset of target members; `related` carries a note and no verification."""

    link_type: Literal["subregion-of", "related"]
    source: str = Field(pattern=REGION_VERSION_RE)
    target: str = Field(pattern=REGION_VERSION_RE)
    note: str | None = Field(default=None, max_length=REVIEW_NOTE_MAX_CHARS)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if self.source == self.target:
            raise ValueError("a link joins two different versions")
        return self
