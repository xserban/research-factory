"""The light theme and the theme toggle, shared by the hub, every product page, the dashboard and
the explorer.

Each page keeps its own dark palette in a `:root` block. `LIGHT_CSS` sits after it and overrides the
same variable names: `:root[data-theme="light"]` applies when the reader chose light, and
`prefers-color-scheme: light` applies only to a page without scripts (with scripts, no saved
choice means LCARS)
(`:root:not([data-theme])`, so any explicit choice, dark or a named theme, always wins). The
dark-only decoration (grid background, glows) is switched off in the light block.

`THEME_SCRIPT` goes in `<head>` before the stylesheet: it applies the saved choice before paint and
wires every `[data-theme-toggle]` button. The choice lives in localStorage under `SAVE_KEY`; the
storage is wrapped in try/catch, so a blocked store only means the choice is not remembered. Storage
events keep same-origin frames (the hub and its product iframes) in step.

This module imports only `site_themes` (which imports nothing), so every page module may import it.
"""

from __future__ import annotations

from typing import Final

from factory.services.site_themes import IDS, THEMES, THEMES_CSS

SAVE_KEY: Final = "factory-theme"
DEFAULT_THEME: Final = "lcars"
"""Applied when no choice is saved (the picker's first entry). Without scripts the page keeps its
own dark palette, or the light one when the system asks for it."""

# The light palette, by variable name. Every name a page uses has a value here, so the light
# block is the same for every page; a name a page does not use is simply unused.
LIGHT: Final[dict[str, str]] = {
    "bg": "#FFFFFF",  # background
    "dk": "#F5F7FB",  # header and input surfaces
    "lt": "#F5F7FB",  # panel
    "panel": "#F5F7FB",  # panel (explorer name)
    "card": "#F5F7FB",  # raised surface behind prose and cards
    "navbg": "#F5F7FB",  # navigation column
    "sel": "#E8EEF8",  # raised / selected
    "hi": "#E8EEF8",  # highlight (explorer name)
    "hov": "#E8EEF8",  # row hover
    "chart": "#FFFFFF",  # chart plot area
    "mut": "#D9E1EC",  # borders
    "line": "#D9E1EC",  # borders (explorer name)
    "fg": "#1B2333",  # text
    "ink": "#1B2333",  # text (explorer name)
    "light": "#2E3850",  # secondary prose
    "dim": "#5B6478",  # muted text
    "ac": "#1D4ED8",  # accent blue
    "acc": "#1D4ED8",  # accent (explorer name)
    "bright": "#1E40AF",  # accent hover; headings in the dashboard
    "blue": "#1E40AF",  # links
    "soft": "#DBEAFE",  # soft accent fill
    "heat": "#93C5FD",  # tint of counts in heat grids
    "mag": "#6D28D9",
    "cyan": "#0E7490",
    "green": "#166534",  # success
    "brown": "#166534",
    "amber": "#92400E",  # warning
    "red": "#B91C1C",  # error
}

_ROOT_LIGHT: Final = ':root[data-theme="light"]'
_ROOT_AUTO: Final = ":root:not([data-theme])"

# Dark-only decoration, switched off under each light root.
_DECOR: Final[tuple[tuple[str, str], ...]] = (
    ("body", "background-image:none"),
    (".led,.led.stale,.led.bad,header .logo", "box-shadow:none"),
)


def _block(root: str) -> str:
    decls = "color-scheme:light;" + "".join(f"--{k}:{v};" for k, v in LIGHT.items())
    rules = "".join(f"{root} {sel}{{{decl}}}" for sel, decl in _DECOR)
    return f"{root}{{{decls}}}{rules}"


LIGHT_CSS: Final = (
    _block(_ROOT_LIGHT)
    + "@media (prefers-color-scheme: light){"
    + _block(_ROOT_AUTO)
    + "}"
    + THEMES_CSS
)
"""The light palette and the decoration switch-off. Append it after a page's own dark `:root`."""

_CHOICES: Final = ("dark", "light", *IDS)

THEME_SCRIPT: Final = (
    "<script>(function(){var K='" + SAVE_KEY + "',R=document.documentElement,"
    "OK=" + repr(list(_CHOICES)) + ",D='" + DEFAULT_THEME + "';"
    "function saved(){try{var v=localStorage.getItem(K);return OK.indexOf(v)>=0?v:null}"
    "catch(e){return null}}"
    "function labels(){var v=saved()||'';"
    "document.querySelectorAll('[data-theme-toggle]').forEach(function(b){b.value=v})}"
    "R.setAttribute('data-theme',saved()||D);"
    "if(window.top!==window.self){var st=document.createElement('style');"
    "st.textContent='[data-theme-toggle],.theme-row{display:none!important}';"
    "document.head.appendChild(st)}"
    "document.addEventListener('DOMContentLoaded',function(){labels();"
    "document.querySelectorAll('[data-theme-toggle]').forEach(function(b){"
    "b.addEventListener('change',function(){var n=b.value;"
    "if(OK.indexOf(n)>=0){R.setAttribute('data-theme',n);try{localStorage.setItem(K,n)}catch(e){}}"
    "else{R.setAttribute('data-theme',D);try{localStorage.removeItem(K)}catch(e){}}"
    "labels()})})});"
    "window.addEventListener('storage',function(ev){if(ev.key!==K)return;var v=saved();"
    "R.setAttribute('data-theme',v||D);labels()});"
    "})();</script>"
)
"""Inline script for `<head>`: applies the saved theme before paint and wires the pickers. Only the
known choices are accepted, so a tampered stored value is ignored. A page shown inside a frame (a
product in the project hub) hides its pickers: the bar of the page that frames it holds the one
picker, and the choice reaches the frame through the `storage` event."""

_OPTIONS: Final = (
    "<option value=''>Default (LCARS)</option>"
    "<optgroup label='Dark'><option value='dark'>Dark</option>"
    + "".join(f"<option value='{t.id}'>{t.label}</option>" for t in THEMES if not t.light)
    + "</optgroup><optgroup label='Light'><option value='light'>Light</option>"
    + "".join(f"<option value='{t.id}'>{t.label}</option>" for t in THEMES if t.light)
    + "</optgroup>"
)

THEME_TOGGLE: Final = (
    "<select class=theme-toggle data-theme-toggle aria-label='Switch theme' title='Switch theme'>"
    + _OPTIONS
    + "</select>"
)
"""The theme picker for a page header: system, dark, light and the named themes. Its value is set
by `THEME_SCRIPT`."""
