"""The Work queue product: the papers added from the feed, each with the stage it stands at, and
the open units of work per kind (plan 2026-11-11-feed-hub, step H4).

Invariants:
- Read-only. Every count and stage comes from `work_queue.queue`; nothing is re-derived here.
- The "Process now" buttons start disabled. A small inline script enables them only when the page
  was served by `factory site serve` (token meta injected) and no run is open; one click is one
  `POST /api/queue/process`. Opened as a file the buttons stay disabled.
- `Process all` (stage `all`) starts the whole pipeline (`services.pipeline`), the per-stage buttons
  one stage each; the stages shown are those that apply to the project, one per registered miner.
  The per-paper progress table has one column per applicable stage with a per-paper reading; each
  cell is `done`, `pending`, `n/a` or `stopped`, read by `pipeline.paper_progress`.
- The "Interrupted" panel (plan restart-and-costs, R3) is rendered from `resume.interrupted` at
  build time and refreshed by the script from `GET /api/queue/interrupted`. `Preview` posts a dry
  run; `Resume` posts a real one (`POST /api/queue/resume`, a 202 when started) and stays disabled
  when nothing is interrupted, when a run is open, or when the page is not served by the hub.
- Text from the entries and the inbox is escaped; the page has no external resources.
"""
# ruff: noqa: E501 (the page script is one JS string; its lines are long by nature)

from __future__ import annotations

from html import escape
from pathlib import Path

from factory.services.context import Project
from factory.services.pipeline import CellState, PipelineStage, paper_progress, stages
from factory.services.resume import Interrupted, InterruptedRun, interrupted
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
    ".intr{margin:6px 0}.intr li{margin:2px 0}"
    "#resume-out{white-space:pre-wrap;margin:8px 0 0;font-size:12px;color:var(--light)}"
)

QUEUE_CSS += (
    ".cell{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim)}"
    ".cell.done{color:var(--ac)}.cell.pending{color:var(--light)}"
    ".cell.stopped{color:var(--amber)}"
)


