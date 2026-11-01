"""The `Work` model — one shape for every kind of literature.

A journal article, a preprint, a blog post and a standard are the same model with a
different `type` and a different appraisal path. Grey literature is not a second-class
citizen here; treating it as one is how it ends up uncited and unappraised.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, ConfigDict, Field, field_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.work_ids import normalize_arxiv, normalize_doi, work_id

RUN_ID_RE = rf"^run_{ULID_RE}$"
QUERY_ID_RE = rf"^qry_{ULID_RE}$"


class _WorkModel(StrictModel):
    """Work-family models: StrictModel's config plus whitespace stripping on strings."""

    model_config = ConfigDict(str_strip_whitespace=True)


class WorkType(StrEnum):
    JOURNAL_ARTICLE = "journal-article"
    PREPRINT = "preprint"
    CONFERENCE_PAPER = "conference-paper"
    BOOK_CHAPTER = "book-chapter"
    THESIS = "thesis"
    TECH_REPORT = "tech-report"
    STANDARD = "standard"
    PATENT = "patent"
    DATASET = "dataset"
    DOCUMENTATION = "documentation"
    BLOG_POST = "blog-post"
    FORUM_POST = "forum-post"
    VIDEO = "video"
    OTHER = "other"

    @property
    def is_peer_reviewed_by_default(self) -> bool:
        """Whether this type normally carries peer review.

        A default, never a finding: it seeds the appraisal route (GRADE/RoB vs AACODS) and
        is overridden by `Appraisal.peer_reviewed` whenever the record says otherwise.
        """
        return self in {
            WorkType.JOURNAL_ARTICLE,
            WorkType.CONFERENCE_PAPER,
            WorkType.BOOK_CHAPTER,
        }


class ProvenanceMethod(StrEnum):
    DATABASE = "database"
    CITATION_CHASE = "citation-chase"
    SEED_ADMISSION = "seed-admission"
    HAND_SEARCH = "hand-search"


class Identifiers(_WorkModel):
    doi: str | None = None
    arxiv: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    openalex: str | None = None
    s2: str | None = None
    url: str | None = None
    isbn: str | None = None

    @field_validator("doi")
    @classmethod
    def _normalize_doi(cls, value: str | None) -> str | None:
        """Normalise on construction so dedup never compares unnormalised forms."""
        return normalize_doi(value) if value else value

    @field_validator("arxiv")
    @classmethod
    def _normalize_arxiv(cls, value: str | None) -> str | None:
        return normalize_arxiv(value) if value else value

    def any_strong(self) -> str | None:
        """The strongest identifier present, for dedup's first cascade stages."""
        return self.doi or self.arxiv or self.pmid or self.openalex


class Author(_WorkModel):
    name: str
    orcid: str | None = None
    affiliation: str | None = None


class Venue(_WorkModel):
    name: str | None = None
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None


class Dates(_WorkModel):
    published: date | None = None
    updated: date | None = None
    retrieved: datetime | None = None

    @property
    def year(self) -> int | None:
        return self.published.year if self.published else None


class Provenance(_WorkModel):
    """How one source came to hand us this record.

    PRISMA's identification counts are derived entirely from these, which is why `Work`
    refuses to exist without at least one.
    """

    source: str
    run_id: str = Field(pattern=RUN_ID_RE)
    query_id: str = Field(pattern=QUERY_ID_RE)
    at: AwareDatetime
    raw_blob: str = Field(pattern=BLOB_REF_RE)
    raw_ref: str | None = None
    method: ProvenanceMethod = ProvenanceMethod.DATABASE


class Work(_WorkModel):
    id: str
    type: WorkType = WorkType.OTHER
    title: str
    abstract: str | None = None
    language: str | None = None
    authors: list[Author] = Field(default_factory=list)
    identifiers: Identifiers = Field(default_factory=Identifiers)
    venue: Venue | None = None
    dates: Dates = Field(default_factory=Dates)
    subjects: list[str] = Field(default_factory=list)
    cited_by_count: int | None = None
    retracted: bool = False

    # The construction-time invariant. A work that cannot say where it came from is not a
    # record, it is a rumour — and it would silently corrupt every PRISMA count downstream.
    provenance: Annotated[list[Provenance], Field(min_length=1)]

    supersedes: list[str] = Field(default_factory=list)
    absorbed: list[str] = Field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        title: str,
        provenance: list[Provenance],
        authors: list[Author] | None = None,
        identifiers: Identifiers | None = None,
        dates: Dates | None = None,
        **rest: object,
    ) -> Work:
        """Construct a `Work`, deriving its deterministic id from its own content."""
        authors = authors or []
        identifiers = identifiers or Identifiers()
        dates = dates or Dates()
        return cls(
            id=work_id(
                title=title,
                authors=[a.name for a in authors],
                year=dates.year,
                doi=identifiers.doi,
                arxiv=identifiers.arxiv,
            ),
            title=title,
            authors=authors,
            identifiers=identifiers,
            dates=dates,
            provenance=provenance,
            **rest,
        )

    @property
    def sources(self) -> list[str]:
        """Distinct sources that returned this work, in first-seen order."""
        return list(dict.fromkeys(p.source for p in self.provenance))
