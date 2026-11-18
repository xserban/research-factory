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
- `section_kind` of a passage is a function of its section path and of the document position
  (whether the back matter had begun at each heading; see `section_kind`). `cut_passages` tracks
  that position in document order: it becomes true at the first heading that is exactly
  references, bibliography, appendix(ces), a supplementary form, or starts with "appendix", and
  stays true. The first heading of the document is treated as a possible title (exact forms only).
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


_NUMBERING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXivx]+\.)(?:\s+|$)")
_TRIM = " \t:.;,-\u2013\u2014*#_()"
_SUPPLEMENTARY = frozenset(
    {
        "appendices",
        "supplementary information",
        "supplementary material",
        "supplementary materials",
        "supplementary",
        "supplement",
    }
)
_BACK_STARTS = (
    "references|bibliography|acknowledgements?|acknowledgments?|funding|competing interests"
    "|conflicts? of interest|declaration of interests|author contributions|ethics statement"
    "|ethical considerations|ethics|data availability|code availability"
    "|data and code availability|statement on ai|table of contents|contents|reporting summary"
    "|broader impacts?|impact statement"
)
_BACK_RE = re.compile(rf"^(?:{_BACK_STARTS})\b")
_BACK_EXACT = frozenset(_BACK_STARTS.replace("?", "").split("|")) | {
    "acknowledgement",
    "acknowledgment",
    "conflict of interest",
    "conflicts of interest",
    "broader impact",
}
_RELATED_RE = re.compile(
    r"^(?:related works?|prior work|previous work|literature review"
    r"|background and related work|related literature)\b"
)
_RELATED_EXACT = frozenset(
    {"related work", "related works", "prior work", "previous work", "literature review"}
    | {"background and related work", "related literature"}
)
_AFTER_BACK = frozenset({"references", "bibliography", "appendix", *_SUPPLEMENTARY})
_DOTTED_LETTER = re.compile(r"^[A-H]\.\d+(?:\.\d+)*\.?\s")
_BARE_LETTER = re.compile(r"^[A-H](?:\.\d+)*\.?\s")


def _words(*stems: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(stems) + ")")


