import re
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Self

from factory.clock import Clock
from factory.config import Settings
from factory.errors import OrderingError, ProjectNotFoundError, ValidationIssue
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, default_catalog
from factory.events.envelope import Actor, Event
from factory.events.factory import EventFactory
from factory.events.library import LabLibrary, ProjectLibrary
from factory.events.writer import EventWriter
from factory.index.default import default_projection
from factory.index.index import Index
from factory.index.levels import attach_level_reader
from factory.index.library import referenced_check
from factory.index.project import latest_host
from factory.model.identity import SLUG_RE, IdGenerator, ulid_time
from factory.model.lab import LAB_SLUG
from factory.model.screening import Channel
from factory.services.call_memo import invalidate

MAX_SLUG_LENGTH = 64
FUTURE_MARGIN = timedelta(minutes=1)
"""How far past the clock an event may be dated and still set the ID floor. A later one (a logged
event can never be removed) would otherwise push every later `ts` past it for good."""


@dataclass(frozen=True)
class Principal:
    """Who is acting (slice 5, "Principal and actor"): the source of every actor. On stdio and the
    local CLI it is `Settings.user` with no credential, so stage 0 behaves as before."""

    user: str
    credential: str | None
    channel: Channel

    @classmethod
    def local(cls, settings: Settings, channel: Channel) -> Self:
        return cls(user=settings.user, credential=None, channel=channel)


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
    library: ProjectLibrary
    events: EventFactory
    writer: EventWriter
    index: Index
    principal: Principal

    def writing(self) -> AbstractContextManager[None]:
        """The project write context: holds the lock and syncs. On a hosted project it also floors
        `ids` above the last applied event, so an event minted inside sorts after the whole log and
        append order equals ID order across sessions and processes (slice 5 ruling 3). Re-entrant.

        An unhosted project keeps its IDs as they were (ruling 2). A future-dated last event sets no
        floor: IDs follow the clock, and the index rebuilds as it does for any out-of-order event.

        It is `index.exclusive()`: `build_project` wires the floor into the lock, so the services
        that take the lock directly mint under the same guarantee."""
        return self.index.exclusive()

    def is_hosted(self) -> bool:
        return hosted_by(self.index) is not None

    def record(self, events: Sequence[Event]) -> None:
        """Append and fold under the write lock. On a hosted project, refuse with nothing written a
        batch that does not sort after the log, and append the rest in ID order. A future-dated last
        event is no measure of order: nothing can sort after it, so the batch is appended."""
        with self.writing():
            # A foreign machine is not asked about order: the writer refuses it, naming the host.
            host = hosted_by(self.index) if events else None
            if host is not None and host == self.settings.host_id:
                last = self.index.last_event_id()
                ordered = last is None or future_dated(last, self.clock.now())
                if not ordered and min(event.id for event in events) <= str(last):
                    raise OrderingError(f"event minted outside writing(): not after {last}")
                events = sorted(events, key=lambda event: event.id)
            self.index.appended()  # before the write: a failed write leaves it unknown too
            self.writer.append(events)
            self.index.sync()
            invalidate()  # a call-scoped memo must not outlive this write

    def human_actor(self) -> Actor:
        return Actor(
            kind="human",
            id=self.principal.user,
            user=self.principal.user,
            session=self.session,
            credential=self.principal.credential,
        )

    def system_actor(self) -> Actor:
        return Actor(
            kind="system",
            id="factory",
            user=self.principal.user,
            session=self.session,
            credential=self.principal.credential,
        )


def slug_issues(slug: str) -> list[ValidationIssue]:
    """Why `slug` cannot name a new project. `lab` is the lab log's envelope slug."""
    if slug == LAB_SLUG:
        return [ValidationIssue("slug", f"{LAB_SLUG!r} is reserved for the lab registry")]
    return _format_issues(slug)


def _format_issues(slug: str) -> list[ValidationIssue]:
    if re.fullmatch(SLUG_RE, slug) is None:
        return [ValidationIssue("slug", "must be lowercase words joined by single hyphens")]
    if len(slug) > MAX_SLUG_LENGTH:
        return [ValidationIssue("slug", f"must be at most {MAX_SLUG_LENGTH} characters")]
    return []


def hosted_by(index: Index) -> str | None:
    """The project's host, as of the log: the outermost lock syncs, and a hold already taken has
    folded everything, so reading it inside `writing()` costs one query."""
    with index.exclusive(), index.connect() as conn:
        return latest_host(conn)


def future_dated(event_id: str, now: datetime) -> bool:
    """Whether an event is dated past `now` by more than `FUTURE_MARGIN`."""
    return ulid_time(event_id.removeprefix("ev_")) > now + FUTURE_MARGIN


def build_project(
    settings: Settings,
    slug: str,
    *,
    session: str,
    clock: Clock,
    principal: Principal | None = None,
) -> Project:
    """Wire the storage layers for one project. Creates no directories. The principal defaults to
    the local user at the command line."""
    paths = ProjectPaths(settings.root, slug)
    catalog = default_catalog()
    ids = IdGenerator(clock)
    blobs = BlobStore(paths.blobs_dir)

    def floor_ids(last_event_id: str | None) -> None:
        if last_event_id is None or hosted_by(index) is None:
            return
        if not future_dated(last_event_id, clock.now()):
            ids.floor(last_event_id.removeprefix("ev_"))

    projection = default_projection(blobs)
    attach_level_reader(projection, paths.events_dir, catalog)
    index = Index(
        paths.index_path,
        paths.events_dir,
        catalog,
        projection,
        on_exclusive=floor_ids,
        on_write_lock=invalidate,  # a decision under the lock never uses a pre-lock memo value
        hold_window=settings.index_hold,
    )
    return Project(
        paths=paths,
        settings=settings,
        session=session,
        clock=clock,
        ids=ids,
        catalog=catalog,
        blobs=blobs,
        library=ProjectLibrary(
            BlobStore(paths.library_dir), LabLibrary(settings.root), referenced_check(index)
        ),
        events=EventFactory(slug, catalog, ids),
        writer=EventWriter(
            paths.events_dir,
            project=slug,
            catalog=catalog,
            blobs=blobs,
            host_guard=lambda: hosted_by(index),
            host_id=settings.host_id,
        ),
        index=index,
        principal=principal or Principal.local(settings, Channel.CLI),
    )


def open_project(
    settings: Settings,
    slug: str,
    *,
    session: str,
    clock: Clock,
    principal: Principal | None = None,
) -> Project:
    # Format only: a project named `lab` before the slug was reserved stays readable.
    if _format_issues(slug):
        raise ProjectNotFoundError(f"no project {slug!r}")
    paths = ProjectPaths(settings.root, slug)
    if not paths.events_dir.is_dir():
        raise ProjectNotFoundError(f"no project {slug!r}")
    return build_project(settings, slug, session=session, clock=clock, principal=principal)


def list_projects(settings: Settings) -> list[str]:
    projects_dir = settings.root / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir() if (p / "events").is_dir())
