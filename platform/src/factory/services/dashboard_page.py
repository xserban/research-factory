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
.help{border:1px solid var(--mut);background:var(--lt);border-radius:6px;padding:8px 12px;margin:0 0 14px;color:var(--light);font-size:.9rem;line-height:1.5}.help b{color:var(--fg)}
tr.clk{cursor:pointer}tr.clk:hover{background:var(--sel)}tr.sel{background:var(--sel)}
.cmdl{display:flex;gap:8px;align-items:center;margin:3px 0}.cmdl code{background:var(--lt);border:1px solid var(--mut);border-radius:4px;padding:2px 8px;flex:1;overflow-x:auto;white-space:nowrap}
.card{border:1px solid var(--mut);border-radius:8px;padding:10px 14px;margin:14px 0;background:var(--lt)}.card h3{margin:0 0 6px}
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
#run{max-width:1100px;margin:0 auto;padding:0 16px}
#run .op{background:var(--lt);border:1px solid var(--mut);border-radius:6px;padding:6px 12px;margin:8px 0}
#run h2{margin:12px 0 0}
.bar{height:8px;background:var(--dk);border:1px solid var(--mut);border-radius:4px;overflow:hidden;margin:4px 0}
.bar>i{display:block;height:100%;background:var(--ac)}.op.failed .bar>i{background:var(--dim)}
#live{max-width:1100px;margin:0 auto;padding:0 16px}
.fold{cursor:pointer;user-select:none;margin:8px 0;font-size:1rem}.fold .dim{font-weight:normal;margin-left:8px}
.chip{display:inline-block;border:1px solid var(--mut);border-radius:12px;padding:1px 10px;margin:2px 6px 2px 0;font-size:.8rem;color:var(--dim)}
.chip.act{color:var(--ac);border-color:var(--ac)}
.v-include{color:var(--ac)}.v-exclude{color:var(--dim)}.v-unsure{color:var(--blue)}.v-cannot-assess{color:var(--cyan)}
.lscroll{max-height:360px;overflow:auto;border:1px solid var(--mut);border-radius:4px}
@media (max-width:600px){.kvs{grid-template-columns:1fr}main{padding:0 10px 48px}}
*{border-radius:0!important}body{background-image:linear-gradient(rgba(130,251,156,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(130,251,156,.035) 1px,transparent 1px);background-size:28px 28px}button{background:transparent;color:var(--ac);border:1px solid rgba(130,251,156,.45);font-weight:600;font-size:11px;letter-spacing:.1em;text-transform:uppercase;cursor:pointer}button:hover,button.on{background:var(--ac);color:var(--bg)}th{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase}.help,.card,.tile{border-left:3px solid var(--ac)}h2::before{content:'▮';color:var(--ac);margin-right:8px}
</style></head><body>
<header><h1>Factory dashboard <span class="dim" id="slug"></span></h1>
<div class="dim"><span id="fresh">loading</span> <span id="last"></span></div>
<nav id="tabs"></nav></header>
<section id="run"></section>
<section id="live"></section>
<main id="main"></main>
<script>
const STATIC=/*STATE*/null;
let D=STATIC||{decisions:[],sections:[],levels:[],meta:{}};
const HQ=new URLSearchParams(location.hash.slice(1));const ui={miner:HQ.get('miner'),tab:HQ.get('tab')||'protocol',sec:null,open:new Set(),flt:{level:'',status:'',q:''}};
let lastJson='';
const $=s=>document.querySelector(s);
function h(tag,attrs,...kids){const e=document.createElement(tag);
 for(const k in(attrs||{})){const v=attrs[k];if(k==='class')e.className=v;else if(k.startsWith('on'))e.addEventListener(k.slice(2),v);else if(v!==null&&v!==undefined&&v!==false)e.setAttribute(k,v===true?'':v);}
 for(const c of kids.flat(2)){if(c===null||c===undefined||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)));}return e;}
