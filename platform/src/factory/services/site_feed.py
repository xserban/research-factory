# ruff: noqa: E501
"""The Daily updates product: the latest feed ranking as a scrollable page, one card per shown
item (plan 2026-11-11-feed-hub, step H1).

Invariants:
- Read-only projection of the events and blobs. Building writes no event and changes no state.
- The cards are the ranking's shown items in shown order (`feed_list`), so nothing is re-ranked
  here. Held entries are never shown: `feed_list` drops them, and this page does not read them back.
- The abstract and the authors come from the entries blob of the first fetch that saw the entry
  (the first fetch stands, as in the feed projection). An entry with no readable blob has neither,
  and its card omits them.
- Without a feed configuration the page says so and shows the command that configures one.
- The action buttons start `disabled`. A small inline script enables them only when the page was
  served by `factory site serve` (which injects `<meta name=factory-token>`); the built file holds no
  token. Opened as a file, the buttons stay disabled and a hint names the command.
- The page has no external resources; its styles are the site theme and this module's CSS.
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping
from datetime import timedelta
from html import escape
from pathlib import Path

from factory.errors import FactoryError
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.feed import FeedStatus, feed_status
from factory.services.feed_read import FeedListItem, feed_list

FEED_CSS = (
    ".card{background:var(--card);border:1px solid var(--mut);border-left:3px solid var(--ac);"
    "padding:12px 16px;margin:10px 0;line-height:1.5}"
    ".card h3{margin:2px 0 6px;font-size:14px;letter-spacing:.02em}"
    ".card h3 a{color:var(--blue)}"
    ".meta{color:var(--dim);font-size:12px;margin:2px 0}"
    ".rank{color:var(--ac);font-variant-numeric:tabular-nums;margin-right:10px}"
    ".score{color:var(--light);font-variant-numeric:tabular-nums;margin-right:10px}"
    ".badge{display:inline-block;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;"
    "padding:1px 7px;margin-right:6px;border:1px solid var(--mut);color:var(--light)}"
    ".badge.explore{color:var(--amber);border-color:var(--amber)}"
    ".badge.added{color:var(--ac);border-color:var(--ac)}"
    "details{margin:8px 0}summary{cursor:pointer;color:var(--dim)}"
    "details p{color:var(--light);font-size:13px}"
    ".acts{margin-top:8px}.acts button{margin-right:6px;padding:3px 9px}"
    ".acts button:disabled{opacity:.45;cursor:not-allowed}"
    ".hint{color:var(--amber);font-size:12px;margin:6px 0}.msg{color:var(--dim);font-size:12px}"
    ".status{background:var(--card);border:1px solid var(--mut);padding:10px 14px;margin:8px 0}"
    ".status span{display:inline-block;margin-right:18px;color:var(--light)}"
)

ACTIONS: tuple[tuple[str, str], ...] = (
    ("like", "Like"),
    ("dislike", "Dislike"),
    ("save", "Save"),
    ("dismiss", "Dismiss"),
    ("add", "Add to project"),
)

# Enables the buttons only when the server injected its token; sends one JSON POST per click and
# shows the answer on the card. Text goes in through textContent, never as markup.
FEED_SCRIPT = """
(function(){
var m=document.querySelector('meta[name=factory-token]');
var feed=document.getElementById('feed');
if(!m||!feed||location.protocol==='file:')return;
var token=m.content,ranking=feed.dataset.rankingId;
var hint=document.getElementById('feed-hint');if(hint)hint.remove();
function show(card,text){
  var el=card.querySelector('.msg');
  if(!el){el=document.createElement('p');el.className='msg';card.appendChild(el);}
  el.textContent=text;
}
function issues(r){return (r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';}
feed.querySelectorAll('button[data-act]').forEach(function(b){
  b.disabled=false;
  b.addEventListener('click',function(){
    var card=b.closest('.card'),act=b.dataset.act,add=act==='add';
    var body={entry_id:card.dataset.entryId,ranking_id:ranking};
    if(!add)body.reaction=act;
    var btns=card.querySelectorAll('button');
    btns.forEach(function(x){x.disabled=true;});
    fetch(add?'/api/feed/add':'/api/feed/react',{method:'POST',
      headers:{'Content-Type':'application/json','X-Factory-Token':token},body:JSON.stringify(body)})
    .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
    .then(function(r){
      if(!r.ok){show(card,issues(r));return;}
      if(add){
        var d=card.firstElementChild;
        if(!d.querySelector('.badge.added')){var s=document.createElement('span');s.className='badge added';s.textContent='added';d.appendChild(s);}
        show(card,'added: '+r.outcome+(r.reason?' ('+r.reason+')':''));
      }else{
        var meta=Array.prototype.find.call(card.querySelectorAll('.meta'),function(p){return p.textContent.indexOf('reaction:')===0;});
        if(meta)meta.textContent='reaction: '+r.reaction;
        show(card,'saved: '+r.reaction);
      }
    })
    .catch(function(e){show(card,'request failed: '+e);})
    .then(function(){btns.forEach(function(x){x.disabled=false;});});
  });
});
})();
"""


def build_feed(project: Project, out: Path) -> None:
    """Write `index.html` into `out` from the latest feed ranking. Writes no event."""
    from factory.services.site import page

    body = _body(project)
    (out / "index.html").write_text(page("Daily updates", body, FEED_CSS), encoding="utf-8")


def _body(project: Project) -> str:
    status = feed_status(project)
    head = "<h1>Daily updates</h1>" + _status_html(status)
    if not status.configured or status.config is None:
        return (
            head + "<div class=note>This project has no feed configuration, so there is no daily "
            "update yet. Configure the feed from the command line:</div>"
            "<p><code>factory feed configure</code></p>"
        )
    listing = feed_list(project)
    if listing.ranking_id is None:
        return head + f"<p class=dim>{escape(listing.reason or 'no ranking yet')}.</p>"
    blobs = _entry_records(project)
    cards = "".join(_card(item, blobs.get(item.entry_id)) for item in listing.items)
    if not cards:
        cards = "<p class=dim>The latest ranking shows no items.</p>"
    return (
        head
        + f"<p class=dim>Ranking <code>{escape(listing.ranking_id)}</code>, {len(listing.items)} items.</p>"
        + "<p class=hint id=feed-hint>Actions are off: open this page with <code>factory site serve</code>.</p>"
        + f"<div id=feed data-ranking-id='{escape(listing.ranking_id)}'>{cards}</div>"
        + f"<script>{FEED_SCRIPT}</script>"
    )


def _status_html(status: FeedStatus) -> str:
    config = status.config
    if config is None:
        return ""
    last_to = status.last_complete_window_to
    if last_to is None:
        next_due = "no complete fetch yet"
    else:
        next_due = (last_to + timedelta(days=config.interval_days)).isoformat()
        if status.due:
            next_due = f"due now (was {next_due})"
    cats = ", ".join(config.categories)
    return (
        "<div class=status>"
        f"<span>categories: {escape(cats)}</span>"
        f"<span>last fetch window: {escape(last_to.isoformat()) if last_to else 'none'}</span>"
        f"<span>next due: {escape(next_due)}</span>"
        f"<span>shown per cycle: {config.shown_per_cycle}</span>"
        "</div>"
    )


def _card(item: FeedListItem, record: Mapping[str, object] | None) -> str:
    entry = escape(item.entry_id)
    title = escape(item.title or item.entry_id)
    badges = ""
    if item.explore:
        badges += "<span class='badge explore'>explore</span>"
    if item.sent:
        badges += "<span class='badge added'>added</span>"
    reaction = escape(str(item.reaction)) if item.reaction is not None else "no reaction"
    authors = _authors(record)
    nearest = item.nearest_reference_title or item.nearest_reference
    nearest_html = escape(nearest) if nearest else "no core paper nearby"
    abstract = _text(record, "abstract")
    abstract_html = (
        f"<details><summary>abstract</summary><p>{escape(abstract)}</p></details>"
        if abstract
        else ""
    )
    buttons = "".join(
        f"<button type=button data-act='{act}' disabled>{escape(label)}</button>"
        for act, label in ACTIONS
    )
    return (
        f"<article class=card data-entry-id='{entry}'>"
        f"<div><span class=rank>#{item.rank}</span><span class=score>{item.score:.3f}</span>{badges}</div>"
        f"<h3><a href='https://arxiv.org/abs/{entry}'>{title}</a></h3>"
        + (f"<p class=meta>{escape(authors)}</p>" if authors else "")
        + f"<p class=meta>nearest core paper: {nearest_html}</p>"
        + f"<p class=meta>reaction: {reaction}</p>"
        + abstract_html
        + f"<div class=acts>{buttons}</div>"
        + "</article>"
    )


def _authors(record: Mapping[str, object] | None) -> str:
    if record is None:
        return ""
    value = record.get("authors")
    if not isinstance(value, list):
        return ""
    return ", ".join(str(a) for a in value if isinstance(a, str) and a.strip())


def _text(record: Mapping[str, object] | None, key: str) -> str:
    if record is None:
        return ""
    value = record.get(key)
    return value.strip() if isinstance(value, str) else ""


def _entry_records(project: Project) -> dict[str, Mapping[str, object]]:
    """The record of each entry from the first valid fetch that saw it (events in id order). An
    unreadable blob or a record that is not an object contributes nothing."""
    found: dict[str, Mapping[str, object]] = {}
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type != "feed.fetched" or event.actor.kind not in ("system", "agent"):
            continue
        ref = event.payload.get("entries_blob")
        if not isinstance(ref, str):
            continue
        try:
            entries = project.blobs.get_json(ref)
        except (FactoryError, OSError, EOFError, ValueError, zlib.error):
            # an unreadable blob contributes nothing; the page still renders
            continue
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id", item.get("entry_id"))
            if isinstance(entry_id, str):
                found.setdefault(entry_id, item)
    return found
