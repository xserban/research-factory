"""Paired statistics in decimals (slice 6, plan XP-B task 1, rulings 2 and 3)."""

from __future__ import annotations

from decimal import Decimal

from factory.hypotheses.stats import PairedSummary, oriented, paired_summary, plain


def D(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_paired_summary_hand_computed() -> None:
    s = paired_summary(D("0.8", "1.1", "0.5"), "0.95")
    # mean 0.8, sd 0.3, se 0.3 / sqrt(3), half width 4.3027 * se = 0.745250 (6 places, half-even)
    assert (s.n, s.mean, s.sd) == (3, Decimal("0.800000"), Decimal("0.300000"))
    assert s.se == Decimal("0.173205")
    assert s.ci_low == Decimal("0.054750") and s.ci_high == Decimal("1.545250")
    assert s.level == "0.95"


def test_n_one_has_no_ci() -> None:
    s = paired_summary(D("0.4"), "0.95")
    assert s == PairedSummary(1, Decimal("0.400000"), None, None, None, None, "0.95")


def test_identical_differences_have_a_degenerate_interval() -> None:
    s = paired_summary(D("2", "2", "2"), "0.99")
    assert (s.sd, s.ci_low, s.ci_high) == (Decimal(0), Decimal("2.000000"), Decimal("2.000000"))


def test_orientation_lower_is_better() -> None:
    assert oriented(Decimal("3"), Decimal("5"), "lower") == Decimal("2")
    assert oriented(Decimal("3"), Decimal("5"), "higher") == Decimal("-2")


def test_results_quantised_half_even() -> None:
    assert paired_summary(D("0.0000005", "0"), "0.90").mean == Decimal("0.000000")
    assert paired_summary(D("0.0000015", "0"), "0.90").mean == Decimal("0.000001")
    assert paired_summary(D("0.0000025"), "0.90").mean == Decimal("0.000002")


def test_plain_is_canonical() -> None:
    assert plain(Decimal("0.8000004")) == "0.8"
    assert plain(Decimal("-0.0000001")) == "0"
    assert plain(Decimal("12")) == "12"
