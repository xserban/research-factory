"""The Work queue product: the papers added from the feed, each with the stage it stands at, and
the open units of work per kind (plan 2026-11-11-feed-hub, step H4).

Invariants:
- Read-only. Every count and stage comes from `work_queue.queue`; nothing is re-derived here.
- The "Process now" buttons start disabled. A small inline script enables them only when the page
  was served by `factory site serve` (token meta injected) and no run is open; one click is one
  `POST /api/queue/process`. Opened as a file the buttons stay disabled.
- Text from the entries and the inbox is escaped; the page has no external resources.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from factory.services.context import Project
from factory.services.work_queue import STAGES, QueueItem, WorkQueue, queue

QUEUE_CSS = (
    ".stage{display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;"
    "padding:1px 7px;border:1px solid var(--mut);color:var(--light);white-space:nowrap}"
    ".stage.stopped{color:var(--amber);border-color:var(--amber)}"
    ".stage.extracted{color:var(--ac);border-color:var(--ac)}"
    ".qtable td,.qtable th{vertical-align:top}"
    ".proc{margin:6px 0 14px}.proc button{padding:4px 12px;margin-right:8px}"
    ".proc button:disabled{opacity:.45;cursor:not-allowed}"
    ".dim{color:var(--dim)}"
)

# Stages the runner (H5) processes, with the pending kinds each one serves.
PROCESS_STAGES: tuple[tuple[str, str, str], ...] = (
    ("screen", "Screening", "Screen the open units of title/abstract and full-text screening."),
    ("extract", "Extraction", "Extract the open units of extraction and mining."),
)


QUEUE_SCRIPT = """
(function(){
var m=document.querySelector('meta[name=factory-token]');
if(!m||location.protocol==='file:')return;
var token=m.content,btns=document.querySelectorAll('button[data-stage]');
var box=document.getElementById('runstatus'),busy=false;
function say(t){if(box)box.textContent=t;}
function issues(r){
  return (r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';
}
function poll(){
  fetch('/api/queue/runs').then(function(r){return r.json();}).then(function(r){
    var runs=r.runs||[],open=runs.filter(function(x){return x.status==='running';})[0];
    busy=!!open;
    btns.forEach(function(b){b.disabled=busy;});
    var last=open||runs[0];
    if(last)say('run '+last.run_id+' ('+last.stage+'): '+last.status);
    if(busy)setTimeout(poll,5000);
  }).catch(function(e){say('status unavailable: '+e);});
}
btns.forEach(function(b){
  b.addEventListener('click',function(){
    btns.forEach(function(x){x.disabled=true;});
    fetch('/api/queue/process',{method:'POST',
      headers:{'Content-Type':'application/json','X-Factory-Token':token},
      body:JSON.stringify({stage:b.dataset.stage})})
    .then(function(r){
      return r.json().catch(function(){
        return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};
      });
    })
    .then(function(r){
      if(!r.ok){say(issues(r));btns.forEach(function(x){x.disabled=false;});return;}
      say('run '+r.run_id+' ('+r.stage+'): running');setTimeout(poll,3000);
    })
    .catch(function(e){say('request failed: '+e);btns.forEach(function(x){x.disabled=false;});});
  });
});
poll();
})();
"""


def build_queue(project: Project, out: Path) -> None:
    """Write `index.html` into `out` from the work queue. Writes no event."""
    from factory.services.site import page

    (out / "index.html").write_text(
        page("Work queue", _body(queue(project)) + f"<script>{QUEUE_SCRIPT}</script>", QUEUE_CSS),
        encoding="utf-8",
    )


def _body(work: WorkQueue) -> str:
    return (
        "<h1>Work queue</h1>"
        + _added_html(work.items)
        + "<h2>Pending work</h2>"
        + _pending_html(work.pending)
    )


def _added_html(items: list[QueueItem]) -> str:
    if not items:
        return "<p class=dim>No paper has been added from the feed yet.</p>"
    rows = "".join(
        "<tr>"
        f"<td>{escape(item.entry_id)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{_stage_badge(item)}</td>"
        f"<td class=dim>{escape(item.detail)}</td>"
        f"<td class=dim>{escape(item.sent_at)}</td>"
        "</tr>"
        for item in items
    )
    return (
        "<table class=qtable><tr><th>Entry</th><th>Title</th><th>Stage</th><th>Detail</th>"
        f"<th>Added</th></tr>{rows}</table>"
    )


def _stage_badge(item: QueueItem) -> str:
    css = (
        "stage"
        + (" stopped" if item.stopped else "")
        + (" extracted" if item.stage == "extracted" else "")
    )
    return f"<span class='{css}'>{escape(item.stage)}</span>"


def _pending_html(pending: dict[str, int]) -> str:
    rows = "".join(
        f"<tr><td>{escape(kind)}</td><td>{count}</td></tr>"
        for kind, count in sorted(pending.items())
    )
    table = (
        f"<table class=qtable><tr><th>Task kind</th><th>Open units</th></tr>{rows}</table>"
        if rows
        else "<p class=dim>No unit of work is defined yet.</p>"
    )
    buttons = "".join(
        f"<div class=proc><strong>{escape(title)}</strong> <span class=dim>{escape(text)}</span>"
        f"<br><button type=button disabled data-stage='{stage}'>Process now</button></div>"
        for stage, title, text in PROCESS_STAGES
    )
    hint = (
        "<p class=dim id=runstatus>Process now works when this page is opened with "
        "<code>factory site serve</code>.</p>"
    )
    return table + buttons + hint + _legend()


def _legend() -> str:
    names = ", ".join(STAGES)
    return f"<p class=dim>Stages, in path order: {escape(names)}.</p>"
