"""Bibliography parser: entries of a document manifest and the fields recoverable from each.

Pure and deterministic: the same manifest and `PARSER_VERSION` give identical entries. Only DOI,
arXiv id, URL and year are claimed reliable; first author, title and venue are best effort and
`None` when no pattern matches. Entry text is truncated at `MAX_ENTRY_CHARS`, with a flag.
Fields are parsed from the first `MAX_FIELD_CHARS` (4000) characters of an entry.
"""

import re
from dataclasses import dataclass
from typing import Literal

from factory.document.anchorise import BIBLIOGRAPHY_HEADINGS, normalise_heading
from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.model.work_ids import normalize_arxiv, normalize_doi

PARSER = "refparse"
PARSER_VERSION = "2"
MAX_ENTRY_CHARS = 1000

MAX_FIELD_CHARS = 4000  # entry text examined for fields; longer tails are ignored


def _uppercase_class() -> str:
    """A regex character-class body of the BMP uppercase letters (`re` has no `\\p{Lu}`)."""
    ranges: list[tuple[int, int]] = []
    for cp in range(0x10000):
        if chr(cp).isupper():
            if ranges and ranges[-1][1] == cp - 1:
                ranges[-1] = (ranges[-1][0], cp)
            else:
                ranges.append((cp, cp))
    return "".join(f"\\u{a:04x}" if a == b else f"\\u{a:04x}-\\u{b:04x}" for a, b in ranges)


UPPER = _uppercase_class()
_LOWER_WORD = r"(?:[^\W\d_]|['\u2019\-])"

_HEADING_PREFIX_RE = re.compile(r"^\s*#+\s*")
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

