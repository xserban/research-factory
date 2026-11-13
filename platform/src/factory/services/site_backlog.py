# ruff: noqa: E501
"""The backlog board product: every idea of `docs/backlog.md` as a board and a dependency tree.

The board reads the backlog document, never edits it. Each entry is parsed (id, title, area, status,
slice, `Depends on`, what, why, rigour notes, open questions). The state of an idea is computed:

- **done**: status `built`, or `accepted` and implemented;
- **specified**: `accepted` in a slice spec, not yet built;
- **ready**: `new` or `triaged`, and every idea it depends on (an `IDEA-nn` in `Depends on`) is done;
- **blocked**: `new` or `triaged` with at least one idea dependency not done;
- **parked**: `parked` or `rejected`.

The page has a board (columns by state, ready ideas ordered by how many ideas they unlock), a
dependency tree (a layered graph, dependencies on the left) and a selection tray that lists what is
selected, what it still needs first, and a brief to copy for an orchestrator. Selection is kept in the
browser only; nothing is written back. The backlog file of the main checkout is the live one: a
worktree reads it through its `.claude/worktrees/` parent, or the file named by `FACTORY_BACKLOG`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from factory.services.context import Project

_HEADER = re.compile(r"^### (IDEA-(\d+)) — (.+)$")
_REF = re.compile(r"IDEA-(\d+)")
_SECTION = re.compile(r"^## (.+?)(?:\s*\((?:added|from)[^)]*\))?\s*$")
_FIELDS = {
    "What": "what",
    "Why": "why",
    "Rigour notes": "rigour",
    "Open questions": "open",
}


def backlog_path() -> Path | None:
    """The live backlog: `FACTORY_BACKLOG`, else `docs/backlog.md` of the main checkout."""
    named = os.environ.get("FACTORY_BACKLOG")
    if named:
        return Path(named) if Path(named).is_file() else None
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "worktrees" and parent.parent.name == ".claude":
            candidate = parent.parent.parent / "docs" / "backlog.md"
            if candidate.is_file():
                return candidate
        candidate = parent / "docs" / "backlog.md"
        if candidate.is_file() and ".claude" not in candidate.parts:
            return candidate
    return None


def backlog_digest() -> str:
    """A short hash of the backlog file, for the product's fingerprint."""
    path = backlog_path()
    if path is None:
        return "none"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def parse_backlog(source: str) -> list[dict[str, Any]]:
    """The entries of a backlog document, in file order, with their ids and dependencies."""
    ideas: list[dict[str, Any]] = []
    area = ""
    current: dict[str, Any] | None = None
    field: str | None = None
    for line in source.splitlines():
        section = _SECTION.match(line)
        if section and not line.startswith("###"):
            area = section.group(1).strip()
            current, field = None, None
            continue
        header = _HEADER.match(line)
        if header:
            current = {
                "id": header.group(1),
                "n": int(header.group(2)),
                "title": header.group(3).strip(),
                "area": area,
                "status_raw": "",
                "status": "new",
                "added": "",
                "slice": "",
                "depends_raw": "",
                "what": "",
                "why": "",
                "rigour": "",
                "open": "",
                "extra": {},
                "more": "",
            }
            ideas.append(current)
            field = None
            continue
        if current is None:
            continue
        if line.startswith("Status:"):
            parts = [p.strip() for p in line.split(" · ")]
            raw = parts[0][len("Status:") :].strip()
            current["status_raw"] = raw
            word = re.match(r"[a-z]+", raw.lower())
            current["status"] = word.group(0) if word else "new"
            for part in parts[1:]:
                if part.startswith("Added:"):
                    current["added"] = part[len("Added:") :].strip()
                elif part.startswith("Slice:"):
                    current["slice"] = part[len("Slice:") :].strip()
                elif part.startswith("Depends on:"):
                    current["depends_raw"] = part[len("Depends on:") :].strip()
            field = None
            continue
        marked = re.match(r"\*\*(What|Why|Rigour notes|Open questions):\*\*\s*(.*)$", line)
        if marked:
            field = _FIELDS[marked.group(1)]
            current[field] = marked.group(2).strip()
            continue
        label = re.match(r"\*\*([^*]+?):\*\*\s*(.*)$", line)
        if label:
            field = "extra:" + label.group(1).strip()
            current["extra"][label.group(1).strip()] = label.group(2).strip()
            continue
        if line.startswith("---"):
            field = None
            continue
        if field and line.strip():
            if field.startswith("extra:"):
                key = field[6:]
                current["extra"][key] += " " + line.strip()
            else:
                current[field] += " " + line.strip()
        elif not line.strip():
            field = None
        elif line.strip():
            current["more"] += line.rstrip() + "\n"  # loose text and tables, kept as written
    return ideas


