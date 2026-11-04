# ruff: noqa: RUF001
"""Tests for number tokens, canonical values, normalisers and citation markers."""

import time
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


def _vals(text: str) -> list[Decimal]:
    return [t.value for t in numbers_in(text)]


@pytest.mark.parametrize(
    "text",
    ["1,2345", "82.4.1", "1.2.3", "Table 2.82.4", "82.4_1", "12,34", "82,4", "1,23,456"],
)
def test_no_false_prefix_tokens(text: str) -> None:
    assert numbers_in(text) == []


def test_boundary_kept_cases() -> None:
    assert _vals("182.45 82.41") == [Decimal("182.45"), Decimal("82.41")]
    assert _vals("x -82.4") == [Decimal("-82.4")]
    assert _vals("80-82") == [Decimal(80), Decimal(82)]
    assert _vals("82.4±0.3") == [Decimal("82.4"), Decimal("0.3")]
    assert _vals("in 2020, 5 models.") == [Decimal(2020), Decimal(5)]


def test_canonical_is_exact() -> None:
    a = canonical(Decimal("12345678901234567890123456789012"), None, UnitFamily.OTHER)
    b = canonical(Decimal("12345678901234567890123456789013"), None, UnitFamily.OTHER)
    assert a != b
    assert a == "12345678901234567890123456789012"
    assert canonical(Decimal("1E+999"), None, UnitFamily.OTHER) == "1" + "0" * 999


def test_exponent_out_of_range() -> None:
    assert numbers_in("1e999999999") == []
    assert parse_printed("1e999999999") is None
    assert parse_printed("1e300") == Decimal("1e300")


@pytest.mark.parametrize(
    ("unit", "family"),
    [("k", UnitFamily.COUNT), ("x", UnitFamily.COUNT), ("M", UnitFamily.SCORE)],
)
def test_canonical_rejects_foreign_unit(unit: str, family: UnitFamily) -> None:
    with pytest.raises(ValueError):
        canonical(Decimal(1), unit, family)


def test_suffix_with_space_and_unit_words() -> None:
    assert [(t.value, t.suffix) for t in numbers_in("82.4 %")] == [(Decimal("82.4"), "%")]
    assert numbers_in("3.5 B")[0].suffix == "B"
    assert numbers_in("22.1 M")[0].suffix == "M"
    assert numbers_in("22 Models")[0].suffix is None
    assert numbers_in("22 M1")[0].suffix is None
    assert numbers_in("4.6 GFLOPs")[0].suffix == "G"
    assert numbers_in("4.6GMACs")[0].suffix == "G"
    assert numbers_in("86 MB")[0].suffix == "M"
    assert numbers_in("86MB")[0].suffix == "M"
    assert numbers_in("22 m")[0].suffix is None
    assert numbers_in("22 k")[0].suffix is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5×10^3", Decimal(1500)),
        ("1.5 x 10^3", Decimal(1500)),
        (r"1.5\times 10^{3}", Decimal(1500)),
        ("1.5×10^{-3}", Decimal("0.0015")),
        ("-2×10^−2", Decimal("-0.02")),
    ],
)
def test_times_ten_power_is_one_number(text: str, expected: Decimal) -> None:
    assert _vals(text) == [expected]


def test_power_exponent_known_limitation() -> None:
    assert _vals("2^8") == [Decimal(2)]  # base only; exponent is not a token
    assert _vals("10^{-3}") == [Decimal(10)]


@pytest.mark.parametrize("text", ["٣", "１２", "٣.٤"])
def test_ascii_digits_only(text: str) -> None:
    assert numbers_in(text) == []
    assert parse_printed(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(Wang, Li, and Zhu, 2021)", ["(Wang, Li, and Zhu, 2021)"]),
        ("(van der Maaten, 2008)", ["(van der Maaten, 2008)"]),
        ("(de Vries et al., 2020)", ["(de Vries et al., 2020)"]),
        ("(Wang et al., 2021; Li et al., 2020)", ["Wang et al., 2021", "Li et al., 2020"]),
        ("[41; 42]", ["[41; 42]"]),
        ("[ 41 ]", ["[ 41 ]"]),
        (r"\cite[p.2]{x}", [r"\cite[p.2]{x}"]),
        ("(Müller, 2019)", ["(Müller, 2019)"]),
        ("(Čech et al., 2020)", ["(Čech et al., 2020)"]),
        ("Wang et al. (2021)", ["Wang et al. (2021)"]),
    ],
)
def test_citation_coverage(text: str, expected: list[str]) -> None:
    assert citation_markers(text, ML_BENCHMARK_V1.citation_patterns) == expected


def test_citation_accepted_false_positives() -> None:
    p = ML_BENCHMARK_V1.citation_patterns
    assert citation_markers("[0, 1]", p) == ["[0, 1]"]
    assert citation_markers("[2021]", p) == ["[2021]"]
    assert citation_markers("(June 2021)", p) == ["(June 2021)"]


@pytest.mark.parametrize(
    ("unit", "reps"),
    [("A, ", 20000), ("Smith, ", 5000), ("Smith and ", 5000), ("Smith, Li, and ", 3000)],
)
def test_citation_markers_linear_on_capitalised_chains(unit: str, reps: int) -> None:
    text = unit * reps + "x"
    t0 = time.perf_counter()
    citation_markers(text, ML_BENCHMARK_V1.citation_patterns)
    assert time.perf_counter() - t0 < 0.5
