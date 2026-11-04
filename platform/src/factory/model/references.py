"""Reference extraction, resolution and snowball rounds: value types and event payloads (slice 3a).

Invariants enforced here (validated at the boundary, before any event is written):
- No raw reference-entry text is stored (ruling 14). An entry carries its ordinal, anchor, printed
  label, the parsed fields (bounded: title <= 300, venue <= 200, first-author surname <= 100) and
  `entry_sha256`, the SHA-256 of the whitespace-normalised raw text; extra fields are refused, so
  a `text` field cannot be written. The raw text is re-derived from the pinned conversion.
- Entry ordinals run 1, 2, ... without gaps; anchors are unique and of the declared form (`b<n>`,
  or a paragraph anchor for `entry_anchors = paragraph`).
- A marker token is at most `MAX_MARKER` characters (ruling 9); a matched context names its entry,
  an unmatched or ambiguous one names none.
- Resolutions name each ordinal once, ascending; that they are entries of the extraction is checked
  by the service. `resolved` needs a work and an `identifier`/`title-exact` confidence;
  `unconfirmed` a work and `title-fuzzy`; `ambiguous` its candidates; `unresolved` no work and a
  reason. `confirmed` comes only from a decision.
- A binding decision (`confirm`, `reject`) names who confirmed; a proposal never does and quotes
  both the entry and the candidate. A confirmation names its work.
- A backward round goes via the document reference list and has no chase round; a forward round
  goes via source metadata and names the delegated chase round. Counts are never fields: the
  number of included works citing a candidate is derived from `cited_by`.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from factory.document.anchors import ANCHOR_RE
from factory.model.base import StrictModel
from factory.model.chase import CHASE_ROUND_ID_RE, WorkId
from factory.model.fulltext import DOCUMENT_ID_RE, Quality
from factory.model.identity import BLOB_REF_RE, CONVERSION_ID_RE, ULID_RE
from factory.model.protocol import SnowballPlan
from factory.model.screening import NonBlank
from factory.model.work import RUN_ID_RE
from factory.model.work_ids import WORK_ID_RE

REX_ID_RE = rf"^rex_{ULID_RE}$"
SNW_ID_RE = rf"^snw_{ULID_RE}$"
ENTRY_KEY_RE = rf"^rex_{ULID_RE}:[1-9]\d*$"
"""An entry key `rex_<ULID>:<ordinal>`: a candidate with no work id yet."""
SHA256_HEX_RE = r"^[0-9a-f]{64}$"
B_ANCHOR_RE = r"^b\d+$"
PARAGRAPH_ANCHOR_RE = r"^s\d+(?:\.\d+)*\.p\d+$"

MAX_TITLE = 300
MAX_VENUE = 200
MAX_SURNAME = 100
MAX_MARKER = 80
MAX_LABEL = 20
MAX_URL = 1000
MAX_DOI = 300
MAX_ARXIV = 40
MAX_QUOTE = 1000
MAX_RATIONALE = 2000
MAX_CANDIDATES = 3

Flag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]
Anchor = Annotated[str, StringConstraints(pattern=ANCHOR_RE.pattern)]
ExtractionId = Annotated[str, StringConstraints(pattern=REX_ID_RE)]
Ordinal = Annotated[int, Field(ge=1)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Method = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=40)]


class LinkState(StrEnum):
    RESOLVED = "resolved"
    UNCONFIRMED = "unconfirmed"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class Confidence(StrEnum):
    IDENTIFIER = "identifier"
    TITLE_EXACT = "title-exact"
    TITLE_FUZZY = "title-fuzzy"
    CONFIRMED = "confirmed"


class Decision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    PROPOSE_CONFIRM = "propose-confirm"
    PROPOSE_REJECT = "propose-reject"


BINDING_DECISIONS = frozenset({Decision.CONFIRM, Decision.REJECT})


class Direction(StrEnum):
    BACKWARD = "backward"
    FORWARD = "forward"


class Via(StrEnum):
    DOCUMENT_REFERENCE_LIST = "document-reference-list"
    SOURCE_METADATA = "source-metadata"


EntryAnchors = Literal["b", "paragraph"]
BblStatus = Literal["absent", "aligned", "count-mismatch"]
MarkerMethod = Literal["link", "numeric", "author-year"]
MarkerState = Literal["matched", "unmatched", "ambiguous"]
UnresolvedReason = Literal["no-identifier-no-title", "not-found", "source-error"]
ConfirmedBy = Literal["human", "second-agent"]


def _unique(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must not repeat an entry")


class ReferenceEntry(StrictModel):
    """One bibliography entry as stored: parsed fields and a hash, never the raw text."""

    ordinal: Ordinal
    anchor: Anchor
    label: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL)
    doi: str | None = Field(default=None, min_length=1, max_length=MAX_DOI)
    arxiv: str | None = Field(default=None, min_length=1, max_length=MAX_ARXIV)
    url: str | None = Field(default=None, min_length=1, max_length=MAX_URL)
    year: int | None = Field(default=None, ge=1900, le=2099)
    first_author: str | None = Field(default=None, min_length=1, max_length=MAX_SURNAME)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    venue: str | None = Field(default=None, min_length=1, max_length=MAX_VENUE)
    entry_sha256: str = Field(pattern=SHA256_HEX_RE)


class BblInfo(StrictModel):
    """The `.bbl` alignment: `absent` carries nothing; otherwise the archive and its entry count."""

    status: BblStatus
    archive_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    bbl_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.status == "absent":
            if self.archive_blob is not None or self.bbl_count is not None:
                raise ValueError("an absent bbl carries no archive and no count")
        elif self.archive_blob is None or self.bbl_count is None:
            raise ValueError("a read bbl names its archive and its entry count")
        return self


class CitationContext(StrictModel):
    """One marker occurrence: where it is, the entry it maps to (or none) and how."""

    citing_anchor: Anchor
    entry: Ordinal | None
    marker: str = Field(min_length=1, max_length=MAX_MARKER)
    method: MarkerMethod
    state: MarkerState

    @model_validator(mode="after")
    def _entry_iff_matched(self) -> Self:
        if (self.state == "matched") != (self.entry is not None):
            raise ValueError("a matched marker names its entry; any other names none")
        return self


class LinkCandidate(StrictModel):
    work_id: WorkId
    score: Score


class Resolution(StrictModel):
    """How one entry resolved. States follow the module invariants."""

    ordinal: Ordinal
    state: LinkState
    work_id: WorkId | None
    method: Method | None
    confidence: Confidence | None
    score: Score | None
    candidates: tuple[LinkCandidate, ...] = Field(default=(), max_length=MAX_CANDIDATES)
    source_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    reason: UnresolvedReason | None = None
    no_source_record: bool = False

    @model_validator(mode="after")
    def _state_shape(self) -> Self:
        if self.confidence is Confidence.CONFIRMED:
            raise ValueError("confidence 'confirmed' comes only from a decision")
        if self.state is not LinkState.UNRESOLVED and self.reason is not None:
            raise ValueError("only an unresolved link carries a reason")
        if self.no_source_record and self.state is not LinkState.RESOLVED:
            raise ValueError("a no-source-record work is only the target of a resolved link")
        if self.state is LinkState.RESOLVED:
            if self.work_id is None or self.confidence not in (
                Confidence.IDENTIFIER,
                Confidence.TITLE_EXACT,
            ):
                raise ValueError("a resolved link needs a work and an identifier/title-exact match")
        elif self.state is LinkState.UNCONFIRMED:
            if self.work_id is None or self.confidence is not Confidence.TITLE_FUZZY:
                raise ValueError("an unconfirmed link needs a work and a title-fuzzy match")
        elif self.state is LinkState.AMBIGUOUS:
            if not self.candidates:
                raise ValueError("an ambiguous link lists its candidates")
        elif self.work_id is not None or self.reason is None:
            raise ValueError("an unresolved link has no work and states a reason")
        return self


class DecisionQuote(StrictModel):
    """A verbatim quote (ruling 14a) of the entry or of the candidate's title/author line."""

    side: Literal["entry", "candidate"]
    text: str = Field(min_length=1, max_length=MAX_QUOTE)


