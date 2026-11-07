# ruff: noqa: E501
"""The dashboard page: one HTML string with inline CSS and JS, no external resource (slice 8, I1).

`render_page(state)` returns it with the state embedded (the static export); with None the page
polls `/api/state` every five seconds. The palette is Omarchy Hackerman, dark only.
"""

from __future__ import annotations

import json

from pydantic import JsonValue

POLL_MARKER = "/*STATE*/null"

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0B0C16;--dk:#080910;--lt:#151828;--sel:#1f253a;--mut:#2d3450;--fg:#ddf7ff;--dim:#6a6e95;--light:#b5c5db;
--ac:#82FB9C;--green:#4fe88f;--cyan:#7cf8f7;--blue:#829dd4;--mag:#86a7df;--brown:#287b51;--bright:#9cf7c2}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-monospace,"JetBrains Mono","Fira Code",SFMono-Regular,Menlo,Consolas,monospace}
header{background:var(--dk);border-bottom:1px solid var(--mut);padding:8px 16px;position:sticky;top:0;z-index:2}
main{max-width:1100px;margin:0 auto;padding:0 16px 48px}
h1{font-size:1.1rem;margin:0;color:var(--ac)}h2{font-size:1.05rem;margin:20px 0 8px;color:var(--bright)}h3{font-size:.95rem;margin:14px 0 6px;color:var(--cyan)}
.dim{color:var(--dim);font-size:.85rem}
nav{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 0}
button,select,input{font:inherit;color:var(--fg);background:var(--lt);border:1px solid var(--mut);border-radius:4px;padding:4px 10px}
button{cursor:pointer}button:hover{background:var(--sel)}button.on{background:var(--sel);color:var(--ac);border-color:var(--ac)}
.card{background:var(--lt);border:1px solid var(--mut);border-radius:6px;padding:8px 12px;margin:8px 0}
.card.hl{outline:2px solid var(--ac)}.card.sup{opacity:.55}
.badge{display:inline-block;border-radius:10px;padding:0 8px;font-size:.75rem;border:1px solid currentColor;white-space:nowrap}
.validated{color:var(--ac)}.added{color:var(--cyan)}.proposed{color:var(--blue)}
.rejected{color:var(--dim);text-decoration:line-through}
.rejected-text{color:var(--dim);text-decoration:line-through}
.selected{color:var(--green)}.open{color:var(--blue)}.superseded{color:var(--dim)}
.major{color:var(--ac)}.minor{color:var(--cyan)}.ok{color:var(--green)}.warn{color:var(--cyan)}
table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{border:1px solid var(--mut);padding:3px 8px;text-align:left;vertical-align:top}
th{background:var(--dk);color:var(--light)}
.scroll{overflow-x:auto}
a.j{color:var(--cyan);cursor:pointer;text-decoration:underline}
summary{cursor:pointer}ul{padding-left:20px;margin:4px 0}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}
code,.q{overflow-wrap:anywhere;font-size:.8rem}
.q{background:var(--dk);padding:4px 6px;border-radius:4px;display:block;margin:4px 0;color:var(--light)}
.item{margin:4px 0;padding:4px 0;border-top:1px dashed var(--mut)}
.kvs{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:4px 0}.kvs dt{color:var(--dim)}.kvs dd{margin:0;overflow-wrap:anywhere}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:8px 0}
.tile{background:var(--lt);border:1px solid var(--mut);border-radius:6px;padding:6px 10px}.tile b{display:block;font-size:1.25rem;color:var(--ac)}
@media (max-width:600px){.kvs{grid-template-columns:1fr}main{padding:0 10px 48px}}
</style></head><body>
<header><h1>Factory dashboard <span class="dim" id="slug"></span></h1>
<div class="dim"><span id="fresh">loading</span> <span id="last"></span></div>
<nav id="tabs"></nav></header>
<main id="main"></main>
<script>
const STATIC=/*STATE*/null;
let D=STATIC||{decisions:[],sections:[],levels:[],meta:{}};
const ui={tab:'protocol',sec:null,open:new Set(),flt:{level:'',status:'',q:''}};
let lastJson='';
const $=s=>document.querySelector(s);
function h(tag,attrs,...kids){const e=document.createElement(tag);
 for(const k in(attrs||{})){const v=attrs[k];if(k==='class')e.className=v;else if(k.startsWith('on'))e.addEventListener(k.slice(2),v);else if(v!==null&&v!==undefined&&v!==false)e.setAttribute(k,v===true?'':v);}
 for(const c of kids.flat(2)){if(c===null||c===undefined||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)));}return e;}
