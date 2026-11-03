"""The anchoriser: converter Markdown in, canonical Markdown with `<a id>` anchors out.

Converters emit plain Markdown; this module alone writes anchors, so one scheme holds across
formats. The output satisfies `parse_manifest` and is a fixed point of `anchorise`.

Numbering:
- A numbered heading (`3`, `3.2`, or an appendix per Ruling F: `A.`, `A:`, `A)`, `A` alone, `A.1`)
  gives section `s3`, `s3.2`, `s101` or `s101.1` (appendix letter index plus 100). `_numbering`
  implements this grammar. An unnumbered heading that is the only heading at the
  minimum depth and has deeper headings is the document title and gets `s0`. Any other unnumbered
  heading takes the next ordinal under its parent heading. A repeated id takes `.k` (k >= 2).
- Paragraphs before the first heading belong to `s0`. Paragraphs are numbered per section from 1.
- Tables are `t<n>`, display equations `e<n>`, figure captions `f<n>.cap` (number from the text,
  then the next free number), and page breaks `p<n>` (the n-th form feed).
- A paragraph starting `Table <n>` next to a table is that table's caption: it moves below the
  table and gets no anchor. Figure captions do not consume paragraph numbers.
- Lists, blockquotes, code fences and rule lines are left unanchored and do not break numbering.
  An element is anchored only if `<a id>` followed by it parses as that element, so the manifest
  check accepts every anchor the output contains.
"""

import re
from dataclasses import dataclass, field

from markdown_it.token import Token

from factory.document.anchors import MARKDOWN, split_row
from factory.document.normalise import normalise

_PAGE = "\x00page\x00"
_MATH = re.compile(r"\x00math(\d+)\x00")
_ANY_ANCHOR = re.compile(r"<a\s+id\s*=[^>]*>\s*</a>")
_PAGE_ANCHOR = re.compile(r'<a id="p\d+"></a>')
_STRAY_ANCHOR = re.compile(r"<(?=a\s+id=)")
_FENCE_OPEN = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*$")
_DIGITS = re.compile(r"(\d+(?:\.\d+)*)\.?(?=\s|$)")
# Roman numerals are not recognised, so I, V and X are excluded from the appendix letters
# (the class is A-H, J-U, W, Y, Z).
_APPENDIX_SUB = re.compile(r"([A-HJ-UWYZ])\.(\d+(?:\.\d+)*)(?=\s|$)")
_APPENDIX_LETTER = re.compile(r"([A-HJ-UWYZ])(?=[.:)](?:\s|$)|$)")
_FIGURE = re.compile(r"(?:Figure|Fig\.)\s+(\d+)\b", re.IGNORECASE)
_TABLE_CAPTION = re.compile(r"Table\s+\d+", re.IGNORECASE)
_PROBE = '<a id="x"></a>'
_KINDS = {"paragraph_open": "paragraph", "heading_open": "heading", "table_open": "table"}


@dataclass
class _Block:
    """One top-level block of the normalised source. `text` is a heading's inline content."""

    kind: str  # "page", "math", "heading", "paragraph", "table" or "other"
    lines: list[str] = field(default_factory=list)
    level: int = 0
    text: str = ""
    caption: list[list[str]] = field(default_factory=list)


def anchorise(markdown: str) -> str:
    """Return canonical Markdown with anchors for `markdown`; see the module docstring."""
    lines, regions = _mask_math(normalise(_mark_pages(markdown)).split("\n"))
    blocks = _attach_captions(_blocks(lines, regions))
    title = _title_index(blocks)
    numbering = _Numbering()
    out: list[str] = []
    for index, block in enumerate(blocks):
        out.extend(numbering.emit(block, title=index == title))
    return "\n\n".join(out) + "\n" if out else ""


def _numbering(text: str) -> str | None:
    """The section path of a heading's text, or None if the heading is unnumbered.

    Digit numbering gives `3` or `3.2`. Ruling F appendix numbering gives `A.1` and `A.1.2` (as
    `101.1` and `101.1.2`), and `A.`, `A:`, `A)` or `A` alone (as `101`). In the letter forms the
    letter must be followed by punctuation and whitespace, or end the heading. A bare `A Title` is
    unnumbered.
    """
    stripped = text.strip()
    digits = _DIGITS.match(stripped)
    if digits is not None:
        return digits.group(1)
    sub = _APPENDIX_SUB.match(stripped)
    if sub is not None:
        return f"{_appendix_index(sub.group(1))}.{sub.group(2)}"
    letter = _APPENDIX_LETTER.match(stripped)
    if letter is not None:
        return str(_appendix_index(letter.group(1)))
    return None


def _appendix_index(letter: str) -> int:
    return 100 + ord(letter) - ord("A") + 1


