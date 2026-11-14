"""The named colour themes of the hub (beside the built-in dark and light).

A theme is one compact palette. It is expanded into the two sets of CSS variables the pages read:
the product family (`bg, dk, panel, ac, amber, ...`, the same names as `site_theme.LIGHT`) on
`:root[data-theme="<id>"]`, and the main hub family (`bg, fg, mut, line, card, acc, ok, warn`, where
`mut` is muted text, not a border) on `body.portal` inside it. The bar's own variables are set on
`.hubbar`. A theme may add a few extra rules (LCARS: pill buttons, an uppercase bar).

Invariants:
- Pure data and string functions; this module imports nothing from the package.
- Every theme is dark-on-light-text with a palette that meets the contrast targets the tests check
  (text 7:1, muted text, accent and link 4.5:1 on the page and panel surfaces).
- Colours are fixed constants of this module; nothing from outside is written into the CSS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

PALETTE_KEYS: Final = (
    "bg",  # page
    "surface",  # panels, navigation, cards
    "raised",  # selected and hovered rows
    "border",
    "fg",  # text
    "soft",  # secondary text
    "dim",  # muted text
    "accent",
    "link",
    "good",
    "warn",
    "bad",
    "violet",
    "cyan",
)


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    palette: dict[str, str]
    extra: tuple[tuple[str, str], ...] = field(default=())
    """Extra rules as (selector, declarations); the selector is prefixed with the theme's root."""

    def product_vars(self) -> dict[str, str]:
        p = self.palette
        return {
            "bg": p["bg"],
            "dk": p["surface"],
            "lt": p["surface"],
            "panel": p["surface"],
            "card": p["surface"],
            "navbg": p["surface"],
            "sel": p["raised"],
            "hi": p["raised"],
            "hov": p["raised"],
            "chart": p["bg"],
            "mut": p["border"],
            "line": p["border"],
            "fg": p["fg"],
            "ink": p["fg"],
            "light": p["soft"],
            "dim": p["dim"],
            "ac": p["accent"],
            "acc": p["accent"],
            "bright": p["link"],
            "blue": p["link"],
            "soft": p["raised"],
            "heat": p["link"],
            "mag": p["violet"],
            "cyan": p["cyan"],
            "green": p["good"],
            "brown": p["good"],
            "amber": p["warn"],
            "red": p["bad"],
        }

    def portal_vars(self) -> dict[str, str]:
        p = self.palette
        return {
            "bg": p["bg"],
            "fg": p["fg"],
            "mut": p["dim"],
            "line": p["border"],
            "card": p["surface"],
            "acc": p["accent"],
            "ok": p["good"],
            "warn": p["warn"],
        }

    def bar_vars(self) -> dict[str, str]:
        p = self.palette
        return {
            "hb-bg": p["surface"],
            "hb-fg": p["fg"],
            "hb-mut": p["dim"],
            "hb-line": p["border"],
            "hb-acc": p["accent"],
        }

    def css(self) -> str:
        root = f':root[data-theme="{self.id}"]'
        out = [
            root + "{color-scheme:dark;" + _decls(self.product_vars()) + "}",
            root + " body.portal{" + _decls(self.portal_vars()) + "}",
            root + " .hubbar{" + _decls(self.bar_vars()) + "}",
        ]
        out.extend(f"{root} {sel}{{{decl}}}" for sel, decl in self.extra)
        return "".join(out)


def _decls(values: dict[str, str]) -> str:
    return "".join(f"--{k}:{v};" for k, v in values.items())


