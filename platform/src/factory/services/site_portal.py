# ruff: noqa: E501
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

from factory.services.site_chrome import PALETTE_CSS, with_bar

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
    "form.card input,form.card select{background:var(--bg);color:var(--fg);border:1px solid var(--line);"
    "border-radius:4px;padding:4px 8px;font:inherit}"
    "a.card:hover{border-color:var(--acc)}.t{font-weight:600;font-size:17px}"
    ".s{color:var(--mut);font-size:13px;font-family:ui-monospace,monospace}"
    ".m{display:flex;gap:14px;margin-top:10px;font-size:13px}.m b{font-size:16px}"
    ".ok{color:var(--ok)}.warn{color:var(--warn)}.note{color:var(--mut);margin-top:24px;"
    "font-size:13px}"
    ".fp{margin:0 0 22px}.fp h2{font-size:17px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:baseline}"
    ".fp h2 a{font-size:13px;font-weight:400;color:var(--acc);text-decoration:none}"
    ".fp .pe{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:9px 12px;margin:0 0 6px}"
    ".fp .pe .tt{font-weight:600;color:inherit;text-decoration:none}.fp .pe .tt:hover{color:var(--acc)}"
    ".fp .pe .mm{color:var(--mut);font-size:13px;margin-top:2px}.fp .pe .sc{color:var(--acc);font-family:ui-monospace,monospace;margin-right:8px}"
    ".fp .pe .ac{margin-top:6px;display:flex;gap:6px;align-items:center}.fp .pe .ac button{padding:2px 10px}.fp .pe .ac .msg{color:var(--mut);font-size:12px}"
) + PALETTE_CSS


_FORM: Final = (
    "<form id=create-form class=card style='margin-top:20px'><div class=t>New project</div>"
    "<p class=s>Created as you, like <code>factory init</code>. The slug is the folder name.</p>"
    "<p><input name=slug placeholder='slug-like-this' required pattern='[a-z0-9]+(-[a-z0-9]+)*' "
    "maxlength=64> <input name=title placeholder='title (optional)' maxlength=120> "
    "<select name=profile><option value='exploratory'>exploratory</option>"
    "<option value='pilot'>pilot</option><option value='systematic'>systematic</option></select> "
    "<button type=submit disabled>Create</button></p><p class=s id=create-msg></p></form>"
)

_FORM_SCRIPT: Final = """
(function(){
var m=document.querySelector('meta[name=factory-token]'),f=document.getElementById('create-form');
if(!m||!f||location.protocol==='file:')return;
var btn=f.querySelector('button'),msg=document.getElementById('create-msg');btn.disabled=false;
f.addEventListener('submit',function(ev){
  ev.preventDefault();btn.disabled=true;
  var body={slug:f.slug.value,title:f.title.value,profile:f.profile.value};
  fetch('/api/projects/create',{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':m.content},body:JSON.stringify(body)})
  .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
  .then(function(r){
    if(r.ok){location.href=r.url;return;}
    msg.textContent=(r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';btn.disabled=false;
  }).catch(function(x){msg.textContent='request failed: '+x;btn.disabled=false;});
});
})();
"""


_INBOX_SCRIPT: Final = """
(function(){
var m=document.querySelector('meta[name=factory-token]'),f=document.getElementById('inbox-form');
if(!m||!f||location.protocol==='file:')return;
var btn=f.querySelector('button'),msg=document.getElementById('inbox-msg');btn.disabled=false;
f.addEventListener('submit',function(ev){
  ev.preventDefault();btn.disabled=true;msg.textContent='adding...';
  var body={project:f.project.value,value:f.value.value};
  if(f.note.value.trim())body.note=f.note.value;
  fetch('/api/inbox/add',{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':m.content},body:JSON.stringify(body)})
  .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
  .then(function(r){
    btn.disabled=false;
    if(r.ok){msg.textContent=(r.duplicate?'duplicate: already in the inbox as ':'added as ')+r.item_id;if(!r.duplicate)f.value.value='';return;}
    msg.textContent='error: '+((r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused');
  }).catch(function(x){msg.textContent='request failed: '+x;btn.disabled=false;});
});
})();
"""


def _inbox_form(rows: list[PortalRow]) -> str:
    """The add-to-inbox form: a project select, one link or identifier, an optional note."""
    options = "".join(
        f"<option value='{e(r.slug, quote=True)}'>{e(r.title)}</option>" for r in rows
    )
    return (
        "<form id=inbox-form class=card style='margin-top:20px'><div class=t>Add to inbox</div>"
        "<p class=s>A DOI, arXiv id or link; kept as an inbox item, like "
        "<code>factory inbox add</code>.</p>"
        f"<p><select name=project>{options}</select> "
        "<input name=value placeholder='doi, arXiv id or link' required maxlength=500> "
        "<input name=note placeholder='note (optional)' maxlength=300> "
        "<button type=submit disabled>Add</button></p>"
        "<p class=s id=inbox-msg role=status></p></form>"
    )


def render_portal(
    rows: list[PortalRow], *, create_token: str | None = None, feed_panel: str = ""
) -> str:
    """The portal page: one card per project linking to its hub under `/p/<slug>/`. With
    `create_token` (the hub's write token) it also has the create-project form; `feed_panel` is the
    short New papers list (`site_hub_feed.render_feed_panel`), shown above the cards."""
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
    token_meta = (
        f"<meta name='factory-token' content='{e(create_token, quote=True)}'>"
        if create_token
        else ""
    )
    form = (_FORM + (_inbox_form(rows) if rows else "")) if create_token else ""
    script = f"<script>{_FORM_SCRIPT}{_INBOX_SCRIPT}</script>" if create_token else ""
    return with_bar(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        + token_meta
        + "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Factory projects</title><style>{_CSS}</style></head><body class=portal><main>"
        "<h1>Factory</h1><p class=sub>All projects on this machine. Open one for its hub.</p>"
        f"{feed_panel}<div class=grid>{body}</div>{form}"
        "<p class=note>Projects are found by scanning the factory root; "
        f"<code>registry.json</code> can give a title or hide one.</p></main>{script}</body></html>",
        "projects",
    )