const FOLD={};try{for(const k of['run','live'])FOLD[k]=localStorage.getItem('fold-'+k)==='1';}catch(e){}
function fold(key,title,summary,redraw){return h('h2',{class:'fold',title:'click to '+(FOLD[key]?'expand':'collapse'),onclick:()=>{FOLD[key]=!FOLD[key];try{localStorage.setItem('fold-'+key,FOLD[key]?'1':'0');}catch(e){}redraw();}},(FOLD[key]?'\u25b6 ':'\u25bc ')+title,h('span',{class:'dim'},FOLD[key]?summary:''));}
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
function slugOf(id){return id.replace('rf:','').replace(/[^A-Za-z0-9._-]+/g,'-').slice(0,90);}
function renderConversion(m){const V=D.conversion||{};m.append(h('h2',null,'Conversion coverage'));
 if(V.error){m.append(h('p',{class:'dim'},V.error));return;}
 if(!V.computed){m.append(h('p',{class:'dim'},'Not computed yet. Run: factory document coverage'));return;}
 m.append(h('p',{class:'dim'},'Automatic word 5-gram comparison of each original with its Markdown (computed '+fmt(V.computed_at)+'). Recall: share of the original found in the Markdown. Precision: share of the Markdown found in the original. Noisy: it ranks documents for a human to check, it decides nothing. Low is below '+V.low_below+'.'));
 const S=V.summary||{};m.append(table(['Converter','Documents','Median recall','Median precision','Low recall','Low precision'],Object.keys(S).map(k=>[k,S[k].documents,S[k].median_recall,S[k].median_precision,S[k].low_recall,S[k].low_precision])));
 if(Object.keys(V.not_measured||{}).length)m.append(h('h3',null,'Not measured'),kv(V.not_measured));
 m.append(h('h3',null,'Lowest recall (check these first)'),h('p',{class:'dim'},'Click a work to open the original beside its extracted text in the hub (factory site serve).'),table(['Recall','Precision','Words orig / md','Converter','Work'],(V.lowest||[]).map(r=>[r.recall,r.precision,r.source_words+' / '+r.markdown_words,r.converter,h('a',{href:'http://127.0.0.1:8766/conversion/doc/'+slugOf(r.work_id)+'.html',target:'_blank',title:'open the original beside the extracted text (factory site serve)'},r.title||r.work_id)])));}
