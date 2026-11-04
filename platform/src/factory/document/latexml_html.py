"""LaTeXML HTML converter: LaTeXML's HTML5 output in, plain Markdown out. Pure lxml.

Mapping (LaTeXML class to Markdown):
- `ltx_title_document` is a `#` heading with no number.
- `ltx_section`, `ltx_appendix` are `##`; `ltx_subsection` `###`; `ltx_subsubsection` `####`. The
  heading keeps the `ltx_tag` number as text: `## 3 Method`, `### 3.2 Setup`. The tag is used only
  if it matches `[A-Za-z0-9]+(\\.[0-9]+)*\\.?`; any other tag is dropped and the heading is
  unnumbered. A single-letter tag (other than the roman-numeral letters I, V, X) gets a full stop:
  `## A. Proofs`, because the anchoriser reads a bare `A Proofs` as unnumbered.
- `ltx_p` (and `p`) is a paragraph; `ltx_para` is a container. A paragraph whose text starts a
  CommonMark list, quote, heading, rule or ordered item has that marker escaped, so it stays a
  paragraph.
- Inline `math` becomes `$alttext$`; `ltx_equation` and `ltx_equationgroup` (and a block-level
  `math`) become `$$alttext$$`, one line per equation. A bare `$` in alttext is written `\\$`, so
  the delimiters stay balanced.
- `pre` and `ltx_verbatim` are a paragraph of their collapsed text (no code fence). `dl` gives one
  paragraph per `dt` and `dd`. `ltx_listingline` gives one paragraph per line.
- A table (`table`) becomes a GFM table. Spans are rectangular: the text sits in the top-left
  cell of a span and the other cells of the span are empty. Row spans are clamped to the rows that
  remain and column spans to 1000 columns; a clamp yields the warning `table <n>: span clamped`.
  The first row of the grid is the Markdown header. This is the first row of the first `thead` if
  there is one, else the first row of the table. Remaining `thead` rows become ordinary body rows.
  Ragged rows are padded with empty cells and yield the warning `table <n>: ragged rows padded`
  (once per table). A table with no cells is skipped with the warning
  `table <n>: no cells, skipped`.
- A float (`ltx_table`, `ltx_figure`, `figure`, `ltx_float_algorithm`, other `ltx_float`) gives
  its caption as the paragraph `Table <n>: text`, `Figure <n>: text`, `Algorithm <n>: text` or
  `Float <n>: text`, placed directly above its content. Only the float's own caption is used: a
  caption inside a nested float belongs to that float. The label is the caption's `ltx_tag`
  digits; else the tag itself when it is a plain word such as `(a)`; else a running count of
  captions of that kind. Images (`img`, `picture`, `svg`, `ltx_graphics`) are dropped.
- `ltx_bibliography` gives `## References` and one paragraph per `ltx_bibitem`.
- An `a.ltx_ref` inside an `ltx_cite` whose `href` is `#<id>` of an `ltx_bibitem` becomes
  `[text](#b<k>)`, where `k` is the 1-based ordinal of that bibitem among all `ltx_bibitem`s in
  document order (the anchoriser's `b<k>`). `\\`, `[` and `]` in the text are backslash-escaped.
  Brackets and separators around the links stay text. A cite link to an unknown target is text.
- A footnote (`ltx_note`) becomes `[^n]` in the text and a paragraph `[^n] text` at the end of the
  enclosing section. The number is the note's `ltx_tag`, else a running count.
- Equation numbers (`ltx_tag_equation`) carry no content and are dropped.
- Other elements: their text is kept as a paragraph, with no markup. A container's own text and
  the tails of its children are kept too. Lists become one paragraph per item. Page furniture
  (`ltx_toc`, `ltx_page_header`, `ltx_page_footer`, `nav`) is dropped.

Text escaping: `&`, `<` and `>` in text, math alttext and captions are written as entities, so the
output contains no `<` (anchor lines are added later by the anchoriser). Cell text additionally goes
through `escape_cell`.

Determinism: the parser is lxml with the encoding from the first `<meta charset>` (UTF-8 by
default); the walk is in document order; no state outside the call.
"""

import re
from dataclasses import dataclass, field
from typing import NamedTuple

import lxml
from lxml import etree

from factory.document.normalise import escape_cell

