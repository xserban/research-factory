"""Pure value checks of card assertions (slice 6, plan H-A, task 3)."""

from __future__ import annotations

from typing import Any

import pytest

from factory.extraction.numbers import canonical, parse_printed
from factory.hypotheses.values import ValueVerdict, check_value, value_in_quote
from factory.packs import UnitFamily
from tests.card_helpers import prop


def _num(**over: Any) -> Any:
    base = {
        "kind": "number",
        "allowed": [],
        "unit_family": "count",
        "match": "at-most",
        "value_aliases": {},
        "aliases": ["parameters", "params"],
    }
    base.update(over)
    return prop("pr:params", **base)


def _set() -> Any:
    return prop(
        "pr:tags",
        kind="set",
        allowed=["a", "b", "c"],
        match="covers",
        value_aliases={"c": ["see"]},
    )


def _bool() -> Any:
    return prop(
        "pr:dense-prediction",
        kind="bool",
        allowed=[],
        match="equal",
        value_aliases={},
        aliases=["dense prediction"],
    )


@pytest.mark.parametrize(
    ("defn", "value", "unit", "ok", "reason"),
    [
        (prop(), "irregular", None, True, None),
        (prop(), "gridded", None, False, "value-not-allowed"),
        (prop(), ["irregular"], None, False, "value-not-allowed"),
        (_set(), ["a", "c"], None, True, None),
        (_set(), [], None, False, "empty-set"),
        (_set(), ["a", "z"], None, False, "value-not-allowed"),
        (_set(), "a", None, False, "value-not-allowed"),
        (_bool(), True, None, True, None),
        (_bool(), False, None, True, None),
        (_bool(), "yes", None, False, "value-not-allowed"),
        (_num(), "1.2", "B", True, None),
        (_num(), "12", None, True, None),
        (_num(), "1.2", "GB", False, "unit-invalid"),
        (_num(), "many", "M", False, "not-a-number"),
        (_num(), True, "M", False, "not-a-number"),
        (_num(unit_family="none"), "3", "M", False, "unit-invalid"),
        (_num(unit_family="none"), "3", None, True, None),
    ],
)
def test_check_value(defn: Any, value: Any, unit: Any, ok: bool, reason: Any) -> None:
    verdict = check_value(defn, value, unit)
    assert (verdict.ok, verdict.reason) == (ok, reason)
    assert (verdict.canonical is not None) == (ok and defn.kind.value == "number")


def test_set_is_sorted_and_deduplicated() -> None:
    verdict = check_value(_set(), ["c", "a", "c"], None)
    assert verdict == ValueVerdict(ok=True, reason=None, canonical=None, value_norm=("a", "c"))


def test_value_norm_of_each_kind() -> None:
    assert check_value(prop(), "regular", None).value_norm == ("regular",)
    assert check_value(_bool(), False, None).value_norm == ("false",)
    assert check_value(_num(), "1.2", "B").value_norm == ("1200000000",)


def test_number_canonical_matches_plan_d() -> None:
    printed = parse_printed("1.2")
    assert printed is not None
    verdict = check_value(_num(), "1.2", "B")
    assert verdict.canonical == canonical(printed, "B", UnitFamily.COUNT)


def test_enum_alias_in_quote() -> None:
    assert value_in_quote(prop(), "irregular", "The points are Irregularly   sampled in time.")
    # a bare token must be a whole word: "irregular" is not found inside "irregularly"
    assert not value_in_quote(prop(), "irregular", "The points are irregularly spaced.")
    assert value_in_quote(prop(), "regular", "A regular grid is assumed.")
    # "regular" is not found inside "irregular" either
    assert not value_in_quote(prop(), "regular", "Observations are irregular.")


def test_set_needs_every_member_in_quote() -> None:
    assert value_in_quote(_set(), ["a", "c"], "We use a and see the rest")
    assert not value_in_quote(_set(), ["a", "b"], "We use a only")


def test_bool_false_never_in_quote() -> None:
    assert value_in_quote(_bool(), True, "It targets Dense Prediction tasks.")
    assert not value_in_quote(_bool(), True, "It targets segmentation.")
    assert not value_in_quote(_bool(), False, "It does not target dense prediction.")


def test_number_in_quote_uses_tokenizer() -> None:
    defn = _num()
    assert value_in_quote(defn, "1.2", "The model has 1.2B parameters.", unit="B")
    assert not value_in_quote(defn, "1.2", "The model has 1,200M parameters.", unit="B")
    assert not value_in_quote(
        defn, "1.2", "The model has 11.25B parameters.", unit="B"
    )  # whole tokens
    assert value_in_quote(defn, "12", "It has 12 layers.")
    assert not value_in_quote(
        defn, "1.2", "The model has 1.2B parameters.", unit="M"
    )  # suffix differs