const fmt=t=>t?String(t).replace('T',' ').replace(/\.\d+(Z|[+-]\d\d:\d\d)?$/,'$1'):'';
const short=id=>String(id||'').replace(/^dec_/,'').slice(-8);
const E=x=>x===null||x===undefined?'':x;
function badge(s){return h('span',{class:'badge '+s},s);}
function det(id,cls,summary,...body){
 const d=h('details',{class:cls,id:id},summary,body);if(ui.open.has(id))d.open=true;
 d.addEventListener('toggle',()=>{if(d.open)ui.open.add(id);else ui.open.delete(id);});return d;}
function kv(o){const dl=h('dl',{class:'kvs'});for(const k in o){const v=o[k];if(v===null||v===undefined)continue;
 dl.append(h('dt',null,k.replace(/_/g,' ')),h('dd',null,typeof v==='object'?JSON.stringify(v):String(v)));}return dl;}
function table(head,rows){return h('div',{class:'scroll'},h('table',null,h('tr',null,head.map(x=>h('th',null,x))),rows.map(r=>h('tr',null,r.map(c=>h('td',null,c))))));}
function tiles(o){return h('div',{class:'tiles'},Object.keys(o).map(k=>h('div',{class:'tile'},h('b',null,E(o[k])===''?'-':String(o[k])),k)));}
const decById=()=>{const m={};(D.decisions||[]).forEach(d=>m[d.decision_id]=d);return m;};
function jump(id){ui.tab='decisions';ui.flt={level:'',status:'',q:''};ui.open.add('dec-'+id);render();
 const el=document.getElementById('dec-'+id);if(el){el.scrollIntoView({block:'center'});el.classList.add('hl');setTimeout(()=>el.classList.remove('hl'),2500);}}
function grounds(gs,byId){return gs.map((g,i)=>{const m=String(g).match(/dec_[0-9A-Z]+/);return h('span',null,i?', ':'',m&&byId[m[0]]?h('a',{class:'j',onclick:()=>jump(m[0])},g):h('span',{class:'badge proposed'},g));});}
function decCard(d,byId){
 const sm=h('summary',null,h('b',null,d.subject),' ',h('span',{class:'dim'},d.level+' / '+short(d.decision_id)+' / '+fmt(d.suggested_at)+' '),badge(d.state));
 const body=[h('p',null,d.explanation)];
 if(d.supersedes)body.push(h('p',{class:'dim'},'Supersedes ',byId[d.supersedes]?h('a',{class:'j',onclick:()=>jump(d.supersedes)},byId[d.supersedes].subject+' ('+short(d.supersedes)+')'):d.supersedes));
 if(d.superseded_by)body.push(h('p',{class:'dim'},'Superseded by ',byId[d.superseded_by]?h('a',{class:'j',onclick:()=>jump(d.superseded_by)},byId[d.superseded_by].subject+' ('+short(d.superseded_by)+')'):d.superseded_by));
 (d.items||[]).forEach(i=>body.push(h('div',{class:'item'},badge(i.status),' ',h('b',null,i.item_id),i.recommended?h('span',{class:'dim'},' (recommended)'):'',' ',
  h('span',{class:i.status==='rejected'?'rejected-text':''},i.text),i.grounds&&i.grounds.length?h('div',{class:'dim'},'Grounds: ',grounds(i.grounds,byId)):'')));
 const s=d.selection;
 if(s){if(s.note)body.push(h('p',null,h('b',null,'Note: '),s.note));
  body.push(h('div',{class:'dim'},'Selected by '+s.actor+' via '+s.channel+' at '+fmt(s.ts)+(s.reconstructed?' (reconstructed)':'')));}
 body.push(h('div',{class:'dim'},'Suggested by '+d.actor+' at '+fmt(d.suggested_at)+'. '+d.decision_id));
 return det('dec-'+d.decision_id,'card'+(d.state==='superseded'?' sup':''),sm,body);}
