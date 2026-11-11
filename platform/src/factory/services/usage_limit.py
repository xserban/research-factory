"""Runs stopped by the CLI's usage limit (plan restart-and-costs, IDEA-59).

A headless `claude -p` session that hits the 5-hour limit prints a notice such as
`You've hit your 5-hour limit · resets 3pm (Europe/Bucharest)` and exits with status 0, so the
runner records it `complete`. This module is the one place that tells such a run from a finished
one. It is a pure read: it parses the run log (through `run_costs.parse_log`, which keeps the short
texts) and the folded run row, and writes nothing.

A complete run is limit-stopped when
- a text of its log matches `LIMIT_PATTERN` (reason `log`), or
- its result line says `is_error`, it closed no unit (`units` is 0, from the MCP counter, else
  counts before minus after) and the stage still has pending units (reason `no-units`; no reset
  time is known then). A complete run without the error flag that closed nothing is not a limit
  stop: it may have found nothing to do.

`reset_text` is the raw text after `resets` (`RESET_PATTERN`) and `reset_at` the stored timestamp
parsed from it by `parse_reset` (a clock time with an optional date and an optional `(Zone)`),
None when the text does not parse. The time is the next occurrence after the run finished.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from factory.clock import format_ts, parse_ts
from factory.model.base import StrictModel
from factory.services import run_costs
from factory.services.context import Project

LIMIT_PATTERN: Final = re.compile(
    r"you(?:'|\u2019)?ve\s+hit\s+your\b[^\n.\u00b7|]{0,40}?\blimit\b", re.IGNORECASE
)
"""The usage-limit notice, e.g. `You've hit your 5-hour limit` or `You've hit your weekly
limit`; the apostrophe may be typographic or absent."""

RESET_PATTERN: Final = re.compile(
    r"\bresets?\s+(?:at\s+)?(?P<when>[^\n]+?)\s*$", re.IGNORECASE | re.MULTILINE
)
"""The text after `resets` in the same message, to the end of the line."""

_CLOCK: Final = re.compile(
    r"(?:(?P<month>[A-Za-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)"
    r"(?:\s*\((?P<zone>[^)]+)\))?",
    re.IGNORECASE,
)
_MONTHS: Final = {
    m: i + 1
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}


class LimitStop(StrictModel):
    reason: Literal["log", "no-units"]
    reset_text: str | None = None
    """The raw text after `resets` in the log, None when absent."""
    reset_at: str | None = None
    """The reset time as a stored timestamp, None when unknown or unparsed."""


def parse_reset(raw: str, after: datetime) -> datetime | None:
    """The next occurrence after `after` of the clock time in `raw` (`3pm (Europe/Bucharest)`,
    `3:30pm`, `Nov 12, 3pm`), in UTC; None when `raw` is not of that form or names an unknown zone.
    Without a zone the machine's local zone is read."""
    match = _CLOCK.fullmatch(raw.strip())
    if match is None:
        return None
    hour, minute = int(match["hour"]), int(match["minute"] or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if match["ampm"].lower() == "pm" else 0)
    zone_name = match["zone"]
    try:
        zone = ZoneInfo(zone_name.strip()) if zone_name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None
    reference = after.astimezone(zone) if zone else after.astimezone()
    tz = reference.tzinfo
    try:
        if match["month"]:
            month = _MONTHS.get(match["month"].lower())
            if month is None:
                return None
            candidate = datetime(reference.year, month, int(match["day"]), hour, minute, tzinfo=tz)
            if candidate <= reference:
                candidate = candidate.replace(year=reference.year + 1)
        else:
            candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= reference:
                candidate += timedelta(days=1)
    except ValueError:
        return None
    return candidate.astimezone(UTC)


def detect(
    texts: list[str],
    *,
    units: int | None,
    stage_pending: bool,
    finished_at: datetime | None,
    result_error: bool = False,
) -> LimitStop | None:
    """The limit stop of a complete run, from the log `texts` and the units it closed (None when
    unknown), or None when it was not stopped by the limit. See the module docstring."""
    for message in texts:
        if LIMIT_PATTERN.search(message) is None:
            continue
        reset = RESET_PATTERN.search(message)
        raw = None if reset is None else reset["when"].strip()
        at = None
        if raw and finished_at is not None:
            parsed = parse_reset(raw, finished_at)
            at = None if parsed is None else format_ts(parsed)
        return LimitStop(reason="log", reset_text=raw, reset_at=at)
    if result_error and units == 0 and stage_pending:
        return LimitStop(reason="no-units")
    return None


def limit_stop(project: Project, run_id: str, *, stage_pending: bool) -> LimitStop | None:
    """The limit stop of the `complete` run `run_id`, None for any other run or outcome. Read-only
    (see the module docstring)."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT r.outcome, r.log_blob, r.counts_before, r.counts_after, fe.ts "
                "FROM runner_runs r LEFT JOIN events fe ON fe.id = r.finished_event_id "
                "WHERE r.run_id = :r"
            ),
            {"r": run_id},
        ).first()
    if row is None or row[0] != "complete":
        return None
    log_text, _ = run_costs._log_text(project, run_id, None if row[1] is None else str(row[1]))
    log = run_costs.parse_log(log_text.splitlines())
    served = run_costs._counter_served(project, run_id)
    if served is not None:
        units: int | None = served
    elif row[3] is None:
        units = None
    else:
        before = sum(json.loads(str(row[2])).values())
        units = max(before - sum(json.loads(str(row[3])).values()), 0)
    finished = None if row[4] is None else parse_ts(str(row[4]))
    return detect(
        log.texts,
        units=units,
        stage_pending=stage_pending,
        finished_at=finished,
        result_error=log.is_error,
    )


def hold_until(stop: LimitStop, now: datetime) -> str | None:
    """Why a resume must wait, or None when it may go ahead: the reset is in the future, or the
    log named a reset time that could not be parsed (its raw text is returned). A stop with no
    reset text (reason `no-units`) never holds."""
    if stop.reset_at is not None:
        return f"usage limit resets {stop.reset_at}" if stop.reset_at > format_ts(now) else None
    if stop.reset_text is not None:
        return f"usage limit, reset time unknown: resets {stop.reset_text}"
    return None


__all__ = [
    "LIMIT_PATTERN",
    "RESET_PATTERN",
    "LimitStop",
    "detect",
    "hold_until",
    "limit_stop",
    "parse_reset",
]
