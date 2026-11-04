"""Verbatim quote check against the plain text of a canonical Markdown element.

A quote is accepted only if its normalised form occurs as a contiguous substring of the normalised
plain text of the element. Normalisation is NFKC (folding ligatures and no-break spaces), removal
of soft hyphens and zero-width characters, and collapse of every whitespace run to one space.
Case is preserved: the check is case-sensitive.
"""

import unicodedata
from collections.abc import Iterable

from markdown_it.token import Token

from factory.document.anchors import MARKDOWN

_INVISIBLE = frozenset("­​‌‍⁠﻿")
_LINE_BREAKS = frozenset({"softbreak", "hardbreak"})


def element_plain_text(markdown: str) -> str:
    """The plain text of a Markdown element: markup removed, its blocks joined with a space.

    Inline text, code spans and image alt text are kept; line breaks become spaces. The result is
    not whitespace-normalised; `normalise_quote` does that for the comparison.
    """
    parts = [_block_text(token) for token in MARKDOWN.parse(markdown)]
    return " ".join(part for part in parts if part)


def normalise_quote(text: str) -> str:
    """The comparison form of a quote or of element text; see the module docstring."""
    folded = unicodedata.normalize("NFKC", text)
    kept = "".join(ch for ch in folded if ch not in _INVISIBLE)
    return " ".join(kept.split())


def quote_in_element(element_markdown: str, quote: str) -> bool:
    """True if the quote, normalised, is a non-empty substring of the normalised element text."""
    needle = normalise_quote(quote)
    if not needle:
        return False
    return needle in normalise_quote(element_plain_text(element_markdown))


def _block_text(token: Token) -> str:
    if token.type == "inline":
        return _inline_text(token.children or [])
    if token.type in ("fence", "code_block"):
        return token.content
    return ""


def _inline_text(tokens: Iterable[Token]) -> str:
    out: list[str] = []
    for token in tokens:
        if token.type in _LINE_BREAKS:
            out.append(" ")
        elif token.type == "image":
            out.append(_inline_text(token.children or []))
        elif token.type in ("text", "code_inline"):
            out.append(token.content)
    return "".join(out)
