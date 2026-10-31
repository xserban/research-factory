import os
from collections.abc import Sequence
from pathlib import Path

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog
from factory.events.envelope import Event
from factory.events.validation import validate_event


class EventWriter:
    """Appends events to `<events_dir>/<actor.id>/<session>.jsonl`. Never edits a line."""

    def __init__(
        self,
        events_dir: Path,
        *,
        project: str,
        catalog: EventCatalog,
        blobs: BlobStore,
    ) -> None:
        self._events_dir = events_dir
        self._project = project
        self._catalog = catalog
        self._blobs = blobs

    def append(self, events: Sequence[Event]) -> None:
        if not events:
            return
        issues: list[ValidationIssue] = []
        for index, event in enumerate(events):
            for issue in validate_event(
                event, catalog=self._catalog, blobs=self._blobs, project=self._project
            ):
                issues.append(ValidationIssue(f"events[{index}].{issue.field}", issue.reason))
        if issues:
            raise FactoryValidationError(issues)

        batches: dict[Path, list[bytes]] = {}
        for event in events:
            path = self._events_dir / event.actor.id / f"{event.actor.session}.jsonl"
            batches.setdefault(path, []).append(event.to_line())
        for path, lines in batches.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as handle:
                handle.write(b"".join(lines))
                handle.flush()
                os.fsync(handle.fileno())
