import shutil
from datetime import timedelta

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError
from factory.events.envelope import Actor
from factory.model.project import ProjectCreated, RigorMode
from factory.services.context import Project, list_projects, open_project
from factory.services.project import init_project, project_status
from factory.services.tasks import TaskCounts, TaskSpec, claim_next, create_tasks
from tests.helpers import SESSION


def test_init_creates_layout_and_one_event(settings: Settings, clock: FixedClock) -> None:
    p = init_project(settings, "linear-attention-vision", "pilot", session=SESSION, clock=clock)
    assert (p.paths.dir / "events" / "obd" / f"{SESSION}.jsonl").exists()
    st = project_status(p)
    assert (st.slug, st.rigor_mode, st.events_total) == (
        "linear-attention-vision",
        RigorMode.PILOT,
        1,
    )
    assert st.events_by_type == {"project.created": 1}


@pytest.mark.parametrize("slug", ["Bad", "a--b", "-a", "", "a" * 65, "../x"])
def test_invalid_slug_creates_nothing(settings: Settings, clock: FixedClock, slug: str) -> None:
    with pytest.raises(FactoryValidationError) as err:
        init_project(settings, slug, "pilot", session=SESSION, clock=clock)
    assert err.value.issues[0].field == "slug"
    assert not (settings.root / "projects").exists()


def test_max_length_slug_is_accepted(settings: Settings, clock: FixedClock) -> None:
    p = init_project(settings, "a" * 64, "exploratory", session=SESSION, clock=clock)
    assert project_status(p).slug == "a" * 64


def test_invalid_mode_is_rejected(settings: Settings, clock: FixedClock) -> None:
    with pytest.raises(FactoryValidationError) as err:
        init_project(settings, "demo", "rigorous", session=SESSION, clock=clock)
    assert [issue.field for issue in err.value.issues] == ["rigor_mode"]
    assert not (settings.root / "projects").exists()


def test_duplicate_init_is_refused(settings: Settings, clock: FixedClock) -> None:
    init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    with pytest.raises(FactoryValidationError) as err:
        init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    assert err.value.issues[0].field == "slug"
    assert err.value.issues[0].reason == "project already exists"


def test_open_unknown_project_raises(settings: Settings, clock: FixedClock) -> None:
    with pytest.raises(ProjectNotFoundError):
        open_project(settings, "missing", session=SESSION, clock=clock)


def test_open_existing_project(project: Project, settings: Settings, clock: FixedClock) -> None:
    reopened = open_project(settings, "demo", session=SESSION, clock=clock)
    assert reopened.paths == project.paths
    assert project_status(reopened).events_total == 1


def test_list_projects(settings: Settings, clock: FixedClock) -> None:
    assert list_projects(settings) == []
    init_project(settings, "beta", "pilot", session=SESSION, clock=clock)
    init_project(settings, "alpha", "pilot", session=SESSION, clock=clock)
    assert list_projects(settings) == ["alpha", "beta"]


def test_status_survives_index_deletion(project: Project) -> None:
    before = project_status(project)
    shutil.rmtree(project.paths.dir / ".index")
    assert project_status(project) == before


def test_status_reports_task_counts(project: Project, agent: Actor) -> None:
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("demo", 2)])
    assert claim_next(project, agent, "demo") is not None
    assert project_status(project).tasks == TaskCounts(open=1, claimed=1, expired=0, completed=0)


def test_duplicate_project_created_does_not_brick_the_index(
    project: Project, project_other_session: Project, clock: FixedClock
) -> None:
    clock.advance(timedelta(milliseconds=1))
    project_other_session.record(
        [
            project_other_session.events.make(
                "project.created",
                ProjectCreated(slug="demo", rigor_mode=RigorMode.EXPLORATORY),
                project_other_session.human_actor(),
            )
        ]
    )
    project.index.sync()
    assert project.index.state_hash() == project.index.rebuild()
    status = project_status(project)
    assert status.rigor_mode == RigorMode.PILOT
    assert status.events_total == 2


def test_project_row_is_keyed_on_the_event_project(project: Project) -> None:
    other = project.events.make(
        "project.created",
        ProjectCreated(slug="elsewhere", rigor_mode=RigorMode.PILOT),
        project.human_actor(),
    )
    project.writer.append([other])
    project.index.rebuild()
    assert project_status(project).slug == "demo"
    with project.index.connect() as conn:
        slugs = conn.execute(text("SELECT slug FROM project")).scalars().all()
    assert slugs == ["demo"]


def test_failed_init_removes_its_directory_and_can_be_retried(
    settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: Project, events: object) -> None:
        raise RuntimeError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(Project, "record", boom)
        with pytest.raises(RuntimeError):
            init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
        assert not (settings.root / "projects" / "demo").exists()
    assert project_status(init_project(settings, "demo", "pilot", session=SESSION, clock=clock))
