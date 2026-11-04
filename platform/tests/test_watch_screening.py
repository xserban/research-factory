"""Watch works reach pass B's sample by the recorded seed and nothing else changes (Task 2)."""

from __future__ import annotations

import hashlib
import random
from typing import Any, cast

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.screening import PassLabel
from factory.services.calibration import calibration_status, draw_calibration
from factory.services.context import Project
from factory.services.living_hooks import extend_sample_hook
from factory.services.screening import extend_sample, open_pass, pass_b_sample, screen_next
from factory.services.watch import CycleSummary, watch_run
from tests.helpers import SourcesFor, _of_type
from tests.living_helpers import filler, screening_watch_setup
from tests.watch_helpers import ScriptedSource, adapters, by_text


def _ready(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    dual_sample: float | None = 0.3,
) -> None:
    screening_watch_setup(project, agent, human, mock_sources, dual_sample=dual_sample)
    draw_calibration(project, project.system_actor(), random_seed=11)
    open_pass(project, agent, PassLabel.B)


def _cycle(project: Project, count: int = 200) -> CycleSummary:
    source = ScriptedSource(by_text({"attention": [filler(count)]}))
    summary = watch_run(
        project,
        sources=adapters(source),
        trigger="scheduler",
        after_runs=(extend_sample_hook,),
    )
    assert summary is not None
    return summary


def _seed_of(cycle_id: str) -> int:
    return int(hashlib.sha256(cycle_id.encode()).hexdigest()[:8], 16)


def test_watch_works_extend_pass_b_sample(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    before_sample = set(pass_b_sample(project) or ())
    assert len(_of_type(project, "screening.sample_extended")) == 1  # recorded at open
    summary = _cycle(project)
    events = _of_type(project, "screening.sample_extended")
    assert len(events) == 2
    payload = cast(dict[str, Any], events[-1].payload)
    assert payload["random_seed"] == _seed_of(summary.cycle_id)
    assert set(payload["considered"]) == set(summary.new_work_ids)
    rng = random.Random(payload["random_seed"])
    expected = tuple(w for w in payload["considered"] if rng.random() < 0.3)
    assert tuple(payload["added"]) == expected and 30 <= len(expected) <= 90
    after = set(pass_b_sample(project) or ())
    assert after - before_sample == set(expected)
    assert events[-1].actor.kind == "system"
    # Nothing else in pass A or B changed.
    assert len(_of_type(project, "screening.pass_opened")) == 1
    assert _of_type(project, "screening.decision_recorded") == []


def test_no_extension_when_pass_b_covers_all(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources, dual_sample=1.0)
    _cycle(project, 20)
    assert _of_type(project, "screening.sample_extended") == []


def test_extension_is_public_and_returns_added(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    summary = watch_run(
        project,
        sources=adapters(ScriptedSource(by_text({"attention": [filler(50)]}))),
        trigger="scheduler",
    )
    assert summary is not None
    added = extend_sample(project, project.system_actor(), random_seed=5)
    assert set(added) <= set(summary.new_work_ids)
    assert extend_sample(project, project.system_actor(), random_seed=5) == ()


def test_existing_sessions_receive_watch_works(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    screen_next(project, agent, PassLabel.B)
    summary = _cycle(project)
    screen_next(project, agent, PassLabel.B)
    queued: set[str] = set()
    for event in _of_type(project, "task.created"):
        assert event.input_blob is not None
        content: Any = project.blobs.get_json(event.input_blob)
        queued.update(r["work_id"] for r in content.get("records", ()))
    added = set(pass_b_sample(project) or ()) & set(summary.new_work_ids)
    assert added and added <= queued


def test_calibration_not_required_again_after_cycle(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready(project, agent, human, mock_sources)
    before = calibration_status(project)
    _cycle(project)
    assert calibration_status(project).model_dump() == before.model_dump()
    assert len(_of_type(project, "calibration.drawn")) == 1


def test_new_session_joins_existing_pass_under_decision_37(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _ready(project, agent, human, mock_sources)
    screen_next(project, agent, PassLabel.A)
    _cycle(project)
    # The same model on the other pass is refused; a different model joins and is served.
    with pytest.raises(FactoryValidationError):
        screen_next(project, agent_other, PassLabel.B)
    third = agent_other.model_copy(update={"model": "claude-sonnet-5-5"})
    screen_next(project, third, PassLabel.B)
    assert len(_of_type(project, "screening.pass_joined")) == 2
