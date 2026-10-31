from datetime import UTC, datetime, timedelta
from typing import Protocol


def format_ts(value: datetime) -> str:
    """The one stored timestamp form: `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC, milliseconds).

    Fixed width, so lexical order equals chronological order.
    """
    utc = value.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, start: datetime) -> None:
        if start.utcoffset() is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta
