"""LaTeXML HTML converter: LaTeXML's HTML5 output in, plain Markdown out. Pure lxml.

Mapping (LaTeXML class to Markdown):
- `ltx_title_document` is a `#` heading with no number.
- `ltx_section`, `ltx_appendix` are `##`; `ltx_subsection` `###`; `ltx_subsubsection` `####`. The
  heading keeps the `ltx_tag` number as text: `## 3 Method`, `### 3.2 Setup`. A single-letter tag
  (other than the roman-numeral letters I, V, X) gets a full stop: `## A. Proofs`, because the
  anchoriser reads a bare `A Proofs` as unnumbered. Roman-numeral tags are left as they are.
- `ltx_p` (and `p`) is a paragraph; `ltx_para` is a container. A paragraph whose text starts a
  CommonMark list, quote, heading, rule or ordered item has that marker escaped, so it stays a
  paragraph.
- Inline `math` becomes `$alttext$`; `ltx_equation` and `ltx_equationgroup` (and a block-level
  `math`) become `$$alttext$$`, one line per equation.
- A table (`table`) becomes a GFM table. Spans are rectangular: the text sits in the top-left
  cell of a span and the other cells of the span are empty. The first row of the grid is the
  Markdown header. This is the first row of the first `thead` if there is one, else the first row
  of the table. Remaining `thead` rows become ordinary body rows. Ragged rows are padded with
  empty cells and yield the warning `table <n>: ragged rows padded` (once per table). A table
  with no cells is skipped with the warning `table <n>: no cells, skipped`.
- A float (`ltx_table`, `ltx_figure`, or a `figure`) gives its caption as the paragraph
  `Table <n>: text` or `Figure <n>: text`, placed directly above its content. The number comes
  from the caption's `ltx_tag` when it has a digit, else from a running count of captions of that
  kind. Images (`img`, `picture`, `svg`, `ltx_graphics`) are dropped.
- `ltx_bibliography` gives `## References` and one paragraph per `ltx_bibitem`.
- A footnote (`ltx_note`) becomes `[^n]` in the text and a paragraph `[^n] text` at the end of the
  enclosing section. The number is the note's `ltx_tag`, else a running count.
- Other elements: their text, with no markup. An element whose tag is a phrase-level tag (span,
  em, a, ...) outside any block becomes a paragraph of its text. Lists become one paragraph per
  item.

Text escaping: `&`, `<` and `>` in text, math alttext and captions are written as entities, so the
output contains no `<` (anchor lines are added later by the anchoriser). Cell text additionally goes
through `escape_cell`.

Determinism: the parser is lxml with the encoding from the first `<meta charset>` (UTF-8 by
default); the walk is in document order; no state outside the call.
"""

import re
from dataclasses import dataclass, field

import lxml
from lxml import etree

from factory.document.normalise import escape_cell

CONVERTER_VERSION = "1.0"

_SECTION_LEVELS = {"ltx_section": 2, "ltx_appendix": 2, "ltx_subsection": 3, "ltx_subsubsection": 4}
_SKIP_TAGS = frozenset(
    {
        "head",
        "script",
        "style",
        "nav",
        "img",
        "picture",
        "svg",
        "video",
        "audio",
        "object",
        "iframe",
    }
)
_SKIP_CLASSES = frozenset(
    {"ltx_caption", "ltx_toc", "ltx_page_header", "ltx_page_footer", "ltx_graphics"}
)
_INLINE_TAGS = frozenset(
    {
        "span",
        "em",
        "strong",
        "b",
        "i",
        "a",
        "sup",
        "sub",
        "cite",
        "code",
        "small",
        "q",
        "u",
        "font",
        "abbr",
    }
)
_ROMAN_LETTERS = frozenset({"I", "V", "X"})
_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE
)
_ORDERED_MARKER = re.compile(r"(\d{1,9})([.)])(?=\s|$)")
_BLOCK_MARKERS = "#>+-*=_"
_NO_CLASSES: frozenset[str] = frozenset()
_TAG_ONLY = frozenset({"ltx_tag"})


def _parse(raw: bytes) -> etree._Element | None:
    """The root element of `raw`, or None if it holds no parseable HTML."""
    match = _META_CHARSET.search(raw[:4096])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        parser = etree.HTMLParser(encoding=encoding, remove_comments=True, remove_pis=True)
    except LookupError:
        parser = etree.HTMLParser(encoding="utf-8", remove_comments=True, remove_pis=True)
    try:
        return etree.fromstring(raw, parser)
    except etree.XMLSyntaxError:
        return None


def _classes(el: etree._Element) -> frozenset[str]:
    return frozenset(str(el.get("class") or "").split())


