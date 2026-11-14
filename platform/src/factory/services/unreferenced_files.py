"""Files of the project folder that no event names (plan flow-transparency, R3).

The hub is built from events, so a file the events never name is invisible to it. This module
finds those files; `check` reports them as a warning. Read-only.

A file is *referenced* when:
- a `file.registered` event names its project-relative path (the `registered_files` table), or
- any event payload holds its project-relative path, or an absolute path inside the project
  folder, as a string value (exact match), or
- it lies under `inputs/` and its sha256 names a file of the project library (an adopted
  document).

Not walked: `events/`, `blobs/`, `library/`, `.index/`, `site/`, and every dot-entry at the top
level. One pass over the event files and one walk of the folder.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

from factory.events.reader import event_files
from factory.services.context import Project

SKIPPED = frozenset({"events", "blobs", "library", "site"})
EXAMPLES = 20


@dataclass(frozen=True)
class UnreferencedReport:
    total: int
    """Files walked."""
    by_folder: dict[str, int] = field(default_factory=dict)
    """Unreferenced files by top-level folder; files at the top level count under `.`."""
    examples: tuple[str, ...] = ()
    """Up to `EXAMPLES` unreferenced paths, sorted."""

    @property
    def unreferenced(self) -> int:
        return sum(self.by_folder.values())


def walk_files(root: Path) -> list[str]:
    """Project-relative POSIX paths of the files outside the skipped top-level entries."""
    found: list[str] = []
    with os.scandir(root) as top:
        entries = sorted(top, key=lambda e: e.name)
    for entry in entries:
        if entry.name.startswith(".") or entry.name in SKIPPED:
            continue
        if entry.is_file(follow_symlinks=False):
            found.append(entry.name)
        elif entry.is_dir(follow_symlinks=False):
            for base, dirs, names in os.walk(entry.path):
                dirs.sort()
                rel = os.path.relpath(base, root)
                found.extend(f"{rel}/{n}".replace(os.sep, "/") for n in sorted(names))
    return found


def _strings(value: object, out: set[str]) -> None:
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _strings(item, out)
    elif isinstance(value, list):
        for item in value:
            _strings(item, out)


def event_strings(events_dir: Path, wanted: frozenset[str]) -> set[str]:
    """The members of `wanted` that occur as a string value in some event payload. One pass; a
    line that does not parse is skipped (the reader reports it elsewhere)."""
    seen: set[str] = set()
    for path in event_files(events_dir):
        with path.open("rb") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                payload = record.get("payload") if isinstance(record, dict) else None
                if payload is None:
                    continue
                strings: set[str] = set()
                _strings(payload, strings)
                seen |= strings & wanted
    return seen


def _in_library(root: Path, path: Path) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    hexa = digest.hexdigest()
    return (root / "library" / "sha256" / hexa[:2] / hexa[2:]).exists()


def unreferenced_files(project: Project) -> UnreferencedReport:
    """Every file outside the skipped folders that no event names. Syncs the index."""
    project.index.sync()
    root = project.paths.dir
    files = walk_files(root)
    with project.index.connect() as conn:
        registered = {str(r[0]) for r in conn.execute(text("SELECT path FROM registered_files"))}
    prefix = str(root.resolve()).rstrip("/") + "/"
    wanted: set[str] = set()
    for rel in files:
        wanted.add(rel)
        wanted.add(prefix + rel)
        wanted.add(str(root) + "/" + rel)
    named = event_strings(project.paths.events_dir, frozenset(wanted))
    missing: list[str] = []
    for rel in files:
        if rel in registered or rel in named:
            continue
        if prefix + rel in named or str(root) + "/" + rel in named:
            continue
        if rel.startswith("inputs/") and _in_library(root, root / rel):
            continue
        missing.append(rel)
    by_folder: dict[str, int] = {}
    for rel in missing:
        top = rel.split("/", 1)[0] if "/" in rel else "."
        by_folder[top] = by_folder.get(top, 0) + 1
    return UnreferencedReport(len(files), by_folder, tuple(sorted(missing)[:EXAMPLES]))