def area_notes(source: str) -> dict[str, str]:
    """The intro paragraph under each `##` heading of the backlog, by area name."""
    notes: dict[str, str] = {}
    area = ""
    for line in source.splitlines():
        section = _SECTION.match(line)
        if section and not line.startswith("###"):
            area = section.group(1).strip()
            notes[area] = ""
        elif line.startswith("###") or line.startswith("---"):
            area = ""
        elif area and line.strip():
            notes[area] = (notes[area] + " " + line.strip()).strip()
    return {k: v for k, v in notes.items() if v}


def _is_done(idea: dict[str, Any]) -> bool:
    raw = idea["status_raw"].lower()
    return idea["status"] == "built" or (idea["status"] == "accepted" and "implemented" in raw)


def classify(ideas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add `deps`, `unmet`, `unlocks`, `layer` and `state` to every idea (computed, never typed)."""
    by_id = {i["id"]: i for i in ideas}
    for idea in ideas:
        refs = [f"IDEA-{int(n):02d}" for n in _REF.findall(idea["depends_raw"])]
        idea["deps"] = [r for r in dict.fromkeys(refs) if r in by_id and r != idea["id"]]
    children: dict[str, list[str]] = {i["id"]: [] for i in ideas}
    for idea in ideas:
        for dep in idea["deps"]:
            children[dep].append(idea["id"])
    for idea in ideas:
        idea["unmet"] = [d for d in idea["deps"] if not _is_done(by_id[d])]
        if _is_done(idea):
            idea["state"] = "done"
        elif idea["status"] in ("parked", "rejected"):
            idea["state"] = "parked"
        elif idea["status"] == "accepted":
            idea["state"] = "specified"
        elif idea["unmet"]:
            idea["state"] = "blocked"
        else:
            idea["state"] = "ready"

    def below(start: str) -> set[str]:
        seen: set[str] = set()
        stack = list(children[start])
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(children[node])
        return seen

    layers: dict[str, int] = {}

    def layer(node: str, trail: frozenset[str] = frozenset()) -> int:
        if node in layers:
            return layers[node]
        if node in trail:
            return 0
        deps = by_id[node]["deps"]
        value = 1 + max(layer(d, trail | {node}) for d in deps) if deps else 0
        layers[node] = value
        return value

    for idea in ideas:
        idea["unlocks"] = len(
            [n for n in below(idea["id"]) if not _is_done(by_id[n]) and n != idea["id"]]
        )
        idea["layer"] = layer(idea["id"])
        idea["dependents"] = sorted(children[idea["id"]])
    return ideas


_CSS = (
    ".top{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}"
    ".top input{background:var(--lt);color:var(--fg);border:1px solid var(--mut);padding:5px 10px;font:inherit;width:250px}"
    ".views button,.chip,.btn{background:var(--lt);color:var(--light);border:1px solid var(--mut);padding:4px 11px;font:inherit;font-size:12px;cursor:pointer;letter-spacing:.04em}"
    ".views button.on,.chip.on{border-color:var(--ac);color:var(--ac)}"
    ".views button:hover,.chip:hover,.btn:hover{border-color:var(--blue);color:var(--fg)}"
    ".stat{font-family:var(--mono);font-size:12px;color:var(--dim)}.stat b{color:var(--ac)}"
    ".cols{display:grid;grid-template-columns:repeat(5,minmax(210px,1fr));gap:10px;align-items:start;overflow-x:auto}"
    ".col{border:1px solid var(--mut);background:var(--dk)}"
    ".col h3{margin:0;padding:8px 10px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;border-bottom:1px solid var(--mut);display:flex;justify-content:space-between}"
    ".col h3 i{font-style:normal;font-family:var(--mono);color:var(--dim)}"
    ".col p.hint{margin:0;padding:6px 10px;font-size:11px;color:var(--dim);border-bottom:1px solid var(--mut)}"
    ".card{margin:8px;padding:8px 10px;background:var(--lt);border:1px solid var(--mut);border-left:3px solid var(--mut);cursor:pointer;position:relative}"
    ".card:hover{border-color:var(--blue)}.card.sel{box-shadow:0 0 0 1px var(--ac)}"
    ".card .id{font-family:var(--mono);font-size:11px;color:var(--dim);padding-right:26px}"
    ".card .t{font-size:13px;margin:2px 0 5px;color:var(--fg);padding-right:26px}"
    ".card .m{display:flex;flex-wrap:wrap;gap:4px;font-size:10.5px;color:var(--dim)}"
    ".card .m span{border:1px solid var(--mut);padding:0 5px;font-family:var(--mono)}"
    ".card .m .need{color:var(--amber);border-color:var(--amber)}.card .m .unl{color:var(--ac);border-color:var(--ac)}"
    ".card button.add{position:absolute;top:6px;right:6px;width:22px;height:22px;background:none;border:1px solid var(--mut);color:var(--ac);cursor:pointer;font:inherit;line-height:1}"
    ".card button.add:hover{border-color:var(--ac)}.card.sel button.add{background:var(--ac);color:var(--bg)}"
    ".s-ready{border-left-color:var(--ac)}.s-blocked{border-left-color:var(--amber)}.s-specified{border-left-color:var(--cyan)}.s-done{border-left-color:var(--dim);opacity:.7}.s-parked{border-left-color:var(--mut);opacity:.6}"
    "#tree{border:1px solid var(--mut);background:var(--dk);overflow:auto;max-height:70vh}"
    "#tree svg{display:block}#tree .node{cursor:pointer}#tree .node rect{fill:var(--lt);stroke:var(--mut)}"
    "#tree .node text{fill:var(--fg);font-size:11px;font-family:var(--mono)}#tree .node.dim{opacity:.18}#tree .edge.dim{opacity:.06}"
    "#tree .edge{fill:none;stroke:var(--dim);stroke-width:1;opacity:.55}#tree .edge.hot{stroke:var(--ac);opacity:1;stroke-width:1.6}"
    "#tree .node.sel rect{stroke:var(--ac);stroke-width:2}"
    ".legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--dim);margin:6px 0}.legend i{display:inline-block;width:10px;height:10px;margin-right:5px;vertical-align:-1px}"
    ".drawer{position:fixed;right:0;top:0;bottom:0;width:min(520px,94vw);background:var(--dk);border-left:1px solid var(--ac);padding:16px 18px;overflow:auto;transform:translateX(102%);transition:transform .15s;z-index:5}"
    ".drawer.open{transform:none}.drawer h2{margin:4px 0 8px;font-size:17px}.drawer h4{margin:14px 0 3px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}"
    ".drawer pre{white-space:pre-wrap;word-break:break-word;background:var(--lt);border:1px solid var(--mut);padding:8px;font-size:11.5px;margin:0}.drawer p{margin:0;font-size:13px;line-height:1.5;color:var(--light)}.drawer .x{float:right}.drawer a{color:var(--ac);cursor:pointer}"
    ".tray{position:sticky;bottom:0;margin-top:16px;border:1px solid var(--ac);background:var(--dk);padding:10px 12px}"
    ".tray h3{margin:0 0 6px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ac)}"
    ".tray ul{margin:4px 0 8px;padding-left:18px;font-size:12.5px}.tray .need{color:var(--amber)}"
    ".tray .row{display:flex;gap:8px;flex-wrap:wrap}"
    ".legend-note{font-size:12px;color:var(--dim);margin:2px 0 8px;max-width:900px}"
    "[hidden]{display:none!important}"
)

_JS = r"""
const D=JSON.parse(document.getElementById('d').textContent);const I=D.ideas;const B={};I.forEach(i=>B[i.id]=i);
const E=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const COL=[['ready','Ready','No unmet idea dependency. Start here: ordered by how many ideas each one unlocks.'],['blocked','Blocked','Waiting on ideas that are not done yet.'],['specified','Specified','Accepted into a slice spec; not built yet.'],['done','Done','Built (status corrected from the code where I could verify it).'],['parked','Parked','Parked or rejected, with a reason.']];
const COLOR={ready:'var(--ac)',blocked:'var(--amber)',specified:'var(--cyan)',done:'var(--dim)',parked:'var(--mut)'};
let sel=[];try{sel=JSON.parse(localStorage.getItem('rf-backlog-sel')||'[]').filter(x=>B[x]);}catch(e){}
let view='board',area='',q='',open=null;
function save(){try{localStorage.setItem('rf-backlog-sel',JSON.stringify(sel));}catch(e){}}
function match(i){return(!area||i.area===area)&&(!q||(i.id+' '+i.title+' '+i.what+' '+i.area).toLowerCase().includes(q));}
function card(i){const n=i.unmet.length;return '<div class="card s-'+i.state+(sel.includes(i.id)?' sel':'')+'" data-id="'+i.id+'"><button class="add" data-add="'+i.id+'" title="'+(sel.includes(i.id)?'Remove from selection':'Add to selection')+'">'+(sel.includes(i.id)?'✓':'+')+'</button><div class="id">'+i.id+' · '+E(i.area.replace(/ \(.*/,''))+'</div><div class="t">'+E(i.title)+'</div><div class="m">'+(n?'<span class="need">needs '+i.unmet.join(', ')+'</span>':'')+(i.unlocks&&i.state!=='done'?'<span class="unl">unlocks '+i.unlocks+'</span>':'')+(i.slice&&i.slice!=='—'?'<span>'+E(i.slice.slice(0,34))+'</span>':'')+'</div></div>';}
function board(){const el=document.getElementById('board');el.innerHTML=COL.map(([k,t,h])=>{let rows=I.filter(i=>i.state===k&&match(i));if(k==='ready')rows.sort((a,b)=>b.unlocks-a.unlocks||a.n-b.n);return '<div class="col"><h3><span style="color:'+COLOR[k]+'">'+t+'</span><i>'+rows.length+'</i></h3><p class="hint">'+h+'</p>'+rows.map(card).join('')+'</div>';}).join('');}
function tree(){const el=document.getElementById('tree');const nodes=I.filter(i=>(i.deps.length||i.dependents.length)&&match(i));const ids=new Set(nodes.map(n=>n.id));
const L={};nodes.forEach(n=>(L[n.layer]=L[n.layer]||[]).push(n));const cols=Object.keys(L).map(Number).sort((a,b)=>a-b);
const W=220,H=30,GX=70,GY=10;const pos={};let maxy=0;cols.forEach((c,ci)=>{L[c].sort((a,b)=>a.area.localeCompare(b.area)||a.n-b.n).forEach((n,ri)=>{pos[n.id]={x:16+ci*(W+GX),y:16+ri*(H+GY)};maxy=Math.max(maxy,16+ri*(H+GY)+H);});});
let edges='';nodes.forEach(n=>n.deps.filter(d=>ids.has(d)).forEach(d=>{const a=pos[d],b=pos[n.id];const x1=a.x+W,y1=a.y+H/2,x2=b.x,y2=b.y+H/2,mx=(x1+x2)/2;edges+='<path class="edge" data-a="'+d+'" data-b="'+n.id+'" d="M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2+'"/>';}));
let nd='';nodes.forEach(n=>{const p=pos[n.id];nd+='<g class="node'+(sel.includes(n.id)?' sel':'')+'" data-id="'+n.id+'" transform="translate('+p.x+','+p.y+')"><rect width="'+W+'" height="'+H+'"/><rect width="4" height="'+H+'" style="fill:'+COLOR[n.state]+';stroke:none"/><text x="12" y="19">'+n.id.replace('IDEA-','')+' '+E(n.title.length>26?n.title.slice(0,25)+'…':n.title)+'</text></g>';});
el.innerHTML='<svg width="'+(32+cols.length*(W+GX))+'" height="'+(maxy+20)+'">'+edges+nd+'</svg>';
el.querySelectorAll('.node').forEach(g=>{g.onclick=()=>show(g.dataset.id);g.onmouseenter=()=>hot(g.dataset.id);g.onmouseleave=()=>hot(null);});}
function chain(id){const up=new Set(),down=new Set();const u=x=>B[x].deps.forEach(d=>{if(!up.has(d)){up.add(d);u(d);}});const d=x=>B[x].dependents.forEach(c=>{if(!down.has(c)){down.add(c);d(c);}});u(id);d(id);return new Set([id,...up,...down]);}
function hot(id){const el=document.getElementById('tree');const keep=id?chain(id):null;el.querySelectorAll('.node').forEach(g=>g.classList.toggle('dim',!!keep&&!keep.has(g.dataset.id)));el.querySelectorAll('.edge').forEach(p=>{const on=!keep||(keep.has(p.dataset.a)&&keep.has(p.dataset.b));p.classList.toggle('dim',!on);p.classList.toggle('hot',!!keep&&on);});}
function show(id){const i=B[id];open=id;const d=document.getElementById('drawer');const f=(t,v)=>v?'<h4>'+t+'</h4><p>'+E(v)+'</p>':'';
const link=x=>'<a data-go="'+x+'">'+x+'</a>';
d.innerHTML='<button class="btn x" id="close">Close</button><div class="id" style="font-family:var(--mono);color:var(--dim)">'+i.id+' · '+E(i.area)+'</div><h2>'+E(i.title)+'</h2><div class="row"><span class="chip on" style="border-color:'+COLOR[i.state]+';color:'+COLOR[i.state]+'">'+i.state+'</span> <button class="btn" id="addd">'+(sel.includes(i.id)?'Remove from selection':'Add to selection')+'</button></div>'+
f('Status',i.status_raw)+f('Added',i.added)+f('Slice',i.slice)+f('Depends on',i.depends_raw)+
(i.deps.length?'<h4>Ideas it needs'+(i.unmet.length?' (not done: '+i.unmet.join(', ')+')':' (all done)')+'</h4><p>'+i.deps.map(link).join(' · ')+'</p>':'')+
(i.dependents.length?'<h4>Unlocks</h4><p>'+i.dependents.map(link).join(' · ')+'</p>':'')+
f('What',i.what)+f('Why',i.why)+f('Rigour notes',i.rigour)+f('Open questions',i.open)+Object.entries(i.extra).map(([k,v])=>f(k,v)).join('')+(i.more.trim()?'<h4>More</h4><pre>'+E(i.more.trim())+'</pre>':'');
d.classList.add('open');d.querySelector('#close').onclick=()=>{d.classList.remove('open');open=null;};
d.querySelector('#addd').onclick=()=>{toggle(i.id);show(i.id);};d.querySelectorAll('[data-go]').forEach(a=>a.onclick=()=>show(a.dataset.go));}
function toggle(id){const k=sel.indexOf(id);if(k<0)sel.push(id);else sel.splice(k,1);save();draw();}
function needs(){const out=[];const seen=new Set(sel);const add=x=>B[x].deps.forEach(d=>{if(!seen.has(d)&&!(B[d].state==='done')){seen.add(d);out.push(d);add(d);}});sel.forEach(add);return out;}
function order(ids){const set=new Set(ids);const out=[];const seen=new Set();const v=x=>{if(seen.has(x))return;seen.add(x);B[x].deps.filter(d=>set.has(d)).forEach(v);out.push(x);};ids.forEach(v);return out;}
function tray(){const t=document.getElementById('tray');if(!sel.length){t.innerHTML='<h3>Selection</h3><span class="dim">Nothing selected. Use + on a card or in the tree detail to pick what to implement; the brief is built here.</span>';return;}
const nd=needs();const all=order([...sel,...nd]);
t.innerHTML='<h3>Selection · '+sel.length+' idea'+(sel.length>1?'s':'')+'</h3><ul>'+sel.map(x=>'<li>'+x+' '+E(B[x].title)+' <a data-go="'+x+'" style="color:var(--ac);cursor:pointer">detail</a></li>').join('')+'</ul>'+(nd.length?'<div class="need">Not done, and needed first: '+nd.map(x=>x+' '+E(B[x].title)).join('; ')+'. <button class="btn" id="addneeds">Add them</button></div>':'<div class="dim">No unmet dependency among the selection.</div>')+
'<div class="row" style="margin-top:8px"><button class="btn" id="copy">Copy brief</button><button class="btn" id="clear">Clear</button></div>';
t.querySelector('#copy').onclick=async e=>{const txt=brief(all);try{await navigator.clipboard.writeText(txt);e.target.textContent='Copied';}catch(x){window.prompt('Copy the brief',txt);}setTimeout(()=>e.target.textContent='Copy brief',1500);};
t.querySelector('#clear').onclick=()=>{sel=[];save();draw();};const an=t.querySelector('#addneeds');if(an)an.onclick=()=>{nd.forEach(x=>sel.push(x));save();draw();};
t.querySelectorAll('[data-go]').forEach(a=>a.onclick=()=>show(a.dataset.go));}
function brief(ids){return '# Brief for the orchestrator: backlog ideas to build\n\nProject rules (CLAUDE.md): the platform never calls a model; events are append-only; logic in services; TDD for platform/ (tests are paused until the researcher lifts it: mypy and ruff only); one worktree per plan; a plan in docs/plans/ before code; no commits, merges or pushes without the researcher.\n\nBuild in this order (a dependency comes before what needs it):\n\n'+ids.map((x,k)=>{const i=B[x];return (k+1)+'. '+i.id+' — '+i.title+(sel.includes(x)?'':' (needed first)')+'\n   Status: '+i.status_raw+'\n   Depends on: '+(i.depends_raw||'—')+'\n   What: '+i.what+'\n   Why: '+i.why+'\n   Rigour: '+i.rigour+'\n   Open questions: '+i.open+Object.entries(i.extra).map(([k,v])=>'\n   '+k+': '+v).join('')+(i.more.trim()?'\n   More:\n'+i.more.trim().split('\n').map(l=>'     '+l).join('\n'):'')+'\n';}).join('\n')+'\nSource: docs/backlog.md (board built '+D.built+').';}
function draw(){document.getElementById('board').hidden=view!=='board';document.getElementById('treewrap').hidden=view!=='tree';if(view==='board')board();else tree();tray();
document.getElementById('board').querySelectorAll('.card').forEach(c=>c.onclick=e=>{if(e.target.dataset.add)return;show(c.dataset.id);});
document.getElementById('board').querySelectorAll('[data-add]').forEach(b=>b.onclick=e=>{e.stopPropagation();toggle(b.dataset.add);});
const cnt={};I.forEach(i=>cnt[i.state]=(cnt[i.state]||0)+1);document.getElementById('stat').innerHTML='<b>'+(cnt.ready||0)+'</b> ready · '+(cnt.blocked||0)+' blocked · '+(cnt.specified||0)+' specified · '+(cnt.done||0)+' done · '+(cnt.parked||0)+' parked of '+I.length;}
document.querySelectorAll('.views button').forEach(b=>b.onclick=()=>{view=b.dataset.v;document.querySelectorAll('.views button').forEach(x=>x.classList.toggle('on',x===b));draw();});
document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();draw();};
const areas=[...new Set(I.map(i=>i.area))];document.getElementById('areas').innerHTML='<button class="chip on" data-a="">All areas</button>'+areas.map(a=>'<button class="chip" data-a="'+E(a)+'">'+E(a.replace(/ \(.*/,''))+'</button>').join('');
document.querySelectorAll('#areas .chip').forEach(b=>b.onclick=()=>{area=b.dataset.a;document.getElementById('anote').textContent=(D.notes[area]||'');document.querySelectorAll('#areas .chip').forEach(x=>x.classList.toggle('on',x===b));draw();});
if(location.hash==='#tree'){view='tree';document.querySelectorAll('.views button').forEach(x=>x.classList.toggle('on',x.dataset.v==='tree'));}
draw();
"""


def build_backlog(project: Project, out: Path) -> None:
    from datetime import UTC, datetime

    from factory.services.site import page

    path = backlog_path()
    if path is None:
        body = "<h1>Backlog board</h1><p class=dim>The backlog document (docs/backlog.md) was not found. Set FACTORY_BACKLOG to its path and rebuild.</p>"
        (out / "index.html").write_text(page("Backlog board", body, _CSS), encoding="utf-8")
        return
    ideas = classify(parse_backlog(path.read_text(encoding="utf-8")))
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    data = json.dumps(
        {"ideas": ideas, "built": stamp, "notes": area_notes(path.read_text(encoding="utf-8"))},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    body = (
        "<h1>Backlog board</h1>"
        "<p class=legend-note>Every idea of <code>docs/backlog.md</code> (read from "
        f"<code>{path.name}</code> of the main checkout), sorted by what you can start now. "
        "<b>Ready</b> ideas have no unmet dependency and are ordered by how many other ideas they "
        "unlock. Click a card for the full entry; press <b>+</b> to select it. The <b>tray</b> at "
        "the bottom lists what the selection still needs first and copies a brief for an "
        "orchestrator. The <b>tree</b> shows dependencies (what must come first is on the left); "
        "hover a node to light its chain. States are computed from each entry's status and "
        "<code>Depends on</code> line; fix a wrong status in the backlog and rebuild. Selection is "
        "kept in this browser only.</p>"
        "<div class=top><span class=views><button class=on data-v=board>Board</button> "
        "<button data-v=tree>Dependency tree</button></span>"
        "<input id=q placeholder='Filter ideas…'><span class=stat id=stat></span></div>"
        "<div class=top id=areas></div><p class=legend-note id=anote></p>"
        "<div id=board class=cols></div>"
        "<div id=treewrap hidden><div class=legend>"
        "<span><i style='background:var(--ac)'></i>ready</span>"
        "<span><i style='background:var(--amber)'></i>blocked</span>"
        "<span><i style='background:var(--cyan)'></i>specified</span>"
        "<span><i style='background:var(--dim)'></i>done</span>"
        "<span><i style='background:var(--mut)'></i>parked</span>"
        "<span>Only ideas with a recorded idea dependency are drawn; the board has them all.</span></div>"
        "<div id=tree></div></div>"
        "<div class=tray id=tray></div><div class=drawer id=drawer></div>"
        f"<script id=d type='application/json'>{data}</script><script>{_JS}</script>"
    )
    (out / "index.html").write_text(
        page("Backlog board", body, _CSS).replace("max-width:1100px", "max-width:1500px"),
        encoding="utf-8",
    )
