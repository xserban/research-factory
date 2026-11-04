"""Projects at known stages under one root, for the portfolio and human-queue tests.

Each builder reuses the screening and extraction helpers; `fresh` re-opens a project under a new
session, as the portfolio does.
"""

from collections.abc import Callable, Mapping

from factory.clock import Clock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.identity import IdGenerator
from factory.services.context import Project, open_project
from factory.sources.registry import SourceFactory
from tests.test_agreement import _decide_four, _ordinary, _ready
from tests.test_screening_next import _decide

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