function list(l,f){return h('ul',null,(l||[]).map(x=>h('li',null,x.id?h('b',null,x.id+' '):'',x.serves?h('span',{class:'dim'},'('+x.serves+') '):'',f?f(x):(x.text||x.name))));}
function secView(key){const P=D.protocol||{},sp=P.spec||{},Q=(D.question||{}).spec,out=[];
 if(key==='question'&&Q){out.push(h('h3',null,'Primary question'),h('p',null,Q.primary_question));
  if(Q.objectives)out.push(h('p',{class:'dim'},Q.objectives));
  out.push(h('h3',null,'Slots ('+Q.scheme+')'),table(['Slot','Value','Open'],(Q.slots||[]).map(s=>[s.name,s.value,s.open?'open':''])),
   h('h3',null,'Sub-questions'),list(Q.sub_questions),h('h3',null,'Non-goals'),list(Q.non_goals));}
 if(key==='criteria')out.push(h('h3',null,'Criteria'),table(['Id','Parent','Applies at','Statement','Rule'],(sp.criteria||[]).map(c=>[h('b',null,c.id),c.parent,c.applies_at,c.statement,c.rule])));
 if(key==='sources'){out.push(h('h3',null,'Sources'),h('ul',null,(sp.sources||[]).map(s=>h('li',null,h('b',null,s.name),s.included===false?' (excluded)':'',': ',s.why))));
  out.push(h('h3',null,'Queries'),(sp.queries||[]).map(q=>h('div',{class:'card'},h('b',null,q.source+' / '+q.kind),h('code',{class:'q'},q.text),q.filters&&Object.keys(q.filters).length?h('div',{class:'dim'},'Filters: '+JSON.stringify(q.filters)):'')));
  out.push(h('h3',null,'Limits'),h('ul',null,(sp.limits||[]).map(l=>h('li',null,l.field+' = '+l.value+' ('+l.why+')'))));}
 if(key==='screening'){const s=sp.screening||{};out.push(h('h3',null,'Title and abstract'),kv(s));
  const f=sp.full_text_screening;if(f)out.push(h('h3',null,'Full text'),kv(f));}
 if(key==='extraction'&&sp.extraction_schema)out.push(h('h3',null,'Extraction schema'),kv(sp.extraction_schema));
 if(key==='snowball'&&sp.snowball_plan)out.push(h('h3',null,'Snowball plan'),kv(sp.snowball_plan));
 return out;}
function renderProtocol(m){const P=D.protocol||{};m.append(h('h2',null,'Current protocol'));
 if(!P.protocol_id){m.append(h('p',{class:'dim'},'No protocol recorded.'));}
 else m.append(h('p',{class:'dim'},P.protocol_id+' / status '+P.status+' / PRESS '+P.press+' / '+(P.amendments||[]).length+' amendments'));
 const decs=D.decisions||[],byId=decById();
 const secs=(D.sections||[]).map(x=>[x[0],x[1]]);
 [...new Set(decs.map(d=>d.section).filter(s=>s.startsWith('other:')))].forEach(o=>secs.push([o,'Other ('+o.slice(6)+')']));
 m.append(h('div',{class:'row'},secs.map(([k,t])=>h('button',{class:ui.sec===k?'on':'',onclick:()=>{ui.sec=ui.sec===k?null:k;render();}},t+' ('+decs.filter(d=>d.section===k).length+')'))));
 if(ui.sec&&secs.find(s=>s[0]===ui.sec)){m.append(h('h2',null,secs.find(s=>s[0]===ui.sec)[1]),...secView(ui.sec),h('h3',null,'Decisions behind this section'));
  const L=decs.filter(d=>d.section===ui.sec);if(!L.length)m.append(h('p',{class:'dim'},'None recorded.'));L.forEach(d=>m.append(decCard(d,byId)));}
 else m.append(h('p',{class:'dim'},'Select a section to see its content and the decisions behind it.'));}
