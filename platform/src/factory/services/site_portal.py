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
from datetime import date, timedelta
from html import escape as e
from pathlib import Path
from typing import Final, NamedTuple

from factory.services import hub_ui
from factory.services.site_chrome import UI_NAME
from factory.services.site_factory_feed import ASSET_PREFIX
from factory.services.site_kit_page import kit_page

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
    activity: tuple[int, ...] = ()
    """Events per day, oldest first, ending on `activity_end`; empty when not read."""
    activity_end: str | None = None
    """The ISO date of the last day of `activity` (the project clock's today)."""
    funnel: tuple[int, int, int] | None = None
    """(found, screened, included) from the last built overview payload; None when there is none."""


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


_CSS: Final = (  # the classic look, still used by the classic feed, settings and updates pages
    "main{padding:24px 0}h1{font-size:24px;margin:0 0 4px}"
    ".sub{color:var(--dim);margin:0 0 20px}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}"
    "a.card{display:block;background:var(--card);border:1px solid var(--mut);border-radius:8px;"
    "padding:14px 16px;color:inherit;text-decoration:none}"
    "form.card input,form.card select{background:var(--bg);color:var(--fg);border:1px solid var(--mut);"
    "border-radius:4px;padding:4px 8px;font:inherit}"
    "a.card:hover{border-color:var(--ac)}.t{font-weight:600;font-size:17px}"
    ".s{color:var(--dim);font-size:13px;font-family:ui-monospace,monospace}"
    ".m{display:flex;gap:14px;margin-top:10px;font-size:13px}.m b{font-size:16px}"
    ".ok{color:var(--green)}.warn{color:var(--amber)}.note{color:var(--dim);margin-top:24px;"
    "font-size:13px}"
    ".fp{margin:0 0 22px}.fp h2{font-size:17px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:baseline}"
    ".fp h2 a{font-size:13px;font-weight:400;color:var(--ac);text-decoration:none}"
    ".fp .pe{background:var(--card);border:1px solid var(--mut);border-radius:8px;padding:9px 12px;margin:0 0 6px}"
    ".fp .pe .tt{font-weight:600;color:inherit;text-decoration:none}.fp .pe .tt:hover{color:var(--ac)}"
    ".fp .pe .mm{color:var(--dim);font-size:13px;margin-top:2px}.fp .pe .sc{color:var(--ac);font-family:ui-monospace,monospace;margin-right:8px}"
    ".fp .pe .ac{margin-top:6px;display:flex;gap:6px;align-items:center}.fp .pe .ac button{padding:2px 10px}.fp .pe .ac .msg{color:var(--dim);font-size:12px}"
)


