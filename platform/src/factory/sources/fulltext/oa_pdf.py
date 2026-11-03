"""Open-access PDF route: the PDF OpenAlex reports as a work's best open-access location.

The work is looked up by DOI (its own, else the DataCite DOI arXiv assigns, `10.48550/arxiv.<id>`).
The lookup carries the contact address (`mailto`) as OpenAlex asks; the address never reaches a
`RouteResult` field or an archived lookup body. The version is the one OpenAlex reports, which
makes `source_version` `<doi>#<version>`; a lookup that reports no version is `<doi>#unknown`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv
from factory.sources.fulltext.base import RouteResult, not_retrieved
from factory.sources.http import PoliteClient, redact

_WORKS = "https://api.openalex.org/works/doi:{doi}"
_ARXIV_DOI = "10.48550/arxiv.{base}"
_PDF_MAGIC = b"%PDF-"
# The PDF header must appear within the first kilobyte; a few bytes of prefix are tolerated.
_PDF_SCAN = 1024
_UNKNOWN_VERSION = "unknown"
_MEDIA_TYPE = "application/pdf"


def _doi_for(work: Work) -> str | None:
    if work.identifiers.doi:
        return work.identifiers.doi
    if work.identifiers.arxiv:
        return _ARXIV_DOI.format(base=normalize_arxiv(work.identifiers.arxiv))
    return None


def _best_location(body: bytes) -> dict[str, Any] | None:
    """The `best_oa_location` object, or None when the body is not JSON or names none."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    location = data.get("best_oa_location")
    return location if isinstance(location, dict) else None


def _text(value: object) -> str | None:
    """A non-blank string, stripped, or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class OaPdfRoute:
    """The open-access PDF that OpenAlex reports for a work, fetched as received."""

    route: Route = Route.OA_PDF

    def __init__(self, http: PoliteClient, mailto: str | None) -> None:
        self._http = http
        self._mailto = mailto

    def _archive(self, body: bytes) -> bytes:
        """The lookup body with the contact address removed, as it is kept in `blobs/`."""
        return redact(body.decode("utf-8", errors="replace"), self._mailto).encode("utf-8")

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        doi = _doi_for(work)
        if doi is None:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-identifier")
        params = {"mailto": self._mailto} if self._mailto else None
        try:
            lookup = self._http.fetch(_WORKS.format(doi=quote(doi, safe="/")), params)
        except httpx.TransportError:
            return not_retrieved(self.route, AttemptOutcome.FAILED, "transport")
        status = lookup.status_code
        archived = self._archive(lookup.content)
        if status == 404:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "not-in-openalex",
                http_status=status,
                metadata=archived,
            )
        if status >= 400:
            return not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{status}",
                http_status=status,
                metadata=archived,
            )
        location = _best_location(lookup.content)
        pdf_url = _text(location.get("pdf_url")) if location else None
        if location is None or pdf_url is None:
            return not_retrieved(
                self.route, AttemptOutcome.NOT_AVAILABLE, "no-oa-pdf", metadata=archived
            )
        source_version = f"{doi}#{_text(location.get('version')) or _UNKNOWN_VERSION}"
        if version is not None and version != source_version:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "oa-version-unknown",
                metadata=archived,
            )
        shown = redact(pdf_url, self._mailto)
        try:
            pdf = self._http.fetch(pdf_url)
        except httpx.TransportError:
            return not_retrieved(
                self.route, AttemptOutcome.FAILED, "transport", url=shown, metadata=archived
            )
        pdf_status = pdf.status_code
        if pdf_status >= 400:
            return not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{pdf_status}",
                url=shown,
                http_status=pdf_status,
                metadata=archived,
            )
        if _PDF_MAGIC not in pdf.content[:_PDF_SCAN]:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "not-a-pdf",
                url=shown,
                http_status=pdf_status,
                metadata=archived,
            )
        return RouteResult(
            route=self.route,
            outcome=AttemptOutcome.RETRIEVED,
            url=shown,
            http_status=pdf_status,
            content=pdf.content,
            media_type=_MEDIA_TYPE,
            source_version=source_version,
            licence=_text(location.get("license")),
            metadata=archived,
        )