const MINER_COLS=[['Units','How many works the miner has to read (one unit per work and pass).'],['Closed','Units finished: the work was read and its rows accepted, or closed with a stated reason.'],['Open','Units not finished yet (waiting, or in progress).'],['Rows','Accepted rows. A work gives one row, or several when the miner records one row per item.'],['Stale','Rows made outdated by a protocol change; they must be read again.']];
const KIND_HELP={enum:'one of a fixed list',quote:'a verbatim sentence from the paper',number:'a number as printed, with its unit',integer:'a whole number',citation:'a citation marker',anchor:'a paragraph anchor',work_ref:'a reference to another work'};
function kindText(k){if(!k)return '';let s=k.type;if(k.values)s+=': '+k.values.join(' | ');if(k.unit_family)s+=' ('+k.unit_family+')';return s;}
function firstSentence(s){if(!s)return '';const i=s.indexOf('. ');const x=i>0?s.slice(0,i+1):s;return x.length>200?x.slice(0,197)+'\u2026':x;}
function cmdRow(c){return h('div',{class:'cmdl'},h('code',null,c),h('button',{onclick:()=>{try{navigator.clipboard.writeText(c);}catch(e){}}},'Copy'));}
function minerCard(r){const d=r.detail||{},S=d.spec||{},U=d.use||{},slug=(D.meta||{}).slug||'PROJECT';
 const sel=S.selector||{},reg=S.regime||{},ev=S.evidence||{};
 const c=h('div',{class:'card'});c.append(h('h3',null,r.name+' v'+r.version));
 c.append(h('p',null,S.rationale||'No rationale recorded.'));
 c.append(h('h3',null,'How it reads'));
 c.append(h('p',{class:'dim'},'The platform picks the paragraphs to read; the model reads them and records values; the platform checks every value and quote against the paper before it is accepted.'));
 c.append(kv({works_read:sel.population+' (the works it runs on)',paragraph_kinds:(sel.elements||[]).join(', '),sections_searched:(sel.heading_patterns||[]).join(', ')||'all',max_works:sel.max_units===null||sel.max_units===undefined?'no limit':sel.max_units,procedure:S.procedure,row_per:'one row per '+((S.row_key_fields||[]).join(' + ')||'work')}));
 c.append(h('h3',null,'Fields ('+(S.fields||[]).length+')'));
 c.append(h('p',{class:'dim'},'Each value is checked: an enum must be one of its allowed values and carry a quote; a quote field must be verbatim from the cited paragraph. \u201cCompared\u201d fields enter the agreement between passes; the others are evidence only.'));
 c.append(table(['Field','Group','Kind','Required','Compared','What it records'],(S.fields||[]).map(f=>[f.name,f.group,kindText(f.kind),f.required?'yes':'',f.compared===false?'no':'yes',f.description||''])));
 c.append(h('h3',null,'Quality and use'));
 c.append(kv({passes:reg.passes+' (pass A reads every work; pass B a sample)',second_pass_sample:U.dual_extract_sample===null||U.dual_extract_sample===undefined?'every work':Math.round(U.dual_extract_sample*100)+'% of works read again by another model',audit:'a random '+Math.round(100*(U.audit_fraction||0))+'% of rows, at least '+(U.audit_minimum||0)+', checked by the researcher',evidence_admitted:U.evidence?'yes: rows enter the evidence report':'no: rows are not admitted to the evidence report',imports:U.imports||'',quote_rule:ev.enum_needs_quote?'every enum value needs a quote':'',calibration:reg.calibration_size?reg.calibration_size+' works labelled by a person before trust, field agreement at least '+reg.field_agreement_min+', recall at least '+reg.recall_min:''}));
 c.append(h('h3',null,'Versions'));
 c.append(h('p',{class:'dim'},'A change to a miner is a new version; older versions keep their rows. Only the listed version runs.'));
 c.append(table(['Version','Digest','Listed in the protocol','Proposed by'],(d.versions||[]).map(v=>[v.version,v.digest,v.listed?'yes':'no',v.proposer])));
 c.append(h('h3',null,'What you can do'));
 c.append(h('p',{class:'dim'},'Run these in a terminal (the dashboard is read-only). The hub\u2019s Miners product (factory site serve) adds per-field agreement and example rows.'));
 for(const x of ['factory --project '+slug+' mine status','factory --project '+slug+' mine agreement '+r.name,'factory --project '+slug+' mine resolve --help'])c.append(cmdRow(x));
 return c;}
function renderMiners(m){const R=D.miners||[];m.append(h('h2',null,'Miners'));
 if(!R.length){m.append(h('p',{class:'dim'},'No miner is listed in the protocol.'));return;}
 m.append(h('h3',null,'How to read the table'));
 m.append(table(['Column','Meaning'],MINER_COLS.map(x=>[x[0],x[1]])));
 m.append(h('p',{class:'dim'},'Agreement is not shown here because it takes too long to compute live; see the hub\u2019s Miners and Miner agreement products.'));
 m.append(h('h3',null,'Listed miners (click one for details)'));
 m.append(h('div',{class:'scroll'},h('table',null,h('tr',null,['Miner','Version','What it records','Units','Closed','Open','Rows','Stale'].map(x=>h('th',null,x))),R.map(r=>h('tr',{class:'clk'+(ui.miner===r.name?' sel':''),onclick:()=>{ui.miner=ui.miner===r.name?null:r.name;render();}},[r.name,r.version,firstSentence(((r.detail||{}).spec||{}).rationale),r.units,r.closed,r.open,r.rows,r.stale].map(c=>h('td',null,c)))))));
 const sel=R.find(r=>r.name===ui.miner);if(sel)m.append(minerCard(sel));else m.append(h('p',{class:'dim'},'Select a miner to see its fields, how it reads, how it is checked and what you can do.'));}
