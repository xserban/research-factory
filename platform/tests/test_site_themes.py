"""The theme set: each theme defines every variable both page families read, meets the contrast
targets, is applied by the picker and by the saved choice, and cannot be overridden by the system
light preference."""

from __future__ import annotations

import pytest

from factory.services import hub_ui, site_chrome, site_theme, site_themes
from factory.services.site_theme import LIGHT, LIGHT_CSS, THEME_SCRIPT, THEME_TOGGLE
from tests.test_theme import _contrast, _luminance

IDS = [t.id for t in site_themes.THEMES]


def test_the_set_has_the_named_themes_and_lcars() -> None:
    assert {"tokyo-night", "catppuccin-mocha", "gruvbox", "nord", "rose-pine", "lcars"} <= set(IDS)
    assert len(IDS) == len(set(IDS))


@pytest.mark.parametrize("theme", site_themes.THEMES, ids=IDS)
def test_a_theme_defines_every_variable_of_both_families(theme: site_themes.Theme) -> None:
    assert set(theme.product_vars()) == set(LIGHT)
    assert set(theme.portal_vars()) == {"bg", "fg", "mut", "line", "card", "acc", "ok", "warn"}
    for value in (*theme.product_vars().values(), *theme.portal_vars().values()):
        assert value.startswith("#") and len(value) == 7


@pytest.mark.parametrize("theme", site_themes.THEMES, ids=IDS)
def test_a_theme_meets_the_contrast_targets(theme: site_themes.Theme) -> None:
    p = theme.palette
    for surface in (p["bg"], p["surface"], p["raised"]):
        assert _contrast(p["fg"], surface) >= 7.0, (theme.id, "fg", surface)
    for surface in (p["bg"], p["surface"]):
        assert _contrast(p["dim"], surface) >= 4.5, (theme.id, "dim", surface)
        assert _contrast(p["accent"], surface) >= 4.5, (theme.id, "accent", surface)
        assert _contrast(p["link"], surface) >= 4.5, (theme.id, "link", surface)


@pytest.mark.parametrize("theme", site_themes.THEMES, ids=IDS)
def test_each_theme_has_a_block_for_products_and_one_for_the_portal_pages(
    theme: site_themes.Theme,
) -> None:
    assert f':root[data-theme="{theme.id}"]{{' in site_themes.THEMES_CSS
    assert f':root[data-theme="{theme.id}"] body.portal{{' in site_themes.THEMES_CSS
    assert f':root[data-theme="{theme.id}"] .hubbar{{' in site_themes.THEMES_CSS


def test_themes_are_part_of_the_css_every_page_carries() -> None:
    assert site_themes.THEMES_CSS in LIGHT_CSS
    assert site_themes.THEMES_CSS in site_chrome.PALETTE_CSS


def test_the_system_light_preference_applies_only_when_no_choice_is_saved() -> None:
    assert ":root:not([data-theme]){" in LIGHT_CSS
    assert ':root:not([data-theme="dark"])' not in LIGHT_CSS


def test_the_picker_offers_system_dark_light_and_every_theme() -> None:
    assert THEME_TOGGLE.startswith("<select")
    assert "data-theme-toggle" in THEME_TOGGLE and "aria-label='Switch theme'" in THEME_TOGGLE
    for ident in ("", "dark", "light", *IDS):
        assert f"<option value='{ident}'" in THEME_TOGGLE


def test_the_script_only_accepts_known_choices_and_listens_for_changes() -> None:
    assert "addEventListener('change'" in THEME_SCRIPT
    for ident in ("dark", "light", *IDS):
        assert f"'{ident}'" in THEME_SCRIPT
    assert "try{localStorage.setItem(K,n)}catch(e){}" in THEME_SCRIPT