QUEUE_SCRIPT = """
(function(){
var m=document.querySelector('meta[name=factory-token]');
var API=(document.querySelector('meta[name=factory-api]')||{}).content||'';
if(!m||location.protocol==='file:')return;
var token=m.content,btns=document.querySelectorAll('button[data-stage]');
var box=document.getElementById('runstatus'),busy=false;
function say(t){if(box)box.textContent=t;}
function issues(r){
  return (r.issues||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';
}
function poll(){
  fetch(API+'/api/queue/runs').then(function(r){return r.json();}).then(function(r){
    var runs=r.runs||[],open=runs.filter(function(x){return x.status==='running';})[0];
    var pls=r.pipelines||[],pl=pls.filter(function(x){return x.status==='running';})[0];
    busy=!!open||!!pl;
    btns.forEach(function(b){b.disabled=busy;});
    var last=open||runs[0];
    var cur=last?' ('+last.stage+': '+last.status+')':'';
    if(pl)say('pipeline '+pl.pipeline_id+': running'+cur);
    else if(last)say('run '+last.run_id+' ('+last.stage+'): '+last.status
      +(pls[0]?'; pipeline '+pls[0].pipeline_id+': '+pls[0].status:''));
    if(busy)setTimeout(poll,5000);
  }).catch(function(e){say('status unavailable: '+e);});
}
var intrBox=document.getElementById('interrupted'),
  preview=document.getElementById('resume-preview'),
  go=document.getElementById('resume-go'),
  out=document.getElementById('resume-out'),
  clean=true,resumeLast=null;
function textOf(el,lines){
  el.replaceChildren();
  lines.forEach(function(t){var li=document.createElement('li');li.textContent=t;el.appendChild(li);});
}
function summary(d){
  var lines=[];
  (d.runs||[]).forEach(function(r){lines.push('run '+r.run_id+' ('+r.stage+'): '+r.kind
    +(r.kind==='limit'?(r.limit_reset_at?' (usage limit; resets '+r.limit_reset_at+(r.limit_reset_estimated?' (estimated)':'')+')':r.limit_reset_text?' (usage limit; resets '+r.limit_reset_text+')':' (usage limit; reset unknown)'):'')
    +(r.stage_pending?'':', no pending units'));});
  (d.pipelines||[]).forEach(function(p){lines.push('pipeline '+p.pipeline_id+': '+p.kind
    +'; stages left: '+((p.stages_left||[]).join(', ')||'none'));});
  (d.leases||[]).forEach(function(l){lines.push('expired leases, '+l.kind+': '+l.count);});
  (d.passes||[]).forEach(function(p){
    var where=p.module==='screening'?p.stage:p.scope;
    lines.push('stale pass '+where+' '+p.label+': '+p.pending+' pending, session '+p.session
      +' silent since '+p.last_activity);});
  var a=d.automatic||{};
  if(a.resolve)lines.push('papers never looked up: '+a.resolve);
  if(a.fetch)lines.push('screened-in papers without full text sought: '+a.fetch);
  if(a.convert)lines.push('full texts not converted: '+a.convert);
  if(!lines.length)lines.push('Nothing is interrupted.');
  return lines;
}
function planLines(p){
  var lines=[];
  if(p.reconcile&&p.reconcile.length)lines.push('reconciled (process gone): '+p.reconcile.join(', '));
  (p.leases||[]).forEach(function(l){lines.push('leases lapsed, released by expiry: '+l.kind+' x'+l.count);});
  if(p.pipeline)lines.push('pipeline '+p.pipeline.resumes+' resumed from stage '+p.pipeline.from_stage
    +' ('+p.pipeline.stages.join(', ')+')');
  if(p.run)lines.push('run '+p.run.resumes+' resumed: stage '+p.run.stage+' with model '+p.run.model);
  (p.waiting||[]).forEach(function(w){lines.push('waiting (not resumed): '+w);});
  if(p.queued&&p.queued.length)lines.push('queued (resumed by a later call): '+p.queued.join(', '));
  (p.stale_passes||[]).forEach(function(s){
    var where=s.module==='screening'?s.stage:s.scope;
    lines.push('stale pass (not resumed): '+s.module+' '+where+' '+s.label+', '+s.pending
      +' pending, session '+s.session);});
  var a=p.automatic||{};
  if(a.resolve||a.fetch||a.convert)lines.push('automatic steps undone: resolve '+(a.resolve||0)
    +', fetch '+(a.fetch||0)+', convert '+(a.convert||0));
  return lines.length?lines:['nothing interrupted'];
}
function resultLines(r){
  if(r.error)return ['error: '+r.error];
  var lines=[];
  (r.reconciled||[]).forEach(function(x){lines.push('reconciled run '+x);});
  if(r.pipeline_id)lines.push('started pipeline '+r.pipeline_id);
  if(r.run_id)lines.push('started run '+r.run_id);
  (r.refused||[]).forEach(function(x){lines.push('refused: '+x);});
  return lines.length?lines:['nothing started'];
}
function refreshInterrupted(){
  fetch(API+'/api/queue/interrupted').then(function(r){return r.json();}).then(function(d){
    if(intrBox)textOf(intrBox,summary(d));
    clean=!!d.is_clean;resumeLast=d.last_resume||null;
    if(go)go.disabled=!token||clean||busy;
  }).catch(function(e){if(intrBox)textOf(intrBox,['unavailable: '+e]);});
}
function postResume(body){
  return fetch(API+'/api/queue/resume',{method:'POST',
    headers:{'Content-Type':'application/json','X-Factory-Token':token},
    body:JSON.stringify(body)})
  .then(function(r){
    return r.json().catch(function(){
      return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};
    });
  });
}
if(preview)preview.addEventListener('click',function(){
  if(out)out.textContent='planning...';
  postResume({dry_run:true}).then(function(r){
    if(!r.ok){if(out)out.textContent=issues(r);return;}
    if(out)out.textContent=planLines(r.plan).join('\n');
  }).catch(function(e){if(out)out.textContent='request failed: '+e;});
});
if(go)go.addEventListener('click',function(){
  go.disabled=true;
  postResume({}).then(function(r){
    if(!r.ok){if(out)out.textContent=issues(r);refreshInterrupted();return;}
    if(out)out.textContent='resume started; the outcome appears here when it ends.';
    setTimeout(refreshInterrupted,3000);
  }).catch(function(e){if(out)out.textContent='request failed: '+e;go.disabled=false;});
});
if(preview)preview.disabled=false;
if(token&&location.protocol!=='file:'){refreshInterrupted();setInterval(refreshInterrupted,15000);}
btns.forEach(function(b){
  b.addEventListener('click',function(){
    btns.forEach(function(x){x.disabled=true;});
    fetch(API+'/api/queue/process',{method:'POST',
      headers:{'Content-Type':'application/json','X-Factory-Token':token},
      body:JSON.stringify({stage:b.dataset.stage,exploratory:b.dataset.exploratory==='1'})})
    .then(function(r){
      return r.json().catch(function(){
        return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};
      });
    })
    .then(function(r){
      if(!r.ok){say(issues(r));btns.forEach(function(x){x.disabled=false;});return;}
      say(r.pipeline_id?'pipeline '+r.pipeline_id+': running'
        :'run '+r.run_id+' ('+r.stage+'): running');setTimeout(poll,3000);
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
        page(
            "Work queue",
            _body(queue(project), stages(project), project) + f"<script>{QUEUE_SCRIPT}</script>",
            QUEUE_CSS,
        ),
        encoding="utf-8",
    )


def _body(work: WorkQueue, plan: list[PipelineStage], project: Project) -> str:
    progress = paper_progress(project, work.items, plan) if work.items else {}
    return (
        "<h1>Work queue</h1>"
        + _added_html(work.items)
        + _progress_html(work.items, plan, progress)
        + "<h2>Pending work</h2>"
        + _pending_html(work.pending, plan)
        + _interrupted_html(project)
    )


def _limit_note(run: InterruptedRun) -> str:
    """For a limit-stopped run: the usage-limit stop and its reset, when the log gives one."""
    if run.kind != "limit":
        return ""
    when = run.limit_reset_at or run.limit_reset_text
    if not when:
        return " (usage limit; reset unknown)"
    estimated = " (estimated)" if run.limit_reset_at and run.limit_reset_estimated else ""
    return f" (usage limit; resets {when}{estimated})"


def summary_lines(found: Interrupted) -> list[str]:
    """The panel's lines for `found` (the script builds the same lines from the JSON)."""
    lines: list[str] = []
    for run in found.runs:
        pending = "" if run.stage_pending else ", no pending units"
        lines.append(f"run {run.run_id} ({run.stage}): {run.kind}{_limit_note(run)}{pending}")
    for pipe in found.pipelines:
        left = ", ".join(pipe.stages_left) or "none"
        lines.append(f"pipeline {pipe.pipeline_id}: {pipe.kind}; stages left: {left}")
    for lease in found.leases:
        lines.append(f"expired leases, {lease.kind}: {lease.count}")
    for item in found.passes:
        where = item.stage if item.module == "screening" else item.scope
        lines.append(
            f"stale pass {where} {item.label}: {item.pending} pending, session {item.session} "
            f"silent since {item.last_activity}"
        )
    a = found.automatic
    if a.resolve:
        lines.append(f"papers never looked up: {a.resolve}")
    if a.fetch:
        lines.append(f"screened-in papers without full text sought: {a.fetch}")
    if a.convert:
        lines.append(f"full texts not converted: {a.convert}")
    return lines or ["Nothing is interrupted."]


