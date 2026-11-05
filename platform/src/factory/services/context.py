import re
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from factory.clock import Clock
from factory.config import Settings
from factory.errors import OrderingError, ProjectNotFoundError, ValidationIssue
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, default_catalog
from factory.events.envelope import Actor, Event
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.index.default import default_projection
from factory.index.index import Index
from factory.model.identity import SLUG_RE, IdGenerator

MAX_SLUG_LENGTH = 64


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    slug: str

    @property
    def dir(self) -> Path:
        return self.root / "projects" / self.slug

    @property
    def events_dir(self) -> Path:
        return self.dir / "events"

    @property
    def blobs_dir(self) -> Path:
        return self.dir / "blobs"

    @property
    def library_dir(self) -> Path:
        """Project-local, git-ignored literature library (decision 39)."""
        return self.dir / "library"

    @property
    def index_path(self) -> Path:
        return self.dir / ".index" / "factory.sqlite"


@dataclass
class Project:
    """Everything a service needs to work on one project."""

    paths: ProjectPaths
    settings: Settings
    session: str
    clock: Clock
    ids: IdGenerator
    catalog: EventCatalog
    blobs: BlobStore
    library: BlobStore
    events: EventFactory
    writer: EventWriter
    index: Index

    def writing(self) -> AbstractContextManager[None]:
        """The project write context: holds the lock, syncs, and floors `ids` above the last
        applied event, so an event minted inside sorts after the whole log and append order equals
        ID order across sessions and processes (slice 5 ruling 3). Re-entrant.

        It is `index.exclusive()`: `build_project` wires the floor into the lock, so the services
        that take the lock directly mint under the same guarantee."""
        return self.index.exclusive()

    def is_hosted(self) -> bool:
        return False

    def record(self, events: Sequence[Event]) -> None:
        """Append and fold under the write lock. On a hosted project, refuse with nothing written a
        batch that does not sort after the log, and append the rest in ID order."""
        with self.writing():
            if events and self.is_hosted():
                last = self.index.last_event_id()
                if last is not None and min(event.id for event in events) <= last:
                    raise OrderingError(f"event minted outside writing(): not after {last}")
                events = sorted(events, key=lambda event: event.id)
            self.writer.append(events)
            self.index.sync()

    def human_actor(self) -> Actor:
        return Actor(
            kind="human", id=self.settings.user, user=self.settings.user, session=self.session
        )

    def system_actor(self) -> Actor:
        return Actor(kind="system", id="factory", user=self.settings.user, session=self.session)


def slug_issues(slug: str) -> list[ValidationIssue]:
    if re.fullmatch(SLUG_RE, slug) is None:
        return [ValidationIssue("slug", "must be lowercase words joined by single hyphens")]
    if len(slug) > MAX_SLUG_LENGTH:
        return [ValidationIssue("slug", f"must be at most {MAX_SLUG_LENGTH} characters")]
    return []


def _id_floor(ids: IdGenerator) -> Callable[[str | None], None]:
    def floor(last_event_id: str | None) -> None:
        if last_event_id is not None:
            ids.floor(last_event_id.removeprefix("ev_"))

    return floor


def build_project(settings: Settings, slug: str, *, session: str, clock: Clock) -> Project:
    """Wire the storage layers for one project. Creates no directories."""
    paths = ProjectPaths(settings.root, slug)
    catalog = default_catalog()
    ids = IdGenerator(clock)
    blobs = BlobStore(paths.blobs_dir)
    return Project(
        paths=paths,
        settings=settings,
        session=session,
        clock=clock,
        ids=ids,
        catalog=catalog,
        blobs=blobs,
        library=BlobStore(paths.library_dir),
        events=EventFactory(slug, catalog, ids),
        writer=EventWriter(paths.events_dir, project=slug, catalog=catalog, blobs=blobs),
        index=Index(
            paths.index_path,
            paths.events_dir,
            catalog,
            default_projection(blobs),
            on_exclusive=_id_floor(ids),
        ),
    )


def open_project(settings: Settings, slug: str, *, session: str, clock: Clock) -> Project:
    if slug_issues(slug):
        raise ProjectNotFoundError(f"no project {slug!r}")
    paths = ProjectPaths(settings.root, slug)
    if not paths.events_dir.is_dir():
        raise ProjectNotFoundError(f"no project {slug!r}")
    return build_project(settings, slug, session=session, clock=clock)


def list_projects(settings: Settings) -> list[str]:
    projects_dir = settings.root / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir() if (p / "events").is_dir())
