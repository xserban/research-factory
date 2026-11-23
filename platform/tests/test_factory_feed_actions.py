"""Factory feed writes: react, train and the ranker's status (decision 169).

Same world as `test_factory_feed` (two projects, a fake embedder with chosen vectors; no network,
torch or weights), enlarged to six entries so that training can pass its thresholds."""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.model.feed import FeedRanked, FeedRankerTrained, FeedReacted, FeedReaction
from factory.services import factory_feed as ff
from factory.services import factory_feed_actions as acts
from factory.services import feed as feed_service
from factory.services.context import Project
from factory.services.factory_scope import open_factory_scope
from tests.helpers import SESSION
from tests.test_factory_feed import (  # noqa: F401 - `world` is a fixture
    VECTORS,
    FakeEmbedder,
    _fetch,
    _rec,
    _vec,
    world,
)

IDS = [f"2611.{n:05d}" for n in range(1, 7)]


@pytest.fixture
def six(world: tuple[Settings, Project, Project]) -> tuple[Settings, Project, Project]:  # noqa: F811
    settings, a, b = world
    VECTORS.update({"Paper 5": _vec(0.8, 0.5), "Paper 6": _vec(0, 0.3, 1)})
    _fetch(a, 3, [_rec(5), _rec(6)])
    return settings, a, b


def _rank(settings: Settings, clock: FixedClock) -> None:
    ff.rank_pool(settings, FakeEmbedder(), session=SESSION, clock=clock)


def _react(settings: Settings, clock: FixedClock, entry: str, reaction: str) -> str:
    return acts.react(settings, entry_id=entry, reaction=reaction, session=SESSION, clock=clock)


def _events(settings: Settings, clock: FixedClock, kind: str) -> list[Any]:
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    return [e for e in read_all(scope.paths.events_dir, scope.catalog) if e.type == kind]


