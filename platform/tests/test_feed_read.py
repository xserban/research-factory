"""The feed listing (slice 4c, F6): order, explore flag, reaction and sent state, held entries
never listed, unknown ranking refused, empty listing.

Events are recorded directly, as the other feed index tests do. The corpus title lookup is
replaced by a stub, so the fixture needs no search run.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.model.feed import FeedReaction
from factory.services import feed_read
from factory.services.context import Project
from factory.services.feed_read import FeedListing, feed_list
from tests.test_feed_index import _record
from tests.test_inbox_model import ITEM, added

ULID = "01HZX3K4M5N6P7Q8R9S0TVWXYZ"
FETCH = f"fdf_{ULID}"
RANKING = f"fdr_{ULID}"
UNKNOWN_RANKING = f"fdr_{ULID[:-1]}A"
FIRST = "2611.01234"
SECOND = "2611.01235"
HELD = "2611.01236"
REFERENCE = "rf:paper-0000aaaa"
TITLES = {REFERENCE: "A core reference"}


@pytest.fixture
def stub_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_work(project: Project, work_id: str) -> Any:
        title = TITLES.get(work_id)
        return None if title is None else SimpleNamespace(title=title)

    monkeypatch.setattr(feed_read, "get_work", fake_get_work)


def _fetch(project: Project) -> None:
    entries = [
        {"id": FIRST, "version": "v1", "title": "First paper"},
        {"id": SECOND, "version": "v1", "title": "Second paper"},
        {"id": HELD, "version": "v1", "title": "Held paper", "held_work_id": REFERENCE},
    ]
    payload = {
        "fetch_id": FETCH,
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),  # type: ignore[arg-type]
        "count": 3,
        "held_count": 1,
        "complete": True,
    }
    _record(project, "feed.fetched", payload, project.system_actor())


def _ranked(project: Project, ranking: str = RANKING) -> None:
    shown = [
        {
            "entry_id": FIRST,
            "rank": 1,
            "score": 0.9,
            "explore": False,
            "nearest_reference": REFERENCE,
        },
        {"entry_id": SECOND, "rank": 2, "score": 0.4, "explore": True, "nearest_reference": None},
        {
            "entry_id": HELD,
            "rank": 3,
            "score": 0.3,
            "explore": False,
            "nearest_reference": REFERENCE,
        },
    ]
    payload = {
        "ranking_id": ranking,
        "fetch_ids": [FETCH],
        "reference_hash": "a" * 64,
        "reference_count": 1,
        "model": "m",
        "weights_hash": "b" * 64,
        "software": "s",
        "parameters": {"shown_per_cycle": 3, "exploration_share": 0.3, "references": "core"},
        "exploration_seed": 1,
        "order_blob": project.blobs.put_json([]),
        "shown": shown,
    }
    _record(project, "feed.ranked", payload, project.system_actor())


def _world(project: Project) -> None:
    _fetch(project)
    _ranked(project)


def _listing(project: Project, **kwargs: Any) -> FeedListing:
    return feed_list(project, **kwargs)


def test_items_follow_shown_order_with_explore_and_nearest_title(
    project: Project, stub_titles: None
) -> None:
    _world(project)
    listing = _listing(project)
    assert listing.ranking_id == RANKING
    assert listing.reason is None
    assert [item.entry_id for item in listing.items] == [FIRST, SECOND]
    first, second = listing.items
    assert (first.rank, first.score, first.explore) == (1, 0.9, False)
    assert (second.rank, second.score, second.explore) == (2, 0.4, True)
    assert first.title == "First paper"
    assert first.nearest_reference == REFERENCE
    assert first.nearest_reference_title == "A core reference"
    assert second.nearest_reference is None
    assert second.nearest_reference_title is None


def test_held_entries_are_never_listed(project: Project, stub_titles: None) -> None:
    _world(project)
    assert HELD not in [item.entry_id for item in _listing(project).items]


def test_top_takes_a_prefix_of_the_shown_order(project: Project, stub_titles: None) -> None:
    _world(project)
    assert [item.entry_id for item in _listing(project, top=1).items] == [FIRST]
    assert _listing(project, top=0).items == ()


def test_reaction_and_sent_state(project: Project, stub_titles: None) -> None:
    _world(project)
    _record(project, "inbox.link_added", added())
    reaction: dict[str, Any] = {
        "entry_id": FIRST,
        "reaction": "like",
        "ranking_id": RANKING,
        "rank_shown": 1,
        "score_shown": 0.9,
    }
    _record(project, "feed.reacted", reaction)
    _record(
        project,
        "feed.sent",
        {"entry_id": FIRST, "ranking_id": RANKING, "inbox_item_id": ITEM},
    )
    first, second = _listing(project).items
    assert first.reaction is FeedReaction.LIKE
    assert first.sent is True
    assert first.inbox_item_id == ITEM
    assert second.reaction is None
    assert second.sent is False
    assert second.inbox_item_id is None


def test_latest_reaction_wins(project: Project, stub_titles: None) -> None:
    _world(project)
    base: dict[str, Any] = {
        "entry_id": FIRST,
        "ranking_id": RANKING,
        "rank_shown": 1,
        "score_shown": 0.9,
    }
    _record(project, "feed.reacted", {**base, "reaction": "like"})
    _record(project, "feed.reacted", {**base, "reaction": "dismiss"})
    assert _listing(project).items[0].reaction is FeedReaction.DISMISS


def test_named_ranking_is_listed(project: Project, stub_titles: None) -> None:
    _world(project)
    other = f"fdr_{ULID[:-2]}AB"
    _ranked(project, ranking=other)
    assert _listing(project).ranking_id == other
    assert _listing(project, ranking_id=RANKING).ranking_id == RANKING


def test_unknown_ranking_is_refused(project: Project, stub_titles: None) -> None:
    _world(project)
    with pytest.raises(FactoryValidationError) as raised:
        feed_list(project, ranking_id=UNKNOWN_RANKING)
    assert [(i.field, i.reason) for i in raised.value.issues] == [("ranking_id", "unknown")]


def test_empty_listing_before_any_ranking(project: Project) -> None:
    listing = feed_list(project)
    assert listing.ranking_id is None
    assert listing.reference_hash is None
    assert listing.reason == "no ranking yet"
    assert listing.items == ()


def test_listing_is_repeatable(project: Project, stub_titles: None) -> None:
    _world(project)
    assert feed_list(project) == feed_list(project)
