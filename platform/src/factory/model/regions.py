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
from typing import Literal, Self

from pydantic import Field, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.question import QUESTION_ID_RE
from factory.regions.rules import REGION_VERSION_RE, MemberType, RuleSet

REGION_ID_RE = rf"^reg_{ULID_RE}$"
EVENT_ID_PATTERN = rf"^ev_{ULID_RE}$"
REGION_DEFINITION_MAX_CHARS = 600
REGION_NAME_MAX_CHARS = 120
REVIEW_NOTE_MAX_CHARS = 600


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
    member: str = Field(min_length=1)
    decision: Literal["add", "remove"]
    note: str | None = Field(default=None, max_length=REVIEW_NOTE_MAX_CHARS)
