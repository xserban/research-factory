from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor
from factory.events.factory import EventFactory
from factory.model.identity import IdGenerator
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
def factory(clock: FixedClock, cat: EventCatalog) -> EventFactory:
    return EventFactory("demo", cat, IdGenerator(clock))


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
