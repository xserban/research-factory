"""Match rules between a problem description and a method card (slice 6, plan H-B). Pure.

Invariants:
- A rule compares one problem value with one method value and yields `satisfied`, `conflicting`
  or `unknown`. `unknown` means the method asserts nothing on the property; a present value that
  fails the rule is `conflicting`. No weights and no scores exist (decision 68).
- `equal` compares values as given (enum, bool, or equal sets); `covers`: the method's set
  contains the problem's set; `at-most`: method number <= problem number; `at-least`: >=.
  Numbers are compared as decimals, so `1e9` equals `1000000000`.
- `order_key` orders cards lexicographically: fewest conflicting, most satisfied, fewest unknown,
  card id.
- `match_key` is a content hash of the assertion ids that took part and `V@`; it does not depend
  on the order in which inputs are supplied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.model.cards import MatchRule, PropertyDef

Outcome = Literal["satisfied", "conflicting", "unknown"]
Value = tuple[str, ...] | Decimal | bool
MATCH_BUILDER_VERSION = "1"
KEY_LENGTH = 16


def rule_outcome(defn: PropertyDef, problem_value: Value, method_value: Value | None) -> Outcome:
    """Apply the property's match rule; see the module docstring."""
    if method_value is None:
        return "unknown"
    rule = defn.match
    if rule is MatchRule.EQUAL:
        ok = _same(problem_value, method_value)
    elif rule is MatchRule.COVERS:
        if not isinstance(problem_value, tuple) or not isinstance(method_value, tuple):
            raise ValueError("`covers` compares sets")
        ok = set(problem_value) <= set(method_value)
    else:
        if not isinstance(problem_value, Decimal) or not isinstance(method_value, Decimal):
            raise ValueError("`at-most` and `at-least` compare numbers")
        ok = (
            method_value <= problem_value
            if rule is MatchRule.AT_MOST
            else method_value >= problem_value
        )
    return "satisfied" if ok else "conflicting"


def _same(a: Value, b: Value) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        return sorted(a) == sorted(b)
    return a == b


def order_key(
    conflicting: int, satisfied: int, unknown: int, card_id: str
) -> tuple[int, int, int, str]:
    """Sort key of a candidate: `(conflicting, -satisfied, unknown, card_id)`."""
    return (conflicting, -satisfied, unknown, card_id)


def match_key(
    problem: tuple[str, Sequence[str]],
    cards: Sequence[tuple[str, Sequence[str]]],
    vocab: str,
) -> str:
    """First 16 hex digits of sha256 over the problem card and its effective assertion ids, the
    candidate cards and theirs (each sorted), `V@` and the builder version."""
    problem_part: list[JsonValue] = [problem[0], list(sorted(problem[1]))]
    card_parts: list[JsonValue] = [[cid, list(sorted(ids))] for cid, ids in sorted(cards)]
    body: JsonValue = {
        "builder": MATCH_BUILDER_VERSION,
        "vocabulary": vocab,
        "problem": problem_part,
        "cards": card_parts,
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()[:KEY_LENGTH]


def row_key(key: str, card_id: str) -> str:
    """Per-row key: first 16 hex digits of sha256 over the query's `match_key` and the card id."""
    return hashlib.sha256(f"{key}:{card_id}".encode()).hexdigest()[:KEY_LENGTH]
