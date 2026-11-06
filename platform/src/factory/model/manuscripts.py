"""External manuscripts: identifiers, events and read models (slice 7b, plan W-C).

Invariants:
- No event here holds a manuscript's text: a sentence is its ordinal, offsets and sha256, and a key
  is one bounded token. `label` is the researcher's own free text, bounded at `MAX_LABEL`.
- Every integer an event carries is bounded here, so the fold cannot overflow a column.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from factory.model.base import StrictModel
from factory.model.drafts import NOTE_MAX_CHARS, AuditLabel, DraftAuditReport, Verdict
from factory.model.identity import BLOB_REF_RE, CONVERSION_ID_RE, ULID_RE
from factory.model.references import MAX_QUOTE
from factory.model.screening import Channel
from factory.model.work_ids import WORK_ID_RE

MANUSCRIPT_ID_RE = rf"^msc_{ULID_RE}$"
MANUSCRIPT_VERDICT_ID_RE = rf"^mvd_{ULID_RE}$"
MANUSCRIPT_AUDIT_ID_RE = rf"^mau_{ULID_RE}$"
ANCHOR_RE = r"^[^/\s]{1,200}$"
MAX_CONTEXT = 3
"""The most preceding sentences `manuscript_read` serves."""
MIN_ECHO = 20
"""A note sharing a run this long with the manuscript is refused: it would copy text into an
event."""
MAX_KEY = 120
"""The longest citation key; `writing.cites` replaces anything else by a digest."""
KEY_RE = rf"^\S{{1,{MAX_KEY}}}$"
MAX_LABEL = 80
MAX_MANUSCRIPT_BYTES = 20_000_000
MAX_SENTENCES = 100_000
MAX_KEYS = 200
"""The most keys one sentence holds; the longest numeric range stays within it."""
MAX_OFFSET = MAX_MANUSCRIPT_BYTES
"""No offset exceeds the stored size: a character is at least one byte."""
MAX_SEGMENTER = 2**31 - 1
SHA256_RE = r"^[0-9a-f]{64}$"

Key = Annotated[str, Field(pattern=KEY_RE)]


class ManuscriptFormat(StrEnum):
    MARKDOWN = "markdown"
    LATEX = "latex"
    TEXT = "text"


class BibFormat(StrEnum):
    BIBTEX = "bibtex"
    CSL = "csl"


class CitationState(StrEnum):
    """`proposed` waits for a human and makes no unit (plan ruling 3)."""

    RESOLVED = "resolved"
    PROPOSED = "proposed"
    UNRESOLVED = "unresolved"


class CitationMethod(StrEnum):
    """How a key was matched, or why it was not."""

    IDENTIFIER = "identifier"
    TITLE_EXACT = "title-exact"
    TITLE_FUZZY = "title-fuzzy"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no-match"
    NO_TITLE = "no-title"
    NO_RECORD = "no-record"


class CitationDecision(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    CLEAR = "clear"
    """Withdraw an earlier decision; the next resolution matches the key afresh."""


class CloseReason(StrEnum):
    """Why the platform closed a unit as `cannot-verify` (plan ruling 4)."""

    CITATION_UNRESOLVED = "citation-unresolved"
    NO_FULL_TEXT = "no-full-text"
    SOURCE_NOT_IN_CORPUS = "source-not-in-corpus"


# --- Events ---


class ManuscriptAdded(StrictModel):
    """A manuscript stored in the library by its hash; `bib_hash` is its companion bibliography."""

    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    library_hash: str = Field(pattern=BLOB_REF_RE)
    format: ManuscriptFormat
    bib_hash: str | None = Field(default=None, pattern=BLOB_REF_RE)
    bib_format: BibFormat | None = None
    label: str = Field(min_length=1, max_length=MAX_LABEL)
    segmenter: int = Field(ge=1, le=MAX_SEGMENTER)

    @field_validator("label")
    @classmethod
    def _label_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a label is not blank")
        return value

    @model_validator(mode="after")
    def _bib_is_whole(self) -> Self:
        if (self.bib_hash is None) != (self.bib_format is None):
            raise ValueError("a bibliography has a hash and a format")
        return self


class SentenceEntry(StrictModel):
    """One sentence, by position and hash. `end` is exclusive."""

    ordinal: int = Field(ge=1, le=MAX_SENTENCES)
    start: int = Field(ge=0, le=MAX_OFFSET)
    end: int = Field(ge=1, le=MAX_OFFSET)
    sha256: str = Field(pattern=SHA256_RE)
    keys: list[Key] = Field(default_factory=list, max_length=MAX_KEYS)

    @model_validator(mode="after")
    def _is_a_span(self) -> Self:
        if self.start >= self.end:
            raise ValueError("a sentence is not empty")
        if len(set(self.keys)) != len(self.keys):
            raise ValueError("keys are distinct")
        return self


class ManuscriptSegmented(StrictModel):
    """The sentences of a manuscript, numbered from 1, in order and not overlapping."""

    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    segmenter: int = Field(ge=1, le=MAX_SEGMENTER)
    sentences: list[SentenceEntry] = Field(min_length=1, max_length=MAX_SENTENCES)

    @model_validator(mode="after")
    def _is_in_order(self) -> Self:
        last = 0
        for i, sentence in enumerate(self.sentences, start=1):
            if sentence.ordinal != i or sentence.start < last:
                raise ValueError("sentences are numbered from 1, in order, without overlap")
            last = sentence.end
        return self


class CitationResolved(StrictModel):
    """What a key resolves to, computed. A confirmed fuzzy citation keeps `title-fuzzy`; only the
    fold can tell it from one no human saw."""

    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    key: Key
    work_id: str | None = Field(default=None, pattern=WORK_ID_RE)
    method: CitationMethod
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    state: CitationState

    @model_validator(mode="after")
    def _work_follows_the_state(self) -> Self:
        if (self.work_id is None) != (self.state is CitationState.UNRESOLVED):
            raise ValueError("only an unresolved citation has no work")
        return self


class CitationDecided(StrictModel):
    """A human's decision on a `proposed` citation, or the withdrawal of one (`clear`), which
    supersedes it."""

    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    key: Key
    decision: CitationDecision


class UnitClosed(StrictModel):
    """A sentence's citation of `key` closed as `cannot-verify`; `work_id` is None exactly when
    the key is unresolved."""

    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    ordinal: int = Field(ge=1, le=MAX_SENTENCES)
    key: Key
    work_id: str | None = Field(default=None, pattern=WORK_ID_RE)
    reason: CloseReason

    @model_validator(mode="after")
    def _work_follows_the_reason(self) -> Self:
        if (self.work_id is None) != (self.reason is CloseReason.CITATION_UNRESOLVED):
            raise ValueError("only an unresolved key closes without a work")
        return self


Offset = Annotated[int, Field(ge=0, le=MAX_OFFSET)]


class ManuscriptVerified(StrictModel):
    """A verifier's verdict on a unit, or with `uncited_flag` its advisory flag on an uncited
    sentence, which carries no verdict and is never counted as one (plan ruling 5).

    `sentence_span` is a pair of offsets into the sentence, never its text. Every verdict but
    `supported` names one; every verdict but `unsupported` has a quote, from the anchor of the
    conversion it names."""

    verdict_id: str = Field(pattern=MANUSCRIPT_VERDICT_ID_RE)
    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    ordinal: int = Field(ge=1, le=MAX_SENTENCES)
    work_id: str | None = Field(default=None, pattern=WORK_ID_RE)
    verdict: Verdict | None = None
    sentence_span: tuple[Offset, Offset] | None = None
    anchor: str | None = Field(default=None, pattern=ANCHOR_RE)
    quote: str | None = Field(default=None, min_length=1, max_length=MAX_QUOTE)
    conversion_id: str | None = Field(default=None, pattern=CONVERSION_ID_RE)
    note: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)
    uncited_flag: bool = False

    @model_validator(mode="after")
    def _is_a_verdict_or_a_flag(self) -> Self:
        said = (self.work_id, self.verdict, self.conversion_id)
        if self.uncited_flag:
            if any(v is not None for v in (*said, self.sentence_span, self.anchor, self.quote)):
                raise ValueError("a flag carries no verdict")
            return self
        if any(v is None for v in said):
            raise ValueError("a verdict names its work and conversion")
        if self.sentence_span is not None and self.sentence_span[0] >= self.sentence_span[1]:
            raise ValueError("a span is not empty")
        if self.sentence_span is None and self.verdict is not Verdict.SUPPORTED:
            raise ValueError("sentence_span is required unless supported")
        if (self.anchor is None) != (self.quote is None):
            raise ValueError("a quote and its anchor go together")
        if self.quote is None and self.verdict is not Verdict.UNSUPPORTED:
            raise ValueError("a quote is required unless unsupported")
        return self


class ManuscriptAuditDrawn(StrictModel):
    """A sample of `supported` verdicts, drawn by the platform from `seed` out of `population`."""

    audit_id: str = Field(pattern=MANUSCRIPT_AUDIT_ID_RE)
    manuscript_id: str = Field(pattern=MANUSCRIPT_ID_RE)
    seed: int = Field(ge=0, lt=2**32)
    population: int = Field(ge=1, le=MAX_SENTENCES * MAX_KEYS)
    verdict_ids: list[Annotated[str, Field(pattern=MANUSCRIPT_VERDICT_ID_RE)]] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_distinct(self) -> Self:
        if len(set(self.verdict_ids)) != len(self.verdict_ids):
            raise ValueError("verdict_ids are distinct")
        return self


class ManuscriptAudited(StrictModel):
    audit_id: str = Field(pattern=MANUSCRIPT_AUDIT_ID_RE)
    verdict_id: str = Field(pattern=MANUSCRIPT_VERDICT_ID_RE)
    label: AuditLabel
    note: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)
    channel: Channel


# --- Read models ---


class ManuscriptRow(StrictModel):
    """A manuscript as the projection holds it."""

    manuscript_id: str
    library_hash: str
    format: ManuscriptFormat
    bib_hash: str | None
    bib_format: BibFormat | None
    label: str
    segmenter: int
    sentences: int


class SentenceRow(StrictModel):
    ordinal: int
    start: int
    end: int
    sha256: str
    keys: list[str]


class CitationRow(StrictModel):
    key: str
    work_id: str | None
    method: CitationMethod
    score: float | None
    state: CitationState
    decision: CitationDecision | None


class ClosureRow(StrictModel):
    ordinal: int
    key: str
    work_id: str | None
    reason: CloseReason


class UnitRow(StrictModel):
    """A unit (sentence, cited work), or a sentence's unresolved key closed as `cannot-verify`.
    `reason` is set exactly when it is closed. A proposed citation makes none."""

    ordinal: int
    work_id: str | None
    keys: list[str]
    reason: CloseReason | None


class ResolutionSummary(StrictModel):
    """Citations by state and the units closed, as they stand after a resolution."""

    resolved: int
    proposed: int
    unresolved: int
    closed: int


class MsUnit(StrictModel):
    """A verification unit as served: ids only. The text is read with `manuscript_read` and
    `document_read`, so no task content and no `input_blob` holds any."""

    task_id: str
    manuscript_id: str
    ordinal: int
    work_id: str
    conversion_id: str


class NeighbourText(StrictModel):
    ordinal: int
    text: str


class SentenceText(StrictModel):
    """A sentence and the sentences before it, marked `before`, as context only; `after` is always
    empty (ruling 12). `length` is
    what a `sentence_span` is measured against."""

    manuscript_id: str
    ordinal: int
    text: str
    length: int
    keys: list[str]
    before: list[NeighbourText]
    after: list[NeighbourText]


class VerdictRow(StrictModel):
    verdict_id: str
    ordinal: int
    work_id: str
    verdict: Verdict
    span_start: int | None
    span_end: int | None
    anchor: str | None
    quote: str | None
    conversion_id: str
    note: str | None


class ReportUnit(StrictModel):
    """A unit as reported. `detached`: a verdict whose citation has changed since; never counted."""

    work_id: str | None
    keys: list[str]
    state: Literal["open", "judged", "closed", "detached"]
    reason: CloseReason | None
    verdict: VerdictRow | None


class ReportSentence(StrictModel):
    """A cited or flagged sentence, by ordinal. `waiting` lists keys with no unit yet."""

    ordinal: int
    keys: list[str]
    waiting: list[str]
    units: list[ReportUnit]
    uncited_flag: bool


class ManuscriptReport(StrictModel):
    """The verdicts of a manuscript with derived counts; no text of it. For the researcher: `audit`
    holds the rate."""

    manuscript_id: str
    label: str
    sentences: int
    cited: int
    verdicts: dict[str, int]
    closed: dict[str, int]
    open_units: int
    waiting: int
    flags: int
    audit: DraftAuditReport
    rows: list[ReportSentence]


class ManuscriptStatus(StrictModel):
    manuscript_id: str
    label: str
    sentences: int
    cited: int
    citations: dict[str, int]
    verdicts: dict[str, int]
    closed: dict[str, int]
    open_units: int
    flags: int
