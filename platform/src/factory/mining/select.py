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
- Fallback (IDEA-99): `heading_share` is the share of PARAGRAPH words (whitespace split of the
  anchor text) lying in the sections the heading patterns match, over all paragraph words of the
  manifest, whatever the selector's element kinds. When the selector has heading patterns, its
  element kinds are empty or include PARAGRAPH (`can_fall_back`) and the share is below
  `SELECTION_FALLBACK_BELOW` (a document with no paragraph words never falls back), the selection
  is replaced by the anchors of the selector's element kinds in every section, bibliography
  entries excluded, and `fallback=True`. A selector without heading patterns, or of kinds that
  exclude PARAGRAPH, never falls back; without patterns the share is None.
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
    """The anchors served, the share of paragraph words lying in the sections the selector's
    heading patterns match (None when the selector has no patterns or the document no paragraph
    words), and whether the fallback to every section applied."""

    anchors: tuple[str, ...]
    matched_share: float | None
    fallback: bool


def _words(anchor: Anchor) -> int:
    return len(anchor.text.split())


def can_fall_back(selector: Selector) -> bool:
    """Whether the fallback can apply to `selector`: it has heading patterns and its element kinds
    are empty (all kinds) or include PARAGRAPH. A selector of tables only never falls back, since
    the share is measured in paragraph words and a table selection is not a paragraph miss."""
    return bool(selector.heading_patterns) and (
        not selector.elements or AnchorKind.PARAGRAPH in selector.elements
    )


def heading_share(manifest: Manifest, selector: Selector) -> float | None:
    """The share of the manifest's paragraph words that lie in the sections the selector's heading
    patterns match (a paragraph lies in a matched section when any enclosing section's heading
    matches), whatever the selector's element kinds. None when the selector has no heading
    patterns or the manifest has no paragraph words (the share is then undefined)."""
    if not selector.heading_patterns:
        return None
    patterns = [re.compile(p, re.IGNORECASE) for p in selector.heading_patterns]
    total = 0
    matched = 0
    for anchor in manifest.anchors:
        if anchor.kind is not AnchorKind.PARAGRAPH:
            continue
        words = _words(anchor)
        total += words
        if any(p.search(h) for p in patterns for h in _headings(manifest, anchor)):
            matched += words
    return None if total == 0 else matched / total


def select_with_fallback(manifest: Manifest, selector: Selector) -> Selection:
    """`selected_anchors`, or every section of the selector's kinds when its heading patterns
    match under `SELECTION_FALLBACK_BELOW` of the paragraph words (see the module invariants)."""
    chosen = selected_anchors(manifest, selector)
    share = heading_share(manifest, selector)
    if share is None or not can_fall_back(selector) or share >= SELECTION_FALLBACK_BELOW:
        return Selection(chosen, share, False)
    kinds = set(selector.elements)
    everywhere = tuple(
        a.id
        for a in manifest.anchors
        if a.kind is not AnchorKind.BIBLIOGRAPHY_ENTRY and (not kinds or a.kind in kinds)
    )
    return Selection(everywhere, share, True)
