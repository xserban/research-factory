"""Vocabulary suggestions: the term blocks a query is missing, computed from missed seeds.

Ported from the old project's probe module. The rule is deterministic and explainable: a phrase
that several positive seeds share, and that the query does not cover, is the missing block.
"""

from __future__ import annotations

import re
from collections import Counter

from factory.model.probe import TermSuggestion
from factory.model.work import Work
from factory.model.work_ids import normalize_title

# Words that cannot discriminate between papers in any technical field.
_NOISE = frozenset(
    {
        "a",
        "also",
        "an",
        "and",
        "approach",
        "approaches",
        "are",
        "art",
        "as",
        "at",
        "based",
        "be",
        "been",
        "both",
        "by",
        "can",
        "could",
        "each",
        "first",
        "for",
        "from",
        "furthermore",
        "high",
        "however",
        "in",
        "is",
        "it",
        "its",
        "large",
        "low",
        "may",
        "method",
        "methods",
        "might",
        "model",
        "models",
        "more",
        "moreover",
        "most",
        "new",
        "novel",
        "of",
        "on",
        "one",
        "or",
        "other",
        "others",
        "our",
        "paper",
        "performance",
        "present",
        "presents",
        "propose",
        "proposed",
        "result",
        "results",
        "second",
        "should",
        "show",
        "shown",
        "shows",
        "small",
        "state",
        "study",
        "such",
        "than",
        "that",
        "the",
        "their",
        "then",
        "therefore",
        "these",
        "they",
        "this",
        "those",
        "three",
        "to",
        "two",
        "use",
        "used",
        "uses",
        "using",
        "via",
        "we",
        "which",
        "while",
        "will",
        "with",
        "work",
        "would",
    }
)


def _ngrams(text: str, max_n: int = 3) -> set[str]:
    tokens = [t for t in normalize_title(text).split() if t not in _NOISE and len(t) > 2]
    grams: set[str] = set()
    for n in range(1, max_n + 1):
        grams.update(" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
    return grams


def _query_terms(query: str) -> set[str]:
    """Terms the query already covers, normalised the same way candidate terms are."""
    stripped = re.sub(r"\b(all|ti|abs|au|cat)\s*:", " ", query)
    stripped = re.sub(r"\b(AND|OR|ANDNOT|NOT)\b", " ", stripped)
    quoted = re.findall(r'"([^"]+)"', stripped)
    bare = re.sub(r'"[^"]*"', " ", stripped)
    return {normalize_title(t) for t in [*quoted, *bare.split()] if t.strip()}


def suggest_terms(
    missed: list[Work], all_seeds: list[Work], query: str, top: int = 8
) -> list[TermSuggestion]:
    """Propose the term blocks a query is missing.

    The rule is simple and explainable: **a phrase that several positive seeds share, and that
    the query does not cover, is the missing block.** Ranking by how many seeds share a term —
    rather than by raw frequency — is what keeps field-wide words like "language model" out of
    the suggestions, since those appear in the query already or in everything equally.
    """
    if not missed:
        return []

    covered = _query_terms(query)
    missed_terms = [_ngrams(f"{w.title} {w.abstract or ''}") for w in missed]
    candidates = Counter[str]()
    for grams in missed_terms:
        candidates.update(grams)

    # A term is only interesting if it is absent from the query and shared beyond one paper.
    seed_grams = {w.id: _ngrams(f"{w.title} {w.abstract or ''}") for w in all_seeds}
    scored: list[TermSuggestion] = []
    for term, _ in candidates.items():
        if term in covered or any(term in c or c in term for c in covered if c):
            continue
        holders = tuple(w.id for w in all_seeds if term in seed_grams[w.id])
        if len(holders) < 2:  # a term unique to one paper is a coincidence, not a block
            continue
        scored.append(TermSuggestion(term=term, seeds=len(holders), holders=holders))

    scored.sort(key=lambda row: (-row.seeds, -len(row.term)))
    # Drop terms fully contained in a better-scoring one: keep the most specific phrasing.
    kept: list[TermSuggestion] = []
    for row in scored:
        if any(
            row.term in other.term and row.term != other.term
            for other in kept
            if other.seeds >= row.seeds
        ):
            continue
        kept.append(row)
    return kept[:top]
