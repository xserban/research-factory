"""Generic web-page HTML to Markdown, for captured grey literature (plan SG, Task 5).

Not a candidate of decision 49 (whose question covers LaTeX and PDF): it accepts only the media
type `WEB_CAPTURE_HTML`, which a captured page carries, so it never competes with `latexml-html`
for `text/html`. It is lxml-only and deterministic: it walks the body, drops scripts, styles and
page furniture (nav, header, footer, aside, forms), and writes headings, paragraphs, lists, code
blocks and tables (as rectangular pipe tables). Links keep their text; no URL is written.

Invariants: for fixed bytes the output is byte-identical; a page that does not parse gives empty
Markdown and a warning, never an exception.
"""

from __future__ import annotations

import lxml
from lxml import etree, html

WEB_CAPTURE_HTML = "text/x-web-capture+html"
CONVERTER_VERSION = "1"

_DROP = frozenset(
    {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe"}
)
_HEADINGS = {f"h{n}": n for n in range(1, 7)}
_BLOCKS = frozenset({"p", "div", "section", "article", "main", "blockquote", "figure", "body"})


def _squash(text: str) -> str:
    return " ".join(text.split())


def _inline(el: etree._Element) -> str:
    return _squash("".join(el.itertext()))


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _table(el: etree._Element) -> str:
    rows = [
        [_cell(_inline(c)) for c in row if isinstance(c.tag, str) and c.tag in ("td", "th")]
        for row in el.iter("tr")
    ]
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _walk(el: etree._Element, out: list[str]) -> None:
    for child in el:
        tag = child.tag
        if not isinstance(tag, str) or tag in _DROP:
            continue
        if tag in _HEADINGS:
            text = _inline(child)
            if text:
                out.append("#" * _HEADINGS[tag] + " " + text)
        elif tag in ("ul", "ol"):
            for n, item in enumerate(child.iter("li"), start=1):
                text = _inline(item)
                if text:
                    out.append((f"{n}." if tag == "ol" else "-") + " " + text)
        elif tag == "pre":
            out.append("```\n" + "".join(child.itertext()).strip("\n") + "\n```")
        elif tag == "table":
            rendered = _table(child)
            if rendered:
                out.append(rendered)
        elif tag in _BLOCKS and any(
            isinstance(g.tag, str) and (g.tag in _BLOCKS or g.tag in _HEADINGS or g.tag in _DROP)
            for g in child
        ):
            _walk(child, out)
        else:
            text = _inline(child)
            if text:
                out.append(text)


class HtmlGenericConverter:
    """Converts a captured web page to Markdown; see the module docstring."""

    name = "html-generic"
    accepts = frozenset({WEB_CAPTURE_HTML})

    def version(self) -> str:
        return f"{CONVERTER_VERSION}+lxml{lxml.__version__}"  # type: ignore[attr-defined]

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        try:
            root = html.fromstring(raw)
        except (etree.ParserError, ValueError):
            return "", ("document: not parseable as HTML",)
        body = root.find("body")
        blocks: list[str] = []
        _walk(root if body is None else body, blocks)
        title = root.findtext(".//title")
        if title and _squash(title):
            blocks.insert(0, "# " + _squash(title))
        return "\n\n".join(blocks) + "\n", ()
