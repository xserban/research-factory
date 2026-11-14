"""Open-access PDF route: the PDFs OpenAlex reports for a work, best location first.

The work is looked up by DOI (its own, else the DataCite DOI arXiv assigns, `10.48550/arxiv.<id>`).
The lookup carries the contact address (`mailto`) as OpenAlex asks; the address never reaches a
`RouteResult` field or an archived lookup body. The version is the one OpenAlex reports for the
location used, which makes `source_version` `<doi>#<version>`; a location that reports no version
is `<doi>#unknown`.

Candidates are `best_oa_location`, then the `locations` entries that are open access and name a
`pdf_url`, in OpenAlex's order, without repeated URLs and at most `_MAX_CANDIDATES`. Each is tried
in turn and the first response that holds a PDF header wins; its URL, licence and version are that
location's. A pinned `version` keeps only the candidates of that version. The route returns one
result. When more than one candidate was tried, the archived `metadata` is a JSON object
`{"lookup": <lookup body>, "attempts": [{"url", "outcome", "reason", "http_status"}, ...]}`; when
one was tried it is the lookup body alone. When all fail, the result is the best location's
(the first candidate's) failure, so its reason strings are unchanged.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from urllib.parse import quote

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv
from factory.sources.fulltext.base import RouteResult, not_retrieved, transport_failure
from factory.sources.http import PoliteClient, redact

_WORKS = "https://api.openalex.org/works/doi:{doi}"
_ARXIV_DOI = "10.48550/arxiv.{base}"
_PDF_MAGIC = b"%PDF-"
# The PDF header must appear within the first kilobyte; a few bytes of prefix are tolerated.
_PDF_SCAN = 1024
_UNKNOWN_VERSION = "unknown"
_MEDIA_TYPE = "application/pdf"
_MAX_CANDIDATES = 5


def _doi_for(work: Work) -> str | None:
    if work.identifiers.doi:
        return work.identifiers.doi
    if work.identifiers.arxiv:
        return _ARXIV_DOI.format(base=normalize_arxiv(work.identifiers.arxiv))
    return None


def _candidates(body: bytes) -> list[dict[str, Any]]:
    """The locations to try: the best one, then the open-access ones with a PDF link.

    Order is OpenAlex's; a location whose `pdf_url` repeats an earlier one is dropped; when none
    has a `pdf_url` the best location alone is returned so that its absence is reported as before.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    best = data.get("best_oa_location")
    if isinstance(best, dict):
        found.append(best)
        url = _text(best.get("pdf_url"))
        if url:
            seen.add(url)
    others = data.get("locations")
    for loc in others if isinstance(others, list) else []:
        if not isinstance(loc, dict) or loc.get("is_oa") is not True:
            continue
        url = _text(loc.get("pdf_url"))
        if url is None or url in seen:
            continue
        seen.add(url)
        found.append(loc)
    with_pdf = [loc for loc in found if _text(loc.get("pdf_url"))]
    return with_pdf[:_MAX_CANDIDATES] if with_pdf else found[:1]


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
        except httpx.RequestError:
            return transport_failure(self.route)
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
        candidates = _candidates(lookup.content)
        if not candidates or _text(candidates[0].get("pdf_url")) is None:
            return not_retrieved(
                self.route, AttemptOutcome.NOT_AVAILABLE, "no-oa-pdf", metadata=archived
            )
        if version is not None:
            candidates = [c for c in candidates if self._version_of(doi, c) == version]
            if not candidates:
                return not_retrieved(
                    self.route,
                    AttemptOutcome.NOT_AVAILABLE,
                    "oa-version-unknown",
                    metadata=archived,
                )
        tried: list[RouteResult] = []
        for location in candidates:
            result = self._try(doi, location)
            if result.outcome is AttemptOutcome.RETRIEVED:
                return replace(result, metadata=self._metadata(archived, tried, result))
            tried.append(result)
        return replace(tried[0], metadata=self._metadata(archived, tried[:-1], tried[-1]))

    @staticmethod
    def _version_of(doi: str, location: dict[str, Any]) -> str:
        return f"{doi}#{_text(location.get('version')) or _UNKNOWN_VERSION}"

    @staticmethod
    def _metadata(archived: bytes, before: list[RouteResult], last: RouteResult) -> bytes:
        """The lookup body alone for one attempt, else the lookup wrapped with every attempt."""
        attempts = [*before, last]
        if len(attempts) == 1:
            return archived
        try:
            lookup: object = json.loads(archived)
        except ValueError:
            lookup = archived.decode("utf-8", errors="replace")
        record = [
            {
                "url": a.url,
                "outcome": a.outcome.value,
                "reason": a.reason,
                "http_status": a.http_status,
            }
            for a in attempts
        ]
        return json.dumps({"lookup": lookup, "attempts": record}).encode("utf-8")

    def _try(self, doi: str, location: dict[str, Any]) -> RouteResult:
        """Fetch one candidate; its result carries no metadata (the caller adds it)."""
        pdf_url = _text(location.get("pdf_url")) or ""
        shown = redact(pdf_url, self._mailto)
        try:
            pdf = self._http.fetch(pdf_url)
        except httpx.RequestError:
            return transport_failure(self.route, url=shown)
        pdf_status = pdf.status_code
        if pdf_status >= 400:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE if pdf_status == 404 else AttemptOutcome.FAILED,
                f"http-{pdf_status}",
                url=shown,
                http_status=pdf_status,
            )
        if _PDF_MAGIC not in pdf.content[:_PDF_SCAN]:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "not-a-pdf",
                url=shown,
                http_status=pdf_status,
            )
        return RouteResult(
            route=self.route,
            outcome=AttemptOutcome.RETRIEVED,
            url=shown,
            http_status=pdf_status,
            content=pdf.content,
            media_type=_MEDIA_TYPE,
            source_version=self._version_of(doi, location),
            licence=_text(location.get("license")),
        )
