# ruff: noqa: E501
"""The hub feed page `/feed/` of the main hub (plan 2026-11-13-hub-feed, part 4).

One page for every project: a tab per project with the cards of that project's latest ranking
(`feed.fetched` and `feed.ranked` events), a status line, and the Fetch now and Refetch buttons of
the hub's feed runner.

Invariants:
- Read-only projection of the events: building the page writes nothing and never starts a run.
- The cards are the latest ranking's shown items in shown order, as `feed_list` gives them, so held
  entries (held-out seeds included) are never shown and nothing is re-ranked here.
- A project without a feed configuration is a tab that says "not configured" and links to its
  Settings page; a project with no ranking says so. Neither is an error: the page renders with no
  feed events at all and with no runner.
- Every project's tab carries that project's own write token (`data-token`), and a reaction or an
  add posts to that project's `/p/<slug>/api/feed/...`, so it is recorded in the project of the
  tab. The hub acts (`/api/feed/run`, `/api/feed/refetch`) use the hub token in `<meta>`.
- A failure reading one project's events turns that tab into an error note, not a failed page.
- Everything written into the page is escaped; the page has no external resources.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape as e
from typing import TYPE_CHECKING, Final

from factory.errors import FactoryError
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.feed import FeedStatus, feed_status
from factory.services.feed_read import FeedListing, FeedListItem, feed_list
from factory.services.site_chrome import with_bar
from factory.services.site_feed import FEED_CSS, _authors, _entry_records, _text
from factory.services.site_portal import _CSS as PORTAL_CSS

if TYPE_CHECKING:
    from factory.services.site_server import FeedRunner

ACTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("like", "Like"),
    ("dislike", "Dislike"),
    ("add", "Add to inbox"),
)


@dataclass(frozen=True)
class LastFetch:
    window_from: str
    window_to: str
    count: int
    held_count: int
    complete: bool


@dataclass(frozen=True)
class ProjectFeed:
    """What the page shows of one project: read from its events, nothing judged."""

    slug: str
    title: str
    token: str
    status: FeedStatus | None = None
    listing: FeedListing | None = None
    records: Mapping[str, Mapping[str, object]] | None = None
    last_fetch: LastFetch | None = None
    reference_count: int | None = None
    references: str | None = None
    error: str | None = None


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def collect(project: Project, slug: str, title: str, token: str) -> ProjectFeed:
    """Read one project's feed state; a failure becomes `error`, never an exception."""
    try:
        status = feed_status(project)
        if not status.configured:
            return ProjectFeed(slug, title, token, status=status)
        listing = feed_list(project)
        records = _entry_records(project)
        last_fetch: LastFetch | None = None
        count: int | None = None
        refs: str | None = None
        for event in read_all(project.paths.events_dir, project.catalog):
            if event.actor.kind not in ("system", "agent"):
                continue
            p = event.payload
            if event.type == "feed.fetched":
                last_fetch = LastFetch(
                    str(p.get("window_from")),
                    str(p.get("window_to")),
                    _int(p.get("count")),
                    _int(p.get("held_count")),
                    p.get("complete") is True,
                )
            elif event.type == "feed.ranked":
                raw = p.get("reference_count")
                count = raw if isinstance(raw, int) else None
                params = p.get("parameters")
                if isinstance(params, dict) and isinstance(params.get("references"), str):
                    refs = str(params["references"])
        return ProjectFeed(
            slug,
            title,
            token,
            status=status,
            listing=listing,
            records=records,
            last_fetch=last_fetch,
            reference_count=count,
            references=refs,
        )
    except (FactoryError, OSError, ValueError) as exc:
        return ProjectFeed(slug, title, token, error=f"{type(exc).__name__}: {exc}")


def runner_payload(runner: FeedRunner | None) -> dict[str, object]:
    """The runner's state for `GET /api/feed/runner` and the page."""
    if runner is None:
        return {"available": False, "running": False, "last": None}
    return {"available": True, "running": runner.running, "last": runner.last}


_CSS: Final = (
    FEED_CSS + ".tabs{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}"
    ".tab{background:var(--card);border:1px solid var(--line);color:var(--fg);padding:5px 12px;"
    "border-radius:6px;cursor:pointer;font:inherit}.tab.on{border-color:var(--acc);color:var(--acc)}"
    ".bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0}"
    ".bar button{padding:4px 12px}.run{color:var(--mut);font-size:13px}"
    ".err{color:var(--warn)}.pn[hidden]{display:none}"
    ".status{background:var(--card);border:1px solid var(--line);padding:10px 14px;margin:8px 0}"
    ".card{border-color:var(--line);border-left-color:var(--acc)}"
    ".meta{color:var(--mut)}.rank,.score{color:var(--acc)}"
)

