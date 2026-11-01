import re
from dataclasses import dataclass

from factory.model.base import StrictModel
from factory.model.dedup import DedupMerged, DedupReverted
from factory.model.project import ProjectCreated
from factory.model.search import (
    QueryRegistered,
    SearchPageArchived,
    SearchRecordsParsed,
    SearchRunFinished,
    SearchRunStarted,
)
from factory.model.task import TaskClaimed, TaskCompleted, TaskCreated, TaskReleased

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
    catalog.register(EventType("task.created", TaskCreated, 1))
    catalog.register(EventType("task.claimed", TaskClaimed, 1))
    catalog.register(EventType("task.completed", TaskCompleted, 1))
    catalog.register(EventType("task.released", TaskReleased, 1))
    catalog.register(EventType("query.registered", QueryRegistered, 1))
    catalog.register(EventType("search.run_started", SearchRunStarted, 1))
    catalog.register(EventType("search.page_archived", SearchPageArchived, 1))
    catalog.register(EventType("search.records_parsed", SearchRecordsParsed, 1))
    catalog.register(EventType("search.run_finished", SearchRunFinished, 1))
    catalog.register(EventType("dedup.merged", DedupMerged, 1))
    catalog.register(EventType("dedup.reverted", DedupReverted, 1))
    return catalog