_FORM: Final = (
    "<form id=create-form class='card pt-form'><h2>New project</h2>"
    "<p>Created as you, like <code>factory init</code>. The slug is the folder name.</p>"
    "<div class=row><input name=slug aria-label='Slug' placeholder='slug-like-this' required "
    "pattern='[a-z0-9]+(-[a-z0-9]+)*' maxlength=64> "
    "<input name=title aria-label='Title' placeholder='Title (optional)' maxlength=120> "
    "<select name=profile aria-label='Profile'><option value='exploratory'>Exploratory</option>"
    "<option value='pilot'>Pilot</option><option value='systematic'>Systematic</option></select> "
    "<button type=submit class='btn primary' disabled>Create</button></div>"
    "<p class=out id=create-msg role=status></p></form>"
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
    msg.className='out err';msg.textContent=(r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';btn.disabled=false;
  }).catch(function(x){msg.className='out err';msg.textContent='Request failed: '+x;btn.disabled=false;});
});
})();
"""


_INBOX_SCRIPT: Final = """
(function(){
var m=document.querySelector('meta[name=factory-token]'),f=document.getElementById('inbox-form');
if(!m||!f||location.protocol==='file:')return;
var btn=f.querySelector('button'),msg=document.getElementById('inbox-msg');btn.disabled=false;
f.addEventListener('submit',function(ev){
  ev.preventDefault();btn.disabled=true;msg.className='out';msg.textContent='Adding…';
  var body={project:f.project.value,value:f.value.value};
  if(f.note.value.trim())body.note=f.note.value;
  fetch('/api/inbox/add',{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':m.content},body:JSON.stringify(body)})
  .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
  .then(function(r){
    btn.disabled=false;
    if(r.ok){msg.textContent=(r.duplicate?'Already in the inbox as ':'Added as ')+r.item_id;if(!r.duplicate)f.value.value='';return;}
    msg.className='out err';msg.textContent=((r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused');
  }).catch(function(x){msg.className='out err';msg.textContent='Request failed: '+x;btn.disabled=false;});
});
})();
"""


def _inbox_form(rows: list[PortalRow]) -> str:
    """The add-to-inbox form: a project select, one link or identifier, an optional note."""
    options = "".join(
        f"<option value='{e(r.slug, quote=True)}'>{e(r.title)}</option>" for r in rows
    )
    return (
        "<form id=inbox-form class='card pt-form'><h2>Add to inbox</h2>"
        "<p>A DOI, arXiv id or link, kept as an inbox item, like "
        "<code>factory inbox add</code>.</p>"
        f"<div class=row><select name=project aria-label='Project'>{options}</select> "
        "<input name=value aria-label='DOI, arXiv id or link' placeholder='DOI, arXiv id or link' "
        "required maxlength=500> "
        "<input name=note aria-label='Note' placeholder='Note (optional)' maxlength=300> "
        "<button type=submit class='btn primary' disabled>Add</button></div>"
        "<p class=out id=inbox-msg role=status></p></form>"
    )


def _state(r: PortalRow) -> str:
    """The hub's state in words, with a glyph so colour is never the only signal."""
    if r.building:
        return "<span class=pt-warn>&#8635; Rebuilding</span>"
    if not r.hub_ready:
        return "<span class=pt-warn>&minus; Hub not built</span>"
    if r.stale:
        return f"<span class=pt-warn>&minus; {r.stale} to rebuild</span>"
    return "<span class=pt-ok>+ Up to date</span>"


def _day(end: str, back: int) -> str:
    d = date.fromisoformat(end) - timedelta(days=back)
    return f"{d.day} {d:%b}"


def _activity(r: PortalRow) -> str:
    """Events per day as a bar sparkline (one bar per day, zero days as a hairline) with a
    sentence that states the total and the busiest day; nothing when no activity was read."""
    if not r.activity or r.activity_end is None:
        return ""
    total, peak = sum(r.activity), max(r.activity)
    days = len(r.activity)
    if total == 0:
        return f"<p class=pt-act>No events in the last {days} days.</p>"
    at = max(range(days), key=lambda k: (r.activity[k], k))
    busiest = _day(r.activity_end, days - 1 - at)
    sentence = f"{total:,} events in the last {days} days, busiest {busiest} ({peak:,})"
    bars = []
    for k, n in enumerate(r.activity):
        h = 1.0 if n == 0 else max(2.0, 30.0 * n / peak)
        label = f"{_day(r.activity_end, days - 1 - k)}: {n:,} event{'' if n == 1 else 's'}"
        bars.append(
            f"<rect class='{'pt-zero' if n == 0 else 'pt-grow'}' style='--i:{k}' x='{k * 10}' "
            f"y='{32 - h:.1f}' width='8' height='{h:.1f}'><title>{label}</title></rect>"
        )
    return (
        f"<svg class=pt-spark role=img aria-label='{e(sentence, quote=True)}' "
        f"viewBox='0 0 {days * 10 - 2} 32' preserveAspectRatio='none'>{''.join(bars)}</svg>"
        f"<p class=pt-act>{e(sentence)}.</p>"
    )


def _funnel(r: PortalRow) -> str:
    """Found, screened and included as nested bars, widths relative to found, with the numbers
    written out; nothing when there is no overview or nothing was found."""
    if r.funnel is None or r.funnel[0] <= 0:
        return ""
    found, screened, included = r.funnel

    def width(n: int) -> str:
        return f"{100 * min(n, found) / found:.1f}%"

    words = f"{found:,} found, {screened:,} screened, {included:,} included"
    return (
        f"<div class=pt-funnel role=img aria-label='{e(words, quote=True)}'>"
        "<span class=pt-f1 style='width:100%'></span>"
        f"<span class=pt-f2 style='width:{width(screened)}'></span>"
        f"<span class=pt-f3 style='width:{width(included)}'></span></div>"
        f"<p class=pt-act>{found:,} found &rarr; {screened:,} screened &rarr; "
        f"<b>{included:,} included</b></p>"
    )


def _card(r: PortalRow) -> str:
    slug = e(r.slug, quote=True)
    return (
        "<article class='card pt-card'>"
        f"<h3><a href='/p/{slug}/ui/'>{e(r.title)}</a></h3>"
        + (f"<span class=pt-slug>{e(r.slug)}</span>" if r.title != r.slug else "")
        + _activity(r)
        + _funnel(r)
        + "<div class=pt-figs>"
        f"<div><b>{r.events:,}</b><span>events</span></div>"
        f"<div><b>{r.built:,}</b><span>pages built</span></div></div>"
        f"<div class=pt-foot>{_state(r)}<span class=grow></span>"
        f"<a href='/p/{slug}/' title='The classic hub of this project'>Classic hub</a></div>"
        "</article>"
    )


def portal_payload(rows: list[PortalRow]) -> dict[str, object]:
    """Pure serializer turning `PortalRow` objects into the JSON payload for the estate view."""
    projects: list[dict[str, object]] = []
    for r in rows:
        funnel: dict[str, int] | None = (
            {"found": r.funnel[0], "screened": r.funnel[1], "included": r.funnel[2]}
            if r.funnel is not None
            else None
        )
        projects.append(
            {
                "slug": r.slug,
                "title": r.title,
                "events": r.events,
                "stale": r.stale,
                "built": r.built,
                "hub_ready": r.hub_ready,
                "building": r.building,
                "activity": list(r.activity),
                "activity_end": r.activity_end,
                "funnel": funnel,
                "hub_url": f"/p/{r.slug}/ui/",
                "classic_url": f"/p/{r.slug}/",
            }
        )
    return {"projects": projects}


def _json_for_script(data: object) -> str:
    """JSON safe to embed inside a `<script>` tag (`</` and line separators escaped)."""
    return (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _estate_stage(rows: list[PortalRow], *, has_forms: bool) -> str:
    """The aerial isometric estate viewport, gatehouse HUD, and 30-day chimney replay deck."""
    if not rows:
        return ""
    actions = (
        "<div class=pt-estate-actions role=toolbar aria-label='Estate quick actions'>"
        "<button type=button class='btn pt-btn' id=pt-btn-break>+ Break ground</button>"
        "<button type=button class='btn pt-btn' id=pt-btn-dock>&darr; Loading dock</button>"
        "<button type=button class='btn pt-btn' id=pt-btn-still aria-pressed=false "
        "title='Toggle still architectural plan (no motion)'>&#9707; Still plan</button>"
        "</div>"
        if has_forms
        else "<div class=pt-estate-actions role=toolbar aria-label='Estate quick actions'>"
        "<button type=button class='btn pt-btn' id=pt-btn-still aria-pressed=false "
        "title='Toggle still architectural plan (no motion)'>&#9707; Still plan</button>"
        "</div>"
    )
    return (
        "<section class=pt-estate id=pt-estate-stage aria-label='The research factory estate'>"
        "<div class=pt-estate-bar>"
        "<div class=pt-legend aria-label='Architectural scale key'>"
        "<span class=pt-leg-item><span class='pt-leg-mark pt-leg-area' aria-hidden=true></span>"
        "Footprint area &prop; included</span>"
        "<span class=pt-leg-item><span class='pt-leg-mark pt-leg-rail' aria-hidden=true></span>"
        "Rail width &prop; found &rarr; screened &rarr; included</span>"
        "<span class=pt-leg-item><span class='pt-leg-mark pt-leg-smoke' aria-hidden=true></span>"
        "Chimney puffs = daily events (30d)</span>"
        "</div>"
        f"{actions}"
        "</div>"
        "<div class=pt-viewport id=pt-viewport>"
        "<div class=pt-hud-top>"
        "<div class='pt-hud-coords mono'>"
        "<span class=pt-coord-dot aria-hidden=true></span>"
        "<span id=pt-hud-mode>AXONOMETRIC 30&deg; &middot; LIVE REPLAY</span>"
        "<span class=pt-hud-sep aria-hidden=true>|</span>"
        "<span>SCALE HONEST</span>"
        "</div>"
        "<div class=pt-hud-cam role=group aria-label='Camera controls'>"
        "<button type=button class='pt-hud-btn mono' id=pt-cam-out aria-label='Zoom out' title='Zoom out'>&minus;</button>"
        "<button type=button class='pt-hud-btn mono' id=pt-cam-fit aria-label='Fit entire estate' title='Fit estate'>Fit</button>"
        "<button type=button class='pt-hud-btn mono' id=pt-cam-in aria-label='Zoom in' title='Zoom in'>+</button>"
        "</div>"
        "</div>"
        "<div class=pt-stage id=pt-stage>"
        "<canvas id=pt-canvas aria-hidden=true></canvas>"
        "<div class=pt-hotspots id=pt-hotspots role=region aria-label='Interactive estate structures'></div>"
        "<div class=pt-tip id=pt-tip role=tooltip hidden></div>"
        "<div class=pt-drop-scrim id=pt-drop-scrim hidden aria-hidden=true>"
        "<div class=pt-drop-box><span class='mono pt-drop-kicker'>RECEIVING BAY &middot; LOADING DOCK</span>"
        "<strong>Drop a DOI, arXiv id, or paper link</strong>"
        "<span class=meta>Fills the Add to inbox form below</span></div></div>"
        "<div class=pt-gatehouse id=pt-gatehouse role=dialog aria-modal=false aria-labelledby=pt-gh-title hidden>"
        "<div class=pt-gh-top><div><div class='pt-gh-kicker mono' id=pt-gh-slug></div>"
        "<h3 class=pt-gh-title id=pt-gh-title></h3></div>"
        "<button type=button class='btn pt-gh-close' id=pt-gh-close aria-label='Return to aerial estate view'>&larr; Aerial view</button></div>"
        "<div class=pt-gh-metrics id=pt-gh-metrics></div>"
        "<div class=pt-gh-actions>"
        "<a class='btn primary' id=pt-gh-enter href='#'>Enter hub &rarr;</a>"
        "<a class=btn id=pt-gh-classic href='#'>Classic hub</a>"
        + (
            "<button type=button class=btn id=pt-gh-inbox>&darr; Add paper to inbox</button>"
            if has_forms
            else ""
        )
        + "</div></div>"
        "<div class=pt-fly-veil id=pt-fly-veil hidden aria-live=polite>"
        "<div class=pt-fly-card><span class='mono pt-fly-kicker'>ENTERING HUB</span>"
        "<strong id=pt-fly-title></strong><span class='mono meta' id=pt-fly-url></span></div></div>"
        "</div>"
        "<div class=pt-replay id=pt-replay aria-label='30-day activity replay'>"
        "<button type=button class=pt-replay-play id=pt-replay-play aria-pressed=true aria-label='Pause 30-day smoke replay'>"
        "<svg class=pt-ic-pause viewBox='0 0 16 16' aria-hidden=true><rect x='3.5' y='3' width='3' height='10' rx='0.5'/><rect x='9.5' y='3' width='3' height='10' rx='0.5'/></svg>"
        "<svg class=pt-ic-play viewBox='0 0 16 16' aria-hidden=true><path d='M4.5 2.5L13 8l-8.5 5.5z'/></svg>"
        "</button>"
        "<div class=pt-replay-tl><div class=pt-replay-spark-wrap>"
        "<svg class=pt-replay-spark id=pt-replay-spark preserveAspectRatio='none' aria-hidden=true></svg>"
        "<input type=range id=pt-replay-range class=pt-replay-range min=0 max=29 value=29 step=1 aria-label='Scrub day in the 30-day window'>"
        "</div><div class='pt-replay-axis mono' id=pt-replay-axis aria-hidden=true></div></div>"
        "<div class=pt-replay-readout aria-live=polite>"
        "<div class='pt-replay-day mono' id=pt-replay-day>&mdash;</div>"
        "<div class='pt-replay-events meta' id=pt-replay-events>&mdash;</div></div>"
        "<div class=pt-replay-peaks id=pt-replay-peaks aria-label='Jump to busiest day'></div>"
        "</div></div></section>"
    )


def render_portal(rows: list[PortalRow], *, create_token: str | None = None) -> str:
    """The portal page: the aerial isometric estate plus the parcel ledger (one card per project
    opening its hub under `/p/<slug>/ui/`, with the classic hub under `/p/<slug>/` as a second
    link). With `create_token` (the hub's write token) it also has the create-project and
    add-to-inbox forms. New papers is a tab of the bar, not a list here."""
    v = e(hub_ui.asset_version(), quote=True)
    cards = "".join(_card(r) for r in rows) or (
        "<p class='card pt-empty'>No project yet under the factory root. Create one below, or with "
        "<code>factory init</code>.</p>"
    )
    token_meta = (
        f"<meta name='factory-token' content='{e(create_token, quote=True)}'>"
        if create_token
        else ""
    )
    head = f"{token_meta}<link rel=stylesheet href='{ASSET_PREFIX}estate.css?v={v}'>"
    forms = (
        "<section class=mh-sec id=pt-ops aria-label='Add'><div class=pt-forms>"
        + _FORM
        + (_inbox_form(rows) if rows else "")
        + "</div></section>"
        if create_token
        else ""
    )
    count = f"{len(rows)} project{'' if len(rows) == 1 else 's'}" if rows else "No project yet"
    data_blob = (
        "<script type='application/json' id='pt-data'>"
        f"{_json_for_script(portal_payload(rows))}"
        "</script>"
        f"<script src='{ASSET_PREFIX}estate.js?v={v}' defer></script>"
    )
    body = (
        "<h1 class=pt-sr>Projects</h1>"
        f"{_estate_stage(rows, has_forms=bool(create_token))}"
        f"<section class=mh-sec id=pt-ledger><header><h2>Projects</h2><span class=meta>{count}</span></header>"
        f"<div class=pt-grid>{cards}</div></section>"
        f"{forms}"
        "<p class=note>Projects are found by scanning the factory root; "
        "<code>registry.json</code> can give a title or hide one.</p>"
        f"{data_blob}"
    )
    return kit_page(
        f"Projects · {UI_NAME}",
        body,
        "projects",
        head=head,
        script=f"{_FORM_SCRIPT}{_INBOX_SCRIPT}" if create_token else "",
    )