def _children(el: etree._Element) -> list[etree._Element]:
    """The element children of `el` (comments and processing instructions removed)."""
    return [child for child in el if isinstance(child.tag, str)]


def _first(el: etree._Element, name: str) -> etree._Element | None:
    """The first descendant of `el` (not `el` itself) carrying class `name`, or None."""
    for node in el.iterdescendants():
        if isinstance(node.tag, str) and name in _classes(node):
            return node
    return None


def _text(el: etree._Element) -> str:
    return "".join(el.itertext())


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_start(text: str) -> str:
    """Escape a leading marker so that CommonMark reads `text` as a paragraph."""
    if text and text[0] in _BLOCK_MARKERS:
        return "\\" + text
    match = _ORDERED_MARKER.match(text)
    if match:
        cut = match.end(1)
        return text[:cut] + "\\" + text[cut:]
    return text


def _span(cell: etree._Element, attribute: str) -> int:
    try:
        return max(1, int(cell.get(attribute, "1")))
    except ValueError:
        return 1


def _rows(table: etree._Element) -> list[etree._Element]:
    """The `tr` elements of `table` in document order: thead, tbody and tfoot rows included."""
    rows: list[etree._Element] = []
    for child in _children(table):
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in {"thead", "tbody", "tfoot"}:
            rows.extend(row for row in _children(child) if row.tag == "tr")
    return rows


def _grid(rows: list[list[tuple[int, int, str]]]) -> tuple[list[list[str]], bool]:
    """Place `(colspan, rowspan, text)` cells on a grid and return it rectangular.

    A cell takes the first free slot of its row. Its text is in the top-left slot; the other
    slots of its span are empty. Returns the grid (one list per row, all of one width) and whether
    any row had to be padded. Slots of a span that reach past the last row are dropped.
    """
    slots: dict[tuple[int, int], str] = {}
    for row_index, row in enumerate(rows):
        column = 0
        for colspan, rowspan, text in row:
            while (row_index, column) in slots:
                column += 1
            for dr in range(rowspan):
                for dc in range(colspan):
                    slots.setdefault((row_index + dr, column + dc), text if dr == dc == 0 else "")
            column += colspan
    reach = [0] * len(rows)  # per row: one past the last filled slot
    for row_index, column in slots:
        if row_index < len(rows):
            reach[row_index] = max(reach[row_index], column + 1)
    width = max(reach, default=0)
    if width == 0:
        return [], False
    grid = [
        [slots.get((row_index, column), "") for column in range(width)]
        for row_index in range(len(rows))
    ]
    return grid, any(length < width for length in reach)