class CitingEntry(StrictModel):
    """One source work's entry that cites a candidate, with the anchors that cite it."""

    work_id: WorkId
    extraction_id: ExtractionId
    ordinal: Ordinal
    anchors: tuple[Anchor, ...] = ()


class SnowballCandidate(StrictModel):
    work_key: str = Field(pattern=rf"(?:{WORK_ID_RE})|(?:{ENTRY_KEY_RE})")
    cited_by: tuple[CitingEntry, ...] = Field(min_length=1)
    no_source_record: bool = False


class Unextracted(StrictModel):
    work_id: WorkId
    reason: NonBlank


# --- Event payloads (schema 1). Written by `factory.services.references`,
# `factory.services.reference_resolve` and `factory.services.snowball`; folded by
# `factory.index.references`.


class ReferenceExtracted(StrictModel):
    extraction_id: ExtractionId
    work_id: WorkId
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    parser: NonBlank
    parser_version: NonBlank
    entry_anchors: EntryAnchors
    source_quality: Quality
    entries: tuple[ReferenceEntry, ...]
    marker_count: int = Field(ge=0)
    flags: tuple[Flag, ...]
    bbl: BblInfo

    @model_validator(mode="after")
    def _entries_shape(self) -> Self:
        if [e.ordinal for e in self.entries] != list(range(1, len(self.entries) + 1)):
            raise ValueError("entry ordinals must run 1, 2, ... without gaps")
        _unique(tuple(e.anchor for e in self.entries), "entry anchors")
        form = re.compile(B_ANCHOR_RE if self.entry_anchors == "b" else PARAGRAPH_ANCHOR_RE)
        if any(not form.match(e.anchor) for e in self.entries):
            raise ValueError(f"entry anchors must have the {self.entry_anchors!r} form")
        _unique(self.flags, "flags")
        count = self.bbl.bbl_count
        if self.bbl.status == "aligned" and count != len(self.entries):
            raise ValueError("an aligned bbl has as many entries as the bibliography")
        if self.bbl.status == "count-mismatch" and count == len(self.entries):
            raise ValueError("a count mismatch has a different bbl entry count")
        return self


