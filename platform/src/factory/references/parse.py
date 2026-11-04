"""Bibliography parser: entries of a document manifest and the fields recoverable from each.

Pure and deterministic: the same manifest and `PARSER_VERSION` give identical entries. Only DOI,
arXiv id, URL and year are claimed reliable; first author, title and venue are best effort and
`None` when no pattern matches. Entry text is truncated at `MAX_ENTRY_CHARS`, with a flag.
"""

import re
from dataclasses import dataclass
from typing import Literal

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.model.work_ids import normalize_arxiv, normalize_doi

PARSER = "refparse"
PARSER_VERSION = "1"
MAX_ENTRY_CHARS = 1000

# Folded heading texts (number stripped) that open a bibliography section.
BIBLIOGRAPHY_HEADINGS = frozenset(
    {"references", "bibliography", "literature cited", "works cited", "reference list"}
)

_ENTRY_ID_RE = re.compile(r"^b(\d+)$")
_HEADING_PREFIX_RE = re.compile(r"^\s*#+\s*")
_HEADING_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+")
_LABEL_RE = re.compile(r"^\s*(?:\[([^\]\s]{1,20})\]|\((\d{1,4})\)|(\d{1,4})[.)])\s*")

_DOI_RE = re.compile(
    r"(?:(?:https?://(?:dx\.)?doi\.org/)|(?:\bdoi\s*:?\s*))?(10\.\d{4,9}/\S+)", re.IGNORECASE
)
_ARXIV_RE = re.compile(
    r"(?:\barxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)"
    r"((?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<![\d.])((?:19|20)\d{2})(?![\d])")
_TRAIL = ".,;:'\"]>}"

_SURNAME = r"[A-Z][\w'\u2019\-]+"
_AUTHOR_COMMA_RE = re.compile(rf"^({_SURNAME}),\s*(?:[A-Z]\.|[A-Z][a-z]+)")
_AUTHOR_VANCOUVER_RE = re.compile(rf"^({_SURNAME}) [A-Z]{{1,3}}\b[,.]")
_AUTHOR_INITIALS_RE = re.compile(
    rf"^(?:[A-Z]\.[\s\-]*)+(?:(?:van|von|de|der|den|di|da|le|la)\s+)*({_SURNAME})"
)
_AUTHOR_GIVEN_RE = re.compile(rf"^[A-Z][a-z]+\s+({_SURNAME})\s*(?:,|and\b|&|et al)")
_PAREN_YEAR_TITLE_RE = re.compile(r"\((?:19|20)\d{2}[a-z]?\)\.?\s*([^.?!]+[.?!]?)(.*)$", re.DOTALL)
_QUOTED_RE = re.compile(r"[“\"]([^”\"]{8,})[”\"]")
_PREFIX_RE = re.compile(r"(?i)\b(?:doi|arxiv|url|available at|accessed)\s*:?\s*$")


@dataclass(frozen=True)
class RefFields:
    """Fields recovered from one entry; `doi` and `arxiv` are normalised."""

    doi: str | None
    arxiv: str | None
    url: str | None
    year: int | None
    first_author: str | None
    title: str | None
    venue: str | None


@dataclass(frozen=True)
class Entry:
    """One bibliography entry. `text` is the raw text, cut at `MAX_ENTRY_CHARS` (`truncated`)."""

    ordinal: int
    anchor: str
    label: str | None
    text: str
    truncated: bool
    fields: RefFields


@dataclass(frozen=True)
class Bibliography:
    """Entries in document order. Ordinals run 1, 2, … without gaps."""

    entries: tuple[Entry, ...]
    entry_anchors: Literal["b", "paragraph"]
    flags: tuple[str, ...]


def parse_bibliography(manifest: Manifest) -> Bibliography:
    """Entries from `b<n>` anchors; else the paragraphs of the bibliography section.

    With neither, the result has no entries and the flag `no-bibliography` (`entry_anchors` is
    then `"b"` by convention, there being nothing to anchor).
    """
    b_anchors = [a for a in manifest.anchors if _ENTRY_ID_RE.match(a.id)]
    if b_anchors:
        return Bibliography(_entries(b_anchors), "b", ())
    section = _bibliography_section(manifest)
    if section is not None:
        paragraphs = [
            a for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH and a.parent == section.id
        ]
        if paragraphs:
            return Bibliography(_entries(paragraphs), "paragraph", ("entry-anchors-paragraph",))
    return Bibliography((), "b", ("no-bibliography",))


