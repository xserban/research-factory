# ruff: noqa: E501
"""The layers product: which layer each work has and where that layer comes from.

A layer is the project's triage of a work (core, benchmark, applied, adjacent, background,
off-topic), set by the layer miner or moved by the researcher (`work_layers.layers_of`). This page
only reads that fold and the explorer's works; it judges nothing.

Invariants:
- Pure data: `layers_view` is a function of the works and the layers, in work-id order within a
  layer and scheme order across layers (an unknown layer follows the known ones, `pending` is last).
- A work with no layer row is not listed; it is counted as `unlayered`, never as pending.
- Every title and id written into the page is escaped; the animation's data is JSON in a script
  block of type `application/json` with `</` escaped.
- The animation's CSS and JS name colours only through CSS variables (canvas colours are read from
  the computed style at draw time and again when the theme changes), never a hard-coded colour.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factory.services.context import Project
from factory.services.site_results import filter_link
from factory.services.site_widgets import REPORT_CSS, esc, section
from factory.services.work_layers import WorkLayer, layer_moves

LAYER_ORDER: tuple[str, ...] = (
    "core",
    "benchmark",
    "applied",
    "adjacent",
    "background",
    "off-topic",
)
PENDING = "pending"

CSS = (
    ".ly-bar{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px}"
    ".ly-bar a{border:1px solid var(--mut);background:var(--card);color:var(--fg);padding:4px 12px;"
    "text-decoration:none;font-size:13px}.ly-bar a:hover{border-color:var(--ac)}.ly-bar b{color:var(--ac)}"
    ".badge{font-size:10px;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--mut);"
    "padding:0 6px;margin-left:6px;color:var(--dim)}.badge.moved{color:var(--amber);border-color:var(--amber)}"
    ".ly-anim{margin:0 0 18px;border:1px solid var(--mut);background:var(--card);padding:8px 10px;position:relative}"
    ".ly-anim canvas{display:block;width:100%;color:var(--fg);cursor:default}"
    ".ly-anim .ly-ctl{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px;font-size:12px;color:var(--dim)}"
    ".ly-anim button{border:1px solid var(--ac);background:var(--bg);color:var(--ac);padding:3px 14px;cursor:pointer;font:inherit}"
    ".ly-anim button:hover{background:var(--ac);color:var(--bg)}"
    ".ly-anim input[type=range]{flex:1;min-width:140px;accent-color:var(--ac)}"
    ".ly-anim .ly-date{min-width:11em;color:var(--fg)}"
    ".ly-anim .ly-key{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;margin-top:6px}"
    ".ly-anim .ly-key a{color:var(--fg);text-decoration:none}.ly-anim .ly-key a:hover{color:var(--ac)}"
    ".ly-anim .ly-key i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;background:var(--dim)}"
    ".ly-tip{position:absolute;pointer-events:none;z-index:5;max-width:320px;padding:4px 8px;font-size:12px;"
    "border:1px solid var(--ac);background:var(--bg);color:var(--fg);display:none}"
)

SCRIPT = r"""(function(){
var box=document.getElementById('ly-anim');if(!box)return;
var raw=document.getElementById('ly-data');if(!raw)return;
var ld=box.querySelector('.rf-loading');if(ld)ld.remove();
var D;try{D=JSON.parse(raw.textContent)}catch(e){return}
var cv=box.querySelector('canvas'),tip=box.querySelector('.ly-tip');
var btn=box.querySelector('.ly-replay'),rng=box.querySelector('.ly-range'),dateEl=box.querySelector('.ly-date');
if(!cv||!cv.getContext)return;
var ctx=cv.getContext('2d');
var NL=D.layers.length,TAU=Math.PI*2;
var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function hash(str){var h=2166136261;for(var i=0;i<str.length;i++){h^=str.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0)/4294967296}
/* dots: placement is a pure function of the work id */
var dots=D.works.map(function(w,i){
  var a=hash(w.id),b=hash(w.id+'#j'),c=hash(w.id+'#s');
  return {i:i,w:w,th:a*TAU,jit:(b-.5)*8,dir:c<.5?1:-1,spd:.7+.6*c,layer:w.l,rho:0,next:null,flash:0,fly:0};
});
var W=0,H=0,CX=0,CY=0,RMAX=0,dpr=1,RR=[];
function ringR(l){return l<0?RMAX*.93:RR[l]}
function resize(){
  dpr=window.devicePixelRatio||1;W=box.clientWidth-20;if(W<200)W=200;H=Math.round(Math.min(540,Math.max(320,W*.6)));
  cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);cv.style.height=H+'px';
  CX=W/2;CY=H/2;RMAX=Math.min(W,H)/2-8;RR=[];
  for(var k=0;k<NL;k++)RR.push(RMAX*(.12+.66*k/Math.max(1,NL-1)));
  dots.forEach(function(d){d.rho=ringR(d.layer)+d.jit});
  need=true;
}
/* colours: read from the computed style, again whenever the theme changes */
var COL={};
function readColours(){
  var cs=getComputedStyle(document.documentElement);
  function v(n){var x=cs.getPropertyValue(n).trim();return x||'currentColor'}
  COL={fg:v('--fg'),dim:v('--dim'),mut:v('--mut'),amber:v('--amber'),ac:v('--ac'),layer:D.colours.map(v)};
  need=true;
}
var need=true;
function layerCol(l){return l<0?COL.dim:COL.layer[l]}
function pos(d){return {x:CX+Math.cos(d.th)*d.rho,y:CY+Math.sin(d.th)*d.rho}}
function draw(){
  need=false;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
  ctx.lineWidth=1;ctx.font='11px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
  ctx.setLineDash([2,5]);ctx.strokeStyle=COL.dim;ctx.globalAlpha=.35;
  ctx.beginPath();ctx.arc(CX,CY,ringR(-1),0,TAU);ctx.stroke();ctx.setLineDash([]);
  for(var k=0;k<NL;k++){ctx.globalAlpha=.55;ctx.strokeStyle=layerCol(k);ctx.beginPath();ctx.arc(CX,CY,RR[k],0,TAU);ctx.stroke()}
  ctx.globalAlpha=.9;
  for(var k2=0;k2<NL;k2++){ctx.fillStyle=layerCol(k2);ctx.fillText(D.layers[k2]+' '+cnt[k2],CX,CY-RR[k2])}
  ctx.fillStyle=COL.dim;ctx.fillText('unlayered '+cnt[NL],CX,CY-ringR(-1));
  dots.forEach(function(d){
    var p=pos(d),col=layerCol(d.layer);
    ctx.globalAlpha=d.layer<0?.45:.95;
    if(d.fly>0){ctx.globalAlpha=.25;ctx.strokeStyle=COL.ac;ctx.beginPath();
      var back=d.rho+(d.rho-(ringR(d.layer)+d.jit))*.5;
      ctx.moveTo(p.x,p.y);ctx.lineTo(CX+Math.cos(d.th)*back,CY+Math.sin(d.th)*back);ctx.stroke();ctx.globalAlpha=1}
    ctx.fillStyle=col;ctx.beginPath();ctx.arc(p.x,p.y,d===hov?4.5:(d.fly>0?3.4:2.2),0,TAU);ctx.fill();
    if(d.flash>0){ctx.globalAlpha=Math.min(1,d.flash);ctx.strokeStyle=COL.amber;ctx.lineWidth=2;
      ctx.beginPath();ctx.arc(p.x,p.y,4+(1-Math.min(1,d.flash))*14,0,TAU);ctx.stroke();ctx.lineWidth=1}
  });
  ctx.globalAlpha=1;
}
var cnt=[];function recount(){cnt=[];for(var k=0;k<=NL;k++)cnt.push(0);dots.forEach(function(d){cnt[d.layer<0?NL:d.layer]++})}
/* assignment: a dot moves to a layer after an optional delay; a move between rings flashes */
function assign(d,l,delay,isMove){
  if(reduce){d.layer=l;d.rho=ringR(l)+d.jit;need=true;return}
  d.next={l:l,at:performance.now()+(delay||0),mv:isMove};
}
function fire(d,now){
  var n=d.next;d.next=null;var was=d.layer;d.layer=n.l;
  if(n.mv&&was>=0&&was!==n.l)d.flash=1.6;
  d.fly=1;
}
var last=0,hov=null,raf=0,timer=0;
function frame(now){
  raf=0;var dt=Math.min(.1,(now-(last||now))/1000);last=now;
  dots.forEach(function(d){
    if(d.next&&now>=d.next.at)fire(d,now);
    var target=ringR(d.layer)+d.jit;
    d.rho+=(target-d.rho)*Math.min(1,dt*3.2);
    if(Math.abs(target-d.rho)<.4){d.rho=target;d.fly=0}
    d.th+=d.dir*d.spd*.1*Math.sqrt(100/Math.max(60,d.rho))*dt;
    if(d.flash>0)d.flash-=dt*1.1;
  });
  draw();loop();
}
function loop(){if(!raf&&!reduce&&!document.hidden)raf=requestAnimationFrame(frame)}
document.addEventListener('visibilitychange',function(){
  if(document.hidden){if(raf){cancelAnimationFrame(raf);raf=0}last=0}else{last=0;loop()}
});
/* replay: stage 0 is the miner pass (every work without a move event goes to its layer, a moved
   work to the layer the miner gave it), then one stage per day of moves */
var stages=[{d:'miner pass',mv:[]}];
dots.forEach(function(d){
  var w=d.w,first=w.m!==undefined?w.m:w.l;
  if(first>=0)stages[0].mv.push([d.i,first]);
});
D.steps.forEach(function(s){stages.push(s)});
function stateAt(k){
  var st=dots.map(function(){return -1});
  for(var j=0;j<=k&&j<stages.length;j++)stages[j].mv.forEach(function(m){st[m[0]]=m[1]});
  return st;
}
function showLabel(k){
  if(!dateEl)return;var s=stages[k];
  dateEl.textContent=(k===0?'miner pass':s.d)+(k>0?' ('+s.mv.length+' moved)':'');
  if(rng)rng.value=String(k);
}
function setStage(k,animate,stagger){
  var st=stateAt(k),prev=k>0?stateAt(k-1):null;
  dots.forEach(function(d){
    var l=st[d.i];if(l===d.layer&&!d.next)return;
    var mv=animate&&prev!==null&&prev[d.i]!==l;
    assign(d,l,animate?(stagger?hash(d.w.id+'#d')*stagger:0):0,mv);
  });
  recount();showLabel(k);need=true;
}
var playing=false;
function replay(){
  if(!stages.length)return;
  playing=true;if(timer)clearTimeout(timer);
  dots.forEach(function(d){d.next=null;d.layer=-1;d.rho=ringR(-1)+d.jit;d.fly=0;d.flash=0});
  recount();showLabel(0);need=true;
  var k=0,n=stages.length,per=Math.max(350,Math.min(1400,11000/n));
  if(reduce)per=700;
  (function step(){
    setStage(k,true,k===0?2200:per*.6);
    k++;if(k<n)timer=setTimeout(step,k===1?2600:per);else{playing=false;timer=setTimeout(function(){setStage(n-1,false,0);finalise()},per)}
  })();
}
function finalise(){dots.forEach(function(d){if(d.layer!==d.w.l){assign(d,d.w.l,0,false)}});recount();need=true;if(reduce)draw()}
if(btn)btn.addEventListener('click',replay);
if(rng){rng.max=String(Math.max(0,stages.length-1));rng.value=String(stages.length-1);
  rng.addEventListener('input',function(){if(timer)clearTimeout(timer);setStage(parseInt(rng.value,10),false,0);if(reduce)draw()})}
/* pointer: nearest dot gives the tooltip and the work link, a ring gives the layer link */
function hit(ev){
  var r=cv.getBoundingClientRect(),x=ev.clientX-r.left,y=ev.clientY-r.top,best=null,bd=100;
  dots.forEach(function(d){var p=pos(d),dx=p.x-x,dy=p.y-y,q=dx*dx+dy*dy;if(q<bd){bd=q;best=d}});
  var dist=Math.sqrt((x-CX)*(x-CX)+(y-CY)*(y-CY)),ring=-2;
  for(var k=-1;k<NL;k++)if(Math.abs(dist-ringR(k))<7)ring=k;
  return {d:best,ring:ring,x:x,y:y};
}
cv.addEventListener('mousemove',function(ev){
  var h=hit(ev);hov=h.d;
  if(h.d){var lab=h.d.layer<0?'unlayered':D.layers[h.d.layer];
    tip.textContent=h.d.w.t+' ('+lab+')';tip.style.display='block';
    tip.style.left=Math.min(h.x+14,W-200)+'px';tip.style.top=(h.y+22)+'px';cv.style.cursor='pointer'}
  else{tip.style.display='none';cv.style.cursor=h.ring>-2?'pointer':'default'}
  need=true;if(reduce)draw();
});
cv.addEventListener('mouseleave',function(){hov=null;tip.style.display='none';need=true;if(reduce)draw()});
cv.addEventListener('click',function(ev){
  var h=hit(ev);
  if(h.d&&h.d.w.s){var fp=window.factoryPanel;
    if(fp&&ev.button===0&&!ev.ctrlKey&&!ev.metaKey&&!ev.shiftKey&&!ev.altKey)fp.open(h.d.w.s,cv);
    else location.href=D.open+encodeURIComponent(h.d.w.s)}
  else if(h.ring>=0)location.href=D.links[h.ring];
});
/* theme and size */
function onTheme(){readColours();if(reduce)draw()}
new MutationObserver(onTheme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
window.addEventListener('storage',onTheme);
window.addEventListener('resize',function(){resize();if(reduce)draw()});
recount();readColours();resize();
if(!reduce){loop()}else{draw()}
})();"""


# Layer colours as CSS variable names (resolved by the page's theme at draw time).
LAYER_COLOURS: tuple[str, ...] = ("--ac", "--cyan", "--green", "--blue", "--mag", "--amber")
REPLAY_CAP = 120
"""Most replay steps (days with moves) kept in the page; earlier days are merged into the first."""


def replay_steps(
    history: Sequence[tuple[str, str, str, str]],
    index: Mapping[str, int],
    layers: Sequence[str],
    cap: int = REPLAY_CAP,
) -> list[dict[str, Any]]:
    """The ordered `(ts, work_id, layer, who)` history as compact steps `{d: day, mv: [[work index,
    layer index]]}`: one step per day, the last move of a work within a day winning, moves of works
    or layers that are unknown skipped. Over `cap` steps the earliest days merge into one (dated by
    the last of them). Pure."""
    days: dict[str, dict[int, int]] = {}
    for ts, work, layer, _who in history:
        if work not in index or layer not in layers:
            continue
        days.setdefault(ts[:10], {})[index[work]] = list(layers).index(layer)
    ordered = list(days.items())
    if cap > 0 and len(ordered) > cap:
        head = ordered[: len(ordered) - cap + 1]
        merged: dict[int, int] = {}
        for _day, moves in head:
            merged.update(moves)
        ordered = [(head[-1][0], merged), *ordered[len(ordered) - cap + 1 :]]
    return [{"d": d, "mv": [[w, ly] for w, ly in moves.items()]} for d, moves in ordered]


def layers_payload(
    works: Sequence[Mapping[str, Any]],
    layers: Mapping[str, WorkLayer],
    history: Sequence[tuple[str, str, str, str]],
) -> dict[str, Any]:
    """The animation's data: the ring order, one entry per work (`l` its layer index, -1 for the
    outer halo; `m` the miner's layer index, only for a moved work), the replay steps, the count of
    works per ring and the explorer links. Pure."""
    names = list(LAYER_ORDER)
    ordered = sorted(works, key=lambda x: str(x["id"]))
    out: list[dict[str, Any]] = []
    counts = [0] * len(names)
    unlayered = 0
    for w in ordered:
        wl = layers.get(str(w["id"]))
        li = names.index(wl.layer) if wl is not None and wl.layer in names else -1
        entry: dict[str, Any] = {
            "id": str(w["id"]),
            "s": str(w.get("slug", "")),
            "t": str(w.get("title", ""))[:120],
            "l": li,
        }
        if wl is not None and wl.source == "moved":
            entry["m"] = names.index(wl.miner_layer) if wl.miner_layer in names else -1
        out.append(entry)
        if li >= 0:
            counts[li] += 1
        else:
            unlayered += 1
    index = {str(w["id"]): i for i, w in enumerate(ordered)}
    return {
        "layers": names,
        "colours": list(LAYER_COLOURS),
        "works": out,
        "steps": replay_steps(history, index, names),
        "counts": counts,
        "unlayered": unlayered,
        "links": [filter_link(("layer", n)) for n in names],
        "open": "../explorer/index.html#open=",
    }


def render_animation(
    works: Sequence[Mapping[str, Any]],
    layers: Mapping[str, WorkLayer],
    history: Sequence[tuple[str, str, str, str]],
) -> str:
    """The animated rings block: a container, the data as JSON, the controls and the script."""
    if not works:
        return "<div id=ly-anim class=ly-anim><p class=dim>No works in the corpus yet, so there is nothing to draw.</p></div>"
    payload = layers_payload(works, layers, history)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    key = (
        "".join(
            f"<a href='{esc(payload['links'][i])}'><i style='background:var({LAYER_COLOURS[i]})'></i>"
            f"{esc(n)} {payload['counts'][i]}</a>"
            for i, n in enumerate(payload["layers"])
        )
        + f"<span class=dim><i></i>unlayered {payload['unlayered']}</span>"
    )
    return (
        "<div id=ly-anim class=ly-anim><p class='dim rf-loading'>Loading corpus\u2026</p>"
        "<canvas role=img aria-label='Works on concentric layer rings'></canvas><div class=ly-tip></div>"
        "<div class=ly-ctl><button type=button class=ly-replay>Replay</button>"
        "<input type=range class=ly-range min=0 max=0 value=0 aria-label='Replay position'>"
        "<span class=ly-date></span></div>"
        f"<div class=ly-key>{key}</div>"
        f"<script type=application/json id=ly-data>{data}</script>"
        f"<script>{SCRIPT}</script></div>"
    )


def _rank(layer: str) -> tuple[int, str]:
    if layer == PENDING:
        return (2, layer)
    return (0, f"{LAYER_ORDER.index(layer):02d}") if layer in LAYER_ORDER else (1, layer)


def layers_view(
    works: Sequence[Mapping[str, Any]], layers: Mapping[str, WorkLayer]
) -> dict[str, Any]:
    """Groups of works by layer (`groups`: layer, n, works) and the number of works with no layer
    row (`unlayered`)."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unlayered = 0
    for w in sorted(works, key=lambda x: str(x["id"])):
        wl = layers.get(str(w["id"]))
        if wl is None:
            unlayered += 1
            continue
        by[wl.layer if wl.layer is not None else PENDING].append(
            {
                "id": w["id"],
                "slug": w.get("slug", ""),
                "title": w.get("title", ""),
                "year": w.get("year", ""),
                "source": wl.source,
                "miner_layer": wl.miner_layer,
            }
        )
    groups = [
        {"layer": k, "n": len(v), "works": v}
        for k, v in sorted(by.items(), key=lambda kv: _rank(kv[0]))
    ]
    return {"groups": groups, "unlayered": unlayered}


