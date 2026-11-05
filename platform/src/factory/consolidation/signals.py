"""Candidate synonym signals (slice 3d ruling 15): string, acronym and target overlap.

Invariants:
- Pure and deterministic: no index, no clock, no model. The same items give the same pairs in the
  same order.
- Cost is bounded by co-occurrence, never by all pairs. String candidates come from blocks (the
  first token of a name and each character trigram); a block larger than `BLOCK_MAX` is skipped, so
  a very common token or trigram cannot make the scan quadratic (its pairs can still be found by
  another signal or another block). A pair is scored only when it shares a first token or at least
  `MIN_SHARED_TRIGRAMS` trigrams. Overlap pairs come from posting lists of the target inverted
  index; a list longer than `POSTING_MAX` is skipped for the same reason.
- A pair names every signal that produced it; `a < b` and pairs are sorted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from rapidfuzz import fuzz

from factory.extraction.numbers import normalise_text

SYNONYM_RATIO = 0.90
SYNONYM_OVERLAP = 0.5
ACRONYM_MIN_WORDS = 2
BLOCK_MAX = 200
POSTING_MAX = 200
MIN_SHARED_TRIGRAMS = 2
ACRONYM_MIN_LENGTH = 2

_NON_WORD = re.compile(r"[^\w]+")


@dataclass(frozen=True)
class Item:
    """One thing that may be a synonym of another of the same `kind`: `names` are its normalised
    or raw names and aliases, `targets` the works (or members) it applies to."""

    kind: str
    id: str
    names: tuple[str, ...]
    targets: frozenset[str]


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    signals: tuple[str, ...]
    score: float


def _ratio(a: str, b: str) -> float:
    return float(fuzz.ratio(a, b)) / 100.0


def _norm(name: str) -> str:
    """Case-folded text with punctuation read as a space."""
    return " ".join(_NON_WORD.sub(" ", normalise_text(name)).split())


def _ordered(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _trigrams(norm: str) -> set[str]:
    if len(norm) < 3:
        return {norm}
    return {norm[i : i + 3] for i in range(len(norm) - 2)}


def string_pairs(items: Sequence[Item]) -> list[Pair]:
    """Pairs whose normalised names have a `fuzz.ratio` of at least `SYNONYM_RATIO`, found
    through blocks (see the module docstring)."""
    entries: list[tuple[int, str]] = []  # (item index, normalised name)
    for index, item in enumerate(items):
        for name in dict.fromkeys(_norm(n) for n in item.names):
            if name:
                entries.append((index, name))
    first: dict[str, list[int]] = defaultdict(list)
    grams: dict[str, list[int]] = defaultdict(list)
    for e, (_, name) in enumerate(entries):
        first[name.split(" ", 1)[0]].append(e)
        for gram in _trigrams(name):
            grams[gram].append(e)
    shared: dict[tuple[int, int], int] = defaultdict(int)
    for block in first.values():
        if 2 <= len(block) <= BLOCK_MAX:
            for x, y in combinations(block, 2):
                shared[(x, y)] += MIN_SHARED_TRIGRAMS
    for block in grams.values():
        if 2 <= len(block) <= BLOCK_MAX:
            for x, y in combinations(block, 2):
                shared[(x, y)] += 1
    best: dict[tuple[str, str], float] = {}
    for (x, y), count in sorted(shared.items()):
        if count < MIN_SHARED_TRIGRAMS:
            continue
        (ix, nx), (iy, ny) = entries[x], entries[y]
        if ix == iy:
            continue
        score = _ratio(nx, ny)
        if score >= SYNONYM_RATIO:
            key = _ordered(items[ix].id, items[iy].id)
            best[key] = max(best.get(key, 0.0), score)
    return [Pair(a, b, ("string",), s) for (a, b), s in sorted(best.items())]


def _initials(norm: str) -> str | None:
    words = norm.split()
    if len(words) < ACRONYM_MIN_WORDS:
        return None
    return "".join(w[0] for w in words)


def acronym_pairs(items: Sequence[Item]) -> list[Pair]:
    """Pairs where the initials of a multi-word name equal a one-word name of another item."""
    short: dict[str, set[str]] = defaultdict(set)
    for item in items:
        for name in item.names:
            norm = _norm(name)
            if " " not in norm and len(norm) >= ACRONYM_MIN_LENGTH:
                short[norm].add(item.id)
    found: set[tuple[str, str]] = set()
    for item in items:
        for name in item.names:
            initials = _initials(_norm(name))
            for other in short.get(initials or "", ()):
                if other != item.id:
                    found.add(_ordered(item.id, other))
    return [Pair(a, b, ("acronym",), 1.0) for a, b in sorted(found)]


def inverted_index(items: Iterable[Item]) -> dict[str, list[str]]:
    """Target -> the sorted ids of the items that have it."""
    index: dict[str, list[str]] = defaultdict(list)
    for item in items:
        for target in item.targets:
            index[target].append(item.id)
    return {t: sorted(ids) for t, ids in sorted(index.items())}


def overlap_pairs(items: Sequence[Item], postings: Mapping[str, Sequence[str]]) -> list[Pair]:
    """Pairs sharing at least one target whose Jaccard overlap is at least `SYNONYM_OVERLAP`.
    Only pairs that co-occur in a posting list are ever formed."""
    size = {item.id: len(item.targets) for item in items}
    common: dict[tuple[str, str], int] = defaultdict(int)
    for ids in postings.values():
        if 2 <= len(ids) <= POSTING_MAX:
            for x, y in combinations(sorted(set(ids)), 2):
                common[(x, y)] += 1
    out: list[Pair] = []
    for (a, b), count in sorted(common.items()):
        score = count / (size[a] + size[b] - count)
        if score >= SYNONYM_OVERLAP:
            out.append(Pair(a, b, ("overlap",), score))
    return out
