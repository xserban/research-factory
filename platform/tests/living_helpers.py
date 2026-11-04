"""Fixtures for living-B tests: a screening corpus that declares a watch, and watch filler."""

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.model.screening import PassLabel
from factory.model.watch import WatchPlan, WatchSource
from factory.services.calibration import calibration_items, draw_calibration
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import open_pass, screen_next
from tests.helpers import SourcesFor, _setup
from tests.screening_helpers import decide
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


def start_screening(project: Project, agent: Actor) -> tuple[str, set[str]]:
    """Draw the calibration set, open both passes and queue pass A; return the protocol id and
    the calibration works (which a test must not decide)."""
    draw_calibration(project, project.system_actor(), random_seed=11)
    screen_next(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    protocol = current_protocol(project)
    assert protocol is not None
    return protocol.protocol_id, set(calibration_items(project))


def agree(
    project: Project,
    agent: Actor,
    work_id: str,
    protocol_id: str,
    verdict: str,
    *,
    supersedes: dict[PassLabel, str] | None = None,
) -> dict[PassLabel, str]:
    """Both passes decide `work_id` alike (criterion EX01 for an exclusion); returns the decision
    ids by pass. `supersedes` replaces the earlier decisions of those ids."""
    criterion = "EX01" if verdict == "exclude" else None
    return {
        label: decide(
            project,
            agent,
            work_id,
            protocol_id,
            verdict,
            pass_label=label,
            criterion=criterion,
            supersedes=None if supersedes is None else supersedes[label],
        )
        for label in PassLabel
    }
