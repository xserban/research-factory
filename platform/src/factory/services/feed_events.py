"""The discovery feed's events, read from the event files without parsing the rest of the log.

The feed views need only the `feed.*` events (fetches, rankings, reactions, sends, configuration),
a small share of a large log. Reading the whole log for them cost seconds per request on a project
of some 200,000 events; this module keeps, per event file, the feed events found so far and the
byte offset it has read to, so a file is scanned once and afterwards only its appended tail.

Invariants:
- Read-only: nothing is written; the result is the feed events of `read_all`, in the same order
  (event id), as the platform reads them (a complete line only; an unterminated tail is left).
- A line is parsed only when its raw bytes carry `"type":"feed.` (the canonical form of the
  envelope); every other line is skipped unread. A parsed line that is not a feed event, or whose
  type the catalog does not know, is dropped here (the projector's own sync is what refuses a
  corrupt log).
- A file that shrank or was replaced (smaller than the offset) is rescanned from its start.
- The cache is process-wide, guarded by one lock, and holds only feed events (small), so memory is
  bounded by the feed's own size.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from factory.events.catalog import EventCatalog
from factory.events.envelope import Event
from factory.events.reader import event_files

_MARK: Final = b'"type":"feed.'
_LOCK = threading.Lock()
# events_dir -> file -> (offset read to, feed events of that file)
_SEEN: dict[str, dict[str, tuple[int, list[Event]]]] = {}


def _scan(path: Path, start: int, catalog: EventCatalog) -> tuple[int, list[Event]]:
    found: list[Event] = []
    offset = start
    with path.open("rb") as handle:
        handle.seek(start)
        for line in handle:
            if not line.endswith(b"\n"):
                break
            offset += len(line)
            if _MARK not in line:
                continue
            try:
                event = Event.from_line(line)
            except ValidationError:
                continue
            if event.type.startswith("feed.") and event.type in catalog:
                found.append(event)
    return offset, found


def feed_events(events_dir: Path, catalog: EventCatalog) -> list[Event]:
    """Every `feed.*` event of the log, sorted by event id."""
    key = str(events_dir)
    with _LOCK:
        files = _SEEN.setdefault(key, {})
        live: set[str] = set()
        for path in event_files(events_dir):
            name = str(path)
            live.add(name)
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            offset, kept = files.get(name, (0, []))
            if size < offset:
                offset, kept = 0, []
            if size == offset:
                continue
            end, new = _scan(path, offset, catalog)
            files[name] = (end, kept + new)
        for gone in set(files) - live:
            del files[gone]
        merged = [event for _offset, kept in files.values() for event in kept]
    return sorted(merged, key=lambda event: event.id)


def clear() -> None:
    """Forget everything kept (tests)."""
    with _LOCK:
        _SEEN.clear()
