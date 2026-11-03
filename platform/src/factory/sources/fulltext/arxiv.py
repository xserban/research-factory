"""arXiv full-text routes and the version lookup they share.

An arXiv HTML rendering is served at `arxiv.org/html/<id>v<N>` and the LaTeX source at
`arxiv.org/e-print/<id>v<N>`. The version `N` is not known from the work's bare id. The latest
version comes from the export API (`id_list=<id>`), which is polite-throttled like every other
arXiv request. A pinned version skips the lookup entirely. `arxiv_version_lookup` makes the
per-call cache that lets the HTML and source routes share one API request.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
import zlib
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv
from factory.sources.fulltext.base import (
    ArxivVersionLookup,
    RouteResult,
    VersionAnswer,
    not_retrieved,
    transport_failure,
)
from factory.sources.http import PoliteClient

_LOOKUP_ENDPOINT = "https://export.arxiv.org/api/query"
_HTML_URL = "https://arxiv.org/html/{versioned}"
_SOURCE_URL = "https://arxiv.org/e-print/{versioned}"
_ATOM = {"atom": "http://www.w3.org/2005/Atom"}
_VERSIONED = re.compile(r"^.+v\d+$", re.IGNORECASE)
# The rendering is complete when its article carries the `ltx_document` class; a 200 without it
# is an error page, not a paper. The class may sit in a list, so match it as one token.
_LTX_DOCUMENT = re.compile(rb'class="[^"]*\bltx_document\b')
_GZIP_MAGIC = b"\x1f\x8b"
_TAR_TYPE = "application/x-eprint-tar"
_SINGLE_TYPE = "application/x-eprint"


def _lookup(http: PoliteClient, base: str) -> httpx.Response:
    """The export API's answer for one bare id. Raises only `httpx.TransportError`."""
    return http.fetch(_LOOKUP_ENDPOINT, {"id_list": base})


