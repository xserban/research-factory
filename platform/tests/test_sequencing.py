"""Event order equals append order (slice 5 ruling 3): IDs are minted under the project write lock.

`Project.writing()` holds the lock, syncs and floors the generator at the last applied event, so a
session with a fresh `IdGenerator` or a slower clock still mints above every event in the log.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Event
from factory.model.identity import IdGenerator
from factory.model.question import GoalStated
from factory.services.context import Project, open_project
from tests.helpers import S2, T0


def goal(project: Project) -> Event:
    return project.events.make("question.goal_stated", GoalStated(text="g"), project.human_actor())


def test_floor_makes_next_id_greater() -> None:
    ids = IdGenerator(FixedClock(T0 - timedelta(days=20000)))
    ids.floor("01KZZZZZZZZZZZZZZZZZZZZZZZ")
    assert ids.ulid() > "01KZZZZZZZZZZZZZZZZZZZZZZZ"


def test_floor_never_lowers_the_generator() -> None:
    ids = IdGenerator(FixedClock(T0))
    first = ids.ulid()
    ids.floor("00000000000000000000000000")
    assert ids.ulid() > first


def test_floor_refuses_what_is_not_a_ulid() -> None:
    with pytest.raises(ValueError):
        IdGenerator(FixedClock(T0)).floor("ev_not-a-ulid")


def test_writing_floors_ids_across_processes(
    project: Project, settings: Settings, clock: FixedClock
) -> None:
    behind = open_project(settings, "demo", session=S2, clock=FixedClock(T0 - timedelta(seconds=5)))
    with project.writing():
        last = goal(project)
        project.record([last])
    with behind.writing():
        minted = goal(behind)
    assert minted.id > last.id


def test_the_index_lock_floors_like_writing(
    project: Project, settings: Settings, clock: FixedClock
) -> None:
    """The services take `index.exclusive()`: it is the same context as `writing()`."""
    behind = open_project(settings, "demo", session=S2, clock=FixedClock(T0 - timedelta(seconds=5)))
    with project.index.exclusive():
        last = goal(project)
        project.record([last])
    with behind.index.exclusive():
        minted = goal(behind)
    assert minted.id > last.id


def test_writing_sees_an_event_another_session_appended(
    project: Project, settings: Settings
) -> None:
    """The floor comes from the log, not from an index synced earlier."""
    behind = open_project(settings, "demo", session=S2, clock=FixedClock(T0 - timedelta(seconds=5)))
    behind.index.sync()
    last = goal(project)
    project.writer.append([last])  # on disk, not yet folded by anyone
    with behind.writing():
        assert goal(behind).id > last.id


def test_writing_is_reentrant(project: Project) -> None:
    with project.writing(), project.writing():
        project.record([goal(project)])


def test_a_new_project_can_be_written_inside_writing(tmp_path: Path, settings: Settings) -> None:
    project = open_or_init(settings)
    with project.writing():
        assert project.index.last_event_id() is not None


def open_or_init(settings: Settings) -> Project:
    from factory.services.project import init_project

    return init_project(settings, "fresh", "pilot", session=S2, clock=FixedClock(T0))
