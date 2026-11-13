"""The portal: the root page of the main hub server (plan 2026-11-13-main-hub, part 1).

One server shows every project under the factory root. Projects are found by scanning
`<root>/projects/` (`context.list_projects`); an optional `<root>/registry.json` adds what a folder
cannot say. The files stay the source of truth: the registry holds no research data.

Registry format (all keys optional)::

    {"projects": {"<slug>": {"title": "A short name", "hidden": true}}}

Invariants:
- `load_registry` never raises: a missing, unreadable or malformed file is an empty registry, and
  a malformed entry is ignored, so a bad registry cannot take the portal down.
- A hidden project is left out of the list, not out of the server: its URL still works.
- Everything written into the page is escaped; slugs come from folder names and titles from the
  registry.
"""

from __future__ import annotations

import json
from html import escape as e
from pathlib import Path
from typing import Final, NamedTuple

REGISTRY: Final = "registry.json"


class Entry(NamedTuple):
    """One project's registry entry."""

    title: str
    hidden: bool


class PortalRow(NamedTuple):
    """One line of the portal: what the server read from the project, no judgement."""

    slug: str
    title: str
    events: int
    stale: int
    built: int
    hub_ready: bool
    building: bool = False


def load_registry(root: Path) -> dict[str, Entry]:
    """The registry's entries by slug; empty when the file is missing or malformed."""
    try:
        data = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        return {}
    out: dict[str, Entry] = {}
    for slug, raw in projects.items():
        if not isinstance(slug, str) or not isinstance(raw, dict):
            continue
        title = raw.get("title")
        out[slug] = Entry(
            title=title if isinstance(title, str) and title.strip() else slug,
            hidden=raw.get("hidden") is True,
        )
    return out


def listed(slugs: list[str], registry: dict[str, Entry]) -> list[tuple[str, str]]:
    """The (slug, title) pairs the portal lists: every scanned project that is not hidden."""
    return [
        (s, registry[s].title if s in registry else s)
        for s in slugs
        if not (s in registry and registry[s].hidden)
    ]


_CSS: Final = (
    ":root{color-scheme:dark light;--bg:#0d1117;--fg:#d7dde5;--mut:#8b96a5;--line:#263040;"
    "--card:#141b25;--acc:#6cb6ff;--ok:#56d364;--warn:#e3b341}"
    "@media (prefers-color-scheme:light){:root{--bg:#f6f8fa;--fg:#1f2933;--mut:#616e7c;"
    "--line:#d0d7de;--card:#fff;--acc:#0b63c5;--ok:#1a7f37;--warn:#9a6700}}"
    "body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}"
    "main{max-width:960px;margin:0 auto;padding:24px 16px}h1{font-size:24px;margin:0 0 4px}"
    ".sub{color:var(--mut);margin:0 0 20px}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}"
    "a.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:8px;"
    "padding:14px 16px;color:inherit;text-decoration:none}"
    "a.card:hover{border-color:var(--acc)}.t{font-weight:600;font-size:17px}"
    ".s{color:var(--mut);font-size:13px;font-family:ui-monospace,monospace}"
    ".m{display:flex;gap:14px;margin-top:10px;font-size:13px}.m b{font-size:16px}"
    ".ok{color:var(--ok)}.warn{color:var(--warn)}.note{color:var(--mut);margin-top:24px;"
    "font-size:13px}"
)


def render_portal(rows: list[PortalRow]) -> str:
    """The portal page: one card per project linking to its hub under `/p/<slug>/`."""
    cards = []
    for r in rows:
        state = (
            "<span class=warn>rebuilding</span>"
            if r.building
            else "<span class=warn>hub not built</span>"
            if not r.hub_ready
            else (
                f"<span class=warn>{r.stale} to rebuild</span>"
                if r.stale
                else "<span class=ok>up to date</span>"
            )
        )
        cards.append(
            f"<a class=card href='/p/{e(r.slug, quote=True)}/'>"
            f"<div class=t>{e(r.title)}</div><div class=s>{e(r.slug)}</div>"
            f"<div class=m><span><b>{r.events:,}</b> events</span>"
            f"<span><b>{r.built}</b> pages</span>{state}</div></a>"
        )
    body = "".join(cards) or "<p class=note>No project found under the factory root.</p>"
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Factory projects</title><style>{_CSS}</style></head><body><main>"
        "<h1>Factory</h1><p class=sub>All projects on this machine. Open one for its hub.</p>"
        f"<div class=grid>{body}</div>"
        "<p class=note>Projects are found by scanning the factory root; "
        "<code>registry.json</code> can give a title or hide one.</p></main></body></html>"
    )
