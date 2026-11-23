"""The factory event scope at `<root>/factory/` (decision 169, proposed).

A third log beside the projects' and the lab's, on the same `EventWriter`, `Index` and
`EventFactory`, with its own catalog (the `feed.*` allow-list) and projection. Its envelope
`project` is the reserved slug `_factory`.

Invariants:
- A type outside the allow-list is refused at the boundary with a structured error; nothing is
  written. The writer validates every event against the factory catalog.
- Reactions are human acts and ranker trainings system acts; any other actor is refused with
  nothing written (R-F3). The fold ignores such an event anyway.
- Every write holds the scope's write lock and syncs the index after it.
"""

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from sqlalchemy import Table
from sqlalchemy.engine import Connection

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog
from factory.events.envelope import Actor, Event
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.index import factory_scope as scope_index
from factory.index.index import Index
from factory.model.factory_scope import FACTORY_DIR, FACTORY_SLUG
from factory.model.identity import IdGenerator
from factory.services.call_memo import invalidate
from factory.services.context import future_dated

_T = TypeVar("_T")

_ACTOR_KIND = {"feed.reacted": "human", "feed.ranker_trained": "system"}
"""The one actor kind that may write each type; `feed.ranked` may come from any non-human."""


@dataclass(frozen=True)
class FactoryPaths:
    root: Path

    @property
    def dir(self) -> Path:
        return self.root / FACTORY_DIR

    @property
    def events_dir(self) -> Path:
        return self.dir / "events"

    @property
    def blobs_dir(self) -> Path:
        return self.dir / "blobs"

    @property
    def index_path(self) -> Path:
        return self.dir / ".index" / "factory.sqlite"


@dataclass
class FactoryScope:
    """Everything a service needs to read and write the factory scope."""

    paths: FactoryPaths
    settings: Settings
    session: str
    clock: Clock
    ids: IdGenerator
    events: EventFactory
    writer: EventWriter
    catalog: EventCatalog
    blobs: BlobStore
    index: Index
    tables: dict[str, Table]

    def writing(self) -> AbstractContextManager[None]:
        """The write context, as `Project.writing()`: lock, sync, and IDs above the log."""
        return self.index.exclusive()

    def record(self, events: Sequence[Event]) -> None:
        """Append `events`, or refuse all with nothing written (type, payload, actor kind)."""
        issues = [
            ValidationIssue(f"events[{i}].actor", f"{e.type} is written by a {need} actor")
            for i, e in enumerate(events)
            if (need := _ACTOR_KIND.get(e.type)) is not None and e.actor.kind != need
        ]
        issues += [
            ValidationIssue(f"events[{i}].type", f"{e.type!r} is not a factory-scope event type")
            for i, e in enumerate(events)
            if e.type not in self.catalog
        ]
        if issues:
            raise FactoryValidationError(issues)
        with self.writing():
            self.index.appended()  # before the write: a failed write leaves it unknown too
            self.writer.append(events)
            self.index.sync()
            invalidate()

    def human_actor(self) -> Actor:
        return Actor(
            kind="human", id=self.settings.user, user=self.settings.user, session=self.session
        )

    def system_actor(self) -> Actor:
        return Actor(kind="system", id="factory", user=self.settings.user, session=self.session)

    def read(self, read: Callable[[Connection], _T]) -> _T:
        """`read` on a connection to the synced factory index."""
        self.index.sync()
        with self.index.connect() as conn:
            return read(conn)


def factory_scope_exists(settings: Settings) -> bool:
    return FactoryPaths(settings.root).events_dir.is_dir()


def _build(settings: Settings, *, session: str, clock: Clock) -> FactoryScope:
    paths = FactoryPaths(settings.root)
    catalog = scope_index.factory_catalog()
    ids = IdGenerator(clock)
    blobs = BlobStore(paths.blobs_dir)
    projection, tables = scope_index.factory_projection()

    def floor(last_event_id: str | None) -> None:
        if last_event_id is not None and not future_dated(last_event_id, clock.now()):
            ids.floor(last_event_id.removeprefix("ev_"))

    return FactoryScope(
        paths=paths,
        settings=settings,
        session=session,
        clock=clock,
        ids=ids,
        events=EventFactory(FACTORY_SLUG, catalog, ids),
        writer=EventWriter(paths.events_dir, project=FACTORY_SLUG, catalog=catalog, blobs=blobs),
        catalog=catalog,
        blobs=blobs,
        index=Index(
            paths.index_path,
            paths.events_dir,
            catalog,
            projection,
            on_exclusive=floor,
            hold_window=settings.index_hold,
        ),
        tables=tables,
    )


def open_factory_scope(settings: Settings, *, session: str, clock: Clock) -> FactoryScope:
    """Open the factory scope, creating `<root>/factory/events` if need be. Writes no event."""
    FactoryPaths(settings.root).events_dir.mkdir(parents=True, exist_ok=True)
    return _build(settings, session=session, clock=clock)
