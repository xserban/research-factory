import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
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


def read_file(
    path: Path, catalog: EventCatalog, start: int = 0, types: frozenset[str] | None = None
) -> ReadResult:
    """Read complete lines from byte `start`; an unterminated last line is left unread.

    With `types`, a line is parsed only when it holds the text `"type":"<t>"` of one of them (the
    writer's canonical form), and kept only when its type is one: the other lines are not parsed,
    so a malformed one among them goes unseen here (the index sync reads every line)."""
    events: list[Event] = []
    needles = None if types is None else tuple(f'"type":"{t}"'.encode() for t in sorted(types))
    offset = start
    truncated = False
    with path.open("rb") as handle:
        handle.seek(start)
        for line in handle:
            if not line.endswith(b"\n"):
                truncated = True
                break
            if needles is None or any(n in line for n in needles):
                event = _parse_line(path, offset, line, catalog)
                if types is None or event.type in types:
                    events.append(event)
            offset += len(line)
    return ReadResult(events=events, end_offset=offset, truncated_tail=truncated)


@dataclass
class _FileRead:
    """What a scope has read of one event file: its events, the byte offset after the last complete
    line, and the file size seen (the two differ only while an unterminated tail waits)."""

    events: list[Event] = field(default_factory=list)
    end_offset: int = 0
    size: int = -1


@dataclass
class _DirRead:
    files: dict[Path, _FileRead] = field(default_factory=dict)
    stamp: tuple[tuple[Path, int], ...] = ()
    merged: list[Event] = field(default_factory=list)


_scope: ContextVar[dict[tuple[Path, int, frozenset[str] | None], _DirRead] | None] = ContextVar(
    "event_read_scope", default=None
)


@contextmanager
def cached_reads() -> Iterator[None]:
    """Open a read scope: inside it `read_all` parses each event line once, however often it is
    called, and re-reads only what was appended since (a file whose size changed is read on from
    where the scope stopped; a file that shrank is read again from the start). Nothing outlives the
    scope, so no answer is kept across calls. A nested scope reuses the open one. Events are shared
    between callers; each call gets a list of its own.

    Invariant: a shared `Event` is frozen but its `payload` dict is not; no caller may mutate it
    (a test scans the sources for such writes). Copy first (`dict(event.payload)`) to edit."""
    if _scope.get() is not None:
        yield
        return
    token = _scope.set({})
    try:
        yield
    finally:
        _scope.reset(token)


def _read_scoped(
    events_dir: Path,
    catalog: EventCatalog,
    held: dict[tuple[Path, int, frozenset[str] | None], _DirRead],
    types: frozenset[str] | None,
) -> list[Event]:
    entry = held.setdefault((events_dir, id(catalog), types), _DirRead())
    stamp: list[tuple[Path, int]] = []
    changed = False
    for path in event_files(events_dir):
        size = path.stat().st_size
        stamp.append((path, size))
        seen = entry.files.setdefault(path, _FileRead())
        # Unchanged only when the whole file was consumed: while an unterminated tail waits
        # (`end_offset != size`) the writer may truncate it and append up to the same size.
        if size == seen.size and seen.end_offset == size:
            continue
        if size < seen.end_offset:  # shrank: not an append, read it afresh
            seen.events, seen.end_offset = [], 0
            changed = True
        result = read_file(path, catalog, seen.end_offset, types)
        changed = changed or bool(result.events)
        seen.events.extend(result.events)
        seen.end_offset = result.end_offset
        seen.size = size
    fingerprint = tuple(stamp)
    if changed or fingerprint != entry.stamp:
        entry.stamp = fingerprint
        entry.merged = sorted(
            (e for path, _ in fingerprint for e in entry.files[path].events), key=lambda e: e.id
        )
    return list(entry.merged)


def read_all(events_dir: Path, catalog: EventCatalog) -> list[Event]:
    held = _scope.get()
    if held is not None:
        return _read_scoped(events_dir, catalog, held, None)
    events: list[Event] = []
    for path in event_files(events_dir):
        events.extend(read_file(path, catalog).events)
    return sorted(events, key=lambda e: e.id)


def read_typed(events_dir: Path, catalog: EventCatalog, types: Iterable[str]) -> list[Event]:
    """The events of `types` in id order: `read_all` filtered by type, without parsing the lines of
    other types (see `read_file`). Inside a `cached_reads` scope each type set is read once."""
    wanted = frozenset(types)
    held = _scope.get()
    if held is not None:
        return _read_scoped(events_dir, catalog, held, wanted)
    events: list[Event] = []
    for path in event_files(events_dir):
        events.extend(read_file(path, catalog, 0, wanted).events)
    return sorted(events, key=lambda e: e.id)


def _parse_line(path: Path, offset: int, line: bytes, catalog: EventCatalog) -> Event:
    try:
        event = Event.from_line(line)
    except ValidationError as exc:
        raise EventLogCorruptError(path, offset, f"invalid event line: {exc}") from exc
    if event.type not in catalog:
        raise EventLogCorruptError(path, offset, f"unknown event type {event.type!r}")
    return event
