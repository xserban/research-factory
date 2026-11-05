"""One writer per hosted project (slice 5 ruling 2): `project.hosted` and the host check."""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.index.index import OMITTED_WHEN_EMPTY
from factory.model.hosting import ProjectHosted
from factory.model.question import GoalStated
from factory.services.context import Project, open_project
from factory.services.hosting import current_host, host_project
from tests.helpers import S2, SESSION, T0
from tests.test_forged_events import fold_state, folds, inert
from tests.test_old_log_replay import BASE_STATE_HASH, FIXTURE


def goal(project: Project) -> Event:
    return project.events.make("question.goal_stated", GoalStated(text="g"), project.human_actor())


def as_host(settings: Settings, host_id: str | None, clock: FixedClock) -> Project:
    configured = settings.model_copy(update={"host_id": host_id})
    return open_project(configured, "demo", session=S2, clock=clock)


def sizes(project: Project) -> dict[str, int]:
    return {str(path): path.stat().st_size for path in project.paths.events_dir.rglob("*.jsonl")}


# --- Settings.host_id ---


def test_host_id_from_argument_env_then_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACTORY_HOST_ID", raising=False)
    assert Settings.load(root=tmp_path, user="obd").host_id is None
    (tmp_path / ".server").mkdir()
    (tmp_path / ".server" / "host_id").write_text("from-file\n")
    assert Settings.load(root=tmp_path, user="obd").host_id == "from-file"
    monkeypatch.setenv("FACTORY_HOST_ID", "from-env")
    assert Settings.load(root=tmp_path, user="obd").host_id == "from-env"
    assert Settings.load(root=tmp_path, user="obd", host_id="given").host_id == "given"


@pytest.mark.parametrize("source", ["argument", "env", "file"])
def test_a_malformed_host_id_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    monkeypatch.delenv("FACTORY_HOST_ID", raising=False)
    given = None
    if source == "argument":
        given = "Not A Host"
    elif source == "env":
        monkeypatch.setenv("FACTORY_HOST_ID", "Not A Host")
    else:
        (tmp_path / ".server").mkdir()
        (tmp_path / ".server" / "host_id").write_text("Not A Host\n")
    with pytest.raises(FactoryValidationError) as caught:
        Settings.load(root=tmp_path, user="obd", host_id=given)
    assert caught.value.issues[0].field == "host_id"


# --- Unhosted projects ---


def test_unhosted_project_unchanged(tmp_path: Path) -> None:
    """A `host_id` has no effect while no `project.hosted` exists; old logs hash the same."""
    shutil.copytree(FIXTURE, tmp_path / "projects" / "demo" / "events")
    settings = Settings(root=tmp_path, user="obd", host_id="somewhere")
    project = open_project(settings, "demo", session=SESSION, clock=FixedClock(T0))
    assert project.index.rebuild() == BASE_STATE_HASH
    assert not project.is_hosted()
    assert current_host(project) is None
    project.record([goal(project)])  # no guard effect


def test_project_hosts_leaves_no_trace_while_empty() -> None:
    assert "project_hosts" in OMITTED_WHEN_EMPTY


# --- Hosting ---


def test_host_records_event_and_previous_host(project: Project) -> None:
    event_id = host_project(project, project.human_actor(), "lab1")
    assert current_host(project) == "lab1"
    assert project.is_hosted()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT event_id, host_id, previous_host FROM project_hosts")
        ).all()
    assert [tuple(row) for row in rows] == [(event_id, "lab1", None)]


def test_rehost_names_previous(settings: Settings, project: Project, clock: FixedClock) -> None:
    host_project(project, project.human_actor(), "lab1")
    on_lab1 = as_host(settings, "lab1", clock)
    host_project(on_lab1, on_lab1.human_actor(), "lab2")
    assert current_host(project) == "lab2"
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT host_id, previous_host FROM project_hosts ORDER BY event_id")
        ).all()
    assert [tuple(row) for row in rows] == [("lab1", None), ("lab2", "lab1")]


