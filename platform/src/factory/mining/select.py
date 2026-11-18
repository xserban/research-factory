"""Selector evaluation over a manifest (M-C ruling 3). Pure.

A selector never names anchors. `selected_anchors` evaluates it on a pinned conversion's manifest:
the anchors of the listed kinds (all kinds when none is listed) that lie in a section whose
heading matches a pattern (every section when no pattern is given).

Invariants:
- A heading is the text of a `SECTION` anchor without its leading `#` marks, passed through
  `normalise_text` (NFKC, casefold, collapsed whitespace); a pattern matches by `re.search`,
  case-insensitively, and need not cover the whole heading.
- An anchor lies in the section that encloses it or in any section above that one, so a pattern
  on `Method` selects the anchors of `3.2 Setup` too. A section anchor encloses itself.
- Anchors keep document order; the result holds ids only, never document text.
- Fallback (IDEA-99): `select_with_fallback` measures the share of PARAGRAPH words (whitespace
  split of the anchor text) that lie in the selected anchors, over all paragraph words of the
  manifest. When the selector has heading patterns and the share is below
  `SELECTION_FALLBACK_BELOW` (a document with no paragraph words never falls back), it serves
  the anchors of the selector's element kinds in every section instead, bibliography entries
  excluded, and reports `fallback=True`. A selector without heading patterns never falls back.
  It is a pure function of the manifest and the selector; the share is not rounded here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.extraction.numbers import normalise_text
from factory.mining.spec import Selector


def heading_text(section: Anchor) -> str:
    """The normalised heading of a section anchor: its source without the leading `#` marks."""
    return normalise_text(section.text.lstrip("#"))


def _headings(manifest: Manifest, anchor: Anchor) -> list[str]:
    """The normalised headings of the sections enclosing `anchor`, nearest first."""
    out: list[str] = []
    seen: set[str] = set()
    current: Anchor | None = anchor
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.kind is AnchorKind.SECTION:
            out.append(heading_text(current))
        current = None if current.parent is None else manifest.get(current.parent)
    return out


def selected_anchors(manifest: Manifest, selector: Selector) -> tuple[str, ...]:
    """The ids of the anchors `selector` selects in `manifest`, in document order."""
    patterns = [re.compile(p, re.IGNORECASE) for p in selector.heading_patterns]
    kinds = set(selector.elements)
    chosen: list[str] = []
    for anchor in manifest.anchors:
        if kinds and anchor.kind not in kinds:
            continue
        if patterns:
            headings = _headings(manifest, anchor)
            if not any(p.search(h) for p in patterns for h in headings):
                continue
        chosen.append(anchor.id)
    return tuple(chosen)


SELECTION_FALLBACK_BELOW = 0.10
"""Below this share of paragraph words a heading selection is replaced by every section."""


@dataclass(frozen=True)
class Selection:
    """The anchors served, the share of paragraph words the selector matched, and whether the
    fallback to every section applied."""

    anchors: tuple[str, ...]
    matched_share: float
    fallback: bool


def _words(anchor: Anchor) -> int:
    return len(anchor.text.split())


def select_with_fallback(manifest: Manifest, selector: Selector) -> Selection:
    """`selected_anchors`, or every section of the selector's kinds when its heading patterns
    match under `SELECTION_FALLBACK_BELOW` of the paragraph words (see the module invariants)."""
    chosen = selected_anchors(manifest, selector)
    total = sum(_words(a) for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH)
    if total == 0:
        return Selection(chosen, 0.0, False)
    ids = set(chosen)
    matched = sum(
        _words(a) for a in manifest.anchors if a.kind is AnchorKind.PARAGRAPH and a.id in ids
    )
    share = matched / total
    if not selector.heading_patterns or share >= SELECTION_FALLBACK_BELOW:
        return Selection(chosen, share, False)
    kinds = set(selector.elements)
    everywhere = tuple(
        a.id
        for a in manifest.anchors
        if a.kind is not AnchorKind.BIBLIOGRAPHY_ENTRY and (not kinds or a.kind in kinds)
    )
    return Selection(everywhere, share, True)
