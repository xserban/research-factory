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
"""

from __future__ import annotations

import re

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
