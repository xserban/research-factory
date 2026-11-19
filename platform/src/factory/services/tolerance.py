"""The protocol's `pending_tolerance` (decision 138): how many works may stay incomplete without
blocking a workflow step. Shared by the snowball and chase gates, pass B agreement, the
extraction audit and extraction agreement.

Invariant: tolerated works are never dropped silently; the caller records them on the event it
writes, or returns them in its result when it writes none. Read-only.
"""

from __future__ import annotations

from collections.abc import Collection

from factory.model.protocol import UnscreenedTolerance
from factory.services.context import Project
from factory.services.protocol import current_protocol


def pending_tolerance(project: Project) -> UnscreenedTolerance | None:
    """The protocol's declared `pending_tolerance` (decision 138); None tolerates none."""
    protocol = current_protocol(project)
    return None if protocol is None else protocol.spec.pending_tolerance


def tolerated_within(project: Project, missing: Collection[str], size: int) -> tuple[str, ...]:
    """The sorted, unique `missing` works when the declared tolerance allows that many among
    `size` works, else empty (the caller then refuses). With no tolerance, or no missing work,
    empty."""
    unique = set(missing)
    tolerance = pending_tolerance(project)
    if tolerance is None or not unique or not tolerance.allows(len(unique), size):
        return ()
    return tuple(sorted(unique))