def test_react_refuses_an_entry_in_no_ranking_and_writes_nothing(
    six: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = six
    with pytest.raises(FactoryValidationError) as none_yet:
        _react(settings, clock, IDS[0], "like")
    assert none_yet.value.issues[0].reason == "not-ranked"
    _rank(settings, clock)
    with pytest.raises(FactoryValidationError) as unknown:
        _react(settings, clock, "2699.99999", "like")
    assert (unknown.value.issues[0].field, unknown.value.issues[0].reason) == (
        "entry_id",
        "not-ranked",
    )
    with pytest.raises(FactoryValidationError):
        _react(settings, clock, IDS[0], "love")
    with pytest.raises(FactoryValidationError):
        _react(settings, clock, "not-an-id", "like")
    assert _events(settings, clock, "feed.reacted") == []


def test_react_writes_a_human_event_with_the_ranked_position(
    six: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = six
    _rank(settings, clock)
    event_id = _react(settings, clock, IDS[0], "like")
    (event,) = _events(settings, clock, "feed.reacted")
    assert event.id == event_id and event.actor.kind == "human" and event.actor.id == "obd"
    payload = FeedReacted.model_validate(event.payload)
    assert payload.reaction is FeedReaction.LIKE and payload.rank_shown >= 1
    assert payload.ranking_id.startswith("fdr_")
    # unset and unsave are factory-scope reactions; explicit card values are kept
    acts.react(
        settings,
        entry_id=IDS[0],
        reaction="unset",
        ranking_id=payload.ranking_id,
        rank_shown=3,
        score_shown=0.25,
        session=SESSION,
        clock=clock,
    )
    _react(settings, clock, IDS[1], "save")
    _react(settings, clock, IDS[1], "unsave")
    last = FeedReacted.model_validate(_events(settings, clock, "feed.reacted")[1].payload)
    assert (last.rank_shown, last.score_shown) == (3, 0.25)
    assert acts.collect_labels(settings, clock=clock) == {}
    assert ff.reading_list(settings, clock=clock) == []


def test_train_below_the_thresholds_refuses_with_the_reason_and_writes_nothing(
    six: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = six
    _rank(settings, clock)
    for entry in IDS[:3]:
        _react(settings, clock, entry, "like")
    status = acts.ranker_status(settings, clock=clock)
    assert not status.can_train and "3 reactions, 5 needed" in str(status.reason)
    assert (status.version, status.likes, status.dislikes) == (None, 3, 0)
    with pytest.raises(FactoryValidationError) as refused:
        acts.train(
            settings, FakeEmbedder(), session=SESSION, clock=clock, command_ref="cli:feed train"
        )
    assert "5 needed" in refused.value.issues[0].reason
    assert _events(settings, clock, "feed.ranker_trained") == []


needs_sklearn = pytest.mark.skipif(
    importlib.util.find_spec("sklearn") is None, reason="needs the ranker extra (scikit-learn)"
)


@needs_sklearn
def test_train_uses_factory_and_project_reactions_and_only_likes_and_dislikes(
    six: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, alpha, _ = six
    _rank(settings, clock)
    # a project like (the researcher's) enters the training set
    ranking = ff.today(settings, clock=clock).ranking_id
    assert ranking is not None
    _project_like(alpha, IDS[0])
    _react(settings, clock, IDS[1], "like")
    _react(settings, clock, IDS[2], "dislike")
    _react(settings, clock, IDS[3], "like")
    _react(settings, clock, IDS[4], "save")  # not a label
    _react(settings, clock, IDS[5], "dismiss")  # not a label
    assert acts.collect_labels(settings, clock=clock) == {
        IDS[0]: True,
        IDS[1]: True,
        IDS[2]: False,
        IDS[3]: True,
    }
    _react(settings, clock, IDS[2], "like")
    _react(settings, clock, IDS[2], "dislike")  # the latest of an entry wins
    _react(settings, clock, IDS[4], "dislike")
    assert acts.ranker_status(settings, clock=clock).can_train
    result = acts.train(
        settings, FakeEmbedder(), session=SESSION, clock=clock, command_ref="cli:feed train"
    )
    assert (result.version, result.likes, result.dislikes, result.skipped) == (1, 3, 2, 0)
    (event,) = _events(settings, clock, "feed.ranker_trained")
    assert event.actor.kind == "system"
    payload = FeedRankerTrained.model_validate(event.payload)
    assert payload.ids == tuple(IDS[:5]) and payload.triggered_by == "cli:feed train"
    assert payload.ranker_version == 1 and payload.state_blob.startswith("sha256:")
    scope = open_factory_scope(settings, session=SESSION, clock=clock)
    assert scope.blobs.get(payload.state_blob).startswith(b"{")  # JSON, no pickle
    # Today reflects the new ranker at once
    cards = ff.today(settings, clock=clock).cards
    assert {c.ranker_version for c in cards} == {1} and all(c.score is not None for c in cards)
    status = acts.ranker_status(settings, clock=clock)
    assert (status.version, status.trained_likes, status.trained_dislikes) == (1, 3, 2)
    assert status.trained_at is not None
    again = acts.train(
        settings, FakeEmbedder(), session=SESSION, clock=clock, command_ref="cli:feed train"
    )
    assert again.version == 2 and again.training_set_hash == result.training_set_hash


def test_labels_outside_the_pool_are_left_out(
    six: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = six
    _rank(settings, clock)
    for entry in IDS[:5]:
        _react(settings, clock, entry, "like")
    _react(settings, clock, IDS[5], "dislike")
    # drop one entry from the pool by pretending it is unknown: only 5 pool labels remain
    labels = acts.collect_labels(settings, clock=clock)
    assert len(labels) == 6
    VECTORS.pop("Paper 6")  # the fake embedder is never asked: Paper 6 is outside the labels below
    import factory.services.factory_feed as module

    pool = [e for e in module.load_pool(settings, clock=clock) if e.entry_id != IDS[5]]
    original = module.load_pool
    module.load_pool = lambda *_a, **_k: pool
    try:
        result = acts.train(
            settings, FakeEmbedder(), session=SESSION, clock=clock, command_ref="cli:feed train"
        )
    finally:
        module.load_pool = original
    assert result.skipped == 1 and result.dislikes == 0


def _project_like(project: Project, entry: str) -> None:
    """A like in a project's own feed: a ranking of the project showing the entry, then react."""
    payload = {
        "ranking_id": "fdr_" + "9" * 26,
        "fetch_ids": [f"fdf_{1:026d}"],
        "reference_hash": "a" * 64,
        "reference_count": 1,
        "model": "m",
        "weights_hash": "b" * 64,
        "software": "s",
        "parameters": {"shown_per_cycle": 3, "exploration_share": 0.0, "references": "core"},
        "exploration_seed": 1,
        "order_blob": project.blobs.put_json([]),
        "shown": [{"entry_id": entry, "rank": 1, "score": 0.9, "explore": False}],
    }
    event = project.events.make(
        "feed.ranked", FeedRanked.model_validate(payload), project.system_actor()
    )
    project.record([event])
    feed_service.react(project, project.human_actor(), entry, FeedReaction.LIKE)


def test_rank_after_fetch_notes_ranked_up_to_date_and_failed(
    six: tuple[Settings, Project, Project], clock: FixedClock
) -> None:
    settings, _, _ = six
    note = acts.rank_after_fetch(settings, FakeEmbedder, session=SESSION, clock=clock)
    assert note == "ranked 6 papers"
    assert acts.rank_after_fetch(settings, FakeEmbedder, session=SESSION, clock=clock) == (
        "up to date"
    )
    _fetch(six[1], 4, [_rec(7)])
    VECTORS["Paper 7"] = _vec(0.2, 0.2)

    def broken() -> FakeEmbedder:
        raise RuntimeError("no weights")

    failed = acts.rank_after_fetch(settings, broken, session=SESSION, clock=clock)
    assert failed == "failed: RuntimeError: no weights"
    assert ff.freshness(settings, clock=clock).stale  # nothing was written
