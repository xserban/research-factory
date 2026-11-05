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

from pydantic import AfterValidator, ConfigDict, Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import CONVERSION_ID_RE, ULID_RE
from factory.model.references import ENTRY_KEY_RE
from factory.model.screening import Channel, NonBlank, anchor_form
from factory.model.work_ids import WORK_ID_RE

__all__ = [
    "CONCEPT_ID_RE",
    "CONCEPT_LINK_ID_RE",
    "CONCEPT_MAX_ALIASES",
    "CONCEPT_NAME_MAX",
    "ENTRY_KEY_RE",
    "INTERPRETATION_ID_RE",
    "INTERPRETATION_MAX_CHARS",
    "INTERPRETATION_MAX_SOURCES",
    "VERIFIER_VERSION",
    "Author",
    "CitationSourceInput",
    "ConceptBrief",
    "ConceptDefined",
    "ConceptHidden",
    "ConceptInput",
    "ConceptLinkDecided",
    "ConceptLinkProposed",
    "ConceptMerged",
    "ConceptReviewed",
    "ConceptSourceDecided",
    "ConceptSourceInput",
    "ConceptSourceKind",
    "ConceptState",
    "ConceptUnmerged",
    "HistoryEntry",
    "InterpretationHidden",
    "InterpretationInput",
    "InterpretationRecorded",
    "InterpretationReviewed",
    "LayerClass",
    "LayerCounts",
    "LayerEdge",
    "LayerGraph",
    "LayerHidden",
    "LayerNode",
    "LinkStatus",
    "QuoteSourceInput",
    "ReviewState",
    "SourceInput",
    "SourceRole",
    "SourceState",
    "StoredConceptSource",
    "StoredSource",
    "UseBasisInput",
]

INTERPRETATION_ID_RE = rf"^int_{ULID_RE}$"
CONCEPT_ID_RE = rf"^cpt_{ULID_RE}$"
CONCEPT_LINK_ID_RE = rf"^cul_{ULID_RE}$"
INTERPRETATION_MAX_CHARS = 600
INTERPRETATION_MAX_SOURCES = 5
CONCEPT_NAME_MAX = 120
CONCEPT_MAX_ALIASES = 10
CONCEPT_CITATION_MAX = 500
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
    kind: Literal["recorded", "reviewed", "superseded-by", "source-decided"]
    state: str | None
    actor: str
    note: str
    self_reviewed: bool
    folded: bool = True
    """False for a review the fold dropped (not a human, or the writer's own session): kept in the
    history, never counted in the state."""


# --- Background concepts (plan G3-B) ---


class ConceptSourceKind(StrEnum):
    TEXTBOOK = "textbook"
    SURVEY = "survey"
    CORPUS_PAPER = "corpus-paper"
    OTHER = "other"


