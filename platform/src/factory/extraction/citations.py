"""Deterministic detection of citation markers in text.

Invariant: the result depends only on ``text`` and ``patterns``; matches are
returned in order of position, and a match overlapping an earlier accepted
match is dropped (the earlier, then the longer, wins).

The patterns come from the pack. For ``ml-benchmark`` the accepted false
positives are ``[0, 1]``, ``[2021]`` and ``(June 2021)``: a spurious marker only
excludes a number from being read as a result (the safe direction).
"""

from __future__ import annotations

import re
from collections.abc import Sequence


def citation_markers(text: str, patterns: Sequence[str]) -> list[str]:
    """Return the marker strings matched by ``patterns`` in ``text``, in order."""
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        spans.extend((m.start(), m.end()) for m in re.finditer(pattern, text))
    spans.sort(key=lambda s: (s[0], -s[1]))
    out: list[str] = []
    last_end = -1
    for start, end in spans:
        if start < last_end or end == start:
            continue
        out.append(text[start:end])
        last_end = end
    return out
