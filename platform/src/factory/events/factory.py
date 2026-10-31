from collections.abc import Sequence

from factory.events.catalog import EventCatalog
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.identity import IdGenerator, ulid_time


class EventFactory:
    """Builds events for one project; the ULID supplies both `id` and `ts`."""

    def __init__(self, project: str, catalog: EventCatalog, ids: IdGenerator) -> None:
        self._project = project
        self._catalog = catalog
        self._ids = ids

    def make(
        self,
        type: str,
        payload: StrictModel,
        actor: Actor,
        refs: Sequence[str] = (),
        input_blob: str | None = None,
    ) -> Event:
        event_type = self._catalog.get(type)
        if not isinstance(payload, event_type.payload):
            raise TypeError(
                f"{type} expects {event_type.payload.__name__}, got {payload.__class__.__name__}"
            )
        ulid = self._ids.ulid()
        return Event(
            id=f"ev_{ulid}",
            ts=ulid_time(ulid),
            project=self._project,
            type=type,
            schema_version=event_type.schema,
            actor=actor,
            refs=tuple(refs),
            input_blob=input_blob,
            payload=payload.model_dump(mode="json"),
        )
