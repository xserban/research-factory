from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.model.identity import IdGenerator
from factory.model.work import Provenance
from factory.services.context import Project, open_project
from factory.services.project import init_project
from tests.helpers import S2, SESSION, T0, Demo


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def session_id() -> str:
    return SESSION


@pytest.fixture
def cat() -> EventCatalog:
    catalog = EventCatalog()
    catalog.register(EventType("demo.recorded", Demo, 1))
    return catalog


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    return tmp_path / "events"


@pytest.fixture
def writer(events_dir: Path, cat: EventCatalog, blobs: BlobStore) -> EventWriter:
    return EventWriter(events_dir, project="demo", catalog=cat, blobs=blobs)


@pytest.fixture
def factory(clock: FixedClock, cat: EventCatalog) -> EventFactory:
    return EventFactory("demo", cat, IdGenerator(clock))


@pytest.fixture
def prov() -> Provenance:
    return Provenance(
        source="openalex",
        run_id=f"run_{SESSION}",
        query_id=f"qry_{SESSION}",
        at=T0,
        raw_blob="sha256:" + "a" * 64,
    )


@pytest.fixture
def human() -> Actor:
    return Actor(kind="human", id="obd", user="obd", session=SESSION)


@pytest.fixture
def other_session_human() -> Actor:
    return Actor(kind="human", id="obd", user="obd", session=S2)


@pytest.fixture
def agent() -> Actor:
    return Actor(
        kind="agent",
        id="screener-a",
        user="obd",
        session=SESSION,
        model="claude-opus-5-5",
        skill="rf-screen@1a2b3c4d",
    )


@pytest.fixture
def agent_other() -> Actor:
    return Actor(
        kind="agent",
        id="screener-b",
        user="obd",
        session=S2,
        model="claude-opus-5-5",
        skill="rf-screen@1a2b3c4d",
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(root=tmp_path, user="obd")


@pytest.fixture
def project(settings: Settings, clock: FixedClock) -> Project:
    return init_project(settings, "demo", "pilot", session=SESSION, clock=clock)


@pytest.fixture
def project_other_session(settings: Settings, clock: FixedClock, project: Project) -> Project:
    return open_project(settings, "demo", session=S2, clock=clock)
