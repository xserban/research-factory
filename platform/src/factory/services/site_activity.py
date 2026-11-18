"""The hub product "Activity": what each agent is working on now (IDEA-98).

Invariants:
- Read-only. Every figure is `services.activity.activity` as of the build; nothing is derived
  here and nothing is recorded. Rate and time left are shown as estimates.
- Served by `factory site serve` (token meta injected, page not opened as a file), an inline
  script polls `GET /api/activity` every `POLL_SECONDS` and redraws the four panels from the JSON
  with `textContent` only. Opened as a file the script does nothing and the page is the
  build-time snapshot, labelled with its time.
- All text from tasks, titles, sessions and trace files is escaped; the page has no external
  resource.
"""
# ruff: noqa: E501 (the page script is one JS string; its lines are long by nature)

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from factory.services.activity import STALE_MINUTES, Activity, activity
from factory.services.context import Project
from factory.services.site_widgets import REPORT_CSS, esc

POLL_SECONDS = 10

ACTIVITY_CSS = (
    REPORT_CSS + ".stale{color:var(--amber)}.dim{color:var(--dim)}"
    ".page h1{font-size:22px}#live{font-size:12px;color:var(--dim);margin:0 0 10px}"
    "td.mono{font-family:var(--mono,monospace);font-size:12px}"
)

ACTIVITY_SCRIPT = """
(function(){
var m=document.querySelector('meta[name=factory-token]');
var API=(document.querySelector('meta[name=factory-api]')||{}).content||'';
if(!m||location.protocol==='file:')return;
var POLL=@POLL@*1000,STALE=@STALE@;
function cell(tr,t,cls){var td=document.createElement('td');td.textContent=t==null?'':String(t);if(cls)td.className=cls;tr.appendChild(td);}
function fill(id,head,rows,empty){
  var box=document.getElementById(id);if(!box)return;box.replaceChildren();
  if(!rows.length){var p=document.createElement('p');p.className='dim';p.textContent=empty;box.appendChild(p);return;}
  var t=document.createElement('table'),h=document.createElement('tr');
  head.forEach(function(x){var th=document.createElement('th');th.textContent=x;h.appendChild(th);});
  t.appendChild(h);rows.forEach(function(r){var tr=document.createElement('tr');
    r.forEach(function(c){cell(tr,c[0],c[1]);});t.appendChild(tr);});
  box.appendChild(t);
}
function render(d){
  fill('active',['Session','Task','Paper','Held (min)','Rows','Last event','State'],
    d.active.map(function(a){
      var task=a.scope+(a.miner_version!=null?' v'+a.miner_version:'')+(a.pass_label?' pass '+a.pass_label:'')+(a.mode?' '+a.mode:'');
      return [[a.session.slice(-6)],[task],[(a.title||a.work_id||'')],[a.minutes_held],[a.rows_recorded],[a.last_event_at||'none'],
        [a.stale?'stale (no event for '+STALE+' min)':'active',a.stale?'stale':'']];}),
    'No task is held.');
  fill('passes',['Pass','Done','Total','Held','Done in 30 min','Rate (estimate, per hour)','Left (estimate, min)','Released'],
    d.passes.map(function(p){return [[p.name+(p.version!=null?' v'+p.version:'')],[p.done],[p.total],[p.claimed],[p.completed_recent],
      [p.rate_estimate_per_hour],[p.eta_estimate_minutes==null?'unknown':p.eta_estimate_minutes],[p.released]];}),
    'No pass is open.');
  fill('operations',['Operation','State','Done','Total','Elapsed (s)'],
    d.operations.map(function(o){return [[o.label||o.op_id],[o.state],[o.done],[o.total==null?'':o.total],[o.elapsed_seconds==null?'':Math.round(o.elapsed_seconds)]];}),
    'No long operation is running.');
  fill('traces',['File','Modified','Last line','Size'],
    d.traces.map(function(t){return [[t.path],[t.modified_at],[t.last_line,'mono'],[t.size]];}),
    'No trace file changed in the last 2 hours.');
  var s=document.getElementById('live');if(s)s.textContent='Live, as of '+d.now+' (refreshed every @POLL@ s).';
}
function poll(){
  fetch(API+'/api/activity').then(function(r){return r.json();}).then(render)
  .catch(function(e){var s=document.getElementById('live');if(s)s.textContent='Live update unavailable: '+e;});
}
poll();setInterval(poll,POLL);
})();
""".replace("@POLL@", str(POLL_SECONDS)).replace("@STALE@", str(STALE_MINUTES))


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f"<p class=dim>{esc(empty)}</p>"
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(cells) + "</tr>" for cells in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _td(value: object, cls: str = "") -> str:
    return f"<td{f' class={cls}' if cls else ''}>{esc('' if value is None else value)}</td>"


