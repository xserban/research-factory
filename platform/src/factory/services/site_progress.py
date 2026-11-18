"""Build progress of a hub product, shared between the build and the server (IDEA-96).

`site.build` opens a progress file `site/.progress/<product>.json` for each product it builds and
removes it at the end; a product's build may call `report(done, total, label)` from its slow loop.
The server reads the file (`read`) and, with the duration of the product's last build, turns it
into a percentage (`summary`). Outside a build, `report` does nothing, so the product code also
runs unchanged from tests and from `factory site build`.

Invariants: the file is written aside and swapped in, never half-written; writes are at most
one per `MIN_GAP` seconds (the last step is always written); progress is a display aid and never
decides anything.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

PROGRESS_DIR: Final = ".progress"
MIN_GAP: Final = 0.5


@dataclass
class _Run:
    path: Path
    started: float
    last_write: float = 0.0
    state: dict[str, object] = field(default_factory=dict)


_active: ContextVar[_Run | None] = ContextVar("site_progress", default=None)


def _write(run: _Run) -> None:
    run.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = run.path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"started": run.started, **run.state}), encoding="utf-8")
    tmp.replace(run.path)
    run.last_write = time.monotonic()


@contextmanager
def tracking(site_root: Path, product_id: str) -> Iterator[None]:
    """Open the progress file of one product build; it is removed when the build ends."""
    run = _Run(site_root / PROGRESS_DIR / f"{product_id}.json", time.time())
    with contextlib.suppress(OSError):
        _write(run)
    token = _active.set(run)
    try:
        yield
    finally:
        _active.reset(token)
        run.path.unlink(missing_ok=True)


def report(done: int, total: int, label: str = "") -> None:
    """Record that `done` of `total` steps (`label`: of what) are finished; a no-op outside a
    build."""
    run = _active.get()
    if run is None:
        return
    run.state = {"done": done, "total": total, "label": label}
    if done < total and time.monotonic() - run.last_write < MIN_GAP:
        return
    with contextlib.suppress(OSError):
        _write(run)


def read(site_root: Path, product_id: str) -> dict[str, object] | None:
    """The progress file of a running build, or None."""
    try:
        loaded = json.loads((site_root / PROGRESS_DIR / f"{product_id}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def summary(found: dict[str, object] | None, last_seconds: float | None) -> dict[str, object]:
    """What the UI shows of a running build: `percent` (0-99, None when unknown), `elapsed` and
    `remaining` seconds (remaining None when unknown), `done`, `total` and `label` of the steps.
    The percentage counts real steps when the build reports them, and otherwise compares elapsed
    time with the product's last build, capped at 99 % (a build is never shown done before it
    is). Time left comes from the last build's length while that is known and not passed, else
    from the steps; with every step done it is None (the build is writing its files)."""
    now = time.time()
    started = found.get("started") if found else None
    elapsed = max(0.0, now - started) if isinstance(started, (int, float)) else 0.0
    done = found.get("done") if found else None
    total = found.get("total") if found else None
    percent: float | None = None
    remaining: float | None = None
    if isinstance(done, int) and isinstance(total, int) and total > 0:
        percent = min(99.0, 100.0 * done / total)
        if last_seconds and elapsed < last_seconds:
            remaining = last_seconds - elapsed  # the last build's length is steadier than steps
        elif 0 < done < total:
            remaining = elapsed * (total - done) / done
    elif last_seconds:
        percent = min(99.0, 100.0 * elapsed / last_seconds)
        remaining = max(0.0, last_seconds - elapsed)
    return {
        "percent": None if percent is None else round(percent),
        "elapsed": round(elapsed),
        "remaining": None if remaining is None else round(remaining),
        "done": done if isinstance(done, int) else None,
        "total": total if isinstance(total, int) else None,
        "label": str(found.get("label") or "") if found else "",
    }
