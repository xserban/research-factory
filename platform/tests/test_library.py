import subprocess
from pathlib import Path

from factory.services.context import Project

REPO_GITIGNORE = Path(__file__).resolve().parents[2] / ".gitignore"


def test_library_lives_under_project_library(project: Project) -> None:
    ref = project.library.put(b"%PDF-1.4 x")
    assert project.library.path(ref).is_relative_to(project.paths.dir / "library" / "sha256")


def test_library_paths_are_git_ignored(tmp_path: Path) -> None:
    # AC 15: the repository .gitignore keeps the project-local library out of git, while the
    # event-referenced blob store stays tracked.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_bytes(REPO_GITIGNORE.read_bytes())

    digest = "ab" + "c" * 62
    library_file = repo / "projects" / "demo" / "library" / "sha256" / "ab" / ("c" * 62)
    blob_file = repo / "projects" / "demo" / "blobs" / "sha256" / "ab" / ("c" * 62)
    for target in (library_file, blob_file):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(digest.encode())

    library_rel = library_file.relative_to(repo).as_posix()
    blob_rel = blob_file.relative_to(repo).as_posix()
    library_ignored = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", library_rel], check=False
    )
    blob_ignored = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", blob_rel], check=False
    )
    assert library_ignored.returncode == 0
    assert blob_ignored.returncode == 1
