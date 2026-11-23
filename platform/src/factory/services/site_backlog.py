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
    ".bl-top{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px}"
    ".bl-top input{width:260px;max-width:100%}"
    ".bl-stat{font:400 var(--t-xs) var(--f-mono);color:var(--mut)}.bl-stat b{color:var(--fg)}"
    ".bl-areas{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px}"
    ".bl-anote{margin:2px 0 12px}"
    ".bl-cols{display:grid;grid-template-columns:repeat(5,minmax(230px,1fr));gap:var(--gap);align-items:start;overflow-x:auto;padding-bottom:6px}"
    ".bl-col{background:var(--surface);border-radius:var(--r);padding:12px;display:flex;flex-direction:column;gap:8px}"
    ".bl-col h3{margin:0;font:600 var(--t-m)/1.3 var(--f-ui);display:flex;justify-content:space-between;align-items:baseline}"
    ".bl-col h3 i{font:400 var(--t-xs) var(--f-mono);font-style:normal;color:var(--mut)}"
    ".bl-col p.bl-hint{margin:0 0 4px;font-size:var(--t-xs);color:var(--mut)}"
    ".bl-empty{margin:0;padding:10px 0;font-size:var(--t-xs);color:var(--mut)}"
    ".bl-card{position:relative;padding:10px 12px;border-radius:var(--r-s);cursor:pointer;border-left:3px solid var(--line)}"
    ".bl-card:hover{background:var(--line)}"
    ".bl-card.bl-sel{box-shadow:inset 0 0 0 1px var(--acc)}"
    ".bl-id{font:400 var(--t-xs) var(--f-mono);color:var(--dim);padding-right:30px}"
    ".bl-t{font-size:var(--t-s);font-weight:600;margin:2px 0 6px;padding-right:30px;color:var(--fg)}"
    ".bl-m{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:var(--t-xs);color:var(--mut)}"
    ".bl-m .bl-need{color:var(--exc)}.bl-m .bl-unl{color:var(--acc)}"
    ".bl-add{position:absolute;top:6px;right:6px;width:26px;height:26px;border:0;border-radius:var(--r-s);background:var(--surface);color:var(--acc);cursor:pointer;font:600 var(--t-m)/1 var(--f-ui);padding:0}"
    ".bl-add:hover{background:var(--acc-soft)}.bl-sel .bl-add{background:var(--acc);color:var(--acc-ink)}"
    ".bl-s-ready{border-left-color:var(--inc)}.bl-s-blocked{border-left-color:var(--exc)}.bl-s-specified{border-left-color:var(--acc)}.bl-s-done{border-left-color:var(--dim)}.bl-s-parked{border-left-color:var(--dim)}"
    ".bl-s-done .bl-t,.bl-s-parked .bl-t{color:var(--mut);font-weight:400}"
    ".bl-k-ready{color:var(--inc)}.bl-k-blocked{color:var(--exc)}.bl-k-specified{color:var(--acc)}.bl-k-done,.bl-k-parked{color:var(--mut)}"
    ".bl-treebox{background:var(--surface);border-radius:var(--r);overflow:auto;max-height:70vh}"
    ".bl-treebox svg{display:block}.bl-treebox .bl-node{cursor:pointer}.bl-treebox .bl-node rect{fill:var(--raised);stroke:var(--line)}"
    ".bl-treebox .bl-node text{fill:var(--fg);font-size:11px;font-family:var(--f-mono)}"
    ".bl-treebox .bl-node .bl-bar{stroke:none}"
    ".bl-bar-ready{fill:var(--inc)}.bl-bar-blocked{fill:var(--exc)}.bl-bar-specified{fill:var(--acc)}.bl-bar-done,.bl-bar-parked{fill:var(--dim)}"
    ".bl-treebox .bl-node.bl-faded{opacity:.2}.bl-treebox .bl-edge.bl-faded{opacity:.06}"
    ".bl-treebox .bl-edge{fill:none;stroke:var(--dim);stroke-width:1;opacity:.55}"
    ".bl-treebox .bl-edge.bl-hot{stroke:var(--acc);opacity:1;stroke-width:1.6}"
    ".bl-treebox .bl-node.bl-sel rect{stroke:var(--acc);stroke-width:2}"
    ".bl-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--mut);margin:0 0 8px}"
    ".bl-drawer{position:fixed;right:0;top:0;bottom:0;width:min(520px,100vw);background:var(--surface);box-shadow:var(--shadow);padding:22px 26px;overflow:auto;transform:translateX(102%);transition:transform .2s;z-index:50;visibility:hidden}"
    ".bl-drawer.bl-open{transform:none;visibility:visible}"
    ".bl-drawer h2{margin:6px 0 10px;font:400 var(--t-l)/1.25 var(--f-display)}"
    ".bl-drawer h4{margin:16px 0 3px;font:500 var(--t-xs) var(--f-ui);color:var(--mut)}"
    ".bl-drawer pre{white-space:pre-wrap;word-break:break-word;background:var(--raised);border-radius:var(--r-s);padding:10px;font:400 var(--t-xs) var(--f-mono);margin:0}"
    ".bl-drawer p{margin:0;font-size:var(--t-s);line-height:1.55}.bl-drawer .bl-x{float:right}"
    ".bl-drawer a,.bl-tray a{color:var(--acc);cursor:pointer;text-decoration:underline}"
    ".bl-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}"
    ".bl-tray{position:sticky;bottom:0;margin-top:20px;background:var(--raised);border-radius:var(--r);box-shadow:inset 0 0 0 1px var(--acc),var(--shadow);padding:12px 16px;z-index:4}"
    ".bl-tray h3{margin:0 0 6px;font:600 var(--t-m) var(--f-ui)}"
    ".bl-tray ul{margin:4px 0 8px;padding-left:18px;font-size:var(--t-s)}"
    ".bl-tray .bl-need{color:var(--exc);font-size:var(--t-s);margin-bottom:6px}"
    ".bl-muted{color:var(--mut);font-size:var(--t-s)}"
    ".bl-err{padding:20px;background:var(--exc-soft);border-radius:var(--r);color:var(--fg)}"
    ".bl-err b{color:var(--exc)}"
    "[hidden]{display:none!important}"
)

