"""Verbatim quote check against the plain text of a canonical Markdown element.

A quote is accepted only if its normalised form occurs as a contiguous substring of the normalised
text of one block of the element. Blocks and table cells are never joined, so a quote cannot span
them. Normalisation is NFKC (folding ligatures and no-break spaces), removal of soft hyphens and
zero-width characters, and collapse of every whitespace run to one space. Case is preserved: the
check is case-sensitive.

Escape rule. The converter stores Markdown backslash escapes (`team\\_size`) and `document_read`
serves them as stored, while the parsed block text has them removed. `quote_in_element` therefore
removes, on the quote and on the block text alike, a backslash that precedes an ASCII punctuation
character (the CommonMark escapable set), and nothing else: a backslash before a letter, digit or
space stays. Both sides get the same rule, so it can only accept more quotes, never fewer.
Known limit: block text is flattened, so a literal backslash inside a code span or math is also
dropped (quote `a_b` verifies against code `a\\_b`); accepted as a small false accept.

Entity rule. The converter also stores HTML character references (`Planning &amp; Control`),
which markdown-it decodes in the block text. Complete references (ending in `;`: named, decimal or
hexadecimal) are decoded on both sides before the escape rule, so a quote copied as served or as
rendered verifies; `&amp` without `;` is left as written, and so is a reference that decodes to a
control character (category Cc, e.g. `&#1;`).
"""

import html
import re
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
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
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
    needle = normalise_quote(_unescape(quote))
    if not needle:
        return False
    return any(
        needle in normalise_quote(_unescape(block)) for block in element_blocks(element_markdown)
    )


def _decode_entity(match: re.Match[str]) -> str:
    """The decoded reference, or the reference as written when it does not decode to printable
    non-control characters (`&#1;` is left alone, so it never matches a quote without it)."""
    raw = match.group(0)
    out = html.unescape(raw)
    if out == raw or any(unicodedata.category(ch) == "Cc" for ch in out):
        return raw
    return out


def _unescape(text: str) -> str:
    """Remove a backslash before ASCII punctuation (the Markdown escape) and decode complete HTML
    character references (`&amp;`, `&#8211;`, ending in `;`); see the module doc."""
    decoded = _ENTITY.sub(_decode_entity, text)
    return _ESCAPE.sub(r"\1", decoded)


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