class CitationContextsRecorded(StrictModel):
    extraction_id: ExtractionId
    contexts: tuple[CitationContext, ...]


class ReferenceResolved(StrictModel):
    extraction_id: ExtractionId
    resolutions: tuple[Resolution, ...]
    matcher_version: NonBlank
    lookup_runs: tuple[Annotated[str, StringConstraints(pattern=RUN_ID_RE)], ...] = ()

    @model_validator(mode="after")
    def _ordinals(self) -> Self:
        ordinals = [r.ordinal for r in self.resolutions]
        if ordinals != sorted(set(ordinals)):
            raise ValueError("resolutions name each ordinal once, in ascending order")
        _unique(self.lookup_runs, "lookup_runs")
        return self


class ReferenceResolutionDecided(StrictModel):
    """A decision on one link; it supersedes the previous decision for the entry."""

    extraction_id: ExtractionId
    ordinal: Ordinal
    decision: Decision
    work_id: WorkId | None
    rationale: Annotated[NonBlank, Field(max_length=MAX_RATIONALE)]
    quotes: tuple[DecisionQuote, ...] = Field(default=(), max_length=2)
    confirmed_by: ConfirmedBy | None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        sides = [q.side for q in self.quotes]
        _unique(tuple(sides), "quote sides")
        if self.decision in BINDING_DECISIONS:
            if self.confirmed_by is None:
                raise ValueError("a binding decision names who confirmed it")
        else:
            if self.confirmed_by is not None:
                raise ValueError("a proposal is never a confirmation")
            if sorted(sides) != ["candidate", "entry"]:
                raise ValueError("a proposal quotes both the entry and the candidate")
        if self.decision in (Decision.CONFIRM, Decision.PROPOSE_CONFIRM) and self.work_id is None:
            raise ValueError("a confirmation names its work")
        return self


class SnowballRoundStarted(StrictModel):
    round_id: str = Field(pattern=SNW_ID_RE)
    direction: Direction
    via: Via
    round_no: int = Field(ge=1)
    sources: tuple[WorkId, ...]
    extraction_ids: tuple[ExtractionId, ...]
    candidates: tuple[SnowballCandidate, ...]
    queries: tuple[NonBlank, ...]
    chase_round_id: str | None = Field(default=None, pattern=CHASE_ROUND_ID_RE)
    rule: SnowballPlan | Literal["none"]
    unextracted: tuple[Unextracted, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.direction is Direction.BACKWARD:
            if self.via is not Via.DOCUMENT_REFERENCE_LIST or self.chase_round_id is not None:
                raise ValueError("a backward round goes via the reference list, without a chase")
        elif self.via is not Via.SOURCE_METADATA or self.chase_round_id is None:
            raise ValueError("a forward round goes via source metadata and names its chase round")
        _unique(self.sources, "sources")
        _unique(self.extraction_ids, "extraction_ids")
        _unique(tuple(c.work_key for c in self.candidates), "candidate work keys")
        _unique(tuple(u.work_id for u in self.unextracted), "unextracted")
        sources = set(self.sources)
        for candidate in self.candidates:
            if any(c.work_id not in sources for c in candidate.cited_by):
                raise ValueError("a candidate is cited only by the round's source works")
        return self
