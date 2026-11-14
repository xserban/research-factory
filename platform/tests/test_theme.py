"""The light theme: palette, contrast, toggle and pre-paint script on every page builder."""

from __future__ import annotations

from factory.services import dashboard_page, site, site_explorer_page
from factory.services.context import Project
from factory.services.site_charts import CHART_CSS
from factory.services.site_theme import (
    LIGHT,
    LIGHT_CSS,
    SAVE_KEY,
    THEME_SCRIPT,
    THEME_TOGGLE,
)

LIGHT_ROOT = ':root[data-theme="light"]'
AUTO_ROOT = ":root:not([data-theme])"

PALETTE = (
    "#FFFFFF",
    "#F5F7FB",
    "#E8EEF8",
    "#D9E1EC",
    "#1B2333",
    "#5B6478",
    "#1E40AF",
    "#1D4ED8",
    "#DBEAFE",
    "#166534",
    "#92400E",
    "#B91C1C",
)


def _channel(c: int) -> float:
    x = c / 255
    return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4


def _luminance(hex_: str) -> float:
    h = hex_.lstrip("#")
    r, g, b = (_channel(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hub(project: Project) -> str:
    site.site_dir(project).mkdir(parents=True, exist_ok=True)
    path = site.render_hub(project, [], pending=[])
    return path.read_text(encoding="utf-8")


def _pages(project: Project) -> dict[str, str]:
    return {
        "dashboard": dashboard_page.render_page(),
        "hub": _hub(project),
        "product": site.page("Daily updates", "<p>body</p>", ""),
        "explorer": site_explorer_page.PAGE,
    }


def test_palette_values_are_in_the_light_block() -> None:
    for value in PALETTE:
        assert value in LIGHT_CSS
    assert LIGHT["bg"] == "#FFFFFF"
    assert LIGHT["ac"] == "#1D4ED8"
    assert LIGHT["dim"] == "#5B6478"


def test_light_block_is_selected_by_attribute_and_by_system_preference() -> None:
    assert LIGHT_CSS.startswith(f"{LIGHT_ROOT}{{")
    assert "@media (prefers-color-scheme: light){" in LIGHT_CSS
    assert f"{AUTO_ROOT}{{" in LIGHT_CSS
    assert "color-scheme:light" in LIGHT_CSS


def test_body_text_and_muted_text_meet_their_contrast_targets() -> None:
    surfaces = (LIGHT["bg"], LIGHT["panel"], LIGHT["sel"])
    for surface in surfaces:
        assert _contrast(LIGHT["fg"], surface) >= 7.0
        assert _contrast(LIGHT["dim"], surface) >= 4.5
    for surface in (LIGHT["bg"], LIGHT["panel"]):
        assert _contrast(LIGHT["ac"], surface) >= 4.5


def test_dark_only_decoration_is_switched_off_in_light() -> None:
    for root in (LIGHT_ROOT, AUTO_ROOT):
        assert f"{root} body{{background-image:none}}" in LIGHT_CSS
        assert f"{root} .led" in LIGHT_CSS


def test_chart_css_reads_theme_variables() -> None:
    assert "var(--chart)" in CHART_CSS
    assert "rgba(8,9,16" not in CHART_CSS
    assert "#fff" not in CHART_CSS


def test_toggle_is_an_accessible_picker_wired_by_the_script() -> None:
    assert "data-theme-toggle" in THEME_TOGGLE
    assert "aria-label='Switch theme'" in THEME_TOGGLE
    assert "data-theme-toggle" in THEME_SCRIPT
    assert "addEventListener('change'" in THEME_SCRIPT
    assert f"'{SAVE_KEY}'" in THEME_SCRIPT


def test_saved_choice_is_read_in_a_try_block() -> None:
    assert "try{var v=localStorage.getItem(K)" in THEME_SCRIPT
    assert "try{localStorage.setItem(K,n)}catch(e){}" in THEME_SCRIPT


def test_every_page_builder_carries_the_light_block_toggle_and_script(
    project: Project,
) -> None:
    for name, html in _pages(project).items():
        assert LIGHT_ROOT in html, name
        assert "prefers-color-scheme: light" in html, name
        assert "data-theme-toggle" in html, name
        assert "aria-label='Switch theme'" in html, name
        assert THEME_SCRIPT in html, name
        assert html.index(THEME_SCRIPT) < html.index("<style>"), name


def test_pre_paint_script_runs_before_the_stylesheet(project: Project) -> None:
    for name, html in _pages(project).items():
        head = html.split("</head>", 1)[0]
        assert "<script>(function(){var K=" in head, name


def test_template_markers_are_all_replaced(project: Project) -> None:
    for name, html in _pages(project).items():
        for marker in ("<!--THEME-->", "<!--TOGGLE-->", "/*LIGHT*/"):
            assert marker not in html, (name, marker)


def test_hub_bar_holds_the_picker(project: Project) -> None:
    html = _hub(project)
    assert "class=hubbar" in html
    bar = html.split("<div class=shell>", 1)[0]
    assert "data-theme-toggle" in bar
    assert "<header" not in html


def test_project_hub_has_the_main_hub_bar_with_its_context_and_a_filter_in_the_sidebar(
    project: Project,
) -> None:
    html = _hub(project)
    assert "href='/' aria-current='page'" in html
    assert "// demo" in html and "EVENTS" in html
    nav = html.split("<nav>", 1)[1].split("</nav>", 1)[0]
    assert "id=q" in nav
