"""External manuscripts: identifiers, events and read models (slice 7b, plan W-C).

Invariants:
- No event here holds a manuscript's text: a sentence is its ordinal, offsets and sha256, and a key
  is one bounded token. `label` is the researcher's own free text, bounded at `MAX_LABEL`.
- Every integer an event carries is bounded here, so the fold cannot overflow a column.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.work_ids import WORK_ID_RE

MANUSCRIPT_ID_RE = rf"^msc_{ULID_RE}$"
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
    """A human's decision on a `proposed` citation."""

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
