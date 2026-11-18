"""Colour tokens of the hub: WCAG AA on every named theme, and kit.css agrees with THEMES.

The kit.css file is the design source; THEMES in services/hub_ui.py is the single
Python copy. The equality test parses kit.css so the two cannot drift apart.
"""

from __future__ import annotations

import re
from importlib import resources

import pytest

from factory.services.hub_ui import THEMES, ThemeSpec, contrast_ratio

_TOKEN_ATTRS = ("bg", "surface", "raised", "fg", "mut", "dim", "acc", "acc_ink", "inc", "exc")
# :root{...} is the dark default; :root[data-theme=light] and :root[data-theme="x"] are the others.
_BLOCK = re.compile(r'(?<![\w-]):root(?:\[data-theme=(?:"([^"]+)"|([a-z-]+))\])?\s*\{([^}]*)\}')


def _kit_css() -> str:
    return resources.files("factory").joinpath("hub_ui", "kit.css").read_text(encoding="utf-8")


def _parse_kit_themes(css: str) -> dict[str, dict[str, str]]:
    """Map theme id to {css token name: hex value} for the ten contrast tokens."""
    out: dict[str, dict[str, str]] = {}
    for match in _BLOCK.finditer(css):
        quoted, bare, body = match.group(1), match.group(2), match.group(3)
        theme_id = quoted or bare or "dark"
        tokens: dict[str, str] = {}
        for attr in _TOKEN_ATTRS:
            name = attr.replace("_", "-")
            found = re.search(rf"--{re.escape(name)}:\s*(#[0-9a-fA-F]{{3,6}})\s*;", body)
            if found is not None:
                tokens[name] = found.group(1).lower()
        if tokens:
            out.setdefault(theme_id, {}).update(tokens)
    return out


def _theme(theme_id: str) -> ThemeSpec:
    for spec in THEMES:
        if spec.id == theme_id:
            return spec
    raise AssertionError(f"no theme {theme_id}")


THEME_IDS = [spec.id for spec in THEMES]


def test_eight_themes_in_kit_order() -> None:
    assert THEME_IDS == [
        "dark",
        "light",
        "tokyo-night",
        "catppuccin-mocha",
        "gruvbox",
        "nord",
        "rose-pine",
        "lcars",
    ]


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_kit_css_block_matches_themes(theme_id: str) -> None:
    parsed = _parse_kit_themes(_kit_css())
    assert theme_id in parsed, f"kit.css has no block for {theme_id}"
    spec = _theme(theme_id)
    for attr in _TOKEN_ATTRS:
        name = attr.replace("_", "-")
        assert parsed[theme_id][name] == getattr(spec, attr).lower(), (
            f"{theme_id}: --{name} differs between kit.css and THEMES"
        )


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_text_on_grounds_meets_aa(theme_id: str) -> None:
    t = _theme(theme_id)
    for ground in (t.bg, t.surface, t.raised):
        assert contrast_ratio(t.fg, ground) >= 4.5, f"{theme_id}: fg on {ground}"
    for ground in (t.bg, t.surface):
        assert contrast_ratio(t.mut, ground) >= 4.5, f"{theme_id}: mut on {ground}"
    assert contrast_ratio(t.dim, t.bg) >= 4.5, f"{theme_id}: dim on bg (small text)"


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_accent_and_outcome_pairs_meet_aa(theme_id: str) -> None:
    t = _theme(theme_id)
    assert contrast_ratio(t.acc, t.bg) >= 3.0, f"{theme_id}: acc on bg"
    assert contrast_ratio(t.acc_ink, t.acc) >= 4.5, f"{theme_id}: acc_ink on acc"
    assert contrast_ratio(t.inc, t.surface) >= 3.0, f"{theme_id}: inc on surface"
    assert contrast_ratio(t.exc, t.surface) >= 3.0, f"{theme_id}: exc on surface"


def test_contrast_black_on_white_is_21() -> None:
    assert contrast_ratio("#000", "#fff") == pytest.approx(21.0)
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#fff", "#000") == pytest.approx(21.0)


def test_contrast_same_colour_is_one() -> None:
    assert contrast_ratio("#5fd4e8", "#5FD4E8") == pytest.approx(1.0)


def test_contrast_rejects_bad_hex() -> None:
    with pytest.raises(ValueError):
        contrast_ratio("#12345", "#000")
    with pytest.raises(ValueError):
        contrast_ratio("red", "#000")