_SCRIPT: Final = """
(function(){
var hub=(document.querySelector('meta[name=factory-token]')||{}).content||'';
var tabs=document.querySelectorAll('.tab'),panels=document.querySelectorAll('.pn');
function show(slug){
  tabs.forEach(function(t){t.classList.toggle('on',t.dataset.slug===slug);});
  panels.forEach(function(p){p.hidden=p.dataset.slug!==slug;});
  try{history.replaceState(null,'','#'+slug);}catch(_){}
}
if(tabs.length){
  tabs.forEach(function(t){t.addEventListener('click',function(){show(t.dataset.slug);});});
  var want=location.hash.slice(1);
  show(Array.prototype.some.call(tabs,function(t){return t.dataset.slug===want;})?want:tabs[0].dataset.slug);
}
function issues(r){return (r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';}
function note(card,text){var el=card.querySelector('.msg');if(!el){el=document.createElement('p');el.className='msg';card.appendChild(el);}el.textContent=text;}
panels.forEach(function(panel){
  var token=panel.dataset.token,slug=panel.dataset.slug,ranking=panel.dataset.rankingId;
  panel.querySelectorAll('button[data-act]').forEach(function(b){
    b.disabled=false;
    b.addEventListener('click',function(){
      var card=b.closest('.card'),act=b.dataset.act,add=act==='add';
      var body={entry_id:card.dataset.entryId,ranking_id:ranking};
      if(!add)body.reaction=act;
      var btns=card.querySelectorAll('button');btns.forEach(function(x){x.disabled=true;});
      fetch('/p/'+slug+(add?'/api/feed/add':'/api/feed/react'),{method:'POST',
        headers:{'Content-Type':'application/json','X-Factory-Token':token},body:JSON.stringify(body)})
      .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
      .then(function(r){
        if(!r.ok){note(card,issues(r));return;}
        note(card,add?('added: '+r.outcome+(r.reason?' ('+r.reason+')':'')):('saved: '+r.reaction));
      })
      .catch(function(e){note(card,'request failed: '+e);})
      .then(function(){btns.forEach(function(x){x.disabled=false;});});
    });
  });
});
var line=document.getElementById('run-line'),runBtns=document.querySelectorAll('button[data-run]');
function outcome(s){
  if(s.running)return 'a run is in progress';
  if(!s.last)return 'no run yet';
  if(s.last.error)return 'last run failed: '+s.last.error;
  var parts=(s.last.outcomes||[]).map(function(o){
    var r=o.result;return o.slug+': '+(o.error?o.error:(r?r.status+', '+r.fetched+' fetched, '+r.shown+' shown'+(r.cached?' (cache)':''):'skipped'));});
  return 'last run'+(s.last.refetch?' (refetch)':'')+': exit '+s.last.exit_code+(parts.length?' ('+parts.join('; ')+')':'');
}
function poll(){
  fetch('/api/feed/runner').then(function(r){return r.json();}).then(function(s){
    if(line)line.textContent=outcome(s);
    runBtns.forEach(function(b){b.disabled=!s.available||s.running;});
    if(s.running)setTimeout(poll,2000);
  }).catch(function(){});
}
runBtns.forEach(function(b){
  b.addEventListener('click',function(){
    runBtns.forEach(function(x){x.disabled=true;});
    fetch('/api/feed/'+b.dataset.run,{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':hub},body:'{}'})
    .then(function(r){return r.json().catch(function(){return {};});})
    .then(function(r){if(line&&r.ok===false)line.textContent=issues(r);setTimeout(poll,500);})
    .catch(function(){poll();});
  });
});
if(runBtns.length)poll();
})();
"""


