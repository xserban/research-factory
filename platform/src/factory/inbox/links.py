"""Parse a supplied link to exactly one identifier (slice 4a ruling 5).

Pure and offline. Accepted forms: bare arXiv ids (new and old style, optional `arXiv:`
scheme) and `arxiv.org/{abs,pdf,html}/` URLs; bare DOIs, `doi:` and `doi.org` URLs, and any
URL whose path contains a DOI (`10.<4-9 digits>/…`); OpenAlex work ids and URLs. Anything else
is unsupported and yields `None`.

Invariants: the returned value is normalised with the same functions that build work
identity (`normalize_arxiv`, `normalize_doi`), so a parsed link and a retrieved record never
disagree about an identifier; a DataCite arXiv DOI (`10.48550/arXiv.<id>`) is returned as the
arXiv id it denotes; an arXiv version suffix is kept separately and dropped from `value`.
Every pattern is anchored (`fullmatch`; the one `search` looks for a DOI inside a URL path
already matched whole) and has no nested unbounded quantifiers, and input longer than
`MAX_LINK` is refused before any matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from factory.model.work_ids import arxiv_id_from_doi, normalize_arxiv, normalize_doi

MAX_LINK = 500

_NEW_ARXIV = r"\d{4}\.\d{4,5}"
_OLD_ARXIV = r"[a-z][a-z-]*(?:\.[a-z]{2})?/\d{7}"
_ARXIV_ID = rf"(?P<id>{_NEW_ARXIV}|{_OLD_ARXIV})(?P<version>v\d+)?"

_ARXIV_BARE = re.compile(rf"(?:arxiv:)?{_ARXIV_ID}", re.IGNORECASE)
_ARXIV_URL = re.compile(
    rf"(?:https?://)?(?:(?:www|export)\.)?arxiv\.org/(?:abs|pdf|html)/{_ARXIV_ID}(?:\.pdf)?/?",
    re.IGNORECASE,
)
_DOI_BODY = r"10\.\d{4,9}/\S+"
_DOI_BARE = re.compile(rf"(?:doi:\s*)?(?P<doi>{_DOI_BODY})", re.IGNORECASE)
_URL = re.compile(r"(?:https?://)?(?P<host>[a-z0-9.-]+\.[a-z]{2,})(?P<path>/\S*)", re.IGNORECASE)
# A DOI inside a URL path starts after a slash; the remainder of the path is the suffix.
_DOI_IN_PATH = re.compile(rf"/(?P<doi>{_DOI_BODY})", re.IGNORECASE)
_OPENALEX_BARE = re.compile(r"(?P<id>w\d+)", re.IGNORECASE)
_OPENALEX_URL = re.compile(
    r"(?:https?://)?(?:api\.)?openalex\.org/(?:works/)?(?P<id>w\d+)/?", re.IGNORECASE
)
_QUERY_OR_FRAGMENT = re.compile(r"[?#].*$")


class IdentifierKind(StrEnum):
    ARXIV = "arxiv"
    DOI = "doi"
    OPENALEX = "openalex"


@dataclass(frozen=True)
class LinkIdentifier:
    """One normalised identifier; `version` is an arXiv version suffix (`v2`) or `None`."""

    kind: IdentifierKind
    value: str
    version: str | None


def _arxiv(match: re.Match[str]) -> LinkIdentifier:
    version = match.group("version")
    return LinkIdentifier(
        kind=IdentifierKind.ARXIV,
        value=normalize_arxiv(match.group("id")),
        version=version.casefold() if version else None,
    )


def _doi(raw: str) -> LinkIdentifier:
    doi = normalize_doi(raw).rstrip("/.")
    bridged = arxiv_id_from_doi(doi)
    if bridged is not None:
        return LinkIdentifier(kind=IdentifierKind.ARXIV, value=bridged, version=None)
    return LinkIdentifier(kind=IdentifierKind.DOI, value=doi, version=None)


def _openalex(match: re.Match[str]) -> LinkIdentifier:
    return LinkIdentifier(
        kind=IdentifierKind.OPENALEX, value=match.group("id").upper(), version=None
    )


def parse_link(link: str) -> LinkIdentifier | None:
    """Return the link's identifier, or `None` when the form is unsupported."""
    if len(link) > MAX_LINK:
        return None
    text = link.strip()
    if not text:
        return None
    if m := _ARXIV_BARE.fullmatch(text):
        return _arxiv(m)
    if m := _OPENALEX_BARE.fullmatch(text):
        return _openalex(m)
    if m := _DOI_BARE.fullmatch(text):
        return _doi(m.group("doi"))
    # Only URLs remain. The query and fragment never carry the identifier we accept.
    url = _QUERY_OR_FRAGMENT.sub("", text)
    if m := _ARXIV_URL.fullmatch(url):
        return _arxiv(m)
    if m := _OPENALEX_URL.fullmatch(url):
        return _openalex(m)
    if (u := _URL.fullmatch(url)) and (d := _DOI_IN_PATH.search(u.group("path"))):
        return _doi(d.group("doi"))
    return None
