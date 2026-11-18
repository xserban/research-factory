"""What the agents are working on now (IDEA-98): one reading of the claimed tasks, the open passes,
the platform's long operations and the headless workers' trace files.

Invariants:
- Read-only. Nothing is written: no event, no file. (`progress_list` prunes expired progress
  files, as it always does; that is the one filesystem write and it is not a record.)
- Deterministic given the event log, the files under `ops/` and `now`. The clock is never read
  here except by `activity_cached`, which supplies it.
- Every count comes from the projected index: the rows of `tasks`, grouped by miner, version,
  pass label and calibration flag for a mining task (read from its content blob), else by kind.
  `total` is the tasks of the pass, `done` the completed ones. `mining.mine_status` is not used:
  it folds every extraction of the project and takes minutes on the pilot. Rate and estimated
  time left are estimates over the last `RATE_WINDOW_MINUTES` and are named so
  (`rate_estimate_per_hour`, `eta_estimate_minutes`); the estimate is None when the rate is 0.
- An active row is a task whose projected status is `claimed` and whose lease is still valid at
  `now`. A claimed task whose lease has expired is not held: it is counted in `abandoned` of its
  pass. `claimed_at` is the lease end less `TASK_LEASE`. A row is `stale` when the holder's session
  wrote no event for `STALE_MINUTES`; the lease itself may still be live.
- A pass is shown in `passes` only when it has a held task or a completion in the last
  `DORMANT_HOURS` hours; the others are in `dormant`.
- One index sync per call (`activity` holds one snapshot).
- `activity_cached` keeps the last answer per project for `CACHE_SECONDS`, keyed on the size and
  newest modification time of the event files, so a polled endpoint does not recompute on every
  request. An answer is never older than `CACHE_SECONDS`, and a change of the log ends the cache.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pydantic import JsonValue
from sqlalchemy import bindparam, text

from factory.clock import format_ts
from factory.events.reader import event_files
from factory.model.base import StrictModel
from factory.model.task import TASK_LEASE
from factory.services.context import Project
from factory.services.progress import progress_list
from factory.services.stages import is_mine_kind

STALE_MINUTES: Final = 30
"""A session that holds a task and wrote no event for this long is shown as stale."""
DORMANT_HOURS: Final = 24
"""A pass with no held task and no completion for this long is dormant."""
RATE_WINDOW_MINUTES: Final = 30
"""The window the completion rate is counted over."""
TRACE_WINDOW_MINUTES: Final = 120
"""A `.live` trace file older than this is not shown."""
TRACE_LIMIT: Final = 30
CACHE_SECONDS: Final = 8.0
_TAIL_BYTES: Final = 4096


class ActiveRow(StrictModel):
    """One claimed task."""

    session: str
    actor: str
    task_id: str
    kind: str
    scope: str
    """The miner name for a mining task, else the task kind."""
    miner_version: int | None = None
    pass_label: str | None = None
    mode: str | None = None
    """`calibration` or `production` for a mining task, else None."""
    work_id: str | None = None
    title: str | None = None
    claimed_at: str
    minutes_held: float
    rows_recorded: int
    last_event_at: str | None
    stale: bool


class PassRow(StrictModel):
    """One open miner, or one other task kind with tasks."""

    kind: str
    """`miner` or the task kind."""
    name: str
    version: int | None = None
    pass_label: str | None = None
    mode: str | None = None
    """`calibration` or `production` for a miner, else None."""
    abandoned: int = 0
    """Claimed tasks whose lease has expired without completion or release."""
    done: int
    total: int
    claimed: int
    completed_recent: int
    rate_estimate_per_hour: float
    eta_estimate_minutes: float | None
    released: int


class TraceRow(StrictModel):
    path: str
    modified_at: str
    last_line: str
    size: int


class Activity(StrictModel):
    now: str
    active: list[ActiveRow]
    passes: list[PassRow]
    dormant: list[PassRow]
    operations: list[dict[str, JsonValue]]
    traces: list[TraceRow]


def _pass_label(kind: str, content: dict[str, JsonValue]) -> str | None:
    label = content.get("pass_label")
    if isinstance(label, str):
        return label.upper()
    return {"mine_a": "A", "mine_b": "B"}.get(kind)


def _as_dict(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _first_record(content: dict[str, JsonValue]) -> dict[str, JsonValue]:
    records = content.get("records")
    if isinstance(records, list) and records:
        return _as_dict(records[0])
    return {}


def _minutes(delta: timedelta) -> float:
    return round(delta.total_seconds() / 60, 1)


def _active(project: Project, now: datetime) -> list[ActiveRow]:
    from factory.clock import parse_ts

    with project.index.connect() as conn:
        claimed = conn.execute(
            text(
                "SELECT task_id, kind, content_blob, claimed_by, claim_session, lease_until "
                "FROM tasks WHERE status = 'claimed' AND claim_session IS NOT NULL "
                "ORDER BY lease_until, task_id"
            )
        ).all()
        if not claimed:
            return []
        sessions = sorted({str(r.claim_session) for r in claimed})
        last_seen = {
            str(s): str(t)
            for s, t in conn.execute(
                text(
                    "SELECT session, MAX(ts) FROM events WHERE session IN :s GROUP BY session"
                ).bindparams(bindparam("s", expanding=True)),
                {"s": sessions},
            ).all()
        }
        rows_by = {
            (str(t), str(s)): int(n)
            for t, s, n in conn.execute(
                text(
                    "SELECT r.task_id, e.session, COUNT(*) FROM extraction_rows r "
                    "JOIN events e ON e.id = r.event_id WHERE r.task_id IN :t GROUP BY 1, 2"
                ).bindparams(bindparam("t", expanding=True)),
                {"t": [str(r.task_id) for r in claimed]},
            ).all()
        }
    out: list[ActiveRow] = []
    for r in claimed:
        if parse_ts(str(r.lease_until)) <= now:
            continue  # an expired lease is not held; `_passes` counts it as abandoned
        content = _as_dict(project.blobs.get_json(str(r.content_blob)))
        record = _first_record(content)
        mine = is_mine_kind(str(r.kind))
        version = content.get("version")
        work = record.get("work_id")
        title = record.get("title")
        claimed_at = parse_ts(str(r.lease_until)) - TASK_LEASE
        last = last_seen.get(str(r.claim_session))
        silent = None if last is None else now - parse_ts(last)
        out.append(
            ActiveRow(
                session=str(r.claim_session),
                actor=str(r.claimed_by),
                task_id=str(r.task_id),
                kind=str(r.kind),
                scope=str(content.get("miner")) if mine and content.get("miner") else str(r.kind),
                miner_version=version if mine and isinstance(version, int) else None,
                pass_label=_pass_label(str(r.kind), content),
                mode=(
                    ("calibration" if content.get("calibration_id") else "production")
                    if mine
                    else None
                ),
                work_id=work if isinstance(work, str) else None,
                title=title if isinstance(title, str) and title else None,
                claimed_at=format_ts(claimed_at),
                minutes_held=_minutes(now - claimed_at),
                rows_recorded=rows_by.get((str(r.task_id), str(r.claim_session)), 0),
                last_event_at=last,
                stale=silent is None or silent >= timedelta(minutes=STALE_MINUTES),
            )
        )
    return out


def _rate(done_recent: int, left: int) -> tuple[float, float | None]:
    per_hour = round(done_recent * 60 / RATE_WINDOW_MINUTES, 2)
    eta = None if per_hour <= 0 else round(left / per_hour * 60, 1)
    return per_hour, eta


def _events_by_task(
    project: Project, event_type: str, since: str | None
) -> list[tuple[str, str, str]]:
    """(kind, content blob, ts) of the tasks an event of `event_type` names."""
    sql = (
        "SELECT t.kind, t.content_blob, e.ts FROM events e "
        "JOIN event_refs r ON r.event_id = e.id JOIN tasks t ON t.task_id = r.ref "
        "WHERE e.type = :type" + ("" if since is None else " AND e.ts >= :since")
    )
    params: dict[str, str] = {"type": event_type}
    if since is not None:
        params["since"] = since
    with project.index.connect() as conn:
        return [(str(a), str(b), str(c)) for a, b, c in conn.execute(text(sql), params).all()]


_PassKey = tuple[str, str, int | None, str | None, str | None]


class _Count:
    __slots__ = ("abandoned", "claimed", "day", "done", "recent", "released", "total")

    def __init__(self) -> None:
        self.total = self.done = self.claimed = self.abandoned = 0
        self.recent = self.day = self.released = 0


def _pass_key(project: Project, kind: str, blob: str, memo: dict[str, _PassKey]) -> _PassKey:
    """The pass a task belongs to: miner, version, pass label and mode; else its kind."""
    if not is_mine_kind(kind):
        return (kind, kind, None, None, None)
    hit = memo.get(blob)
    if hit is None:
        content = _as_dict(project.blobs.get_json(blob))
        version = content.get("version")
        hit = (
            "miner",
            str(content.get("miner", "")),
            version if isinstance(version, int) else None,
            _pass_label(kind, content),
            "calibration" if content.get("calibration_id") else "production",
        )
        memo[blob] = hit
    return hit


def _passes(project: Project, now: datetime) -> tuple[list[PassRow], list[PassRow]]:
    """(shown passes, dormant passes). Counts come from `tasks` and the task events."""
    from factory.clock import parse_ts

    memo: dict[str, _PassKey] = {}
    counts: dict[_PassKey, _Count] = {}

    def of(kind: str, blob: str) -> _Count:
        return counts.setdefault(_pass_key(project, kind, blob, memo), _Count())

    with project.index.connect() as conn:
        tasks = conn.execute(
            text("SELECT kind, status, content_blob, lease_until FROM tasks")
        ).all()
    for kind, status, blob, lease in tasks:
        c = of(str(kind), str(blob))
        c.total += 1
        if status == "completed":
            c.done += 1
        elif status == "claimed" and lease is not None:
            if parse_ts(str(lease)) > now:
                c.claimed += 1
            else:
                c.abandoned += 1
    since = format_ts(now - timedelta(minutes=RATE_WINDOW_MINUTES))
    for kind, blob, ts in _events_by_task(
        project, "task.completed", format_ts(now - timedelta(hours=DORMANT_HOURS))
    ):
        c = of(kind, blob)
        c.day += 1
        c.recent += ts >= since
    for kind, blob, _ in _events_by_task(project, "task.released", None):
        of(kind, blob).released += 1

    shown: list[PassRow] = []
    dormant: list[PassRow] = []
    for key in sorted(
        counts, key=lambda k: (k[0] != "miner", k[1], k[2] or 0, k[3] or "", k[4] or "")
    ):
        c = counts[key]
        per_hour, eta = _rate(c.recent, c.total - c.done)
        row = PassRow(
            kind=key[0],
            name=key[1],
            version=key[2],
            pass_label=key[3],
            mode=key[4],
            abandoned=c.abandoned,
            done=c.done,
            total=c.total,
            claimed=c.claimed,
            completed_recent=c.recent,
            rate_estimate_per_hour=per_hour,
            eta_estimate_minutes=eta,
            released=c.released,
        )
        (shown if c.claimed or c.day else dormant).append(row)
    return shown, dormant


def _last_line(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _traces(project: Project, now: datetime) -> list[TraceRow]:
    ops = project.paths.dir / "ops"
    if not ops.is_dir():
        return []
    cutoff = now.timestamp() - TRACE_WINDOW_MINUTES * 60
    found: list[tuple[float, TraceRow]] = []
    for base, _, names in os.walk(ops):
        for name in names:
            if not name.endswith(".live"):
                continue
            full = Path(base) / name
            try:
                stat = full.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue
            found.append(
                (
                    stat.st_mtime,
                    TraceRow(
                        path=full.relative_to(ops).as_posix(),
                        modified_at=format_ts(datetime.fromtimestamp(stat.st_mtime, UTC)),
                        last_line=_last_line(full),
                        size=stat.st_size,
                    ),
                )
            )
    found.sort(key=lambda item: (-item[0], item[1].path))
    return [row for _, row in found[:TRACE_LIMIT]]


def activity(project: Project, now: datetime) -> Activity:
    """The four panels as of `now` (timezone-aware). Read-only; see the module invariants."""
    with project.index.snapshot():  # syncs once; the reads below do not sync again
        active = _active(project, now)
        passes, dormant = _passes(project, now)
    return Activity(
        now=format_ts(now),
        active=active,
        passes=passes,
        dormant=dormant,
        operations=progress_list(project, now.timestamp()),
        traces=_traces(project, now),
    )


_CACHE: dict[str, tuple[tuple[int, float], float, Activity]] = {}
_CACHE_LOCK = threading.Lock()


def _log_signature(project: Project) -> tuple[int, float]:
    """(total size, newest modification time) of the event files."""
    size, newest = 0, 0.0
    for path in event_files(project.paths.events_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        size += stat.st_size
        newest = max(newest, stat.st_mtime)
    return size, newest


def activity_cached(
    project: Project,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
) -> Activity:
    """`activity` as of the clock, reused for `CACHE_SECONDS` while the event log is unchanged."""
    key = str(project.paths.dir)
    signature = _log_signature(project)
    at = monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == signature and at - hit[1] < CACHE_SECONDS:
            return hit[2]
    fresh = activity(project, clock())
    with _CACHE_LOCK:
        _CACHE[key] = (signature, at, fresh)
    return fresh
