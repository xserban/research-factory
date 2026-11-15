# ruff: noqa: E501
"""The project Updates page `/p/<slug>/updates/` (plan 2026-11-15-updates-page, T3).

Four blocks from `updates.updates_view`: the header (since v1), the additions with a route filter
and the add-link form, the growth (an inline SVG line and the update-flow table) and the weekly
watch with its two acts. The acts post to `/api/inbox/add`, `/api/watch/configure` and
`/api/living/snapshot` of the same project with that project's token; the server records each as the
local human and refuses any other actor.

Invariants:
- Read-only: building the page writes no event and changes no state.
- Every button starts `disabled` and is enabled by the script only when the server injected its
  token (`<meta name=factory-token>`); a page opened as a file cannot act.
- A full re-run of the search is never offered: the page states how to run one by hand.
- Everything written into the page is escaped; the page has no external resources (the growth
  line is inline SVG).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from html import escape as e
from pathlib import Path
from typing import Final

from factory.errors import FactoryError
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.site import page
from factory.services.site_chrome import with_bar
from factory.services.site_portal import _CSS as PORTAL_CSS
from factory.services.updates import (
    AdditionRow,
    GrowthPoint,
    UpdatesView,
    WatchView,
    updates_view,
)

_ROUTES: Final = ("all", "inbox", "feed", "watch", "chase", "search", "other")
_CSS: Final = (
    "table{border-collapse:collapse;margin:8px 0;max-width:100%}td,th{border:1px solid var(--mut);padding:4px 10px;"
    "text-align:left;vertical-align:top}th{color:var(--dim);font-weight:600}"
    ".box{background:var(--card);border:1px solid var(--mut);padding:10px 14px;margin:10px 0;overflow-x:auto}"
    "button{padding:4px 12px}button:disabled{opacity:.45;cursor:not-allowed}"
    "input[type=text],input[type=number],input[type=date]{padding:4px 6px;max-width:100%}"
    ".msg{color:var(--dim);font-size:13px}.err{color:var(--amber)}.filters button[aria-pressed=true]{font-weight:700}"
    ".row{margin:6px 0}.row label{margin-right:12px;white-space:nowrap}svg.growth{width:100%;max-width:640px;height:auto}"
    "svg.growth .ln{stroke:var(--ac);fill:none;stroke-width:2}svg.growth .pt{fill:var(--ac)}"
    "svg.growth text{fill:var(--dim);font-size:11px}svg.growth .ax{stroke:var(--mut);stroke-width:1}"
)

_SCRIPT: Final = """
(function(){
var m=document.querySelector('meta[name=factory-token]');
var API=(document.querySelector('meta[name=factory-api]')||{}).content||'';
var btns=document.querySelectorAll('button[data-act]');
var live=!!m&&location.protocol!=='file:';
if(live){for(var i=0;i<btns.length;i++)btns[i].disabled=false;}
function post(path,body,msg,ok){
  fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':m.content},body:JSON.stringify(body)})
  .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
  .then(function(r){
    if(r.ok){msg.textContent=ok(r);return;}
    msg.textContent=(r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';
  })
  .catch(function(x){msg.textContent='request failed: '+x;});
}
function act(name,fn){var b=document.querySelector('button[data-act='+name+']');if(b&&live)b.addEventListener('click',function(){fn(b);});}
var slug=document.body.dataset.slug||'';
act('addlink',function(){
  var v=document.getElementById('link-value').value;
  post('/api/inbox/add',{project:slug,value:v,note:document.getElementById('link-note').value||null},
    document.getElementById('link-msg'),function(r){return r.duplicate?'already in the inbox':'added to the inbox; reload later to see it';});
});
act('watch',function(){
  var s=[].slice.call(document.querySelectorAll('input[name=src]:checked')).map(function(x){return x.value;});
  var u=document.getElementById('w-until').value;
  post('/api/watch/configure',{sources:s,interval_days:parseInt(document.getElementById('w-int').value,10)||0,until:u||null},
    document.getElementById('w-msg'),function(r){return 'saved: protocol '+r.protocol_id+'; reload to see it';});
});
act('snapshot',function(){
  post('/api/living/snapshot',{},document.getElementById('s-msg'),function(r){return 'week closed; reload to see it';});
});
var fb=document.querySelectorAll('button[data-route]');
for(var j=0;j<fb.length;j++)fb[j].addEventListener('click',function(ev){
  var r=ev.currentTarget.dataset.route;
  for(var k=0;k<fb.length;k++)fb[k].setAttribute('aria-pressed',fb[k]===ev.currentTarget?'true':'false');
  var rows=document.querySelectorAll('tr[data-r]');
  for(var q=0;q<rows.length;q++)rows[q].style.display=(r==='all'||rows[q].dataset.r===r||(r==='other'&&['search','other'].indexOf(rows[q].dataset.r)>=0))?'':'none';
});
})();
"""


def _when(value: datetime | date | None) -> str:
    return "-" if value is None else value.strftime("%Y-%m-%d")


def _header(view: UpdatesView) -> str:
    base = view.baseline
    if base is None:
        return (
            "<div class=box><b>No snapshot yet.</b> The first snapshot (v1) freezes the reviewed "
            "corpus; additions are counted from it.</div>"
        )
    line = (
        f"Since v1 ({e(base.snapshot_id)}, {_when(base.recorded_at)}): "
        f"<b>{base.included_count}</b> included at v1, <b>{len(view.additions)}</b> works added since."
    )
    period = view.open_period
    if period is not None:
        line += (
            f"<br>Open period since {e(period.since_snapshot or 'v1')}: {period.new_works} new "
            f"works, {period.included_at_title_abstract} included at title/abstract."
        )
    return f"<div class=box>{line}</div>"


def _addition_row(a: AdditionRow) -> str:
    outcome = " / ".join(x for x in (a.ta_outcome, a.ft_state, a.ft_outcome) if x) or "-"
    return (
        f"<tr data-r='{e(a.route)}'><td>{_when(a.added_at)}</td><td>{e(a.title or a.work_id)}</td>"
        f"<td>{a.year if a.year is not None else '-'}</td><td>{e(a.route)}</td>"
        f"<td>{e(a.note or '')}</td><td>{e(outcome)}</td><td>{e(a.layer or '-')}</td>"
        f"<td>{e(', '.join(a.mined) or '-')}</td></tr>"
    )


def _additions(view: UpdatesView) -> str:
    filters = "".join(
        f"<button type=button data-route='{r}' aria-pressed={'true' if r == 'all' else 'false'}>{r}</button> "
        for r in _ROUTES
    )
    if view.additions:
        rows = "".join(_addition_row(a) for a in view.additions)
        table = (
            "<table><tr><th>added</th><th>title</th><th>year</th><th>route</th><th>note</th>"
            f"<th>title/abstract / full text</th><th>layer</th><th>mined</th></tr>{rows}</table>"
        )
    else:
        table = "<p class=msg>No work has entered the corpus since v1.</p>"
    form = (
        "<p class=row><label>Link or identifier <input type=text id=link-value size=40></label> "
        "<label>Note <input type=text id=link-note size=24></label> "
        "<button type=button data-act=addlink disabled>Add to the inbox (as you)</button> "
        "<span class=msg id=link-msg>Actions are off until the page is served by "
        "<code>factory site serve</code>.</span></p>"
    )
    return (
        "<div class=box><b>Additions since v1</b>"
        f"<p class='filters row'>route: {filters}</p>{table}{form}</div>"
    )


def _svg(points: Sequence[GrowthPoint]) -> str:
    if not points:
        return ""
    w, h, pad = 600, 180, 34
    top = max(p.included_count for p in points) or 1
    step = (w - 2 * pad) / max(len(points) - 1, 1)

    def xy(i: int, n: int) -> tuple[float, float]:
        return pad + i * step, h - pad - (h - 2 * pad) * n / top

    coords = [xy(i, p.included_count) for i, p in enumerate(points)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "".join(
        f"<circle class=pt cx='{x:.1f}' cy='{y:.1f}' r=3><title>{e(_label(i))}: {p.included_count}</title></circle>"
        f"<text x='{x:.1f}' y='{h - 12}' text-anchor=middle>{e(_label(i))}</text>"
        f"<text x='{x:.1f}' y='{y - 8:.1f}' text-anchor=middle>{p.included_count}</text>"
        for i, ((x, y), p) in enumerate(zip(coords, points, strict=True))
    )
    return (
        f"<svg class=growth viewBox='0 0 {w} {h}' role=img aria-label='Included works per snapshot'>"
        f"<line class=ax x1={pad} y1={h - pad} x2={w - pad} y2={h - pad}></line>"
        f"<polyline class=ln points='{path}'></polyline>{dots}</svg>"
    )


def _label(i: int) -> str:
    return "v1" if i == 0 else f"v{i + 1}"


def _counts(values: dict[str, int] | None) -> str:
    if not values:
        return "-"
    return ", ".join(f"{e(k)} {v}" for k, v in sorted(values.items()))


def _growth(view: UpdatesView) -> str:
    if not view.growth:
        return "<div class=box><b>Growth</b><p class=msg>No snapshot yet.</p></div>"
    rows = "".join(
        f"<tr><td>{_label(i)}</td><td>{e(p.snapshot_id)}</td><td>{_when(p.recorded_at)}</td>"
        f"<td>{p.included_count}</td><td>{'-' if p.identified is None else p.identified}</td>"
        f"<td>{'-' if p.screened is None else p.screened}</td><td>{'-' if p.included is None else p.included}</td>"
        f"<td>{_counts(p.identified_databases)}; {_counts(p.identified_other)}</td></tr>"
        for i, p in enumerate(view.growth)
    )
    table = (
        "<table><tr><th>version</th><th>snapshot</th><th>recorded</th><th>studies included</th>"
        f"<th>identified</th><th>screened</th><th>passed title/abstract</th><th>identified by route</th></tr>{rows}</table>"
    )
    return f"<div class=box><b>Growth</b>{_svg(view.growth)}<p class=msg>Update flow of each snapshot.</p>{table}</div>"


def _watch_block(watch: WatchView, slug: str, sources: Sequence[str]) -> str:
    if watch.has_plan:
        rows = "".join(
            f"<tr><td>{e(s.source)}</td><td>{e(s.mode)}</td><td>{s.interval_days} d</td>"
            f"<td>{_when(s.last_finished_at)}</td><td>{'due now' if s.due else _when(s.next_due)}</td>"
            f"<td>{_when(s.last_full_replay) if s.last_full_replay else 'none in the watch'}</td>"
            f"<td>{s.windows_since_full_replay}</td></tr>"
            for s in watch.sources
        )
        current = (
            f"<p>Weekly watch on. Ends: {_when(watch.until) if watch.until else 'no end date'}; "
            f"open cycle: {e(watch.open_cycle or 'none')}.</p>"
            "<table><tr><th>source</th><th>mode</th><th>every</th><th>last cycle</th><th>next</th>"
            f"<th>last full run</th><th>weekly windows since</th></tr>{rows}</table>"
        )
    else:
        current = "<p>Weekly watch: <b>not configured</b>.</p>"
    first = watch.sources[0] if watch.sources else None
    chosen = {s.source for s in watch.sources}
    interval = 7 if first is None else first.interval_days
    boxes = "".join(
        f"<label><input type=checkbox name=src value='{e(s, quote=True)}'{' checked' if (s in chosen or not chosen) else ''}> {e(s)}</label>"
        for s in sources
    )
    until = "" if watch.until is None else watch.until.isoformat()
    form = (
        "<p class=row>Sources: "
        + (boxes or "<span class=msg>no included source in the protocol</span>")
        + "</p>"
        f"<p class=row><label>Interval (days) <input type=number id=w-int min=1 value={interval}></label> "
        f"<label>End date (optional) <input type=date id=w-until value='{e(until, quote=True)}'></label> "
        "<button type=button data-act=watch disabled>Save watch settings (as you)</button> "
        "<span class=msg id=w-msg></span></p>"
        "<p class=row><button type=button data-act=snapshot disabled>Close week now (as you)</button> "
        "<span class=msg id=s-msg>Actions are off until the page is served by "
        "<code>factory site serve</code>.</span></p>"
    )
    note = (
        "<p class=msg>Sources run in window mode: each weekly window covers the days since the last. "
        "A full re-run never happens automatically. To run one: "
        f"<code>factory --project {e(slug)} watch run --full-replay</code>.</p>"
    )
    return f"<div class=box><b>Weekly watch</b>{current}{form}{note}</div>"


def render_updates(view: UpdatesView, slug: str, included_sources: Sequence[str] = ()) -> str:
    """The Updates page of one project from its view. Writes nothing."""
    body = (
        f"<h1>Updates <span class=s>{e(slug)}</span></h1>"
        "<p class=sub>What entered the corpus since the frozen review, how it grew, and the weekly "
        "watch. <a href='/'>All projects</a></p>"
        + _header(view)
        + _additions(view)
        + _growth(view)
        + _watch_block(view.watch, slug, included_sources)
    )
    doc = page(
        f"Updates: {e(slug)}",
        f"<main>{body}</main><script>{_SCRIPT}</script>",
        PORTAL_CSS + _CSS,
        body_class="portal",
    )
    return with_bar(
        doc.replace(
            "<body class=portal>", f"<body class=portal data-slug='{e(slug, quote=True)}'>", 1
        ),
        None,
    )


def _included_sources(project: Project) -> tuple[str, ...]:
    current = current_protocol(project)
    if current is None:
        return ()
    return tuple(s.name for s in current.spec.sources if s.included)


def build_updates(project: Project, out: Path) -> None:
    """Write `index.html` into `out`. Writes no event."""
    slug = project.paths.slug
    try:
        html = render_updates(updates_view(project), slug, _included_sources(project))
    except FactoryError as exc:
        html = with_bar(
            page(
                f"Updates: {e(slug)}",
                f"<main><div class='box err'>could not read the updates: {e(str(exc))}</div></main>",
                PORTAL_CSS + _CSS,
                body_class="portal",
            ),
            None,
        )
    (out / "index.html").write_text(html, encoding="utf-8")
