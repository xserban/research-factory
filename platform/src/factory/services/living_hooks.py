"""Cycle hooks of a living review (living-B): what runs after each watch cycle's searches.

A hook is a living-A `CycleHook`: `(project, cycle_id, new_work_ids) -> run ids`. Each acts as
the system and decides nothing about any work. They are listed in `DEFAULT_HOOKS`, which the
CLI and the MCP server pass to `watch_run`.

Invariants:
- `extend_sample_hook` only extends pass B's sample, with the seed derived from the cycle id, so
  a rerun of the same cycle draws the same works and the event records the seed.
- `snapshot_hook` records a snapshot after every `watch_plan.snapshot_every` finished cycles.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text

from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.screening import extend_sample
from factory.services.snapshots import last_snapshot_event, snapshot
from factory.services.watch import CycleHook

# Module kind (slice M): a cycle hook is a `status` module; hand-written until M-B lands.


def cycle_seed(cycle_id: str) -> int:
    """The reproducible seed of a cycle's sample draw."""
    return int(hashlib.sha256(cycle_id.encode()).hexdigest()[:8], 16)


def extend_sample_hook(
    project: Project, cycle_id: str, new_work_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Extend pass B's sample over the works that arrived (title/abstract); returns no runs."""
    extend_sample(project, project.system_actor(), random_seed=cycle_seed(cycle_id))
    return ()


def snapshot_hook(
    project: Project, cycle_id: str, new_work_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Take a snapshot when `watch_plan.snapshot_every` cycles have run since the last one.

    The count includes the calling cycle, which is still open while its hooks run and is the one
    cycle a snapshot may ignore. Writes nothing when the plan sets no `snapshot_every`."""
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.watch_plan
    if plan is None or plan.snapshot_every is None:
        return ()
    since = last_snapshot_event(project)
    with project.index.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM watch_cycles WHERE started_event > :since"),
            {"since": since or ""},
        ).scalar_one()
    if count >= plan.snapshot_every:
        snapshot(project, project.system_actor(), trigger="cycle", ignoring_cycle=cycle_id)
    return ()


DEFAULT_HOOKS: tuple[CycleHook, ...] = (extend_sample_hook, snapshot_hook)
"""The hooks the CLI and the MCP server pass to `watch_run`, in order."""