@dataclass
class _Walker:
    """Walks one parsed document and collects Markdown blocks in document order."""

    out: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _scopes: list[list[str]] = field(default_factory=lambda: [[]])
    _captions: dict[str, int] = field(default_factory=lambda: {"Table": 0, "Figure": 0})
    _notes: int = 0
    _tables: int = 0

    def finish(self) -> str:
        """The document's Markdown, with the footnotes of the top level appended."""
        self.out.extend(self._scopes.pop())
        return "\n\n".join(self.out) + "\n" if self.out else ""

    def block(self, el: etree._Element) -> None:
        classes = _classes(el)
        if el.tag in _SKIP_TAGS or classes & _SKIP_CLASSES:
            return
        if "ltx_title_document" in classes:
            self._heading(1, el)
            return
        for name, level in _SECTION_LEVELS.items():
            if name in classes:
                self._section(el, level)
                return
        if "ltx_bibliography" in classes:
            self._bibliography(el)
            return
        if classes & {"ltx_table", "ltx_figure"} or el.tag == "figure":
            self._float(el, "Table" if "ltx_table" in classes else "Figure")
            return
        if classes & {"ltx_equation", "ltx_equationgroup"}:
            for math in el.iter("math"):
                self._equation(math)
            return
        if el.tag == "table":
            self._table(el)
            return
        if el.tag == "math":
            self._equation(el)
            return
        if "ltx_title" in classes or el.tag == "p" or "ltx_p" in classes:
            self._para(self._inline(el))
            return
        if el.tag in {"ul", "ol"}:
            for item in _children(el):
                if item.tag == "li":
                    self._para(self._inline(item))
            return
        if el.tag in _INLINE_TAGS:
            self._para(self._inline(el))
            return
        for child in _children(el):
            self.block(child)

    def _heading(self, level: int, el: etree._Element, tag: str = "") -> None:
        text = self._inline(el, _TAG_ONLY)
        line = " ".join(part for part in (tag, text) if part)
        self.out.append("#" * level + (f" {line}" if line else ""))

    def _section(self, el: etree._Element, level: int) -> None:
        title = next((child for child in _children(el) if "ltx_title" in _classes(child)), None)
        if title is not None:
            tag = _first(title, "ltx_tag")
            number = _collapse(_text(tag)) if tag is not None else ""
            if re.fullmatch(r"[A-Z]", number) and number not in _ROMAN_LETTERS:
                number += "."
            self._heading(level, title, number)
        self._scopes.append([])
        for child in _children(el):
            if child is not title:
                self.block(child)
        self.out.extend(self._scopes.pop())

    def _para(self, text: str) -> None:
        if text:
            self.out.append(_safe_start(text))

    def _equation(self, math: etree._Element) -> None:
        alttext = _collapse(math.get("alttext") or _text(math))
        if alttext:
            self.out.append(f"$${_esc(alttext)}$$")

    def _bibliography(self, el: etree._Element) -> None:
        self.out.append("## References")
        for node in el.iterdescendants():
            if isinstance(node.tag, str) and "ltx_bibitem" in _classes(node):
                self._para(self._inline(node))

    def _float(self, el: etree._Element, kind: str) -> None:
        caption = _first(el, "ltx_caption")
        if caption is not None:
            self._para(self._caption(caption, kind))
        for child in _children(el):
            self.block(child)

    def _caption(self, caption: etree._Element, kind: str) -> str:
        self._captions[kind] += 1
        tag = _first(caption, "ltx_tag")
        digits = re.search(r"\d+", _text(tag)) if tag is not None else None
        number = digits.group(0) if digits is not None else str(self._captions[kind])
        text = self._inline(caption, _TAG_ONLY)
        return f"{kind} {number}: {text}" if text else f"{kind} {number}:"

    def _footnote(self, note: etree._Element) -> str:
        content = _first(note, "ltx_note_content")
        if content is None:
            return _esc(_collapse(_text(note)))
        self._notes += 1
        tag = _first(content, "ltx_tag")
        digits = re.search(r"\d+", _text(tag)) if tag is not None else None
        label = digits.group(0) if digits is not None else str(self._notes)
        text = self._inline(content, frozenset({"ltx_tag", "ltx_note_mark"}))
        self._scopes[-1].append(f"[^{label}] {text}" if text else f"[^{label}]")
        return f"[^{label}]"

    def _inline(self, el: etree._Element, exclude: frozenset[str] = _NO_CLASSES) -> str:
        parts: list[str] = []
        self._gather(el, parts, exclude)
        return _collapse("".join(parts))

    def _gather(self, el: etree._Element, parts: list[str], exclude: frozenset[str]) -> None:
        if el.text:
            parts.append(_esc(el.text))
        for child in el:
            if isinstance(child.tag, str):
                classes = _classes(child)
                if child.tag in _SKIP_TAGS or classes & (_SKIP_CLASSES | exclude):
                    pass
                elif "ltx_note" in classes:
                    parts.append(self._footnote(child))
                elif child.tag == "math":
                    alttext = _collapse(child.get("alttext") or _text(child))
                    if alttext:
                        parts.append(f"${_esc(alttext)}$")
                elif child.tag == "br":
                    parts.append(" ")
                else:
                    self._gather(child, parts, exclude)
            if child.tail:
                parts.append(_esc(child.tail))

    def _table(self, table: etree._Element) -> None:
        self._tables += 1
        number = self._tables
        rows = [
            [
                (_span(cell, "colspan"), _span(cell, "rowspan"), self._inline(cell))
                for cell in _children(row)
                if cell.tag in {"td", "th"}
            ]
            for row in _rows(table)
        ]
        grid, padded = _grid(rows)
        if not grid:
            self.warnings.append(f"table {number}: no cells, skipped")
            return
        if padded:
            self.warnings.append(f"table {number}: ragged rows padded")
        width = len(grid[0])
        lines = ["| " + " | ".join(escape_cell(cell) for cell in grid[0]) + " |"]
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for row in grid[1:]:
            lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
        self.out.append("\n".join(lines))


class LatexmlHtmlConverter:
    """Converts LaTeXML HTML to canonical Markdown; see the module docstring."""

    name = "latexml-html"
    accepts = frozenset({"text/html"})

    def version(self) -> str:
        # lxml's type stubs do not declare __version__; the attribute exists at runtime.
        return f"{CONVERTER_VERSION}+lxml{lxml.__version__}"  # type: ignore[attr-defined]

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        root = _parse(raw)
        if root is None:
            return "", ("document: not parseable as HTML",)
        walker = _Walker()
        walker.block(root)
        markdown = walker.finish()
        return markdown, tuple(walker.warnings)
