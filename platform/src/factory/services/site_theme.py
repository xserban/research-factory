"""The light theme and the theme toggle, shared by the hub, every product page, the dashboard and
the explorer.

Each page keeps its own dark palette in a `:root` block. `LIGHT_CSS` sits after it and overrides the
same variable names: `:root[data-theme="light"]` applies when the reader chose light, and
`prefers-color-scheme: light` applies when no choice is saved
(`:root:not([data-theme="dark"])`, so an explicit dark choice always wins). The dark-only
decoration (grid background, glows) is switched off in the light block.

`THEME_SCRIPT` goes in `<head>` before the stylesheet: it applies the saved choice before paint and
wires every `[data-theme-toggle]` button. The choice lives in localStorage under `SAVE_KEY`; the
storage is wrapped in try/catch, so a blocked store only means the choice is not remembered. Storage
events keep same-origin frames (the hub and its product iframes) in step.

This module imports nothing from the package, so every page module may import it.
"""

from __future__ import annotations

from typing import Final

SAVE_KEY: Final = "factory-theme"

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
_ROOT_AUTO: Final = ':root:not([data-theme="dark"])'

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
    _block(_ROOT_LIGHT) + "@media (prefers-color-scheme: light){" + _block(_ROOT_AUTO) + "}"
)
"""The light palette and the decoration switch-off. Append it after a page's own dark `:root`."""

THEME_SCRIPT: Final = (
    "<script>(function(){var K='" + SAVE_KEY + "',R=document.documentElement;"
    "function saved(){try{var v=localStorage.getItem(K);return v==='light'||v==='dark'?v:null}"
    "catch(e){return null}}"
    "function current(){var s=R.getAttribute('data-theme');if(s==='light'||s==='dark')return s;"
    "return window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'}"
    "function labels(){var t=current()==='light'?'☾ Dark':'☀ Light';"
    "document.querySelectorAll('[data-theme-toggle]').forEach(function(b){b.textContent=t})}"
    "var s=saved();if(s)R.setAttribute('data-theme',s);"
    "document.addEventListener('DOMContentLoaded',function(){labels();"
    "document.querySelectorAll('[data-theme-toggle]').forEach(function(b){"
    "b.addEventListener('click',function(){var n=current()==='light'?'dark':'light';"
    "R.setAttribute('data-theme',n);try{localStorage.setItem(K,n)}catch(e){}labels()})})});"
    "window.addEventListener('storage',function(ev){if(ev.key!==K)return;var v=saved();"
    "if(v)R.setAttribute('data-theme',v);else R.removeAttribute('data-theme');labels()});"
    "})();</script>"
)
"""Inline script for `<head>`: applies the saved theme before paint and wires the toggles."""

THEME_TOGGLE: Final = (
    "<button type=button class=theme-toggle data-theme-toggle aria-label='Switch theme' "
    "title='Switch theme'>☀ Light</button>"
)
"""The toggle button for a page header. Its label is set by `THEME_SCRIPT`."""
