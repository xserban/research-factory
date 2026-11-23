"""The main hub's portal page (projects, each with a data portrait: activity per day and the
screening funnel) and the bar with the theme toggle on the portal and the feed page."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from factory.services import hub_ui, site_hub_feed, site_portal
from factory.services.site_chrome import BAR_CSS
from factory.services.site_theme import THEME_TOGGLE


def test_portal_has_the_bar_with_one_toggle_and_no_new_papers_list() -> None:
    page = site_portal.render_portal([])
    assert "class=hubbar" in page and page.count(THEME_TOGGLE) == 1
    assert "data-act" not in page and "pt-paper" not in page
    assert page.index("class=hubbar") < page.index("Conjecture</h1>")


def _row(**kw: object) -> site_portal.PortalRow:
    base: dict[str, object] = dict(
        slug="demo", title="Demo", events=10, stale=0, built=1, hub_ready=True
    )
    base.update(kw)
    return site_portal.PortalRow(**base)  # type: ignore[arg-type]


def test_activity_sparkline_has_one_bar_per_day_and_a_text_alternative() -> None:
    days = tuple([0] * 27 + [4, 0, 12])
    page = site_portal.render_portal([_row(activity=days, activity_end="2026-11-23")])
    spark = page[page.index("class=pt-spark") :]
    spark = spark[: spark.index("</svg>")]
    assert spark.count("<rect") == 30
    assert "role=img" in spark
    assert "16 events in the last 30 days" in page
    assert "busiest 23 Nov (12)" in page


def test_a_quiet_month_says_so_instead_of_drawing_flat_bars() -> None:
    page = site_portal.render_portal([_row(activity=(0,) * 30, activity_end="2026-11-23")])
    assert "No events in the last 30 days" in page and "class=pt-spark" not in page


def test_no_activity_data_draws_nothing() -> None:
    page = site_portal.render_portal([_row()])
    assert "pt-spark" not in page and "last 30 days" not in page


def test_funnel_shows_found_screened_included_with_widths_from_found() -> None:
    page = site_portal.render_portal([_row(funnel=(5760, 4296, 467))])
    assert "5,760 found" in page and "4,296 screened" in page and "467 included" in page
    assert "width:74.6%" in page and "width:8.1%" in page
    assert "pt-funnel" in page


def test_funnel_absent_or_empty_draws_nothing() -> None:
    assert "pt-funnel" not in site_portal.render_portal([_row()])
    assert "pt-funnel" not in site_portal.render_portal([_row(funnel=(0, 0, 0))])


def test_motion_is_off_when_the_reader_asks_for_reduced_motion() -> None:
    css = (Path(__file__).parents[1] / "src/factory/hub_ui/main-hub.css").read_text()
    assert "pt-grow" in css
    reduced = css[css.index("prefers-reduced-motion") :]
    assert "animation:none" in reduced.replace(" ", "")


def test_feed_page_has_the_bar_with_feed_active_and_one_toggle() -> None:
    page = site_hub_feed.render_feed_page([], {"available": False}, "hubtok")
    assert "class=hubbar" in page
    assert "href='/feed/' aria-current='page'" in page
    assert page.count(THEME_TOGGLE) == 1


def test_portal_is_a_kit_page_whose_stylesheet_carries_every_theme() -> None:
    page = site_portal.render_portal([])
    assert "/feed/assets/kit.css?v=" in page and "/feed/assets/main-hub.css?v=" in page
    kit = hub_ui.asset_bytes("kit.css").decode()
    assert ":root[data-theme=light]" in kit and ':root[data-theme="lcars"]' in kit
    styles = re.findall(r"<style>(.*?)</style>", page, re.S)
    assert styles == [BAR_CSS]  # the bar's own fallbacks; main-hub.css maps it to kit tokens


def test_portal_cards_open_the_new_hub_and_keep_the_classic_one_as_a_second_link() -> None:
    row = site_portal.PortalRow("demo", "Demo <b>", 1234, 0, 3, True)
    page = site_portal.render_portal([row])
    assert "href='/p/demo/ui/'" in page and "href='/p/demo/'" in page
    assert page.index("href='/p/demo/ui/'") < page.index("href='/p/demo/'")
    assert "Demo &lt;b&gt;" in page and "1,234" in page and "+ Up to date" in page


@pytest.mark.parametrize(
    ("row", "word"),
    [
        (site_portal.PortalRow("a", "a", 1, 0, 0, False), "Hub not built"),
        (site_portal.PortalRow("a", "a", 1, 4, 1, True), "4 to rebuild"),
        (site_portal.PortalRow("a", "a", 1, 0, 1, True, True), "Rebuilding"),
    ],
)
def test_portal_card_states_are_words_not_colour_alone(
    row: site_portal.PortalRow, word: str
) -> None:
    assert word in site_portal.render_portal([row])


def test_portal_with_no_project_says_what_to_do_next() -> None:
    page = site_portal.render_portal([], create_token="tok")
    assert "No project yet" in page and "factory init" in page and "id=create-form" in page


def test_every_standalone_page_comes_from_the_one_shell() -> None:
    from factory.services import site
    from factory.services.site_chrome import CONTAINER_WIDTH

    shell = f"max-width:{CONTAINER_WIDTH};margin:0 auto"
    feed = site_hub_feed.render_feed_page([], {"available": False, "running": False}, "tok")
    docs = {
        "feed": feed,
        "page": site.page("t", "<p>b</p>"),
    }
    for name, doc in docs.items():
        assert shell in doc, name
        assert "max-width:1100px" not in doc and "max-width:960px" not in doc, name
        assert site.THEME_CSS in doc, name  # the same control-room stylesheet as the catalog
    assert "<body class=portal>" in feed


def test_the_interface_name_is_conjecture_in_the_bar_and_the_portal() -> None:
    from factory.services.site_chrome import UI_NAME, hub_bar

    assert UI_NAME == "Conjecture"
    assert "<b>Conjecture</b>" in hub_bar("projects") and "FACTORY" not in hub_bar("projects")
    page = site_portal.render_portal([])
    assert "<h1>Conjecture</h1>" in page and "<title>Projects · Conjecture</title>" in page
