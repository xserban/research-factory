"""The server commit job (slice 5 rulings 4 and 5; `factory commit`).

Commits what the projects hosted here have appended: event files and text blobs, nothing else.
`git` runs with fixed arguments only; paths go through stdin, so no path can act as an option.

Invariants:
- A path under a location that must stay out of git (`library/`, `.index/`, `.server/`, a project's
  library or index) that git can see, staged or untracked, refuses the whole job before anything is
  staged: a missing `.gitignore` stops the job instead of being trusted.
- The commit holds exactly the paths this job staged; anything else staged by hand stays out.
- A file is staged under the project's write lock, so a line half-written never enters history.
- A deletion is never committed: events are append-only.
"""

import re
import subprocess
from pathlib import Path

from factory.clock import SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE, ULID_RE, IdGenerator
from factory.services.context import list_projects, open_project
from factory.services.hosting import current_host, git, server_author

_REMOTE_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_PRIVATE_TOP = frozenset({"library", ".index", ".server"})
_PRIVATE_IN_PROJECT = frozenset({"library", ".index"})
_PATHSPEC_STDIN = ("--pathspec-from-file=-", "--pathspec-file-nul")
_EVENT_FILE_RE = rf"{ACTOR_ID_RE.strip('^$')}/{ULID_RE}\.jsonl"
_BLOB_FILE_RE = r"sha256/[0-9a-f]{2}/[0-9a-f]{62}"


class CommitReport(StrictModel):
    """Files committed per project slug; the commit id, None when there was nothing to commit;
    whether a push was asked for and succeeded."""

    projects: dict[str, int]
    commit: str | None
    pushed: bool


def commit_hosted(settings: Settings, *, sign: bool, push: str | None) -> CommitReport:
    """Commit the new event and text-blob files of every project hosted here, then push."""
    host_id = _require_host(settings)
    if push is not None and re.fullmatch(_REMOTE_RE, push) is None:
        raise FactoryValidationError([ValidationIssue("push", "not a remote name")])
    root = settings.root
    _require_repository(root)
    changes = _changes(root)
    private = sorted(path for path, _ in changes if is_private(path))
    if private:
        listed = ", ".join(private[:5])
        raise FactoryValidationError(
            [ValidationIssue("paths", f"git can see paths that must stay out of it: {listed}")]
        )

    staged: dict[str, list[str]] = {}
    clock = SystemClock()
    session = IdGenerator(clock).ulid()
    for slug in list_projects(settings):
        project = open_project(settings, slug, session=session, clock=clock)
        if current_host(project) != host_id:
            continue
        with project.writing():
            paths = _committable(root, slug, _changes(root))
            if paths:
                _run(root, "add", *_PATHSPEC_STDIN, stdin=_nul_joined(paths))
                staged[slug] = paths

    commit = _commit(root, host_id, staged, sign) if staged else None
    pushed = push is not None and git(root, "push", push, "HEAD").returncode == 0
    return CommitReport(
        projects={slug: len(paths) for slug, paths in staged.items()}, commit=commit, pushed=pushed
    )


def is_private(path: str) -> bool:
    """Whether a repository path lies where git must never reach."""
    parts = path.split("/")
    if parts[0] in _PRIVATE_TOP:
        return True
    if parts[0] == "projects" and len(parts) > 2:
        return parts[2] in _PRIVATE_IN_PROJECT
    return parts[:2] == ["lab", ".index"]


def _require_host(settings: Settings) -> str:
    if settings.host_id is None:
        raise FactoryValidationError([ValidationIssue("host_id", "this machine has no host id")])
    return settings.host_id


def _require_repository(root: Path) -> None:
    prefix = git(root, "rev-parse", "--show-prefix")
    if prefix.returncode != 0 or prefix.stdout.strip():
        raise FactoryValidationError([ValidationIssue("root", "not the root of a git repository")])


def _changes(root: Path) -> list[tuple[str, str]]:
    """Every (path, status) git can see, staged or not; ignored files are not listed."""
    listing = _run(root, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
    entries = listing.decode().split("\0")
    return [(entry[3:], entry[:2]) for entry in entries if entry]


def _committable(root: Path, slug: str, changes: list[tuple[str, str]]) -> list[str]:
    events = f"projects/{slug}/events/"
    blobs = f"projects/{slug}/blobs/"
    paths: list[str] = []
    for path, status in changes:
        if "D" in status:
            continue
        if path.startswith(events):
            if re.fullmatch(_EVENT_FILE_RE, path[len(events) :]) is not None:
                paths.append(path)
        elif path.startswith(blobs) and re.fullmatch(_BLOB_FILE_RE, path[len(blobs) :]) is not None:
            if _is_text(root / path):
                paths.append(path)
    return paths


def _is_text(path: Path) -> bool:
    """Whether a blob is text. Bytes that are not (a PDF, an archive) are literature or derived
    data, and the repository carries neither (decision 39)."""
    data = path.read_bytes()
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _commit(root: Path, host_id: str, staged: dict[str, list[str]], sign: bool) -> str:
    paths = [path for slug_paths in staged.values() for path in slug_paths]
    author = server_author(host_id)
    email = f"factory-server@{host_id}"
    env = {
        "GIT_AUTHOR_NAME": author,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": author,
        "GIT_COMMITTER_EMAIL": email,
    }
    summary = ", ".join(f"{slug} ({len(p)})" for slug, p in sorted(staged.items()))
    result = git(
        root,
        "commit",
        "-q",
        "-S" if sign else "--no-gpg-sign",
        "-m",
        f"factory commit: {summary}",
        *_PATHSPEC_STDIN,
        stdin=_nul_joined(paths),
        env=env,
    )
    if result.returncode != 0:
        git(root, "reset", "-q", *_PATHSPEC_STDIN, stdin=_nul_joined(paths))
        reason = result.stderr.decode(errors="replace").strip()
        raise FactoryValidationError([ValidationIssue("commit", reason or "git commit failed")])
    return _run(root, "rev-parse", "HEAD").decode().strip()


def _nul_joined(paths: list[str]) -> bytes:
    return b"".join(path.encode() + b"\0" for path in paths)


def _run(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result: subprocess.CompletedProcess[bytes] = git(root, *args, stdin=stdin)
    if result.returncode != 0:
        reason = result.stderr.decode(errors="replace").strip()
        raise FactoryValidationError([ValidationIssue("git", reason or f"git {args[0]} failed")])
    return result.stdout
