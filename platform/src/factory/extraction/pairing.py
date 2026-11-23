"""Candidate pairs between the unmatched contribution rows of pass A and pass B (IDEA-140).

Pure: no I/O, no model. Row keys hash the anchor of the first anchored field, so two passes that
cite different paragraphs for the same item never align; this module proposes, for a human to
confirm, which unmatched A row most likely describes the same item as which unmatched B row.
Invariants: rows pair only within one work and one ``item_kind``; a ``not-stated`` row pairs only
with the same ``absent_kind``; a row is proposed at most once (greedy by score, ties broken by
row keys); a candidate needs name or citation evidence, never the anchor alone; statements and
quotes are never compared. The output is a proposal: nothing here resolves a disagreement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

NOT_STATED = "not-stated"
DEFAULT_MIN_SCORE = 0.3
W_TEXT = 0.6
W_ENTRY = 0.2
W_VALUE = 0.2
W_SECTION = 0.15
W_PARENT = 0.075
W_YEAR = 0.05
W_ABSENT = 0.5
_NOISE = frozenset({"et", "al", "and"})
_YEAR = re.compile(r"^(?:19|20)\d{2}[a-z]?$")
_PARAGRAPH = re.compile(r"\.p\d+$")


@dataclass(frozen=True)
class PairRow:
    """The fields of one unmatched row that pairing reads. ``text`` is the name, or the metric
    for a result row; ``value`` its canonical value."""

    work_id: str
    row_key: str
    item_kind: str
    absent_kind: str | None = None
    text: str | None = None
    cited_entry: int | None = None
    value: str | None = None
    anchor: str | None = None


@dataclass(frozen=True)
class Candidate:
    work_id: str
    a_key: str
    b_key: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Proposal:
    pairs: tuple[Candidate, ...]
    a_without: tuple[tuple[str, str], ...]
    """``(work_id, row_key)`` of A rows with no candidate, sorted."""
    b_without: tuple[tuple[str, str], ...]


def name_tokens(text: str | None) -> tuple[frozenset[str], frozenset[str]]:
    """Casefolded alphanumeric tokens of a free-text name without ``et al`` and ``and``, and
    its years apart: ``Itti & Baldi [2005]`` gives ({itti, baldi}, {2005})."""
    words = re.findall(r"[^\W_]+", (text or "").casefold())
    years = frozenset(w for w in words if _YEAR.match(w))
    return frozenset(w for w in words if w not in _NOISE and w not in years), years


def section_of(anchor: str | None) -> str | None:
    """The section an anchor lies in (``s1.2.p3`` gives ``s1.2``); None for other anchors."""
    if anchor is None or not anchor.startswith("s"):
        return None
    return _PARAGRAPH.sub("", anchor)


def _top(section: str) -> str:
    return section.split(".", 1)[0]


def score_pair(a: PairRow, b: PairRow) -> tuple[float, tuple[str, ...]] | None:
    """The score and reasons of A against B, or None when they cannot be the same item."""
    if a.work_id != b.work_id or a.item_kind != b.item_kind:
        return None
    reasons = [f"kind {a.item_kind}"]
    if a.item_kind == NOT_STATED:
        if a.absent_kind != b.absent_kind:
            return None
        return W_ABSENT, (*reasons, f"absent_kind {a.absent_kind}")
    score = 0.0
    (ta, ya), (tb, yb) = name_tokens(a.text), name_tokens(b.text)
    shared = ta & tb
    same_entry = a.cited_entry is not None and a.cited_entry == b.cited_entry
    if not shared and not same_entry:
        return None
    if shared:
        score += W_TEXT * len(shared) / len(ta | tb)
        reasons.append(f"name tokens {'/'.join(sorted(shared))} ({len(shared)}/{len(ta | tb)})")
        if ya & yb:
            score += W_YEAR
            reasons.append("same year")
    if same_entry:
        score += W_ENTRY
        reasons.append(f"same cited entry {a.cited_entry}")
    if a.value is not None and a.value == b.value:
        score += W_VALUE
        reasons.append(f"same value {a.value}")
    sa, sb = section_of(a.anchor), section_of(b.anchor)
    if sa is not None and sb is not None:
        if sa == sb:
            score += W_SECTION
            reasons.append(f"same section {sa}")
        elif _top(sa) == _top(sb):
            score += W_PARENT
            reasons.append(f"same top section {_top(sa)}")
    return round(score, 4), tuple(reasons)


def propose_pairs(
    a_rows: Iterable[PairRow], b_rows: Iterable[PairRow], min_score: float = DEFAULT_MIN_SCORE
) -> Proposal:
    """Greedy one-to-one proposals over the unmatched rows, best score first; ties go to the
    lower ``(work, a key, b key)``. Rows left over are reported as without candidate."""
    a_list, b_list = sorted(a_rows, key=_id), sorted(b_rows, key=_id)
    scored: list[Candidate] = []
    for a in a_list:
        for b in b_list:
            hit = score_pair(a, b)
            if hit is not None and hit[0] >= min_score:
                scored.append(Candidate(a.work_id, a.row_key, b.row_key, hit[0], hit[1]))
    scored.sort(key=lambda c: (-c.score, c.work_id, c.a_key, c.b_key))
    used_a: set[tuple[str, str]] = set()
    used_b: set[tuple[str, str]] = set()
    chosen: list[Candidate] = []
    for c in scored:
        if (c.work_id, c.a_key) in used_a or (c.work_id, c.b_key) in used_b:
            continue
        used_a.add((c.work_id, c.a_key))
        used_b.add((c.work_id, c.b_key))
        chosen.append(c)
    return Proposal(
        tuple(chosen),
        tuple(_id(a) for a in a_list if _id(a) not in used_a),
        tuple(_id(b) for b in b_list if _id(b) not in used_b),
    )


def _id(row: PairRow) -> tuple[str, str]:
    return (row.work_id, row.row_key)


__all__ = [
    "DEFAULT_MIN_SCORE",
    "Candidate",
    "PairRow",
    "Proposal",
    "name_tokens",
    "propose_pairs",
    "score_pair",
    "section_of",
]