def _heading_text(anchor: Anchor) -> str:
    lines = anchor.text.strip().splitlines()
    text = _HEADING_PREFIX_RE.sub("", lines[0] if lines else "")
    text = _HEADING_NUMBER_RE.sub("", text.strip())
    return text.strip().rstrip(":").strip().casefold()


def _bibliography_section(manifest: Manifest) -> Anchor | None:
    for a in manifest.anchors:
        if a.kind is AnchorKind.SECTION and _heading_text(a) in BIBLIOGRAPHY_HEADINGS:
            return a
    return None


def _entries(anchors: list[Anchor]) -> tuple[Entry, ...]:
    out: list[Entry] = []
    for ordinal, a in enumerate(anchors, start=1):
        raw = " ".join(a.text.split())
        label_match = _LABEL_RE.match(raw)
        label = next((g for g in label_match.groups() if g), None) if label_match else None
        out.append(
            Entry(
                ordinal=ordinal,
                anchor=a.id,
                label=label,
                text=raw[:MAX_ENTRY_CHARS],
                truncated=len(raw) > MAX_ENTRY_CHARS,
                fields=parse_entry_fields(raw),
            )
        )
    return tuple(out)


def _clean_tail(token: str) -> str:
    token = token.rstrip(_TRAIL)
    while token.endswith(")") and token.count(")") > token.count("("):
        token = token[:-1].rstrip(_TRAIL)
    return token


def parse_entry_fields(text: str) -> RefFields:
    """Recover the fields of one entry by ordered rules (DOI, arXiv, URL, then the rest)."""
    work = " ".join(text.split())
    label = _LABEL_RE.match(work)
    if label:
        work = work[label.end() :]

    doi: str | None = None
    arxiv: str | None = None
    url: str | None = None

    m = _DOI_RE.search(work)
    if m:
        doi = normalize_doi(_clean_tail(m.group(1)))
        work = work[: m.start()] + " " + work[m.end() :]
    m = _ARXIV_RE.search(work)
    if m:
        arxiv = normalize_arxiv(m.group(1))
        work = work[: m.start()] + " " + work[m.end() :]
    m = _URL_RE.search(work)
    if m:
        url = _clean_tail(m.group(0))
        work = work[: m.start()] + " " + work[m.end() :]
    work = _PREFIX_RE.sub("", " ".join(work.split())).strip()

    years = _YEAR_RE.findall(work)
    year = int(years[-1]) if years else None
    title, venue = _title_venue(work)
    return RefFields(doi, arxiv, url, year, _first_author(work), title, venue)


def _first_author(text: str) -> str | None:
    for pattern in (_AUTHOR_COMMA_RE, _AUTHOR_VANCOUVER_RE, _AUTHOR_INITIALS_RE, _AUTHOR_GIVEN_RE):
        m = pattern.match(text)
        if m:
            return m.group(1)
    return None


def _vancouver_end(words: list[str]) -> bool:
    """True for `Surname I.` (initials after a surname, no comma): the end of an author list."""
    return len(words) > 1 and re.fullmatch(r"[A-Z][a-z'\u2019\-]+", words[-2]) is not None


def _boundaries(text: str) -> list[int]:
    """Indices just after sentence-ending periods that do not follow an author initial."""
    out: list[int] = []
    for m in re.finditer(r"\.\s+|\.$", text):
        words = text[: m.start()].split(" ")
        if re.fullmatch(r"[A-Z]", words[-1].split("-")[-1]) and not _vancouver_end(words):
            continue
        out.append(m.end())
    return out


def _tidy(segment: str) -> str | None:
    seg = re.sub(r"\(?(?:19|20)\d{2}[a-z]?\)?", "", segment)
    seg = " ".join(seg.split()).strip(" ,;:.-\u2013()[]")
    return seg or None


def _title_venue(text: str) -> tuple[str | None, str | None]:
    quoted = _QUOTED_RE.search(text)
    if quoted:
        return quoted.group(1).strip(" ,."), _tidy(text[quoted.end() :])
    py = _PAREN_YEAR_TITLE_RE.search(text)
    if py:
        title = py.group(1).strip().rstrip(".?!").strip()
        return (title or None), _tidy(py.group(2))
    cuts = _boundaries(text)
    if not cuts:
        return None, None
    stop = cuts[1] if len(cuts) > 1 else len(text)
    title = text[cuts[0] : stop].strip().rstrip(".").strip()
    if not title:
        return None, None
    end = cuts[2] if len(cuts) > 2 else len(text)
    return title, _tidy(text[stop:end])
