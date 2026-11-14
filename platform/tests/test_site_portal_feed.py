"""The short New papers panel on the main hub's portal page: the top entries over all projects,
with the react buttons, and the bar with the theme toggle on the portal and the feed page."""

from __future__ import annotations

from factory.services import site_hub_feed, site_portal
from factory.services.feed_read import FeedListing, FeedListItem
from factory.services.site_theme import THEME_TOGGLE


def _item(
    entry: str, rank: int, score: float, title: str | None = None, explore: bool = False
) -> FeedListItem:
    return FeedListItem(
        entry_id=entry,
        title=title or f"Title {entry}",
        rank=rank,
        score=score,
        explore=explore,
        nearest_reference="W1",
        nearest_reference_title="A core work",
        reaction=None,
        sent=False,
        inbox_item_id=None,
    )


def _view(
    slug: str, items: list[FeedListItem], ranking: str | None = "rk1"
) -> site_hub_feed.ProjectFeed:
    listing = FeedListing(ranking_id=ranking, reference_hash=None, reason=None, items=tuple(items))
    return site_hub_feed.ProjectFeed(slug, slug.title(), f"tok-{slug}", listing=listing)


def test_top_entries_are_the_best_scores_over_all_projects() -> None:
    a = _view("a", [_item("1", 1, 0.9), _item("2", 2, 0.5)])
    b = _view("b", [_item("3", 1, 0.8), _item("4", 2, 0.7)])
    top = site_hub_feed.top_entries([a, b], 3)
    assert [(t.slug, t.item.entry_id) for t in top] == [("a", "1"), ("b", "3"), ("b", "4")]


def test_top_entries_skip_projects_without_a_ranking_or_with_an_error() -> None:
    none = _view("n", [], ranking=None)
    bad = site_hub_feed.ProjectFeed("e", "E", "t", error="boom")
    plain = site_hub_feed.ProjectFeed("p", "P", "t")
    ok = _view("a", [_item("1", 1, 0.4)])
    top = site_hub_feed.top_entries([none, bad, plain, ok], 5)
    assert [t.slug for t in top] == ["a"]


def test_top_entries_ties_keep_project_then_shown_order() -> None:
    a = _view("a", [_item("1", 1, 0.5), _item("2", 2, 0.5)])
    b = _view("b", [_item("3", 1, 0.5)])
    assert [t.item.entry_id for t in site_hub_feed.top_entries([a, b], 5)] == ["1", "2", "3"]


def test_panel_shows_title_project_score_nearest_work_react_buttons_and_the_link() -> None:
    top = site_hub_feed.top_entries(
        [_view("a", [_item("2611.0001", 1, 0.912, "A <b>paper</b>")])], 5
    )
    html = site_hub_feed.render_feed_panel(top, shown_total=30)
    assert "A &lt;b&gt;paper&lt;/b&gt;" in html
    assert "<b>paper</b>" not in html
    assert "0.912" in html
    assert "A core work" in html
    assert "data-act='like'" in html and "data-act='dislike'" in html
    assert "data-act='add'" not in html
    assert "data-slug='a'" in html and "data-token='tok-a'" in html
    assert "data-ranking-id='rk1'" in html and "data-entry-id='2611.0001'" in html
    assert "href='/feed/'" in html


def test_panel_with_no_entries_says_so_and_still_links_to_the_page() -> None:
    html = site_hub_feed.render_feed_panel([], shown_total=0)
    assert "No new papers yet" in html
    assert "href='/feed/'" in html


def test_portal_carries_the_panel_and_the_bar_with_one_toggle() -> None:
    panel = site_hub_feed.render_feed_panel(
        site_hub_feed.top_entries([_view("a", [_item("1", 1, 0.5)])], 5), shown_total=1
    )
    page = site_portal.render_portal([], feed_panel=panel)
    assert "class=hubbar" in page
    assert page.count(THEME_TOGGLE) == 1
    assert "New papers" in page and "data-act='like'" in page
    assert page.index("class=hubbar") < page.index("Factory</h1>")


def test_portal_without_a_panel_still_renders_with_the_bar() -> None:
    page = site_portal.render_portal([])
    assert "class=hubbar" in page and "data-act" not in page


def test_feed_page_has_the_bar_with_feed_active_and_one_toggle() -> None:
    page = site_hub_feed.render_feed_page([], {"available": False}, "hubtok")
    assert "class=hubbar" in page
    assert "href='/feed/' aria-current='page'" in page
    assert page.count(THEME_TOGGLE) == 1


def test_portal_palette_follows_an_explicit_choice() -> None:
    page = site_portal.render_portal([])
    assert ':root[data-theme="light"]' in page and ':root[data-theme="dark"]' in page
