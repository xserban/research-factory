"""`factory commit`: the server commits event files and text blobs, and nothing else."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.model.question import GoalStated
from factory.services.commit import PUSH_REMOTES_FILE, commit_hosted, is_private
from factory.services.context import Project, open_project
from factory.services.hosting import host_project
from factory.services.project import init_project
from tests.helpers import S2, SESSION, T0

GITIGNORE = "library/\n.index/\n.server/\nprojects/*/.index/\nprojects/*/library/\n"


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=someone", "-c", "user.email=s@x", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


@pytest.fixture
def server(tmp_path: Path) -> Settings:
    """A git root with one project hosted here and the base commit made by hand."""
    (tmp_path / ".gitignore").write_text(GITIGNORE)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".gitignore")
    git(tmp_path, "commit", "-qm", "base")
    return Settings(root=tmp_path, user="obd", host_id="lab1")


@pytest.fixture
def hosted(server: Settings) -> Project:
    project = init_project(server, "demo", "pilot", session=SESSION, clock=FixedClock(T0))
    host_project(project, project.human_actor(), "lab1")
    return project


def allow(root: Path, url: str) -> None:
    (root / ".server").mkdir(exist_ok=True)
    (root / PUSH_REMOTES_FILE).write_text(f"# private remotes\n{url}\n")


def tracked(root: Path) -> set[str]:
    return set(git(root, "ls-files").split())


def commits(root: Path) -> int:
    return int(git(root, "rev-list", "--count", "HEAD"))


def test_commit_adds_only_events_and_text_blobs(server: Settings, hosted: Project) -> None:
    text_ref = hosted.blobs.put_json({"a": 1})
    pdf_ref = hosted.blobs.put(b"%PDF-1.7\n\xff\xfe\x00binary")
    hosted.library.put(b"literature")
    (server.root / "notes.txt").write_text("not the factory's")
    report = commit_hosted(server, sign=False, push=None)

    files = tracked(server.root)
    events = {
        p.relative_to(server.root).as_posix() for p in hosted.paths.events_dir.rglob("*.jsonl")
    }
    assert events and events <= files
    assert hosted.blobs.path(text_ref).relative_to(server.root).as_posix() in files
    assert hosted.blobs.path(pdf_ref).relative_to(server.root).as_posix() not in files
    assert files == {
        ".gitignore",
        *events,
        hosted.blobs.path(text_ref).relative_to(server.root).as_posix(),
    }
    assert report.projects == {"demo": len(files) - 1}
    assert report.commit == git(server.root, "rev-parse", "HEAD").strip()
    assert report.pushed is False


def test_commit_refuses_library_paths(server: Settings, hosted: Project) -> None:
    """Review focus 4: `.gitignore` gone, a library file visible: refused, nothing committed."""
    (server.root / ".gitignore").unlink()
    (server.root / "library").mkdir()
    (server.root / "library" / "paper.pdf").write_bytes(b"literature")
    before = commits(server.root)
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(server, sign=False, push=None)
    assert caught.value.issues[0].field == "paths"
    assert "library/paper.pdf" in caught.value.issues[0].reason
    assert commits(server.root) == before
    assert git(server.root, "diff", "--cached", "--name-only") == ""


def test_commit_refuses_a_library_path_someone_staged(server: Settings, hosted: Project) -> None:
    hidden = server.root / "projects" / "demo" / "library" / "paper.pdf"
    hidden.parent.mkdir(parents=True)
    hidden.write_bytes(b"literature")
    git(server.root, "add", "-f", "projects/demo/library/paper.pdf")
    before = commits(server.root)
    with pytest.raises(FactoryValidationError):
        commit_hosted(server, sign=False, push=None)
    assert commits(server.root) == before


@pytest.mark.parametrize(
    ("path", "private"),
    [
        ("library/sha256/ab/cd", True),
        (".index/x", True),
        (".server/credentials.sqlite", True),
        ("projects/demo/library/x", True),
        ("projects/demo/.index/factory.sqlite", True),
        ("lab/.index/lab.sqlite", True),
        ("projects/demo/events/library/S.jsonl", False),
        ("projects/demo/blobs/sha256/ab/cd", False),
        ("docs/library/x", False),
    ],
)
def test_private_paths(path: str, private: bool) -> None:
    assert is_private(path) is private


def test_something_else_staged_stays_out_of_the_commit(server: Settings, hosted: Project) -> None:
    (server.root / "notes.txt").write_text("by hand")
    git(server.root, "add", "notes.txt")
    commit_hosted(server, sign=False, push=None)
    assert "notes.txt" not in git(server.root, "show", "--name-only", "--format=", "HEAD")


def test_commit_is_noop_without_changes(server: Settings, hosted: Project) -> None:
    commit_hosted(server, sign=False, push=None)
    before = commits(server.root)
    report = commit_hosted(server, sign=False, push=None)
    assert report.commit is None and report.projects == {}
    assert commits(server.root) == before


def test_commit_author_is_factory_server(server: Settings, hosted: Project) -> None:
    commit_hosted(server, sign=False, push=None)
    assert git(server.root, "log", "-1", "--format=%an|%cn").strip() == (
        "factory-server lab1|factory-server lab1"
    )


def test_a_project_hosted_elsewhere_or_unhosted_is_left_alone(server: Settings) -> None:
    clock = FixedClock(T0)
    plain = init_project(server, "plain", "pilot", session=SESSION, clock=clock)
    elsewhere = init_project(server, "elsewhere", "pilot", session=S2, clock=clock)
    host_project(elsewhere, elsewhere.human_actor(), "lab2")
    report = commit_hosted(server, sign=False, push=None)
    assert report.commit is None
    assert tracked(server.root) == {".gitignore"}
    assert plain.paths.events_dir.is_dir()


def test_a_deleted_event_file_refuses_the_job(server: Settings, hosted: Project) -> None:
    commit_hosted(server, sign=False, push=None)
    victim = next(hosted.paths.events_dir.rglob("*.jsonl"))
    victim.unlink()
    before = commits(server.root)
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(server, sign=False, push=None)
    assert caught.value.issues[0].field == "history"
    assert commits(server.root) == before
    assert victim.relative_to(server.root).as_posix() in tracked(server.root)


def test_a_machine_without_a_host_id_is_refused(server: Settings, hosted: Project) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(server.model_copy(update={"host_id": None}), sign=False, push=None)
    assert caught.value.issues[0].field == "host_id"


def test_a_root_that_is_no_repository_is_refused(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, user="obd", host_id="lab1")
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(settings, sign=False, push=None)
    assert caught.value.issues[0].field == "root"


def test_a_subdirectory_of_a_repository_is_refused(server: Settings) -> None:
    inner = server.root / "inner"
    inner.mkdir()
    settings = Settings(root=inner, user="obd", host_id="lab1")
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(settings, sign=False, push=None)
    assert caught.value.issues[0].field == "root"


@pytest.mark.parametrize("remote", ["--upload-pack=evil", "-x", "a b", ""])
def test_a_remote_that_could_be_an_option_is_refused(
    server: Settings, hosted: Project, remote: str
) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(server, sign=False, push=remote)
    assert caught.value.issues[0].field == "push"


def test_push_reaches_the_remote(
    server: Settings, hosted: Project, tmp_path_factory: pytest.TempPathFactory
) -> None:
    remote = tmp_path_factory.mktemp("remote")
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(server.root, "remote", "add", "origin", str(remote))
    allow(server.root, str(remote))
    report = commit_hosted(server, sign=False, push="origin")
    assert report.pushed is True
    head = git(server.root, "rev-parse", "HEAD").strip()
    assert head in git(remote, "rev-parse", "--all")


def test_a_failed_push_keeps_the_commit(server: Settings, hosted: Project) -> None:
    missing = str(server.root / "no-such-remote")
    git(server.root, "remote", "add", "origin", missing)
    allow(server.root, missing)
    report = commit_hosted(server, sign=False, push="origin")
    assert report.commit is not None and report.pushed is False


def test_a_failed_signature_commits_nothing_and_unstages(server: Settings, hosted: Project) -> None:
    git(server.root, "config", "gpg.program", "/bin/false")
    before = commits(server.root)
    with pytest.raises(FactoryValidationError) as caught:
        commit_hosted(server, sign=True, push=None)
    assert caught.value.issues[0].field == "commit"
    assert commits(server.root) == before
    assert git(server.root, "diff", "--cached", "--name-only") == ""


def test_a_new_event_is_committed_by_the_next_run(server: Settings, hosted: Project) -> None:
    commit_hosted(server, sign=False, push=None)
    project = open_project(server, "demo", session=S2, clock=FixedClock(T0))
    with project.writing():
        project.record(
            [
                project.events.make(
                    "question.goal_stated", GoalStated(text="g"), project.human_actor()
                )
            ]
        )
    report = commit_hosted(server, sign=False, push=None)
    assert report.projects == {"demo": 1}


# --- CLI ---


def test_cli_commit_prints_the_report(server: Settings, hosted: Project) -> None:
    result = CliRunner().invoke(
        app,
        ["--root", str(server.root), "commit", "--no-sign"],
        env={"FACTORY_HOST_ID": "lab1", "FACTORY_USER": "obd"},
    )
    assert result.exit_code == 0, result.output
    assert "demo" in result.output


def test_cli_commit_reports_a_refusal(server: Settings, hosted: Project) -> None:
    (server.root / ".gitignore").unlink()
    (server.root / "library").mkdir()
    (server.root / "library" / "paper.pdf").write_bytes(b"x")
    result = CliRunner().invoke(
        app,
        ["--root", str(server.root), "commit", "--no-sign"],
        env={"FACTORY_HOST_ID": "lab1", "FACTORY_USER": "obd"},
    )
    assert result.exit_code == 1


def test_cli_commit_exits_nonzero_when_the_push_fails(server: Settings, hosted: Project) -> None:
    result = CliRunner().invoke(
        app,
        ["--root", str(server.root), "commit", "--no-sign", "--push", "nowhere"],
        env={"FACTORY_HOST_ID": "lab1", "FACTORY_USER": "obd"},
    )
    assert result.exit_code == 1
