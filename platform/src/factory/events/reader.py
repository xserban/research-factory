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


def event_files(events_dir: Path) -> list[Path]:
    paths = list(events_dir.glob("*/*.jsonl"))
    return sorted(paths, key=lambda p: p.relative_to(events_dir).as_posix())


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
