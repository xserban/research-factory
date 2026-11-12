"""The dashboard's feed and work-queue panel (feed-hub): None without a feed configuration, the
counts and titles from the events when there is one, titles escaped in the page, and one failing
read leaving the rest of the panel filled.

Events are recorded directly, as the feed read tests do.
"""

from __future__ import annotations

from typing import Any

import pytest

from factory.errors import FactoryError
from factory.services import dashboard as dashboard_service
from factory.services.context import Project
from factory.services.dashboard_page import render_page
from tests.test_feed_index import CONFIG, _record
from tests.test_feed_read import FETCH, FIRST, HELD, RANKING, REFERENCE, SECOND
from tests.test_inbox_model import ITEM, added

EVIL = "</script><b>Evil</b> paper"


def _config(project: Project) -> None:
    _record(project, "feed.configured", {"config_id": CONFIG, "categories": ["cs.AI"]})


def _fetch(project: Project) -> None:
    entries = [
        {"id": FIRST, "version": "v1", "title": EVIL},
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


def _ranked(project: Project) -> None:
    shown = [
        {"entry_id": FIRST, "rank": 1, "score": 0.9, "explore": False, "nearest_reference": None},
        {"entry_id": SECOND, "rank": 2, "score": 0.4, "explore": True, "nearest_reference": None},
        {"entry_id": HELD, "rank": 3, "score": 0.3, "explore": False, "nearest_reference": None},
    ]
    payload = {
        "ranking_id": RANKING,
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
    _config(project)
    _fetch(project)
    _ranked(project)
    _record(
        project,
        "feed.reacted",
        {
            "entry_id": FIRST,
            "reaction": "like",
            "ranking_id": RANKING,
            "rank_shown": 1,
            "score_shown": 0.9,
        },
    )
    _record(project, "inbox.link_added", added())
    _record(project, "feed.sent", {"entry_id": FIRST, "ranking_id": RANKING, "inbox_item_id": ITEM})


def test_no_feed_config_gives_no_panel(project: Project) -> None:
    state = dashboard_service.dashboard_state(project)
    assert state["feed"] is None
    assert '"feed": null' in render_page(state)


def test_counts_and_titles_from_events(project: Project) -> None:
    _world(project)
    state = dashboard_service.dashboard_state(project)
    feed = state["feed"]
    assert isinstance(feed, dict)
    assert feed["categories"] == ["cs.AI"]
    fetch: Any = feed["fetch"]
    assert fetch["last_window_from"] == "2026-11-10"
    assert fetch["last_window_to"] == "2026-11-11"
    assert fetch["next_due"] == "2026-11-12"
    ranking: Any = feed["ranking"]
    assert ranking["ranking_id"] == RANKING
    assert ranking["shown"] == 3
    assert ranking["explore"] == 1
    top: Any = feed["top"]
    assert [row["entry_id"] for row in top] == [FIRST, SECOND]
    assert top[0]["title"] == EVIL
    assert top[0]["score"] == 0.9
    assert top[0]["reaction"] == "like"
    assert top[0]["sent"] is True
    assert top[0]["reactions_7d"] == 1
    assert top[0]["adds_7d"] == 1
    assert top[1]["reaction"] is None
    assert top[1]["adds_7d"] == 0
    queue: Any = feed["queue"]
    assert queue["added"] == 1
    assert sum(queue["stages"].values()) == 1
    assert isinstance(queue["pending"], dict)
    run: Any = feed["run"]
    assert run["last"] is None
    assert run["run_open"] is False
    assert run["pipeline_open"] is False


def test_titles_are_escaped_in_the_page(project: Project) -> None:
    _world(project)
    html = render_page(dashboard_service.dashboard_state(project))
    assert EVIL not in html
    assert "<\\/script><b>Evil<\\/b> paper" in html


def test_failing_read_leaves_the_rest_filled(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _world(project)

    def refuse(*args: object, **kwargs: object) -> None:
        raise FactoryError("refused")

    monkeypatch.setattr(dashboard_service.feed_read_service, "feed_list", refuse)
    feed: Any = dashboard_service.dashboard_state(project)["feed"]
    assert feed["top"] == "unavailable"
    assert feed["ranking"]["shown"] == 3
    assert feed["queue"]["added"] == 1
    html = render_page(dashboard_service.dashboard_state(project))
    assert '"top": "unavailable"' in html
