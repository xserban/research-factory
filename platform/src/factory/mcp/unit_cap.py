"""The unit cap of a headless run (plan feed-hub H8): `FACTORY_UNIT_CAP` and `FACTORY_RUN_ID` in
the environment of the MCP server the runner starts for its child.

Invariants:
- Without `FACTORY_UNIT_CAP` there is no cap: an ordinary session is unchanged.
- The count is in this process only. A `*_next` tool of a run's stage calls `check` first, which
  refuses once the process has served `cap` units, and `count` with what it is about to return.
  A unit is a record of a screening batch, otherwise one batch (a work, a task, a target).
- A refusal is one `FactoryValidationError` on field `cap-reached`; it writes nothing.
- A value that is not a positive integer is read as no cap (a stray variable never blocks work).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from pydantic import JsonValue

from factory.errors import FactoryValidationError, ValidationIssue

CAP_ENV = "FACTORY_UNIT_CAP"
RUN_ENV = "FACTORY_RUN_ID"


class UnitCap:
    """The units served by this process against the cap of its run."""

    def __init__(self, cap: int | None = None, run_id: str | None = None) -> None:
        self.cap = cap
        self.run_id = run_id
        self.served = 0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> UnitCap:
        raw = env.get(CAP_ENV, "").strip()
        cap = int(raw) if raw.isdecimal() and int(raw) >= 1 else None
        return cls(cap, env.get(RUN_ENV) or None)

    def check(self) -> None:
        """Refuse with `cap-reached` once `cap` units have been served."""
        if self.cap is None:
            return
        with self._lock:
            if self.served >= self.cap:
                run = f" of run {self.run_id}" if self.run_id else ""
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "cap-reached",
                            f"this run{run} has served its {self.cap} units; stop and report",
                        )
                    ]
                )

    def count(self, served: JsonValue) -> None:
        """Add the units of a served result (a dump with a `batch`; none when it is null)."""
        if self.cap is None or not isinstance(served, dict):
            return
        batch = served.get("batch")
        if not batch:
            return
        records = batch.get("records") if isinstance(batch, dict) else None
        units = len(records) if isinstance(records, list) and records else 1
        with self._lock:
            self.served += units
