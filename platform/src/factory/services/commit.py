"""The server commit job (slice 5 rulings 4 and 5; `factory commit`).

Commits what the projects hosted here have appended: event files and text blobs, nothing else.
`git` runs with fixed arguments only; paths go through stdin, so no path can act as an option.

Invariants:
- A path under a location that must stay out of git (`library/`, `.index/`, `.server/`, a project's
  library or index) that git can see, staged or untracked, refuses the whole job before anything is
  staged: a missing `.gitignore` stops the job instead of being trusted.
- The commit holds exactly the paths this job staged; anything else staged by hand stays out.
- A file is staged under the project's write lock, so a line half-written never enters history.
- History only grows. An event file must extend what HEAD holds byte for byte, a blob must hash to
  its own file name, and a deleted file is a refusal: the job never puts the server's name on an
  edit, a truncation or a removal, and stops loudly instead of skipping one.
- A push goes only to a remote whose every push URL is listed in `.server/push_remotes`, checked
  before anything is committed; with no list, or an empty one, nothing is pushed (ruling 5: the
  remote is private, and a person vouches for that by listing it).
- A push ships history, not the job's own commit: a private path anywhere in what the remote lacks,
  or in HEAD or the index, refuses the push. The job's commit stands; only the push is withheld.
"""

import hashlib
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
PUSH_REMOTES_FILE = ".server/push_remotes"
"""The allow-list of push URLs: UTF-8 text, one URL per line, compared exactly with the output of
`git remote get-url --push --all`. Surrounding spaces are stripped; blank lines and lines starting
with `#` are ignored. Written by `factory server init`."""

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
    if push is not None:
        _require_listed_remote(root, push)
    changes = _changes(root)
    private = sorted(path for path, _ in changes if is_private(path))
    if private:
        listed = ", ".join(private[:5])
        raise FactoryValidationError(
            [ValidationIssue("paths", f"git can see paths that must stay out of it: {listed}")]
        )

    staged: dict[str, list[str]] = {}
    refused: list[str] = []
    clock = SystemClock()
    session = IdGenerator(clock).ulid()
    for slug in list_projects(settings):
        project = open_project(settings, slug, session=session, clock=clock)
        if current_host(project) != host_id:
            continue
        with project.writing():
            paths, problems = _committable(root, slug, _changes(root))
            refused += problems
            if paths and not refused:
                _run(root, "add", *_PATHSPEC_STDIN, stdin=_nul_joined(paths))
                staged[slug] = paths
    if refused:
        done = [path for paths in staged.values() for path in paths]
        if done:
            git(root, "reset", "-q", *_PATHSPEC_STDIN, stdin=_nul_joined(done))
        raise FactoryValidationError(
            [ValidationIssue("history", problem) for problem in sorted(refused)]
        )

    commit = _commit(root, host_id, staged, sign) if staged else None
    pushed = False
    if push is not None:
        _require_shippable_history(root, push)
        pushed = git(root, "push", push, "HEAD").returncode == 0
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


def allowed_push_urls(root: Path) -> frozenset[str]:
    """The URLs of `PUSH_REMOTES_FILE`; empty when the file is absent."""
    path = root / PUSH_REMOTES_FILE
    if not path.is_file():
        return frozenset()
    lines = (line.strip() for line in path.read_text().splitlines())
    return frozenset(line for line in lines if line and not line.startswith("#"))


def _require_listed_remote(root: Path, remote: str) -> None:
    allowed = allowed_push_urls(root)
    if not allowed:
        raise FactoryValidationError(
            [ValidationIssue("push", f"no remote is allowed: {PUSH_REMOTES_FILE} lists none")]
        )
    urls = git(root, "remote", "get-url", "--push", "--all", remote)
    listed = urls.stdout.decode(errors="replace").split()
    if urls.returncode != 0 or not listed:
        raise FactoryValidationError([ValidationIssue("push", f"no remote named {remote}")])
    unlisted = [url for url in listed if url not in allowed]
    if unlisted:
        raise FactoryValidationError(
            [ValidationIssue("push", f"{remote} is not in {PUSH_REMOTES_FILE}: {unlisted[0]}")]
        )


def _require_shippable_history(root: Path, remote: str) -> None:
    """Refuse a push that would carry a private path, however it entered history (`git add -f`).

    The range is what the remote's tracking ref lacks, or all of HEAD when it has none. Commits are
    read one by one as well as the end state, so a path added and later removed still counts."""
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    ref = f"refs/remotes/{remote}/{branch.stdout.decode().strip()}"
    tracked = (
        branch.returncode == 0
        and git(root, "rev-parse", "--verify", "--quiet", ref).returncode == 0
    )
    span = f"{ref}..HEAD" if tracked else "HEAD"
    listings = [
        ("ls-files", "-z"),
        ("ls-tree", "-r", "--name-only", "-z", "HEAD"),
        ("log", "--format=", "--name-only", "-z", "--no-renames", "-m", span),
    ]
    if tracked:
        listings.append(("diff", "--name-only", "-z", "--no-renames", span))
    paths = {
        path
        for listing in listings
        for path in _run(root, *listing).decode().replace("\n", "\0").split("\0")
        if path
    }
    private = sorted(path for path in paths if is_private(path))
    if private:
        raise FactoryValidationError(
            [ValidationIssue("paths", f"history holds private paths: {', '.join(private[:5])}")]
        )


def _changes(root: Path) -> list[tuple[str, str]]:
    """Every (path, status) git can see, staged or not; ignored files are not listed."""
    listing = _run(root, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
    entries = listing.decode().split("\0")
    return [(entry[3:], entry[:2]) for entry in entries if entry]


def _committable(
    root: Path, slug: str, changes: list[tuple[str, str]]
) -> tuple[list[str], list[str]]:
    """The paths of this project to commit, and what refuses the job."""
    events = f"projects/{slug}/events/"
    blobs = f"projects/{slug}/blobs/"
    paths: list[str] = []
    refused: list[str] = []
    for path, status in changes:
        event = path.startswith(events) and re.fullmatch(_EVENT_FILE_RE, path[len(events) :])
        blob = path.startswith(blobs) and re.fullmatch(_BLOB_FILE_RE, path[len(blobs) :])
        if not event and not blob:
            continue
        if "D" in status:
            refused.append(f"{path}: deleted")
            continue
        data = (root / path).read_bytes()
        problem = _event_problem(root, path, status, data) if event else _blob_problem(path, data)
        if problem is not None:
            refused.append(f"{path}: {problem}")
        elif event or _is_text(data):
            paths.append(path)
    return paths, refused


def _event_problem(root: Path, path: str, status: str, data: bytes) -> str | None:
    """Why this event file cannot be committed: what HEAD holds must be a prefix of it. A file new
    to git has nothing to extend."""
    if status == "??" or status[0] == "A":
        return None
    head = git(root, "show", f"HEAD:{path}")
    if head.returncode != 0:
        return "cannot read it from HEAD"
    return None if data.startswith(head.stdout) else "does not extend what HEAD holds"


def _blob_problem(path: str, data: bytes) -> str | None:
    """Why this blob cannot be committed: a store path is `sha256/<2>/<62>` of its content."""
    expected = "".join(path.rsplit("/", 2)[-2:])
    return None if hashlib.sha256(data).hexdigest() == expected else "does not hash to its name"


def _is_text(data: bytes) -> bool:
    """Whether a blob is text. Bytes that are not (a PDF, an archive) are literature or derived
    data, and the repository carries neither (decision 39)."""
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
