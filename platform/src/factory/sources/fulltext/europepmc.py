"""Europe PMC JATS route: the article XML from the Europe PMC REST service.

Endpoints (public, no key; `https://europepmc.org/RestfulWebService`):

- search `https://www.ebi.ac.uk/europepmc/webservices/rest/search` with `query`, `format=json`,
  `resultType=core`, `pageSize=2`. The query is `PMCID:PMC<n>` when the work has a PMCID, else
  `EXT_ID:<pmid> AND SRC:MED`, else `DOI:"<doi>"`. Reply `{hitCount, resultList: {result: [...]}}`
  where a result has `pmcid`, `isOpenAccess` (`Y` or `N`) and `license` (core records only).
- full text `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC<n>/fullTextXML`, JATS for the
  open-access articles Europe PMC holds (404 otherwise).

Rulings (IDEA-77; the route follows the PMC route): it is tried after `pmc-jats`, so it serves
articles NCBI's bucket does not; the article is fetched only when Europe PMC reports `isOpenAccess`
`Y`; the licence is Europe PMC's `license`, recorded also when the article is refused; the XML is
kept as received with `application/jats+xml`, so the same pandoc JATS converter applies. Europe PMC
has no article versions: `source_version` is `EPMC:PMC<n>`, so a changed body under the same
version reads as a changed source (decision 46), never as a silent new version. The raw search
reply is the archived `metadata`. The politeness client is the shared one; no contact address or
key is sent.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from typing import Any

import httpx

from factory.model.fulltext import AttemptOutcome, Route
from factory.model.work import Work
from factory.sources.fulltext.base import RouteResult, not_retrieved, transport_failure
from factory.sources.http import PoliteClient

_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
_SEARCH = _BASE + "search"
_FULLTEXT = _BASE + "PMC{num}/fullTextXML"
_MEDIA_TYPE = "application/jats+xml"
_PMCID_RE = re.compile(r"^(?:PMC)?(\d+)$", re.IGNORECASE)
_VERSION_RE = re.compile(r"^EPMC:PMC(\d+)$")


def _pmc_number(value: object) -> str | None:
    if isinstance(value, str):
        m = _PMCID_RE.match(value.strip())
        if m:
            return m.group(1)
    return None


def _query(work: Work) -> str | None:
    ids = work.identifiers
    num = _pmc_number(ids.pmcid)
    if num:
        return f"PMCID:PMC{num}"
    if ids.pmid:
        return f"EXT_ID:{ids.pmid} AND SRC:MED"
    if ids.doi:
        return 'DOI:"' + ids.doi.replace('"', "") + '"'
    return None


def _results(body: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(body)
    except ValueError:
        return []
    result_list = data.get("resultList") if isinstance(data, dict) else None
    rows = result_list.get("result") if isinstance(result_list, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _has_body(xml: bytes) -> bool:
    """True when the XML is an `<article>` with a `<body>` child."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    articles = [root] if root.tag.rsplit("}", 1)[-1] == "article" else []
    articles += [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "article"]
    return any(c.tag.rsplit("}", 1)[-1] == "body" for a in articles for c in a)


class EuropePmcJatsRoute:
    """The JATS XML of an open-access article from Europe PMC, fetched as received."""

    route: Route = Route.EUROPEPMC_JATS

    def __init__(self, http: PoliteClient) -> None:
        self._http = http

    def _get(
        self, url: str, params: dict[str, str | int] | None = None, metadata: bytes | None = None
    ) -> tuple[httpx.Response | None, RouteResult | None]:
        """One GET; a failure comes back as a ready result."""
        try:
            response = self._http.fetch(url, params)
        except httpx.RequestError:
            return None, transport_failure(self.route, url=url, metadata=metadata)
        status = response.status_code
        if status >= 400:
            return None, not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE if status == 404 else AttemptOutcome.FAILED,
                f"http-{status}",
                url=url,
                http_status=status,
                metadata=metadata,
            )
        return response, None

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        pinned = _VERSION_RE.match(version) if version else None
        if version is not None and pinned is None:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-version")
        query = _query(work)
        if pinned:
            query = f"PMCID:PMC{pinned.group(1)}"
        if query is None:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-identifier")
        params: dict[str, str | int] = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": 2,
        }
        reply, failure = self._get(_SEARCH, params)
        if failure is not None or reply is None:
            return failure or transport_failure(self.route)
        meta = reply.content
        rows = _results(meta)
        row = next((r for r in rows if _pmc_number(r.get("pmcid"))), None)
        if row is None:
            return not_retrieved(
                self.route, AttemptOutcome.NOT_AVAILABLE, "not-in-europepmc", metadata=meta
            )
        num = str(_pmc_number(row.get("pmcid")))
        licence = row.get("license")
        licence = licence.strip() if isinstance(licence, str) and licence.strip() else None
        if row.get("isOpenAccess") != "Y":
            return replace(
                not_retrieved(
                    self.route, AttemptOutcome.NOT_AVAILABLE, "not-open-access", metadata=meta
                ),
                licence=licence,
            )
        url = _FULLTEXT.format(num=num)
        xml, failure = self._get(url, metadata=meta)
        if failure is not None or xml is None:
            return failure or transport_failure(self.route, url=url, metadata=meta)
        if not _has_body(xml.content):
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "no-body",
                url=url,
                http_status=xml.status_code,
                metadata=meta,
            )
        return RouteResult(
            route=self.route,
            outcome=AttemptOutcome.RETRIEVED,
            url=url,
            http_status=xml.status_code,
            content=xml.content,
            media_type=_MEDIA_TYPE,
            source_version=f"EPMC:PMC{num}",
            licence=licence,
            metadata=meta,
        )
