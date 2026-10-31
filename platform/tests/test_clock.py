from datetime import datetime, timedelta

import pytest

from factory.clock import FixedClock, SystemClock


def test_fixed_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))


def test_system_clock_is_utc() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)