_JS = r"""
const D=JSON.parse(document.getElementById('d').textContent);const I=D.ideas;const B={};I.forEach(i=>B[i.id]=i);
const E=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const COL=[['ready','Ready','No unmet idea dependency. Start here: ordered by how many ideas each one unlocks.'],['blocked','Blocked','Waiting on ideas that are not done yet.'],['specified','Specified','Accepted into a slice spec; not built yet.'],['done','Done','Built (status corrected from the code where I could verify it).'],['parked','Parked','Parked or rejected, with a reason.']];
const GLYPH={ready:'▸',blocked:'⊘',specified:'◇',done:'✓',parked:'‖'};
let sel=[];try{sel=JSON.parse(localStorage.getItem('rf-backlog-sel')||'[]').filter(x=>B[x]);}catch(e){}
let view='board',area='',q='',open=null;
function save(){try{localStorage.setItem('rf-backlog-sel',JSON.stringify(sel));}catch(e){}}
function match(i){return(!area||i.area===area)&&(!q||(i.id+' '+i.title+' '+i.what+' '+i.area).toLowerCase().includes(q));}
function card(i){const n=i.unmet.length;const on=sel.includes(i.id);return '<div class="card bl-card bl-s-'+i.state+(on?' bl-sel':'')+'" data-id="'+i.id+'" tabindex="0" role="button"><button class="bl-add" data-add="'+i.id+'" aria-pressed="'+on+'" aria-label="'+(on?'Remove '+i.id+' from selection':'Add '+i.id+' to selection')+'" title="'+(on?'Remove from selection':'Add to selection')+'">'+(on?'✓':'+')+'</button><div class="bl-id">'+i.id+' · '+E(i.area.replace(/ \(.*/,''))+'</div><div class="bl-t">'+E(i.title)+'</div><div class="bl-m"><span class="bl-k-'+i.state+'">'+GLYPH[i.state]+' '+i.state+'</span>'+(n?'<span class="bl-need">needs '+i.unmet.join(', ')+'</span>':'')+(i.unlocks&&i.state!=='done'?'<span class="bl-unl">unlocks '+i.unlocks+'</span>':'')+(i.slice&&i.slice!=='—'?'<span>'+E(i.slice.slice(0,34))+'</span>':'')+'</div></div>';}
function board(){const el=document.getElementById('board');el.innerHTML=COL.map(([k,t,h])=>{let rows=I.filter(i=>i.state===k&&match(i));if(k==='ready')rows.sort((a,b)=>b.unlocks-a.unlocks||a.n-b.n);return '<section class="bl-col"><h3><span class="bl-k-'+k+'">'+GLYPH[k]+' '+t+'</span><i>'+rows.length+'</i></h3><p class="bl-hint">'+h+'</p>'+(rows.length?rows.map(card).join(''):'<p class="bl-empty">Nothing here'+((area||q)?' for this filter. Clear the filter to see all.':'.')+'</p>')+'</section>';}).join('');}
function tree(){const el=document.getElementById('tree');const nodes=I.filter(i=>(i.deps.length||i.dependents.length)&&match(i));const ids=new Set(nodes.map(n=>n.id));
if(!nodes.length){el.innerHTML='<p class="bl-empty" style="padding:16px">No idea with a recorded dependency matches this filter. Clear the filter, or switch to the board to see every idea.</p>';return;}
const L={};nodes.forEach(n=>(L[n.layer]=L[n.layer]||[]).push(n));const cols=Object.keys(L).map(Number).sort((a,b)=>a-b);
const W=220,H=30,GX=70,GY=10;const pos={};let maxy=0;cols.forEach((c,ci)=>{L[c].sort((a,b)=>a.area.localeCompare(b.area)||a.n-b.n).forEach((n,ri)=>{pos[n.id]={x:16+ci*(W+GX),y:16+ri*(H+GY)};maxy=Math.max(maxy,16+ri*(H+GY)+H);});});
let edges='';nodes.forEach(n=>n.deps.filter(d=>ids.has(d)).forEach(d=>{const a=pos[d],b=pos[n.id];const x1=a.x+W,y1=a.y+H/2,x2=b.x,y2=b.y+H/2,mx=(x1+x2)/2;edges+='<path class="bl-edge" data-a="'+d+'" data-b="'+n.id+'" d="M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2+'"/>';}));
let nd='';nodes.forEach(n=>{const p=pos[n.id];nd+='<g class="bl-node'+(sel.includes(n.id)?' bl-sel':'')+'" data-id="'+n.id+'" transform="translate('+p.x+','+p.y+')" tabindex="0" role="button"><title>'+n.state+': '+E(n.title)+'</title><rect width="'+W+'" height="'+H+'" rx="4"/><rect class="bl-bar bl-bar-'+n.state+'" width="4" height="'+H+'"/><text x="12" y="19">'+GLYPH[n.state]+' '+n.id.replace('IDEA-','')+' '+E(n.title.length>24?n.title.slice(0,23)+'…':n.title)+'</text></g>';});
el.innerHTML='<svg width="'+(32+cols.length*(W+GX))+'" height="'+(maxy+20)+'" role="img" aria-label="Dependency tree of backlog ideas, dependencies on the left">'+edges+nd+'</svg>';
el.querySelectorAll('.bl-node').forEach(g=>{g.onclick=()=>show(g.dataset.id);g.onkeydown=e=>{if(e.key==='Enter')show(g.dataset.id);};g.onmouseenter=()=>hot(g.dataset.id);g.onmouseleave=()=>hot(null);g.onfocus=()=>hot(g.dataset.id);g.onblur=()=>hot(null);});}
function chain(id){const up=new Set(),down=new Set();const u=x=>B[x].deps.forEach(d=>{if(!up.has(d)){up.add(d);u(d);}});const d=x=>B[x].dependents.forEach(c=>{if(!down.has(c)){down.add(c);d(c);}});u(id);d(id);return new Set([id,...up,...down]);}
function hot(id){const el=document.getElementById('tree');const keep=id?chain(id):null;el.querySelectorAll('.bl-node').forEach(g=>g.classList.toggle('bl-faded',!!keep&&!keep.has(g.dataset.id)));el.querySelectorAll('.bl-edge').forEach(p=>{const on=!keep||(keep.has(p.dataset.a)&&keep.has(p.dataset.b));p.classList.toggle('bl-faded',!on);p.classList.toggle('bl-hot',!!keep&&on);});}
function closeDrawer(){const d=document.getElementById('drawer');d.classList.remove('bl-open');open=null;}
function show(id){const i=B[id];open=id;const d=document.getElementById('drawer');const f=(t,v)=>v?'<h4>'+t+'</h4><p>'+E(v)+'</p>':'';
const link=x=>'<a data-go="'+x+'">'+x+'</a>';
d.innerHTML='<button class="btn bl-x" id="close">Close</button><div class="bl-id">'+i.id+' · '+E(i.area)+'</div><h2>'+E(i.title)+'</h2><div class="bl-row"><span class="bl-k-'+i.state+'">'+GLYPH[i.state]+' '+i.state+'</span> <button class="btn" id="addd">'+(sel.includes(i.id)?'Remove from selection':'Add to selection')+'</button></div>'+
f('Status',i.status_raw)+f('Added',i.added)+f('Slice',i.slice)+f('Depends on',i.depends_raw)+
(i.deps.length?'<h4>Ideas it needs'+(i.unmet.length?' (not done: '+i.unmet.join(', ')+')':' (all done)')+'</h4><p>'+i.deps.map(link).join(' · ')+'</p>':'')+
(i.dependents.length?'<h4>Unlocks</h4><p>'+i.dependents.map(link).join(' · ')+'</p>':'')+
f('What',i.what)+f('Why',i.why)+f('Rigour notes',i.rigour)+f('Open questions',i.open)+Object.entries(i.extra).map(([k,v])=>f(k,v)).join('')+(i.more.trim()?'<h4>More</h4><pre>'+E(i.more.trim())+'</pre>':'');
d.classList.add('bl-open');d.querySelector('#close').onclick=closeDrawer;d.querySelector('#close').focus();
d.querySelector('#addd').onclick=()=>{toggle(i.id);show(i.id);};d.querySelectorAll('[data-go]').forEach(a=>a.onclick=()=>show(a.dataset.go));}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&open)closeDrawer();});
function toggle(id){const k=sel.indexOf(id);if(k<0)sel.push(id);else sel.splice(k,1);save();draw();}
function needs(){const out=[];const seen=new Set(sel);const add=x=>B[x].deps.forEach(d=>{if(!seen.has(d)&&!(B[d].state==='done')){seen.add(d);out.push(d);add(d);}});sel.forEach(add);return out;}
function order(ids){const set=new Set(ids);const out=[];const seen=new Set();const v=x=>{if(seen.has(x))return;seen.add(x);B[x].deps.filter(d=>set.has(d)).forEach(v);out.push(x);};ids.forEach(v);return out;}
function tray(){const t=document.getElementById('tray');if(!sel.length){t.innerHTML='<h3>Selection</h3><span class="bl-muted">Nothing selected. Use + on a card or in the detail panel to pick what to implement; the brief is built here.</span>';return;}
const nd=needs();const all=order([...sel,...nd]);
t.innerHTML='<h3>Selection · '+sel.length+' idea'+(sel.length>1?'s':'')+'</h3><ul>'+sel.map(x=>'<li>'+x+' '+E(B[x].title)+' <a data-go="'+x+'" tabindex="0">detail</a></li>').join('')+'</ul>'+(nd.length?'<div class="bl-need">⊘ Not done, and needed first: '+nd.map(x=>x+' '+E(B[x].title)).join('; ')+'. <button class="btn" id="addneeds">Add them</button></div>':'<div class="bl-muted">✓ No unmet dependency among the selection.</div>')+
'<div class="bl-row" style="margin-top:8px"><button class="btn primary" id="copy">Copy brief</button><button class="btn" id="clear">Clear</button></div>';
t.querySelector('#copy').onclick=async e=>{const txt=brief(all);try{await navigator.clipboard.writeText(txt);e.target.textContent='Copied';}catch(x){window.prompt('Copy the brief',txt);}setTimeout(()=>e.target.textContent='Copy brief',1500);};
t.querySelector('#clear').onclick=()=>{sel=[];save();draw();};const an=t.querySelector('#addneeds');if(an)an.onclick=()=>{nd.forEach(x=>sel.push(x));save();draw();};
t.querySelectorAll('[data-go]').forEach(a=>{a.onclick=()=>show(a.dataset.go);a.onkeydown=e=>{if(e.key==='Enter')show(a.dataset.go);};});}
function brief(ids){return '# Brief for the orchestrator: backlog ideas to build\n\nProject rules (CLAUDE.md): the platform never calls a model; events are append-only; logic in services; TDD for platform/ (tests are paused until the researcher lifts it: mypy and ruff only); one worktree per plan; a plan in docs/plans/ before code; no commits, merges or pushes without the researcher.\n\nBuild in this order (a dependency comes before what needs it):\n\n'+ids.map((x,k)=>{const i=B[x];return (k+1)+'. '+i.id+' — '+i.title+(sel.includes(x)?'':' (needed first)')+'\n   Status: '+i.status_raw+'\n   Depends on: '+(i.depends_raw||'—')+'\n   What: '+i.what+'\n   Why: '+i.why+'\n   Rigour: '+i.rigour+'\n   Open questions: '+i.open+Object.entries(i.extra).map(([k,v])=>'\n   '+k+': '+v).join('')+(i.more.trim()?'\n   More:\n'+i.more.trim().split('\n').map(l=>'     '+l).join('\n'):'')+'\n';}).join('\n')+'\nSource: docs/backlog.md (board built '+D.built+').';}
function setView(v){view=v;document.querySelectorAll('.bl-views button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.v===v)));}
function draw(){document.getElementById('board').hidden=view!=='board';document.getElementById('treewrap').hidden=view!=='tree';if(view==='board')board();else tree();tray();
document.getElementById('board').querySelectorAll('.bl-card').forEach(c=>{c.onclick=e=>{if(e.target.dataset.add)return;show(c.dataset.id);};c.onkeydown=e=>{if(e.key==='Enter'&&e.target===c)show(c.dataset.id);};});
document.getElementById('board').querySelectorAll('[data-add]').forEach(b=>b.onclick=e=>{e.stopPropagation();toggle(b.dataset.add);});
const cnt={};I.forEach(i=>cnt[i.state]=(cnt[i.state]||0)+1);document.getElementById('stat').innerHTML='<b>'+(cnt.ready||0)+'</b> ready · '+(cnt.blocked||0)+' blocked · '+(cnt.specified||0)+' specified · '+(cnt.done||0)+' done · '+(cnt.parked||0)+' parked of '+I.length;}
document.querySelectorAll('.bl-views button').forEach(b=>b.onclick=()=>{setView(b.dataset.v);draw();});
document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();draw();};
const areas=[...new Set(I.map(i=>i.area))];document.getElementById('areas').innerHTML='<button class="chip" aria-pressed="true" data-a="">All areas</button>'+areas.map(a=>'<button class="chip" aria-pressed="false" data-a="'+E(a)+'">'+E(a.replace(/ \(.*/,''))+'</button>').join('');
document.querySelectorAll('#areas .chip').forEach(b=>b.onclick=()=>{area=b.dataset.a;document.getElementById('anote').textContent=(D.notes[area]||'');document.querySelectorAll('#areas .chip').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));draw();});
if(location.hash==='#tree')setView('tree');
draw();
"""


