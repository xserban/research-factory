"""The gate-policy folds see the autonomy level (lane L14) without a table or column: the level is
read from the first `project.created` event. Under `attended`, or while `AUTONOMOUS_FLOOR` is
empty (as shipped), the policy is today's."""

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.index.default import default_projection
from factory.index.hypotheses import policy_of
from factory.index.levels import attach_level_reader
from factory.modules import autonomy
from factory.modules.contract import PolicyKind
from factory.modules.presets import AGENT
from factory.services.context import Project
from factory.services.project import init_project
from tests.helpers import SESSION

GATE = "hypotheses.lead_decide"
"""`human` in a systematic project; `AUTONOMOUS_FLOOR` can lower it."""


def _kind(project: Project, *, with_reader: bool = True) -> PolicyKind:
    projection = default_projection()
    if with_reader:
        attach_level_reader(projection, project.paths.events_dir, project.catalog)
    tables = projection.metadata.tables
    project.index.sync()
    with project.index.connect() as conn:
        return policy_of(conn, tables["protocols"], tables["project"], GATE)


def _project(settings: Settings, clock: FixedClock, level: str) -> Project:
    return init_project(
        settings, level, "systematic", session=SESSION, clock=clock, autonomy_level=level
    )


def test_shipped_floor_is_empty() -> None:
    assert dict(autonomy.AUTONOMOUS_FLOOR) == {}


@pytest.mark.parametrize("level", ["attended", "supervised", "autonomous"])
def test_empty_floor_changes_nothing(settings: Settings, clock: FixedClock, level: str) -> None:
    project = _project(settings, clock, level)
    assert _kind(project) is PolicyKind.HUMAN
    assert _kind(project, with_reader=False) is PolicyKind.HUMAN


def test_autonomous_fold_respects_a_non_empty_floor(
    settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autonomy, "AUTONOMOUS_FLOOR", {GATE: AGENT})
    autonomous = _project(settings, clock, "autonomous")
    assert _kind(autonomous) is PolicyKind.AGENT


def test_attended_and_supervised_ignore_the_floor(
    settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autonomy, "AUTONOMOUS_FLOOR", {GATE: AGENT})
    for level in ("attended", "supervised"):
        assert _kind(_project(settings, clock, level)) is PolicyKind.HUMAN


def test_a_fold_without_a_reader_is_attended(
    settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autonomy, "AUTONOMOUS_FLOOR", {GATE: AGENT})
    assert _kind(_project(settings, clock, "autonomous"), with_reader=False) is PolicyKind.HUMAN
