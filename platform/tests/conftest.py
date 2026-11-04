import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.blobs import BlobStore
from factory.events.catalog import EventCatalog, EventType
from factory.events.envelope import Actor
from factory.events.factory import EventFactory
from factory.events.writer import EventWriter
from factory.model.identity import IdGenerator
from factory.model.screening import PassLabel
from factory.model.search import QueryKind
from factory.model.work import Provenance
from factory.services.calibration import calibration_items
from factory.services.context import Project, open_project
from factory.services.project import init_project
from factory.services.screening import open_pass
from factory.services.search import list_works
from factory.sources.arxiv import ArxivSource
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import SourceFactory
from tests import world_cache
from tests.helpers import (
    FAKE_PAGES,
    S2,
    SESSION,
    T0,
    Demo,
    FakeSource,
    _setup,
    arxiv_atom,
    install_skill,
)
from tests.test_fulltext_service import _include_all
from tests.test_screening_next import _draw


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
    settings = Settings(root=tmp_path, user="obd")
    install_skill(settings, "rf-screen")
    return settings


@pytest.fixture
def project(settings: Settings, clock: FixedClock) -> Project:
    return init_project(settings, "demo", "pilot", session=SESSION, clock=clock)


@pytest.fixture
def explore_project(settings: Settings, clock: FixedClock) -> Project:
    """An exploratory project: searches are not gated by a protocol."""
    return init_project(settings, "demo", "exploratory", session=SESSION, clock=clock)


@pytest.fixture
def project_other_session(settings: Settings, clock: FixedClock, project: Project) -> Project:
    return open_project(settings, "demo", session=S2, clock=clock)


@pytest.fixture
def fake_sources() -> Callable[..., dict[str, SourceFactory]]:
    """Build a `sources` mapping whose only source is a scripted `FakeSource` named "fake".

    Defaults to `FAKE_PAGES` (three distinct records over two pages). Scripting arguments
    are passed straight to `FakeSource`.
    """

    def make(
        pages: list[list[dict[str, Any]]] | None = None,
        *,
        reported: int | None = None,
        fail_after: int | None = None,
        parse_fail_at: int | None = None,
        raise_at: int | None = None,
        raise_error: Exception | None = None,
    ) -> dict[str, SourceFactory]:
        source = FakeSource(
            pages if pages is not None else FAKE_PAGES,
            reported=reported,
            fail_after=fail_after,
            parse_fail_at=parse_fail_at,
            raise_at=raise_at,
            raise_error=raise_error,
        )
        return {"fake": SourceFactory(FakeSource.kinds, lambda _settings, _clock: source)}

    return make


@pytest.fixture
def http_log() -> list[httpx.Request]:
    """Every request the mocked sources receive, in order, for inspection."""
    return []


@pytest.fixture
def mock_sources(http_log: list[httpx.Request]) -> Callable[..., dict[str, SourceFactory]]:
    """Build a `sources` mapping of the REAL OpenAlex and arXiv adapters over MockTransport.

    No network: each adapter's HTTP client answers from the scripted payloads. `openalex` is the
    list of `results` entries; `openalex_count` overrides the `meta.count` it reports. `arxiv`
    is an Atom body (see `helpers.arxiv_atom`). Every request is appended to `http_log`.
    """

    def make(
        *,
        openalex: list[dict[str, Any]] | None = None,
        openalex_count: int | None = None,
        arxiv: str | None = None,
    ) -> dict[str, SourceFactory]:
        items = openalex or []
        count = len(items) if openalex_count is None else openalex_count
        atom = arxiv if arxiv is not None else arxiv_atom()

        def openalex_handler(request: httpx.Request) -> httpx.Response:
            http_log.append(request)
            page = {"meta": {"count": count, "next_cursor": None}, "results": items}
            return httpx.Response(200, json=page)

        def arxiv_handler(request: httpx.Request) -> httpx.Response:
            http_log.append(request)
            return httpx.Response(200, text=atom)

        def polite(handler: Callable[[httpx.Request], httpx.Response]) -> PoliteClient:
            transport = httpx.MockTransport(handler)
            return PoliteClient(httpx.Client(transport=transport), sleep=lambda _seconds: None)

        return {
            "openalex": SourceFactory(
                OpenAlexSource.kinds,
                lambda s, c: OpenAlexSource(polite(openalex_handler), clock=c, mailto=s.mailto),
            ),
            "arxiv": SourceFactory(
                ArxivSource.kinds,
                lambda s, c: ArxivSource(polite(arxiv_handler), clock=c, mailto=s.mailto),
                probe_kinds=frozenset({QueryKind.KEYWORD}),
            ),
        }

    return make


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> None:
    """Both passes opened and every ordinary work included, so several works are promoted."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


@pytest.fixture
def corpus_leaving(project: Project, agent: Actor, human: Actor, mock_sources: Any) -> str:
    """As `corpus`, but one ordinary work gets no decision, so it is not promoted. Returns it."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    calibration = set(calibration_items(project))
    leave = sorted(w.id for w in list_works(project) if w.id not in calibration)[0]
    _include_all(project, agent, human, protocol_id, leave=leave)
    return leave


@pytest.fixture(scope="session")
def portfolio_world_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three projects at known stages, built once per session (see `build_world`)."""
    from tests.portfolio_helpers import build_world

    root = tmp_path_factory.mktemp("portfolio-world")
    build_world(root)
    return root


@pytest.fixture
def portfolio_settings(portfolio_world_root: Path, tmp_path: Path) -> Settings:
    """A private copy of the portfolio world, safe for a test to modify."""
    root = tmp_path / "factory"
    shutil.copytree(portfolio_world_root, root)
    return Settings(root=root, user="obd")


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """With FACTORY_TEST_WORLD_CACHE_STATS=1, report how often world snapshots were reused."""
    if not os.environ.get("FACTORY_TEST_WORLD_CACHE_STATS"):
        return
    for (builder, outcome), count in sorted(world_cache.STATS.items()):
        terminalreporter.write_line(f"world cache: {builder} {outcome}: {count}")
