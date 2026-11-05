"""Drafts, sentences, supports and their events (slice 7b, plan W-A).

Invariants (validated at the boundary, before any event is written):
- A sentence carries one class, at most `MAX_SUPPORTS` typed supports and at most
  `SENTENCE_MAX_CHARS` characters. A `structural` sentence has no support.
- A support is a typed reference in the grammar of `parse_support`; the canonical form of a cell
  always names its field (`rk_...` alone means the field `value`).
- No `draft.sentence_recorded` carries quote text: supports are ids, and quotes are read from
  extraction events when a slot is served or a draft rendered. The outline blob holds ids only. A
  verdict names the substrings it relies on (spec, Events); they are already in those events.
- No input model carries a flag, a status or a stat value: the platform computes them.

This module is pure. Services in `factory.services` decide when the events are written.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from factory.model.base import StrictModel
from factory.model.extraction import CLAIM_ID_RE, EXTRACTION_ID_RE, ROW_KEY_RE
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.references import REX_ID_RE
from factory.model.task import TASK_ID_RE

DRAFT_ID_RE = rf"^drf_{ULID_RE}$"
SENTENCE_ID_RE = rf"^snt_{ULID_RE}$"
OUTLINE_ID_RE = r"^OL@[0-9a-f]{8}$"
SECTION_ID_RE = r"^sec_[0-9]{2}$"
GROUP_ID_RE = r"^grp_[0-9a-f]{12}$"
RELATION_ID_RE = rf"^rel_{ULID_RE}$"
INTERPRETATION_ID_RE = rf"^int_{ULID_RE}$"
CONCEPT_ID_RE = rf"^cpt_{ULID_RE}$"
SENTENCE_MAX_CHARS = 400
MAX_SUPPORTS = 6
MAX_TITLE = 200
MAX_HEADING = 200
MAX_REASON = 300
MAX_ORDER = 2**63 - 1
"""The largest sentence order and stat value: what the index's integer columns hold."""
VERDICT_ID_RE = rf"^svd_{ULID_RE}$"
NOTE_MAX_CHARS = 300
_FIELD_RE = r"^[a-z][a-z0-9_]*$"
_CITES_RE = rf"^cit:{REX_ID_RE[1:-1]}:[1-9][0-9]*$"
_STAT_RE = r"^[a-z][a-z-]*(?::[A-Za-z0-9_.-]+){0,2}$"


class SentenceClass(StrEnum):
    CLAIM = "claim"
    SYNTHESIS = "synthesis"
    INTERPRETIVE = "interpretive"
    STRUCTURAL = "structural"


class DraftKind(StrEnum):
    RELATED_WORK = "related-work"
    REVIEW = "review"
    GRANT_BACKGROUND = "grant-background"
    HORIZON_NOTE = "horizon-note"
    OTHER = "other"


class SupportKind(StrEnum):
    CLAIM = "claim"
    CELL = "cell"
    ITEM = "item"
    EDGE = "edge"
    GROUP = "group"
    STAT = "stat"
    INTERP = "interp"


class SentenceFlag(StrEnum):
    CITATION_MISMATCH = "citation-mismatch"
    QUANTIFIER_WITHOUT_STATISTIC = "quantifier-without-statistic"
    CROSS_GROUP = "cross-group"
    SINGLE_SOURCE_GENERALISATION = "single-source-generalisation"
    OFF_OUTLINE = "off-outline"