# Checked in this order for one heading: the first group with a match decides.
_BODY: tuple[tuple[SectionKind, re.Pattern[str]], ...] = (
    (
        SectionKind.DISCUSSION,
        _words(
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
        _words(
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
        _words(
            "method",
            "approach",
            "framework",
            "architecture",
            "system",
            "design",
            "implementation",
            "model",
            "setup",
            "prompt",
        ),
    ),
    (SectionKind.FRONT, _words("abstract", "introduction", "overview", "motivation")),
)


def normalise_heading(heading: str) -> str:
    """The heading without leading section numbering ("4.", "4.2 ", "IV."), surrounding
    whitespace and punctuation, lower-cased."""
    text = _NUMBERING.sub("", heading.strip())
    return text.strip(_TRIM).lower()


def is_back_matter_start(heading: str, *, exact: bool = False) -> bool:
    """True for a heading that opens the back matter: references, bibliography, an appendix or
    supplementary material. After the first such heading, bare lettered headings are appendices."""
    plain = normalise_heading(heading)
    if plain in _AFTER_BACK:
        return True
    return plain.startswith("appendix") and not exact


def _is_appendix(heading: str, plain: str, after_back: bool, exact: bool) -> bool:
    if (
        plain == "appendix"
        or plain in _SUPPLEMENTARY
        or (plain.startswith("appendix") and not exact)
    ):
        return True
    if exact:
        return False
    if _DOTTED_LETTER.match(heading.strip()):
        return True
    return after_back and bool(_BARE_LETTER.match(heading.strip()))


def _heading_kind(heading: str, after_back: bool, exact: bool) -> SectionKind | None:
    """The kind one heading names, or None. `exact` limits appendix/back/related to whole-heading
    matches (used for a document's first heading, which is usually the paper title)."""
    plain = normalise_heading(heading)
    if _is_appendix(heading, plain, after_back, exact):
        return SectionKind.APPENDIX
    if plain in _BACK_EXACT or (not exact and _BACK_RE.match(plain)):
        return SectionKind.BACK
    if plain == "background" or plain in _RELATED_EXACT or (not exact and _RELATED_RE.match(plain)):
        return SectionKind.RELATED
    for kind, pattern in _BODY:
        if pattern.search(plain):
            return kind
    return None


_BODY_KINDS = frozenset({SectionKind.METHOD, SectionKind.RESULTS, SectionKind.DISCUSSION})


def section_kind(
    section_path: tuple[str, ...],
    after_back: tuple[bool, ...] | None = None,
    *,
    title_first: bool = False,
) -> SectionKind:
    """The kind of a section from its heading texts (case-insensitive, numbering ignored).

    Invariants:
    - Each heading is normalised (`normalise_heading`) and judged alone. The INNERMOST heading
      of the path that names any kind decides; ancestors do not force back or related.
    - Exception: if any heading of the path is an appendix, the section is appendix.
    - Appendix: the normalised heading starts with "appendix" or is a supplementary form
      (supplementary information/material(s), supplementary, supplement, appendices); or the raw
      heading has a dotted lettered number ("A.3 Code", "B.2.1 Notes"); or, once the back matter
      has begun (`after_back[i]` for heading i), it has a bare lettered number ("G Baseline").
      A bare letter before the references ("A Framework for X") is never appendix.
    - Back: starts with references, bibliography, acknowledgement(s), funding, competing
      interests, conflict(s) of interest, declaration of interests, author contributions, ethics
      statement, ethical considerations, ethics, data/code availability, statement on AI, table
      of contents, contents, reporting summary, broader impact(s), impact statement.
    - Related: starts with related work(s), prior work, previous work, literature review,
      background and related work, related literature; or is exactly "background".
      "Background and Motivation" is not related (front, by "motivation"). A related heading
      nested under a method, results or discussion heading is not related: it names a stage of
      the system ("3 Key Designs > 3.2 Literature Review"); the next heading out decides.
    - Otherwise the first matching group of whole-word stems decides: discussion > results >
      method > front ("Results and Discussion" is discussion). No match gives `OTHER`.
    - `title_first`: path[0] is the document's first heading (normally the paper title); it
      counts as appendix, back or related only when the whole heading is one of the exact forms.
    - `after_back` has one flag per heading, the state when that heading was met; None is all
      False.
    """
    flags = after_back if after_back is not None else (False,) * len(section_path)
    kinds = [_heading_kind(h, flags[i], title_first and i == 0) for i, h in enumerate(section_path)]
    if SectionKind.APPENDIX in kinds:
        return SectionKind.APPENDIX
    for i in range(len(kinds) - 1, -1, -1):
        kind = kinds[i]
        if kind is SectionKind.RELATED and _BODY_KINDS.intersection(kinds[:i]):
            continue  # a related-work heading inside a system section names a stage of it
        if kind is not None:
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
    kind: SectionKind,
) -> Passage:
    names = tuple(anchors)
    return Passage(
        _passage_id(names),
        names,
        section,
        path,
        " ".join(texts),
        tuple(skipped),
        kind,
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

    section_ids = [a.id for a in manifest.anchors if a.kind is AnchorKind.SECTION]
    first_heading = section_ids[0] if section_ids else None
    back_state: dict[str, bool] = {}  # section id -> back matter had begun at its heading
    kind_cache: dict[str, SectionKind] = {}

    def kind_of(section: str) -> SectionKind:
        if section not in kind_cache:
            if section == "s0":
                kind_cache[section] = SectionKind.OTHER
            else:
                parts = section[1:].split(".")
                ids = ["s" + ".".join(parts[:n]) for n in range(1, len(parts) + 1)]
                ids = [i for i in ids if i in headings]
                kind_cache[section] = section_kind(
                    tuple(headings[i] for i in ids),
                    tuple(back_state.get(i, False) for i in ids),
                    title_first=bool(ids) and ids[0] == first_heading,
                )
        return kind_cache[section]

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
    after_back = False  # the back matter has begun
    section_start = 0  # index in `out` of the first passage of the current section

    def flush() -> None:
        nonlocal anchors, texts, words, skipped
        if anchors:
            out.append(_make(anchors, texts, skipped, section, path_of(section), kind_of(section)))
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
            if not after_back and is_back_matter_start(headings[a.id], exact=a.id == first_heading):
                after_back = True
            back_state[a.id] = after_back
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
                out.append(_make([a.id], [text], [], sec, path_of(sec), kind_of(sec)))
    close_section()
    return _merge_short(out)
