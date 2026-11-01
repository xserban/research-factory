"""Pure screening statistics: agreement, calibration rates, audit sizing, draw and quote checks."""

import random

import pytest

from factory.model.project import RigorMode
from factory.services.screening_stats import (
    AUDIT_ERROR_CEILING,
    CALIBRATION_SENSITIVITY,
    audit_error_rates,
    audit_size,
    cohen_kappa,
    draw_audit,
    kappa_by_criterion,
    quote_in,
    sensitivity_specificity,
)


def test_kappa_textbook_value() -> None:
    pairs = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 10 + [(False, False)] * 15
    assert cohen_kappa(pairs) == pytest.approx(0.4)


def test_kappa_undefined_when_no_variation() -> None:
    assert cohen_kappa([(True, True)] * 5) is None
    assert cohen_kappa([]) is None


def test_kappa_by_criterion_scores_each_criterion() -> None:
    pairs: list[tuple[str | None, str | None]] = [
        ("EX01", "EX01"),
        ("EX01", "EX01"),
        ("EX02", None),
        (None, "EX02"),
        (None, None),
        (None, None),
    ]
    result = kappa_by_criterion(pairs, ["EX01", "EX02", "EX03"])
    assert result["EX01"] == pytest.approx(1.0)
    assert result["EX02"] == pytest.approx(-0.2)
    assert result["EX03"] is None


def test_audit_size_minimum_and_cap() -> None:
    assert audit_size(300, 0.02, 50) == 50
    assert audit_size(5000, 0.02, 50) == 100
    assert audit_size(30, 0.02, 50) == 30


def test_draw_audit_three_to_one_with_backfill() -> None:
    rng = random.Random(7)
    exc, inc = [f"e{i}" for i in range(100)], [f"i{i}" for i in range(100)]
    drawn = draw_audit(exc, inc, 40, rng)
    assert sum(d.startswith("e") for d in drawn) == 30
    assert len(draw_audit(exc[:5], inc, 40, random.Random(7))) == 40


def test_draw_audit_is_sorted_and_reproducible_from_seed() -> None:
    exc, inc = [f"e{i}" for i in range(50)], [f"i{i}" for i in range(50)]
    first = draw_audit(exc, inc, 20, random.Random(3))
    assert first == sorted(first)
    assert first == draw_audit(list(reversed(exc)), list(reversed(inc)), 20, random.Random(3))


def test_quote_whitespace_normalised_but_case_exact() -> None:
    assert quote_in(
        "linear  attention\nfor",
        "Linear attention for ViT",
        "We study linear attention for vision.",
    )
    assert not quote_in("Linear Attention", "x", "We study linear attention.")
    assert quote_in("ViT", "Linear attention for ViT", None)


def test_quote_empty_after_normalisation_never_matches() -> None:
    assert not quote_in("   \n ", "Title", "Abstract")


def test_sensitivity_specificity() -> None:
    pairs = [(True, True)] * 3 + [(True, False)] + [(False, False)] * 4
    rates = sensitivity_specificity(pairs)
    assert rates.sensitivity == pytest.approx(0.75)
    assert rates.specificity == pytest.approx(1.0)
    assert rates.n_positive == 4
    assert rates.n_negative == 4


def test_sensitivity_undefined_without_positives() -> None:
    rates = sensitivity_specificity([(False, False), (False, True)])
    assert rates.sensitivity is None
    assert rates.n_positive == 0
    assert rates.specificity == pytest.approx(0.5)


def test_audit_error_rates_weighted() -> None:
    exclusion_stratum = [(False, False)] * 29 + [(False, True)]
    inclusion_stratum = [(True, True)] * 10
    rates = audit_error_rates(exclusion_stratum + inclusion_stratum, 150, 50)
    assert rates.false_exclusion == pytest.approx(1 / 30)
    assert rates.false_inclusion == pytest.approx(0.0)
    assert rates.weighted == pytest.approx((150 * (1 / 30) + 50 * 0) / 200)
    assert rates.labelled == 40


def test_audit_error_rates_undefined_for_empty_stratum() -> None:
    rates = audit_error_rates([(True, True)], 10, 10)
    assert rates.false_exclusion is None
    assert rates.false_inclusion == pytest.approx(0.0)
    assert rates.weighted is None


def test_constants() -> None:
    assert AUDIT_ERROR_CEILING == 0.05
    assert CALIBRATION_SENSITIVITY == {
        RigorMode.EXPLORATORY: None,
        RigorMode.PILOT: 0.9,
        RigorMode.SYSTEMATIC: 0.95,
    }


def test_audit_weighted_ignores_empty_population_stratum() -> None:
    rates = audit_error_rates([(True, False)] * 4, 0, 20)
    assert rates.false_exclusion is None
    assert rates.weighted == pytest.approx(1.0)


def test_audit_weighted_undefined_without_population() -> None:
    assert audit_error_rates([(True, True)], 0, 0).weighted is None