function renderProducts(m){const R=D.products||[];m.append(h('h2',null,'Products'));
 m.append(h('p',{class:'dim'},'Every product of the factory for this project, rebuilt from the events. Open the hub with: factory site serve (http://127.0.0.1:8766/). Rebuild with: factory site build.'));
 if(!R.length){m.append(h('p',{class:'dim'},'No product is registered.'));return;}
 m.append(table(['Product','Group','State','Built','Model-written'],R.map(r=>[h('a',{href:'http://127.0.0.1:8766/#'+r.id,target:'_blank'},r.title),r.group,r.error?'build failed':(r.stale?'stale':'up to date'),r.built_at||'not built yet',r.needs_model?'yes':''])));}
function feedPart(title,v,f){const box=h('div',null,h('h3',null,title));if(v==='unavailable')box.append(h('p',{class:'dim'},'unavailable'));else f(box,v);return box;}
function renderFeed(m){const F=D.feed;if(!F)return;m.append(h('h2',null,'Feed and queue'));
 if(F.error){m.append(h('p',{class:'dim'},'unavailable'));return;}
 m.append(h('div',{class:'row'},h('a',{href:'http://127.0.0.1:8766/feed/',target:'_blank'},'Feed (hub)'),h('a',{href:'http://127.0.0.1:8766/queue/',target:'_blank'},'Queue (hub)')));
 m.append(h('p',{class:'dim'},'Categories: '+(F.categories||[]).join(', ')+' \u00b7 shown per cycle '+E(F.shown_per_cycle)+' \u00b7 every '+E(F.interval_days)+' day(s)'));
 m.append(feedPart('Last fetch',F.fetch,(b,f)=>b.append(kv({last_window_from:f.last_window_from,last_window_to:f.last_window_to,next_due:f.next_due,due_now:f.due?'yes':'no'}))));
 m.append(feedPart('Latest ranking',F.ranking,(b,f)=>b.append(kv({ranking_id:f.ranking_id,shown:f.shown,explore:f.explore}))));
 m.append(feedPart('Top shown titles (last 7 days for reactions and adds)',F.top,(b,f)=>b.append(table(['Title','Score','Reaction','Sent','Reactions 7d','Adds 7d'],f.map(t=>[t.title||t.entry_id,E(t.score),E(t.reaction),t.sent?'yes':'',t.reactions_7d,t.adds_7d])))));
 m.append(feedPart('Work queue',F.queue,(b,f)=>{b.append(kv({added_papers:f.added}));const st=Object.keys(f.stages||{});
  b.append(st.length?table(['Stage','Added papers'],st.map(k=>[k,f.stages[k]])):h('p',{class:'dim'},'no added papers'));
  const pk=Object.keys(f.pending||{});b.append(table(['Pending kind','Open units'],pk.map(k=>[k,f.pending[k]])));}));
 m.append(feedPart('Last run',F.run,(b,f)=>{const L=f.last;b.append(kv({run_open:f.run_open?'yes':'no',pipeline_open:f.pipeline_open?'yes':'no'}));
  b.append(L?kv({stage:L.stage,outcome:L.outcome,finished_at:L.finished_at||'not finished'}):h('p',{class:'dim'},'no run yet'));}));
}
function tabs(){return D.feed?TABS.concat([['feed','Feed and queue',renderFeed]]):TABS;}
function renderCost(m){const C=D.cost||{};m.append(h('h2',null,'Cost and time'));
 m.append(kv({first_event:fmt(C.first_event_at),last_event:fmt(C.last_event_at)}));
 m.append(h('h3',null,'Agent events by stage'),kv(C.events_per_stage||{}));
 m.append(h('h3',null,'Per agent model'),table(['Model','Events','First','Last'],Object.keys(C.per_model||{}).map(k=>[k,C.per_model[k].events,fmt(C.per_model[k].first),fmt(C.per_model[k].last)])));
 const B=C.budget||{};m.append(h('h3',null,'Budgets'),(B.budgets||[]).length?table(['Unit','Scope','Limit','Consumed','Remaining'],B.budgets.map(b=>[b.budget.unit,E(b.budget.scope_user)||'project',b.budget.limit,b.consumed,b.remaining])):h('p',{class:'dim'},B.notice||'None declared.'));
 m.append(h('h3',null,'Reported usage'),kv(B.reported_usage||{}));
 m.append(h('h3',null,'All events by type'),kv(C.events_by_type||{}));}
