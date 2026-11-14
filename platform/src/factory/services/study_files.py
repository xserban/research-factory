"""Registered study files: register, list and compare with the disk (plan flow-transparency, B).

A file of the project folder that is a record of the study but sits outside the events (the
research plan, a review protocol, a validation report) is **registered**: `file.registered` names
its path, the sha256 of its content, its size and a kind, and the content is stored as a blob, so
the record survives later edits of the file.

Invariants:
- Only a human registers: the researcher's files are the researcher's to name.
- A path is relative to the project folder, inside it after symlinks are resolved, an existing
  regular file, and not under `events/`, `blobs/`, `library/` or `.index/`. Anything else is
  refused with nothing written.
- Registering a path whose current hash, kind and title all equal its latest registration writes
  nothing and returns that registration (`changed` is false); a changed file, or the same content
  with a different kind or title, is a new registration that supersedes the latest one.
- `file_status` only reads: it never registers or rewrites anything.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.files import (
    EXCLUDED_TOP_FOLDERS,
    FILE_KINDS,
    FileKind,
    FileRegistered,
    path_issue,
)
from factory.services.context import Project

Status = Literal["unchanged", "changed", "missing"]


@dataclass(frozen=True)
class Registration:
    """One registration of a path (one `file.registered` event)."""

    event_id: str
    path: str
    sha256: str
    kind: str
    title: str | None
    blob: str
    supersedes: str | None
    registered_at: str
    version: int
    """1 for the first registration of the path, then 2, 3, ..."""


@dataclass(frozen=True)
class Registered:
    registration: Registration
    changed: bool
    """True when this call wrote a new registration; false when the file was already registered
    with this content, kind and title."""
    metadata_only: bool = False
    """True when the new registration changes only the kind or title (same content)."""


@dataclass(frozen=True)
class StudyFile:
    """A registered path: its latest registration and the earlier ones, newest first."""

    latest: Registration
    history: tuple[Registration, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FileStatus:
    path: str
    kind: str
    state: Status
    registered_sha256: str
    current_sha256: str | None
    version: int


def _issue(field_name: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, message)])


def _rows(project: Project) -> list[Registration]:
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT event_id, path, sha256, kind, title, blob, supersedes, registered_at "
                "FROM registered_files ORDER BY path, event_id"
            )
        ).all()
    out: list[Registration] = []
    counts: dict[str, int] = {}
    for eid, path, sha, kind, title, blob, sup, at in found:
        counts[path] = counts.get(path, 0) + 1
        out.append(
            Registration(
                str(eid),
                str(path),
                str(sha),
                str(kind),
                title,
                str(blob),
                sup,
                str(at),
                counts[path],
            )
        )
    return out


def _latest(project: Project, path: str) -> Registration | None:
    mine = [r for r in _rows(project) if r.path == path]
    return mine[-1] if mine else None


def _locate(project: Project, path: str) -> Path:
    """The file behind a registrable path, or a refusal naming the reason."""
    reason = path_issue(path)
    if reason is not None:
        raise _issue("path", reason)
    root = project.paths.dir.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise _issue("path", "the file is outside the project folder")
    inside = target.relative_to(root).parts
    if inside and inside[0] in EXCLUDED_TOP_FOLDERS:
        raise _issue("path", f"{inside[0]}/ belongs to the platform and is not registered")
    if not target.exists():
        raise _issue("path", f"no such file: {path}")
    if not target.is_file():
        raise _issue("path", f"not a regular file: {path}")
    return target


def register_file(
    project: Project,
    path: str,
    kind: str,
    title: str | None,
    actor: Actor,
) -> Registered:
    """Register the current content of `path` (relative to the project folder).

    Refused, with nothing written: for a non-human actor, an unknown kind, a path that is absolute,
    escapes the folder, lies under an excluded folder, does not exist or is not a file. An
    file with the same kind and title writes nothing and returns its latest registration; the same
    content with another kind or title is a new registration."""
    if actor.kind != "human":
        raise _issue("actor", "a human registers study files")
    if kind not in FILE_KINDS:
        raise _issue("kind", f"kind is one of {', '.join(FILE_KINDS)}")
    if title is not None and not 1 <= len(title.strip()) <= 200:
        raise _issue("title", "a title has 1 to 200 characters")
    target = _locate(project, path)
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    with project.index.exclusive():
        previous = _latest(project, path)
        clean_title = title.strip() if title else None
        if (
            previous is not None
            and previous.sha256 == digest
            and previous.kind == kind
            and previous.title == clean_title
        ):
            return Registered(previous, False)
        blob = project.blobs.put(data)
        payload = FileRegistered(
            path=path,
            sha256=digest,
            size=len(data),
            kind=cast(FileKind, kind),
            title=clean_title,
            supersedes=previous.event_id if previous else None,
        )
        event = project.events.make("file.registered", payload, actor, input_blob=blob)
        project.record([event])
    stored = _latest(project, path)
    assert stored is not None and stored.event_id == event.id
    return Registered(stored, True, previous is not None and previous.sha256 == digest)


def list_files(project: Project) -> list[StudyFile]:
    """Every registered path with its latest registration and history, by kind then path."""
    by_path: dict[str, list[Registration]] = {}
    for reg in _rows(project):
        by_path.setdefault(reg.path, []).append(reg)
    files = [StudyFile(v[-1], tuple(reversed(v[:-1]))) for v in by_path.values()]
    return sorted(files, key=lambda f: (FILE_KINDS.index(f.latest.kind), f.latest.path))


def file_status(project: Project) -> list[FileStatus]:
    """Each registered path's current on-disk hash against its latest registration."""
    root = project.paths.dir.resolve()
    out: list[FileStatus] = []
    for entry in list_files(project):
        latest = entry.latest
        target = (root / latest.path).resolve()
        current: str | None = None
        if target.is_relative_to(root) and target.is_file():
            current = hashlib.sha256(target.read_bytes()).hexdigest()
        state: Status = (
            "missing" if current is None else "unchanged" if current == latest.sha256 else "changed"
        )
        out.append(
            FileStatus(latest.path, latest.kind, state, latest.sha256, current, latest.version)
        )
    return out
