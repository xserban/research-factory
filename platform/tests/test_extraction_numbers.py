# ruff: noqa: RUF001
"""Tests for number tokens, canonical values, normalisers and citation markers."""

from decimal import Decimal

import pytest

from factory.extraction.citations import citation_markers
from factory.extraction.numbers import (
    canonical,
    normalise_for,
    normalise_resolution,
    normalise_text,
    numbers_in,
    parse_printed,
)
from factory.packs import ML_BENCHMARK_V1, UnitFamily


def test_decimal_equality_ignores_trailing_zero() -> None:
    assert parse_printed("82.40") == parse_printed(82.4) == Decimal("82.4")


def test_canonical_count_units() -> None:
    assert canonical(Decimal("22.1"), "M", UnitFamily.COUNT) == "22100000"
    assert (
        canonical(Decimal("4.6"), "B", UnitFamily.COUNT)
        == canonical(Decimal("4.6"), "G", UnitFamily.COUNT)
        == "4600000000"
    )
    assert canonical(Decimal("82.40"), "%", UnitFamily.SCORE) == "82.4"
    assert canonical(Decimal("0.824"), "fraction", UnitFamily.SCORE) == "0.824"


def test_canonical_plain_decimal_no_exponent() -> None:
    assert canonical(Decimal("5"), "T", UnitFamily.COUNT) == "5000000000000"
    assert canonical(Decimal("1E+2"), None, UnitFamily.OTHER) == "100"
    assert canonical(Decimal("-0.0"), None, UnitFamily.NONE) == "0"
    assert canonical(Decimal("3"), "", UnitFamily.COUNT) == "3"


def test_tokens_are_whole() -> None:
    assert [t.value for t in numbers_in("top-1 182.45 and 82.40%")] == [
        Decimal("182.45"),
        Decimal("82.40"),
    ]
    assert numbers_in("22.1M params")[0].suffix == "M"
    assert numbers_in("12 ms")[0].suffix is None
    assert numbers_in("1,234 imgs")[0].value == Decimal("1234")
    assert numbers_in("−3.5")[0].value == Decimal("-3.5")
    assert numbers_in("82.4%")[0].suffix == "%"
    assert numbers_in("1e-3")[0].value == Decimal("0.001")
    assert numbers_in("3Bytes")[0].suffix is None


def test_parse_printed_rejects_suffix_and_percent() -> None:
    assert parse_printed("82.4%") is None
    assert parse_printed("22M") is None
    assert parse_printed("abc") is None
    assert parse_printed(True) is None
    assert parse_printed(float("nan")) is None
    assert parse_printed(7) == Decimal(7)
    assert parse_printed(" 1,234 ") == Decimal(1234)


@pytest.mark.parametrize("raw", ["224", "224²", "224^2", "224x224", "224 × 224"])
def test_resolution_normaliser(raw: str) -> None:
    assert normalise_resolution(raw) == "224x224"


def test_resolution_rectangular_and_other_text_unchanged() -> None:
    assert normalise_resolution("384X256") == "384x256"
    assert normalise_resolution("Native") == "native"


def test_normalise_text_and_for() -> None:
    assert normalise_text("  \uff24eiT \n Small ") == "deit small"
    res = ML_BENCHMARK_V1.field("input_resolution")
    assert res is not None
    assert normalise_for(res, "224²") == "224x224"
    name = ML_BENCHMARK_V1.field("method_name")
    assert name is not None
    assert normalise_for(name, "DeiT-S") == "deit-s"


def test_citation_markers() -> None:
    p = ML_BENCHMARK_V1.citation_patterns
    assert citation_markers("DeiT-S [41]", p) == ["[41]"]
    assert citation_markers("PVT [12, 14]", p) == ["[12, 14]"]
    assert citation_markers("x [3-5]", p) == ["[3-5]"]
    assert citation_markers("Swin (Liu et al., 2021)", p)
    assert citation_markers("Wang et al., 2021", p)
    assert citation_markers("Ours [ours]", p) == []
    assert citation_markers("ViT-B/16", p) == []
    assert citation_markers(r"see \cite{wang21}", p) == [r"\cite{wang21}"]
    assert citation_markers("A [1] B [2]", p) == ["[1]", "[2]"]
