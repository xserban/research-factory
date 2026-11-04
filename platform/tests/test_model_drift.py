"""Calibration model drift: a model no calibration of the pass recorded (Task 6, ruling 22)."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.project import RigorMode
from factory.model.screening import PassLabel
from factory.services.calibration import calibrated_models
from factory.services.check import _findings_as
from factory.services.context import Project
from factory.services.screening import join_pass
from factory.services.watch import watch_run
from tests.helpers import SourcesFor
from tests.living_helpers import filler, screening_watch_setup, start_screening
from tests.test_check import _calibrate
from tests.watch_helpers import ScriptedSource, adapters, by_text

NEW_MODEL = "claude-sonnet-5-5"


def _calibrated(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    screening_watch_setup(project, agent, human, mock_sources)
    protocol_id, _ = start_screening(project, agent)
    _calibrate(project, agent, human, protocol_id)
    return protocol_id


def _cycle(project: Project) -> None:
    source = ScriptedSource(by_text({"attention": [filler(3)]}))
    assert watch_run(project, sources=adapters(source), trigger="scheduler") is not None


def _drift(project: Project, mode: RigorMode) -> list[str]:
    return [f.severity for f in _findings_as(project, mode) if f.code == "calibration-model-drift"]


def test_calibrated_models_of_a_pass(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    screening_watch_setup(project, agent, human, mock_sources)
    protocol_id, _ = start_screening(project, agent)
    assert calibrated_models(project, PassLabel.A) == set()
    _calibrate(project, agent, human, protocol_id)
    assert calibrated_models(project, PassLabel.A) == {agent.model}
    assert calibrated_models(project, PassLabel.B) == {agent.model}


def test_model_drift_by_mode(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibrated(project, agent, human, mock_sources)
    drifter = agent_other.model_copy(update={"model": NEW_MODEL})
    # Before any cycle a new model joins freely (it will calibrate), and nothing is reported.
    _cycle(project)
    assert _drift(project, RigorMode.PILOT) == []

    # systematic: the join is refused, with nothing written.
    monkeypatch.setattr("factory.services.screening._rigor_mode", lambda _p: RigorMode.SYSTEMATIC)
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as exc:
        join_pass(project, drifter, PassLabel.A)
    assert [(i.field, i.reason) for i in exc.value.issues] == [
        ("model", "not calibrated for this pass")
    ]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    join_pass(project, agent, PassLabel.A)  # the calibrated model joins

    # pilot: the join is allowed and only `check` warns.
    monkeypatch.undo()
    join_pass(project, drifter, PassLabel.B)
    assert _drift(project, RigorMode.PILOT) == ["warning"]
    assert _drift(project, RigorMode.SYSTEMATIC) == ["error"]
    assert _drift(project, RigorMode.EXPLORATORY) == []


def test_no_drift_finding_for_a_calibrated_model(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _calibrated(project, agent, human, mock_sources)
    join_pass(project, agent, PassLabel.A)
    _cycle(project)
    assert _drift(project, RigorMode.SYSTEMATIC) == []
