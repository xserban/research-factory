"""Event payloads of free labels, terms and consolidation (slice 3d, plan Regions-C).

Invariants:
- Labels, terms and consolidation rows are organisation class: they never select evidence and
  never enter the graph or layer tables.
- A label key is `label_key(text)`: NFKC, case-folded, whitespace collapsed, 1 to 60 characters,
  no control characters. The key in an event is always recomputed from its text by the validator.
- The platform computes an application's `status`; no actor types it.
- A term is a promoted label key; its keys (name and aliases) are label keys.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.cards import QuoteBasis
from factory.model.identity import ULID_RE
from factory.model.regions import EVENT_ID_PATTERN
from factory.model.screening import NonBlank
from factory.regions.rules import MemberType

LABEL_ID_RE = rf"^lbl_{ULID_RE}$"
TERM_ID_RE = rf"^trm_{ULID_RE}$"
PASS_ID_RE = rf"^cns_{ULID_RE}$"
PROPOSAL_ID_RE = rf"^cnp_{ULID_RE}$"
LABEL_MAX_CHARS = 60
TERM_DEFINITION_MAX_CHARS = 600
REASON_MAX_CHARS = 600
TERM_MAX_ALIASES = 30

Reason = Annotated[NonBlank, StringConstraints(max_length=REASON_MAX_CHARS)]
Origin = Literal["agent", "human", "import-tag"]
AppStatus = Literal["confirmed", "stated", "inferred"]


def label_key(text: str) -> str:
    """The key of a label text. Not validated: see `key_problem`."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def key_problem(text: str) -> str | None:
    """Why `text` is not a label, or None: blank or over 60 characters once normalised, or a
    control character."""
    if any(unicodedata.category(ch).startswith("C") for ch in text):
        return "control-character"
    key = label_key(text)
    if not key:
        return "blank"
    if len(key) > LABEL_MAX_CHARS:
        return f"over-{LABEL_MAX_CHARS}-characters"
    return None


def _checked_key(text: str) -> str:
    problem = key_problem(text)
    if problem is not None:
        raise ValueError(f"not a label: {problem}")
    return label_key(text)


class LabelApplied(StrictModel):
    application_id: str = Field(pattern=LABEL_ID_RE)
    target_type: MemberType
    target: str = Field(pattern=r"^[^\s]+$")
    text: str
    key: str
    quote: QuoteBasis | None = None
    status: AppStatus
    origin: Origin
    import_ref: str | None = None

    @model_validator(mode="after")
    def _key_from_text(self) -> Self:
        if self.key != _checked_key(self.text):
            raise ValueError("key must be the label key of text")
        return self


class LabelWithdrawn(StrictModel):
    application_id: str = Field(pattern=LABEL_ID_RE)
    reason: Reason


class LabelApplicationDecided(StrictModel):
    """A human confirms or rejects an application (gate `labels.application_confirm`)."""

    application_id: str = Field(pattern=LABEL_ID_RE)
    decision: Literal["confirm", "reject"]


class LabelMerged(StrictModel):
    """`from_key` now reads as `into_key` (a reversible alias, never an edit of applications)."""

    into_key: str
    from_key: str
    reason: Reason
    proposal_id: str | None = Field(default=None, pattern=PROPOSAL_ID_RE)

    @model_validator(mode="after")
    def _keys(self) -> Self:
        for key in (self.into_key, self.from_key):
            if key != _checked_key(key):
                raise ValueError("a merge names label keys")
        if self.into_key == self.from_key:
            raise ValueError("a label cannot be merged into itself")
        return self


class LabelUnmerged(StrictModel):
    merge_event: str = Field(pattern=EVENT_ID_PATTERN)
    reason: Reason


class TermPromoted(StrictModel):
    term_id: str = Field(pattern=TERM_ID_RE)
    name: str
    aliases: tuple[str, ...] = ()
    definition: Annotated[NonBlank, StringConstraints(max_length=TERM_DEFINITION_MAX_CHARS)]
    applies_to: tuple[MemberType, ...] = Field(min_length=1)
    refers_to: str | None = Field(default=None, pattern=r"^[^\s]+$")
    from_keys: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _keys(self) -> Self:
        _checked_key(self.name)
        keys = [_checked_key(a) for a in self.aliases]
        if len(keys) > TERM_MAX_ALIASES:
            raise ValueError(f"at most {TERM_MAX_ALIASES} aliases")
        if label_key(self.name) in keys or len(set(keys)) != len(keys):
            raise ValueError("aliases are distinct from the name and from each other")
        if len(set(self.applies_to)) != len(self.applies_to):
            raise ValueError("applies_to lists each type once")
        return self


class TermRevised(TermPromoted):
    supersedes: str = Field(pattern=EVENT_ID_PATTERN)


class TermRetired(StrictModel):
    term_id: str = Field(pattern=TERM_ID_RE)
    reason: Reason


class ConsolidationPassStarted(StrictModel):
    pass_id: str = Field(pattern=PASS_ID_RE)
    clusters_blob: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    constants: dict[str, float | int]
    counts: dict[str, int]


class ConsolidationProposed(StrictModel):
    proposal_id: str = Field(pattern=PROPOSAL_ID_RE)
    pass_id: str = Field(pattern=PASS_ID_RE)
    cluster_index: int = Field(ge=0)
    action: Literal["merge", "keep", "split"]
    into: str | None = None
    members: tuple[str, ...] = ()
    reason: Reason
    quotes: tuple[QuoteBasis, ...] = ()

    @model_validator(mode="after")
    def _merge_names_into(self) -> Self:
        if self.action == "merge" and (self.into is None or self.into not in self.members):
            raise ValueError("a merge names `into`, one of its members")
        if self.action != "merge" and self.into is not None:
            raise ValueError("only a merge names `into`")
        return self


class ConsolidationDecided(StrictModel):
    pass_id: str = Field(pattern=PASS_ID_RE)
    cluster_index: int = Field(ge=0)
    decision: Literal["merge", "keep", "split", "skip"]
    merge_events: tuple[str, ...] = ()
    reason: Reason
    proposal_id: str | None = Field(default=None, pattern=PROPOSAL_ID_RE)


class ConsolidationPassCompleted(StrictModel):
    pass_id: str = Field(pattern=PASS_ID_RE)