CONVERTER_VERSION = "1.1"

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
    {
        "ltx_toc",
        "ltx_page_header",
        "ltx_page_footer",
        "ltx_graphics",
        # Equation numbers carry no content; the equation itself is emitted from its math.
        "ltx_tag_equation",
    }
)
_FLOAT_CLASSES = frozenset({"ltx_table", "ltx_figure", "ltx_float"})
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
_SECTION_TAG = re.compile(r"[A-Za-z0-9]+(\.[0-9]+)*\.?")
_LABEL = re.compile(r"[A-Za-z0-9().]+")
_BARE_DOLLAR = re.compile(r"(?<!\\)\$")
_MAX_WIDTH = 64
_SLOT_BUDGET = 200_000
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


def _own_captions(el: etree._Element) -> list[etree._Element]:
    """The captions owned by float `el`, in document order, not entering nested floats."""
    found: list[etree._Element] = []
    for child in _children(el):
        if "ltx_caption" in _classes(child):
            found.append(child)
        elif not _is_float(child):
            found.extend(_own_captions(child))
    return found


def _is_float(el: etree._Element) -> bool:
    return bool(_classes(el) & _FLOAT_CLASSES) or el.tag == "figure"


def _float_kind(el: etree._Element) -> str:
    classes = _classes(el)
    if "ltx_table" in classes:
        return "Table"
    if "ltx_float_algorithm" in classes:
        return "Algorithm"
    if "ltx_float" in classes:
        return "Float"
    return "Figure"


def _inside_float(el: etree._Element) -> bool:
    return any(_is_float(ancestor) for ancestor in el.iterancestors())


def _text(el: etree._Element) -> str:
    return "".join(el.itertext())


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _math_text(text: str) -> str:
    """Escaped math alttext in which every bare `$` is written `\\$`."""
    return _BARE_DOLLAR.sub(r"\\$", _esc(text))


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


class _Placed(NamedTuple):
    """A placed table: rectangular `grid`, whether rows were padded or spans clamped, and the
    texts of cells that fell beyond the column limit (`overflow`, in document order)."""

    grid: list[list[str]]
    padded: bool
    clamped: bool
    overflow: list[str]


