"""Full-text acquisition vocabulary and event payloads: routes, quality, attempts, documents.

A route is one legal source of full text. The canonical order `ROUTE_ORDER` is the order in which
automatic fetching tries them. `RESEARCHER` (a PDF the researcher supplies) is never tried
automatically, so it is excluded from `ROUTE_ORDER` and refused as an automatic fetch route.
Each route has one quality class (`QUALITY`), which a document carries and which is derived from
its route, never typed.

Invariants enforced here (validated at the boundary, before any event is written):
- An attempt is retrieved or restored exactly when it carries a library hash and a document id.
  A not-available or failed attempt names its reason.
- An attempt's licence is present exactly when its licence status is `reported`.
- A fetch names each route at most once and never names `researcher-supplied`.
- A document's quality and provenance follow from its route.
- A source change records two different library hashes, and a document never supersedes itself.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE
from factory.model.screening import NonBlank
from factory.model.work_ids import WORK_ID_RE

FETCH_ID_RE = rf"^fft_{ULID_RE}$"
ATTEMPT_ID_RE = rf"^att_{ULID_RE}$"
DOCUMENT_ID_RE = rf"^doc_{ULID_RE}$"


class Route(StrEnum):
    ARXIV_HTML = "arxiv-html"
    ARXIV_SOURCE = "arxiv-source"
    OA_PDF = "oa-pdf"
    RESEARCHER = "researcher-supplied"


ROUTE_ORDER: tuple[Route, ...] = (Route.ARXIV_HTML, Route.ARXIV_SOURCE, Route.OA_PDF)
"""The automatic routes in the order they are tried. `RESEARCHER` is not among them."""


class Quality(StrEnum):
    STRUCTURED_HTML = "structured-html"
    LATEX = "latex"
    PDF_TEXT = "pdf-text"


QUALITY: Mapping[Route, Quality] = MappingProxyType(
    {
        Route.ARXIV_HTML: Quality.STRUCTURED_HTML,
        Route.ARXIV_SOURCE: Quality.LATEX,
        Route.OA_PDF: Quality.PDF_TEXT,
        Route.RESEARCHER: Quality.PDF_TEXT,
    }
)


class AttemptOutcome(StrEnum):
    RETRIEVED = "retrieved"
    NOT_AVAILABLE = "not-available"
    FAILED = "failed"
    RESTORED = "restored"


class LicenceStatus(StrEnum):
    REPORTED = "reported"
    NOT_REPORTED = "not-reported"


WorkId = Annotated[str, StringConstraints(pattern=WORK_ID_RE)]


# --- Event payloads (schema 1). Written by `factory.services.fulltext`, folded by
# `factory.index.fulltext`.


class FetchStarted(StrictModel):
    """A fetch of full text for some works. `routes=None` means the default first-success order."""

    fetch_id: str = Field(pattern=FETCH_ID_RE)
    work_ids: list[WorkId]
    routes: list[Route] | None
    refresh: bool

    @model_validator(mode="after")
    def _routes_are_automatic(self) -> Self:
        if self.routes is None:
            return self
        if Route.RESEARCHER in self.routes:
            raise ValueError("a researcher-supplied route is never fetched automatically")
        if len(set(self.routes)) != len(self.routes):
            raise ValueError("routes must not repeat a route")
        return self


class Attempted(StrictModel):
    """One route tried for one work. Every route tried is one attempt, whatever its outcome."""

    attempt_id: str = Field(pattern=ATTEMPT_ID_RE)
    fetch_id: str | None = Field(default=None, pattern=FETCH_ID_RE)
    work_id: WorkId
    route: Route
    url: str | None
    http_status: int | None = Field(default=None, ge=100, le=599)
    outcome: AttemptOutcome
    reason: NonBlank | None
    retrieved_at: AwareDatetime
    source_version: str | None
    licence: NonBlank | None
    licence_status: LicenceStatus
    media_type: str | None
    raw_hash: str | None = Field(default=None, pattern=BLOB_REF_RE)
    metadata_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    document_id: str | None = Field(default=None, pattern=DOCUMENT_ID_RE)

    @model_validator(mode="after")
    def _check_outcome(self) -> Self:
        has_content = self.raw_hash is not None and self.document_id is not None
        if self.outcome in (AttemptOutcome.RETRIEVED, AttemptOutcome.RESTORED):
            if not has_content:
                raise ValueError("a retrieved or restored attempt names its hash and document")
        elif self.raw_hash is not None or self.document_id is not None:
            raise ValueError("an attempt without content carries no hash or document")
        not_retrieved = self.outcome in (AttemptOutcome.NOT_AVAILABLE, AttemptOutcome.FAILED)
        if not_retrieved and self.reason is None:
            raise ValueError("a not-available or failed attempt names its reason")
        return self

    @model_validator(mode="after")
    def _check_licence(self) -> Self:
        reported = self.licence_status is LicenceStatus.REPORTED
        if (self.licence is not None) != reported:
            raise ValueError("a licence is recorded exactly when its status is reported")
        return self


class DocumentAdded(StrictModel):
    """A new document: a distinct library entry for one work, from one attempt."""

    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    work_id: WorkId
    route: Route
    quality: Quality
    source_version: NonBlank
    raw_hash: str = Field(pattern=BLOB_REF_RE)
    media_type: NonBlank
    attempt_id: str = Field(pattern=ATTEMPT_ID_RE)
    provenance: Literal["retrieved", "researcher-supplied"]
    supersedes: str | None = Field(default=None, pattern=DOCUMENT_ID_RE)

    @model_validator(mode="after")
    def _check_derived_fields(self) -> Self:
        if self.quality is not QUALITY[self.route]:
            raise ValueError("a document's quality follows from its route")
        supplied = self.route is Route.RESEARCHER
        if (self.provenance == "researcher-supplied") != supplied:
            raise ValueError("a document's provenance follows from its route")
        if self.supersedes == self.document_id:
            raise ValueError("a document never supersedes itself")
        return self


class SourceChanged(StrictModel):
    """A re-fetch of a known source that hashed differently. The original stays the reference."""

    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    attempt_id: str = Field(pattern=ATTEMPT_ID_RE)
    expected_hash: str = Field(pattern=BLOB_REF_RE)
    observed_hash: str = Field(pattern=BLOB_REF_RE)

    @model_validator(mode="after")
    def _hashes_differ(self) -> Self:
        if self.expected_hash == self.observed_hash:
            raise ValueError("a source change records two different hashes")
        return self
