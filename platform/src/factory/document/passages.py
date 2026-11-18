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
  passage. Either closes the passage being packed, so passages stay in document order. Tables
  and captions stay their own passage only if they have `MIN_WORDS` words or more.
- A passage (of any type) with fewer than `MIN_WORDS` words merges into the previous passage of
  the same section, else into the next passage of the same section; it stays alone only if it is
  the only passage of its section. A merged passage keeps all anchors in document order, joins
  texts with a space and skipped lists in order, and takes its id from the first and last anchor.
  Merging never crosses a section.
- `section_kind` of a passage is a pure function of its section path (see `section_kind`).
- The output depends only on the input.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from factory.document.anchors import Anchor, AnchorKind, parse_manifest
from factory.document.quotes import element_plain_text

BOILERPLATE: frozenset[str] = frozenset(
    {"skip to main content", "references", "acknowledgements", "acknowledgments"}
)


MIN_WORDS = 30
"""Passages with fewer words merge into a neighbour of the same section."""


class SectionKind(StrEnum):
    """The role of a section in a paper, from its heading path."""

    FRONT = "front"
    METHOD = "method"
    RESULTS = "results"
    DISCUSSION = "discussion"
    RELATED = "related"
    APPENDIX = "appendix"
    BACK = "back"
    OTHER = "other"


_BACK = (
    "reference",
    "bibliograph",
    "acknowledg",
    "author contribution",
    "funding",
    "competing",
    "ethic",
    "availability",
    "statement on ai",
    "contents",
)
_APPENDIX = ("appendix", "supplement", "prompt")
_RELATED = ("related work", "background", "prior work", "literature review")
# Checked in this order for one heading: the first group with a match decides.
_BODY: tuple[tuple[SectionKind, tuple[str, ...]], ...] = (
    (
        SectionKind.DISCUSSION,
        (
            "discussion",
            "limitation",
            "failure",
            "error",
            "lesson",
            "conclusion",
            "future work",
            "threat",
        ),
    ),
    (
        SectionKind.RESULTS,
        (
            "result",
            "experiment",
            "evaluat",
            "analys",
            "ablation",
            "benchmark",
            "case stud",
            "human stud",
            "user stud",
            "finding",
        ),
    ),
    (
        SectionKind.METHOD,
        (
            "method",
            "approach",
            "framework",
            "architecture",
            "system",
            "design",
            "implementation",
            "model",
            "setup",
        ),
    ),
    (SectionKind.FRONT, ("abstract", "introduction", "overview", "motivation")),
)
_LETTERED = re.compile(r"^[A-H](\.\d+)*\.?\s")
_NUMBER = re.compile(r"^\d+(\.\d+)*\.?\s+")


def section_kind(section_path: tuple[str, ...]) -> SectionKind:
    """The kind of a section from its heading texts (case-insensitive).

    Back, appendix and related headings win at any depth, in that priority. Otherwise the
    innermost heading matching front/method/results/discussion decides (discussion > results >
    method > front when one heading matches several). No match gives `OTHER`.
    """
    plain = [_NUMBER.sub("", h).lower() for h in section_path]
    if any(k in h for h in plain for k in _BACK):
        return SectionKind.BACK
    if any(k in h for h in plain for k in _APPENDIX) or any(
        _LETTERED.match(h) for h in section_path
    ):
        return SectionKind.APPENDIX
    if any(k in h for h in plain for k in _RELATED):
        return SectionKind.RELATED
    for heading in reversed(plain):
        for kind, words in _BODY:
            if any(k in heading for k in words):
                return kind
    return SectionKind.OTHER


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def embedding_windows(text: str, max_words: int = 350) -> list[str]:
    """Sub-windows of `text` for vectors only; the passage and its anchors stay whole.

    A text of at most `max_words` words is `[text]`. A longer one is split at sentence ends into
    consecutive windows of at most `max_words` words; a single sentence longer than `max_words`
    is split by words, and its pieces stand alone. Deterministic.
    """
    if len(text.split()) <= max_words:
        return [text]
    windows: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in _SENTENCE_END.split(text.strip()):
        n = len(sentence.split())
        if n > max_words:
            if current:
                windows.append(" ".join(current))
                current, count = [], 0
            words = sentence.split()
            windows.extend(
                " ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)
            )
            continue
        if current and count + n > max_words:
            windows.append(" ".join(current))
            current, count = [], 0
        current.append(sentence)
        count += n
    if current:
        windows.append(" ".join(current))
    return windows


@dataclass(frozen=True)
class Passage:
    """One search unit; `anchors` are the elements it covers, in order."""

    passage_id: str
    anchors: tuple[str, ...]
    section_anchor: str
    section_path: tuple[str, ...]
    text: str
    skipped: tuple[str, ...]
    section_kind: SectionKind


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
    return Passage(
        _passage_id(names),
        names,
        section,
        path,
        " ".join(texts),
        tuple(skipped),
        section_kind(path),
    )


def _merge(a: Passage, b: Passage) -> Passage:
    names = a.anchors + b.anchors
    return Passage(
        _passage_id(names),
        names,
        a.section_anchor,
        a.section_path,
        a.text + " " + b.text,
        a.skipped + b.skipped,
        a.section_kind,
    )


def _merge_short(passages: list[Passage]) -> list[Passage]:
    """Merge passages under `MIN_WORDS` words into a neighbour of the same section."""
    out: list[Passage] = []
    carry: Passage | None = None  # short passage waiting for the next one of its section
    for p in passages:
        if carry is not None:
            if carry.section_anchor == p.section_anchor:
                p, carry = _merge(carry, p), None
            else:
                out.append(carry)
                carry = None
        if len(p.text.split()) >= MIN_WORDS:
            out.append(p)
        elif out and out[-1].section_anchor == p.section_anchor:
            out[-1] = _merge(out[-1], p)
        else:
            carry = p
    if carry is not None:
        out.append(carry)
    return out


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
                last.section_kind,
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
    return _merge_short(out)