function statuses(d){return new Set((d.items||[]).map(i=>i.status));}
function renderDecisions(m){const decs=D.decisions||[],byId=decById();
 const lv=h('select',{onchange:e=>{ui.flt.level=e.target.value;render();}},h('option',{value:''},'All levels'),(D.levels||[]).map(l=>h('option',{value:l,selected:ui.flt.level===l},l)));
 const st=h('select',{onchange:e=>{ui.flt.status=e.target.value;render();}},h('option',{value:''},'All statuses'),['validated','rejected','added','proposed','open','selected','superseded'].map(l=>h('option',{value:l,selected:ui.flt.status===l},l)));
 const q=h('input',{type:'search',id:'q',placeholder:'Search text',value:ui.flt.q,oninput:e=>{ui.flt.q=e.target.value;draw();}});
 m.append(h('h2',null,'Decisions timeline'),h('div',{class:'row'},lv,st,q));const box=h('div');m.append(box);
 function draw(){const n=ui.flt.q.toLowerCase();
  const L=decs.filter(d=>(!ui.flt.level||d.level===ui.flt.level)&&(!ui.flt.status||d.state===ui.flt.status||statuses(d).has(ui.flt.status))&&
   (!n||(d.explanation||'').toLowerCase().includes(n)||d.subject.toLowerCase().includes(n)||(d.items||[]).some(i=>i.text.toLowerCase().includes(n))));
  box.replaceChildren(h('p',{class:'dim'},L.length+' of '+decs.length+' decisions'));
  (D.levels||[]).forEach(l=>{const g=L.filter(d=>d.level===l);if(!g.length)return;box.append(h('h3',null,l+' ('+g.length+')'));g.forEach(d=>box.append(decCard(d,byId)));});}
 draw();}
function renderPress(m){const R=D.press||[];m.append(h('h2',null,'PRESS reviews ('+R.length+')'));
 if(!R.length)m.append(h('p',{class:'dim'},'None recorded.'));
 R.forEach(r=>m.append(det('prs-'+r.review_id,'card',h('summary',null,h('b',null,r.review_id),' ',h('span',{class:'dim'},'on '+r.protocol_id+' / '+r.findings.length+' findings / '+(r.confirmed?'confirmed':'not confirmed'))),
  r.findings.length?table(['#','Severity','Element','Finding','Response'],r.findings.map((f,i)=>[i+1,h('span',{class:'badge '+f.severity},f.severity),f.element,f.finding,r.responses[i]||''])):h('p',null,'No findings.'))));}
function renderProbes(m){const R=D.probes||[];m.append(h('h2',null,'Probe rounds ('+R.length+')'));
 if(!R.length)m.append(h('p',{class:'dim'},'None recorded.'));
 R.forEach(p=>m.append(det('prb-'+p.probe_id,'card',h('summary',null,h('b',null,'Round '+p.round),' ',h('span',{class:'dim'},p.probe_id+' / '+p.queries.length+' queries')),
  table(['Source','Reported','Dev. retrieved / tested','Negatives retrieved','Query'],p.queries.map(q=>[q.source,q.failed?h('span',{class:'badge rejected'},'failed: '+E(q.reason)):E(q.reported_count),q.development_retrieved+' / '+q.development_tested,q.failed?'':q.negatives_retrieved,h('code',null,q.text)])))));}
