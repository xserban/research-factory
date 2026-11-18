"""Cut a canonical anchored Markdown document into search passages.

A passage is the unit of search; its anchors remain the unit of citation. Pure: no I/O.

Invariants:
- Paragraphs (`s<x>.p<k>`) of one section are packed in document order until adding the next
  would exceed `target_words` words; a passage never crosses a section (heading) anchor.
- A paragraph longer than `target_words` is a passage by itself and is never split.
- Paragraphs with no letter, or whose whole stripped, lower-cased plain text is in `BOILERPLATE`,
  are not passage content; they are listed in `skipped` of the passage they fall in (the open
  one, else the next one of the section, else the last one of the section). Paragraphs with
  fewer than four words are packed like any other.
- Bibliography entries, page anchors, equations and table cells are never passages.
- A table is its own passage (cell texts joined with " | "); a figure caption is its own
  passage. Either closes the passage being packed, so passages stay in document order.
- The output depends only on the input.
"""

from dataclasses import dataclass

from factory.document.anchors import Anchor, AnchorKind, parse_manifest
from factory.document.quotes import element_plain_text

BOILERPLATE: frozenset[str] = frozenset(
    {"skip to main content", "references", "acknowledgements", "acknowledgments"}
)


@dataclass(frozen=True)
class Passage:
    """One search unit; `anchors` are the elements it covers, in order."""

    passage_id: str
    anchors: tuple[str, ...]
    section_anchor: str
    section_path: tuple[str, ...]
    text: str
    skipped: tuple[str, ...]


def _is_filtered(text: str) -> bool:
    return not any(ch.isalpha() for ch in text) or text.strip().lower() in BOILERPLATE


def _passage_id(anchors: tuple[str, ...]) -> str:
    return anchors[0] if len(anchors) == 1 else f"{anchors[0]}~{anchors[-1]}"


def _make(
    anchors: list[str],
    texts: list[str],
    skipped: list[str],
    section: str,
    path: tuple[str, ...],
) -> Passage:
    names = tuple(anchors)
    return Passage(_passage_id(names), names, section, path, " ".join(texts), tuple(skipped))


def cut_passages(markdown: str, *, target_words: int = 250) -> list[Passage]:
    """The passages of an anchored Markdown document, in document order."""
    manifest = parse_manifest(markdown)
    headings: dict[str, str] = {
        a.id: element_plain_text(a.text) for a in manifest.anchors if a.kind is AnchorKind.SECTION
    }

    def path_of(section: str) -> tuple[str, ...]:
        if section == "s0":
            return ()
        parts = section[1:].split(".")
        found = (headings.get("s" + ".".join(parts[:n])) for n in range(1, len(parts) + 1))
        return tuple(h for h in found if h is not None)

    cells: dict[str, list[Anchor]] = {}
    for a in manifest.anchors:
        if a.kind is AnchorKind.CELL and a.parent is not None:
            cells.setdefault(a.parent, []).append(a)

    out: list[Passage] = []
    section = "s0"
    anchors: list[str] = []
    texts: list[str] = []
    words = 0
    skipped: list[str] = []  # skipped anchors not yet attached to a passage
    section_start = 0  # index in `out` of the first passage of the current section

    def flush() -> None:
        nonlocal anchors, texts, words, skipped
        if anchors:
            out.append(_make(anchors, texts, skipped, section, path_of(section)))
            skipped = []
        anchors, texts, words = [], [], 0

    def close_section() -> None:
        nonlocal skipped
        flush()
        if skipped and len(out) > section_start:
            last = out[-1]
            out[-1] = Passage(
                last.passage_id,
                last.anchors,
                last.section_anchor,
                last.section_path,
                last.text,
                last.skipped + tuple(skipped),
            )
        skipped = []

    for a in manifest.anchors:
        if a.kind is AnchorKind.SECTION:
            close_section()
            section = a.id
            section_start = len(out)
        elif a.kind is AnchorKind.PARAGRAPH:
            text = element_plain_text(a.text)
            if _is_filtered(text):
                skipped.append(a.id)
                continue
            n = len(text.split())
            if anchors and words + n > target_words:
                flush()
            anchors.append(a.id)
            texts.append(text)
            words += n
        elif a.kind in (AnchorKind.TABLE, AnchorKind.FIGURE_CAPTION):
            flush()
            sec = a.parent or "s0"
            if a.kind is AnchorKind.TABLE:
                text = " | ".join(element_plain_text(c.text) for c in cells.get(a.id, []))
            else:
                text = element_plain_text(a.text)
            if text.strip():
                out.append(_make([a.id], [text], [], sec, path_of(sec)))
    close_section()
    return out