def test_lcars_has_pill_buttons_and_an_uppercase_bar() -> None:
    lcars = next(t for t in site_themes.THEMES if t.id == "lcars")
    css = site_themes.THEMES_CSS
    assert lcars.palette["bg"] == "#000000"
    assert ':root[data-theme="lcars"] button' in css
    assert "border-radius:999px" in css
    assert "text-transform:uppercase" in css


def test_the_theme_module_imports_nothing_from_the_package() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(site_themes))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module is not None and not node.module.startswith("factory")
    assert site_theme.SAVE_KEY == "factory-theme"


NEW_IDS = [
    "ethereal", "aetheria", "cyberpunk-dreams", "circuit-horizon", "moon-orbit", "solitude",
    "vantablack", "kanagawa", "paper-blue", "sepia", "cool-grey", "catppuccin-latte",
    "flexoki-light", "solarized-light",
]  # fmt: skip


def test_the_new_themes_are_present_and_match_the_hub_ids_and_names() -> None:
    assert set(NEW_IDS) <= set(IDS)
    assert [t.id for t in hub_ui.THEMES][2:] == IDS
    assert [t.label for t in site_themes.THEMES] == [t.label for t in hub_ui.THEMES][2:]


@pytest.mark.parametrize("theme", site_themes.THEMES, ids=IDS)
def test_both_uis_use_the_same_palette(theme: site_themes.Theme) -> None:
    spec = next(s for s in hub_ui.THEMES if s.id == theme.id)
    p = theme.palette
    assert (spec.bg, spec.surface, spec.raised) == (p["bg"], p["surface"], p["raised"])
    assert (spec.fg, spec.dim, spec.acc) == (p["fg"], p["dim"], p["accent"])


@pytest.mark.parametrize("theme", [t for t in site_themes.THEMES if t.id in NEW_IDS], ids=NEW_IDS)
def test_a_new_theme_keeps_muted_text_and_semantic_colours_readable(
    theme: site_themes.Theme,
) -> None:
    p = theme.palette
    for surface in (p["bg"], p["surface"], p["raised"]):
        assert _contrast(p["soft"], surface) >= 7.0, (theme.id, "soft", surface)
        assert _contrast(p["dim"], surface) >= 4.5, (theme.id, "dim", surface)
    for key in ("good", "warn", "bad", "violet", "cyan"):
        for surface in (p["bg"], p["surface"]):
            assert _contrast(p[key], surface) >= 4.5, (theme.id, key, surface)
    assert len({p["good"], p["warn"], p["bad"], p["violet"], p["cyan"]}) == 5


@pytest.mark.parametrize("theme", site_themes.THEMES, ids=IDS)
def test_a_light_theme_declares_light_and_drops_the_dark_decoration(
    theme: site_themes.Theme,
) -> None:
    root = f':root[data-theme="{theme.id}"]'
    css = theme.css()
    assert (root + "{color-scheme:light;" in css) is theme.light
    assert (root + "{color-scheme:dark;" in css) is not theme.light
    if theme.light:
        assert root + " body{background-image:none}" in css
        assert root + " .led,.led.stale,.led.bad,header .logo{box-shadow:none}" in css
        assert _contrast(theme.palette["fg"], theme.palette["bg"]) >= 7.0
        assert _luminance(theme.palette["bg"]) > _luminance(theme.palette["fg"])


def test_there_are_light_themes_among_the_new_ones() -> None:
    light = {t.id for t in site_themes.THEMES if t.light}
    assert len(light) >= 4 and light <= set(NEW_IDS)
    assert set(site_themes.LIGHT_IDS) == light


def test_the_picker_groups_themes_into_dark_and_light() -> None:
    dark, light = THEME_TOGGLE.split("<optgroup label='Light'>")
    assert "<optgroup label='Dark'>" in dark
    for ident in site_themes.LIGHT_IDS:
        assert f"<option value='{ident}'" in light and f"<option value='{ident}'" not in dark
    for ident in site_themes.DARK_IDS:
        assert f"<option value='{ident}'" in dark