THEMES: Final[tuple[Theme, ...]] = (
    Theme(
        "tokyo-night",
        "Tokyo Night",
        {
            "bg": "#1a1b26",
            "surface": "#1f2335",
            "raised": "#292e42",
            "border": "#3b4261",
            "fg": "#c0caf5",
            "soft": "#a9b1d6",
            "dim": "#8b95c4",
            "accent": "#7aa2f7",
            "link": "#7dcfff",
            "good": "#9ece6a",
            "warn": "#e0af68",
            "bad": "#f7768e",
            "violet": "#bb9af7",
            "cyan": "#7dcfff",
        },
    ),
    Theme(
        "catppuccin-mocha",
        "Catppuccin Mocha",
        {
            "bg": "#1e1e2e",
            "surface": "#181825",
            "raised": "#313244",
            "border": "#45475a",
            "fg": "#cdd6f4",
            "soft": "#bac2de",
            "dim": "#a6adc8",
            "accent": "#cba6f7",
            "link": "#89b4fa",
            "good": "#a6e3a1",
            "warn": "#f9e2af",
            "bad": "#f38ba8",
            "violet": "#cba6f7",
            "cyan": "#94e2d5",
        },
    ),
    Theme(
        "gruvbox",
        "Gruvbox",
        {
            "bg": "#282828",
            "surface": "#32302f",
            "raised": "#3c3836",
            "border": "#504945",
            "fg": "#ebdbb2",
            "soft": "#d5c4a1",
            "dim": "#a89984",
            "accent": "#fe8019",
            "link": "#83a598",
            "good": "#b8bb26",
            "warn": "#fabd2f",
            "bad": "#fb4934",
            "violet": "#d3869b",
            "cyan": "#8ec07c",
        },
    ),
    Theme(
        "nord",
        "Nord",
        {
            "bg": "#2e3440",
            "surface": "#3b4252",
            "raised": "#434c5e",
            "border": "#4c566a",
            "fg": "#eceff4",
            "soft": "#d8dee9",
            "dim": "#aab4c8",
            "accent": "#88c0d0",
            "link": "#a9c4e0",
            "good": "#a3be8c",
            "warn": "#ebcb8b",
            "bad": "#bf616a",
            "violet": "#b48ead",
            "cyan": "#8fbcbb",
        },
    ),
    Theme(
        "rose-pine",
        "Rosé Pine",
        {
            "bg": "#191724",
            "surface": "#1f1d2e",
            "raised": "#26233a",
            "border": "#403d52",
            "fg": "#e0def4",
            "soft": "#c4c1da",
            "dim": "#908caa",
            "accent": "#c4a7e7",
            "link": "#9ccfd8",
            "good": "#9ccfd8",
            "warn": "#f6c177",
            "bad": "#eb6f92",
            "violet": "#c4a7e7",
            "cyan": "#9ccfd8",
        },
    ),
    Theme(
        "lcars",
        "LCARS",
        {
            "bg": "#000000",
            "surface": "#0b0910",
            "raised": "#1c1628",
            "border": "#7a6a9a",
            "fg": "#ffcc99",
            "soft": "#ffcc99",
            "dim": "#cc99cc",
            "accent": "#ff9900",
            "link": "#99ccff",
            "good": "#99cc99",
            "warn": "#ffcc66",
            "bad": "#ff7777",
            "violet": "#cc99cc",
            "cyan": "#99ccff",
        },
        extra=(
            ("button,.tab,.chip,input,select", "border-radius:999px"),
            ("body", "background-image:none"),
            (".hubbar", "border-bottom:6px solid var(--ac);border-radius:0 0 0 28px;height:46px"),
            (
                ".hubbar b",
                "background:var(--ac);color:#000;padding:9px 18px;border-radius:999px 0 0 999px",
            ),
            (
                ".hubbar a,.hubbar b,header b,nav h3",
                "text-transform:uppercase;letter-spacing:.14em",
            ),
            (".hubbar a[aria-current]", "background:var(--ac);color:#000;border-radius:999px"),
            ("nav a.i.on", "background:var(--ac);color:#000;border-radius:0 999px 999px 0"),
        ),
    ),
)

THEMES_CSS: Final = "".join(t.css() for t in THEMES)
"""Every theme's blocks; appended to the light block and to the main hub palette."""

IDS: Final = tuple(t.id for t in THEMES)
