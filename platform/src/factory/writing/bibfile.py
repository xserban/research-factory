"""Minimal bibliography records of a manuscript (slice 7b, plan W-C). Pure.

Declares: `BibRecord`, `BibFileError`, `read_bib`, `read_csl`, `read_reference_list`.

Reads a companion BibTeX subset (`@type{key, field = {...} | "..." | number}`, nested braces,
unknown entry types kept; `@comment`, `@string` and `@preamble` skipped) or CSL-JSON into the fields
G1's matcher uses, and a reference-list section through G1's readers (`references/parse.py`,
`references/markers.py`, `references/bbl.py`).

Invariants:
- A record reaches no event; only its match does.
- `BibFileError` carries a fixed text, never the file's.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.model.work_ids import normalize_arxiv, normalize_doi
from factory.references.bbl import read_bbl
from factory.references.markers import find_contexts
from factory.references.parse import RefFields, parse_bibliography, parse_entry_fields
from factory.writing.segment import Format

YEAR_MIN, YEAR_MAX = 1000, 2999

_SKIPPED = frozenset({"comment", "string", "preamble"})
_ENTRY = re.compile(r"@\s*([A-Za-z]+)\s*[{(]")
_FIELD = re.compile(r"\s*,?\s*([A-Za-z][\w:.\-]*)\s*=\s*")
_BARE = re.compile(r"[^\s,#}]+")
_CONCAT = re.compile(r"\s*#\s*")
_AND = re.compile(r"\s+and\s+", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(\S+)", re.IGNORECASE)
_ARXIV_NOTE = re.compile(r"arxiv\s*:\s*(\S+)", re.IGNORECASE)
_DOI_URL = re.compile(r"doi\.org/(\S+)", re.IGNORECASE)
_COMMAND = re.compile(r"\\[a-zA-Z]+\*?")
_ACCENT = re.compile(r"\\[`'^\"~=.]")
_ESCAPED = re.compile(r"\\([&%_#$])")
_ENTRY_START = re.compile(r"^\s*(?:\[[^\]\s]{1,20}\]|\(\d{1,4}\)|\d{1,4}[.)]\s|[-*+]\s)")
_BULLET = re.compile(r"^\s*[-*+]\s+")


class BibFileError(ValueError):
    """A bibliography that cannot be read. The text is fixed; it never quotes the file."""


@dataclass(frozen=True)
class BibRecord:
    """One entry: `key` as the manuscript cites it; `doi` and `arxiv` are normalised."""

    key: str
    title: str | None
    authors: tuple[str, ...]
    year: int | None
    doi: str | None
    arxiv: str | None

    @property
    def fields(self) -> RefFields:
        """The record as G1's matcher reads an entry."""
        first = self.authors[0] if self.authors else None
        return RefFields(self.doi, self.arxiv, None, self.year, first, self.title, None)


def _plain(value: str) -> str:
    """LaTeX markup reduced to text: accents and commands dropped, their arguments kept."""
    value = _ESCAPED.sub(r"\1", _ACCENT.sub("", value))
    value = _COMMAND.sub("", value).replace("~", " ").replace("{", "").replace("}", "")
    return " ".join(value.split())


def _closing(text: str, start: int, closing: str) -> int | None:
    """The index of what closes the opener at `start`, at brace depth 0, or None."""
    depth = 0
    i = start if closing == "}" else start + 1  # a brace opener counts itself
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        depth += (c == "{") - (c == "}")
        if c == closing and depth == 0:
            return i
        i += 1
    return None


def _quoted_end(body: str, start: int) -> int | None:
    depth, i = 0, start + 1
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 2
            continue
        depth += (c == "{") - (c == "}")
        if c == '"' and depth == 0:
            return i
        i += 1
    return None


def _value(body: str, i: int) -> tuple[str, int]:
    """One value starting at `i`: its text and the index after it. A bare word is a macro, whose
    text is unknown here; a bare number is itself."""
    if body[i] in '{"':
        end = _closing(body, i, "}") if body[i] == "{" else _quoted_end(body, i)
        if end is None:
            raise BibFileError("a value does not close")
        return body[i + 1 : end], end + 1
    m = _BARE.match(body, i)
    if m is None:
        return "", i + 1
    return (m.group(0) if m.group(0).isdigit() else ""), m.end()


