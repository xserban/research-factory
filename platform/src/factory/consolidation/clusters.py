"""Clusters of candidate pairs (slice 3d ruling 3 of plan Regions-C).

Invariants:
- Deterministic: the result does not depend on the order of the pairs.
- A cluster has 2 to `CLUSTER_MAX` members. Components larger than the cap are split by joining
  the highest-scoring edges first (ties by member ids) and never past the cap; members left
  alone are not clustered.
- Members are sorted inside a cluster and clusters by their smallest member.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from factory.consolidation.signals import Pair

CLUSTER_MAX = 12


def merge_pairs(pairs: Sequence[Pair]) -> list[Pair]:
    """One pair per `(a, b)`: the union of the signals (sorted) and the greatest score."""
    signals: dict[tuple[str, str], set[str]] = defaultdict(set)
    score: dict[tuple[str, str], float] = {}
    for p in pairs:
        key = (p.a, p.b)
        signals[key].update(p.signals)
        score[key] = max(score.get(key, 0.0), p.score)
    return [Pair(a, b, tuple(sorted(signals[(a, b)])), score[(a, b)]) for a, b in sorted(signals)]


def clusters(pairs: Sequence[Pair]) -> list[tuple[str, ...]]:
    parent: dict[str, str] = {}
    size: dict[str, int] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        size.setdefault(x, 1)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in sorted(merge_pairs(pairs), key=lambda q: (-q.score, q.a, q.b)):
        ra, rb = find(p.a), find(p.b)
        if ra != rb and size[ra] + size[rb] <= CLUSTER_MAX:
            if ra > rb:
                ra, rb = rb, ra
            parent[rb] = ra
            size[ra] += size[rb]
    groups: dict[str, list[str]] = defaultdict(list)
    for member in sorted(parent):
        groups[find(member)].append(member)
    found = [tuple(sorted(g)) for g in groups.values() if len(g) >= 2]
    return sorted(found, key=lambda g: g[0])