def render_backlog() -> str:
    """The backlog board page in the hub v2 kit: read from docs/backlog.md at the call, written nowhere."""
    from datetime import UTC, datetime

    from factory.services.site_kit_page import kit_page

    head = (
        "<header class=mh-head><h1>Backlog board</h1>"
        "<p>Every idea of the backlog document, sorted by what you can start now.</p></header>"
    )
    path = backlog_path()
    if path is None:
        body = (
            head + "<div class=bl-err role=alert><b>The backlog document was not found.</b> "
            "docs/backlog.md could not be located from this checkout. Set the environment "
            "variable <code>FACTORY_BACKLOG</code> to its path and reload this page.</div>"
        )
        return kit_page("Backlog board", body, "backlog", css=_CSS)
    source = path.read_text(encoding="utf-8")
    ideas = classify(parse_backlog(source))
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    data = json.dumps(
        {"ideas": ideas, "built": stamp, "notes": area_notes(source)},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    if not ideas:
        body = (
            head + "<div class=bl-err role=alert><b>No idea could be read.</b> "
            f"<code>{path.name}</code> has no <code>### IDEA-nn — title</code> entries. "
            "Check the file format against the template in the document and reload.</div>"
        )
        return kit_page("Backlog board", body, "backlog", css=_CSS)
    body = (
        head + "<p class='note bl-anote'>Read from "
        f"<code>{path.name}</code> of the main checkout. <b>Ready</b> ideas have no unmet "
        "dependency and are ordered by how many other ideas they unlock. Click a card for the "
        "full entry; press <b>+</b> to select it. The tray at the bottom lists what the selection "
        "still needs first and copies a brief for an orchestrator. States are computed from each "
        "entry's status and <code>Depends on</code> line; fix a wrong status in the backlog and "
        "reload. Selection is kept in this browser only.</p>"
        "<div class=bl-top><span class='seg bl-views' role=group aria-label='View'>"
        "<button aria-pressed=true data-v=board>Board</button>"
        "<button aria-pressed=false data-v=tree>Dependency tree</button></span>"
        "<input id=q type=search placeholder='Filter ideas' aria-label='Filter ideas'>"
        "<span class=bl-stat id=stat></span></div>"
        "<div class=bl-areas id=areas></div><p class='note bl-anote' id=anote></p>"
        "<div id=board class=bl-cols></div>"
        "<div id=treewrap hidden><div class=bl-legend>"
        "<span class=bl-k-ready>▸ ready</span>"
        "<span class=bl-k-blocked>⊘ blocked</span>"
        "<span class=bl-k-specified>◇ specified</span>"
        "<span class=bl-k-done>✓ done</span>"
        "<span class=bl-k-parked>‖ parked</span>"
        "<span>Only ideas with a recorded idea dependency are drawn; the board has them all.</span></div>"
        "<div id=tree class=bl-treebox></div></div>"
        "<div class=bl-tray id=tray aria-live=polite></div>"
        "<aside class=bl-drawer id=drawer aria-label='Idea detail'></aside>"
        f"<script id=d type='application/json'>{data}</script>"
    )
    return kit_page("Backlog board", body, "backlog", css=_CSS, script=_JS)
