"""Interpretations of the intuition layer: value types and event payloads (slice 3c, G3-A).

Invariants:
- An interpretation is source-bound: its input carries 1 to 5 sources, each a verified quote of a
  pinned conversion or a citation (a G1 reference entry or a corpus work). The models here check
  shape only (types, patterns, the discriminator, exactly one citation locator); the bounds on
  the text and the number of sources are `factory.intuition.validate`'s, so one function reports
  every problem together.
- The writer never sets a review state: `InterpretationInput` has no state field and refuses one.
  Only `reviewed` and `wrong` are reviewable states; `superseded` is the platform's.
- The layer class is `interpretation`; nothing here is evidence.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import CONVERSION_ID_RE, ULID_RE
from factory.model.references import ENTRY_KEY_RE
from factory.model.screening import Channel, NonBlank, anchor_form
from factory.model.work_ids import WORK_ID_RE

__all__ = [
    "CONCEPT_ID_RE",
    "CONCEPT_LINK_ID_RE",
    "ENTRY_KEY_RE",
    "INTERPRETATION_ID_RE",
    "INTERPRETATION_MAX_CHARS",
    "INTERPRETATION_MAX_SOURCES",
    "VERIFIER_VERSION",
    "Author",
    "CitationSourceInput",
    "HistoryEntry",
    "InterpretationHidden",
    "InterpretationInput",
    "InterpretationRecorded",
    "InterpretationReviewed",
    "LayerClass",
    "QuoteSourceInput",
    "ReviewState",
    "SourceInput",
    "SourceRole",
    "StoredSource",
]

INTERPRETATION_ID_RE = rf"^int_{ULID_RE}$"
CONCEPT_ID_RE = rf"^cpt_{ULID_RE}$"
CONCEPT_LINK_ID_RE = rf"^cul_{ULID_RE}$"
INTERPRETATION_MAX_CHARS = 600
INTERPRETATION_MAX_SOURCES = 5
VERIFIER_VERSION = 1
"""Bumped when the source checks change, so a stored verdict names the rules that made it."""

_DOCUMENT_ANCHOR = Annotated[str, AfterValidator(lambda v: anchor_form(v) or v)]


class LayerClass(StrEnum):
    EVIDENCE = "evidence"
    INTERPRETATION = "interpretation"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    WRONG = "wrong"
    SUPERSEDED = "superseded"


class Author(StrEnum):
    AGENT = "agent"
    HUMAN = "human"


class SourceRole(StrEnum):
    SUPPORTS = "supports"
    BACKGROUND = "background"


class QuoteSourceInput(StrictModel):
    kind: Literal["quote"]
    role: SourceRole
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)]
    conversion_id: Annotated[str, StringConstraints(pattern=CONVERSION_ID_RE)]
    anchor: _DOCUMENT_ANCHOR
    quote: NonBlank


class CitationSourceInput(StrictModel):
    kind: Literal["citation"]
    role: SourceRole
    reference: Annotated[str, StringConstraints(pattern=ENTRY_KEY_RE)] | None = None
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)] | None = None

    @model_validator(mode="after")
    def _one_locator(self) -> Self:
        if (self.reference is None) == (self.work_id is None):
            raise ValueError("name exactly one of reference and work_id")
        return self


SourceInput = Annotated[QuoteSourceInput | CitationSourceInput, Field(discriminator="kind")]


class StoredSource(StrictModel):
    """A verified source as the event stores it: the input fields plus what the platform
    computed (`document_id` of a quote's conversion; the link state and resolved work of a
    cited reference entry)."""

    kind: Literal["quote", "citation"]
    role: SourceRole
    work_id: str | None = None
    conversion_id: str | None = None
    anchor: str | None = None
    quote: str | None = None
    reference: str | None = None
    document_id: str | None = None
    link_state: str | None = None
    resolved_work: str | None = None


class InterpretationInput(StrictModel):
    """An interpretation as an agent or a human states it; it cannot set a review state."""

    target: str
    text: str
    sources: tuple[SourceInput, ...]
    supersedes: Annotated[str, StringConstraints(pattern=INTERPRETATION_ID_RE)] | None = None


class InterpretationRecorded(StrictModel):
    interpretation_id: Annotated[str, StringConstraints(pattern=INTERPRETATION_ID_RE)]
    target: str
    target_kind: Literal["idea", "paper"]
    text: str
    sources: tuple[StoredSource, ...]
    author: Author
    supersedes: Annotated[str, StringConstraints(pattern=INTERPRETATION_ID_RE)] | None = None
    task_id: str | None = None
    verifier: int = VERIFIER_VERSION


class InterpretationReviewed(StrictModel):
    interpretation_id: Annotated[str, StringConstraints(pattern=INTERPRETATION_ID_RE)]
    state: Literal["reviewed", "wrong"]
    note: str
    self_reviewed: bool
    channel: Channel = Channel.CLI
    """`mcp` for a human answer relayed by an agent session; that session may never join a pass
    (decision 37 item 6)."""


class InterpretationHidden(StrictModel):
    """Items the default view hides, counted (spec ruling 7)."""

    wrong: int
    superseded: int


class HistoryEntry(StrictModel):
    """One step of an item's history (interpretation or concept definition)."""

    event_id: str
    kind: Literal["recorded", "reviewed", "superseded-by"]
    state: str | None
    actor: str
    note: str
    self_reviewed: bool
    folded: bool = True
    """False for a review the fold dropped (not a human, or the writer's own session): kept in the
    history, never counted in the state."""