def render_layers(view: Mapping[str, Any]) -> str:
    """The page body for a `layers_view`."""
    groups = view["groups"]
    if not groups:
        return "<p class=dim>No work has a layer yet. The layer miner <code>m-layer</code> sets one per work.</p>"
    bar = "".join(
        f"<a href='#layer-{esc(g['layer'])}'>{esc(g['layer'])} <b>{g['n']}</b></a>" for g in groups
    )
    out = f"<div class=ly-bar>{bar}</div>"
    for g in groups:
        rows = ""
        for w in g["works"]:
            note = ""
            if w["source"] == "moved":
                said = f" (miner said {esc(w['miner_layer'])})" if w["miner_layer"] else ""
                note = f"<span class='badge moved'>moved by the researcher{said}</span>"
            rows += (
                f"<tr><td><a href='../explorer/index.html#open={esc(w['slug'])}'>{esc(str(w['title'])[:110])}</a>"
                f"{note}</td><td>{esc(w['year'])}</td></tr>"
            )
        out += f"<div id='layer-{esc(g['layer'])}'></div>" + section(
            f"{g['layer']} ({g['n']})",
            f"<table><tr><th>work</th><th>year</th></tr>{rows}</table>",
        )
    if view["unlayered"]:
        out += (
            f"<p class=dim>{view['unlayered']} further works in the corpus have no layer row "
            "(they are outside the layer pass's population).</p>"
        )
    return out


