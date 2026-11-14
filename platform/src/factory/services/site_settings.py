# ruff: noqa: E501
"""The project Settings page `/p/<slug>/settings/` (plan 2026-11-13-hub-feed, part 5).

It shows the project's feed configuration and the category proposal (`propose_categories`: the
shares, the proposed set, the coverage) and offers one act, Accept, which posts the proposed
categories to `/api/feed/configure` of the same project with that project's token. The act is
`site_server.feed_configure`, which records `feed.configured` as the local human (the service
refuses any other actor); the page never writes anything itself.

Invariants:
- Read-only: building the page writes no event and changes no state.
- The proposal is computed from the events at request time and changes nothing; with no proposal
  (no core-layer work has an arXiv category) the page says so and offers no Accept.
- The buttons start `disabled` and are enabled by the script only when the server injected its
  token (`<meta name=factory-token>`); a page opened as a file cannot act.
- Everything written into the page is escaped; the page has no external resources.
"""

from __future__ import annotations

from html import escape as e
from typing import Final

from factory.errors import FactoryError
from factory.services.context import Project
from factory.services.feed import current_config
from factory.services.feed_categories import CategoryProposal, propose_categories
from factory.services.site_portal import _CSS as PORTAL_CSS

_CSS: Final = (
    "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid var(--line);padding:4px 10px;"
    "text-align:left}th{color:var(--mut);font-weight:600}.pick{color:var(--acc);font-weight:600}"
    ".box{background:var(--card);border:1px solid var(--line);padding:10px 14px;margin:10px 0}"
    "button{padding:4px 12px}button:disabled{opacity:.45;cursor:not-allowed}"
    ".msg{color:var(--mut);font-size:13px}.err{color:var(--warn)}"
)

_SCRIPT: Final = """
(function(){
var m=document.querySelector('meta[name=factory-token]');
var API=(document.querySelector('meta[name=factory-api]')||{}).content||'';
var b=document.querySelector('button[data-act=accept]');
if(!m||!b||location.protocol==='file:')return;
b.disabled=false;
var msg=document.getElementById('accept-msg');
b.addEventListener('click',function(){
  b.disabled=true;
  fetch(API+'/api/feed/configure',{method:'POST',
    headers:{'Content-Type':'application/json','X-Factory-Token':m.content},
    body:JSON.stringify({categories:b.dataset.categories.split(',')})})
  .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
  .then(function(r){
    if(r.ok){msg.textContent='accepted: feed configured ('+r.event_id+'); reload to see it';return;}
    msg.textContent=(r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';
    b.disabled=false;
  })
  .catch(function(x){msg.textContent='request failed: '+x;b.disabled=false;});
});
})();
"""


def _configuration(project: Project) -> str:
    config = current_config(project)
    if config is None:
        return (
            "<div class=box><b>Feed configuration</b>: not configured. The feed skips this "
            "project until a human accepts categories below.</div>"
        )
    rows = [
        ("categories", ", ".join(config.categories)),
        ("references", config.references.value),
        ("shown per cycle", str(config.shown_per_cycle)),
        ("exploration share", f"{config.exploration_share:g}"),
        ("interval (days)", str(config.interval_days)),
        ("overlap (days)", str(config.overlap_days)),
        ("drift threshold", f"{config.drift_threshold:g}"),
        ("drift minimum count", str(config.drift_min_count)),
    ]
    body = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows)
    return f"<div class=box><b>Feed configuration</b><table>{body}</table></div>"


def _proposal(proposal: CategoryProposal) -> str:
    head = "<div class=box><b>Proposed categories</b>"
    basis = (
        f"<p class=msg>From the core layer: {proposal.core_works} core works, "
        f"{proposal.with_category} with an arXiv category. Rule: cover {proposal.coverage:.0%}, "
        f"{proposal.minimum} to {proposal.maximum} categories.</p>"
    )
    if not proposal.categories:
        return head + basis + "<p>no proposal: no core-layer work has an arXiv category.</p></div>"
    rows = "".join(
        f"<tr><td class='{'pick' if s.category in proposal.categories else ''}'>{e(s.category)}</td>"
        f"<td>{s.works}</td><td>{s.share:.0%}</td>"
        f"<td>{'proposed' if s.category in proposal.categories else ''}</td></tr>"
        for s in proposal.shares[:12]
    )
    chosen = ",".join(proposal.categories)
    return (
        head
        + basis
        + f"<table><tr><th>category</th><th>works</th><th>share</th><th></th></tr>{rows}</table>"
        + f"<p>Proposed set: <b>{e(', '.join(proposal.categories))}</b>, covering "
        f"{proposal.covered:.0%} of the {proposal.with_category} works that have an arXiv "
        f"category (of {proposal.core_works} core works).</p>"
        + f"<p><button type=button data-act=accept data-categories='{e(chosen, quote=True)}' disabled>"
        "Accept (writes the feed configuration as you)</button> "
        "<span class=msg id=accept-msg>Actions are off until the page is served by "
        "<code>factory site serve</code>.</span></p></div>"
    )


def render_settings(project: Project, slug: str) -> str:
    """The Settings page of one project. Writes nothing."""
    try:
        config_html = _configuration(project)
        try:
            proposal_html = _proposal(propose_categories(project))
        except FactoryError as exc:
            proposal_html = f"<div class='box err'>no proposal: {e(str(exc))}</div>"
    except FactoryError as exc:
        config_html = f"<div class='box err'>could not read the settings: {e(str(exc))}</div>"
        proposal_html = ""
    body = (
        f"<h1>Settings <span class=s>{e(slug)}</span></h1>"
        "<p class=sub>Settings are recorded acts, made as the human; this page has no other store. "
        "<a href='/'>All projects</a></p>" + config_html + proposal_html
    )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Settings: {e(slug)}</title><style>{PORTAL_CSS}{_CSS}</style></head>"
        f"<body><main>{body}</main><script>{_SCRIPT}</script></body></html>"
    )
