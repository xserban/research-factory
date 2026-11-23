"""The factory event scope (decision 169, proposed): reserved slug, allow-list, own projector."""

from pathlib import Path

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.catalog import default_catalog
from factory.events.envelope import Actor, Event
from factory.index import default as project_index
from factory.index import factory_scope as fx
from factory.model.feed import (
    FACTORY_ONLY_REACTIONS,
    FeedRankerTrained,
    FeedReacted,
    FeedReaction,
)
from factory.services import feed
from factory.services.context import Project, list_projects, slug_issues
from factory.services.factory_scope import FactoryScope, open_factory_scope
from factory.services.project import init_project
from tests.conftest import SESSION

RANKING = "fdr_" + "0" * 26
BLOB = "sha256:" + "a" * 64


@pytest.fixture
def scope(tmp_path: Path, clock: FixedClock) -> FactoryScope:
    return open_factory_scope(Settings(root=tmp_path, user="obd"), session=SESSION, clock=clock)


def _react(
    scope: FactoryScope, entry: str, reaction: FeedReaction, actor: Actor | None = None
) -> Event:
    payload = FeedReacted(
        entry_id=entry, reaction=reaction, ranking_id=RANKING, rank_shown=1, score_shown=0.5
    )
    return scope.events.make("feed.reacted", payload, actor or scope.human_actor(), refs=(entry,))


def _trained(
    version: int, ids: tuple[str, ...] = ("2401.00001", "2401.00002")
) -> FeedRankerTrained:
    return FeedRankerTrained(
        training_set_hash="b" * 64,
        ids=ids,
        likes=1,
        dislikes=len(ids) - 1,
        features=("cosine",),
        library_versions={"scikit-learn": "1.5"},
        state_blob=BLOB,
        ranker_version=version,
        triggered_by="cli:factory feed train",
    )


def test_layout_and_envelope(scope: FactoryScope, tmp_path: Path) -> None:
    scope.record([_react(scope, "2401.00001", FeedReaction.LIKE)])
    files = list((tmp_path / "factory" / "events" / "obd").glob("*.jsonl"))
    assert len(files) == 1
    assert Event.from_line(files[0].read_bytes().splitlines()[0]).project == "_factory"
    assert (tmp_path / "factory" / ".index" / "factory.sqlite").is_file()
    assert not (tmp_path / "projects").exists()


def test_other_types_are_refused_and_nothing_written(
    scope: FactoryScope, tmp_path: Path, clock: FixedClock
) -> None:
    good = _react(scope, "2401.00001", FeedReaction.LIKE)
    bad = good.model_copy(update={"type": "feed.sent"})
    with pytest.raises(FactoryValidationError) as exc:
        scope.record([good, bad])
    assert any("not a factory-scope event type" in i.reason for i in exc.value.issues)
    assert not list((tmp_path / "factory" / "events").glob("*/*.jsonl"))
    other = default_catalog()
    assert "project.created" in other and "project.created" not in scope.catalog
    assert scope.catalog.names() == ["feed.ranked", "feed.ranker_trained", "feed.reacted"]


def test_wrong_envelope_project_is_refused(scope: FactoryScope) -> None:
    event = _react(scope, "2401.00001", FeedReaction.LIKE).model_copy(update={"project": "demo"})
    with pytest.raises(FactoryValidationError):
        scope.record([event])


def test_agent_reaction_and_human_training_are_refused(scope: FactoryScope) -> None:
    agent = Actor(
        kind="agent", id="claude", user="obd", session=SESSION, model="m", skill="rf-feed@abcdef12"
    )
    payload = FeedReacted(
        entry_id="2401.00001",
        reaction=FeedReaction.LIKE,
        ranking_id=RANKING,
        rank_shown=1,
        score_shown=0.5,
    )
    event = scope.events.make("feed.reacted", payload, agent, input_blob=scope.blobs.put(b"{}"))
    with pytest.raises(FactoryValidationError):
        scope.record([event])
    training = scope.events.make("feed.ranker_trained", _trained(1), scope.human_actor())
    with pytest.raises(FactoryValidationError):
        scope.record([training])


def test_latest_reactions_unset_and_unsave(scope: FactoryScope) -> None:
    for entry, reaction in (
        ("2401.00001", FeedReaction.LIKE),
        ("2401.00001", FeedReaction.UNSET),
        ("2401.00002", FeedReaction.DISLIKE),
        ("2401.00002", FeedReaction.LIKE),
        ("2401.00003", FeedReaction.SAVE),
        ("2401.00003", FeedReaction.UNSAVE),
        ("2401.00004", FeedReaction.SAVE),
        ("2401.00004", FeedReaction.DISMISS),
    ):
        scope.record([_react(scope, entry, reaction)])
    state = scope.read(lambda c: fx.latest_reactions(c, scope.tables))
    assert state["2401.00001"] == {"label": None, "saved": None}
    assert state["2401.00002"] == {"label": "like", "saved": None}
    assert state["2401.00003"] == {"label": None, "saved": None}
    assert state["2401.00004"] == {"label": None, "saved": "save"}


def test_training_versions_must_follow_and_rebuild_is_deterministic(scope: FactoryScope) -> None:
    system = scope.system_actor()
    scope.record([scope.events.make("feed.ranker_trained", _trained(1), system)])
    scope.record([scope.events.make("feed.ranker_trained", _trained(3), system)])  # skips 2
    scope.record([scope.events.make("feed.ranker_trained", _trained(2), system)])
    scope.record([_react(scope, "2401.00001", FeedReaction.LIKE)])
    versions = scope.read(lambda c: fx.latest_version(c, scope.tables))
    assert versions == 2
    before = scope.index.state_hash()
    scope.index.rebuild()
    assert scope.index.state_hash() == before


def test_own_version_is_independent() -> None:
    assert fx.FACTORY_PROJECTION_VERSION != ""
    assert fx.FACTORY_PROJECTION_VERSION is not project_index.PROJECTION_VERSION


def test_slug_reserved_and_not_listed(tmp_path: Path, clock: FixedClock) -> None:
    settings = Settings(root=tmp_path, user="obd")
    issues = slug_issues("_factory")
    assert issues and "reserved" in issues[0].reason
    with pytest.raises(FactoryValidationError):
        init_project(settings, "_factory", "pilot", session=SESSION, clock=clock)
    init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    open_factory_scope(settings, session=SESSION, clock=clock)
    (tmp_path / "projects" / "_factory" / "events").mkdir(parents=True)
    assert list_projects(settings) == ["demo"]


def test_ranker_trained_model_guards() -> None:
    with pytest.raises(ValueError):
        FeedRankerTrained(**{**_trained(1).model_dump(), "likes": 5})
    with pytest.raises(ValueError):
        _trained(1, ids=("2401.00001", "2401.00001"))
    assert {FeedReaction.UNSET, FeedReaction.UNSAVE} == FACTORY_ONLY_REACTIONS


def test_project_feed_refuses_factory_only_reactions(project: Project) -> None:
    human = project.human_actor()
    for reaction in FACTORY_ONLY_REACTIONS:
        with pytest.raises(FactoryValidationError) as exc:
            feed.react(project, human, "2401.00001", reaction)
        assert exc.value.issues[0].field == "reaction"
