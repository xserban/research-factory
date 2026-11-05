"""Hosting: one writer per hosted project (slice 5 rulings 2 and 19).

`project.hosted` names the host; from then on `EventWriter` refuses any machine whose
`Settings.host_id` differs. An unhosted project has no host and no host check.

Invariants:
- Only a person hosts a project (lab administration; agents never hold it). The fold enforces the
  same rule, so a hand-written event of any other actor changes nothing.
- `previous_host` comes from the fold, never from the caller.
- `git` runs with fixed arguments; a machine without git gets a failed result, not an exception.
"""

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.hosting import ProjectHosted
from factory.model.identity import ACTOR_ID_RE
from factory.services.context import Project, hosted_by

GIT_TIMEOUT_SECONDS = 300
# Set by a git hook or a wrapping shell, these would point every command at another repository.
_INHERITED_GIT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


@dataclass(frozen=True)
class ForeignFile:
    """An event file holding events of a hosted period, added to git by someone else."""

    path: str
    author: str
    expected: tuple[str, ...]


def server_author(host_id: str) -> str:
    """The git author name of the commits a host makes (ruling 5)."""
    return f"factory-server {host_id}"


def git(
    root: Path, *args: str, stdin: bytes | None = None, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run git at `root`. `env` adds to a cleaned environment: a path is never a pattern, git never
    asks a terminal, and a hung command fails instead of holding the caller."""
    command = ["git", "-C", str(root), *args]
    clean = {name: value for name, value in os.environ.items() if name not in _INHERITED_GIT}
    full = {**clean, "GIT_LITERAL_PATHSPECS": "1", "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    try:
        return subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            env=full,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, b"", b"git timed out")
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, b"", str(exc).encode())


def current_host(project: Project) -> str | None:
    """The host named by the last folded `project.hosted`; None for an unhosted project."""
    return hosted_by(project.index)


def host_project(project: Project, actor: Actor, host_id: str) -> str:
    """Record that `host_id` is the project's only writer; returns the event id.

    Refused, with nothing written: an actor who is not a person (`actor`); a malformed host, or the
    host already named (`host_id`). A machine other than the current host is refused by the host
    check itself (`host`), so only the current host can move a project."""
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "only a person hosts a project")])
    if re.fullmatch(ACTOR_ID_RE, host_id) is None:
        raise FactoryValidationError([ValidationIssue("host_id", f"must match {ACTOR_ID_RE}")])
    with project.writing():
        previous = current_host(project)
        if previous == host_id:
            raise FactoryValidationError(
                [ValidationIssue("host_id", f"project is already hosted by {host_id}")]
            )
        payload = ProjectHosted(host_id=host_id, previous_host=previous)
        event = project.events.make("project.hosted", payload, actor)
        project.record([event])
    return event.id


def foreign_event_files(project: Project) -> list[ForeignFile] | None:
    """Event files with an event later than `project.hosted` whose adding commit is not by the host
    in force over those events. Sessions write no event, so the commit's author is the only durable
    record of who wrote a file; the writer's guard prevents the case on the server itself.

    A file not yet committed has no author and is not listed. None when the root has no readable
    git history, so nothing can be said."""
    project.index.sync()
    with project.index.connect() as conn:
        hosts = [
            (str(event_id), str(host_id))
            for event_id, host_id in conn.execute(
                text("SELECT event_id, host_id FROM project_hosts ORDER BY event_id")
            )
        ]
        if not hosts:
            return []
        files = conn.execute(
            text(
                "SELECT actor_id, session, MIN(id), MAX(id) FROM events WHERE id > :first "
                "GROUP BY actor_id, session"
            ),
            {"first": hosts[0][0]},
        ).all()
    authors = _adding_authors(project)
    if authors is None:
        return None
    events = project.paths.events_dir.relative_to(project.settings.root).as_posix()
    foreign: list[ForeignFile] = []
    for actor_id, session, low, high in files:
        path = f"{events}/{actor_id}/{session}.jsonl"
        expected = _hosts_in_force(hosts, str(low), str(high))
        allowed = {server_author(host) for host in expected}
        foreign += [
            ForeignFile(path, author, expected)
            for author in authors.get(path, ())
            if author not in allowed
        ]
    return foreign


def _hosts_in_force(hosts: Sequence[tuple[str, str]], low: str, high: str) -> tuple[str, ...]:
    """The hosts whose periods meet the IDs `low` to `high`. A period starts just after its
    `project.hosted`: that event itself is the outgoing host's."""
    found: list[str] = []
    for index, (event_id, host_id) in enumerate(hosts):
        ends = hosts[index + 1][0] if index + 1 < len(hosts) else None
        if event_id < high and (ends is None or ends >= low):
            found.append(host_id)
    return tuple(found)


def _adding_authors(project: Project) -> dict[str, list[str]] | None:
    """Each event file's adding commits' author names, in one pass over the history."""
    root = project.settings.root
    events = project.paths.events_dir.relative_to(root).as_posix()
    log = git(
        root,
        "log",
        "--no-renames",
        "--diff-filter=A",
        "--relative",
        "--format=%x01%an",
        "--name-only",
        "--",
        events,
    )
    if log.returncode != 0:
        return None
    authors: dict[str, list[str]] = {}
    author = ""
    for line in log.stdout.decode(errors="replace").splitlines():
        if line.startswith("\x01"):
            author = line[1:]
        elif line:
            authors.setdefault(line, []).append(author)
    return authors
