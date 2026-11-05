"""The embedded t table (slice 6, plan XP-B task 1, ruling 1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.hypotheses.tquantiles import Level, t_quantile


@pytest.mark.parametrize(
    ("level", "df", "expected"),
    [
        ("0.95", 1, "12.7062"),
        ("0.95", 2, "4.3027"),
        ("0.95", 4, "2.7764"),
        ("0.95", 30, "2.0423"),
        ("0.95", 60, "2.0003"),
        ("0.99", 10, "3.1693"),
        ("0.99", 5, "4.0321"),
        ("0.90", 3, "2.3534"),
        ("0.90", 20, "1.7247"),
        ("0.99", 120, "2.6174"),
    ],
)
def test_known_quantiles(level: Level, df: int, expected: str) -> None:
    assert t_quantile(level, df) == Decimal(expected)


def test_df_between_rows_uses_lower() -> None:
    # 61..79 use the df 60 row, 81..99 the df 80 row, more than 120 the df 120 row
    assert t_quantile("0.95", 70) == Decimal("2.0003")
    assert t_quantile("0.95", 99) == Decimal("1.9901")
    assert t_quantile("0.95", 5000) == Decimal("1.9799")


def test_df_below_one_is_refused() -> None:
    with pytest.raises(ValueError):
        t_quantile("0.95", 0)


def test_unknown_level_is_refused() -> None:
    with pytest.raises(ValueError):
        t_quantile("0.5", 3)  # type: ignore[arg-type]