class Verdict(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    OVERSTATED = "overstated"


def _ref_ok(kind: SupportKind, ref: str) -> bool:
    if kind is SupportKind.CLAIM:
        return re.fullmatch(CLAIM_ID_RE, ref) is not None
    if kind is SupportKind.CELL:
        row, sep, field = ref.partition("/")
        return (
            bool(sep)
            and re.fullmatch(ROW_KEY_RE, row) is not None
            and re.fullmatch(_FIELD_RE, field) is not None
        )
    if kind is SupportKind.ITEM:
        return re.fullmatch(EXTRACTION_ID_RE, ref) is not None
    if kind is SupportKind.EDGE:
        return (
            re.fullmatch(RELATION_ID_RE, ref) is not None
            or re.fullmatch(_CITES_RE, ref) is not None
        )
    if kind is SupportKind.GROUP:
        return re.fullmatch(GROUP_ID_RE, ref) is not None
    if kind is SupportKind.STAT:
        return re.fullmatch(_STAT_RE, ref) is not None
    return (
        re.fullmatch(INTERPRETATION_ID_RE, ref) is not None
        or re.fullmatch(CONCEPT_ID_RE, ref) is not None
    )


class SupportRef(StrictModel):
    """A typed support. `ref` is canonical: `clm_...`, `rk_.../<field>`, `ext_...`, `rel_...` or
    `cit:rex_...:<n>`, `grp_...`, `<stat kind>[:<arg>[:<arg>]]`, `int_...` or `cpt_...`."""

    kind: SupportKind
    ref: str

    @model_validator(mode="after")
    def _ref_has_the_shape_of_its_kind(self) -> Self:
        if not _ref_ok(self.kind, self.ref):
            raise ValueError(f"not a {self.kind.value} support reference")
        return self

    @property
    def text(self) -> str:
        """The grammar form, `<kind>:<ref>`."""
        return f"{self.kind.value}:{self.ref}"


def parse_support(text: str) -> SupportRef:
    """Parse the grammar form of a support. A bare `rk_...` is the cell `rk_.../value`; a bare id
    of another kind is not accepted. Raises `ValueError` on anything else."""
    if re.fullmatch(ROW_KEY_RE, text):
        return SupportRef(kind=SupportKind.CELL, ref=f"{text}/value")
    head, sep, rest = text.partition(":")
    if not sep:
        raise ValueError("a support is <kind>:<reference>")
    try:
        kind = SupportKind(head)
    except ValueError:
        raise ValueError(f"unknown support kind {head!r}") from None
    if kind is SupportKind.CELL and re.fullmatch(ROW_KEY_RE, rest):
        rest = f"{rest}/value"
    try:
        return SupportRef(kind=kind, ref=rest)
    except ValueError:
        raise ValueError(f"not a valid {kind.value} support") from None


# --- Outline (ids only) ---


class OutlineSection(StrictModel):
    """One slot of the outline. `kind` is `idea`, `group`, `claims` or `limits`; `title_ref` the
    id (idea or group) or the claim type or `limits` it is built from; `supports` canonical
    support texts (ids); `conflicts` lists of cell supports whose values disagree; `notes` fixed
    platform codes, never prose."""

    section_ref: str
    kind: Literal["idea", "group", "claims", "limits"]
    title_ref: str
    works: list[str]
    supports: list[str]
    conflicts: list[list[str]]
    notes: list[str]


class Outline(StrictModel):
    outline_id: str = Field(pattern=OUTLINE_ID_RE)
    scope: dict[str, JsonValue]
    as_of: str | None
    sections: list[OutlineSection]


def outline_id_of(scope: dict[str, JsonValue], sections: Sequence[OutlineSection]) -> str:
    """`OL@` and the first 8 hex digits of the sha256 of the canonical JSON of the scope and the
    sections. The log position (`as_of`) is not part of it: an unrelated event leaves the id."""
    payload = {"scope": scope, "sections": [s.model_dump(mode="json") for s in sections]}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "OL@" + hashlib.sha256(blob.encode()).hexdigest()[:8]


# --- Events ---


class SectionDef(StrictModel):
    section_id: str = Field(pattern=SECTION_ID_RE)
    heading: str = Field(min_length=1, max_length=MAX_HEADING)
    outline_section: str | None = None


class DraftCreated(StrictModel):
    draft_id: str = Field(pattern=DRAFT_ID_RE)
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    kind: DraftKind
    outline_ref: str = Field(pattern=OUTLINE_ID_RE)
    outline_blob: str = Field(pattern=BLOB_REF_RE)
    sections: list[SectionDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _sections_are_distinct(self) -> Self:
        ids = [s.section_id for s in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError("section ids must be distinct")
        return self


class DraftOutlineRepinned(StrictModel):
    draft_id: str = Field(pattern=DRAFT_ID_RE)
    outline_ref: str = Field(pattern=OUTLINE_ID_RE)
    outline_blob: str = Field(pattern=BLOB_REF_RE)


class SentenceRecorded(StrictModel):
    sentence_id: str = Field(pattern=SENTENCE_ID_RE)
    draft_id: str = Field(pattern=DRAFT_ID_RE)
    section_id: str = Field(pattern=SECTION_ID_RE)
    order: int = Field(ge=0, le=MAX_ORDER)
    cls: SentenceClass
    text: str = Field(min_length=1, max_length=SENTENCE_MAX_CHARS)
    supports: list[SupportRef] = Field(default_factory=list, max_length=MAX_SUPPORTS)
    stat_values: dict[str, Annotated[int, Field(ge=0, le=MAX_ORDER)]] = Field(default_factory=dict)
    stats_version: int = Field(ge=1)
    flags: list[SentenceFlag] = Field(default_factory=list)
    author: Literal["agent", "human"]
    task_id: str | None = Field(default=None, pattern=TASK_ID_RE)
    supersedes: str | None = Field(default=None, pattern=SENTENCE_ID_RE)

    @field_validator("text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a sentence is not blank")
        return value

    @model_validator(mode="after")
    def _classes_and_supports_agree(self) -> Self:
        if self.cls is SentenceClass.STRUCTURAL and self.supports:
            raise ValueError("a structural sentence has no support")
        if len({s.text for s in self.supports}) != len(self.supports):
            raise ValueError("supports must be distinct")
        if any(s.kind is SupportKind.INTERP for s in self.supports) and (
            self.cls is not SentenceClass.INTERPRETIVE
        ):
            raise ValueError("an interpretation supports an interpretive sentence only")
        stats = {s.ref for s in self.supports if s.kind is SupportKind.STAT}
        if set(self.stat_values) != stats:
            raise ValueError("stat_values must hold exactly the stat supports")
        return self


class SentenceWithdrawn(StrictModel):
    sentence_id: str = Field(pattern=SENTENCE_ID_RE)
    reason: str = Field(min_length=1, max_length=MAX_REASON)


class DraftReordered(StrictModel):
    draft_id: str = Field(pattern=DRAFT_ID_RE)
    section_id: str = Field(pattern=SECTION_ID_RE)
    order: list[str]

    @field_validator("order")
    @classmethod
    def _order_is_sentence_ids(cls, value: list[str]) -> list[str]:
        if any(re.fullmatch(SENTENCE_ID_RE, v) is None for v in value) or (
            len(set(value)) != len(value)
        ):
            raise ValueError("order lists distinct sentence ids")
        return value


class SupportSpan(StrictModel):
    """The substring of one support's span a verdict relies on; `ref` is the grammar form."""

    ref: str
    substring: str = Field(min_length=1)


class SentenceVerified(StrictModel):
    """One verdict on one sentence. Every verdict but `supported` names the sentence part it
    judges; every verdict but `unsupported` names at least one support substring."""

    verdict_id: str = Field(pattern=VERDICT_ID_RE)
    sentence_id: str = Field(pattern=SENTENCE_ID_RE)
    verdict: Verdict
    sentence_span: str | None = None
    support_spans: list[SupportSpan] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)
