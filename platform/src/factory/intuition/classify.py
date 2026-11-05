"""Pure rules of the `uses` links of background concepts (slice 3c, plan G3-B; rulings B1, B6, B8).

Invariants: names are compared folded (NFKC, case-fold, whitespace collapsed) and whole-word, so
"kernel" never matches "kernels"; a link is `stated` only for a quote that names the concept or a
citation of the concept's approved source, otherwise `inferred` with exactly one reason; a link
from a concept is always inferred. Nothing here reads the index or judges meaning.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from typing import Literal

from factory.extraction.numbers import normalise_text
from factory.model.intuition import ConceptSourceInput


def fold(s: str) -> str:
    """NFKC, case-folded, whitespace collapsed."""
    return normalise_text(s)


def name_in_text(names: Collection[str], text: str) -> bool:
    """True when a folded name occurs in the folded text bounded by non-word characters."""
    haystack = fold(text)
    for name in names:
        needle = fold(name)
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            return True
    return False


def source_digest(source: ConceptSourceInput) -> str:
    """`src_` + the first 16 hex digits of the SHA-256 of the canonical JSON of the source's
    kind, citation and work id: an approval binds to exactly this source (ruling B1)."""
    canonical = json.dumps(
        {"kind": source.kind.value, "citation": source.citation, "work_id": source.work_id},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "src_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def classify_use(
    *,
    from_kind: str,
    names: Collection[str],
    quote: str | None,
    cited_work: str | None,
    link_resolved: bool | None,
    source_work: str | None,
    source_approved: bool,
) -> tuple[Literal["stated", "inferred"], str]:
    """Ruling B6. `quote` is a verified quote of the citing work, `cited_work` the work a
    reference entry resolves to and `link_resolved` whether that link is resolved or confirmed;
    `source_work` and `source_approved` describe the concept's source."""
    if from_kind == "concept":
        return "inferred", "concept-to-concept"
    if quote is not None:
        if name_in_text(names, quote):
            return "stated", "name-in-quote"
        return "inferred", "name-not-in-quote"
    if cited_work is not None or link_resolved is not None:
        if cited_work is None or not link_resolved:
            return "inferred", "citation-unresolved"
        if source_work is None:
            return "inferred", "source-not-in-corpus"
        if cited_work != source_work:
            return "inferred", "citation-not-approved-source"
        if not source_approved:
            return "inferred", "source-unapproved"
        return "stated", "cites-approved-source"
    return "inferred", "no-basis"


def would_cycle(edges: Collection[tuple[str, str]], new: tuple[str, str]) -> bool:
    """Whether adding `new` (from, to) to `edges` closes a cycle or is a self-link (ruling B8)."""
    start, end = new
    if start == end:
        return True
    adjacent: dict[str, list[str]] = {}
    for a, b in edges:
        adjacent.setdefault(a, []).append(b)
    seen = {end}
    stack = [end]
    while stack:
        node = stack.pop()
        if node == start:
            return True
        for nxt in adjacent.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
