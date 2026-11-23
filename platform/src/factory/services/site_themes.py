"""The named colour themes of the hub (beside the built-in dark and light).

A theme is one compact palette. It is expanded into the two sets of CSS variables the pages read:
the product family (`bg, dk, panel, ac, amber, ...`, the same names as `site_theme.LIGHT`) on
`:root[data-theme="<id>"]`, and the main hub family (`bg, fg, mut, line, card, acc, ok, warn`, where
`mut` is muted text, not a border) on `body.portal` inside it. The bar's own variables are set on
`.hubbar`. A theme may add a few extra rules (LCARS: pill buttons, an uppercase bar).

Invariants:
- Pure data and string functions; this module imports nothing from the package.
- A theme is dark (light text on a dark page) unless `light=True` (dark text on a light page, with
  `color-scheme:light` and the dark-only decoration switched off). Every theme has a palette that
  meets the contrast targets the tests check (text 7:1, muted text, accent and link 4.5:1 on the
  page and panel surfaces).
- Colours are fixed constants of this module; nothing from outside is written into the CSS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

LIGHT_DECOR: Final[tuple[tuple[str, str], ...]] = (
    ("body", "background-image:none"),
    (".led,.led.stale,.led.bad,header .logo", "box-shadow:none"),
)
"""Dark-only decoration (grid background, glows), switched off under every light theme."""

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
    light: bool = False
    """A light theme: dark text on a light page."""

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
            root
            + "{color-scheme:"
            + ("light" if self.light else "dark")
            + ";"
            + _decls(self.product_vars())
            + "}",
            root + " body.portal{" + _decls(self.portal_vars()) + "}",
            root + " .hubbar{" + _decls(self.bar_vars()) + "}",
        ]
        if self.light:
            out.extend(f"{root} {sel}{{{decl}}}" for sel, decl in LIGHT_DECOR)
        out.extend(f"{root} {sel}{{{decl}}}" for sel, decl in self.extra)
        return "".join(out)


def _decls(values: dict[str, str]) -> str:
    return "".join(f"--{k}:{v};" for k, v in values.items())


# The themes after LCARS were mapped from Omarchy colour files (or are original paper palettes).
# A source colour that missed a contrast target was moved toward white (dark themes) or black
# (light themes) in 3% steps until it passed; each theme's comment lists what changed. Solitude and
# Vantablack are greyscale in the source, so their good, warn, bad, violet and cyan carry a hue that
# the source lacks (semantic colours must stay distinguishable); the derived values are marked.
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
    # ethereal: Omarchy ethereal. Adjusted for contrast: dim #6d7db6->#7685ba
    Theme(
        "ethereal",
        "Ethereal",
        {
            "bg": "#060B1E",
            "surface": "#0b1129",
            "raised": "#131a3a",
            "border": "#252e56",
            "fg": "#ffcead",
            "soft": "#c9b8a6",
            "dim": "#7685ba",
            "accent": "#7d82d9",
            "link": "#c2c4f0",
            "good": "#92a593",
            "warn": "#E9BB4F",
            "bad": "#ED5B5A",
            "violet": "#c89dc1",
            "cyan": "#a3bfd1",
        },
    ),
    # aetheria: Omarchy aetheria. Adjusted for contrast: soft #11AEB3->#2eb8bc, violet
    #   #9147a8->#a86eba
    Theme(
        "aetheria",
        "Aetheria",
        {
            "bg": "#0e091d",
            "surface": "#150f28",
            "raised": "#1f1638",
            "border": "#3a2a5c",
            "fg": "#14B9B5",
            "soft": "#2eb8bc",
            "dim": "#11AEB3",
            "accent": "#FD3E6A",
            "link": "#04C5F0",
            "good": "#7cd699",
            "warn": "#ffbe74",
            "bad": "#f93d3b",
            "violet": "#a86eba",
            "cyan": "#5fd0e0",
        },
    ),
    # cyberpunk-dreams: Omarchy cyberpunk-dreams. Adjusted for contrast: dim #9483C4->#aa9dd0,
    #   accent #EB6BED->#ec74ee, bad #FF3D7F->#ff77a5, violet #9B8CFF->#a496ff
    Theme(
        "cyberpunk-dreams",
        "Cyberpunk Dreams",
        {
            "bg": "#240B39",
            "surface": "#2d1048",
            "raised": "#352B82",
            "border": "#4a3d9e",
            "fg": "#EBE2FB",
            "soft": "#d3c4f0",
            "dim": "#aa9dd0",
            "accent": "#ec74ee",
            "link": "#7CC3E0",
            "good": "#39D8A0",
            "warn": "#F5D76E",
            "bad": "#ff77a5",
            "violet": "#a496ff",
            "cyan": "#A8E6F5",
        },
    ),
    # circuit-horizon: Omarchy circuit-horizon. No colour adjusted.
    Theme(
        "circuit-horizon",
        "Circuit Horizon",
        {
            "bg": "#080F18",
            "surface": "#0c1621",
            "raised": "#142330",
            "border": "#285567",
            "fg": "#D7E8EE",
            "soft": "#BDD2DC",
            "dim": "#7895A3",
            "accent": "#43D9E6",
            "link": "#83B6EA",
            "good": "#91CFAC",
            "warn": "#FFCA80",
            "bad": "#F47783",
            "violet": "#B6A4E8",
            "cyan": "#8CECF3",
        },
    ),
    # moon-orbit: Omarchy moon-orbit. Adjusted for contrast: fg #6096fd->#bfd5fe, soft
    #   #a09bd3->#d3d1eb, dim #7b79a4->#aba9c5, accent #a09bd3->#aba7d8, link
    #   #6096fd->#81acfd, bad #ee897d->#f09489, violet #c192c0->#c89fc8
    Theme(
        "moon-orbit",
        "Moon Orbit",
        {
            "bg": "#2d2940",
            "surface": "#353150",
            "raised": "#403b5e",
            "border": "#5a5480",
            "fg": "#bfd5fe",
            "soft": "#d3d1eb",
            "dim": "#aba9c5",
            "accent": "#aba7d8",
            "link": "#81acfd",
            "good": "#00ffd2",
            "warn": "#fca766",
            "bad": "#f09489",
            "violet": "#c89fc8",
            "cyan": "#7fd4e8",
        },
    ),
    # solitude: Omarchy solitude. Adjusted for contrast: soft #a5aeb4->#adb5bb, dim
    #   #4b4e55->#919397, bad #de6145->#e16f56
    Theme(
        "solitude",
        "Solitude",
        {
            "bg": "#101315",
            "surface": "#161a1d",
            "raised": "#232a2d",
            "border": "#343d41",
            "fg": "#cacccc",
            "soft": "#adb5bb",
            "dim": "#919397",
            "accent": "#a8adb0",
            "link": "#9db7c9",
            "good": "#9fb99a",
            "warn": "#d9b36c",
            "bad": "#e16f56",
            "violet": "#a99bc4",
            "cyan": "#86b4bd",
        },
    ),
    # vantablack: Omarchy vantablack. Adjusted for contrast: dim #7a7a7a->#828282
    Theme(
        "vantablack",
        "Vantablack",
        {
            "bg": "#000000",
            "surface": "#090909",
            "raised": "#1a1a1a",
            "border": "#333333",
            "fg": "#ffffff",
            "soft": "#ececec",
            "dim": "#828282",
            "accent": "#cecece",
            "link": "#b0b0b0",
            "good": "#8fcf9e",
            "warn": "#e0b861",
            "bad": "#ef7b6b",
            "violet": "#b4a0d6",
            "cyan": "#86c5d4",
        },
    ),
    # kanagawa: Omarchy kanagawa. Adjusted for contrast: soft #c8c093->#cfc8a0, dim
    #   #727169->#a1a09a, accent #7e9cd8->#86a2da, bad #e82424->#f28080, violet
    #   #957fb8->#ab9ac7, cyan #7aa89f->#7eaba2
    Theme(
        "kanagawa",
        "Kanagawa",
        {
            "bg": "#1f1f28",
            "surface": "#272733",
            "raised": "#363646",
            "border": "#54546D",
            "fg": "#dcd7ba",
            "soft": "#cfc8a0",
            "dim": "#a1a09a",
            "accent": "#86a2da",
            "link": "#7fb4ca",
            "good": "#98bb6c",
            "warn": "#e6c384",
            "bad": "#f28080",
            "violet": "#ab9ac7",
            "cyan": "#7eaba2",
        },
    ),
    # paper-blue: site_theme LIGHT (white and blue). No colour adjusted.
    Theme(
        "paper-blue",
        "Paper Blue",
        {
            "bg": "#FFFFFF",
            "surface": "#F4F7FC",
            "raised": "#E8EEF8",
            "border": "#D9E1EC",
            "fg": "#1B2333",
            "soft": "#2E3850",
            "dim": "#5B6478",
            "accent": "#1D4ED8",
            "link": "#1E40AF",
            "good": "#166534",
            "warn": "#92400E",
            "bad": "#B91C1C",
            "violet": "#6D28D9",
            "cyan": "#0E7490",
        },
        light=True,
    ),
    # sepia: original warm paper. No colour adjusted.
    Theme(
        "sepia",
        "Sepia",
        {
            "bg": "#f4ecd8",
            "surface": "#fbf5e6",
            "raised": "#ebe1c8",
            "border": "#d8ccaa",
            "fg": "#3b2f22",
            "soft": "#54443a",
            "dim": "#6f5f4c",
            "accent": "#9c4a1a",
            "link": "#1f5f8b",
            "good": "#3f6b2a",
            "warn": "#8a5a00",
            "bad": "#a8321f",
            "violet": "#6f4a8e",
            "cyan": "#1f6b72",
        },
        light=True,
    ),
    # cool-grey: original grey-white. Adjusted for contrast: good #1f7a3d->#1e763b, cyan
    #   #0e7490->#0e718c
    Theme(
        "cool-grey",
        "Cool Grey",
        {
            "bg": "#f3f5f7",
            "surface": "#ffffff",
            "raised": "#e6eaee",
            "border": "#cfd6dd",
            "fg": "#1c2127",
            "soft": "#2f3740",
            "dim": "#56616d",
            "accent": "#0f766e",
            "link": "#1d4ed8",
            "good": "#1e763b",
            "warn": "#8a5a00",
            "bad": "#b42318",
            "violet": "#6d3fc0",
            "cyan": "#0e718c",
        },
        light=True,
    ),
    # catppuccin-latte: Omarchy catppuccin-latte. Adjusted for contrast: fg #4c4f69->#3a3c50,
    #   soft #5c5f77->#383a49, dim #6c6f85->#555869, accent #1e66f5->#1851c2, link
    #   #1e66f5->#1851c2, good #40a02b->#29661c, warn #df8e1d->#7b4e10, bad #d20f39->#b20d30,
    #   violet #8839ef->#702fc4, cyan #179299->#0f6267
    Theme(
        "catppuccin-latte",
        "Catppuccin Latte",
        {
            "bg": "#eff1f5",
            "surface": "#e6e9ef",
            "raised": "#ccd0da",
            "border": "#bcc0cc",
            "fg": "#3a3c50",
            "soft": "#383a49",
            "dim": "#555869",
            "accent": "#1851c2",
            "link": "#1851c2",
            "good": "#29661c",
            "warn": "#7b4e10",
            "bad": "#b20d30",
            "violet": "#702fc4",
            "cyan": "#0f6267",
        },
        light=True,
    ),
    # flexoki-light: Omarchy flexoki-light. Adjusted for contrast: dim #6F6E69->#656460, good
    #   #66800B->#576d09, warn #AD8301->#7e6001, cyan #24837B->#1f6f69
    Theme(
        "flexoki-light",
        "Flexoki Light",
        {
            "bg": "#FFFCF0",
            "surface": "#f2efe4",
            "raised": "#E6E4D9",
            "border": "#CECDC3",
            "fg": "#100F0F",
            "soft": "#403E3C",
            "dim": "#656460",
            "accent": "#205EA6",
            "link": "#205EA6",
            "good": "#576d09",
            "warn": "#7e6001",
            "bad": "#AF3029",
            "violet": "#5E409D",
            "cyan": "#1f6f69",
        },
        light=True,
    ),
    # solarized-light: Solarized (Schoonover). Adjusted for contrast: soft #586e75->#38464b,
    #   dim #657b83->#506167, accent #cb4b16->#a63e12, link #268bd2->#1c6599, good
    #   #859900->#596700, warn #b58900->#795c00, bad #dc322f->#b42927, violet
    #   #6c71c4->#55599b, cyan #2aa198->#1c6c66
    Theme(
        "solarized-light",
        "Solarized Light",
        {
            "bg": "#fdf6e3",
            "surface": "#eee8d5",
            "raised": "#e3dcc3",
            "border": "#d3cbb0",
            "fg": "#073642",
            "soft": "#38464b",
            "dim": "#506167",
            "accent": "#a63e12",
            "link": "#1c6599",
            "good": "#596700",
            "warn": "#795c00",
            "bad": "#b42927",
            "violet": "#55599b",
            "cyan": "#1c6c66",
        },
        light=True,
    ),
)

THEMES_CSS: Final = "".join(t.css() for t in THEMES)
"""Every theme's blocks; appended to the light block and to the main hub palette."""

IDS: Final = tuple(t.id for t in THEMES)
DARK_IDS: Final = tuple(t.id for t in THEMES if not t.light)
LIGHT_IDS: Final = tuple(t.id for t in THEMES if t.light)