let P=(STATIC&&STATIC.progress)||[];
function dur(s){if(s===null||s===undefined)return '-';s=Math.round(s);const m=Math.floor(s/60),x=s%60;return m?m+'m '+String(x).padStart(2,'0')+'s':x+'s';}
function drawRun(){const box=$('#run');if(!box)return;
 const L=(P||[]).filter(o=>o.state==='running'||o.state==='stale'||(o.idle_seconds||0)<30);
 if(!L.length){box.replaceChildren();return;}
 const sum=L.map(o=>o.label+(o.total?' '+Math.min(100,Math.round(100*o.done/o.total))+'%':'')).join(' / ');
 const head=fold('run','Running now',sum,drawRun);
 if(FOLD.run){box.replaceChildren(head);return;}
 box.replaceChildren(head,...L.map(o=>{
  const pct=o.total?Math.min(100,Math.round(100*o.done/o.total)):0;
  const bar=h('div',{class:'bar'},h('i',{style:'width:'+pct+'%'}));
  const cnt=o.done+(o.total?' / '+o.total:'')+' '+o.unit+(o.total?' ('+pct+'%)':'');
  const tail=o.state==='running'?[o.rate_per_second?o.rate_per_second+' '+o.unit+'/s':'',o.eta_seconds!==null&&o.eta_seconds!==undefined?'ETA '+dur(o.eta_seconds):'','elapsed '+dur(o.elapsed_seconds)].filter(x=>x).join(' / '):
   (o.state==='finished'?'done in '+dur(o.elapsed_seconds):o.state+(o.message?': '+o.message:''));
  return h('div',{class:'op '+o.state},h('b',null,o.label),' ',h('span',{class:'dim'},o.kind+' / '+o.state+(o.state==='running'&&o.message?' / '+o.message:'')),bar,h('div',{class:'dim'},cnt+(tail?' / '+tail:'')));}));}
function running(){return(P||[]).some(o=>o.state==='running');}
async function pollProgress(){
 try{const r=await fetch('/api/progress',{cache:'no-store'});P=JSON.parse(await r.text());drawRun();}catch(e){}
 setTimeout(pollProgress,running()?1500:5000);}
let L=(STATIC&&STATIC.screening_live)||null;
function drawLive(){const box=$('#live');if(!box)return;
 if(!L||L.error||(!(L.recent||[]).length&&!(L.sessions||[]).length)){box.replaceChildren();return;}
 const old=box.querySelector('.lscroll'),top=old?old.scrollTop:0;
 const tot=L.totals||{},rem=L.remaining!==null&&L.remaining!==undefined?L.remaining:((D.screening||{}).records_left);
 const tl=Object.keys(tot).sort().map(k=>h('div',{class:'tile'},h('b',null,Object.values(tot[k]).reduce((a,b)=>a+b,0)),'pass '+k.toUpperCase()+': '+Object.keys(tot[k]).sort().map(v=>v+' '+tot[k][v]).join(', ')));
 if(rem!==null&&rem!==undefined)tl.push(h('div',{class:'tile'},h('b',null,rem),'in queue (pass A)'));
 const chips=(L.sessions||[]).map(s=>h('span',{class:'chip'+(s.active?' act':'')},s.session+' '+s.actor+' / '+s.decisions+' dec / '+s.includes+' inc / '+(s.rate_per_minute===null||s.rate_per_minute===undefined?'-':s.rate_per_minute+'/min')+' / last '+fmt(s.last_at).slice(11,19)));
 const stops=(L.stops||[]).map(s=>{const pct=s.n?Math.min(100,Math.round(100*s.run/s.n)):0;
  return h('div',null,h('span',{class:'dim'},s.rule+(s.below_score?' (<'+s.below_score+')':'')+': '+s.progress+(s.stopped?' stopped':'')),h('div',{class:'bar'},h('i',{style:'width:'+pct+'%'})));});
 const rows=(L.recent||[]).map(r=>h('tr',null,h('td',null,fmt(r.ts).slice(11,19)),h('td',null,r.pass),h('td',null,r.session),h('td',null,E(r.title)),
  h('td',{class:'v-'+r.verdict},r.verdict),h('td',null,E(r.score)),h('td',null,E(r.criterion)),h('td',null,r.quote),h('td',{class:'dim'},r.rationale)));
 const act=(L.sessions||[]).filter(x=>x.active).length;
 const head=fold('live','Screening live',act+' active / '+(rem===null||rem===undefined?'-':rem+' in queue'),drawLive);
 if(FOLD.live){box.replaceChildren(head);return;}
 box.replaceChildren(head,h('div',null,chips),h('div',{class:'tiles'},tl),...stops,
  h('div',{class:'lscroll'},h('table',null,h('tr',null,['Time','Pass','Session','Work','Verdict','Score','Criterion','Quote','Rationale'].map(x=>h('th',null,x))),rows)));
 const n=box.querySelector('.lscroll');if(n)n.scrollTop=top;}
