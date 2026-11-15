"""Registered study files: files of the project folder that are records of the study but sit
outside the events (plan flow-transparency, "Broader" part B and D).

The event `file.registered` names a path, the sha256 of its content and a kind; the content is
also stored as a blob (the event's input blob), so the record survives later edits of the file.

Invariants:
- `path` is POSIX, relative to the project folder, and has no `..` or empty part.
- A registration is never edited: a changed file is a new registration that names the previous
  registration of the same path in `supersedes`.
- The first registration of a path has no `supersedes`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

EVENT_ID_RE = rf"^ev_{ULID_RE}$"
SHA256_HEX_RE = r"^[0-9a-f]{64}$"
EXCLUDED_TOP_FOLDERS: tuple[str, ...] = ("events", "blobs", "library", ".index", "site")
"""Folders of the project the platform owns (`site/` is hub output): never registered."""

FileKind = Literal["study-document", "validation", "input", "ops", "other"]
FILE_KINDS: tuple[str, ...] = ("study-document", "validation", "input", "ops", "other")


def path_issue(path: str) -> str | None:
    """Why `path` is not a registrable relative POSIX path, or None."""
    if not path or path.startswith("/") or "\\" in path:
        return "a path is relative to the project folder, with forward slashes"
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "a path has no empty, '.' or '..' part"
    if parts[0] in EXCLUDED_TOP_FOLDERS:
        return f"{parts[0]}/ belongs to the platform and is not registered"
    return None


class FileRegistered(StrictModel):
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=SHA256_HEX_RE)
    size: int = Field(ge=0)
    kind: FileKind
    title: str | None = Field(default=None, min_length=1, max_length=200)
    supersedes: str | None = Field(default=None, pattern=EVENT_ID_RE)
    """The previous registration of the same path (an event id), set when the hash changed."""

    @field_validator("path")
    @classmethod
    def _path_is_relative(cls, value: str) -> str:
        issue = path_issue(value)
        if issue is not None:
            raise ValueError(issue)
        return value