def _grid(rows: list[list[tuple[int, int, str]]]) -> _Placed:
    """Place `(colspan, rowspan, text)` cells on a grid of at most `_MAX_WIDTH` columns.

    The width is the widest row's span sum, capped at `_MAX_WIDTH` and at
    `_SLOT_BUDGET // rows`, so the grid never holds more than `_SLOT_BUDGET` slots. A cell takes
    the first free slot of its row; its text is in the top-left slot and the other slots of its
    span are empty. A column span is clipped to the width and a row span to the rows that remain
    (both count as clamped). A cell that starts past the width keeps its text in `overflow`.
    """
    height = len(rows)
    declared = max((sum(colspan for colspan, _, _ in row) for row in rows), default=0)
    width = max(1, min(declared, _MAX_WIDTH, _SLOT_BUDGET // max(height, 1)))
    slots: dict[tuple[int, int], str] = {}
    clamped = False
    overflow: list[str] = []
    for row_index, row in enumerate(rows):
        column = 0
        for colspan, rowspan, text in row:
            while (row_index, column) in slots:
                column += 1
            if column >= width:
                if text:
                    overflow.append(text)
                continue
            if colspan > width - column:
                colspan = width - column
                clamped = True
            if rowspan > height - row_index:
                rowspan = height - row_index
                clamped = True
            for dr in range(rowspan):
                for dc in range(colspan):
                    slots.setdefault((row_index + dr, column + dc), text if dr == dc == 0 else "")
            column += colspan
    if not slots:
        return _Placed([], False, clamped, overflow)
    reach = [0] * height  # per row: one past the last filled slot
    for row_index, column in slots:
        reach[row_index] = max(reach[row_index], column + 1)
    grid_width = max(reach)
    grid = [
        [slots.get((row_index, column), "") for column in range(grid_width)]
        for row_index in range(height)
    ]
    return _Placed(grid, any(length < grid_width for length in reach), clamped, overflow)


def _is_inline_like(child: etree._Element) -> bool:
    """True if `child` sits within running text (so it joins a paragraph, not a block).

    Display math and equation containers are blocks; inline math is not.
    """
    classes = _classes(child)
    if classes & {"ltx_equation", "ltx_equationgroup"}:
        return False
    if child.tag == "math" and child.get("display") == "block":
        return False
    return (
        child.tag in _INLINE_TAGS
        or child.tag in {"math", "br"}
        or "ltx_note" in _classes(child)
        or _skipped(child, _NO_CLASSES)
    )


def _skipped(el: etree._Element, exclude: frozenset[str]) -> bool:
    return el.tag in _SKIP_TAGS or bool(_classes(el) & (_SKIP_CLASSES | exclude))


@dataclass
class _Walker:
    """Walks one parsed document and collects Markdown blocks in document order."""

    out: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _scopes: list[list[str]] = field(default_factory=lambda: [[]])
    _captions: dict[str, int] = field(default_factory=dict)
    _notes: int = 0
    _tables: int = 0
    _bib_ordinals: dict[str, int] = field(default_factory=dict)

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
        if _is_float(el):
            self._float(el)
            return
        if classes & {"ltx_equation", "ltx_equationgroup"}:
            self._equation_pieces(el)
            return
        if el.tag == "table":
            self._table(el)
            return
        if el.tag == "math":
            self._equation(el)
            return
        if "ltx_caption" in classes:
            # A caption is emitted by its float; only a stray one is kept as a paragraph.
            if not _inside_float(el):
                self._para(self._inline(el))
            return
        if classes & {"ltx_title", "ltx_p", "ltx_listingline", "ltx_verbatim"} or el.tag in {
            "p",
            "pre",
        }:
            self._para(self._inline(el))
            return
        if el.tag == "dl":
            self._items(el, {"dt", "dd"})
            return
        if el.tag in {"ul", "ol"}:
            self._items(el, {"li"})
            return
        if el.tag in _INLINE_TAGS:
            self._para(self._inline(el))
            return
        self._container(el)

    def _container(self, el: etree._Element, skip: etree._Element | None = None) -> None:
        """Keep every piece of text in `el`, grouping running text into paragraphs.

        Text, inline elements and inline math between block children form one paragraph; a
        block child ends the paragraph. `skip` is a child that the caller has already emitted.
        """
        run: list[str] = []
        if el.text:
            run.append(_esc(el.text))
        for child in _children(el):
            if child is not skip:
                if _is_inline_like(child):
                    self._gather_child(child, run, _NO_CLASSES)
                else:
                    self._flush(run)
                    self.block(child)
            if child.tail:
                run.append(_esc(child.tail))
        self._flush(run)

    def _flush(self, run: list[str]) -> None:
        text = _collapse("".join(run))
        run.clear()
        self._para(text)

    def _items(self, el: etree._Element, item_tags: set[str]) -> None:
        """A list or definition list: one paragraph per item; other children are blocks."""
        self._tail_para(el.text)
        for child in _children(el):
            if child.tag in item_tags:
                self._para(self._inline(child))
            else:
                self.block(child)
            self._tail_para(child.tail)

    def _equation_pieces(self, el: etree._Element) -> None:
        """An equation or equation group: each math is a `$$` line; loose text keeps its place."""
        run: list[str] = []
        if el.text:
            run.append(el.text)
        for child in _children(el):
            if child.tag == "math":
                self._tail_para("".join(run))
                run.clear()
                self._equation(child)
            elif not _skipped(child, _NO_CLASSES):
                self._tail_para("".join(run))
                run.clear()
                self._equation_pieces(child)
            if child.tail:
                run.append(child.tail)
        self._tail_para("".join(run))

    def _tail_para(self, text: str | None) -> None:
        """Keep loose text (raw, unescaped) as a paragraph of its own."""
        if text and text.strip():
            self._para(_esc(_collapse(text)))

    def _heading(self, level: int, el: etree._Element, tag: str = "") -> None:
        text = self._inline(el, _TAG_ONLY)
        line = " ".join(part for part in (tag, text) if part)
        self.out.append("#" * level + (f" {line}" if line else ""))

    def _section(self, el: etree._Element, level: int) -> None:
        title = next((child for child in _children(el) if "ltx_title" in _classes(child)), None)
        if title is not None:
            tag = _first(title, "ltx_tag")
            number = _collapse(_text(tag)) if tag is not None else ""
            if not _SECTION_TAG.fullmatch(number):
                number = ""
            if re.fullmatch(r"[A-Z]", number) and number not in _ROMAN_LETTERS:
                number += "."
            self._heading(level, title, number)
        self._scopes.append([])
        self._container(el, skip=title)
        self.out.extend(self._scopes.pop())

    def _para(self, text: str) -> None:
        if text:
            self.out.append(_safe_start(text))

    def _equation(self, math: etree._Element) -> None:
        alttext = _collapse(math.get("alttext") or _text(math))
        if alttext:
            self.out.append(f"$${_math_text(alttext)}$$")

    def _bibliography(self, el: etree._Element) -> None:
        self.out.append("## References")
        for node in el.iterdescendants():
            if isinstance(node.tag, str) and "ltx_bibitem" in _classes(node):
                self._para(self._inline(node))

    def _float(self, el: etree._Element) -> None:
        kind = _float_kind(el)
        for caption in _own_captions(el):
            self._para(self._caption(caption, kind))
        self._container(el)

    def _caption(self, caption: etree._Element, kind: str) -> str:
        count = self._captions.get(kind, 0) + 1
        self._captions[kind] = count
        tag = _first(caption, "ltx_tag")
        tag_text = _collapse(_text(tag)) if tag is not None else ""
        digits = re.search(r"\d+", tag_text)
        if digits is not None:
            label = digits.group(0)
        elif _LABEL.fullmatch(tag_text):
            label = tag_text
        else:
            label = str(count)
        text = self._inline(caption, _TAG_ONLY)
        return f"{kind} {label}: {text}" if text else f"{kind} {label}:"

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
                self._gather_child(child, parts, exclude)
            if child.tail:
                parts.append(_esc(child.tail))

    def _gather_child(
        self, child: etree._Element, parts: list[str], exclude: frozenset[str]
    ) -> None:
        """Append one child's inline text to `parts`; its tail is the caller's job."""
        if _skipped(child, exclude):
            return
        classes = _classes(child)
        if "ltx_note" in classes:
            parts.append(self._footnote(child))
        elif child.tag == "math":
            alttext = _collapse(child.get("alttext") or _text(child))
            if alttext:
                parts.append(f"${_math_text(alttext)}$")
        elif child.tag == "br":
            parts.append(" ")
        elif self._cite_target(child) is not None:
            text = _collapse(_text(child)).replace("\\", "\\\\")
            text = text.replace("[", "\\[").replace("]", "\\]")
            parts.append(f"[{_esc(text)}](#b{self._cite_target(child)})")
        else:
            self._gather(child, parts, exclude)

    def _cite_target(self, link: etree._Element) -> int | None:
        """The bibliography ordinal that citation link `link` points to, else None."""
        href = link.get("href") or ""
        if (
            link.tag != "a"
            or "ltx_ref" not in _classes(link)
            or not href.startswith("#")
            or not any("ltx_cite" in _classes(a) for a in link.iterancestors())
        ):
            return None
        return self._bib_ordinals.get(href[1:])

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
        placed = _grid(rows)
        caption = next(
            (child for child in _children(table) if "ltx_caption" in _classes(child)), None
        )
        if caption is not None and not _inside_float(table):
            self._para(self._caption(caption, "Table"))
        if not placed.grid:
            self.warnings.append(f"table {number}: no cells, skipped")
        else:
            self._emit_table(number, placed)
        if placed.overflow:
            self.warnings.append(f"table {number}: cells beyond column limit moved to text")
            self._para(_collapse(" ".join(placed.overflow)))

    def _emit_table(self, number: int, placed: _Placed) -> None:
        if placed.clamped:
            self.warnings.append(f"table {number}: span clamped")
        if placed.padded:
            self.warnings.append(f"table {number}: ragged rows padded")
        width = len(placed.grid[0])
        lines = ["| " + " | ".join(escape_cell(cell) for cell in placed.grid[0]) + " |"]
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for row in placed.grid[1:]:
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
        bibitems = (
            node
            for node in root.iter()
            if isinstance(node.tag, str)
            and "ltx_bibitem" in _classes(node)
            and _collapse(_text(node))  # an empty bibitem yields no paragraph, so no anchor
        )
        for ordinal, item in enumerate(bibitems, start=1):
            if item.get("id"):
                walker._bib_ordinals.setdefault(str(item.get("id")), ordinal)
        walker.block(root)
        markdown = walker.finish()
        return markdown, tuple(walker.warnings)
