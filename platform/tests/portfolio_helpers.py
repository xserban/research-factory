"""Projects at known stages under one root, for the portfolio and human-queue tests.

Each builder reuses the screening and extraction helpers; `fresh` re-opens a project under a new
session, as the portfolio does.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from factory.clock import Clock, FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.identity import IdGenerator
from factory.services.context import Project, open_project
from factory.services.extraction_audit import extraction_audit_sample
from factory.services.project import init_project
from factory.sources.registry import SourceFactory
from tests import conftest
from tests.extraction_helpers import SESSION_A, SESSION_B, _both, _declare, _extractor
from tests.fulltext_helpers import _screened_full_text_world
from tests.helpers import SESSION, T0, install_skill
from tests.screening_helpers import _decide
from tests.test_agreement import _decide_four, _ordinary, _ready

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def fresh(settings: Settings, slug: str, clock: Clock) -> Project:
    """The project under a new session id, as `portfolio` opens it."""
    return open_project(settings, slug, session=IdGenerator(clock).ulid(), clock=clock)


def ta_world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    """Title/abstract screening with unresolved disagreements: an outcome conflict, an `unsure`
    and, when the corpus has a fifth ordinary work, a second outcome conflict. Returns the
    protocol id."""
    protocol_id = _ready(project, agent, human, mock_sources)
    taken = _decide_four(project, agent, protocol_id)
    rest = [w for w in _ordinary(project) if w not in taken]
    if rest:
        _decide(project, agent, rest[0], "B", "screening", "exclude", "EX01", protocol_id)
    return protocol_id


TA_SLUG = "alpha-ta"
EXT_SLUG = "bravo-extraction"
SCOPING_SLUG = "charlie-scoping"


def build_world(root: Path) -> None:
    """Three pilot projects under `root`: `alpha-ta` at title/abstract with unresolved
    disagreements, `bravo-extraction` with an extraction audit sampled and unlabelled, and
    `charlie-scoping`, freshly initialised. Built once per test session and copied per test."""
    settings = Settings(root=root, user="obd")
    install_skill(settings, "rf-screen")
    clock = FixedClock(T0)
    human = Actor(kind="human", id="obd", user="obd", session=SESSION)
    agent = Actor(
        kind="agent",
        id="screener-a",
        user="obd",
        session=SESSION,
        model="claude-opus-5-5",
        skill="rf-screen@1a2b3c4d",
    )
    agent_other = agent.model_copy(
        update={"id": "screener-b", "session": "01JZ9Q3K5M7N8P0R2S4T6V8W0Y"}
    )
    make_sources = conftest.mock_sources._get_wrapped_function()
    sources = make_sources([])

    ta = init_project(settings, TA_SLUG, "pilot", session=SESSION, clock=clock)
    ta_world(ta, agent, human, sources)

    ext = init_project(settings, EXT_SLUG, "pilot", session=SESSION, clock=clock)
    _screened_full_text_world(ext, agent, agent_other, human, sources)
    _declare(ext, agent)
    _both(ext, _extractor(SESSION_A, "claude-opus-5-5"), _extractor(SESSION_B, "claude-sonnet-5-5"))
    extraction_audit_sample(ext, human, random_seed=3)

    init_project(settings, SCOPING_SLUG, "exploratory", session=SESSION, clock=clock)
