"""Fixtures for living-B tests: a screening corpus that declares a watch, and watch filler."""

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.model.watch import WatchPlan, WatchSource
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from tests.helpers import SourcesFor, _setup
from tests.watch_helpers import record


def screening_watch_setup(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    dual_sample: float | None = 0.3,
    snapshot_every: int | None = None,
) -> str:
    """A screening corpus (seeds, protocol with `dual_sample`) that declares a watch on openalex.

    The planned query is the screening setup's `attention`; returns the amended protocol id."""
    _setup(project, agent, human, mock_sources, dual_sample=dual_sample, random_works=0)
    current = current_protocol(project)
    assert current is not None
    plan = WatchPlan(
        sources=(WatchSource(source="openalex", interval_days=7),), snapshot_every=snapshot_every
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"watch_plan": plan}),
        reason="declare the watch",
        semantic=True,
        effects={},
    )
    amended = current_protocol(project)
    assert amended is not None
    return amended.protocol_id


def filler(count: int, *, first: int = 0) -> list[dict[str, Any]]:
    """`count` distinct watch records."""
    return [
        record(f"Watch study {k} of routing", author=f"Wat {k}", year=2025)
        for k in range(first, first + count)
    ]
