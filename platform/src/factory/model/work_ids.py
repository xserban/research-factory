"""Deterministic identity for works.

A work's id must be stable across re-runs, or every search re-run churns the corpus and
`rf trace` points at files that no longer exist. Identity is therefore derived from the
work's own content, never from retrieval order, timestamps, or the source that found it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

WORK_ID_RE = r"^rf:\S+-[0-9a-f]{8}$"
TRAILING_PUNCTUATION = ".,;:)]}"
"""Characters that end a sentence around an identifier rather than the identifier itself."""
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE)
_ARXIV_VERSION = re.compile(r"v\d+$", re.IGNORECASE)
_ARXIV_URL = re.compile(
    r"^(?:https?://)?(?:(?:www|export)\.)?arxiv\.org/(?:abs|pdf)/", re.IGNORECASE
)
_QUERY_OR_FRAGMENT = re.compile(r"[?#].*$")
_ARXIV_SCHEME = re.compile(r"^arxiv:", re.IGNORECASE)
_PDF_SUFFIX = re.compile(r"\.pdf$", re.IGNORECASE)
_PMID_PREFIX_RE = re.compile(r"^pmid\s*:\s*", re.IGNORECASE)
# DataCite mints a DOI for every arXiv preprint. OpenAlex returns that DOI where the arXiv
# adapter returns the bare id, so without this the same preprint arrives as two works.
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(?P<id>.+)$", re.IGNORECASE)

# Words too common to make a slug recognisable.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "and",
        "or",
        "in",
        "on",
        "at",
        "to",
        "with",
        "from",
        "via",
        "using",
        "towards",
        "toward",
    }
)


def normalize_title(title: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    Used for both identity hashing and (later) dedup title matching, so the two can never
    disagree about whether two titles are the same string.
    """
    folded = unicodedata.normalize("NFKD", title)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = _PUNCT.sub(" ", folded.casefold())
    return _WS.sub(" ", folded).strip()


def nfc_matches(work_id: str, stored: Iterable[str]) -> list[str]:
    """The stored ids `work_id` names: `[work_id]` when it is stored as given, else every stored
    id whose NFC form equals its NFC form (IDEA-66).

    `normalize_title` applies NFKD, so a Hangul word of an id is stored as jamo while a model or
    a person writes it composed; the two look identical and differ as strings. The ids are
    never rewritten; a caller uses the one match's spelling and refuses several.
    """
    pool = list(stored)
    if work_id in pool:
        return [work_id]
    folded = unicodedata.normalize("NFC", work_id)
    return sorted({w for w in pool if unicodedata.normalize("NFC", w) == folded})


def normalize_doi(doi: str) -> str:
    """Strip resolver prefixes and casefold. DOIs are case-insensitive by specification."""
    return _DOI_PREFIX.sub("", doi.strip()).casefold()


def normalize_arxiv(arxiv_id: str) -> str:
    """Strip the URL form, the `arXiv:` scheme, a `.pdf` suffix and any version suffix.

    The URL form may omit the scheme and may use the `www.` or `export.` host; any `?query` or
    `#fragment` is dropped, and the `v<N>` suffix is matched case-insensitively.

    `2301.01234v3` and `2301.01234` are the same work; keeping the version in the identity
    would mint a new work every time a preprint is revised. Only those known wrappers are
    removed: an old-style id such as `hep-th/9901001` keeps its archive prefix, because
    `hep-th/9901001` and `cond-mat/9901001` are different papers that share a number.
    """
    ident = _QUERY_OR_FRAGMENT.sub("", arxiv_id.strip())
    ident = _ARXIV_URL.sub("", ident, count=1)
    ident = _ARXIV_SCHEME.sub("", ident, count=1)
    ident = _PDF_SUFFIX.sub("", ident)
    return _ARXIV_VERSION.sub("", ident).casefold()


def arxiv_id_from_doi(doi: str) -> str | None:
    """Recover the arXiv id from a DataCite arXiv DOI, if that is what this is."""
    match = _ARXIV_DOI.match(normalize_doi(doi))
    return normalize_arxiv(match.group("id")) if match else None


def _surname(author: str) -> str:
    """Best-effort surname from a display name. Latin-alphabet assumption, stated plainly."""
    cleaned = normalize_title(author)
    if not cleaned:
        return "anon"
    return cleaned.split()[-1]


def _title_slug(title: str, words: int = 3) -> str:
    tokens = [t for t in normalize_title(title).split() if t not in _STOPWORDS]
    return "-".join(tokens[:words]) or "untitled"


def work_id(
    *,
    title: str,
    authors: list[str],
    year: int | None,
    doi: str | None = None,
    arxiv: str | None = None,
) -> str:
    """Build a stable `rf:` identifier.

    The hash basis is the strongest available identifier, in order: DOI, then arXiv id, then
    a normalised title/author/year triple. This ordering matters for stability — a work first
    seen as a bare preprint and later matched to a DOI would otherwise change identity, which
    is the one thing an identifier may never do.

    The human-readable slug is cosmetic. Only the hash carries identity, so two works with
    identical slugs remain distinct.
    """
    # A DataCite arXiv DOI denotes the same preprint as the bare id. Folding them here means
    # the two records share an identity rather than relying on dedup to notice afterwards.
    if doi and (bridged := arxiv_id_from_doi(doi)):
        arxiv, doi = bridged, None

    if doi:
        basis = f"doi:{normalize_doi(doi)}"
    elif arxiv:
        basis = f"arxiv:{normalize_arxiv(arxiv)}"
    else:
        first = _surname(authors[0]) if authors else "anon"
        basis = f"tay:{first}|{year or ''}|{normalize_title(title)}"

    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:8]
    surname = _surname(authors[0]) if authors else "anon"
    return f"rf:{surname}{year or ''}-{_title_slug(title)}-{digest}"


def normalize_pmid(value: str) -> str:
    """The bare PMID: stripped, a `PMID:` or `pmid:` prefix and leading zeros removed (a PMID is
    a positive integer). Raises ValueError unless the rest is ASCII digits, not all zero."""
    stripped = _PMID_PREFIX_RE.sub("", value.strip()).strip()
    if not (stripped.isascii() and stripped.isdigit()):
        raise ValueError("pmid must be digits only, optionally prefixed `PMID:`")
    bare = stripped.lstrip("0")
    if not bare:
        raise ValueError("pmid must be a positive integer")
    return bare


def work_pmid_key(value: str | None) -> str | None:
    """The normalised PMID of a work's stored identifier, or None when absent or malformed.
    The one way the work side is compared with a seed's `pmid` key."""
    if not value or not value.strip():
        return None
    try:
        return normalize_pmid(value)
    except ValueError:
        return None
