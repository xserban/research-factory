"""Canonical text normalisation for converter output, and GFM table cell escaping.

Invariants of `normalise` output: NFC; LF line endings; no trailing whitespace; no two adjacent
blank lines outside fenced code; no leading or trailing blank line; exactly one final newline (or
the empty string for empty input); tabs inside table cells replaced by single spaces. Ligatures and
dashes are kept: quote matching handles them later. Applying `normalise` twice gives the same bytes
as applying it once.
"""

import unicodedata

from factory.document.anchors import _MARKDOWN


def normalise(markdown: str) -> str:
    """Return `markdown` in the canonical form described in the module docstring."""
    text = unicodedata.normalize("NFC", markdown).replace("\r\n", "\n").replace("\r", "\n")
    table_lines, verbatim = _line_sets(text)
    lines = [
        (line.replace("\t", " ") if index in table_lines else line).rstrip()
        for index, line in enumerate(text.split("\n"))
    ]
    kept: list[str] = []
    for index, line in enumerate(lines):
        if line == "" and index not in verbatim and (not kept or kept[-1] == ""):
            continue
        kept.append(line)
    while kept and kept[-1] == "":
        kept.pop()
    return "\n".join(kept) + "\n" if kept else ""


def escape_cell(text: str) -> str:
    """Make `text` safe as one GFM table cell: `|` becomes `\\|`, a newline becomes a space, and
    the result is stripped. The column count of the row is then unchanged."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _line_sets(text: str) -> tuple[set[int], set[int]]:
    """0-based line indexes of table rows, and of fenced or indented code (kept verbatim)."""
    tables: set[int] = set()
    verbatim: set[int] = set()
    for token in _MARKDOWN.parse(text):
        if token.map is None:
            continue
        start, end = token.map
        if token.type == "table_open":
            tables.update(range(start, end))
        elif token.type in {"fence", "code_block"}:
            verbatim.update(range(start, end))
    return tables, verbatim
