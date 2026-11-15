# ruff: noqa: E501, RUF001
"""The Flow explorer page: one HTML string with inline CSS and JS, no external resource.

`PAGE` carries a `/*DATA*/null` marker that `site_flow` replaces with the payload. The trails are not
embedded: the page loads `trails.js` (which sets `window.FLOW_TRAILS`) when a work is first opened.
The palette and theme follow the explorer page.
"""

from __future__ import annotations

from factory.services.site_theme import LIGHT_CSS, THEME_SCRIPT, THEME_TOGGLE

DATA_MARKER = "/*DATA*/null"

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<!--THEME-->
<title>Flow explorer</title>
<style>
:root{color-scheme:dark;--bg:#0B0C16;--panel:#151828;--ink:#ddf7ff;--dim:#6a6e95;--line:#2d3450;--acc:#82FB9C;--ac:#82FB9C;--red:#ff8a80;--green:#4fe88f;--hi:#1f253a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif}
header{display:flex;gap:10px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
header h1{font-size:15px;margin:0 8px 0 0}input,select,button{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
button{cursor:pointer}button:hover{border-color:var(--acc)}
.dim{color:var(--dim)}.red{color:var(--red)}.ok{color:var(--green)}
main{padding:12px 14px 60px;max-width:1280px;margin:0 auto}
h2{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:24px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--dim);font-size:11px;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}
th.sort{cursor:pointer}th.sort:hover{color:var(--ink)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
td.n a{color:var(--acc);cursor:pointer;text-decoration:none}td.n a:hover{text-decoration:underline}
tr.t0 td:first-child{font-weight:600}
tr.tw td{border-bottom:1px solid var(--line)}
#bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}
#bar select{max-width:220px}
.chip{background:var(--hi);border:1px solid var(--acc);color:var(--ink)}
#list tr{cursor:pointer}#list tr:hover td{background:var(--hi)}
.lnk{color:var(--acc);cursor:pointer}
#panel{position:fixed;top:0;right:0;bottom:0;width:min(520px,100vw);background:var(--panel);border-left:1px solid var(--line);padding:12px 16px;overflow:auto;transform:translateX(105%);transition:transform .15s;z-index:5}
#panel.open{transform:none}
#panel h3{margin:0 24px 4px 0;font-size:15px}
.xbtn{position:absolute;top:8px;right:10px}
.step{border-left:2px solid var(--line);margin:0 0 8px 4px;padding:0 0 0 10px}
.kind{display:inline-block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--bg);background:var(--acc);padding:0 6px;border-radius:4px;margin-right:6px}
.step .tm{color:var(--dim);font-size:12px}
.step .kv{font-size:13px}.step .kv b{color:var(--dim);font-weight:600}
.step blockquote{margin:2px 0;padding:0 0 0 8px;border-left:2px solid var(--line);color:var(--dim);font-size:12.5px}
.skip td{font-size:12.5px}
details summary{cursor:pointer;color:var(--dim);margin:6px 0}
FUTURE_OVERLAY/*LIGHT*/</style></head><body>
<header><h1>Flow explorer</h1><span id="recon"></span><!--TOGGLE--><span class="dim" style="margin-left:auto" id="gen"></span></header>
<main>
<p class="dim">Every identified record, by the source that found it and the step it reached. A number in the table filters the list below to those records. Click a title for its trail.</p>
<h2>PRISMA steps by source</h2>
<div style="overflow:auto"><table id="flow"></table></div>
<h2>Works</h2>
<div id="bar">
<input id="q" placeholder="Search title, id, source…" size="30">
<select id="fg"></select><select id="fs"></select><select id="fo"></select><select id="fc"></select>
<span id="chips"></span><button id="clear">Clear filters</button><button id="csv">Download CSV</button><span id="count" class="dim"></span>
</div>
<div style="overflow:auto"><table><thead><tr id="head"></tr></thead><tbody id="list"></tbody></table></div>
<p><button id="more" hidden>Show more</button></p>
<div id="prisma"></div>
<h2>Records that never became works</h2>
<div id="skipped"></div>
</main>
<div id="panel"><button class="xbtn" id="pclose">Close</button><div id="pbody"></div></div>
<script>
const DATA=/*DATA*/null;
const W=DATA.works,BY={};W.forEach(w=>BY[w.i]=w);
const KIDS={};W.forEach(w=>{if(w.p)(KIDS[w.p]=KIDS[w.p]||[]).push(w.i);});
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const F={q:'',g:'',st:'',o:'',c:'',k:''};
const COLS=[['t','Title',1],['y','Year',1],['g','Source group',1],['s','Sources',0],['st','Step reached',1],['o','Outcome',1],['c','Criterion or reason',1]];
let SORT=['y',-1],SHOWN=300,CUR=[];
$('#gen').textContent=DATA.project+' · '+DATA.generated;
const rc=$('#recon');
if(DATA.mismatches.length){rc.className='red';rc.innerHTML='The ledger does not reconcile with the PRISMA flow: '+DATA.mismatches.map(esc).join('; ');}
else{rc.className='ok';rc.textContent='Every count reconciles with the PRISMA flow';}
const LABEL={'id':'identified','dup':'duplicates','scr':'screened','ta-exc':'excluded at title/abstract','ta-inc':'included at title/abstract','ta-pen':'pending at title/abstract','prom':'promoted','ns':'not yet sought','sought':'sought','nr':'not retrieved','ret':'retrieved','ft-exc':'excluded at full text','ft-inc':'included at full text','ft-pen':'pending at full text','ft-aw':'awaiting resolution'};
function count(k,c,g){let n=0;for(const w of W){if(!w.k.includes(k))continue;if(c!=null&&(w.c||'unspecified')!==c)continue;if(g&&g!==DATA.total&&w.g!==g)continue;n++;}return n;}
function drawTable(){
 const G=DATA.groups.concat([DATA.total]);
 let h='<thead><tr><th>step</th>'+G.map(g=>'<th class="n">'+esc(g)+'</th>').join('')+'</tr></thead><tbody>';
 DATA.spec.forEach((r,i)=>{
  h+='<tr class="t'+(r.d===0?0:'w')+'"><td style="padding-left:'+(8+r.d*16)+'px">'+esc(r.l)+'</td>';
  G.forEach(g=>{const n=count(r.k,r.c,g);h+='<td class="n">'+(n?'<a data-r="'+i+'" data-g="'+esc(g)+'">'+n+'</a>':'')+'</td>';});
  h+='</tr>';});
 $('#flow').innerHTML=h+'</tbody>';
 $('#flow').querySelectorAll('a').forEach(a=>a.onclick=()=>{const r=DATA.spec[+a.dataset.r];
  F.g=a.dataset.g===DATA.total?'':a.dataset.g;F.k=r.k;F.c=r.c||'';F.st='';F.o='';F.q='';$('#q').value='';syncSel();SHOWN=300;render();$('#bar').scrollIntoView({behavior:'smooth'});});
}
function drawPrisma(){const P=DATA.prisma,el=$('#prisma');
 const src=Object.entries(P.identified).map(([k,n])=>'<tr><td>identified, database: '+esc(k)+'</td><td class="n">'+n+'</td></tr>').join('');
 const oth=Object.entries(P.identified_other).map(([k,n])=>'<tr><td>identified, other: '+esc(k)+'</td><td class="n">'+n+'</td></tr>').join('');
 el.innerHTML='<h2>PRISMA identification (from the PRISMA flow)</h2><p class="dim">These figures come from the PRISMA flow, not from the ledger rows above. A merged work\'s absorbed duplicates are grouped by their own provenance, so the per-column ledger rows close only in the total.</p><table><tbody>'+src+oth+'<tr><td>duplicate records removed</td><td class="n">'+P.duplicates_removed+'</td></tr></tbody></table>';}
function opts(sel,key,label){const vals=[...new Set(W.map(w=>w[key]||''))].filter(v=>v).sort();
 $(sel).innerHTML='<option value="">'+label+': all</option>'+vals.map(v=>'<option>'+esc(v)+'</option>').join('');}
function syncSel(){$('#fg').value=F.g;$('#fs').value=F.st;$('#fo').value=F.o;
 const c=$('#fc');if(F.c&&![...c.options].some(o=>o.value===F.c)){c.add(new Option(F.c,F.c));}c.value=F.c;}
function filtered(){const q=F.q.toLowerCase();
 return W.filter(w=>(!F.g||w.g===F.g)&&(!F.st||w.st===F.st)&&(!F.o||w.o===F.o)&&(!F.c||(w.c||'unspecified')===F.c)&&(!F.k||w.k.includes(F.k))&&
  (!q||w.t.toLowerCase().includes(q)||w.i.toLowerCase().includes(q)||w.s.join(' ').toLowerCase().includes(q)));}
function render(){
 CUR=filtered();const [key,dir]=SORT;
 CUR.sort((a,b)=>{const x=a[key]==null?'':a[key],y=b[key]==null?'':b[key];return (x<y?-1:x>y?1:0)*dir||(a.i<b.i?-1:1);});
 $('#count').textContent=CUR.length+' of '+W.length+' records';
 $('#chips').innerHTML=F.k?'<button class="chip" id="kchip" title="remove this filter">'+esc(LABEL[F.k]||F.k)+' ×</button>':'';
 if(F.k)$('#kchip').onclick=()=>{F.k='';render();};
 $('#head').innerHTML=COLS.map(([k,l,s])=>s?'<th class="sort" data-k="'+k+'">'+l+(SORT[0]===k?(SORT[1]>0?' ▲':' ▼'):'')+'</th>':'<th>'+l+'</th>').join('');
 $('#head').querySelectorAll('th.sort').forEach(th=>th.onclick=()=>{const k=th.dataset.k;SORT=SORT[0]===k?[k,-SORT[1]]:[k,1];render();});
 $('#list').innerHTML=CUR.slice(0,SHOWN).map(w=>'<tr data-i="'+esc(w.i)+'"><td>'+esc(w.t)+'</td><td>'+esc(w.y)+'</td><td>'+esc(w.g)+'</td><td>'+esc(w.s.join(', '))+'</td><td>'+esc(w.st)+'</td><td>'+esc(w.o)+'</td><td>'+esc(w.c)+'</td></tr>').join('');
 $('#list').querySelectorAll('tr').forEach(tr=>tr.onclick=()=>openWork(tr.dataset.i));
 const more=$('#more');more.hidden=CUR.length<=SHOWN;more.textContent='Show '+Math.min(300,CUR.length-SHOWN)+' more';
}
$('#more').onclick=()=>{SHOWN+=300;render();};
for(const [id,key] of [['fg','g'],['fs','st'],['fo','o'],['fc','c']])$('#'+id).onchange=e=>{F[key]=e.target.value;SHOWN=300;render();};
$('#q').oninput=e=>{F.q=e.target.value;SHOWN=300;render();};
$('#clear').onclick=()=>{Object.assign(F,{q:'',g:'',st:'',o:'',c:'',k:''});$('#q').value='';syncSel();SHOWN=300;render();};
$('#csv').onclick=()=>{const q=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
 const rows=[['work_id','title','year','source_group','sources','step','outcome','criterion_or_reason','duplicate_of']].concat(CUR.map(w=>[w.i,w.t,w.y,w.g,w.s.join('; '),w.st,w.o,w.c,w.p||'']));
 const blob=new Blob([rows.map(r=>r.map(q).join(',')).join('\n')+'\n'],{type:'text/csv'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='flow-works.csv';document.body.append(a);a.click();a.remove();};
let TRAILS=null;
function loadTrails(){return new Promise(res=>{if(window.FLOW_TRAILS){res(window.FLOW_TRAILS);return;}
 const s=document.createElement('script');s.src='trails.js';s.onload=()=>res(window.FLOW_TRAILS||{});s.onerror=()=>res(null);document.head.append(s);});}
const LONG=new Set(['rationale','quote','reason','error']);
function stepHtml(s){let kv='',long='';
 for(const [k,v] of Object.entries(s.d)){const key=k==='pass_label'?'pass':k;
  if(LONG.has(k))long+='<blockquote><b>'+esc(key)+':</b> '+esc(v)+'</blockquote>';
  else if((k==='primary'||k==='document')&&BY[v])kv+='<b>'+esc(key)+'</b> <a class="lnk" data-w="'+esc(v)+'">'+esc(v)+'</a> ';
  else kv+='<b>'+esc(key)+'</b> '+esc(v)+' ';}
 return '<div class="step"><span class="kind">'+esc(s.kind)+'</span><span class="tm">'+esc(s.at.replace('T',' ').replace(/\.\d+Z$/,'Z'))+'</span><div class="kv">'+kv+'</div>'+long+'</div>';}
async function openWork(id){
 const w=BY[id];const p=$('#panel');p.classList.add('open');
 if(!w){$('#pbody').textContent='No record '+id;return;}
 let h='<h3>'+esc(w.t)+'</h3><div class="dim">'+esc(w.i)+' · '+esc(w.y)+' · '+esc(w.g)+' ('+esc(w.s.join(', '))+')</div>'+
  '<p>Step reached: <b>'+esc(w.st)+'</b>, '+esc(w.o)+(w.c?' ('+esc(w.c)+')':'')+'</p>';
 if(w.p)h+='<p>Duplicate of <a class="lnk" data-w="'+esc(w.p)+'">'+esc(BY[w.p]?BY[w.p].t:w.p)+'</a></p>';
 const kids=KIDS[id]||[];
 if(kids.length)h+='<p>Absorbed duplicates: '+kids.map(k=>'<a class="lnk" data-w="'+esc(k)+'">'+esc(BY[k]?BY[k].t:k)+'</a>').join('; ')+'</p>';
 $('#pbody').innerHTML=h+'<p class="dim">Loading trail…</p>';
 const T=await loadTrails();
 let tail;
 if(T===null)tail='<p class="red">The trail file trails.js could not be loaded.</p>';
 else{const steps=T[id]||[];tail='<h2>Trail</h2>'+(steps.length?steps.map(stepHtml).join(''):'<p class="dim">No recorded steps.</p>');}
 $('#pbody').innerHTML=h+tail;
 $('#pbody').querySelectorAll('a[data-w]').forEach(a=>a.onclick=()=>openWork(a.dataset.w));
 p.scrollTop=0;
}
$('#pclose').onclick=()=>$('#panel').classList.remove('open');
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#panel').classList.remove('open');});
function drawSkipped(){const el=$('#skipped');
 if(DATA.skip_error){el.innerHTML='<p class="red">The archived search pages could not be read: '+esc(DATA.skip_error)+'</p>';return;}
 let h='<p class="dim">Records that a source returned but that did not become a work in their run, and the gap between the total a source reported and the records retrieved, per query.</p>';
 h+='<h3>Reported against retrieved, per query</h3>';
 if(!DATA.skip_gaps.length)h+='<p class="dim">No search runs recorded.</p>';
 else h+='<table><thead><tr><th>query</th><th>source</th><th class="n">reported</th><th class="n">retrieved</th><th class="n">gap</th><th>runs</th></tr></thead><tbody>'+DATA.skip_gaps.map(g=>'<tr><td>'+esc(g.q)+'</td><td>'+esc(g.s)+'</td><td class="n">'+esc(g.rep==null?'not reported':g.rep)+'</td><td class="n">'+g.got+'</td><td class="n'+(g.gap?' red':'')+'">'+esc(g.gap==null?'':g.gap)+'</td><td>'+g.runs.map(r=>esc(r[0])+' '+esc(r[1])+' ('+r[3]+' retrieved'+(r[4]?', '+r[4]+' skipped':'')+(r[5]?'; '+esc(r[5]):'')+')').join('<br>')+'</td></tr>').join('')+'</tbody></table>';
 const S=DATA.skip_skipped;const by={};S.forEach(s=>by[s[5]]=(by[s[5]]||0)+1);
 h+='<h3>Skipped records ('+S.length+')</h3>';
 if(!S.length)h+='<p class="dim">None.</p>';
 else{h+='<p>'+Object.entries(by).map(([k,n])=>esc(k)+': '+n).join(' · ')+'</p><details><summary>List them</summary><table class="skip"><thead><tr><th>reason</th><th>source</th><th>query</th><th>run</th><th>native id</th><th>title</th></tr></thead><tbody>'+S.slice(0,2000).map(s=>'<tr><td>'+esc(s[5])+'</td><td>'+esc(s[2])+'</td><td>'+esc(s[1])+'</td><td>'+esc(s[0])+'</td><td>'+esc(s[3])+'</td><td>'+esc(s[4])+'</td></tr>').join('')+'</tbody></table>'+(S.length>2000?'<p class="dim">The first 2000 of '+S.length+' are shown.</p>':'')+'</details>';}
 el.innerHTML=h;}
opts('#fg','g','Source group');opts('#fs','st','Step');opts('#fo','o','Outcome');opts('#fc','c','Criterion or reason');
drawTable();drawPrisma();drawSkipped();render();
</script></body></html>
"""

PAGE = (
    PAGE.replace("<!--THEME-->", THEME_SCRIPT)
    .replace("/*LIGHT*/", LIGHT_CSS)
    .replace("<!--TOGGLE-->", THEME_TOGGLE)
)
