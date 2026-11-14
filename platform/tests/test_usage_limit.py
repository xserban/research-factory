"""Usage-limit detection (plan restart-and-costs, IDEA-59): the notice patterns, the reset parser
and the log reader together."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from factory.services import run_costs
from factory.services.usage_limit import (
    LIMIT_PATTERN,
    RESET_PATTERN,
    detect,
    parse_reset,
    read_log,
)

SAMPLE = "You've hit your 5-hour limit · resets 1pm (Europe/Bucharest)"
"""The researcher's sample of the limit line, as they quoted it in a message. It was NOT captured
from a real run log (no limit stop was found in the pilot's logs), so the wording is unverified."""

# 10:00 UTC is 12:00 in Bucharest (UTC+2 in November).
END = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


def test_rule_one_matches_the_sample_and_extracts_the_reset() -> None:
    assert LIMIT_PATTERN.search(SAMPLE) is not None
    reset = RESET_PATTERN.search(SAMPLE)
    assert reset is not None and reset["when"] == "1pm (Europe/Bucharest)"
    assert parse_reset(reset["when"], END) == datetime(2026, 11, 11, 11, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3:30pm (Europe/Bucharest)", datetime(2026, 11, 11, 13, 30, tzinfo=UTC)),
        ("Nov 12, 3pm (UTC)", datetime(2026, 11, 12, 15, 0, tzinfo=UTC)),
        ("Nov 12, 3pm (Europe/Bucharest)", datetime(2026, 11, 12, 13, 0, tzinfo=UTC)),
    ],
)
def test_the_reset_variants_parse(raw: str, expected: datetime) -> None:
    assert parse_reset(raw, END) == expected


def test_a_reset_without_a_zone_parses_in_the_local_zone() -> None:
    parsed = parse_reset("3pm", END)
    assert parsed is not None and parsed > END
    assert parsed.astimezone().hour == 15


def test_a_normal_run_text_does_not_match() -> None:
    for text in (
        "Screened 3 records; the limit of the method is small samples.",
        "I hit the rate of 5 per hour and went on. It resets nothing.",
        "Done. 2 units closed.",
    ):
        assert LIMIT_PATTERN.search(text) is None
        assert detect([text], units=2, stage_pending=True, finished_at=END) is None


def _assistant(text: str) -> str:
    return json.dumps(
        {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": text}]}}
    )


def _utc(stamp: str | None) -> datetime:
    """The reset stamp as an aware datetime (the code writes milliseconds and `Z`)."""
    assert stamp is not None
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _result(text: str, *, is_error: bool) -> str:
    return json.dumps({"type": "result", "is_error": is_error, "result": text})


def test_the_line_in_a_result_record_goes_through_the_log_reader() -> None:
    log = run_costs.parse_log([_result(SAMPLE, is_error=True)])
    assert log.is_error is True and SAMPLE in log.texts
    stop = detect(
        log.texts, units=0, stage_pending=True, finished_at=END, result_error=log.is_error
    )
    assert stop is not None and stop.reason == "log"
    assert stop.reset_text == "1pm (Europe/Bucharest)"
    assert _utc(stop.reset_at) == END.replace(hour=11) and stop.reset_estimated is False


def test_the_line_as_assistant_text_goes_through_the_log_reader() -> None:
    log = run_costs.parse_log([_assistant(SAMPLE), _result("", is_error=False)])
    stop = detect(log.texts, units=1, stage_pending=True, finished_at=END)
    assert stop is not None and stop.reason == "log"
    assert stop.reset_text == "1pm (Europe/Bucharest)"
    assert _utc(stop.reset_at) == END.replace(hour=11)


def test_a_normal_log_is_not_a_limit_stop() -> None:
    log = run_costs.parse_log([_assistant("Screened 2 records."), _result("done", is_error=False)])
    assert detect(log.texts, units=2, stage_pending=True, finished_at=END) is None


@pytest.mark.parametrize(
    ("notice", "reset_text"),
    [
        (
            "You've hit your 5-hour limit \u00b7 resets 1pm (Europe/Bucharest)",
            "1pm (Europe/Bucharest)",
        ),
        (
            "You've hit your 5-hour limit \u00b7 resets 6:10pm (Europe/Bucharest)",
            "6:10pm (Europe/Bucharest)",
        ),
    ],
)
def test_a_plain_text_log_from_live_py_is_a_limit_stop(notice: str, reset_text: str) -> None:
    """Excerpt of a real pilot log (plain text written by live.py, not stream-json): the notice
    line, then the `exit 0` line. Neither line is marked as an error."""
    texts, is_error = read_log([notice, "exit 0"])
    assert is_error is False
    stop = detect(texts, units=0, stage_pending=True, finished_at=END, result_error=is_error)
    assert stop is not None and stop.reason == "log"
    assert stop.reset_text == reset_text
    assert stop.reset_estimated is False


def test_a_plain_text_normal_log_is_not_a_limit_stop() -> None:
    texts, is_error = read_log(
        ["Row accepted: 1 written, 0 rejected, work finished.", "exit 0 seconds 51"]
    )
    assert (
        detect(texts, units=0, stage_pending=True, finished_at=END, result_error=is_error) is None
    )
