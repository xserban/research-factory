# ruff: noqa: E501
"""The steps product: what the exploratory miner `m-stage-steps` found (v1, pass A).

For each of the nine research-lifecycle stages, the steps an AI research system takes in that stage,
per paper and in the paper's own order, each with its actor and, where the paper says so, its
inputs, outputs, method, check and limits, every one with its verbatim quote and anchor.

The miner has no calibration: the rows are for reading, not evidence, and no count from them goes
into a report. The page says so at the top. Rows are read from the index (closed pass-A rows of the
latest `m-stage-steps` version, live only); nothing is judged here. The page is static: the filters
(stage, actor, has a check, has limits, text) are plain JavaScript over data attributes.
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text

from factory.services.context import Project
from factory.services.site_lifecycle import STAGES
from factory.services.site_widgets import REPORT_CSS, esc

MINER = "m-stage-steps"
ACTORS: tuple[str, ...] = ("automated", "human-assisted", "human", "not-stated")
OPTIONAL: tuple[tuple[str, str], ...] = (
    ("inputs", "inputs"),
    ("outputs", "outputs"),
    ("method", "method"),
    ("check", "check"),
    ("limits", "limits"),
)
__all__ = ["STAGES", "build_steps", "render_steps", "step_rows", "steps_view"]


def _shown_actor(actor: str) -> str:
    """The label of an actor: absence is worded as such, never shown as a value."""
    return "not stated" if actor in ("not-stated", "") else actor


def step_rows(project: Project) -> list[dict[str, Any]]:
    """The live, closed pass-A rows of the latest `m-stage-steps` version, one dict per row:
    `work`, `title`, `year`, `stage`, `order`, `step`, `actor`, and each optional field as
    `{text, quote, anchor}` or None. Empty when the miner has no rows. Reads the index only."""
    like = f"{MINER}@%"
    with project.index.connect() as conn:
        schema = conn.execute(
            text(
                "SELECT schema_ref FROM extraction_rows WHERE schema_ref LIKE :l "
                "ORDER BY CAST(substr(schema_ref, instr(schema_ref, '@') + 1) AS INTEGER) DESC LIMIT 1"
            ),
            {"l": like},
        ).scalar()
        if schema is None:
            return []
        ids = {
            str(r[0]): str(r[1])
            for r in conn.execute(
                text(
                    "SELECT x.extraction_id, x.work_id FROM extraction_rows x "
                    "JOIN extraction_closures c ON c.task_id = x.task_id "
                    "WHERE x.pass_label = 'A' AND x.superseded_by IS NULL AND x.schema_ref = :s"
                ),
                {"s": schema},
            )
        }
        fields: dict[str, dict[str, tuple[str, str, str]]] = defaultdict(dict)
        for eid, name, value, quote, anchor in conn.execute(
            text(
                "SELECT f.extraction_id, f.field, f.value, f.quote, f.anchor FROM extraction_fields f "
                "JOIN extraction_rows x ON x.extraction_id = f.extraction_id "
                "WHERE x.schema_ref = :s AND x.pass_label = 'A' AND x.superseded_by IS NULL"
            ),
            {"s": schema},
        ):
            if str(eid) in ids:
                fields[str(eid)].setdefault(
                    str(name), (str(value or ""), str(quote or ""), str(anchor or ""))
                )
        titles: dict[str, tuple[str, str]] = {}
        for wid in set(ids.values()):
            row = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": wid}
            ).first()
            if row is not None:
                d = json.loads(row[0])
                titles[wid] = (
                    str(d.get("title") or wid),
                    str((d.get("dates") or {}).get("published") or "")[:4],
                )
    out: list[dict[str, Any]] = []
    for eid, wid in ids.items():
        f = fields.get(eid, {})
        if "stage" not in f or "step" not in f:
            continue

        def opt(name: str, f: dict[str, tuple[str, str, str]] = f) -> dict[str, str] | None:
            if name not in f:
                return None
            value, quote, anchor = f[name]
            return {"text": quote or value, "anchor": anchor}

        row_out: dict[str, Any] = {
            "work": wid,
            "title": titles.get(wid, (wid, ""))[0],
            "year": titles.get(wid, (wid, ""))[1],
            "stage": f["stage"][0],
            "order": f.get("step_order", ("", "", ""))[0],
            "actor": f.get("actor", ("", "", ""))[0],
        }
        row_out["step"] = {"text": f["step"][1] or f["step"][0], "anchor": f["step"][2]}
        for name, _label in OPTIONAL:
            row_out[name] = opt(name)
        out.append(row_out)
    return out


def _slug(wid: str) -> str:
    from factory.services.site_corpus import slug_of

    return slug_of(wid)


def steps_view(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The page's data: per stage (in `STAGES` order) the works with their steps in step order.
    `step` in a row is `{text, anchor}`; a step's optional fields are `{text, anchor}` or None.
    Pure: the same rows in any order give the same view (works by id, steps by order)."""
    by: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        stage = str(r["stage"])
        work = by[stage].setdefault(
            str(r["work"]),
            {
                "id": str(r["work"]),
                "slug": _slug(str(r["work"])),
                "title": str(r.get("title") or r["work"]),
                "year": str(r.get("year") or ""),
                "steps": [],
            },
        )
        order = str(r.get("order") or "")
        work["steps"].append(
            {
                "order": int(order) if order.isdigit() else 99,
                "text": str(r["step"]["text"]),
                "anchor": str(r["step"].get("anchor") or ""),
                "actor": str(r.get("actor") or "not-stated"),
                **{name: r.get(name) for name, _ in OPTIONAL},
            }
        )
    stages: list[dict[str, Any]] = []
    for sid, name in STAGES:
        works = sorted(by.get(sid, {}).values(), key=lambda w: str(w["id"]))
        for w in works:
            w["steps"].sort(key=lambda s: (s["order"], s["text"]))
        stages.append(
            {
                "id": sid,
                "name": name,
                "n_works": len(works),
                "n_steps": sum(len(w["steps"]) for w in works),
                "works": works,
            }
        )
    return {"stages": stages}


