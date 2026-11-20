# ruff: noqa: F811
"""A real snowball round needs the researcher's recorded go-ahead (G5, ruling 2026-11-20).

In `pilot` and `systematic` a round that is not a dry run cites a selected `plan` decision on the
subject `snowball-<direction>-<round_no>`; `exploratory` and every dry run need none. Every entry
and work is invented (fixtures are those of `test_snowball_round`).
"""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.decisions import DecisionItem, DecisionLevel, DecisionSelected
from factory.model.references import Direction
from factory.model.screening import Channel
from factory.services import decisions as decisions_service
from factory.services.context import Project
from factory.services.snowball import snowball_round
from tests.document_helpers import event_bytes, events_of_type
from tests.test_snowball_round import (  # noqa: F401  (fixtures)
    _sources,
    explore_world,
    planned,
    world,
)


@pytest.fixture
def enforce_round_decision() -> None:
    """Marks a test that runs with the round decision rule on (conftest switches it off for the
    older round tests, which predate it)."""


def _suggest(
    project: Project, agent: Actor, subject: str = "snowball-backward-1", select: bool = False
) -> str:
    decision_id = decisions_service.suggest(
        project,
        agent,
        DecisionLevel.PLAN,
        subject,
        "Run the first backward round.",
        (DecisionItem(item_id="I01", text="Backward round 1", grounds=("dry run",)),),
    )
    if select:
        decisions_service.select(
            project, project.human_actor(), decision_id, ["I01"], [], "", Channel.CLI
        )
    return decision_id


def _fields(error: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in error.value.issues]


def _run(project: Project, agent: Actor, ids: list[str] | None) -> object:
    return snowball_round(
        project,
        agent,
        Direction.BACKWARD,
        sources=_sources(),
        dry_run=False,
        decision_ids=ids,
    )


def test_pilot_round_refused_without_a_decision(
    enforce_round_decision: None, project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as caught:
        _run(project, agent, None)
    assert _fields(caught) == ["decision_ids"]
    assert "snowball-backward-1" in caught.value.issues[0].reason
    assert event_bytes(project) == before


def test_pilot_round_runs_with_a_selected_decision(
    enforce_round_decision: None, project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    decision_id = _suggest(project, agent, select=True)
    result = _run(project, agent, [decision_id])
    assert result.round_id is not None
    started = events_of_type(project, "snowball.round_started")
    assert [e.payload["decision_ids"] for e in started] == [[decision_id]]


def test_round_refused_with_an_unselected_decision(
    enforce_round_decision: None, project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    decision_id = _suggest(project, agent)
    before = event_bytes(project)
    with pytest.raises(FactoryValidationError) as caught:
        _run(project, agent, [decision_id])
    assert _fields(caught) == ["decision_ids.0"]
    assert event_bytes(project) == before


def test_round_refused_with_an_agent_selection(
    enforce_round_decision: None, project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    decision_id = _suggest(project, agent)
    forged = project.events.make(
        "decision.selected",
        DecisionSelected(decision_id=decision_id, selected=("I01",)),
        agent,
        refs=[decision_id],
        input_blob=project.blobs.put_json({}),
    )
    project.record([forged])
    with pytest.raises(FactoryValidationError) as caught:
        _run(project, agent, [decision_id])
    assert _fields(caught) == ["decision_ids.0"]


def test_decision_for_another_round_is_refused(
    enforce_round_decision: None, project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    for subject in ("snowball-backward-2", "snowball-forward-1"):
        decision_id = _suggest(project, agent, subject, select=True)
        with pytest.raises(FactoryValidationError) as caught:
            _run(project, agent, [decision_id])
        assert _fields(caught) == ["decision_ids.0"]


def test_dry_run_needs_no_decision(
    enforce_round_decision: None, project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    before = event_bytes(project)
    result = snowball_round(project, agent, Direction.BACKWARD, sources=_sources())
    assert result.round_id is None
    assert event_bytes(project) == before


def test_exploratory_round_needs_no_decision(
    enforce_round_decision: None, explore_world: Project, agent: Actor
) -> None:
    result = snowball_round(
        explore_world, agent, Direction.BACKWARD, sources=_sources(), dry_run=False
    )
    assert result.round_id is not None
    started = events_of_type(explore_world, "snowball.round_started")
    assert "decision_ids" not in started[0].payload
