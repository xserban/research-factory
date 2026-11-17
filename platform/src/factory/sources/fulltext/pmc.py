"""PubMed Central JATS route: the article XML from the `pmc-oa-opendata` bucket.

Endpoints, checked 2026-11-14 (the PMC OA web service `oa.fcgi` was retired on 2026-02-12):

- ID converter `https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/` (`ids`, `idtype`,
  `format=json`; `tool` and `email` only when a contact address is configured), used only when the
  work has no PMCID. Reply `{status, records: [{doi, pmcid, pmid, requested-id}]}`.
- Bucket `https://pmc-oa-opendata.s3.amazonaws.com/`: `PMC<id>.<ver>/PMC<id>.<ver>.json` and
  `.xml`. The bucket README (read 2026-11-14) confirms the layout and the JSON fields used here:
  `is_pmc_openaccess`, `is_retracted`, `license_code`, `xml_url`. Versions are listed with the S3
  ListObjectsV2 query (`list-type=2`, `prefix=PMC<id>.`, `delimiter=/`); the highest number wins.

Rulings: both the JSON and the JATS come from the bucket (no E-utilities); the latest version is
used, `source_version` is `PMC<id>.<ver>`; the article is fetched when `is_pmc_openaccess` is true
or `license_code` is `TDM`, and `licence` is `license_code`; otherwise `not-open-access`, which
still carries the `license_code` it found.
Retraction is not refused here: it is recorded by the notices service, so a retracted article is
fetched like any other and `is_retracted` stays in the archived version JSON.
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

_IDCONV = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
_BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com/"
_OBJECT = _BUCKET + "PMC{num}.{ver}/PMC{num}.{ver}.{ext}"
_MEDIA_TYPE = "application/jats+xml"
_TDM = "TDM"
_VERSION_RE = re.compile(r"^PMC(\d+)\.(\d+)$")
_PMCID_RE = re.compile(r"^(?:PMC)?(\d+)$", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^PMC(\d+)\.(\d+)/$")


def _pmc_number(value: object) -> str | None:
    """The digits of a PMCID (`PMC123` or `123`), or None."""
    if isinstance(value, str):
        m = _PMCID_RE.match(value.strip())
        if m:
            return m.group(1)
    return None


def _json_object(body: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _latest_version(listing: bytes, num: str) -> int | None:
    """The highest version in an S3 listing's `CommonPrefixes`, or None when there is none."""
    try:
        root = ET.fromstring(listing)
    except ET.ParseError:
        return None
    versions = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Prefix" or not element.text:
            continue
        m = _PREFIX_RE.match(element.text.strip())
        if m and m.group(1) == num:
            versions.append(int(m.group(2)))
    return max(versions) if versions else None


def _has_body(xml: bytes) -> bool:
    """True when the XML is an `<article>` with a `<body>` child."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    articles = [root] if root.tag.rsplit("}", 1)[-1] == "article" else []
    articles += [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "article"]
    return any(c.tag.rsplit("}", 1)[-1] == "body" for a in articles for c in a)


class PmcJatsRoute:
    """The JATS XML of a PubMed Central article from the open bucket, fetched as received."""

    route: Route = Route.PMC_JATS

    def __init__(self, http: PoliteClient) -> None:
        self._http = http

    def _convert(self, work: Work) -> tuple[str | None, RouteResult | None]:
        """The PMC number from the converter, or a failure result. `(None, None)` means none."""
        ids = work.identifiers
        if ids.pmid:
            idtype, value = "pmid", ids.pmid
        elif ids.doi:
            idtype, value = "doi", ids.doi
        else:
            return None, None
        params: dict[str, str | int] = {"ids": value, "idtype": idtype, "format": "json"}
        try:
            reply = self._http.fetch(_IDCONV, params)
        except httpx.RequestError:
            return None, transport_failure(self.route)
        if reply.status_code >= 400:
            return None, not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{reply.status_code}",
                http_status=reply.status_code,
            )
        data = _json_object(reply.content)
        records = data.get("records") if data else None
        for record in records if isinstance(records, list) else []:
            if isinstance(record, dict):
                num = _pmc_number(record.get("pmcid"))
                if num:
                    return num, None
        return None, None

    def _get(self, url: str, **kw: Any) -> tuple[httpx.Response | None, RouteResult | None]:
        """One GET; a failure comes back as a ready result."""
        try:
            response = self._http.fetch(url, kw.get("params"))
        except httpx.RequestError:
            return None, transport_failure(self.route, url=url, metadata=kw.get("metadata"))
        status = response.status_code
        if status == 404:
            return None, not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "http-404",
                url=url,
                http_status=status,
                metadata=kw.get("metadata"),
            )
        if status >= 400:
            return None, not_retrieved(
                self.route,
                AttemptOutcome.FAILED,
                f"http-{status}",
                url=url,
                http_status=status,
                metadata=kw.get("metadata"),
            )
        return response, None

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        pinned = _VERSION_RE.match(version) if version else None
        num = _pmc_number(work.identifiers.pmcid)
        if num is None and pinned:
            num = pinned.group(1)
        if num is None:
            num, failure = self._convert(work)
            if failure is not None:
                return failure
        if num is None:
            return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-pmcid")
        if pinned and pinned.group(1) == num:
            ver = int(pinned.group(2))
        else:
            if version is not None:
                return not_retrieved(self.route, AttemptOutcome.NOT_AVAILABLE, "no-version")
            listing, failure = self._get(_BUCKET + f"?list-type=2&prefix=PMC{num}.&delimiter=/")
            if failure is not None or listing is None:
                return failure or transport_failure(self.route)
            latest = _latest_version(listing.content, num)
            if latest is None:
                return not_retrieved(
                    self.route, AttemptOutcome.NOT_AVAILABLE, "no-version", http_status=200
                )
            ver = latest
        source_version = f"PMC{num}.{ver}"
        meta_resp, failure = self._get(_OBJECT.format(num=num, ver=ver, ext="json"))
        if failure is not None or meta_resp is None:
            return failure or transport_failure(self.route)
        meta = meta_resp.content
        info = _json_object(meta) or {}
        licence = info.get("license_code")
        licence = licence.strip() if isinstance(licence, str) and licence.strip() else None
        if info.get("is_pmc_openaccess") is not True and licence != _TDM:
            return replace(
                not_retrieved(
                    self.route, AttemptOutcome.NOT_AVAILABLE, "not-open-access", metadata=meta
                ),
                licence=licence,
            )
        xml_url = _OBJECT.format(num=num, ver=ver, ext="xml")
        xml, failure = self._get(xml_url, metadata=meta)
        if failure is not None or xml is None:
            return failure or transport_failure(self.route, url=xml_url, metadata=meta)
        if not _has_body(xml.content):
            return not_retrieved(
                self.route,
                AttemptOutcome.NOT_AVAILABLE,
                "no-body",
                url=xml_url,
                http_status=xml.status_code,
                metadata=meta,
            )
        return RouteResult(
            route=self.route,
            outcome=AttemptOutcome.RETRIEVED,
            url=xml_url,
            http_status=xml.status_code,
            content=xml.content,
            media_type=_MEDIA_TYPE,
            source_version=source_version,
            licence=licence,
            metadata=meta,
        )