def _interrupted_html(project: Project) -> str:
    """The Interrupted panel: the lines of `interrupted`, and the Preview and Resume buttons. Both
    buttons start disabled; the script enables them when served by the hub."""
    try:
        found = interrupted(project)
    except Exception:  # a panel must never take the page down
        body = "<ul id=interrupted class=intr><li>unavailable</li></ul>"
    else:
        items = "".join(f"<li>{escape(line)}</li>" for line in summary_lines(found))
        body = f"<ul id=interrupted class='intr dim'>{items}</ul>"
    controls = (
        "<div class=proc><button type=button id=resume-preview disabled>Preview</button> "
        "<button type=button id=resume-go disabled>Resume</button>"
        "<pre id=resume-out></pre></div>"
    )
    return "<h2>Interrupted</h2>" + body + controls


def _progress_html(
    items: list[QueueItem], plan: list[PipelineStage], progress: dict[str, dict[str, CellState]]
) -> str:
    """One row per added paper, one column per applicable stage with a per-paper reading."""
    columns = [s for s in plan if s.applies and s.key != "intuition"]
    if not items or not columns:
        return ""
    head = "".join(f"<th>{escape(s.label)}</th>" for s in columns)
    rows = "".join(
        f"<tr><td>{escape(item.title or item.entry_id)}</td>"
        + "".join(
            f"<td><span class='cell {cell}'>{escape(cell)}</span></td>"
            for cell in (progress.get(item.entry_id, {}).get(s.key, "n/a") for s in columns)
        )
        + "</tr>"
        for item in items
    )
    return (
        "<h2>Progress per paper</h2><table class=qtable>"
        f"<tr><th>Paper</th>{head}</tr>{rows}</table>"
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


def _pending_html(pending: dict[str, int], plan: list[PipelineStage]) -> str:
    rows = "".join(
        f"<tr><td>{escape(kind)}</td><td>{count}</td></tr>"
        for kind, count in sorted(pending.items())
    )
    table = (
        f"<table class=qtable><tr><th>Task kind</th><th>Open units</th></tr>{rows}</table>"
        if rows
        else "<p class=dim>No unit of work is defined yet.</p>"
    )
    every = (
        "<div class=proc><strong>All stages</strong> <span class=dim>Run each stage with pending "
        "work in order, the automatic steps between them; stops at the first failed run.</span>"
        "<br><button type=button disabled data-stage='all'>Process all</button></div>"
    )
    buttons = every + "".join(
        f"<div class=proc><strong>{escape(s.label)}</strong> "
        f"<span class=dim>{s.pending} pending ({escape(s.model)}).</span>"
        f"<br><button type=button disabled data-stage='{escape(s.key)}'>Process now</button></div>"
        for s in plan
        if s.applies
    )
    buttons += "".join(
        f"<div class=proc><strong>{escape(s.label)}</strong> "
        f"<span class=dim>{s.pending} pending ({escape(s.model)}); {escape(s.reason)}.</span>"
        f"<br><button type=button disabled data-stage='{escape(s.key)}' data-exploratory=1>"
        "Process exploratory</button></div>"
        for s in plan
        if s.exploratory_only
    )
    hint = (
        "<p class=dim id=runstatus>Process now works when this page is opened with "
        "<code>factory site serve</code>.</p>"
    )
    return table + buttons + hint + _legend()


def _legend() -> str:
    names = ", ".join(STAGES)
    return f"<p class=dim>Stages, in path order: {escape(names)}.</p>"
