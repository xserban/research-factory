"""GROBID candidate (Apache-2.0): processFulltextDocument TEI, converted to Markdown here.

The service must be running on localhost:8070 (`grobid_service.py start`). Header and citation
consolidation are off, so no request leaves the machine. GROBID's TEI has no page breaks, so this
candidate emits no `\\f` and the anchoriser creates no page anchors.

TEI mapping: `head` (with `n`) -> heading, level from the dots in `n` (`1` -> `##`, `1.2` -> `###`,
unnumbered -> `##`); `p` -> paragraph; `figure[@type=table]` -> `Table <label>: <caption>` plus a
GFM table (first row is the header); other `figure` -> `Figure <label>: <caption>`; `formula` ->
`$$...$$` (equation label dropped).
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import httpx
from factory.document.converter import ConverterUnavailable
from factory.document.normalise import escape_cell

from adapters._common import PDF

URL = "http://localhost:8070/api"
NS = "{http://www.tei-c.org/ns/1.0}"
TIMEOUT = 600.0


def _tag(el: ET.Element) -> str:
    return el.tag.removeprefix(NS)


def _text(el: ET.Element, skip: frozenset[str] = frozenset()) -> str:
    """Whitespace-collapsed text of `el`, leaving out subtrees whose tag is in `skip`."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            if _tag(child) not in skip:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return " ".join("".join(parts).split())


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(fig: ET.Element) -> list[str]:
    rows = [
        [escape_cell(_escape(_text(c))) for c in row.findall(f"{NS}cell")]
        for row in fig.iter(f"{NS}row")
    ]
    rows = [r for r in rows if r]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return ["\n".join(lines)]


def _figure(fig: ET.Element, counts: dict[str, int]) -> list[str]:
    is_table = fig.get("type") == "table"
    kind = "Table" if is_table else "Figure"
    label = _text(fig.find(f"{NS}label")) if fig.find(f"{NS}label") is not None else ""
    head = fig.find(f"{NS}head")
    head_text = _text(head) if head is not None else ""
    desc = fig.find(f"{NS}figDesc")
    caption = _text(desc) if desc is not None else ""
    number = re.sub(r"\D", "", label or head_text)
    if not number:
        counts[kind] += 1
        number = str(counts[kind])
    out = [f"{kind} {number}: {_escape(caption or head_text)}".rstrip(": ")]
    if is_table:
        out += _table(fig)
    return out


def _blocks(node: ET.Element, level_of: dict[str, int], counts: dict[str, int]) -> list[str]:
    out: list[str] = []
    for child in node:
        tag = _tag(child)
        if tag == "div":
            out += _blocks(child, level_of, counts)
        elif tag == "head":
            number = child.get("n") or ""
            level = 2 + number.rstrip(".").count(".") if number else 2
            title = _escape(_text(child))
            out.append(f"{'#' * min(level, 6)} {number + ' ' if number else ''}{title}".rstrip())
        elif tag == "p":
            text = _text(child)
            if text:
                out.append(_escape(text))
        elif tag == "figure":
            out += _figure(child, counts)
        elif tag == "formula":
            text = _text(child, skip=frozenset({"label"}))
            if text:
                out.append("$$" + text.replace("$", "\\$") + "$$")
    return out


def tei_to_markdown(tei: bytes) -> str:
    """Convert a GROBID TEI document to plain Markdown (see the module docstring)."""
    root = ET.fromstring(tei)
    counts = {"Table": 0, "Figure": 0}
    blocks: list[str] = []
    title = root.find(f".//{NS}titleStmt/{NS}title")
    if title is not None and _text(title):
        blocks.append("# " + _escape(_text(title)))
    abstract = root.find(f".//{NS}abstract")
    if abstract is not None and _text(abstract):
        blocks.append("## Abstract")
        blocks += [_escape(_text(p)) for p in abstract.iter(f"{NS}p") if _text(p)]
    for part in ("body", "back"):
        node = root.find(f".//{NS}text/{NS}{part}")
        if node is not None:
            blocks += _blocks(node, {}, counts)
    return "\n\n".join(blocks) + "\n"


class GrobidConverter:
    name = "grobid"
    accepts = frozenset({PDF})

    def version(self) -> str:
        try:
            response = httpx.get(f"{URL}/version", timeout=10)
            response.raise_for_status()
        except httpx.HTTPError as err:
            raise ConverterUnavailable("GROBID service not running on localhost:8070") from err
        return f"grobid {response.text.strip()} (CRF models, no consolidation)"

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.version()
        response = httpx.post(
            f"{URL}/processFulltextDocument",
            files={"input": ("doc.pdf", raw, "application/pdf")},
            data={"consolidateHeader": "0", "consolidateCitations": "0"},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise RuntimeError(f"GROBID HTTP {response.status_code}")
        return tei_to_markdown(response.content), ()
