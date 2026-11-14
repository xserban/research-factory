# ruff: noqa: E501
"""The main hub's shared chrome: one slim bar on every main-hub page (Projects, New papers, Backlog,
Capabilities) that holds the page's only theme toggle, and the palette that follows the toggle.

Invariants:
- Pure string functions: nothing is read or written here, no model is called.
- The bar's own styles are self-contained (`--hb-*` variables set per theme), so the same bar sits
  on a portal-style page and on a `site.page` product page without either palette's variables.
- The bar is a div (not a header) so a page's `header` rules never reach it.
- A page that already carries `THEME_SCRIPT` is not given a second script, and the toggle row of
  `site.page` is removed: the bar's toggle is the only one.
- Every label and link is a fixed constant of this module: nothing from outside is written into the
  bar, so nothing needs escaping.
"""

from __future__ import annotations

from typing import Final

from factory.services.site_theme import THEME_SCRIPT, THEME_TOGGLE
from factory.services.site_themes import THEMES_CSS

HUB_NAV: Final[tuple[tuple[str, str, str], ...]] = (
    ("projects", "Projects", "/"),
    ("feed", "New papers", "/feed/"),
    ("backlog", "Backlog", "/backlog/"),
    ("catalog", "Capabilities", "/catalog/"),
)
"""(id, label, path) of each main-hub page, in bar order."""

PALETTE_CSS: Final = (
    ':root[data-theme="light"]{color-scheme:light;--bg:#f6f8fa;--fg:#1f2933;--mut:#616e7c;'
    "--line:#d0d7de;--card:#fff;--acc:#0b63c5;--ok:#1a7f37;--warn:#9a6700}"
    ':root[data-theme="dark"]{color-scheme:dark;--bg:#0d1117;--fg:#d7dde5;--mut:#8b96a5;'
    "--line:#263040;--card:#141b25;--acc:#6cb6ff;--ok:#56d364;--warn:#e3b341}"
) + THEMES_CSS
"""The portal palette chosen by the toggle (its own `:root` and light media block cover "no choice")."""

BAR_CSS: Final = (
    ".hubbar{--hb-bg:#0b1118;--hb-fg:#d7dde5;--hb-mut:#8b96a5;--hb-line:#263040;--hb-acc:#6cb6ff;"
    "display:flex;align-items:center;gap:4px;padding:0 16px;height:42px;background:var(--hb-bg);"
    "border-bottom:1px solid var(--hb-line);font:14px/1 system-ui,sans-serif;position:sticky;top:0;z-index:20}"
    ':root[data-theme="light"] .hubbar{--hb-bg:#f6f8fa;--hb-fg:#1f2933;--hb-mut:#616e7c;--hb-line:#d0d7de;--hb-acc:#0b63c5}'
    "@media (prefers-color-scheme:light){:root:not([data-theme]) .hubbar{--hb-bg:#f6f8fa;--hb-fg:#1f2933;"
    "--hb-mut:#616e7c;--hb-line:#d0d7de;--hb-acc:#0b63c5}}"
    ".hubbar b{margin-right:14px;color:var(--hb-fg);letter-spacing:.04em}"
    ".hubbar a{color:var(--hb-mut);text-decoration:none;padding:6px 10px;border-radius:6px}"
    ".hubbar a:hover{color:var(--hb-fg)}.hubbar a[aria-current]{color:var(--hb-acc);background:rgba(127,127,127,.12)}"
    ".hubbar .crumb{color:var(--hb-mut);margin:0 10px}.hubbar .ro{color:var(--hb-mut);font-size:12px;letter-spacing:.06em;margin-left:8px}"
    ".hubbar .ro b{color:var(--hb-acc);margin:0}.hubbar{flex:none}"
    ".hubbar .sp{flex:1}.hubbar .theme-toggle{background:none;border:1px solid var(--hb-line);color:var(--hb-fg);"
    "border-radius:6px;padding:4px 10px;font:inherit;cursor:pointer}"
    ".hubbar~.theme-row{display:none}"
)


_HIDE_TABS: Final = (
    "<script>if(location.pathname.indexOf('/p/')!==0)"
    "document.querySelectorAll('.hubbar a').forEach(function(a){a.hidden=true})</script>"
)
"""For a bar inside a project hub: its tabs point at main-hub pages, so they are hidden when the
hub is served alone (the single-project server has no such pages)."""


def hub_bar(active: str | None, *, context: str = "", main_hub_only: bool = False) -> str:
    """The bar: the Factory name, a tab per main-hub page (`active` marks one), an optional
    `context` (trusted HTML from the caller: a project's name and status) and the picker. It is a
    div, so a page's own `header` rules never reach it."""
    tabs = "".join(
        f"<a href='{href}'{' aria-current=' + chr(39) + 'page' + chr(39) if ident == active else ''}>{label}</a>"
        for ident, label, href in HUB_NAV
    )
    return (
        f"<div class=hubbar role=banner><b>FACTORY</b>{tabs}"
        f"{context}<span class=sp></span>{THEME_TOGGLE}</div>"
        + (_HIDE_TABS if main_hub_only else "")
    )


def with_bar(doc: str, active: str | None) -> str:
    """`doc` (a full HTML page) with the theme script in its head, the bar styles, and the bar as
    the first thing in its body. A page without `</head>` or `<body>` gets them added around it."""
    doc = doc.replace(
        f"<div class=theme-row>{THEME_TOGGLE}</div>", ""
    )  # the bar's toggle is the one
    script = "" if THEME_SCRIPT in doc else THEME_SCRIPT
    style = f"<style>{BAR_CSS}</style>"
    if "</head>" in doc:
        opened = doc.lower().find("<head")
        start = doc.find(">", opened) + 1 if opened >= 0 else 0
        doc = doc[:start] + script + doc[start:]
        doc = doc.replace("</head>", style + "</head>", 1)
    else:
        doc = f"<!doctype html><html lang=en><head><meta charset=utf-8>{script}{style}</head><body>{doc}</body></html>"
    bar = hub_bar(active)
    lower = doc.lower()
    at = lower.find("<body")
    if at < 0:
        return doc.replace("</head>", "</head><body>" + bar + "</body>", 1)
    end = doc.find(">", at) + 1
    return doc[:end] + bar + doc[end:]