def _detail(label: str, cell: Mapping[str, Any] | None) -> str:
    if not cell:
        return ""
    anchor = f" <small class=dim>[{esc(cell['anchor'])}]</small>" if cell.get("anchor") else ""
    return (
        f"<details class=sd><summary>{esc(label)}</summary>"
        f"<q>{esc(cell['text'])}</q>{anchor}</details>"
    )


def _step(s: Mapping[str, Any]) -> str:
    actor = str(s["actor"])
    attrs = (
        f"data-actor='{html.escape(actor, quote=True)}' data-check='{1 if s['check'] else 0}' "
        f"data-limits='{1 if s['limits'] else 0}' "
        f"data-text='{html.escape(' '.join(str(s['text']).lower().split()), quote=True)}'"
    )
    anchor = f" <small class=dim>[{esc(s['anchor'])}]</small>" if s["anchor"] else ""
    details = "".join(_detail(label, s[name]) for name, label in OPTIONAL)
    return (
        f"<li class=step {attrs}><span class=ord>{esc(s['order'])}</span> {esc(s['text'])}{anchor}"
        f"<span class='badge {esc(actor)}'>{esc(_shown_actor(actor))}</span>{details}</li>"
    )


def _work(w: Mapping[str, Any]) -> str:
    link = f"../explorer/index.html#open={html.escape(str(w['slug']), quote=True)}"
    year = f" <small class=dim>{esc(w['year'])}</small>" if w["year"] else ""
    steps = "".join(_step(s) for s in w["steps"])
    return (
        f"<div class=work><h4><a href='{link}'>{esc(str(w['title'])[:120])}</a>{year}</h4>"
        f"<ol class=steps>{steps}</ol></div>"
    )


def render_steps(view: Mapping[str, Any]) -> str:
    """The page body: banner, count strip, filters and one section per stage. Everything that comes
    from a row is escaped; a stage without rows says so."""
    strip = ""
    sections = ""
    tabs = "<button type=button class='chip on' data-stage=all>all stages</button>"
    for st in view["stages"]:
        sid = html.escape(str(st["id"]), quote=True)
        strip += (
            f"<a class=cell href='#stage-{sid}' data-go='{sid}'><b>{esc(st['name'])}</b>"
            f"<span>{esc(st['n_works'])} works with steps</span><span>{esc(st['n_steps'])} steps</span></a>"
        )
        tabs += f"<button type=button class=chip data-stage='{sid}'>{esc(st['name'])}</button>"
        body = (
            "".join(_work(w) for w in st["works"])
            if st["works"]
            else "<p class=dim>No steps in this stage: the miner found none in any work.</p>"
        )
        sections += (
            f"<section class=stage id='stage-{sid}' data-stage='{sid}'>"
            f"<h2>{esc(st['name'])} <small class=dim>{esc(st['n_works'])} works, {esc(st['n_steps'])} steps</small></h2>"
            f"{body}</section>"
        )
    actors = "".join(
        f"<option value='{html.escape(a, quote=True)}'>{esc(_shown_actor(a))}</option>"
        for a in ACTORS
    )
    return (
        "<h1>Steps</h1>"
        "<div class='note warn'><b>EXPLORATORY.</b> The miner <code>m-stage-steps</code> v1 has no calibration: "
        "its rows are for reading, not evidence. No count from them goes into a report, a hub claim or a "
        "hypothesis until it is calibrated against gold sub-steps. Some steps may sit in the wrong stage.</div>"
        f"<div class=strip>{strip}</div>"
        f"<div class=lc-bar id=st-tabs>{tabs}</div>"
        "<div class=lc-bar id=st-filters><b>filter</b>"
        f"<label>actor <select id=st-actor><option value=''>any</option>{actors}</select></label>"
        "<label><input type=checkbox id=st-check> has a check</label>"
        "<label><input type=checkbox id=st-limits> has limits</label>"
        "<label>search <input type=search id=st-search placeholder='text of a step'></label>"
        "<span class=dim id=st-count></span></div>"
        f"{sections}<script>{SCRIPT}</script>"
    )


