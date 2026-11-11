"""The Daily updates product page (plan 2026-11-11-feed-hub, H1): cards in shown order, the explore
and added badges, the abstract and authors from the fetch blob, and the no-config page.

Events are recorded directly, as the other feed tests do. The corpus title lookup is stubbed.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from factory.services import feed_read
from factory.services.context import Project
from factory.services.site_feed import build_feed
from tests.test_feed_index import CONFIG, _record
from tests.test_feed_read import FIRST, HELD, RANKING, REFERENCE, SECOND, TITLES, _fetch, _ranked
from tests.test_inbox_model import ITEM, added


@pytest.fixture
def stub_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_work(project: Project, work_id: str) -> Any:
        title = TITLES.get(work_id)
        return None if title is None else SimpleNamespace(title=title)

    monkeypatch.setattr(feed_read, "get_work", fake_get_work)


def _configure(project: Project) -> None:
    _record(project, "feed.configured", {"config_id": CONFIG, "categories": ["cs.AI"]})


def _world(project: Project) -> None:
    _configure(project)
    _fetch(project)
    _ranked(project)


def _html(project: Project, tmp_path: Path) -> str:
    build_feed(project, tmp_path)
    return (tmp_path / "index.html").read_text(encoding="utf-8")


def _cards(html: str) -> dict[str, str]:
    """Each card's markup, keyed by entry id, in page order (the dict keeps insertion order)."""
    parts = re.split(r"<article class=card ", html)[1:]
    out: dict[str, str] = {}
    for part in parts:
        match = re.search(r"data-entry-id='([^']+)'", part)
        assert match is not None
        out[match.group(1)] = part.split("</article>", 1)[0]
    return out


def test_cards_follow_shown_order_and_held_entries_are_absent(
    project: Project, stub_titles: None, tmp_path: Path
) -> None:
    _world(project)
    html = _html(project, tmp_path)
    cards = _cards(html)
    assert list(cards) == [FIRST, SECOND]
    assert HELD not in html
    assert "#1" in cards[FIRST] and "0.900" in cards[FIRST]
    assert "#2" in cards[SECOND] and "0.400" in cards[SECOND]
    assert f"https://arxiv.org/abs/{FIRST}" in cards[FIRST]
    assert "A core reference" in cards[FIRST]


def test_explore_badge_only_on_explore_items(
    project: Project, stub_titles: None, tmp_path: Path
) -> None:
    _world(project)
    cards = _cards(_html(project, tmp_path))
    assert "badge explore" in cards[SECOND]
    assert "badge explore" not in cards[FIRST]


def test_added_badge_after_send(project: Project, stub_titles: None, tmp_path: Path) -> None:
    _world(project)
    assert "badge added" not in _cards(_html(project, tmp_path))[FIRST]
    _record(project, "inbox.link_added", added())
    _record(
        project,
        "feed.sent",
        {"entry_id": FIRST, "ranking_id": RANKING, "inbox_item_id": ITEM},
    )
    cards = _cards(_html(project, tmp_path))
    assert "badge added" in cards[FIRST]
    assert "badge added" not in cards[SECOND]


def test_buttons_are_disabled_placeholders(
    project: Project, stub_titles: None, tmp_path: Path
) -> None:
    _world(project)
    card = _cards(_html(project, tmp_path))[FIRST]
    for act in ("like", "dislike", "save", "dismiss", "add"):
        assert f"data-act='{act}' disabled" in card


def test_abstract_and_authors_come_from_the_fetch_blob(
    project: Project, stub_titles: None, tmp_path: Path
) -> None:
    _configure(project)
    entries = [
        {
            "id": FIRST,
            "version": "v1",
            "title": "First paper",
            "abstract": "A short abstract.",
            "authors": ["A. Author", "B. Writer"],
        },
        {"id": SECOND, "version": "v1", "title": "Second paper"},
    ]
    payload = {
        "fetch_id": "fdf_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
        "categories": ["cs.AI"],
        "window_from": "2026-11-10",
        "window_to": "2026-11-11",
        "raw_blobs": [],
        "entries_blob": project.blobs.put_json(entries),  # type: ignore[arg-type]
        "count": 2,
        "held_count": 0,
        "complete": True,
    }
    _record(project, "feed.fetched", payload, project.system_actor())
    _ranked(project)
    cards = _cards(_html(project, tmp_path))
    assert "A short abstract." in cards[FIRST]
    assert "<details>" in cards[FIRST]
    assert "A. Author, B. Writer" in cards[FIRST]
    assert "abstract" not in cards[SECOND]
    assert "A. Author" not in cards[SECOND]


def test_no_config_says_so_and_shows_the_command(
    project: Project, tmp_path: Path
) -> None:
    html = _html(project, tmp_path)
    assert "no feed configuration" in html
    assert "factory feed configure" in html
    assert "<article" not in html


def test_configured_without_ranking_says_no_ranking(project: Project, tmp_path: Path) -> None:
    _configure(project)
    html = _html(project, tmp_path)
    assert "no ranking yet" in html
    assert "<article" not in html
    assert "factory feed configure" not in html


def test_nearest_reference_missing_title_falls_back_to_none_text(
    project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(feed_read, "get_work", lambda project, work_id: None)
    _world(project)
    cards = _cards(_html(project, tmp_path))
    assert REFERENCE in cards[FIRST]
    assert "no core paper nearby" in cards[SECOND]
