"""Ephemeral progress of long operations (slice 8, IDEA-44).

Invariants:
- Progress is never an event and never enters the index. One small JSON file per operation lives
  in `<project>/.progress/<op_id>.json` (git-ignored); deleting the directory loses nothing.
- Writing never takes the project write lock and never breaks the operation: every failure of the
  reporter is swallowed. Each write is atomic (temp file, then rename), so a reader sees either the
  previous or the new content.
- `update` writes at most once per `THROTTLE_SECONDS`; the first update, `finish` and `fail`
  always write.
- Rate and ETA are computed by the reader from `started_at`, `updated_at`, `done` and `total`;
  the writer stores only facts. Readers prune finished entries after `FINISHED_KEEP_SECONDS` and
  abandoned ones (a crashed process) after `ABANDONED_SECONDS`.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal

from pydantic import JsonValue

from factory.services.context import Project

PROGRESS_DIR = ".progress"
THROTTLE_SECONDS = 1.0
FINISHED_KEEP_SECONDS = 600.0
STALE_SECONDS = 600.0
ABANDONED_SECONDS = 3600.0

Kind = Literal["ranking", "search", "snowball", "probe", "dedup"]
Callback = Callable[[int, int | None], None]
"""`(done, total)`; `total` None leaves the known total unchanged."""


def _stamp(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="milliseconds")


def _parse(value: object) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


class Reporter:
    """Publishes the progress of one operation. Use as a context manager: leaving it normally
    finishes a still-running entry, leaving it by an exception marks it failed and re-raises."""

    def __init__(
        self,
        directory: Path,
        kind: Kind,
        label: str,
        *,
        unit: str,
        total: int | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.op_id = "op_" + secrets.token_hex(5)
        self._dir = directory
        self._clock = clock
        self._mono = monotonic
        self._data: dict[str, JsonValue] = {
            "op_id": self.op_id,
            "kind": kind,
            "label": label,
            "done": 0,
            "total": total,
            "unit": unit,
            "started_at": _stamp(clock()),
            "updated_at": _stamp(clock()),
            "state": "running",
            "message": None,
        }
        self._last_write: float | None = None
        self._write()

    def __enter__(self) -> Reporter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is not None:
            self.fail(f"{type(exc).__name__}: {exc}")
        elif self._data["state"] == "running":
            self.finish()

    def update(self, done: int, total: int | None = None, message: str | None = None) -> None:
        """Record `done` (and a newly known `total` or `message`); written at most once per
        second."""
        self._data["done"] = done
        if total is not None:
            self._data["total"] = total
        if message is not None:
            self._data["message"] = message
        now = self._mono()
        if self._last_write is None or now - self._last_write >= THROTTLE_SECONDS:
            self._write()

    def finish(self, message: str | None = None) -> None:
        self._end("finished", message)

    def fail(self, message: str) -> None:
        self._end("failed", message[:300])

    def _end(self, state: str, message: str | None) -> None:
        self._data["state"] = state
        self._data["message"] = message
        if state == "finished" and self._data["total"] is not None:
            self._data["done"] = max(_int(self._data["done"]), _int(self._data["total"]))
        self._write()

    def _write(self) -> None:
        try:
            self._data["updated_at"] = _stamp(self._clock())
            self._dir.mkdir(parents=True, exist_ok=True)
            final = self._dir / f"{self.op_id}.json"
            temp = self._dir / f"{self.op_id}.json.tmp"
            temp.write_text(json.dumps(self._data), encoding="utf-8")
            os.replace(temp, final)
            self._last_write = self._mono()
        except Exception:  # progress must never break the operation
            return


def _int(value: JsonValue) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def track(
    project: Project, kind: Kind, label: str, *, unit: str, total: int | None = None
) -> Reporter:
    """A reporter for one operation of `project`; nothing is written to the event log."""
    return Reporter(project.paths.dir / PROGRESS_DIR, kind, label, unit=unit, total=total)


def progress_list(project: Project, now: float | None = None) -> list[dict[str, JsonValue]]:
    """Running and recently finished operations, oldest first, with `elapsed_seconds`,
    `rate_per_second` and `eta_seconds` (None when unknown). Expired entries are deleted.

    A running entry not updated for `STALE_SECONDS` is reported with state `stale`. Reading never
    raises: an unreadable or foreign file is skipped."""
    return read_directory(project.paths.dir / PROGRESS_DIR, now)


def read_directory(directory: Path, now: float | None = None) -> list[dict[str, JsonValue]]:
    at = time.time() if now is None else now
    rows: list[dict[str, JsonValue]] = []
    try:
        files = sorted(directory.glob("op_*.json"))
    except OSError:
        return rows
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        started = _parse(raw.get("started_at"))
        updated = _parse(raw.get("updated_at"))
        if started is None or updated is None:
            continue
        state = str(raw.get("state"))
        idle = at - updated
        if (state != "running" and idle > FINISHED_KEEP_SECONDS) or idle > ABANDONED_SECONDS:
            with contextlib.suppress(OSError):
                path.unlink()
            continue
        if state == "running" and idle > STALE_SECONDS:
            state = "stale"
        row: dict[str, JsonValue] = dict(raw)
        row["state"] = state
        row.update(_figures(raw, state, started, updated, at))
        rows.append(row)
    rows.sort(key=lambda r: (str(r.get("started_at")), str(r.get("op_id"))))
    return rows


def _figures(
    raw: dict[str, JsonValue], state: str, started: float, updated: float, at: float
) -> dict[str, JsonValue]:
    end = at if state == "running" else updated
    elapsed = max(end - started, 0.0)
    done = _int(raw.get("done"))
    total_raw = raw.get("total")
    total = _int(total_raw) if total_raw is not None else None
    rate = done / elapsed if elapsed > 0 and done > 0 else None
    eta = None
    if state == "running" and rate is not None and total is not None and total >= done:
        eta = round((total - done) / rate, 1)
    return {
        "idle_seconds": round(max(at - updated, 0.0), 1),
        "elapsed_seconds": round(elapsed, 1),
        "rate_per_second": None if rate is None else round(rate, 3),
        "eta_seconds": eta,
    }