def _status_line(view: ProjectFeed) -> str:
    status = view.status
    if view.error is not None:
        return f"<div class='status err'>could not read this project's feed: {e(view.error)}</div>"
    if status is None or not status.configured or status.config is None:
        return (
            "<div class=status><span>not configured</span>"
            f"<span><a href='/p/{e(view.slug, quote=True)}/settings/'>Settings</a> proposes the "
            "categories from the core layer</span></div>"
        )
    fetch = view.last_fetch
    last_to = status.last_complete_window_to
    parts = [
        f"<span>last fetch: {e(last_to.isoformat()) if last_to else 'none yet'}</span>",
        "<span>window: "
        + (f"{e(fetch.window_from)} to {e(fetch.window_to)}" if fetch else "none")
        + ("" if fetch is None or fetch.complete else " (incomplete)")
        + "</span>",
        "<span>references: "
        + (e(view.references) if view.references else "not yet used")
        + (
            f", {view.reference_count} reference{'' if view.reference_count == 1 else 's'}"
            if view.reference_count is not None
            else ""
        )
        + "</span>",
        f"<span>entries held: {status.held_entries} of {status.entries}</span>",
        f"<span>categories: {e(', '.join(status.config.categories))}</span>",
        f"<span>{'due now' if status.due else 'not due'}</span>",
    ]
    return "<div class=status>" + "".join(parts) + "</div>"


def _card(item: object, record: Mapping[str, object] | None) -> str:
    assert isinstance(item, FeedListItem)
    entry = e(item.entry_id, quote=True)
    title = e(item.title or item.entry_id)
    badges = ""
    if item.explore:
        badges += "<span class='badge explore'>explore</span>"
    if item.sent:
        badges += "<span class='badge added'>added</span>"
    authors = _authors(record)
    nearest = item.nearest_reference_title or item.nearest_reference
    abstract = _text(record, "abstract")
    buttons = "".join(
        f"<button type=button data-act='{act}' disabled>{e(label)}</button>"
        for act, label in ACTIONS
    )
    reaction = e(str(item.reaction)) if item.reaction is not None else "no reaction"
    return (
        f"<article class=card data-entry-id='{entry}'>"
        f"<div><span class=rank>#{item.rank}</span><span class=score>{item.score:.3f}</span>{badges}</div>"
        f"<h3><a href='https://arxiv.org/abs/{entry}'>{title}</a></h3>"
        + (f"<p class=meta>{e(authors)}</p>" if authors else "")
        + f"<p class=meta>nearest core work: {e(nearest) if nearest else 'none nearby'}</p>"
        + f"<p class=meta>reaction: {reaction}</p>"
        + (
            f"<details><summary>abstract</summary><p>{e(abstract)}</p></details>"
            if abstract
            else ""
        )
        + f"<p class=meta><a href='https://arxiv.org/abs/{entry}'>abstract page</a> "
        f"<a href='https://arxiv.org/pdf/{entry}'>pdf</a></p>"
        + f"<div class=acts>{buttons}</div></article>"
    )


def _panel(view: ProjectFeed) -> str:
    slug = e(view.slug, quote=True)
    ranking = view.listing.ranking_id if view.listing else None
    head = (
        f"<section class=pn data-slug='{slug}' data-token='{e(view.token, quote=True)}'"
        + (f" data-ranking-id='{e(ranking, quote=True)}'" if ranking else "")
        + f"><h2>{e(view.title)} <span class=s>{e(view.slug)}</span></h2>"
        + _status_line(view)
    )
    if view.error is not None or view.status is None or not view.status.configured:
        return head + "</section>"
    listing = view.listing
    if listing is None or listing.ranking_id is None:
        return (
            head
            + "<p class=sub>No ranking yet: nothing has been fetched for this project.</p></section>"
        )
    records = view.records or {}
    cards = "".join(_card(i, records.get(i.entry_id)) for i in listing.items)
    return (
        head
        + f"<p class=sub>Ranking <code>{e(listing.ranking_id)}</code>, {len(listing.items)} items.</p>"
        + (cards or "<p class=sub>The latest ranking shows no items.</p>")
        + "</section>"
    )


def render_feed_page(
    views: Sequence[ProjectFeed], runner: Mapping[str, object], hub_token: str
) -> str:
    """The page: the run bar, one tab per project, one panel per project."""
    tabs = "".join(
        f"<button type=button class=tab data-slug='{e(v.slug, quote=True)}'>{e(v.title)}</button>"
        for v in views
    )
    if runner.get("available") is True:
        state = (
            "a run is in progress" if runner.get("running") else _last_outcome(runner.get("last"))
        )
        disabled = " disabled" if runner.get("running") else ""
        bar = (
            f"<div class=bar><button type=button data-run=run{disabled}>Fetch now</button>"
            f"<button type=button data-run=refetch{disabled}>Refetch (no cache)</button>"
            f"<span class=run id=run-line>{e(state)}</span></div>"
        )
    else:
        bar = "<div class=bar><span class=run id=run-line>the feed runner is off (start the hub with feed on)</span></div>"
    body = (
        "<h1>New papers</h1><p class=sub>One arXiv pull, compared with each project's core works. "
        "A ranking orders; it judges nothing. <a href='/'>All projects</a></p>"
        + bar
        + (f"<div class=tabs>{tabs}</div>" if views else "")
        + (
            "".join(_panel(v) for v in views)
            or "<p class=sub>No project found under the factory root.</p>"
        )
    )
    return with_bar(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<meta name='factory-token' content='{e(hub_token, quote=True)}'>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>New papers</title><style>{PORTAL_CSS}{_CSS}</style></head><body><main>{body}</main>"
        f"<script>{_SCRIPT}</script></body></html>",
        "feed",
    )