CSS = (
    ".warn{border-color:var(--amber)}"
    ".strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;margin:10px 0}"
    ".strip .cell{display:flex;flex-direction:column;border:1px solid var(--mut);background:var(--card);padding:6px 10px;color:var(--fg);text-decoration:none}"
    ".strip .cell:hover{background:var(--hov)}.strip .cell span{font-size:12px;color:var(--dim)}"
    ".lc-bar{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px;align-items:center}"
    ".lc-bar b{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin-right:6px}"
    ".lc-bar label{font-size:12px;color:var(--fg);margin-right:8px}"
    ".chip{border:1px solid var(--mut);background:var(--card);color:var(--fg);padding:3px 10px;cursor:pointer;font:inherit;font-size:12px}"
    ".chip.on{border-color:var(--ac);color:var(--ac)}.chip:hover{background:var(--hov)}"
    ".work{margin:0 0 14px}.work h4{margin:8px 0 4px}"
    "ol.steps{margin:0;padding:0;list-style:none}li.step{margin:0 0 6px;padding:2px 0 2px 4px;border-left:2px solid var(--mut)}"
    "li.step .ord{color:var(--ac);font-weight:600;margin-right:4px}"
    ".badge{font-size:10px;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--mut);padding:0 6px;margin-left:6px;color:var(--dim)}"
    ".badge.automated{color:var(--ac);border-color:var(--ac)}.badge.human-assisted,.badge.human{border-color:var(--amber)}"
    "details.sd{margin:2px 0 0 18px;font-size:12px}details.sd summary{cursor:pointer;color:var(--dim)}"
    "details.sd q{display:block;color:var(--light);margin:2px 0 0}"
    ".hide{display:none}"
)

SCRIPT = r"""
(function(){
var $=function(i){return document.getElementById(i);};
var S={stage:'all'};
function apply(){
  var actor=$('st-actor').value,chk=$('st-check').checked,lim=$('st-limits').checked,q=$('st-search').value.toLowerCase().trim();
  var nSteps=0;
  Array.prototype.forEach.call(document.querySelectorAll('section.stage'),function(sec){
    var show=S.stage==='all'||sec.dataset.stage===S.stage,ns=0;
    Array.prototype.forEach.call(sec.querySelectorAll('.work'),function(w){
      var any=0;
      Array.prototype.forEach.call(w.querySelectorAll('li.step'),function(li){
        var ok=(!actor||li.dataset.actor===actor)&&(!chk||li.dataset.check==='1')&&(!lim||li.dataset.limits==='1')&&(!q||li.dataset.text.indexOf(q)>=0);
        li.classList.toggle('hide',!ok);if(ok)any++;
      });
      w.classList.toggle('hide',any===0);ns+=any;
    });
    sec.classList.toggle('hide',!show);if(show)nSteps+=ns;
  });
  $('st-count').textContent=nSteps+' steps shown';
}
function setStage(s){S.stage=s;Array.prototype.forEach.call(document.querySelectorAll('#st-tabs .chip'),function(c){c.classList.toggle('on',c.dataset.stage===s);});apply();}
Array.prototype.forEach.call(document.querySelectorAll('#st-tabs .chip'),function(c){c.onclick=function(){setStage(c.dataset.stage);};});
Array.prototype.forEach.call(document.querySelectorAll('.strip .cell'),function(a){a.onclick=function(e){e.preventDefault();setStage(a.dataset.go);};});
['st-actor','st-check','st-limits'].forEach(function(i){$(i).onchange=apply;});
$('st-search').oninput=apply;
apply();
})();
"""


def build_steps(project: Project, out: Path) -> None:
    """Write `index.html` of the steps product into the directory `out`."""
    from factory.services.site import page

    body = render_steps(steps_view(step_rows(project)))
    (out / "index.html").write_text(page("Steps", body, REPORT_CSS + CSS), encoding="utf-8")