function liveActive(){return L&&(L.sessions||[]).some(s=>s.active);}
async function pollLive(){
 try{const r=await fetch('/api/screening',{cache:'no-store'});L=JSON.parse(await r.text());drawLive();}catch(e){}
 setTimeout(pollLive,liveActive()?3000:15000);}
const TAB_HELP={
protocol:'<b>The protocol</b> is the review\u2019s plan, recorded before screening: the question, the inclusion and exclusion criteria, the sources and queries, how screening and extraction are done, and which miners are used. Every later change is an <b>amendment</b> (with a reason and whether it changes the meaning) or a <b>deviation</b> (something done differently from the plan). Read this first: everything else is judged against it.',
decisions:'<b>Decisions</b> are the researcher\u2019s rulings: the options that were on the table, the choice, who decided and why. They are append-only; a ruling is replaced by a newer one, never edited. Open an entry to see its options and its consequences.',
press:'<b>PRESS</b> is a peer review of the search strategy (terms, databases, limits) before the search is run. Each finding gets a response, and the search counts as confirmed only after the review is closed.',
probes:'<b>Probes</b> are small trial searches that test the strategy before the real one: how many records a query returns, and whether known seed papers are found. They are not part of the review\u2019s results.',
search:'<b>The search</b>: each query, the source it ran on, the number of records the source reported and the number retrieved, any shortfall with its reason, and the duplicates removed afterwards. The PRISMA flow is computed from these counts.',
screening:'<b>Screening</b> decides which records stay in the review. Pass A screens every record; a second pass screens a sample, so the agreement between the two shows how stable the decisions are. Calibration and audits are checks by the researcher. Title/abstract screening comes first; full-text screening follows for the records promoted.',
extraction:'<b>Extraction</b> (the older claim-row pack): units, papers, rows and the agreement of two passes. In this project the <b>miners</b> do the extraction (see the Miners tab); this tab mostly stays empty.',
conversion:'<b>Conversion</b> turns each downloaded PDF or HTML page into Markdown with a numbered anchor on every paragraph, so a quote can point to its place. <b>Recall</b> is the share of the original\u2019s words found in the Markdown (low: text may be lost); <b>precision</b> is the share of the Markdown\u2019s words found in the original (low: text added or scrambled). Both are noisy and only rank documents for a person to check. The hub\u2019s Conversion product opens each document with the original beside the extracted text.',
miners:'<b>Miners</b> read the included full texts and record typed, quoted values: each value is an enum, a number or a verbatim sentence, never free text. One model reads every work (pass A); another reads a sample (pass B) so agreement can be measured. Click a miner below to see what it records, how it reads, its fields and how to work with it.',
products:'<b>Products</b> are the reports and views the factory builds from the events: dashboard snapshot, explorer, wiki, results, agreement, taxonomy, synthesis, conversion, acquisition, PRISMA and bibliography. Each is rebuilt when the events it reads change; the hub opens them all.',
cost:'<b>Cost and time</b>: how many agent events each stage and model recorded, the budgets declared and the usage reported. These are recorded events, not dollars: the model sessions\u2019 own cost figures are not stored by the platform.'};
const TAB_ACTIONS={
protocol:{cmds:['protocol show','protocol amend --help','protocol deviation --help'],hub:[]},
decisions:{cmds:['decide list','decide show --help','decide select --help'],hub:[]},
press:{cmds:['protocol show','protocol confirm-press --help'],hub:[]},
probes:{cmds:['protocol show'],hub:[]},
search:{cmds:['report search','dedup list','search --help'],hub:[['PRISMA flow','prisma']]},
screening:{cmds:['screen disagreements','screen resolve --help','audit --help','report prisma'],hub:[['PRISMA flow and criteria','prisma'],['Full-text acquisition','acquisition']]},
extraction:{cmds:['mine status'],hub:[['Results','results'],['Miners','miners']]},
conversion:{cmds:['document status','document coverage','document convert --help'],hub:[['Conversion coverage: open each document beside its extracted text','conversion']]},
products:{cmds:['site build','site status','site serve'],hub:[['Open the hub','']]},
cost:{cmds:['budget --help','report methods'],hub:[['Results (events per model)','results']]}};
const TABS=[['protocol','Protocol',renderProtocol],['decisions','Decisions',renderDecisions],['press','PRESS',renderPress],['probes','Probes',renderProbes],['search','Search',renderSearch],['screening','Screening',renderScreening],['extraction','Extraction',renderExtraction],['conversion','Conversion',renderConversion],['miners','Miners',renderMiners],['products','Products',renderProducts],['cost','Cost and time',renderCost]];
function render(){
 const y=window.scrollY,a=document.activeElement,keep=a&&a.id==='q'?[a.selectionStart,a.selectionEnd]:null;
 $('#tabs').replaceChildren(...tabs().map(([k,l])=>h('button',{class:ui.tab===k?'on':'',onclick:()=>{ui.tab=k;render();}},l)));
 const m=$('#main');m.replaceChildren();if(TAB_HELP[ui.tab]){const hp=h('div',{class:'help'});hp.innerHTML=TAB_HELP[ui.tab];m.append(hp);}const ta=TAB_ACTIONS[ui.tab];if(ta){const slug=(D.meta||{}).slug||'PROJECT';const bx=h('div',{class:'help'},h('b',null,'What you can do'),h('div',{class:'dim'},'Run these in a terminal (the dashboard is read-only).'),ta.cmds.map(c=>cmdRow('factory --project '+slug+' '+c)));if(ta.hub.length)bx.append(h('div',{class:'dim'},'In the hub (factory site serve): ',ta.hub.map(x=>h('a',{href:'http://127.0.0.1:8766/#'+x[1],target:'_blank',style:'margin-right:12px'},x[0]))));m.append(bx);}(tabs().find(t=>t[0]===ui.tab)||TABS[0])[2](m);
 $('#slug').textContent=(D.meta||{}).slug||'';
 window.scrollTo(0,y);
 if(keep){const q=$('#q');if(q){q.focus();q.setSelectionRange(keep[0],keep[1]);}}}
function stamp(){const meta=D.meta||{};$('#fresh').textContent=STATIC?'snapshot '+fmt(meta.generated_at):'updated '+new Date().toTimeString().slice(0,8);
 $('#last').textContent=' / '+(meta.events_total===null||meta.events_total===undefined?0:meta.events_total)+' events / last '+(meta.last_event_id||'none');}
async function poll(){
 try{const r=await fetch('/api/state',{cache:'no-store'});const t=await r.text();
  const j=JSON.parse(t);P=j.progress||[];delete j.progress;if(j.screening_live&&!L)L=j.screening_live;delete j.screening_live;drawRun();drawLive();
  const key=JSON.stringify(j);if(key!==lastJson){lastJson=key;D=j;render();}stamp();}
 catch(e){$('#fresh').textContent='offline, retrying';}}
if(STATIC){render();drawRun();drawLive();stamp();}else{render();poll();setInterval(poll,5000);pollProgress();pollLive();}
</script></body></html>
"""


def render_page(state: dict[str, JsonValue] | None = None) -> str:
    """The page; with `state` it is a static snapshot, without it the page polls `/api/state`."""
    if state is None:
        return PAGE
    data = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace(POLL_MARKER, data, 1)