class LinkStatus(StrEnum):
    STATED = "stated"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ConceptState(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    WRONG = "wrong"
    MERGED = "merged"


SourceState = Literal["none", "proposed", "approved", "rejected"]
_CONCEPT_ID = Annotated[str, StringConstraints(pattern=CONCEPT_ID_RE)]
_LINK_ID = Annotated[str, StringConstraints(pattern=CONCEPT_LINK_ID_RE)]


class ConceptSourceInput(StrictModel):
    """The first source of a concept as a human or an agent names it: kind, citation text and,
    when the source is a corpus work, its work id (required for `corpus-paper`)."""

    kind: ConceptSourceKind
    citation: Annotated[NonBlank, StringConstraints(max_length=CONCEPT_CITATION_MAX)]
    work_id: Annotated[str, StringConstraints(pattern=WORK_ID_RE)] | None = None

    @model_validator(mode="after")
    def _corpus_paper_has_work(self) -> Self:
        if self.kind is ConceptSourceKind.CORPUS_PAPER and self.work_id is None:
            raise ValueError("a corpus-paper source names its work_id")
        return self


class StoredConceptSource(ConceptSourceInput):
    """A concept source as the event stores it: `digest` binds an approval to it (ruling B1);
    `verifiable` is false without a work id (ruling B3)."""

    digest: str
    verifiable: bool


class ConceptInput(StrictModel):
    """A concept as an agent or a human states it; it cannot set a source or review state."""

    name: NonBlank
    aliases: tuple[NonBlank, ...] = ()
    text: str | None = None
    source: ConceptSourceInput | None = None
    quotes: tuple[QuoteSourceInput, ...] = ()
    concept_id: _CONCEPT_ID | None = None
    supersedes: str | None = None


class UseBasisInput(StrictModel):
    """The basis of a `uses` link: a quote of the citing work, or a reference entry, or neither."""

    quote: QuoteSourceInput | None = None
    reference: Annotated[str, StringConstraints(pattern=ENTRY_KEY_RE)] | None = None

    @model_validator(mode="after")
    def _at_most_one(self) -> Self:
        if self.quote is not None and self.reference is not None:
            raise ValueError("name at most one of quote and reference")
        return self


class ConceptDefined(StrictModel):
    concept_id: _CONCEPT_ID
    name: str
    aliases: tuple[str, ...]
    text: str | None
    source: StoredConceptSource | None
    quotes: tuple[StoredSource, ...]
    author: Author
    supersedes: str | None = None


class ConceptSourceDecided(StrictModel):
    concept_id: _CONCEPT_ID
    decision: Literal["approve", "reject"]
    source_digest: str
    note: str
    channel: Channel = Channel.CLI


class ConceptReviewed(StrictModel):
    concept_id: _CONCEPT_ID
    definition: str
    """The event id of the `concept.defined` that was reviewed."""
    state: Literal["reviewed", "wrong"]
    note: str
    self_reviewed: bool
    channel: Channel = Channel.CLI

    @model_validator(mode="after")
    def _wrong_needs_note(self) -> Self:
        if self.state == "wrong" and not self.note.strip():
            raise ValueError("a wrong review needs a note")
        return self


class ConceptLinkProposed(StrictModel):
    link_id: _LINK_ID
    from_node: str
    from_kind: Literal["paper", "idea", "concept"]
    concept_id: _CONCEPT_ID
    basis_kind: Literal["quote", "citation", "none"]
    quote: StoredSource | None = None
    reference: str | None = None
    cited_work: str | None = None
    basis_digest: str
    status: Literal["stated", "inferred"]
    status_reason: str
    note: str | None = None


class ConceptLinkDecided(StrictModel):
    link_id: _LINK_ID
    decision: Literal["confirm", "reject"]
    rationale: NonBlank
    channel: Channel = Channel.CLI


class ConceptMerged(StrictModel):
    into: _CONCEPT_ID
    from_concept: _CONCEPT_ID
    reason: NonBlank


class ConceptUnmerged(StrictModel):
    into: _CONCEPT_ID
    from_concept: _CONCEPT_ID
    reason: NonBlank


class ConceptHidden(StrictModel):
    """Concept items the default views hide, counted (spec ruling 7)."""

    unapproved: int
    wrong: int
    merged: int
    links_inferred: int
    links_rejected: int


class ConceptBrief(StrictModel):
    """A visible concept's name and aliases: what a writer needs to link and cite it."""

    concept_id: str
    name: str
    aliases: list[str]


# --- The visible layer (plan G3-C) ---


class _LayerModel(StrictModel):
    """Layer read models serialise `class_` as `class`, whichever model contains them."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, serialize_by_alias=True
    )


class LayerNode(_LayerModel):
    """A visible layer node. `class` is always `interpretation`; `label` ends in the review state;
    `flags` lists `source-stale`, `self-reviewed` and `unverifiable-source`."""

    node_id: str
    node_type: Literal["interpretation", "concept"]
    class_: str = Field(serialization_alias="class")
    review_state: str
    label: str
    name: str | None
    flags: list[str]


class LayerEdge(_LayerModel):
    edge_id: str
    edge_type: Literal["explains", "uses"]
    source: str
    target: str
    class_: str = Field(serialization_alias="class")
    review_state: str
    label: str
    basis: str | None


class LayerHidden(_LayerModel):
    """What the layer view hides, counted: interpretations (within the attached nodes), concepts
    and links (the whole layer) and `uses` edges dropped because an endpoint is hidden."""

    interpretations: InterpretationHidden
    concepts: ConceptHidden
    endpoint_hidden: int


class LayerGraph(_LayerModel):
    nodes: list[LayerNode]
    edges: list[LayerEdge]
    hidden: LayerHidden


class LayerCounts(_LayerModel):
    """The layer's own counts; there is no total across the evidence and the layer."""

    interpretations: dict[str, int]
    concepts: dict[str, int]
    explains: int
    uses: dict[str, int]
    hidden: LayerHidden
