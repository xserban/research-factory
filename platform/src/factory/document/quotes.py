"""Verbatim quote check against the plain text of a canonical Markdown element.

A quote is accepted only if its normalised form occurs as a contiguous substring of the normalised
text of one block of the element. Blocks and table cells are never joined, so a quote cannot span
them. Normalisation is NFKC (folding ligatures and no-break spaces), removal of soft hyphens and
zero-width characters, and collapse of every whitespace run to one space. Case is preserved: the
check is case-sensitive.
"""

import unicodedata
from collections.abc import Iterable

from markdown_it.token import Token

from factory.document.anchors import MARKDOWN

_INVISIBLE = frozenset(
    {
        "\N{SOFT HYPHEN}",
        "\N{ZERO WIDTH SPACE}",
        "\N{ZERO WIDTH NON-JOINER}",
        "\N{ZERO WIDTH JOINER}",
        "\N{WORD JOINER}",
        "\N{ZERO WIDTH NO-BREAK SPACE}",
    }
)
_LINE_BREAKS = frozenset({"softbreak", "hardbreak"})


def element_blocks(markdown: str) -> list[str]:
    """The plain text of each non-empty block of a Markdown element, in document order.

    Table cells are separate blocks. Inline text, code spans and image alt text are kept; line
    breaks become spaces. The texts are not whitespace-normalised.
    """
    return [text for text in (_block_text(t) for t in MARKDOWN.parse(markdown)) if text]


def element_plain_text(markdown: str) -> str:
    """The plain text of a Markdown element: markup removed, its blocks joined with a space."""
    return " ".join(element_blocks(markdown))


def normalise_quote(text: str) -> str:
    """The comparison form of a quote or of element text; see the module docstring."""
    folded = unicodedata.normalize("NFKC", text)
    kept = "".join(ch for ch in folded if ch not in _INVISIBLE)
    return " ".join(kept.split())


def quote_in_element(element_markdown: str, quote: str) -> bool:
    """True if the normalised quote is a non-empty substring of the normalised text of one block.

    A quote never spans two blocks: table cells and paragraphs are matched separately. A soft
    break inside a block is a space, so a quote across the line break of one paragraph matches.
    """
    needle = normalise_quote(quote)
    if not needle:
        return False
    return any(needle in normalise_quote(block) for block in element_blocks(element_markdown))


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