def _fields(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    i = 0
    while (m := _FIELD.match(body, i)) is not None:
        i = m.end()
        parts: list[str] = []
        while i < len(body):
            value, i = _value(body, i)
            parts.append(value)
            more = _CONCAT.match(body, i)
            if more is None:
                break
            i = more.end()
        out.setdefault(m.group(1).casefold(), "".join(parts))
    return out


def _split_authors(value: str) -> list[str]:
    names: list[str] = []
    depth, start, i = 0, 0, 0
    while i < len(value):
        depth += (value[i] == "{") - (value[i] == "}")
        m = _AND.match(value, i) if depth == 0 else None
        if m is not None:
            names.append(value[start:i])
            start = i = m.end()
            continue
        i += 1
    names.append(value[start:])
    return names


def _display(name: str) -> str:
    """`Last, First` as `First Last`: the matcher reads a surname as the last token."""
    plain = _plain(name)
    last, comma, first = plain.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if comma else plain


def _year(value: object) -> int | None:
    m = _YEAR.search(str(value))
    year = int(m.group(1)) if m else None
    return year if year is not None and YEAR_MIN <= year <= YEAR_MAX else None


def _doi(value: str | None) -> str | None:
    if not value:
        return None
    m = _DOI_URL.search(value)
    return normalize_doi(m.group(1) if m else value)


def _arxiv(*values: str | None) -> str | None:
    for value in values:
        m = (_ARXIV_URL.search(value) or _ARXIV_NOTE.search(value)) if value else None
        if m is not None:
            return normalize_arxiv(m.group(1).rstrip(".,;"))
    return None


def _nfc(key: str) -> str:
    return unicodedata.normalize("NFC", key.strip())


def _record(body: str) -> BibRecord | None:
    key, comma, rest = body.partition(",")
    if not key.strip():
        return None
    f = _fields(rest) if comma else {}
    eprint = f.get("eprint")
    prefix = (f.get("archiveprefix") or f.get("eprinttype") or "").casefold()
    arxiv = normalize_arxiv(eprint) if eprint and prefix == "arxiv" else None
    return BibRecord(
        key=_nfc(key),
        title=_plain(f.get("title", "")) or None,
        authors=tuple(a for a in map(_display, _split_authors(f.get("author", ""))) if a),
        year=_year(f.get("year") or f.get("date") or ""),
        doi=_doi(f.get("doi")),
        arxiv=arxiv or _arxiv(f.get("url"), f.get("journal"), f.get("note")),
    )


def read_bib(text: str) -> list[BibRecord]:
    """The entries of a BibTeX file, in file order. Raises `BibFileError` on an entry or a value
    that does not close."""
    records: list[BibRecord] = []
    pos = 0
    while (m := _ENTRY.search(text, pos)) is not None:
        end = _closing(text, m.end() - 1, "}" if text[m.end() - 1] == "{" else ")")
        if end is None:
            raise BibFileError("an entry does not close")
        pos = end + 1
        if m.group(1).casefold() not in _SKIPPED:
            record = _record(text[m.end() : end])
            if record is not None:
                records.append(record)
    return records


def _csl_author(author: object) -> str:
    if not isinstance(author, Mapping):
        return ""
    if author.get("literal"):
        return str(author["literal"])
    return " ".join(str(author[k]) for k in ("given", "family") if author.get(k))


def _csl_year(item: Mapping[str, Any]) -> int | None:
    issued = item.get("issued")
    if not isinstance(issued, Mapping):
        return None
    parts = issued.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        return _year(parts[0][0])
    return _year(issued.get("raw", ""))


def _opt(item: Mapping[str, Any], key: str) -> str | None:
    value = item.get(key)
    return value if isinstance(value, str) and value else None


def read_csl(text: str) -> list[BibRecord]:
    """The items of a CSL-JSON file (a list, or one item). Raises `BibFileError` when it is not."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise BibFileError("not JSON") from None
    items = [data] if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise BibFileError("not a list of items")
    records: list[BibRecord] = []
    for item in items:
        if not isinstance(item, dict) or item.get("id") is None:
            raise BibFileError("an item has no id")
        authors = item.get("author")
        names = authors if isinstance(authors, list) else []
        records.append(
            BibRecord(
                key=_nfc(str(item["id"])),
                title=_opt(item, "title"),
                authors=tuple(a for a in map(_csl_author, names) if a),
                year=_csl_year(item),
                doi=_doi(_opt(item, "DOI")),
                arxiv=_arxiv(_opt(item, "URL"), _opt(item, "note")),
            )
        )
    return records


def _blocks(section: str) -> list[str]:
    """The entries of a list section: a blank line, a label or a bullet starts one; a wrapped line
    continues it."""
    blocks: list[list[str]] = []
    fresh = True
    for line in section.splitlines():
        if not line.strip():
            fresh = True
            continue
        if fresh or _ENTRY_START.match(line):
            blocks.append([])
        blocks[-1].append(_BULLET.sub("", line).strip())
        fresh = False
    return [" ".join(b) for b in blocks]


def _as_record(key: str, fields: RefFields) -> BibRecord:
    authors = (fields.first_author,) if fields.first_author else ()
    return BibRecord(key, fields.title, authors, fields.year, fields.doi, fields.arxiv)


def read_reference_list(section: str, fmt: Format, numbers: Iterable[str] = ()) -> list[BibRecord]:
    """The records of a manuscript's own reference list: in LaTeX each `\\bibitem` under its key;
    elsewhere the entry each of `numbers` maps to through G1's markers, under that number."""
    if fmt == "latex":
        entries = read_bbl(section.encode())
        return [_as_record(_nfc(e.key), parse_entry_fields(e.text)) for e in entries]
    anchors = (
        Anchor(f"b{i}", AnchorKind.BIBLIOGRAPHY_ENTRY, None, block)
        for i, block in enumerate(_blocks(section), start=1)
    )
    bibliography = parse_bibliography(Manifest(tuple(anchors)))
    by_ordinal = {e.ordinal: e for e in bibliography.entries}
    wanted = sorted({n for n in numbers if n.isascii() and n.isdigit()})
    probes = (Anchor(f"n{n}", AnchorKind.PARAGRAPH, None, f"[{n}]") for n in wanted)
    contexts, _ = find_contexts(Manifest(tuple(probes)), bibliography)
    return [
        _as_record(c.citing_anchor[1:], by_ordinal[c.entry].fields)
        for c in contexts
        if c.entry is not None
    ]