def _latest_from_feed(body: bytes, base: str) -> str | None:
    """The versioned id of the first entry, if it is the paper `base` (normalised)."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return None
    node = root.find("atom:entry/atom:id", _ATOM)
    if node is None or not node.text:
        return None
    _, sep, tail = node.text.strip().partition("/abs/")
    if not sep or not _VERSIONED.match(tail) or normalize_arxiv(tail) != base:
        return None
    return tail


def latest_arxiv_version(http: PoliteClient, arxiv_id: str) -> tuple[str | None, bytes]:
    """The latest versioned id for `arxiv_id` (e.g. `2301.01234v3`), and the raw API response.

    The version is None when the response is not a 200 or names no entry for this paper. Only
    `httpx.TransportError` is raised; callers decide what a failed lookup means.
    """
    base = normalize_arxiv(arxiv_id)
    response = _lookup(http, base)
    if response.status_code != 200:
        return None, response.content
    return _latest_from_feed(response.content, base), response.content


def _answer(http: PoliteClient, base: str) -> VersionAnswer:
    response = _lookup(http, base)
    return VersionAnswer(
        _latest_from_feed(response.content, base), response.status_code, response.content
    )


def arxiv_version_lookup(http: PoliteClient) -> ArxivVersionLookup:
    """A new per-call lookup over `http`. Create one per `fetch_fulltext` call, not per route."""
    return ArxivVersionLookup(lambda base: _answer(http, base))


def _pin_is_valid(version: str, base: str) -> bool:
    return bool(_VERSIONED.match(version)) and normalize_arxiv(version) == base


@dataclass(frozen=True)
class _Resolved:
    """The versioned id a route will fetch, and the lookup response it consulted, if any."""

    versioned: str
    metadata: bytes | None


class _ArxivRoute:
    """Version resolution shared by the arXiv routes. Subclasses set `route` and the fetch."""

    route: Route

    def __init__(self, http: PoliteClient, lookup: ArxivVersionLookup | None = None) -> None:
        self._http = http
        self._lookup = lookup

    def _resolve(self, work: Work, version: str | None) -> _Resolved | RouteResult:
        """The versioned id to fetch, or the not-retrieved result that ends the attempt.

        Without a shared lookup, each call asks the API afresh.
        """
        raw = work.identifiers.arxiv
        if not raw:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-arxiv-id")
        base = normalize_arxiv(raw)
        if version is not None:
            if _pin_is_valid(version, base):
                return _Resolved(version, None)
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "arxiv-version-unknown")
        try:
            answer = self._lookup.get(base) if self._lookup else _answer(self._http, base)
        except httpx.RequestError:
            return transport_failure(self.route)
        if answer.status >= 400:
            return not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{answer.status}",
                http_status=answer.status,
                metadata=answer.body,
            )
        if answer.versioned is None:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "arxiv-version-unknown",
                metadata=answer.body,
            )
        return _Resolved(answer.versioned, answer.body)


class ArxivHtmlRoute(_ArxivRoute):
    """The arXiv HTML rendering of a work, at its latest version unless a version is pinned."""

    route: Route = Route.ARXIV_HTML

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        resolved = self._resolve(work, version)
        if isinstance(resolved, RouteResult):
            return resolved
        metadata = resolved.metadata
        versioned = resolved.versioned
        url = _HTML_URL.format(versioned=versioned)
        try:
            response = self._http.fetch(url)
        except httpx.RequestError:
            return transport_failure(self.route, url=url)
        status = response.status_code
        if status == 404 or (status < 400 and not _LTX_DOCUMENT.search(response.content)):
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "no-html-rendering",
                url=url,
                http_status=status,
                metadata=metadata,
            )
        if status >= 400:
            return not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{status}",
                url=url,
                http_status=status,
                metadata=metadata,
            )
        return RouteResult(
            route=self.route,
            outcome=AttemptOutcome.RETRIEVED,
            url=url,
            http_status=status,
            content=response.content,
            media_type="text/html",
            source_version=versioned,
            licence=None,
            metadata=metadata,
        )


def _eprint_media_type(body: bytes) -> str | None:
    """The media type of an e-print body, or None when it is not a LaTeX source archive.

    A gzip tar is `application/x-eprint-tar`; a gzipped single file is `application/x-eprint`.
    Anything else (a PDF-only submission, an error page, a corrupt archive) is None.
    """
    if not body.startswith(_GZIP_MAGIC):
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz"):
            return _TAR_TYPE
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        pass
    try:
        gzip.decompress(body)
    except (OSError, EOFError, zlib.error):
        return None
    return _SINGLE_TYPE


class ArxivSourceRoute(_ArxivRoute):
    """The arXiv LaTeX source of a work, at its latest version unless a version is pinned.

    The content is stored as received; unpacking it is the caller's concern.
    """

    route: Route = Route.ARXIV_SOURCE

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        resolved = self._resolve(work, version)
        if isinstance(resolved, RouteResult):
            return resolved
        metadata = resolved.metadata
        versioned = resolved.versioned
        url = _SOURCE_URL.format(versioned=versioned)
        try:
            response = self._http.fetch(url)
        except httpx.RequestError:
            return transport_failure(self.route, url=url)
        status = response.status_code
        if status == 404:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "no-latex-source",
                url=url,
                http_status=status,
                metadata=metadata,
            )
        if status >= 400:
            return not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{status}",
                url=url,
                http_status=status,
                metadata=metadata,
            )
        media_type = _eprint_media_type(response.content)
        if media_type is None:
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "no-latex-source",
                url=url,
                http_status=status,
                metadata=metadata,
            )
        return RouteResult(
            route=self.route,
            outcome=AttemptOutcome.RETRIEVED,
            url=url,
            http_status=status,
            content=response.content,
            media_type=media_type,
            source_version=versioned,
            licence=None,
            metadata=metadata,
        )
