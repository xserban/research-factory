# ruff: noqa: E501
"""The lifecycle product: the stages of AI research systems as the papers show them (plan
2026-11-13-ai-scientist-lifecycle).

Two sources, both rows of miners read from the index, never judged here:
- `m-stages`: which of the miner's fixed stages a system automates, and in what mode. The page
  draws these as a flow whose node size is the number of works and whose arcs are the number of
  works that cover both stages (co-occurrence, not order). The order of the nodes is a layout
  convention (a typical research cycle), not a finding.
- `m-lifecycle`: the stages each paper describes in its own words, in its own order, with who
  does each and what follows it. Shown as one sequence per paper, linked to the paper.

Every work, stage and arc is a link or a click: a stage opens its works with the quote behind each
row, a work opens in the explorer. The state (layer, mode, stage) lives in the URL hash, so any view
can be linked to or bookmarked.
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
from factory.services.site_widgets import REPORT_CSS, esc, section

# the stages of the `m-stages` miner in the order a research cycle usually runs them (layout only)
STAGES: tuple[tuple[str, str], ...] = (
    ("literature-review", "Literature review"),
    ("ideation-hypothesis", "Ideation and hypothesis"),
    ("experiment-design", "Experiment design"),
    ("implementation-execution", "Implementation and execution"),
    ("data-analysis", "Data analysis"),
    ("paper-writing", "Paper writing"),
    ("review-verification", "Review and verification"),
    ("lab-automation", "Lab automation"),
    ("other", "Other"),
)
MODES: tuple[str, ...] = ("automated", "human-assisted", "mentioned-only")
LAYER_ORDER: tuple[str, ...] = (
    "core",
    "benchmark",
    "applied",
    "adjacent",
    "background",
    "off-topic",
)


def lifecycle_data(
    works: Sequence[Mapping[str, Any]], layers: Mapping[str, str | None]
) -> dict[str, Any]:
    """The page's data from the explorer's works (`stages`: rows with stage, mode, quote, anchor)
    and the layer of each work id (None when pending). Only works with at least one stage row are
    kept. Pure: the same inputs give the same output, in work-id order."""
    out: list[dict[str, Any]] = []
    for w in sorted(works, key=lambda w: str(w["id"])):
        by_stage: dict[str, list[dict[str, str]]] = defaultdict(list)
        for r in w.get("stages") or ():
            by_stage[str(r["stage"])].append(
                {
                    "mode": str(r.get("mode") or ""),
                    "quote": str(r.get("quote") or ""),
                    "anchor": str(r.get("anchor") or ""),
                }
            )
        if not by_stage:
            continue
        out.append(
            {
                "slug": str(w["slug"]),
                "title": str(w.get("title") or w["id"]),
                "year": str(w.get("year") or ""),
                "layer": layers.get(str(w["id"])) or "pending",
                "stages": dict(by_stage),
            }
        )
    counts: dict[str, int] = defaultdict(int)
    for w in out:
        counts[str(w["layer"])] += 1
    known = [(k, v) for k, v in counts.items()]
    known.sort(
        key=lambda kv: (
            LAYER_ORDER.index(kv[0]) if kv[0] in LAYER_ORDER else len(LAYER_ORDER),
            kv[0],
        )
    )
    return {
        "stages": [{"id": i, "name": n} for i, n in STAGES],
        "modes": list(MODES),
        "layers": [{"id": k, "n": v} for k, v in known],
        "works": out,
    }


def own_stage_sequences(project: Project) -> list[dict[str, Any]]:
    """The stages each paper describes (`m-lifecycle`, live pass-A rows of the latest version), one
    entry per work in work-id order: rows sorted by their `stage_order`. Empty when the miner has
    no rows. Reads the index only."""
    with project.index.connect() as conn:
        schema = conn.execute(
            text(
                "SELECT schema_ref FROM extraction_rows WHERE schema_ref LIKE 'm-lifecycle@%' "
                "ORDER BY CAST(substr(schema_ref, instr(schema_ref, '@') + 1) AS INTEGER) DESC LIMIT 1"
            )
        ).scalar()
        if schema is None:
            return []
        rows = conn.execute(
            text(
                "SELECT extraction_id, work_id FROM extraction_rows WHERE pass_label = 'A' "
                "AND superseded_by IS NULL AND schema_ref = :s"
            ),
            {"s": schema},
        ).all()
        ids = {str(r[0]): str(r[1]) for r in rows}
        fields: dict[str, dict[str, tuple[str, str, str]]] = defaultdict(dict)
        for eid, name, value, quote, anchor in conn.execute(
            text("SELECT extraction_id, field, value, quote, anchor FROM extraction_fields")
        ):
            if str(eid) in ids:
                fields[str(eid)].setdefault(
                    str(name), (str(value or ""), str(quote or ""), str(anchor or ""))
                )
        titles: dict[str, dict[str, str]] = {}
        for wid in set(ids.values()):
            row = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": wid}
            ).first()
            if row is not None:
                d = json.loads(row[0])
                titles[wid] = {
                    "title": d.get("title") or wid,
                    "year": ((d.get("dates") or {}).get("published") or "")[:4],
                }
    per_work: dict[str, list[dict[str, str]]] = defaultdict(list)
    for eid, wid in ids.items():
        f = fields.get(eid, {})
        if "stage_order" not in f:
            continue
        per_work[wid].append(
            {
                "order": f["stage_order"][0],
                "name": f.get("stage_name", ("", "", ""))[1]
                or f.get("stage_name", ("", "", ""))[0],
                "actor": f.get("actor", ("", "", ""))[0],
                "how": f.get("how", ("", "", ""))[1],
                "next": f.get("next_stage", ("", "", ""))[0],
                "loops": f.get("loops_back_to", ("", "", ""))[0],
                "anchor": f["stage_order"][2],
            }
        )
    out: list[dict[str, Any]] = []
    for wid in sorted(per_work):
        stages = sorted(
            per_work[wid],
            key=lambda s: (int(s["order"]) if s["order"].isdigit() else 99, s["name"]),
        )
        out.append(
            {
                "id": wid,
                "title": titles.get(wid, {}).get("title", wid),
                "year": titles.get(wid, {}).get("year", ""),
                "stages": stages,
            }
        )
    return out


def _slug(wid: str) -> str:
    from factory.services.site_corpus import slug_of

    return slug_of(wid)


def render_own_sequences(seqs: Sequence[Mapping[str, Any]]) -> str:
    """One row per paper: its stages in order, each with who does it; a loop is shown as ↺ n and a
    link to the next stage as → n. Titles link to the explorer."""
    if not seqs:
        return (
            "<p class=dim>No paper has stage rows from the miner <code>m-lifecycle</code> yet. "
            "It is registered and listed for core works; its calibration (a sample of 10 works "
            "labelled by the researcher) comes before the production run.</p>"
        )
    rows = ""
    lead = (
        f"<p class=dim>{len(seqs)} papers, from pass A of <code>m-lifecycle</code>. Until the production "
        "run these are the calibration sample only, and not yet checked against the researcher's gold labels.</p>"
    )
    for s in seqs:
        chain = " ".join(
            f"<span class='st {esc(st['actor'] or 'na')}' title='{esc(st['how'] or st['name'])}'>"
            f"<b>{esc(st['order'])}</b> {esc(st['name'][:60])}"
            f"{' → ' + esc(st['next']) if st['next'] else ''}{' ↺ ' + esc(st['loops']) if st['loops'] else ''}</span>"
            for st in s["stages"]
        )
        slug = _slug(str(s["id"]))
        rows += (
            f"<tr><td><a href='../explorer/index.html#open={html.escape(slug, quote=True)}'>{esc(str(s['title'])[:90])}</a>"
            f"<br><small>{esc(s['year'])}</small></td><td>{chain}</td></tr>"
        )
    return (
        lead
        + f"<table class=seq><tr><th>paper</th><th>its own stages, in its order (hover for how it is done)</th></tr>{rows}</table>"
    )


CSS = (
    ".lc-bar{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px;align-items:center}"
    ".lc-bar b{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin-right:6px}"
    ".chip{border:1px solid var(--mut);background:var(--card);color:var(--fg);padding:3px 10px;cursor:pointer;font:inherit;font-size:12px}"
    ".chip.on{border-color:var(--ac);color:var(--ac)}.chip:hover{background:var(--hov)}"
    "#lc-svg{width:100%;max-width:980px;height:auto;border:1px solid var(--mut);background:var(--card)}"
    "#lc-svg .node{cursor:pointer}#lc-svg .node circle{fill:var(--ac);fill-opacity:.25;stroke:var(--ac);stroke-width:1.5}"
    "#lc-svg .node.sel circle{fill-opacity:.6}#lc-svg .node text{fill:var(--fg);font-size:11px;text-anchor:middle}"
    "#lc-svg .arc{fill:none;stroke:var(--blue);stroke-opacity:.35;cursor:pointer}#lc-svg .arc:hover,#lc-svg .arc.sel{stroke-opacity:.9}"
    "#lc-svg .num{fill:var(--fg);font-size:12px;text-anchor:middle;font-weight:600}"
    "#lc-list li{margin:0 0 10px;list-style:none;padding:0}#lc-list q{display:block;color:var(--light);margin:2px 0 0;font-size:12px}"
    ".badge{font-size:10px;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--mut);padding:0 6px;margin-left:6px;color:var(--dim)}"
    ".badge.automated{color:var(--ac);border-color:var(--ac)}"
    "table.seq td{line-height:2}.st{display:inline-block;border:1px solid var(--mut);padding:0 8px;margin:0 4px 4px 0;font-size:12px;white-space:nowrap}"
    ".st.automated{border-color:var(--ac)}.st.human-assisted{border-color:var(--amber)}.st b{color:var(--ac)}"
)

SCRIPT = r"""
(function(){
var D=JSON.parse(document.getElementById('lc-data').textContent);
var S={layer:'all',mode:'any',sel:null};
function readHash(){var h=location.hash.replace(/^#/,'').split('&');h.forEach(function(p){var kv=p.split('=');if(kv[0]==='layer')S.layer=decodeURIComponent(kv[1]||'all');if(kv[0]==='mode')S.mode=decodeURIComponent(kv[1]||'any');if(kv[0]==='stage')S.sel=decodeURIComponent(kv[1]||'')||null;});}
function writeHash(){var p=['layer='+encodeURIComponent(S.layer),'mode='+encodeURIComponent(S.mode)];if(S.sel)p.push('stage='+encodeURIComponent(S.sel));history.replaceState(null,'','#'+p.join('&'));}
function el(t,a,c){var e=document.createElementNS(a&&a.ns||'http://www.w3.org/1999/xhtml',t);for(var k in (a||{})){if(k!=='ns')e.setAttribute(k,a[k]);}if(c!=null)e.textContent=c;return e;}
function svg(t,a,c){a=a||{};a.ns='http://www.w3.org/2000/svg';return el(t,a,c);}
function works(){return D.works.filter(function(w){return S.layer==='all'||w.layer===S.layer;});}
function has(w,sid){var r=w.stages[sid];if(!r)return false;return S.mode==='any'||r.some(function(x){return x.mode===S.mode;});}
function chips(id,items,cur,fn){var b=document.getElementById(id);b.innerHTML='';var l=el('b',{},b.dataset.label);b.appendChild(l);items.forEach(function(it){var c=el('button',{'class':'chip'+(it.id===cur?' on':''),type:'button'},it.label);c.onclick=function(){fn(it.id);};b.appendChild(c);});}
function draw(){
  var ws=works(),st=D.stages,n={},pair={};
  st.forEach(function(s){n[s.id]=ws.filter(function(w){return has(w,s.id);}).length;});
  st.forEach(function(a,i){st.forEach(function(b,j){if(j>i){pair[a.id+'|'+b.id]=ws.filter(function(w){return has(w,a.id)&&has(w,b.id);}).length;}});});
  var max=Math.max.apply(null,Object.values(n).concat([1])),pmax=Math.max.apply(null,Object.values(pair).concat([1]));
  var root=document.getElementById('lc-svg');root.innerHTML='';
  var W=980,main=st.slice(0,7),X=function(i){return 70+i*(W-140)/6;},pos={};
  main.forEach(function(s,i){pos[s.id]=[X(i),210];});
  pos['lab-automation']=[X(2),340];pos['other']=[X(4),340];
  Object.keys(pair).forEach(function(k){var c=pair[k];if(c<1)return;var ab=k.split('|'),p=pos[ab[0]],q=pos[ab[1]];var mx=(p[0]+q[0])/2,my=Math.min(p[1],q[1])-30-Math.abs(p[0]-q[0])*.22+(p[1]!==q[1]?60:0);
    var path=svg('path',{'class':'arc'+(S.sel===k?' sel':''),d:'M'+p[0]+','+(p[1]-26)+' Q'+mx+','+my+' '+q[0]+','+(q[1]-26),'stroke-width':(0.5+7*c/pmax).toFixed(1)});
    var tt=svg('title',{},c+' works cover both '+ab[0]+' and '+ab[1]);path.appendChild(tt);path.onclick=function(){S.sel=k;writeHash();draw();};root.appendChild(path);});
  st.forEach(function(s){var p=pos[s.id];var r=14+34*Math.sqrt(n[s.id]/max);var g=svg('g',{'class':'node'+(S.sel===s.id?' sel':''),transform:'translate('+p[0]+','+p[1]+')'});
    g.appendChild(svg('circle',{r:r}));g.appendChild(svg('text',{y:r+16},s.name));g.appendChild(svg('text',{'class':'num',y:4},String(n[s.id])));
    g.appendChild(svg('title',{},n[s.id]+' works: '+s.name));g.onclick=function(){S.sel=s.id;writeHash();draw();};root.appendChild(g);});
  root.setAttribute('viewBox','0 0 '+W+' 420');
  chips('lc-layers',[{id:'all',label:'all ('+D.works.length+')'}].concat(D.layers.map(function(l){return {id:l.id,label:l.id+' ('+l.n+')'};})),S.layer,function(v){S.layer=v;writeHash();draw();});
  chips('lc-modes',[{id:'any',label:'any mode'}].concat(D.modes.map(function(m){return {id:m,label:m};})),S.mode,function(v){S.mode=v;writeHash();draw();});
  list(ws);
}
function list(ws){
  var box=document.getElementById('lc-list'),head=document.getElementById('lc-head');box.innerHTML='';
  if(!S.sel){head.textContent='Click a stage or an arc to list its works.';return;}
  var ids=S.sel.split('|'),names=ids.map(function(i){var f=D.stages.filter(function(s){return s.id===i;})[0];return f?f.name:i;});
  var hit=ws.filter(function(w){return ids.every(function(i){return has(w,i);});});
  head.textContent=hit.length+' works'+(ids.length>1?' cover both ':' cover ')+names.join(' and ')+(S.layer!=='all'?' (layer '+S.layer+')':'');
  hit.forEach(function(w){var li=el('li');var a=el('a',{href:'../explorer/index.html#open='+encodeURIComponent(w.slug)},w.title);li.appendChild(a);li.appendChild(el('span',{'class':'badge'},w.layer));
    ids.forEach(function(i){(w.stages[i]||[]).slice(0,1).forEach(function(r){li.appendChild(el('span',{'class':'badge '+r.mode},r.mode));if(r.quote){var q=el('q',{},r.quote.slice(0,260)+(r.anchor?'  ['+r.anchor+']':''));li.appendChild(q);}});});box.appendChild(li);});
}
readHash();draw();window.addEventListener('hashchange',function(){readHash();draw();});
})();
"""


def _matrix(data: Mapping[str, Any]) -> str:
    """A server-rendered table (works per stage and layer) whose cells link into the interactive view."""
    layers = [str(layer["id"]) for layer in data["layers"]]
    head = "".join(f"<th>{esc(layer)}</th>" for layer in layers)
    rows = ""
    for st in data["stages"]:
        cells = ""
        for layer in layers:
            n = sum(1 for w in data["works"] if w["layer"] == layer and st["id"] in w["stages"])
            href = f"#layer={html.escape(layer, quote=True)}&mode=any&stage={html.escape(str(st['id']), quote=True)}"
            cells += f"<td class=n><a href='{href}'>{n}</a></td>" if n else "<td class=n>0</td>"
        total = sum(1 for w in data["works"] if st["id"] in w["stages"])
        href = f"#layer=all&mode=any&stage={html.escape(str(st['id']), quote=True)}"
        rows += f"<tr><td>{esc(st['name'])}</td>{cells}<td class=n><a href='{href}'>{total}</a></td></tr>"
    return f"<table><tr><th>stage</th>{head}<th>all</th></tr>{rows}</table>"


def build_lifecycle(project: Project, out: Path) -> None:
    from factory.services.site import page
    from factory.services.site_corpus import corpus_payload

    works: list[dict[str, Any]] = corpus_payload(project)["works"]
    try:
        from factory.services.work_layers import layers_of

        layer_map: dict[str, str | None] = {wid: wl.layer for wid, wl in layers_of(project).items()}
    except Exception:  # layers are an aid: a project without them still gets the page
        layer_map = {}
    data = lifecycle_data(works, layer_map)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    slug = esc(project.paths.slug)
    body = "<h1>Lifecycle of AI research systems</h1>"
    body += (
        "<div class=note>Each node is a stage of the <code>m-stages</code> miner; its size is the number of works that "
        "automate it, and an arc joins two stages that the same works cover (thicker is more works). "
        "The left-to-right order is a layout convention, not a finding. <b>Click a stage or an arc</b> "
        "to list its works with the quote behind each row; click a work to open it in the explorer. "
        "Filter by layer (the layer pass, not yet calibrated) and by mode. The view is in the URL, so "
        "you can link to it.</div>"
    )
    body += (
        "<div class=lc-bar id=lc-layers data-label=layer></div><div class=lc-bar id=lc-modes data-label=mode></div>"
        "<svg id=lc-svg role=img aria-label='Stages of AI research systems and how often works cover them'></svg>"
        "<h3 id=lc-head></h3><ul id=lc-list></ul>"
        f"<script type='application/json' id='lc-data'>{payload}</script><script>{SCRIPT}</script>"
    )
    body += section(
        "Works per stage and layer",
        "<p class=dim>Each count opens the list above for that stage and layer.</p>"
        + _matrix(data),
    )
    body += section(
        "The stages each paper describes in its own words",
        render_own_sequences(own_stage_sequences(project)),
    )
    body += section(
        "What you can do",
        "<ul class=links>"
        "<li><a href='../explorer/index.html'>Explorer</a>: every paper with its rows and quotes.</li>"
        "<li><a href='../miners/index.html'>Miners</a>: the state of <code>m-stages</code> and <code>m-lifecycle</code> (units, rows, agreement).</li>"
        "<li><a href='../agreement/index.html'>Agreement</a>: how far two passes agree.</li>"
        "<li><a href='../taxonomy/index.html'>Taxonomy</a>: the categories the classification miner uses.</li>"
        "<li><a href='../backlog/index.html'>Backlog</a>: what is planned for this view.</li></ul>"
        "<p class=dim>Next step (plan 2026-11-13-ai-scientist-lifecycle): label the calibration sample of "
        "<code>m-lifecycle</code>, run it on the core works, then group the papers' stage names into a common lifecycle. "
        f"Commands: <code>factory --project {slug} mine status</code>.</p>",
    )
    (out / "index.html").write_text(page("Lifecycle", body, REPORT_CSS + CSS), encoding="utf-8")
