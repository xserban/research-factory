import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from factory.errors import FactoryError
from factory.events.catalog import EventCatalog
from factory.events.envelope import Event


class EventLogCorruptError(FactoryError):
    """A complete event line is malformed or names an unknown type."""

    def __init__(self, path: Path, offset: int, reason: str) -> None:
        self.path = path
        self.offset = offset
        self.reason = reason
        super().__init__(f"{path} at byte offset {offset}: {reason}")


@dataclass(frozen=True)
class ReadResult:
    events: list[Event]
    end_offset: int
    truncated_tail: bool


def relative_name(path: Path, events_dir: Path) -> str:
    """`path` relative to `events_dir`, POSIX form; equal to `path.relative_to(events_dir)`.

    Lexical, like `relative_to`, but without its per-call walk over every ancestor of
    `events_dir`, which dominated index syncs. Raises `ValueError` if `path` is not inside.
    """
    text, base = str(path), str(events_dir)
    prefix = base if base.endswith(os.sep) else base + os.sep
    if text.startswith(prefix) and len(text) > len(prefix):  # fast path: plain string prefix
        return text[len(prefix) :].replace(os.sep, "/")
    inside, parts = events_dir.parts, path.parts  # e.g. events_dir == Path("."), parts ()
    if (
        path.is_absolute() != events_dir.is_absolute()
        or len(parts) <= len(inside)
        or parts[: len(inside)] != inside
    ):
        raise ValueError(f"{path} is not inside {events_dir}")
    return "/".join(parts[len(inside) :])


def event_files(events_dir: Path) -> list[Path]:
    """Every event file (`<dir>/<name>.jsonl`), ordered by its POSIX path relative to `events_dir`.

    Equivalent to `events_dir.glob("*/*.jsonl")`, but with `os.scandir`: the index syncs on every
    read, and pathlib's glob was a large share of each sync.
    """
    names: list[str] = []
    try:
        top = os.scandir(events_dir)
    except (FileNotFoundError, NotADirectoryError):
        return []
    with top:
        for entry in top:
            if not entry.is_dir():
                continue
            with os.scandir(entry.path) as inner:
                names.extend(f"{entry.name}/{f.name}" for f in inner if f.name.endswith(".jsonl"))
    return [events_dir / name for name in sorted(names)]


def read_file(path: Path, catalog: EventCatalog, start: int = 0) -> ReadResult:
    """Read complete lines from byte `start`; an unterminated last line is left unread."""
    events: list[Event] = []
    offset = start
    truncated = False
    with path.open("rb") as handle:
        handle.seek(start)
        for line in handle:
            if not line.endswith(b"\n"):
                truncated = True
                break
            events.append(_parse_line(path, offset, line, catalog))
            offset += len(line)
    return ReadResult(events=events, end_offset=offset, truncated_tail=truncated)


def read_all(events_dir: Path, catalog: EventCatalog) -> list[Event]:
    events: list[Event] = []
    for path in event_files(events_dir):
        events.extend(read_file(path, catalog).events)
    return sorted(events, key=lambda e: e.id)


def _parse_line(path: Path, offset: int, line: bytes, catalog: EventCatalog) -> Event:
    try:
        event = Event.from_line(line)
    except ValidationError as exc:
        raise EventLogCorruptError(path, offset, f"invalid event line: {exc}") from exc
    if event.type not in catalog:
        raise EventLogCorruptError(path, offset, f"unknown event type {event.type!r}")
    return event