def test_hosting_twice_on_the_same_host_is_refused(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    on_lab1 = as_host(settings, "lab1", clock)
    before = sizes(on_lab1)
    with pytest.raises(FactoryValidationError) as caught:
        host_project(on_lab1, on_lab1.human_actor(), "lab1")
    assert caught.value.issues[0].field == "host_id"
    assert sizes(on_lab1) == before


def test_a_malformed_host_is_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        host_project(project, project.human_actor(), "Not A Host")
    assert caught.value.issues[0].field == "host_id"
    assert current_host(project) is None


@pytest.mark.parametrize("fixture", ["agent", "system"])
def test_only_a_person_hosts_a_project(
    project: Project, fixture: str, request: pytest.FixtureRequest
) -> None:
    actor = request.getfixturevalue("agent") if fixture == "agent" else project.system_actor()
    with pytest.raises(FactoryValidationError) as caught:
        host_project(project, actor, "lab1")
    assert caught.value.issues[0].field == "actor"
    assert current_host(project) is None


# --- The host check ---


def test_foreign_host_cannot_append(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    laptop = as_host(settings, "laptop", clock)
    before = sizes(laptop)
    with pytest.raises(FactoryValidationError) as caught:
        laptop.record([goal(laptop)])
    assert caught.value.issues[0].field == "host"
    assert "lab1" in caught.value.issues[0].reason
    assert "host-mismatch" in caught.value.issues[0].reason
    assert sizes(laptop) == before


def test_a_machine_without_a_host_id_cannot_append(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    personal = as_host(settings, None, clock)
    with pytest.raises(FactoryValidationError):
        personal.record([goal(personal)])


def test_a_direct_append_meets_the_guard_too(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    laptop = as_host(settings, "laptop", clock)
    with pytest.raises(FactoryValidationError):
        laptop.writer.append([goal(laptop)])


def test_the_guard_sees_a_hosting_another_process_appended(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    laptop = as_host(settings, "laptop", clock)
    laptop.index.sync()
    host_project(project, project.human_actor(), "lab1")
    with pytest.raises(FactoryValidationError):
        laptop.record([goal(laptop)])


def test_the_hosting_host_appends(settings: Settings, project: Project, clock: FixedClock) -> None:
    host_project(project, project.human_actor(), "lab1")
    server = as_host(settings, "lab1", clock)
    with server.writing():
        server.record([goal(server)])


def test_a_foreign_host_cannot_take_a_project_over(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    laptop = as_host(settings, "laptop", clock)
    with pytest.raises(FactoryValidationError):
        host_project(laptop, laptop.human_actor(), "laptop")
    assert current_host(project) == "lab1"


def test_rehosted_project_refuses_the_old_host(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    on_lab1 = as_host(settings, "lab1", clock)
    host_project(on_lab1, on_lab1.human_actor(), "lab2")
    with pytest.raises(FactoryValidationError):
        on_lab1.record([goal(on_lab1)])


# --- Hand-written events ---


def test_only_a_persons_hosting_folds(project: Project, agent: Actor) -> None:
    inert(project, "project.hosted", ProjectHosted(host_id="lab1"), agent)
    inert(project, "project.hosted", ProjectHosted(host_id="lab1"), project.system_actor())
    assert current_host(project) is None
    project.record([goal(project)])
    folds(project, "project.hosted", ProjectHosted(host_id="lab1"), project.human_actor())
    assert current_host(project) == "lab1"


def test_a_hosting_that_misstates_the_previous_host_changes_nothing(project: Project) -> None:
    human = project.human_actor()
    inert(project, "project.hosted", ProjectHosted(host_id="lab1", previous_host="lab0"), human)
    assert current_host(project) is None


def test_a_hosting_with_no_change_changes_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    server = as_host(settings, "lab1", clock)
    human = server.human_actor()
    inert(server, "project.hosted", ProjectHosted(host_id="lab1", previous_host="lab1"), human)
    inert(server, "project.hosted", ProjectHosted(host_id="lab2"), human)
    assert current_host(project) == "lab1"


def test_a_malformed_hosting_line_folds_to_nothing(project: Project) -> None:
    """A line no service writes: the projector stays total and a rebuild agrees."""
    project.index.sync()
    before = fold_state(project)
    good = project.events.make(
        "project.hosted", ProjectHosted(host_id="lab1"), project.human_actor()
    )
    line = json.loads(good.to_line())
    line["payload"] = {"host_id": "Not A Host", "extra": 1}
    path = project.paths.events_dir / good.actor.id / f"{good.actor.session}.jsonl"
    with path.open("ab") as handle:
        handle.write(json.dumps(line).encode() + b"\n")
    assert fold_state(project) == before
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    assert current_host(project) is None


def test_hosting_survives_a_rebuild(project: Project) -> None:
    host_project(project, project.human_actor(), "lab1")
    synced = project.index.state_hash()
    assert project.index.rebuild() == synced
    assert current_host(project) == "lab1"
