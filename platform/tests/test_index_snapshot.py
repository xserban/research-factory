"""`Index.snapshot()`: one shared hold for a read-only view (slice 8, I3 fix)."""

from pathlib import Path

import pytest

from factory.clock import SystemClock
from factory.config import Settings
from factory.model.identity import IdGenerator
from factory.services.project import init_project
from factory.services.tasks import TaskSpec, create_tasks


def _project(tmp_path: Path):  # type: ignore[no-untyped-def]
    clock = SystemClock()
    settings = Settings(root=tmp_path, user="obd")
    return init_project(settings, "demo", "pilot", session=IdGenerator(clock).ulid(), clock=clock)


def test_snapshot_syncs_on_entry_and_nested_sync_applies_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
    before = project.index.last_event_id()
    with project.index.snapshot():
        assert project.index.sync().applied == 0
        with project.index.connect() as conn:
            assert conn is not None
    assert project.index.last_event_id() == before


def test_exclusive_is_refused_inside_a_snapshot(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with project.index.snapshot(), pytest.raises(RuntimeError):
        with project.index.exclusive():
            pass


def test_snapshot_is_reentrant_and_sync_works_after_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with project.index.snapshot(), project.index.snapshot():
        pass
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 2})])
    assert project.index.sync().applied >= 0
