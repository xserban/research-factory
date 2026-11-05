"""Candidate signals and clusters (slice 3d, plan Regions-C, task 2)."""

from __future__ import annotations

import random
import string

import pytest

from factory.consolidation import signals
from factory.consolidation.clusters import CLUSTER_MAX, clusters, merge_pairs
from factory.consolidation.signals import (
    Item,
    Pair,
    acronym_pairs,
    inverted_index,
    overlap_pairs,
    string_pairs,
)


def item(ident: str, *names: str, targets: tuple[str, ...] = ()) -> Item:
    return Item("label", ident, names, frozenset(targets))


def test_string_signal_case_and_punctuation() -> None:
    items = [
        item("a", "Linear Attention"),
        item("b", "linear-attention"),
        item("c", "kernel trick"),
    ]
    [pair] = string_pairs(items)
    assert (pair.a, pair.b, pair.signals) == ("a", "b", ("string",))
    assert pair.score >= signals.SYNONYM_RATIO


def test_acronym_signal() -> None:
    items = [item("a", "linear transformer attention"), item("b", "lta"), item("c", "ltb")]
    [pair] = acronym_pairs(items)
    assert (pair.a, pair.b, pair.signals) == ("a", "b", ("acronym",))


def test_overlap_signal_without_string_similarity() -> None:
    works = ("w1", "w2", "w3")
    items = [
        item("performer", "Performer", targets=works),
        item("favor", "FAVOR+", targets=works),
        item("other", "Reformer", targets=("w9",)),
    ]
    assert string_pairs(items) == []
    [pair] = overlap_pairs(items, inverted_index(items))
    assert (pair.a, pair.b, pair.signals) == ("favor", "performer", ("overlap",))
    assert pair.score == 1.0


def test_overlap_below_threshold_is_not_a_pair() -> None:
    items = [
        item("a", "alpha", targets=("w1", "w2", "w3")),
        item("b", "beta", targets=("w3", "w4", "w5", "w6")),
    ]
    assert overlap_pairs(items, inverted_index(items)) == []


def _counting(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]
    real = signals._ratio

    def counting(a: str, b: str) -> float:
        calls[0] += 1
        return real(a, b)

    monkeypatch.setattr(signals, "_ratio", counting)
    return calls


def test_no_all_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = random.Random(7)
    words = [
        "".join(rng.choices(string.ascii_lowercase, k=rng.randint(5, 9))) for _ in range(20_000)
    ]
    items = [item(f"i{n:05d}", f"{words[2 * n]} {words[2 * n + 1]}") for n in range(10_000)]
    calls = _counting(monkeypatch)
    string_pairs(items)
    assert calls[0] < 10_000 * 20  # far below the 50 million of an all-pairs scan


def test_oversized_blocks_are_skipped_not_scanned(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [item(f"i{n:04d}", f"item {n:04d}") for n in range(3000)]
    calls = _counting(monkeypatch)
    string_pairs(items)
    assert calls[0] < 3000 * signals.BLOCK_MAX


def test_pairs_name_their_signals() -> None:
    a = Pair("a", "b", ("string",), 0.95)
    b = Pair("a", "b", ("overlap",), 0.6)
    c = Pair("b", "c", ("acronym",), 1.0)
    merged = merge_pairs([c, b, a])
    assert [(p.a, p.b, p.signals, p.score) for p in merged] == [
        ("a", "b", ("overlap", "string"), 0.95),
        ("b", "c", ("acronym",), 1.0),
    ]


def test_clusters_deterministic_and_capped() -> None:
    ids = [f"n{n:02d}" for n in range(30)]
    pairs = [Pair(ids[n], ids[n + 1], ("string",), 0.9 + (n % 7) / 100) for n in range(29)]
    first = clusters(pairs)
    assert clusters(list(reversed(pairs))) == first
    assert all(2 <= len(c) <= CLUSTER_MAX for c in first)
    assert [c[0] for c in first] == sorted(c[0] for c in first)
    assert all(list(c) == sorted(c) for c in first)
    assert len({m for c in first for m in c}) == sum(len(c) for c in first)


def test_clusters_join_components() -> None:
    pairs = [Pair("a", "b", ("string",), 1.0), Pair("b", "c", ("overlap",), 0.6)]
    pairs.append(Pair("x", "y", ("acronym",), 1.0))
    assert clusters(pairs) == [("a", "b", "c"), ("x", "y")]
