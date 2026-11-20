"""One writer per hosted project (slice 5 ruling 2): `project.hosted` and the host check."""

import json
import shutil
import subprocess
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
from factory.services.check import check
from factory.services.context import Project, open_project
from factory.services.hosting import current_host, host_project
from factory.services.server_check import linux_filesystem, mac_filesystem, server_check
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
    with server.writing():  # a hosted project takes only what is minted under the lock
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


# --- `host-mismatch` ---


def append_goal(project: Project) -> None:
    with project.writing():
        project.record([goal(project)])


def commit_as(root: Path, author: str) -> None:
    identity = ["-c", f"user.name={author}", "-c", "user.email=a@x"]
    subprocess.run(["git", "-C", str(root), "add", "projects"], check=True)
    subprocess.run(["git", "-C", str(root), *identity, "commit", "-qm", "c"], check=True)


def codes(project: Project) -> set[str]:
    return {finding.code for finding in check(project).findings}


@pytest.fixture
def repo_server(settings: Settings, project: Project, clock: FixedClock) -> Project:
    """A hosted project in a git root, its history so far committed by the host."""
    (settings.root / ".gitignore").write_text("projects/*/.index/\n")
    subprocess.run(["git", "init", "-q", str(settings.root)], check=True)
    host_project(project, project.human_actor(), "lab1")
    commit_as(settings.root, "factory-server lab1")
    return as_host(settings, "lab1", clock)


def test_host_mismatch_flags_foreign_commit(repo_server: Project) -> None:
    append_goal(repo_server)
    commit_as(repo_server.settings.root, "someone-else")
    report = check(repo_server)
    hits = [f for f in report.findings if f.code == "host-mismatch"]
    assert len(hits) == 1 and hits[0].severity == "error"
    assert "someone-else" in hits[0].message and "lab1" in hits[0].message


def test_the_hosts_own_commit_is_clean(repo_server: Project) -> None:
    append_goal(repo_server)
    commit_as(repo_server.settings.root, "factory-server lab1")
    assert "host-mismatch" not in codes(repo_server)


def test_an_uncommitted_file_is_not_flagged(repo_server: Project) -> None:
    append_goal(repo_server)
    assert "host-mismatch" not in codes(repo_server)


def test_a_file_from_before_hosting_is_not_flagged(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    subprocess.run(["git", "init", "-q", str(settings.root)], check=True)
    (settings.root / ".gitignore").write_text("projects/*/.index/\n")
    commit_as(settings.root, "a-researcher")
    host_project(project, project.human_actor(), "lab1")
    assert "host-mismatch" not in codes(as_host(settings, "lab1", clock))


def test_each_period_answers_to_its_own_host(repo_server: Project, clock: FixedClock) -> None:
    append_goal(repo_server)
    commit_as(repo_server.settings.root, "factory-server lab1")
    host_project(repo_server, repo_server.human_actor(), "lab2")
    commit_as(repo_server.settings.root, "factory-server lab1")
    assert "host-mismatch" not in codes(repo_server)


def test_without_git_the_check_says_it_was_skipped(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    host_project(project, project.human_actor(), "lab1")
    report = check(as_host(settings, "lab1", clock))
    hits = [f for f in report.findings if f.code == "host-mismatch-unchecked"]
    assert len(hits) == 1 and hits[0].severity == "warning" and report.ok is not None


def test_an_unhosted_project_runs_no_git(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("git was run")

    monkeypatch.setattr("factory.services.hosting.git", refuse)
    assert not {"host-mismatch", "host-mismatch-unchecked"} & codes(project)


# --- `factory server check` ---


def fit_root(root: Path) -> None:
    (root / ".gitignore").write_text("library/\n.index/\n.server/\n")


def test_a_fit_root_passes(tmp_path: Path) -> None:
    fit_root(tmp_path)
    assert server_check(Settings(root=tmp_path, user="obd")) == []


def test_server_check_flags_missing_gitignore(tmp_path: Path) -> None:
    issues = server_check(Settings(root=tmp_path, user="obd"))
    assert sum(issue.field == "gitignore" for issue in issues) == 3


def test_server_check_flock_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fit_root(tmp_path)
    monkeypatch.setattr("factory.services.server_check._PROBE", "import sys; sys.exit(1)")
    issues = server_check(Settings(root=tmp_path, user="obd"))
    assert [issue.field for issue in issues] == ["lock"]


def test_the_deepest_mount_decides() -> None:
    mounts = "/dev/a / ext4 rw 0 0\nsrv:/x /mnt/lab nfs4 rw 0 0\n"
    assert linux_filesystem(Path("/mnt/lab/root"), mounts) == "nfs4"
    assert linux_filesystem(Path("/home/user"), mounts) == "ext4"


def test_the_mac_mount_table() -> None:
    mounts = "/dev/disk1 on / (apfs, local)\nsrv:/x on /Volumes/lab (nfs, nodev)\n"
    assert mac_filesystem(Path("/Volumes/lab/root"), mounts) == "nfs"
    assert mac_filesystem(Path("/Users/obd"), mounts) == "apfs"
