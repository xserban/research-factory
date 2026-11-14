"""Reference list of a JATS article as plain-text paragraphs.

pandoc renders `<ref-list>` as an empty `<div id="refs">` (the entries need citeproc, which
rewrites text). This module reads the XML directly and returns one line per `<ref>`, and puts
those lines where pandoc left the empty block. Pure and deterministic; no network, no pandoc.
"""

import re
import xml.etree.ElementTree as ET

_REFS_DIV = re.compile(r'<div id="refs"[^>]*>\s*</div>')
_HEADING = re.compile(
    r"^#+\s*(references|bibliography|literature cited|works cited|reference list)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _text(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _element_citation(cit: ET.Element) -> str:
    """Join the parts of an `element-citation` (which has no punctuation) in a fixed order."""
    names: list[str] = []
    for name in cit.findall("./person-group[@person-group-type='author']/name") or cit.findall(
        ".//name"
    ):
        piece = " ".join(
            p for p in (_text(name.find("surname")), _text(name.find("given-names"))) if p
        )
        if piece:
            names.append(piece)
    for coll in cit.findall(".//collab"):
        if _text(coll):
            names.append(_text(coll))
    pages = "-".join(p for p in (_text(cit.find("fpage")), _text(cit.find("lpage"))) if p)
    doi = _text(cit.find("pub-id[@pub-id-type='doi']"))
    parts = [
        ", ".join(names),
        _text(cit.find("year")),
        _text(cit.find("article-title")) or _text(cit.find("chapter-title")),
        _text(cit.find("source")),
        _text(cit.find("volume")),
        pages,
        f"doi:{doi}" if doi else "",
    ]
    return ". ".join(p.rstrip(".") for p in parts if p)


def _entry(ref: ET.Element, ordinal: int) -> str:
    mixed = ref.find("mixed-citation")
    cit = ref.find("element-citation")
    if mixed is None:
        mixed = ref.find("nlm-citation")
    if mixed is not None and _text(mixed):
        body = _text(mixed)
    elif cit is not None and _element_citation(cit):
        body = _element_citation(cit)
    else:
        label = ref.find("label")
        body = " ".join("".join(el.itertext()).strip() for el in ref if el is not label).strip()
        body = " ".join(body.split())
    label_text = _text(ref.find("label")).strip("[]().") or str(ordinal)
    return f"[{label_text}] {body}"


def reference_entries(xml: bytes) -> list[str]:
    """One plain-text line per `<ref>` under `back`, in document order; `[]` if unreadable."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out: list[str] = []
    for back in root.iter("back"):
        for ref in back.iter("ref"):
            line = _entry(ref, len(out) + 1)
            if line.split("] ", 1)[-1].strip():
                out.append(line)
    return out


def with_reference_list(markdown: str, xml: bytes) -> str:
    """`markdown` with the empty pandoc refs block replaced by the entries as paragraphs.

    Without the block, entries are appended under `# References` unless a bibliography heading
    already exists. With no entries the markdown is returned unchanged.
    """
    entries = reference_entries(xml)
    if not entries:
        return markdown
    body = "\n\n".join(entries)
    if _REFS_DIV.search(markdown):
        if not _HEADING.search(markdown):
            body = "# References\n\n" + body
        return _REFS_DIV.sub(lambda _m: body, markdown, count=1)
    if _HEADING.search(markdown):
        return markdown
    return markdown.rstrip("\n") + "\n\n# References\n\n" + body + "\n"
