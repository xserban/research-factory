"""The frame of a main-hub page outside a project (the portal, Backlog, Capabilities) in the hub v2
design system: `kit.css`, its fonts and `main-hub.css`, served under the feed page's asset prefix,
and the shared bar of `site_chrome`.

Invariants:
- A pure string function: nothing is read or written, no model is called.
- `title` is escaped here; `body`, `css`, `head` and `script` are trusted HTML or CSS built by the
  caller, which escapes every value from outside.
- The page links only same-origin assets (`site_factory_feed.ASSET_PREFIX`); no external request.
- The theme is the bar's (`site_chrome.with_bar`): its ids are the ids `kit.css` styles.
"""

from __future__ import annotations

import html

from factory.services import hub_ui
from factory.services.site_chrome import with_bar
from factory.services.site_factory_feed import ASSET_PREFIX


def kit_page(
    title: str,
    body: str,
    active: str,
    *,
    css: str = "",
    head: str = "",
    script: str = "",
) -> str:
    """A full page: the kit stylesheets, page-local `css` (prefixed classes, kit tokens only),
    `body` inside `<main class=mh>`, then `script`; with the main-hub bar marking `active`."""
    v = html.escape(hub_ui.asset_version(), quote=True)
    doc = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"{head}<title>{html.escape(title)}</title>"
        f"<link rel=stylesheet href='{ASSET_PREFIX}kit.css?v={v}'>"
        f"<link rel=stylesheet href='{ASSET_PREFIX}main-hub.css?v={v}'>"
        + (f"<style>{css}</style>" if css else "")
        + f"</head><body><main class=mh>{body}</main>"
        + (f"<script>{script}</script>" if script else "")
        + "</body></html>"
    )
    return with_bar(doc, active)