function renderSearch(m){const S=D.search||{},X=D.dedup||{};m.append(h('h2',null,'Search and deduplication'));
 const id=S.identification||{};const sum=o=>Object.values(o||{}).reduce((a,b)=>a+b,0);
 m.append(tiles({'queries run':(S.rows||[]).length,'runs complete':S.runs_complete,'runs partial':S.runs_partial,'records identified':sum(id.databases)+sum(id.other),'duplicates removed':id.duplicates_removed,'merges active':X.active,'merges reverted':X.reverted}));
 m.append(h('h3',null,'Per source'),table(['Source','Queries','Records retrieved'],Object.keys(S.per_source||{}).map(k=>[k,S.per_source[k].queries,S.per_source[k].retrieved])));
 m.append(h('h3',null,'PRISMA identification'),kv({databases:id.databases,other:id.other,duplicates_removed:id.duplicates_removed}));
 m.append(h('h3',null,'Queries'),table(['Source','Purpose','Query','Runs','Reported','Retrieved'],(S.rows||[]).map(r=>[r.source,r.purpose,h('code',null,r.text),(r.runs||[]).map(x=>x.status).join(', '),E(r.reported),r.retrieved])));
 m.append(h('h3',null,'Merges by rule'),kv(X.by_rule||{}));}
function renderScreening(m){const S=D.screening||{};m.append(h('h2',null,'Screening'));const R=S.ranking;
 m.append(R?kv({ranking:R.ranking_id,model:R.model_id,weights_hash:R.weights_hash,works_ranked:R.count}):h('p',{class:'dim'},'No ranking computed.'));
 const P=S.passes||{};m.append(h('h3',null,'Title and abstract passes'),table(['Pass','Queued','Decided','Remaining'],Object.keys(P).map(k=>[k.toUpperCase(),E(P[k].queued),P[k].decided,E(P[k].remaining)])));
 m.append(tiles({'records left (pass A)':S.records_left,'stale decisions':S.stale_decisions}));
 m.append(h('h3',null,'Stop rules'),(S.stops||[]).length?table(['Rule','Run','Stopped','Not screened'],S.stops.map(s=>[s.rule+(s.below_score?' (<'+s.below_score+')':''),s.progress,s.stopped?h('span',{class:'warn'},'stopped'):'running',s.not_screened])):h('p',{class:'dim'},'No stop rule in force.'));
 const C=S.calibration||{};m.append(h('h3',null,'Calibration'),kv({drawn:C.drawn,labelled:C.labelled,required:C.required,passed:C.passed}));
 if(S.full_text_passes){const F=S.full_text_passes;m.append(h('h3',null,'Full-text passes'),table(['Pass','Queued','Decided','Remaining'],Object.keys(F).map(k=>[k.toUpperCase(),E(F[k].queued),F[k].decided,E(F[k].remaining)])));}
 m.append(h('h3',null,'Checks'));if(!(S.checks||[]).length)m.append(h('p',{class:'dim'},'No check drawn.'));
 (S.checks||[]).forEach(c=>m.append(det('chk-'+c.draw_id,'card',h('summary',null,h('b',null,c.kind+(c.name?' '+c.name:'')),' ',h('span',{class:'dim'},c.draw_id+' / '+c.labelled+' of '+c.drawn+' labelled / '+(c.current?'current':'outdated')+(c.agreement!==null&&c.agreement!==undefined?' / agreement '+c.agreement:''))),
  c.agreement_note?h('p',{class:'dim'},c.agreement_note):'',c.bands.length?table(['Band','Drawn','Labelled','Compared','Agreed','Agreement','Would add includes','Would add excludes','Undecided'],c.bands.map(b=>[b.band,b.drawn,b.labelled,b.compared,b.agreed,E(b.agreement),b.would_add_includes,b.would_add_excludes,b.undecided])):'',h('div',{class:'dim'},c.disagreements+' disagreements'))));}
