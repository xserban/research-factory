"""The unit cap of a headless run (plan feed-hub H8): `FACTORY_UNIT_CAP` and `FACTORY_RUN_ID` in
the environment of the MCP server the runner starts for its child.

Invariants:
- Without `FACTORY_UNIT_CAP` there is no cap: an ordinary session is unchanged.
- The count is in this process only. A `*_next` tool of a run's stage calls `reserve(n)` before
  it serves, with the most units the call can serve; the check and the count are one step under
  one lock. It refuses with `cap-reached` when the units served plus `n` would pass the cap, and
  `settle` gives back what the call did not serve. The cap is therefore never passed.
- A unit is, per tool: `screen_next`, one record of the batch (a batch is up to `SCREEN_BATCH`
  records, served whole; a cap smaller than a batch serves one batch); `extract_next`,
  `appraisal_next`, `contribution_next`, `mine_next`, `intuition_next`, one task (a work, a
  work-and-miner, a target). `remaining()` is the units still servable (None without a cap).
- A refusal is one `FactoryValidationError` on field `cap-reached`; it writes nothing.
- A value that is not a positive integer is read as no cap (a stray variable never blocks work).
- With `FACTORY_RUN_DIR` (the run folder) set and a cap, every change of the served total made by
  `settle` or `count` rewrites `<run dir>/units.json` (`run_id`, `served`, `cap`, `updated_at`)
  atomically: a temp file and `os.replace`, under the lock. An OSError is swallowed; the file is
  evidence for the cost reader (`services.run_costs`) and serving never depends on it.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from factory.errors import FactoryValidationError, ValidationIssue

CAP_ENV = "FACTORY_UNIT_CAP"
RUN_ENV = "FACTORY_RUN_ID"
RUN_DIR_ENV = "FACTORY_RUN_DIR"
UNITS_FILE = "units.json"


class UnitCap:
    """The units served by this process against the cap of its run."""

    def __init__(
        self, cap: int | None = None, run_id: str | None = None, run_dir: Path | None = None
    ) -> None:
        self.cap = cap
        self.run_id = run_id
        self.run_dir = run_dir
        self.served = 0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> UnitCap:
        raw = env.get(CAP_ENV, "").strip()
        cap = int(raw) if raw.isdecimal() and int(raw) >= 1 else None
        run_dir = env.get(RUN_DIR_ENV) or None
        return cls(cap, env.get(RUN_ENV) or None, Path(run_dir) if run_dir else None)

    def _write_units(self) -> None:
        """Rewrite `units.json` in the run folder with the served total (caller holds the lock).
        Swallows OSError: a counter file never breaks serving."""
        if self.run_dir is None or self.cap is None:
            return
        record = {
            "run_id": self.run_id,
            "served": self.served,
            "cap": self.cap,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        target = self.run_dir / UNITS_FILE
        temp = self.run_dir / f"{UNITS_FILE}.tmp"
        try:
            temp.write_text(json.dumps(record), encoding="utf-8")
            os.replace(temp, target)
        except OSError:
            return

    def remaining(self) -> int | None:
        """The units still servable, or None when there is no cap."""
        if self.cap is None:
            return None
        with self._lock:
            return max(self.cap - self.served, 0)

    def _refusal(self) -> FactoryValidationError:
        run = f" of run {self.run_id}" if self.run_id else ""
        return FactoryValidationError(
            [
                ValidationIssue(
                    "cap-reached",
                    f"this run{run} has {max((self.cap or 0) - self.served, 0)} of its "
                    f"{self.cap} units left; stop and report",
                )
            ]
        )

    def reserve(self, n: int = 1, *, whole: int | None = None) -> int:
        """Reserve `n` units (the most the call can serve) in one step and return the number
        reserved. Without a cap, `n`. Refuses with `cap-reached` when fewer than `n` units remain;
        a call that serves whole batches passes `whole` (the batch size) and, with a cap smaller
        than one batch, reserves the cap instead so that one batch can still be served when
        nothing has been served yet."""
        if self.cap is None:
            return n
        with self._lock:
            need = n
            if whole is not None and self.cap < whole and self.served == 0:
                need = min(n, self.cap)
            if self.served + need > self.cap:
                raise self._refusal()
            self.served += need
            return need

    def settle(self, reserved: int, served: JsonValue) -> None:
        """Give back the part of `reserved` that the result `served` does not use (the units of a
        result: the records of a batch, else one for a batch, none when it is null)."""
        if self.cap is None:
            return
        used = min(reserved, self.units(served))
        with self._lock:
            self.served = max(self.served - (reserved - used), 0)
            self._write_units()

    @staticmethod
    def units(served: JsonValue) -> int:
        """The units of a served result: its records, else one for a batch, none for null."""
        if not isinstance(served, dict):
            return 0
        batch = served.get("batch")
        if not batch:
            return 0
        records = batch.get("records") if isinstance(batch, dict) else None
        return len(records) if isinstance(records, list) and records else 1

    @contextmanager
    def serving(
        self, n: int = 1, *, whole: int | None = None
    ) -> Iterator[Callable[[JsonValue], None]]:
        """Reserve `n` units for one `*_next` call; yields `done(served)`, which settles the
        reservation against the result. A call that raises before `done` gives all back."""
        reserved = self.reserve(n, whole=whole)
        settled = False

        def done(served: JsonValue) -> None:
            nonlocal settled
            settled = True
            self.settle(reserved, served)

        try:
            yield done
        finally:
            if not settled:
                self.release(reserved)

    def release(self, n: int) -> None:
        """Give back `n` reserved units (the call failed before serving)."""
        if self.cap is None:
            return
        with self._lock:
            self.served = max(self.served - n, 0)

    def check(self) -> None:
        """Refuse with `cap-reached` once `cap` units have been served."""
        if self.cap is None:
            return
        with self._lock:
            if self.served >= self.cap:
                raise self._refusal()

    def count(self, served: JsonValue) -> None:
        """Add the units of a served result (a dump with a `batch`; none when it is null)."""
        if self.cap is None:
            return
        units = self.units(served)
        with self._lock:
            self.served += units
            self._write_units()