_SURNAME = rf"[{UPPER}][\w'\u2019\-]+"
_AUTHOR_COMMA_RE = re.compile(rf"^({_SURNAME}),\s*(?:[{UPPER}]\.|[{UPPER}][^\W\d_]+)")
_AUTHOR_VANCOUVER_RE = re.compile(rf"^({_SURNAME}) [{UPPER}]{{1,3}}\b[,.]")
_AUTHOR_INITIALS_RE = re.compile(
    rf"^(?:[{UPPER}]\.[\s\-]*)+(?:(?:van|von|de|der|den|di|da|le|la)\s+)*({_SURNAME})"
)
_AUTHOR_GIVEN_RE = re.compile(rf"^[{UPPER}][^\W\d_]+\s+({_SURNAME})\s*(?:,|and\b|&|et al)")
_PARTICLES = r"(?i:(?:van|von|de|der|den|di|da|del|dos|du|le|la|ten|ter)\s+)*"
_INITIALS = rf"(?:[{UPPER}]\.[\s\-]*){{1,4}}"
_NAME_INITIALS_FIRST_RE = re.compile(
    rf"{_INITIALS}{_PARTICLES}(?P<sur>{_SURNAME}|[{UPPER}](?=\s*(?:,|and\b|&|et\s+al\b)))"
)
_NAME_SURNAME_FIRST_RE = re.compile(rf"(?P<sur>{_PARTICLES}{_SURNAME}),\s*{_INITIALS}")
_NAME_SEP_RE = re.compile(r"\s*(?:,\s*(?:and\s+|&\s*)?|;\s*|\s+and\s+|\s*&\s*)")
_ET_AL_RE = re.compile(r"\s*,?\s*et\s+al\b\.?")
_BLOCK_END_RE = re.compile(r"\s*[.:]?\s*")
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

    With neither, the result has no entries. The flag is `bibliography-without-entries` when a
    bibliography heading exists but has no paragraph entries (for example a list), else
    `no-bibliography`; `entry_anchors` is then `"b"` by convention, there being nothing to anchor.
    """
    b_anchors = [a for a in manifest.anchors if a.kind is AnchorKind.BIBLIOGRAPHY_ENTRY]
    if b_anchors:
        return Bibliography(_entries(b_anchors), "b", ())
    sections = _bibliography_sections(manifest)
    for section in sections:
        paragraphs = [
            a for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH and a.parent == section.id
        ]
        if paragraphs:
            return Bibliography(_entries(paragraphs), "paragraph", ("entry-anchors-paragraph",))
    flag = "bibliography-without-entries" if sections else "no-bibliography"
    return Bibliography((), "b", (flag,))


def _heading_text(anchor: Anchor) -> str:
    lines = anchor.text.strip().splitlines()
    return normalise_heading(_HEADING_PREFIX_RE.sub("", lines[0] if lines else ""))


def _bibliography_sections(manifest: Manifest) -> list[Anchor]:
    return [
        a
        for a in manifest.anchors
        if a.kind is AnchorKind.SECTION and _heading_text(a) in BIBLIOGRAPHY_HEADINGS
    ]


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
                fields=parse_entry_fields(raw[:MAX_FIELD_CHARS]),
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
    work = " ".join(text.split())[:MAX_FIELD_CHARS]
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


def _vancouver_end(previous: str) -> bool:
    """True if `previous` is a surname: a single initial after it ends a Vancouver author list."""
    return re.fullmatch(rf"[{UPPER}]{_LOWER_WORD}+", previous) is not None


def _boundaries(text: str) -> list[int]:
    """Indices just after sentence-ending periods that do not follow an author initial.

    Linear: each period inspects only the one or two words before it.
    """
    out: list[int] = []
    for m in re.finditer(r"\.\s+|\.$", text):
        start = text.rfind(" ", 0, m.start()) + 1
        word = text[start : m.start()].split("-")[-1]
        if re.fullmatch(rf"[{UPPER}]", word):
            prev_start = text.rfind(" ", 0, max(start - 1, 0)) + 1 if start > 0 else 0
            previous = text[prev_start : start - 1] if start > 0 else ""
            if not (start > 0 and _vancouver_end(previous)):
                continue
        out.append(m.end())
    return out


def _tidy(segment: str) -> str | None:
    seg = re.sub(r"\(?(?:19|20)\d{2}[a-z]?\)?", "", segment)
    seg = " ".join(seg.split()).strip(" ,;:.-\u2013()[]")
    return seg or None


def _author_block(text: str) -> tuple[str, int] | None:
    """`(first surname, end index)` of a leading author block of initials, else None.

    Names are `A. B. Surname` or `Surname, A. B.`, joined by `,` `;` `and` `&` and optionally
    closed by `et al.`. The end index is after the block and the `.` or `:` that may follow it;
    the source text sometimes has no such mark (`... Steiner A tale of ...`), so the title starts
    at the next token. Each name needs at least one initial with a period: a list of full names
    is not recognised. Linear: every step consumes input.
    """
    pos = 0
    end = 0
    first: str | None = None
    prev_start = -1
    last_start = -1  # where the last name began, and the block would end without it
    while True:
        m = _NAME_SURNAME_FIRST_RE.match(text, pos) or _NAME_INITIALS_FIRST_RE.match(text, pos)
        if not m:
            break
        first = first or m.group("sur")
        prev_start, last_start = last_start, pos
        end = m.end()
        et_al = _ET_AL_RE.match(text, end)
        if et_al:
            end = et_al.end()
            break
        sep = _NAME_SEP_RE.match(text, end)
        if not sep:
            break
        pos = sep.end()
    if first is None:
        return None
    closed = _BLOCK_END_RE.match(text, end)
    if closed is None:
        return None
    # Unmarked block ending in a lowercase word (`J. Doe, A. Roe, C. Title of the paper`): the
    # last "name" is the first word of the title, so the block stops before it.
    if (
        prev_start >= 0
        and not text[end : closed.end()].strip()
        and text[closed.end() : closed.end() + 1].islower()
    ):
        return first, last_start
    return first, closed.end()


def _split_title_venue(rest: str) -> tuple[str | None, str | None]:
    """Title and venue of `rest`, which starts at the title (the author block is gone)."""
    cuts = _boundaries(rest)
    stop = cuts[0] if cuts else len(rest)
    title = rest[:stop].strip().rstrip(".").strip()
    if not title:
        return None, None
    end = cuts[1] if len(cuts) > 1 else len(rest)
    return title, _tidy(rest[stop:end])


def _title_venue(text: str) -> tuple[str | None, str | None]:
    quoted = _QUOTED_RE.search(text)
    if quoted:
        return quoted.group(1).strip(" ,."), _tidy(text[quoted.end() :])
    py = _PAREN_YEAR_TITLE_RE.search(text)
    if py:
        title = py.group(1).strip().rstrip(".?!").strip()
        return (title or None), _tidy(py.group(2))
    block = _author_block(text)
    if block is not None and text[block[1] :].strip():
        title, venue = _split_title_venue(text[block[1] :])
        if title is not None:
            return title, venue
    cuts = _boundaries(text)
    if not cuts:
        return None, None
    stop = cuts[1] if len(cuts) > 1 else len(text)
    title = text[cuts[0] : stop].strip().rstrip(".").strip()
    if not title:
        return None, None
    end = cuts[2] if len(cuts) > 2 else len(text)
    return title, _tidy(text[stop:end])
