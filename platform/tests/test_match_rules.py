"""Pure match rules, ordering and key (slice 6, plan H-B, task 1)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from factory.hypotheses.match import MATCH_BUILDER_VERSION, match_key, order_key, rule_outcome
from factory.model.cards import PropertyDef


def _d(kind: str, match: str, **over: Any) -> PropertyDef:
    base: dict[str, Any] = {
        "key": "pr:x-prop",
        "kind": kind,
        "match": match,
        "applies_to": "both",
    }
    if kind in ("enum", "set"):
        base["allowed"] = ["a", "b", "c"]
    if kind == "number":
        base["unit_family"] = "count"
    base.update(over)
    return PropertyDef.model_validate(base)


@pytest.mark.parametrize(
    ("defn", "problem", "method", "expected"),
    [
        (_d("enum", "equal"), ("a",), ("a",), "satisfied"),
        (_d("enum", "equal"), ("a",), ("b",), "conflicting"),
        (_d("enum", "equal"), ("a",), None, "unknown"),
        (_d("bool", "equal"), True, True, "satisfied"),
        (_d("bool", "equal"), True, False, "conflicting"),
        (_d("bool", "equal"), True, None, "unknown"),
        (_d("set", "covers"), ("a", "b"), ("a", "b", "c"), "satisfied"),
        (_d("set", "covers"), ("a", "b"), ("a", "c"), "conflicting"),
        (_d("set", "covers"), ("a",), None, "unknown"),
        (_d("number", "at-most"), Decimal(10), Decimal(10), "satisfied"),
        (_d("number", "at-most"), Decimal(10), Decimal(11), "conflicting"),
        (_d("number", "at-most"), Decimal(10), None, "unknown"),
        (_d("number", "at-least"), Decimal(10), Decimal(10), "satisfied"),
        (_d("number", "at-least"), Decimal(10), Decimal(9), "conflicting"),
        (_d("number", "at-least"), Decimal(10), None, "unknown"),
    ],
)
def test_rule_outcome(defn: PropertyDef, problem: Any, method: Any, expected: str) -> None:
    assert rule_outcome(defn, problem, method) == expected


def test_at_most_uses_canonical_decimals() -> None:
    defn = _d("number", "at-most")
    assert rule_outcome(defn, Decimal("1e9"), Decimal("1000000000")) == "satisfied"
    assert rule_outcome(defn, Decimal("1000000000"), Decimal("1.0E+9")) == "satisfied"
    assert rule_outcome(defn, Decimal("1e9"), Decimal("1000000001")) == "conflicting"


def test_order_is_lexicographic_without_weights() -> None:
    keys = {
        "ok": order_key(0, 3, 0, "mcd_a"),
        "unk": order_key(0, 3, 1, "mcd_b"),
        "few": order_key(0, 2, 0, "mcd_c"),
        "bad": order_key(1, 9, 0, "mcd_d"),
        "tie": order_key(0, 3, 0, "mcd_0"),
    }
    assert sorted(keys, key=lambda k: keys[k]) == ["tie", "ok", "unk", "few", "bad"]


def test_match_key_independent_of_input_order() -> None:
    a = ("mcd_1", ["pas_2", "pas_1"])
    b = ("mcd_2", ["pas_3"])
    k1 = match_key(("pbd_1", ["pas_9"]), [a, b], "V@00000001")
    other = [("mcd_2", ["pas_3"]), ("mcd_1", ["pas_1", "pas_2"])]
    assert k1 == match_key(("pbd_1", ["pas_9"]), other, "V@00000001")
    assert len(k1) == 16
    assert MATCH_BUILDER_VERSION == "1"


def test_match_key_changes_with_assertion_ids_and_vocab() -> None:
    base = match_key(("pbd_1", ["pas_9"]), [("mcd_1", ["pas_1"])], "V@00000001")
    assert base != match_key(("pbd_1", ["pas_9"]), [("mcd_1", ["pas_2"])], "V@00000001")
    assert base != match_key(("pbd_1", ["pas_8"]), [("mcd_1", ["pas_1"])], "V@00000001")
    assert base != match_key(("pbd_1", ["pas_9"]), [("mcd_1", ["pas_1"])], "V@00000002")
