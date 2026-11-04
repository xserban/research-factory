"""Anchor grammar and manifest of a canonical Markdown document.

An anchor is the HTML comment-free tag `<a id="ID"></a>` alone on its own line, immediately
followed by the element it names (a heading, a paragraph, a table, a figure caption or an
equation). Page anchors `p<n>` mark a page break and name no element. Table cells `t<n>.r<r>.c<c>`
are derived from position and are never written in the Markdown.

Invariants of a parsed `Manifest`:
- every anchor id matches `ANCHOR_RE` and occurs once;
- every non-page anchor is followed on the next line by an element of the matching kind;
- every paragraph id `s<x>.p<k>` names section `s<x>` (`s0` is implicit);
- every top-level table is rectangular, and each `t<n>` table yields one cell anchor per cell;
- anchors are in document order, a table's cells directly after the table.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from markdown_it import MarkdownIt
from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.errors import FactoryError

ANCHOR_RE = re.compile(r"^(?:s\d+(?:\.\d+)*(?:\.p\d+)?|p\d+|t\d+|f\d+\.cap|e\d+)$")
_ANCHOR_LINE_RE = re.compile(r'<a id="([^"]*)"></a>')
_ANCHOR_OCCURRENCE_RE = re.compile(r"<a\s+id=")
_PARAGRAPH_ID_RE = re.compile(r"s\d+(?:\.\d+)*\.p\d+")
_SECTION_ID_RE = re.compile(r"s\d+(?:\.\d+)*")
_PAGE_ID_RE = re.compile(r"p\d+")
_TABLE_ID_RE = re.compile(r"t\d+")
_CAPTION_ID_RE = re.compile(r"f\d+\.cap")
_EQUATION_ID_RE = re.compile(r"e\d+")
_CELL_ID_RE = re.compile(r"t\d+\.r\d+\.c\d+")
_ENTRY_KEYS = frozenset({"id", "kind", "parent", "text"})

MARKDOWN = MarkdownIt("commonmark").enable("table").disable(["html_block", "html_inline"])


class ManifestError(FactoryError):
    """The Markdown breaks the anchor grammar or the table rules; nothing is manifested."""


class AnchorKind(StrEnum):
    """What an anchored element is."""

    SECTION = "section"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    CELL = "cell"
    FIGURE_CAPTION = "figure_caption"
    EQUATION = "equation"
    PAGE = "page"


@dataclass(frozen=True)
class Anchor:
    """One addressable element.

    `parent` is the section for a section (its parent section, None at top level), the section for
    a paragraph (`s0` for the preamble), the enclosing section for a table, figure caption or
    equation (None before the first section), the table for a cell, and None for a page.
    `text` is the element's Markdown source without the anchor line; a cell's text is unescaped
    and stripped.
    """

    id: str
    kind: AnchorKind
    parent: str | None
    text: str


@dataclass(frozen=True)
class Manifest:
    """The anchors of one document, in document order."""

    anchors: tuple[Anchor, ...]

    def get(self, anchor_id: str) -> Anchor | None:
        """The anchor with this id, or None."""
        return next((a for a in self.anchors if a.id == anchor_id), None)

    @classmethod
    def from_json(cls, data: bytes) -> "Manifest":
        """Read the output of `to_json`; the inverse of it.

        Raises `ManifestError` unless `data` is a JSON list of objects with exactly the keys `id`,
        `kind`, `parent` and `text`, with a valid anchor or cell id, a valid `AnchorKind` value, a
        string or null parent and a string text.
        """
        try:
            body: object = json.loads(data)
        except ValueError as exc:
            raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
        if not isinstance(body, list):
            raise ManifestError("manifest must be a JSON list")
        return cls(tuple(_anchor_from_entry(entry, i) for i, entry in enumerate(body)))

    def to_json(self) -> bytes:
        """Canonical JSON of the anchors; equal manifests give equal bytes."""
        body: list[JsonValue] = [
            {"id": a.id, "kind": a.kind.value, "parent": a.parent, "text": a.text}
            for a in self.anchors
        ]
        return canonical_json(body)


@dataclass(frozen=True)
class _Anchor:
    """An anchor line found in the source."""

    line: int
    id: str


@dataclass(frozen=True)
class _Element:
    """A block element; `start` is its first source line (0-based)."""

    start: int
    kind: str  # "heading", "paragraph", "table" or "other"
    text: str
    lines: tuple[str, ...]


_Unit = _Anchor | _Element


def parse_manifest(markdown: str) -> Manifest:
    """Read the anchors of a canonical Markdown document and derive its table cells.

    Raises `ManifestError` on any violation of the grammar listed in the module docstring.
    """
    src = markdown.replace("\r\n", "\n")
    lines = src.split("\n")
    units = list(_units(src, lines))
    _check_anchor_occurrences(src, units)
    section_ids = {u.id for u in units if isinstance(u, _Anchor) and _is_section(u.id)}
    anchors: list[Anchor] = []
    seen: set[str] = set()
    enclosing: str | None = None
    i = 0
    while i < len(units):
        unit = units[i]
        if not isinstance(unit, _Anchor):
            i += 1
            continue
        if unit.id in seen:
            raise ManifestError(f"line {unit.line + 1}: duplicate anchor id {unit.id!r}")
        seen.add(unit.id)
        if not ANCHOR_RE.match(unit.id):
            raise ManifestError(f"line {unit.line + 1}: {unit.id!r} is not a valid anchor id")
        if _PAGE_ID_RE.fullmatch(unit.id):
            anchors.append(Anchor(unit.id, AnchorKind.PAGE, None, ""))
            i += 1
            continue
        following = units[i + 1] if i + 1 < len(units) else None
        if not isinstance(following, _Element) or following.start != unit.line + 1:
            raise ManifestError(
                f"line {unit.line + 1}: anchor {unit.id!r} is not directly followed by an element"
            )
        if _is_section(unit.id):
            if following.kind != "heading":
                raise ManifestError(
                    f"line {unit.line + 1}: section {unit.id!r} must be followed by a heading"
                )
            enclosing = unit.id
            anchors.append(
                Anchor(unit.id, AnchorKind.SECTION, _section_parent(unit.id), following.text)
            )
        elif _PARAGRAPH_ID_RE.fullmatch(unit.id):
            prefix = unit.id.rsplit(".p", 1)[0]
            if prefix != "s0" and prefix not in section_ids:
                raise ManifestError(
                    f"line {unit.line + 1}: paragraph {unit.id!r} is under unknown section "
                    f"{prefix!r}"
                )
            _require(following, "paragraph", unit.id, unit.line)
            anchors.append(Anchor(unit.id, AnchorKind.PARAGRAPH, prefix, following.text))
        elif _TABLE_ID_RE.fullmatch(unit.id):
            _require(following, "table", unit.id, unit.line)
            anchors.append(Anchor(unit.id, AnchorKind.TABLE, enclosing, following.text))
            anchors.extend(_cells(unit.id, following))
        elif _CAPTION_ID_RE.fullmatch(unit.id):
            _require(following, "paragraph", unit.id, unit.line)
            anchors.append(Anchor(unit.id, AnchorKind.FIGURE_CAPTION, enclosing, following.text))
        else:
            _require(following, "paragraph", unit.id, unit.line)
            anchors.append(Anchor(unit.id, AnchorKind.EQUATION, enclosing, following.text))
        i += 2
    return Manifest(tuple(anchors))


def _anchor_from_entry(entry: object, index: int) -> Anchor:
    where = f"manifest entry {index}"
    if not isinstance(entry, dict):
        raise ManifestError(f"{where} is not an object")
    if set(entry) != _ENTRY_KEYS:
        raise ManifestError(f"{where} must have exactly the keys id, kind, parent, text")
    anchor_id, kind, parent, text = entry["id"], entry["kind"], entry["parent"], entry["text"]
    if not isinstance(anchor_id, str) or not (
        ANCHOR_RE.fullmatch(anchor_id) or _CELL_ID_RE.fullmatch(anchor_id)
    ):
        raise ManifestError(f"{where} has an invalid id {anchor_id!r}")
    if not isinstance(kind, str) or kind not in {k.value for k in AnchorKind}:
        raise ManifestError(f"{where} has an invalid kind {kind!r}")
    if parent is not None and not isinstance(parent, str):
        raise ManifestError(f"{where} has a parent that is neither a string nor null")
    if not isinstance(text, str):
        raise ManifestError(f"{where} has a text that is not a string")
    return Anchor(anchor_id, AnchorKind(kind), parent, text)


def _is_section(anchor_id: str) -> bool:
    return _SECTION_ID_RE.fullmatch(anchor_id) is not None


def _section_parent(section_id: str) -> str | None:
    head, dot, _ = section_id.rpartition(".")
    return head if dot else None


def _require(element: _Element, kind: str, anchor_id: str, line: int) -> None:
    if element.kind != kind:
        raise ManifestError(f"line {line + 1}: anchor {anchor_id!r} must be followed by a {kind}")


def _units(src: str, lines: list[str]) -> Iterator[_Unit]:
    """Anchor lines and top-level block elements, in document order."""
    for token in MARKDOWN.parse(src):
        if token.level != 0 or token.nesting == -1 or token.map is None:
            continue
        start, end = token.map
        if token.type == "paragraph_open":
            idx = start
            while idx < end and (anchor_id := _anchor_on_line(lines[idx])) is not None:
                yield _Anchor(idx, anchor_id)
                idx += 1
            if idx < end:
                yield _Element(idx, "paragraph", "\n".join(lines[idx:end]), tuple(lines[idx:end]))
            continue
        kind = {"heading_open": "heading", "table_open": "table"}.get(token.type, "other")
        yield _Element(start, kind, "\n".join(lines[start:end]), tuple(lines[start:end]))


def _anchor_on_line(line: str) -> str | None:
    match = _ANCHOR_LINE_RE.fullmatch(line.strip())
    return match.group(1) if match else None


def _check_anchor_occurrences(src: str, units: list[_Unit]) -> None:
    """Every `<a id=` in the source must be a standalone anchor line that was read as one."""
    recognised = sum(isinstance(u, _Anchor) for u in units)
    found = len(_ANCHOR_OCCURRENCE_RE.findall(src))
    if found != recognised:
        raise ManifestError("an anchor must be on its own line at the start of a block")


def split_row(line: str) -> list[str]:
    """The raw cells of one GFM table row; `\\|` does not split a cell."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            buf.append(body[i : i + 2])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf))
    if body.endswith("|") and cells[-1].strip() == "":
        cells.pop()
    return cells


def _cells(table_id: str, table: _Element) -> list[Anchor]:
    """Cell anchors `t<n>.r<r>.c<c>` (1-based, header row r1) of a rectangular table."""
    rows = [split_row(line) for line in table.lines[2:]]
    header = split_row(table.lines[0])
    width = len(header)
    grid = [header, *rows]
    for r, row in enumerate(grid, start=1):
        if len(row) != width:
            raise ManifestError(
                f"table {table_id!r} is non-rectangular: row {r} has {len(row)} cells, "
                f"expected {width}"
            )
    return [
        Anchor(f"{table_id}.r{r}.c{c}", AnchorKind.CELL, table_id, cell.strip().replace("\\|", "|"))
        for r, row in enumerate(grid, start=1)
        for c, cell in enumerate(row, start=1)
    ]