def _last_outcome(last: object) -> str:
    if not isinstance(last, dict):
        return "no run yet"
    if "error" in last:
        return f"last run failed: {last['error']}"
    return f"last run{' (refetch)' if last.get('refetch') else ''}: exit {last.get('exit_code')}"


@dataclass(frozen=True)
class TopEntry:
    """One entry of the portal's short list: the shown item, and whose ranking it came from."""

    slug: str
    title: str
    token: str
    ranking_id: str
    item: FeedListItem


def top_entries(views: Sequence[ProjectFeed], limit: int) -> list[TopEntry]:
    """The `limit` best-scored shown items over every project's latest ranking. A project with no
    ranking, no configuration or a read error adds none; equal scores keep project order, then
    shown order. Scores are the ranker's own: nothing is re-ranked here."""
    found: list[TopEntry] = []
    for view in views:
        listing = view.listing
        if view.error is not None or listing is None or listing.ranking_id is None:
            continue
        found.extend(
            TopEntry(view.slug, view.title, view.token, listing.ranking_id, i)
            for i in listing.items
        )
    return sorted(found, key=lambda t: -t.item.score)[: max(limit, 0)]


_PANEL_SCRIPT: Final = """
(function(){
document.querySelectorAll('.fp .pe').forEach(function(card){
  var slug=card.dataset.slug,token=card.dataset.token,ranking=card.dataset.rankingId;
  var msg=card.querySelector('.msg');
  card.querySelectorAll('button[data-act]').forEach(function(b){
    b.disabled=false;
    b.addEventListener('click',function(){
      var btns=card.querySelectorAll('button');btns.forEach(function(x){x.disabled=true;});
      fetch('/p/'+slug+'/api/feed/react',{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':token},
        body:JSON.stringify({entry_id:card.dataset.entryId,ranking_id:ranking,reaction:b.dataset.act})})
      .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
      .then(function(r){msg.textContent=r.ok?('saved: '+r.reaction):((r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused');})
      .catch(function(x){msg.textContent='request failed: '+x;})
      .then(function(){btns.forEach(function(x){x.disabled=false;});});
    });
  });
});
})();
"""


def render_feed_panel(entries: Sequence[TopEntry], *, shown_total: int) -> str:
    """The short New papers list for the portal: each entry with its score, project, nearest core
    work and the like and dislike buttons; the full page has the abstract and Add to inbox."""
    if not entries:
        return (
            "<section class=fp><h2>New papers <a href='/feed/'>Open the feed</a></h2>"
            "<p class=sub>No new papers yet: nothing has been fetched for any project.</p></section>"
        )
    rows = []
    for t in entries:
        item = t.item
        entry = e(item.entry_id, quote=True)
        nearest = item.nearest_reference_title or item.nearest_reference
        reaction = (
            f" &middot; reaction: {e(str(item.reaction))}" if item.reaction is not None else ""
        )
        rows.append(
            f"<div class=pe data-slug='{e(t.slug, quote=True)}' data-token='{e(t.token, quote=True)}' "
            f"data-ranking-id='{e(t.ranking_id, quote=True)}' data-entry-id='{entry}'>"
            f"<div><span class=sc>{item.score:.3f}</span>"
            f"<a class=tt href='https://arxiv.org/abs/{entry}'>{e(item.title or item.entry_id)}</a></div>"
            f"<div class=mm>{e(t.title)} &middot; nearest core work: {e(nearest) if nearest else 'none nearby'}{reaction}</div>"
            "<div class=ac><button type=button data-act='like' disabled>Like</button>"
            "<button type=button data-act='dislike' disabled>Dislike</button><span class=msg></span></div></div>"
        )
    return (
        f"<section class=fp><h2>New papers <a href='/feed/'>See all {shown_total} &rarr;</a></h2>"
        + "".join(rows)
        + f"</section><script>{_PANEL_SCRIPT}</script>"
    )
