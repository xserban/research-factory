"""The main hub's shared bar: one theme toggle in the bar, none in a framed page, the bar on every
main-hub page, and the palette that follows the toggle."""

from __future__ import annotations

from factory.services import site, site_chrome
from factory.services.site_theme import THEME_SCRIPT, THEME_TOGGLE


def test_theme_script_hides_toggles_in_a_framed_page() -> None:
    """A page inside the project hub's iframe follows the bar's toggle and shows none of its own."""
    assert "window.top!==window.self" in THEME_SCRIPT
    assert "[data-theme-toggle],.theme-row{display:none!important}" in THEME_SCRIPT


def test_bar_has_the_tabs_the_toggle_and_marks_the_active_tab() -> None:
    bar = site_chrome.hub_bar("feed")
    for _id, label, href in site_chrome.HUB_NAV:
        assert f"href='{href}'" in bar
        assert label in bar
    assert bar.count("data-theme-toggle") == 1
    assert "aria-current='page'" in bar
    # only the active tab is marked
    assert bar.count("aria-current") == 1
    assert "href='/feed/' aria-current='page'" in bar


def test_bar_with_no_active_tab_marks_none() -> None:
    assert "aria-current" not in site_chrome.hub_bar(None)


def test_with_bar_adds_script_style_and_bar_to_a_full_page() -> None:
    doc = "<!doctype html><html><head><title>x</title></head><body><main>hi</main></body></html>"
    out = site_chrome.with_bar(doc, "projects")
    assert out.count(THEME_SCRIPT) == 1
    assert out.index(THEME_SCRIPT) < out.index("<title>")
    assert "class=hubbar" in out
    assert out.index("class=hubbar") < out.index("<main>")
    assert out.count(THEME_TOGGLE) == 1


def test_with_bar_does_not_double_the_script_or_the_toggle_of_a_page_that_has_them() -> None:
    """`site.page` already carries the script and its own toggle row; the bar's toggle is the only
    one shown, and the script is not added twice."""
    doc = site.page("Backlog board", "<h1>b</h1>")
    out = site_chrome.with_bar(doc, "backlog")
    assert out.count(THEME_SCRIPT) == 1
    assert "class=theme-row" not in out
    assert out.count(THEME_TOGGLE) == 1


def test_with_bar_leaves_a_page_without_a_body_alone_but_still_valid() -> None:
    out = site_chrome.with_bar("<p>fragment</p>", None)
    assert "<p>fragment</p>" in out


def test_palette_follows_the_toggle_and_the_system_preference() -> None:
    css = site_chrome.PALETTE_CSS
    assert ':root[data-theme="light"]' in css
    assert ':root[data-theme="dark"]' in css
    # muted text stays text, not a border colour (the site palette's `mut` is a border)
    assert "--mut:#" in css


def test_bar_escapes_nothing_it_was_not_given_and_keeps_labels_plain() -> None:
    bar = site_chrome.hub_bar("projects")
    assert "<script" not in bar
