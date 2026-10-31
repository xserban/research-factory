import re
from dataclasses import dataclass

from factory.model.base import StrictModel
from factory.model.project import ProjectCreated

_NAME_RE = re.compile(r"[a-z][a-z_]*\.[a-z][a-z_]*")


@dataclass(frozen=True)
class EventType:
    name: str
    payload: type[StrictModel]
    schema: int


class EventCatalog:
    """Registry of event types: name -> payload model and schema version."""

    def __init__(self) -> None:
        self._types: dict[str, EventType] = {}

    def register(self, event_type: EventType) -> None:
        if _NAME_RE.fullmatch(event_type.name) is None:
            raise ValueError(f"invalid event type name: {event_type.name!r}")
        if event_type.name in self._types:
            raise ValueError(f"event type already registered: {event_type.name!r}")
        self._types[event_type.name] = event_type

    def get(self, name: str) -> EventType:
        return self._types[name]

    def __contains__(self, name: object) -> bool:
        return name in self._types

    def names(self) -> list[str]:
        return sorted(self._types)


def default_catalog() -> EventCatalog:
    """The production catalog: every event type the platform writes."""
    catalog = EventCatalog()
    catalog.register(EventType("project.created", ProjectCreated, 1))
    return catalog