def panels(found: Activity) -> str:
    """The four panels as HTML, every value escaped; the script redraws the same panels."""
    active = [
        [
            _td(a.session[-6:]),
            _td(
                a.scope
                + (f" v{a.miner_version}" if a.miner_version is not None else "")
                + (f" pass {a.pass_label}" if a.pass_label else "")
                + (f" {a.mode}" if a.mode else "")
            ),
            _td(a.title or a.work_id or ""),
            _td(a.minutes_held),
            _td(a.rows_recorded),
            _td(a.last_event_at or "none"),
            _td(
                f"stale (no event for {STALE_MINUTES} min)" if a.stale else "active",
                "stale" if a.stale else "",
            ),
        ]
        for a in found.active
    ]
    passes = [
        [
            _td(p.name + (f" v{p.version}" if p.version is not None else "")),
            _td(p.done),
            _td(p.total),
            _td(p.claimed),
            _td(p.completed_recent),
            _td(p.rate_estimate_per_hour),
            _td("unknown" if p.eta_estimate_minutes is None else p.eta_estimate_minutes),
            _td(p.released),
        ]
        for p in found.passes
    ]
    operations = [
        [
            _td(o.get("label") or o.get("op_id")),
            _td(o.get("state")),
            _td(o.get("done")),
            _td(o.get("total")),
            _td(
                round(float(str(o["elapsed_seconds"])))
                if isinstance(o.get("elapsed_seconds"), int | float)
                else ""
            ),
        ]
        for o in found.operations
    ]
    traces = [
        [_td(t.path), _td(t.modified_at), _td(t.last_line, "mono"), _td(t.size)]
        for t in found.traces
    ]
    return (
        "<h2>Held tasks</h2><div id=active>"
        + _table(
            ["Session", "Task", "Paper", "Held (min)", "Rows", "Last event", "State"],
            active,
            "No task is held.",
        )
        + "</div><h2>Passes</h2><div id=passes>"
        + _table(
            [
                "Pass",
                "Done",
                "Total",
                "Held",
                "Done in 30 min",
                "Rate (estimate, per hour)",
                "Left (estimate, min)",
                "Released",
            ],
            passes,
            "No pass is open.",
        )
        + "</div><h2>Long operations</h2><div id=operations>"
        + _table(
            ["Operation", "State", "Done", "Total", "Elapsed (s)"],
            operations,
            "No long operation is running.",
        )
        + "</div><h2>Worker traces</h2><div id=traces>"
        + _table(
            ["File", "Modified", "Last line", "Size"],
            traces,
            "No trace file changed in the last 2 hours.",
        )
        + "</div>"
    )


def build_activity(project: Project, out: Path) -> None:
    """Write `index.html` into `out` from `activity` as of now. Writes no event."""
    from factory.services.site import page

    found = activity(project, datetime.now(UTC))
    body = (
        "<div class=page><h1>Activity</h1>"
        f"<p id=live>Snapshot as of {esc(found.now)}. Served by <code>factory site serve</code>, "
        "this page updates itself.</p>" + panels(found) + "</div>"
    )
    (out / "index.html").write_text(
        page("Activity", body + f"<script>{ACTIVITY_SCRIPT}</script>", ACTIVITY_CSS),
        encoding="utf-8",
    )
