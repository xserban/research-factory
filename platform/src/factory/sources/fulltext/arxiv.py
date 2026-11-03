"""arXiv full-text routes and the version lookup they share.

An arXiv HTML rendering is served at `arxiv.org/html/<id>v<N>`, and the version `N` is not known
from the work's bare id. The latest version comes from the export API (`id_list=<id>`), which is
polite-throttled like every other arXiv request. A pinned version skips the lookup entirely.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work
from factory.model.work_ids import normalize_arxiv
from factory.sources.fulltext.base import RouteResult, not_retrieved
from factory.sources.http import PoliteClient

_LOOKUP_ENDPOINT = "https://export.arxiv.org/api/query"
_HTML_URL = "https://arxiv.org/html/{versioned}"
_ATOM = {"atom": "http://www.w3.org/2005/Atom"}
_VERSIONED = re.compile(r"^.+v\d+$", re.IGNORECASE)
# The rendering is complete when its article carries the `ltx_document` class; a 200 without it
# is an error page, not a paper. The class may sit in a list, so match it as one token.
_LTX_DOCUMENT = re.compile(rb'class="[^"]*\bltx_document\b')


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


def _pin_is_valid(version: str, base: str) -> bool:
    return bool(_VERSIONED.match(version)) and normalize_arxiv(version) == base


class ArxivHtmlRoute:
    """The arXiv HTML rendering of a work, at its latest version unless a version is pinned."""

    route: Route = Route.ARXIV_HTML

    def __init__(self, http: PoliteClient) -> None:
        self._http = http

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        raw = work.identifiers.arxiv
        if not raw:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-arxiv-id")
        base = normalize_arxiv(raw)

        metadata: bytes | None = None
        if version is None:
            try:
                response = _lookup(self._http, base)
            except httpx.TransportError:
                return not_retrieved(self.route, AttemptOutcome.FAILED, "transport")
            metadata = response.content
            if response.status_code >= 400:
                return not_retrieved(
                    self.route,
                    AttemptOutcome.FAILED,
                    f"http-{response.status_code}",
                    http_status=response.status_code,
                    metadata=metadata,
                )
            versioned = _latest_from_feed(metadata, base)
            if versioned is None:
                return not_retrieved(
                    self.route,
                    AttemptOutcome.NOT_AVAILABLE,
                    "arxiv-version-unknown",
                    metadata=metadata,
                )
        elif _pin_is_valid(version, base):
            versioned = version
        else:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "arxiv-version-unknown")

        url = _HTML_URL.format(versioned=versioned)
        try:
            response = self._http.fetch(url)
        except httpx.TransportError:
            return not_retrieved(self.route, AttemptOutcome.FAILED, "transport", url=url)
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
