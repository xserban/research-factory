"""Import records: the allow-listed bibliographic fields of one record of a library export.

Invariants (slice 3d ruling 19, plan Import-A ruling 1):
- `ImportFields` holds only title, authors, year, DOI, arXiv id, URL, venue, type, abstract and
  tags. Notes, `annote`, file paths and every other field of an export never reach a record.
- `record_sha256` is the SHA-256 (hex) of the record's raw source text, so a record is traceable
  to the archived export without copying it.
- An attachment is known by the hash of its path as written and the hash of its bytes; the bytes
  travel in `ParsedImport.attachment_bytes`, which is never serialised.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel

MAX_AUTHORS = 50
MAX_ABSTRACT = 5_000
MAX_TAGS = 50
MAX_TAG_LENGTH = 60

SHA256_HEX_RE = r"^[0-9a-f]{64}$"

ABSTRACT_TRUNCATED = "abstract-truncated"
AUTHORS_TRUNCATED = "authors-truncated"
TAGS_TRUNCATED = "tags-truncated"
NOT_PDF = "not-pdf"
TITLE_METADATA_REJECTED = "title-metadata-rejected"

RecordType = Literal["article", "inproceedings", "preprint", "book", "thesis", "report", "other"]


class ImportFormatError(Exception):
    """The bytes cannot be read as the declared format at all."""


class ImportFormat(StrEnum):
    BIBTEX = "bibtex"
    CSL = "csl"
    RIS = "ris"
    PDFS = "pdfs"


class ImportRole(StrEnum):
    """What an import is for: `reference` stays outside the corpus, `corpus` is admitted."""

    REFERENCE = "reference"
    CORPUS = "corpus"


class ParseOutcome(StrEnum):
    PARSED = "parsed"
    NO_TITLE_NO_IDENTIFIER = "no-title-no-identifier"
    MALFORMED = "malformed"


class ImportFields(StrictModel):
    """The allow-listed fields of one record. Lists are bounded; truncation is flagged on the
    record, never silent."""

    title: str | None = None
    authors: list[str] = Field(default_factory=list, max_length=MAX_AUTHORS)
    year: int | None = None
    doi: str | None = None
    arxiv: str | None = None
    url: str | None = None
    venue: str | None = None
    type: RecordType = "other"
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    def has_identity(self) -> bool:
        """A title, DOI or arXiv id: something a resolver can work from."""
        return bool(self.title or self.doi or self.arxiv)


class Attachment(StrictModel):
    path_sha256: str = Field(pattern=SHA256_HEX_RE)
    content_sha256: str | None = Field(default=None, pattern=SHA256_HEX_RE)


class ImportRecord(StrictModel):
    """One raw record of an export. A malformed record keeps only its ordinal and hash."""

    ordinal: int = Field(ge=1)
    outcome: ParseOutcome
    fields: ImportFields | None
    record_sha256: str = Field(pattern=SHA256_HEX_RE)
    attachment: Attachment | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedImport:
    """A parser's result. `attachment_bytes` maps content hash to bytes and `local_paths` maps a
    PDF-folder record's ordinal to its path under the folder; neither reaches a record, and only
    the library manifest holds the paths (ruling 19)."""

    format: ImportFormat
    parser: str
    parser_version: str
    records: tuple[ImportRecord, ...]
    attachment_bytes: Mapping[str, bytes] = field(default_factory=dict)
    local_paths: Mapping[int, str] = field(default_factory=dict)


def bounded_fields(
    *,
    title: str | None,
    authors: list[str],
    year: int | None,
    doi: str | None,
    arxiv: str | None,
    url: str | None,
    venue: str | None,
    type: RecordType,
    abstract: str | None,
    tags: list[str],
    truncated_authors: bool = False,
) -> tuple[ImportFields, tuple[str, ...]]:
    """Build `ImportFields` within the allow-list bounds, and the flags for what was cut."""
    flags: list[str] = []
    authors = [a for a in authors if a]
    if truncated_authors or len(authors) > MAX_AUTHORS:
        flags.append(AUTHORS_TRUNCATED)
    if abstract is not None and len(abstract) > MAX_ABSTRACT:
        flags.append(ABSTRACT_TRUNCATED)
    kept_tags: list[str] = []
    for tag in tags:
        cut = tag.strip()[:MAX_TAG_LENGTH].strip()
        if cut and cut not in kept_tags:
            kept_tags.append(cut)
    if len(kept_tags) > MAX_TAGS:
        flags.append(TAGS_TRUNCATED)
    built = ImportFields(
        title=title or None,
        authors=authors[:MAX_AUTHORS],
        year=year,
        doi=doi or None,
        arxiv=arxiv or None,
        url=url or None,
        venue=venue or None,
        type=type,
        abstract=abstract[:MAX_ABSTRACT] if abstract else None,
        tags=kept_tags[:MAX_TAGS],
    )
    return built, tuple(flags)


def outcome_of(fields: ImportFields) -> ParseOutcome:
    return ParseOutcome.PARSED if fields.has_identity() else ParseOutcome.NO_TITLE_NO_IDENTIFIER