def build_layers(project: Project, out: Path) -> None:
    from factory.services.site import page
    from factory.services.site_corpus import corpus_payload
    from factory.services.work_layers import layers_of

    works: list[dict[str, Any]] = corpus_payload(project)["works"]
    try:
        layers = layers_of(project)
    except Exception:  # layers are an aid: a project without them still gets the page
        layers = {}
    slug = esc(project.paths.slug)
    body = "<h1>Layers</h1>"
    body += (
        "<div class=note>The layer of each work: the project's triage into core, benchmark, applied, adjacent, "
        "background and off-topic. It comes from the layer miner <code>m-layer</code>, or from a researcher's move "
        "(shown on the row, with what the miner said). The layer pass is <b>not yet calibrated</b>: treat the "
        "layers as a first triage, not a finding.</div>"
    )
    try:
        history = layer_moves(project)
    except Exception:  # the replay is an aid too
        history = []
    body += render_animation(works, layers, history)
    body += render_layers(layers_view(works, layers))
    body += section(
        "What you can do",
        "<ul class=links>"
        "<li><a href='../lifecycle/index.html'>Lifecycle</a>: filter the stage flow by layer.</li>"
        "<li><a href='../miners/m-layer.html'>The layer miner</a>: its rows, quotes and agreement.</li>"
        "<li><a href='../explorer/index.html'>Explorer</a>: every paper with its rows.</li></ul>"
        f"<p class=dim>Commands: <code>factory --project {slug} mine status</code>.</p>",
    )
    (out / "index.html").write_text(page("Layers", body, REPORT_CSS + CSS), encoding="utf-8")