def _mark_pages(markdown: str) -> str:
    """Replace form feeds and page anchors outside fenced code by page markers; strip every other
    anchor. Inside fenced code a form feed is ordinary text."""
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for raw in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip(" \t")
        if fence is not None:
            close = _FENCE_CLOSE.match(raw)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                fence = None
            out.append(_ANY_ANCHOR.sub("", raw))
            continue
        opened = _FENCE_OPEN.match(raw)
        if opened:
            fence = (opened.group(1)[0], len(opened.group(1)))
            out.append(_ANY_ANCHOR.sub("", raw))
        elif stripped == "\f" or _PAGE_ANCHOR.fullmatch(stripped):
            out.extend(["", _PAGE, ""])
        else:
            out.append(_ANY_ANCHOR.sub("", raw))
    return _STRAY_ANCHOR.sub("&lt;", "\n".join(out))


def _mask_math(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Replace each display math block (outside fenced code) by a placeholder paragraph.

    A block is a run of non-blank lines from a line starting with `$$` to the next line ending in
    `$$`. The original lines are returned in `regions`, indexed by the placeholder.
    """
    masked: list[str] = []
    regions: list[list[str]] = []
    fence: tuple[str, int] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if fence is not None:
            close = _FENCE_CLOSE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1]:
                fence = None
            masked.append(line)
            continue
        opened = _FENCE_OPEN.match(line)
        if opened:
            fence = (opened.group(1)[0], len(opened.group(1)))
            masked.append(line)
            continue
        end = _math_end(lines, index - 1)
        if end is None:
            masked.append(line)
            continue
        regions.append(lines[index - 1 : end + 1])
        masked.extend(["", f"\x00math{len(regions) - 1}\x00", ""])
        index = end + 1
    return masked, regions


def _math_end(lines: list[str], start: int) -> int | None:
    """The last line of the display math block opening at `start`, or None if there is none."""
    text = lines[start].strip()
    if not text.startswith("$$"):
        return None
    if len(text) >= 4 and text.endswith("$$") and text.count("$$") == 2:
        return start
    if "$$" in text[2:]:
        return None
    for end in range(start + 1, len(lines)):
        stripped = lines[end].strip()
        if not stripped:
            return None
        if stripped.endswith("$$"):
            return end
    return None


def _blocks(lines: list[str], regions: list[list[str]]) -> list[_Block]:
    """The top-level blocks of the masked source, in document order."""
    tokens = MARKDOWN.parse("\n".join(lines))
    blocks: list[_Block] = []
    for index, token in enumerate(tokens):
        if not _is_top_level_open(token):
            continue
        assert token.map is not None
        start, end = token.map
        body = _trim(lines[start:end])
        if token.type == "heading_open":
            inline = tokens[index + 1]
            blocks.append(_Block("heading", level=int(token.tag[1]), text=inline.content))
        elif token.type == "paragraph_open":
            placeholder = _MATH.fullmatch(body[0]) if len(body) == 1 else None
            if body == [_PAGE]:
                blocks.append(_Block("page"))
            elif placeholder is not None:
                blocks.append(_Block("math", regions[int(placeholder.group(1))]))
            else:
                blocks.append(_Block("paragraph", body))
        elif token.type == "table_open":
            blocks.append(_Block("table", body))
        else:
            blocks.append(_Block("other", body))
    return blocks


def _is_top_level_open(token: Token) -> bool:
    return token.level == 0 and token.nesting != -1 and token.map is not None


def _trim(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return lines[start:end]


def _is_caption(block: _Block) -> bool:
    return block.kind == "paragraph" and _TABLE_CAPTION.match(block.lines[0].strip()) is not None


def _caption_run(blocks: list[_Block], removed: set[int], start: int, step: int) -> list[int]:
    """Indexes of the unclaimed caption paragraphs directly after (step 1) or before (step -1)
    `start`, nearest first."""
    run: list[int] = []
    index = start + step
    while 0 <= index < len(blocks) and index not in removed and _is_caption(blocks[index]):
        run.append(index)
        index += step
    return run


def _attach_captions(blocks: list[_Block]) -> list[_Block]:
    """Move each run of `Table <n>` paragraphs next to a table below that table.

    A table claims the unclaimed caption paragraphs directly after it, then those directly before
    it. A claimed paragraph is removed from its place, so no block is left next to a table that
    was not next to one before: a second pass claims exactly the same captions.
    """
    removed: set[int] = set()
    for index, block in enumerate(blocks):
        if block.kind != "table":
            continue
        claimed = sorted(
            _caption_run(blocks, removed, index, 1) + _caption_run(blocks, removed, index, -1)
        )
        removed.update(claimed)
        block.caption = [blocks[position].lines for position in claimed]
    return [block for index, block in enumerate(blocks) if index not in removed]


def _title_index(blocks: list[_Block]) -> int | None:
    """The index of the document title: the only minimum-depth heading, unnumbered, with deeper
    headings present. None if there is no title."""
    headings = [(index, block) for index, block in enumerate(blocks) if block.kind == "heading"]
    if not headings:
        return None
    depth = min(block.level for _, block in headings)
    top = [(index, block) for index, block in headings if block.level == depth]
    if len(top) != 1 or len(headings) == len(top):
        return None
    index, block = top[0]
    return index if _numbering(block.text) is None else None


def _spans(tokens: list[Token]) -> list[tuple[str, int, int]]:
    """(kind, first line, end line) of each top-level block, in order."""
    spans: list[tuple[str, int, int]] = []
    for token in tokens:
        if _is_top_level_open(token):
            assert token.map is not None
            spans.append((_KINDS.get(token.type, "other"), token.map[0], token.map[1]))
    return spans


def _anchors_ok(kind: str, lines: list[str]) -> bool:
    """True if `<a id>` followed by `lines` parses as exactly one element of `kind` on those lines.

    A paragraph may absorb the anchor line as its first line; any other kind must start on the
    line after an anchor-only paragraph.
    """
    count = len(lines)
    spans = _spans(MARKDOWN.parse("\n".join([_PROBE, *lines])))
    if kind == "paragraph" and spans == [("paragraph", 0, count + 1)]:
        return True
    return spans == [("paragraph", 0, 1), (kind, 1, count + 1)]


def _anchored(anchor_id: str, lines: list[str]) -> str:
    return "\n".join([f'<a id="{anchor_id}"></a>', *lines])


def _atx(level: int, text: str) -> str:
    """An ATX heading line with the given inline content, safe from closing-sequence parsing."""
    content = " ".join(part.strip() for part in text.split("\n")).strip()
    trailing = re.search(r"(^|\s)(#+)$", content)
    if trailing:
        cut = trailing.start(2)
        content = content[:cut] + "\\" + content[cut:]
    return "#" * level + (f" {content}" if content else "")


class _Numbering:
    """The state that assigns ids in document order."""

    def __init__(self) -> None:
        self.used: set[str] = set()
        self.section = "s0"
        self.paragraphs: dict[str, int] = {}
        self.ordinals: dict[tuple[str | None, int], int] = {}
        self.stack: list[tuple[int, str]] = []
        self.pages = 0
        self.tables = 0
        self.equations = 0

    def emit(self, block: _Block, *, title: bool) -> list[str]:
        """The output blocks (each a string of lines) for one source block."""
        if block.kind == "page":
            self.pages += 1
            return [_anchored(f"p{self.pages}", [])]
        if block.kind == "heading":
            return [self._heading(block, title=title)]
        if block.kind == "paragraph":
            return [self._paragraph(block.lines)]
        if block.kind == "math":
            return [self._equation(block.lines)]
        if block.kind == "table":
            return self._table(block)
        return ["\n".join(block.lines)]

    def _heading(self, block: _Block, *, title: bool) -> str:
        parent = self._parent(block.level)
        numbered = None if title else _numbering(block.text)
        key = (parent, block.level)
        if title:
            base, last = "s0", None
        elif numbered is not None:
            base, last = f"s{numbered}", int(numbered.rsplit(".", 1)[-1])
        else:
            ordinal = self.ordinals.get(key, 0) + 1
            base = f"s{ordinal}" if parent is None else f"{parent}.{ordinal}"
            last = ordinal
        sid = self._unique(base)
        if last is not None:
            self.ordinals[key] = max(self.ordinals.get(key, 0), last)
        self.stack.append((block.level, sid))
        self.section = sid
        return _anchored(sid, [_atx(block.level, block.text)])

    def _parent(self, level: int) -> str | None:
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        return self.stack[-1][1] if self.stack else None

    def _unique(self, base: str) -> str:
        candidate, suffix = base, 2
        while candidate in self.used:
            candidate = f"{base}.{suffix}"
            suffix += 1
        self.used.add(candidate)
        return candidate

    def _paragraph(self, lines: list[str]) -> str:
        figure = _FIGURE.match(lines[0].strip())
        if figure is not None:
            number = int(figure.group(1))
            while f"f{number}.cap" in self.used:
                number += 1
            if not _anchors_ok("paragraph", lines):
                return "\n".join(lines)
            self.used.add(f"f{number}.cap")
            return _anchored(f"f{number}.cap", lines)
        ident = f"{self.section}.p{self.paragraphs.get(self.section, 0) + 1}"
        if not _anchors_ok("paragraph", lines):
            return "\n".join(lines)
        self.paragraphs[self.section] = self.paragraphs.get(self.section, 0) + 1
        self.used.add(ident)
        return _anchored(ident, lines)

    def _equation(self, lines: list[str]) -> str:
        if not _anchors_ok("paragraph", lines):
            return "\n".join(lines)
        self.equations += 1
        return _anchored(f"e{self.equations}", lines)

    def _table(self, block: _Block) -> list[str]:
        rows = [block.lines[0], *block.lines[2:]]
        rectangular = len({len(split_row(row)) for row in rows}) == 1
        text = "\n".join(block.lines)
        if rectangular and _anchors_ok("table", block.lines):
            self.tables += 1
            text = _anchored(f"t{self.tables}", block.lines)
        parts = [text]
        parts.extend("\n".join(lines) for lines in block.caption)
        return parts