function renderExtraction(m){const X=D.extraction||{};m.append(h('h2',null,'Extraction'));
 m.append(tiles({units:X.units,papers:X.papers,rows:X.rows}));m.append(h('h3',null,'Units by state'),kv(X.by_state||{}));
 const A=X.agreement||{};m.append(h('h3',null,'Agreement'),A.error?h('p',{class:'dim'},A.error):kv({dual_works:A.dual_works,rows_aligned:A.rows_aligned,overall:A.overall,unresolved:A.unresolved,resolved:A.resolved,single_extraction:A.single_extraction}));
 if(A.rates&&A.rates.length)m.append(table(['Group','Compared','Agreed','Rate'],A.rates.map(r=>[r.group,r.compared,r.agreed,E(r.rate)])));
 m.append(h('h3',null,'Audit'),X.audit?kv(X.audit):h('p',{class:'dim'},'No audit drawn.'));}
function renderCost(m){const C=D.cost||{};m.append(h('h2',null,'Cost and time'));
 m.append(kv({first_event:fmt(C.first_event_at),last_event:fmt(C.last_event_at)}));
 m.append(h('h3',null,'Agent events by stage'),kv(C.events_per_stage||{}));
 m.append(h('h3',null,'Per agent model'),table(['Model','Events','First','Last'],Object.keys(C.per_model||{}).map(k=>[k,C.per_model[k].events,fmt(C.per_model[k].first),fmt(C.per_model[k].last)])));
 const B=C.budget||{};m.append(h('h3',null,'Budgets'),(B.budgets||[]).length?table(['Unit','Scope','Limit','Consumed','Remaining'],B.budgets.map(b=>[b.budget.unit,E(b.budget.scope_user)||'project',b.budget.limit,b.consumed,b.remaining])):h('p',{class:'dim'},B.notice||'None declared.'));
 m.append(h('h3',null,'Reported usage'),kv(B.reported_usage||{}));
 m.append(h('h3',null,'All events by type'),kv(C.events_by_type||{}));}
const TABS=[['protocol','Protocol',renderProtocol],['decisions','Decisions',renderDecisions],['press','PRESS',renderPress],['probes','Probes',renderProbes],['search','Search',renderSearch],['screening','Screening',renderScreening],['extraction','Extraction',renderExtraction],['cost','Cost and time',renderCost]];
function render(){
 const y=window.scrollY,a=document.activeElement,keep=a&&a.id==='q'?[a.selectionStart,a.selectionEnd]:null;
 $('#tabs').replaceChildren(...TABS.map(([k,l])=>h('button',{class:ui.tab===k?'on':'',onclick:()=>{ui.tab=k;render();}},l)));
 const m=$('#main');m.replaceChildren();(TABS.find(t=>t[0]===ui.tab)||TABS[0])[2](m);
 $('#slug').textContent=(D.meta||{}).slug||'';
 window.scrollTo(0,y);
 if(keep){const q=$('#q');if(q){q.focus();q.setSelectionRange(keep[0],keep[1]);}}}
function stamp(){const meta=D.meta||{};$('#fresh').textContent=STATIC?'snapshot '+fmt(meta.generated_at):'updated '+new Date().toTimeString().slice(0,8);
 $('#last').textContent=' / '+(meta.events_total===null||meta.events_total===undefined?0:meta.events_total)+' events / last '+(meta.last_event_id||'none');}
async function poll(){
 try{const r=await fetch('/api/state',{cache:'no-store'});const t=await r.text();
  if(t!==lastJson){lastJson=t;D=JSON.parse(t);render();}stamp();}
 catch(e){$('#fresh').textContent='offline, retrying';}}
if(STATIC){render();stamp();}else{render();poll();setInterval(poll,5000);}
</script></body></html>
"""


def render_page(state: dict[str, JsonValue] | None = None) -> str:
    """The page; with `state` it is a static snapshot, without it the page polls `/api/state`."""
    if state is None:
        return PAGE
    data = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace(POLL_MARKER, data, 1)
