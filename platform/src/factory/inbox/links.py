"""Parse a supplied link to exactly one identifier (slice 4a ruling 5).

Pure and offline. Accepted forms: bare arXiv ids (new and old style, optional `arXiv:`
scheme) and `arxiv.org/{abs,pdf,html}/` URLs; bare DOIs, `doi:` and `doi.org` URLs, and any
URL whose path contains a DOI (`10.<4-9 digits>/…`); OpenAlex work ids and URLs; PubMed
(`pubmed.ncbi.nlm.nih.gov/<n>`, `PMID: <n>`) and PubMed Central (`PMC<n>`,
`pmc.ncbi.nlm.nih.gov/articles/PMC<n>`) links. Anything else is unsupported and yields `None`.

Invariants: the returned value is normalised with the same functions that build work
identity (`normalize_arxiv`, `normalize_doi`), so a parsed link and a retrieved record never
disagree about an identifier; a DataCite arXiv DOI (`10.48550/arXiv.<id>`) is returned as the
arXiv id it denotes; an arXiv version suffix is kept separately and dropped from `value`.
Every pattern is anchored (`fullmatch`; the one `search` looks for a DOI inside a URL path
already matched whole) and has no nested unbounded quantifiers, and input longer than
`MAX_LINK` is refused before any matching.

A `?query` or `#fragment` tail never carries an identifier, in any form, and is dropped before
percent-decoding, so `%3F` and `%23` stay part of a DOI (some Wiley DOIs end in `#`, and can
only be given encoded). The text is percent-decoded exactly once; bytes that are not UTF-8 are
unsupported. An old-style arXiv id must name a known archive, so a path such as `a/1234567` is
not one. A closing bracket that pairs with an opener inside the DOI is part of the DOI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from factory.model.work_ids import (
    TRAILING_PUNCTUATION,
    arxiv_id_from_doi,
    normalize_arxiv,
    normalize_doi,
)

MAX_LINK = 500

_NEW_ARXIV = r"\d{4}\.\d{4,5}"
# Every archive that ever issued an old-style (pre-2007) identifier.
_OLD_ARCHIVES = (
    "acc-phys|adap-org|alg-geom|ao-sci|astro-ph|atom-ph|bayes-an|chao-dyn|chem-ph|cmp-lg|"
    "comp-gas|cond-mat|cs|dg-ga|funct-an|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|math|math-ph|"
    "mtrl-th|nlin|nucl-ex|nucl-th|patt-sol|physics|plasm-ph|q-alg|q-bio|q-fin|quant-ph|"
    "solv-int|stat|supr-con"
)
_OLD_ARXIV = rf"(?:{_OLD_ARCHIVES})(?:\.[a-z]{{2}})?/\d{{7}}"
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
_PMID = r"(?P<id>[1-9]\d{0,9})"
_PMID_BARE = re.compile(rf"pmid:\s*{_PMID}", re.IGNORECASE)
_PMID_URL = re.compile(
    rf"(?:https?://)?(?:pubmed\.ncbi\.nlm\.nih\.gov|(?:www\.)?ncbi\.nlm\.nih\.gov/pubmed)/{_PMID}/?",
    re.IGNORECASE,
)
_PMCID_BARE = re.compile(r"PMC(?P<id>\d{1,12})", re.IGNORECASE)
_PMCID_URL = re.compile(
    r"(?:https?://)?(?:pmc\.ncbi\.nlm\.nih\.gov|(?:www\.)?ncbi\.nlm\.nih\.gov/pmc)"
    r"/articles/PMC(?P<id>\d{1,12})/?",
    re.IGNORECASE,
)
_QUERY_OR_FRAGMENT = re.compile(r"[?#].*$")
_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}


class IdentifierKind(StrEnum):
    ARXIV = "arxiv"
    DOI = "doi"
    OPENALEX = "openalex"
    PMID = "pmid"
    PMCID = "pmcid"
    """A PubMed id (digits) and a PubMed Central id (`PMC<digits>`); a bare number is never a
    PMID (plan pmid-seeds). A PMCID is converted to a PMID or DOI at resolution."""
    PAGE = "page"
    """A publisher page whose `citation_doi` meta tag is read once at resolution (slice 4a Later,
    plan SG). Captured only on request (`LinkInput.page`); `parse_link` never returns it."""


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


def _trim_doi(doi: str) -> str:
    """Drop trailing punctuation and slashes, keeping a bracket the DOI itself opened."""
    while doi and (doi[-1] == "/" or doi[-1] in TRAILING_PUNCTUATION):
        opener = _BRACKET_PAIRS.get(doi[-1])
        if opener is not None and doi.count(opener) >= doi.count(doi[-1]):
            break
        doi = doi[:-1]
    return doi


def _doi(raw: str) -> LinkIdentifier:
    doi = _trim_doi(normalize_doi(raw))
    bridged = arxiv_id_from_doi(doi)
    if bridged is not None:
        return LinkIdentifier(kind=IdentifierKind.ARXIV, value=bridged, version=None)
    return LinkIdentifier(kind=IdentifierKind.DOI, value=doi, version=None)


def _openalex(match: re.Match[str]) -> LinkIdentifier:
    return LinkIdentifier(
        kind=IdentifierKind.OPENALEX, value=match.group("id").upper(), version=None
    )


def _pmid(match: re.Match[str]) -> LinkIdentifier:
    return LinkIdentifier(kind=IdentifierKind.PMID, value=match.group("id"), version=None)


def _pmcid(match: re.Match[str]) -> LinkIdentifier:
    return LinkIdentifier(kind=IdentifierKind.PMCID, value=f"PMC{match.group('id')}", version=None)


def stored_link(link: str) -> str:
    """The link as an item keeps it: stripped, without a query or fragment tail."""
    return _QUERY_OR_FRAGMENT.sub("", link.strip())


def parse_link(link: str) -> LinkIdentifier | None:
    """Return the link's identifier, or `None` when the form is unsupported."""
    if len(link) > MAX_LINK:
        return None
    try:
        text = unquote(stored_link(link), errors="strict")
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    if m := _ARXIV_BARE.fullmatch(text):
        return _arxiv(m)
    if m := _OPENALEX_BARE.fullmatch(text):
        return _openalex(m)
    if m := _PMID_BARE.fullmatch(text) or _PMID_URL.fullmatch(text):
        return _pmid(m)
    if m := _PMCID_BARE.fullmatch(text) or _PMCID_URL.fullmatch(text):
        return _pmcid(m)
    if m := _DOI_BARE.fullmatch(text):
        return _doi(m.group("doi"))
    if m := _ARXIV_URL.fullmatch(text):
        return _arxiv(m)
    if m := _OPENALEX_URL.fullmatch(text):
        return _openalex(m)
    if (u := _URL.fullmatch(text)) and (d := _DOI_IN_PATH.search(u.group("path"))):
        return _doi(d.group("doi"))
    return None


def parse_page_link(link: str) -> LinkIdentifier | None:
    """An http(s) page URL as a `page` identifier: the stored link, without query or fragment.

    Only for a link the caller declared to be a publisher page; `parse_link` is tried first."""
    if len(link) > MAX_LINK:
        return None
    stored = stored_link(link)
    parts = urlsplit(stored)
    if parts.scheme not in ("http", "https") or "." not in parts.netloc:
        return None
    return LinkIdentifier(kind=IdentifierKind.PAGE, value=stored, version=None)
