# ruff: noqa: RUF001
"""A pinned, rule-based sentence splitter for external manuscripts (slice 7b, plan W-C ruling 1;
spec ruling 17). Pure and deterministic.

Declares: `SEGMENTER_VERSION`, `ABBREVIATIONS`, `Segment`, `Format`, `mask`, `reference_span`,
`segment`.

Invariants:
- Offsets are character offsets into the stored bytes decoded as UTF-8. Masking replaces text by
  blanks of the same length, so an offset into the masked text is an offset into the stored text.
- NFC is therefore not applied to the text: it could change its length, and no boundary depends on
  it (an uppercase letter stays one before a combining mark). `cites.cite_keys` applies it to the
  keys, where it matters.
- A sentence is its slice of the masked text: a comment or a masked equation inside a sentence
  reads as blanks, so nothing masked is ever served, and `sha256` is of that slice.
- A heading, a code block, a float, a bibliography or a reference-list section ends a sentence and
  never holds one. A masked equation does not end one, and its periods split nothing.
- A change to any rule here is a new `SEGMENTER_VERSION`, with its mask added to `_MASKS`: an
  existing segmentation stays valid for its units.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from factory.document.anchorise import BIBLIOGRAPHY_HEADINGS, normalise_heading
from factory.references.parse import UPPER

SEGMENTER_VERSION = 1
Format = Literal["markdown", "latex", "text"]

ABBREVIATIONS = frozenset(
    {"al", "e.g", "i.e", "cf", "fig", "figs", "eq", "eqs", "vs", "sec", "tab", "approx", "resp"}
)
"""The tokens (case folded, without the final period) after which a period ends no sentence: W-A
ruling 5 and `al.`, `Sec.`, `Tab.`, `approx.`, `resp.`. A single capital initial is one too."""

_BOUNDARY = re.compile(rf"[.?!](?=\s+(?:[{UPPER}]|\d|\\|\[))")
_PARAGRAPH = re.compile(r"(?:\r\n?|\n)\s*(?:\r\n?|\n)")
_LEADING = "([{\"'`*_“‘"

# LaTeX. The order matters: comments first, so a commented `\begin{figure}` opens nothing.
_TEX_COMMENT = re.compile(r"(?<!\\)(?:\\\\)*%[^\n]*\n?")
_TEX_PREAMBLE = re.compile(r"\A.*?\\begin\{document\}", re.DOTALL)
_TEX_TAIL = re.compile(r"\\end\{document\}.*\Z", re.DOTALL)
_TEX_FLOATS = (
    "figure|table|tabular|tabularx|longtable|thebibliography|verbatim|lstlisting|minted|algorithm"
)
_TEX_MATH = "equation|align|alignat|gather|multline|eqnarray|displaymath|math|split"
_TEX_FLOAT = re.compile(
    rf"\\begin\{{(?P<e>(?:{_TEX_FLOATS})\*?)\}}.*?(?:\\end\{{(?P=e)\}}|\Z)", re.DOTALL
)
_TEX_DISPLAY = re.compile(
    rf"\\begin\{{(?P<e>(?:{_TEX_MATH})\*?)\}}.*?(?:\\end\{{(?P=e)\}}|\Z)|\\\[.*?(?:\\\]|\Z)",
    re.DOTALL,
)
_TEX_HEADING = re.compile(
    r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph|title|author|date"
    r"|caption|bibliography|bibliographystyle|label|input|include|usepackage)\*?"
    r"(?:\[[^\]]*\])?\{(?:[^{}]|\{[^{}]*\})*\}"
)
_TEX_BARE = re.compile(
    r"\\(?:begin|end)\{[^{}]*\}|\\(?:maketitle|tableofcontents|newpage|clearpage|appendix|item)\b"
)
_TEX_BIBLIOGRAPHY = re.compile(
    r"\\begin\{thebibliography\}.*?(?:\\end\{thebibliography\}|\Z)", re.DOTALL
)

# Markdown.
_MD_FRONT = re.compile(r"\A---[ \t]*\r?\n.*?\n(?:---|\.\.\.)[ \t]*\r?(?:\n|\Z)", re.DOTALL)
_MD_FENCE = re.compile(
    r"^ {0,3}(?P<f>`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}(?P=f)[`~]*[ \t\r]*$|\Z)",
    re.DOTALL | re.MULTILINE,
)
_MD_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_MD_ATX = re.compile(r"^ {0,3}(?P<h>#{1,6})(?:[ \t]+(?P<t>[^\n]*?))?[ \t#\r]*$", re.MULTILINE)
_MD_SETEXT = re.compile(r"^[^\n]+\n {0,3}(?:=+|-+)[ \t\r]*$", re.MULTILINE)
_LINE = re.compile(r"^[ \t]*(?P<t>[^\n]*?)[ \t:\r]*$", re.MULTILINE)


@dataclass(frozen=True)
class Segment:
    """One sentence: its ordinal from 1, its offsets (`end` exclusive), the sha256 of its text."""

    ordinal: int
    start: int
    end: int
    sha256: str


def _blank(pattern: re.Pattern[str], text: str, fill: str) -> str:
    return pattern.sub(lambda m: fill * len(m.group(0)), text)


def reference_span(text: str, fmt: Format) -> tuple[int, int] | None:
    """Where the manuscript's own reference list is, its heading left out, or None. The first such
    section counts; it runs to the next heading of its level or above, or to the end."""
    if fmt == "latex":
        found = _TEX_BIBLIOGRAPHY.search(_blank(_TEX_COMMENT, text, " "))
        return None if found is None else found.span()
    if fmt == "markdown":
        headings = list(_MD_ATX.finditer(text))
        for i, m in enumerate(headings):
            if normalise_heading(m.group("t") or "") not in BIBLIOGRAPHY_HEADINGS:
                continue
            level = len(m.group("h"))
            after = (h.start() for h in headings[i + 1 :] if len(h.group("h")) <= level)
            return m.end(), next(after, len(text))
    for m in _LINE.finditer(text):
        if normalise_heading(m.group("t")) in BIBLIOGRAPHY_HEADINGS:
            return m.end(), len(text)
    return None


def _mask_v1(text: str, fmt: Format) -> str:
    span = reference_span(text, fmt)
    if span is not None:
        text = text[: span[0]] + "\n" * (span[1] - span[0]) + text[span[1] :]
    text = text.removeprefix("\ufeff").rjust(len(text))  # a byte order mark is not text
    if fmt == "latex":
        text = _blank(_TEX_COMMENT, text, " ")
        text = _blank(_TEX_PREAMBLE, text, "\n")
        text = _blank(_TEX_TAIL, text, "\n")
        text = _blank(_TEX_FLOAT, text, "\n")
        text = _blank(_TEX_DISPLAY, text, " ")
        text = _blank(_TEX_HEADING, text, "\n")
        return _blank(_TEX_BARE, text, "\n")
    if fmt == "markdown":
        text = _blank(_MD_FRONT, text, "\n")
        text = _blank(_MD_FENCE, text, "\n")
        text = _blank(_MD_COMMENT, text, " ")
        text = _blank(_MD_SETEXT, text, "\n")
        return _blank(_MD_ATX, text, "\n")
    return text


_MASKS: dict[int, Callable[[str, Format], str]] = {1: _mask_v1}


def mask(text: str, fmt: Format, version: int = SEGMENTER_VERSION) -> str:
    """The text with everything that is not prose blanked, of the same length. Raises `KeyError`
    for a segmenter version this platform does not hold."""
    return _MASKS[version](text, fmt)


def _ends_sentence(text: str, stop: int) -> bool:
    """Whether the mark at `stop` ends a sentence, by the token before it."""
    if text[stop] != ".":
        return True
    start = stop
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    token = text[start:stop].lstrip(_LEADING)
    if token.casefold() in ABBREVIATIONS:
        return False
    return not (len(token) == 1 and token.isupper())


def _pieces(text: str, start: int, end: int) -> list[tuple[int, int]]:
    cuts = [start]
    for m in _BOUNDARY.finditer(text, start, end):
        if _ends_sentence(text, m.start()):
            cuts.append(m.end())
    cuts.append(end)
    return list(pairwise(cuts))


def _trimmed(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if any(c.isalnum() for c in text[start:end]) else None


def segment(text: str, fmt: Format) -> list[Segment]:
    """The sentences of `text` in order. A paragraph break always ends a sentence; otherwise `.`,
    `?` or `!` does, before whitespace and an uppercase letter, a digit, `\\` or `[`, unless the
    token before it is an abbreviation or a single capital initial."""
    masked = mask(text, fmt)
    paragraphs: list[tuple[int, int]] = []
    start = 0
    for m in _PARAGRAPH.finditer(masked):
        paragraphs.append((start, m.start()))
        start = m.end()
    paragraphs.append((start, len(masked)))
    out: list[Segment] = []
    for begin, stop in paragraphs:
        for a, b in _pieces(masked, begin, stop):
            span = _trimmed(masked, a, b)
            if span is not None:
                digest = hashlib.sha256(masked[span[0] : span[1]].encode()).hexdigest()
                out.append(Segment(len(out) + 1, span[0], span[1], digest))
    return out
