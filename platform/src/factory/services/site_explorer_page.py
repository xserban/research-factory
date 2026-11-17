# ruff: noqa: E501, RUF001
"""The explorer page: one HTML string with inline CSS and JS, no external resource (plan site-hub, step 2).

`PAGE` carries a `/*DATA*/null` marker that the explorer product replaces with the corpus payload
(`site_corpus.corpus_payload`). Views: list, timeline, chronology, lineage, graph; a detail panel with
the structured summary, the quoted evidence and a link to the original. The palette is the
dashboard's (Omarchy Hackerman, dark only).
"""

from __future__ import annotations

from factory.services.site_theme import LIGHT_CSS, THEME_SCRIPT, THEME_TOGGLE

DATA_MARKER = "/*DATA*/null"

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<!--THEME-->
<title>Corpus explorer</title>
<style>
:root{color-scheme:dark;--bg:#0B0C16;--panel:#151828;--ink:#ddf7ff;--dim:#6a6e95;--line:#2d3450;--acc:#82FB9C;--ac:#82FB9C;--red:#ff8a80;--green:#4fe88f;--hi:#1f253a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
header{display:flex;gap:10px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
header h1{font-size:15px;margin:0 8px 0 0}input,select,button{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
button{cursor:pointer}button.on{background:var(--acc);color:var(--bg);border-color:var(--acc)}
main{flex:1;display:flex;min-height:0}
#side{width:250px;overflow:auto;border-right:1px solid var(--line);padding:8px 10px;background:var(--panel)}
#side h3{margin:10px 0 4px;font-size:12px;text-transform:uppercase;color:var(--dim);letter-spacing:.04em}
.f{display:flex;gap:6px;align-items:center;font-size:13px;padding:1px 0;cursor:pointer}.f span.n{margin-left:auto;color:var(--dim)}
.minebox{margin-top:14px;font-size:12px}.minebox summary{cursor:pointer;color:var(--dim)}
#view{flex:1;overflow:auto;position:relative;min-width:0}
#detail{width:420px;overflow:auto;border-left:1px solid var(--line);padding:12px 14px;background:var(--panel);display:none}
#detail.open{display:block}.lybadge{font-size:11px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--line);border-radius:4px;padding:0 6px;color:var(--acc)}#detail h2{font-size:16px;margin:0 0 4px}.dim{color:var(--dim)}
table{border-collapse:collapse;width:100%}td,th{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
tr.w:hover{background:var(--hi);cursor:pointer}th{position:sticky;top:0;background:var(--panel);font-size:12px;color:var(--dim)}
.grp{background:var(--bg);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--line);cursor:pointer}
.tag{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 7px;margin:1px 2px;font-size:12px}
.q{border-left:3px solid var(--line);margin:2px 0 8px 2px;padding-left:8px;color:var(--dim);font-size:13px}
#ch{display:flex;height:100%;overflow-x:auto;overflow-y:hidden;padding:8px 10px;gap:10px;align-items:stretch}
.mon{flex:none;width:300px;display:flex;flex-direction:column;border-right:1px solid var(--line);padding-right:10px;min-height:0}
.mon h4{margin:0 0 6px;font-size:14px;position:sticky;top:0;background:var(--bg);padding:2px 0}.mon .col{overflow-y:auto;flex:1}
.card{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:7px 9px;margin-bottom:8px;cursor:pointer;font-size:13px}
.card:hover{outline:2px solid var(--acc)}.card b{display:block;margin:2px 0 3px}.card .qt{color:var(--dim);font-size:12px;margin-top:4px}
.sd{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:2px;vertical-align:middle}
#ln{position:relative;overflow:auto;height:100%}#ln svg{position:absolute;left:0;top:0;pointer-events:none;z-index:2}
.nd{position:absolute;width:176px;height:54px;border:1px solid var(--line);border-left:5px solid var(--acc);background:var(--panel);border-radius:6px;padding:3px 6px;font-size:11.5px;line-height:1.25;overflow:hidden;cursor:pointer}
.nd:hover{outline:2px solid var(--acc);z-index:3}.nd.dim{opacity:.18}.nd.sel{outline:3px solid var(--red);z-index:4}.nd.anc{outline:2px solid var(--red)}.nd.desc{outline:2px solid var(--green)}
.nd .d{color:var(--dim);font-size:10.5px}.mh{position:absolute;top:2px;font-size:12px;font-weight:600;color:var(--dim)}
.sumrow{margin:3px 0}.sumrow b{font-size:12px;color:var(--dim);display:block}
#chips{padding:6px 16px;border-bottom:1px solid var(--line);background:var(--panel)}#chips .chip{margin:0 6px 0 0;border-radius:12px;font-size:12px}#helpbox{padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel);color:var(--dim);font-size:13px;line-height:1.5}#helpbox b{color:var(--ink)}#helpbox li{margin:3px 0}
canvas{display:block;width:100%;height:100%}#tl{padding:10px}
.lane{display:flex;align-items:flex-start;border-bottom:1px solid var(--line);padding:4px 0}.lane b{width:210px;flex:none;font-size:12px;padding-right:8px}
.cells{display:flex;flex:1}.cell{flex:1;min-width:26px;border-left:1px dashed var(--line);padding:0 1px}
.dot{display:block;height:9px;margin:1px 0;border-radius:3px;cursor:pointer;opacity:.9}.dot:hover{outline:2px solid var(--ink)}
.axis{display:flex;margin-left:210px;font-size:11px;color:var(--dim)}.axis div{flex:1;min-width:26px;border-left:1px dashed var(--line);padding-left:2px}
a{color:var(--acc)}.note{padding:8px 12px;color:var(--dim)}
html.panel header,html.panel #side,html.panel #view,html.panel #chips,html.panel #helpbox{display:none!important}
html.panel body{height:auto;min-height:100vh}html.panel main{display:block}
html.panel #detail{display:block;width:100%;border:0;min-height:100vh}html.panel #detail .xbtn{display:none}
.pnl{margin:0 0 6px;font-size:13px}
FUTURE_OVERLAY/*LIGHT*/</style></head><body>
<header><h1>Corpus Explorer</h1>
<input id="q" placeholder="Search title, abstract, quotes…" size="34">
<span class="dim">View</span>
<button data-v="list" class="on">List</button><button data-v="timeline">Timeline</button><button data-v="chrono">Chronology</button><button data-v="lineage">Lineage</button><button data-v="graph">Graph</button>
<span class="dim">Group by</span><select id="grp"></select>
<span class="dim">Sort</span><select id="sortby"><option value="new">Date, newest first</option><option value="old">Date, oldest first</option><option value="cited">Most cited in corpus</option><option value="title">Title A to Z</option></select>
<label class="dim" title="Works of this project whose extracted reference lists resolve to the work. Unknown counts are left out when a number is set.">Cited by <input id="citemin" type="number" min="0" step="1" style="width:64px"> or more corpus works</label>
<span id="exbox" title="Tick works in the list (or select all in the current filter), then download them as files for a notebook tool. Answers produced there are not records." style="display:inline-flex;gap:6px;align-items:center"><button id="exall">Select all in filter</button><button id="exclear">Clear</button><label class="dim"><input type="checkbox" id="expdf"> with PDFs</label><button id="exgo" disabled>Export selected (0)</button><span id="exmsg" class="dim"></span></span><button id="helpbtn">Help</button><!--TOGGLE--><span id="count" class="dim"></span><span class="dim" style="margin-left:auto" id="gen"></span></header>
<div id="chips" hidden></div>
<div id="helpbox" hidden><b>What this is.</b> The corpus of the review: every paper included after full-text screening, with what the miners read from it. Every value shown has a quote from the paper behind it.
<ul><li><b>List</b>: titles by date, grouped by any dimension (Group by). <b>Timeline</b>: one lane per group, one block per paper by month. <b>Chronology</b>: months side by side, newest on the left, a card per paper. <b>Lineage</b>: papers by month with an arrow to each earlier paper in the corpus that they cite; click a paper to light up what it builds on (red) and what builds on it (green). <b>Graph</b>: papers linked to techniques, stages and other categories.</li>
<li><b>Filters</b> (left): tick values to narrow every view; counts are for the whole corpus. <b>Search</b> looks in titles, abstracts and quotes.</li>
<li><b>Click a paper</b> for its detail: the structured summary, classification and stages with the quotes behind them, citations inside the corpus, links to the original, the conversion inspector, and commands to run.</li>
<li>Links from other pages open here already filtered, for example technique multi-agent.</li></ul></div>
<main><div id="side"></div><div id="view"><p class="dim rf-loading" id="rf-loading">Loading corpus…</p></div><div id="detail"></div></main>
<script>
const DATA=/*DATA*/null;
const W=DATA.works,DIMS=DATA.dims.concat([{key:'layer',label:'Layer',src:'meta',field:'layer'}]);const LORD=DATA.layer_order||[];
function lrank(v){if(v==='unlayered'||v==='pending')return [2,0,''];const i=LORD.indexOf(v);return i>=0?[0,i,'']:[1,0,v];}
function lcmp(a,b){const x=lrank(a),y=lrank(b);return x[0]-y[0]||x[1]-y[1]||x[2].localeCompare(y[2]);}
function layerBadge(w){const l=w.layer||'unlayered';const src=w.layer_source==='moved'?' (moved by the researcher'+(w.layer_miner?'; the miner said '+esc(w.layer_miner):'')+')':(w.layer_source==='miner'?' (from the miner)':'');return `<div class="dim">Layer <span class="lybadge">${esc(l)}</span>${src}</div>`;}
const BYS={};W.forEach((w,i)=>BYS[w.slug]=i);const OUT={},INN={};(DATA.cites||[]).forEach(([a,b])=>{(OUT[a]=OUT[a]||[]).push(b);(INN[b]=INN[b]||[]).push(a);});
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function val(w,d){if(d.src==='meta')return w[d.field]||'';const o=w[d.src];return o&&o[d.field]?o[d.field].v:'';}
function stagesOf(w){return [...new Set(w.stages.map(s=>s.stage))];}
const FILT={};let H=new URLSearchParams(location.hash.slice(1));let PANEL=H.get('panel')==='1';document.documentElement.classList.toggle('panel',PANEL);let view=H.get('view')||'list',grp='technique',query=H.get('q')||'',sel=null;let citeMin=parseInt(H.get('cite'),10)||0;let sortBy=['new','old','cited','title'].includes(H.get('sort'))?H.get('sort'):'new';
function wcmp(a,b){const da=a.published||'',db=b.published||'';
 if(sortBy==='title')return a.title.localeCompare(b.title);
 if(sortBy==='cited')return (b.cited_in_corpus||0)-(a.cited_in_corpus||0)||db.localeCompare(da);
 if(!da!==!db)return da?-1:1;
 return sortBy==='old'?da.localeCompare(db):db.localeCompare(da);}
for(const f of H.getAll('f')){const i=f.indexOf(':');if(i>0){const k=f.slice(0,i);(FILT[k]=FILT[k]||new Set()).add(f.slice(i+1));}}
const palette=['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f','#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac','#1f77b4','#d62728','#2ca02c','#9467bd'];
const colorMap={};function colorOf(v){if(!(v in colorMap))colorMap[v]=palette[Object.keys(colorMap).length%palette.length];return colorMap[v];}
function matches(w){
 if(citeMin>0&&(w.cited_in_corpus==null||w.cited_in_corpus<citeMin))return false;
 if(query){const t=(w.title+' '+w.abstract+' '+Object.values(w.cls).map(x=>x.q).join(' ')+' '+Object.values(w.map).map(x=>x.q).join(' ')).toLowerCase();if(!query.toLowerCase().split(/\s+/).every(x=>t.includes(x)))return false;}
 for(const k in FILT){const s=FILT[k];if(!s.size)continue;
  if(k==='stage'){if(!stagesOf(w).some(x=>s.has(x)))return false;}
  else if(k.includes('.')){const[r,f]=k.split('.');const o=(w[r]||{})[f];if(!o||!s.has(o.v))return false;}
  else{const d=DIMS.find(d=>d.key===k);if(!s.has(val(w,d)))return false;}}
 return true;}
function filtered(){return W.filter(matches);}
function drawSide(){
 let h='';
 const dims=DIMS.filter(d=>d.key==='layer').concat(DIMS.filter(d=>d.key!=='year'&&d.key!=='layer'),[{key:'stage',label:'Lifecycle stage'}]);
 for(const d of dims){
  const c={};for(const w of W){const vs=d.key==='stage'?stagesOf(w):[val(w,d)];for(const v of vs)if(v)c[v]=(c[v]||0)+1;}
  const ks=Object.keys(c).sort(d.key==='layer'?lcmp:(a,b)=>c[b]-c[a]);
  h+=`<h3>${esc(d.label)}</h3>`;
  for(const k of ks){const on=FILT[d.key]&&FILT[d.key].has(k);h+=`<label class="f"><input type="checkbox" data-d="${d.key}" data-v="${esc(k)}" ${on?'checked':''}><span style="color:${colorOf(k)}">●</span> ${esc(k)}<span class="n">${c[k]}</span></label>`;}
 }
 $('#side').innerHTML=h+layerSide();
 $('#side').querySelectorAll('input').forEach(i=>i.onchange=()=>{const k=i.dataset.d;FILT[k]=FILT[k]||new Set();i.checked?FILT[k].add(i.dataset.v):FILT[k].delete(i.dataset.v);render();});
}
function docLink(w){return w.doc?`<a href="${esc(w.doc.path)}" target="_blank">Open ${w.doc.kind.toUpperCase()} (on disk)</a>`:'<span class="dim">no document</span>';}
function paperLink(w){return w.doi?`<a href="https://doi.org/${esc(w.doi)}" target="_blank">DOI</a>`:(w.arxiv?`<a href="https://arxiv.org/abs/${esc(w.arxiv)}" target="_blank">arXiv</a>`:'');}
const SUMF=[['problem_gap','Problem and gap'],['core_innovation','Core innovation'],['contribution_type','Contribution type'],['innovation_axis','Novelty is about'],['builds_on','Builds on'],['builds_on_relation','Relation'],['improves_over','Improves over'],['improvement_aspect','Improves'],['benchmark_role','Benchmark'],['benchmark_named','Benchmark named'],['headline_result','Headline result'],['validation_level','Validation'],['claimed_discovery','Claimed discovery'],['failure_modes','Failure modes'],['limitations','Limitations'],['future_work','Future work'],['availability','Availability'],['cost_compute','Cost and compute']];
function sumHtml(w){const s=w.sum||{};if(!Object.keys(s).length)return '<h3>Structured summary</h3><div class="dim">not extracted for this paper yet</div>';
 return '<h3>Structured summary</h3><div class="dim" style="font-size:12px">Sentences quoted from the paper; enum values are backed by a quote.</div>'+SUMF.filter(([k])=>s[k]).map(([k,l])=>{const o=s[k];const isq=o.q&&o.q===o.v.slice(0,o.q.length)||(o.q&&o.v.length>40);return `<div class="sumrow"><b>${esc(l)}</b>${isq||!o.q?esc(o.v):`<span class="tag">${esc(o.v)}</span><div class="q">“${esc(o.q)}” <span class="dim">${esc(o.a)}</span></div>`}${isq&&o.a?` <span class="dim">${esc(o.a)}</span>`:''}</div>`;}).join('');}
const TOKEN=(document.querySelector('meta[name=factory-token]')||{}).content||'';const API=(document.querySelector('meta[name=factory-api]')||{}).content||'';let LAYERS={layers:[],works:{}};
function layerPost(path,body,out){if(!TOKEN){out.textContent='Open this page with factory site serve to use this.';return;}
 out.textContent='sending...';
 fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':TOKEN},body:JSON.stringify(body)})
 .then(r=>r.json().catch(()=>({ok:false,issues:[{field:'response',reason:'status '+r.status}]})))
 .then(r=>{out.textContent=r.ok?'recorded ('+(r.request_id||r.event_id)+')':(r.issues||[]).map(i=>i.field+': '+i.reason).join('; ');})
 .catch(e=>{out.textContent='request failed: '+e;});}
function layerActs(w){const cur=(LAYERS.works[w.id]||{}).layer;
 const opts=LAYERS.layers.map(l=>`<option value="${esc(l)}"${l===cur?' selected':''}>${esc(l)}</option>`).join('');
 return `<h3>Mine and layer</h3><div class="dim" style="font-size:12px">Your acts, recorded under your name. Current layer: ${esc(cur||'pending')}.</div>
 <div id="layact" data-w="${esc(w.id)}" style="margin:4px 0"><input id="layreason" placeholder="reason" style="width:60%"> <button onclick="layerAct('mine-work')">Mine this work</button>
 <br><select id="laysel">${opts}</select> <button onclick="layerAct('move-layer')">Move to layer</button> <span id="layout" class="dim"></span></div>`;}
function layerAct(act){const box=$('#layact'),out=$('#layout'),reason=$('#layreason').value.trim(),w=box.dataset.w;
 if(act==='mine-work')layerPost('/api/mine/work',{work_id:w,reason:reason||null},out);
 else layerPost('/api/layers/move',{work_id:w,layer:$('#laysel').value,reason:reason},out);}
function mineLayer(l,el){layerPost('/api/mine/layer',{layer:l},el.nextElementSibling);}
function layerSide(){if(!LAYERS.layers.length)return '';return '<details class="minebox"><summary>Mining acts (run the layer miner on a whole layer)</summary>'+LAYERS.layers.map(l=>{const n=Object.values(LAYERS.works).filter(x=>x.layer===l).length;return `<div>${esc(l)} <span class="n">${n}</span> <button onclick="mineLayer(this.dataset.l,this)" data-l="${esc(l)}">Mine this layer</button><span class="dim"></span></div>`;}).join('')+'</details>';}
if(TOKEN)fetch(API+'/api/layers').then(r=>r.json()).then(d=>{if(d&&d.layers){LAYERS=d;drawSide();}}).catch(()=>{});
function actionsHtml(w){const P=DATA.project||'PROJECT';const cmds=['factory --project '+P+' document read '+w.id,'factory --project '+P+' trace '+w.id];
 const row=c=>`<div style="display:flex;gap:6px;margin:3px 0"><code style="flex:1;overflow-x:auto;white-space:nowrap;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:2px 6px;font-size:12px">${esc(c)}</code><button onclick="navigator.clipboard.writeText(this.dataset.c)" data-c="${esc(c)}">Copy</button></div>`;
 return `<h3>What you can do</h3><div class="dim" style="font-size:12px">Open the original or its conversion, or run a command in a terminal.</div><div style="margin:4px 0"><a href="../conversion/doc/${esc(w.slug)}.html" target="_blank">Conversion inspector</a> · <a href="../wiki/works/${esc(w.slug)}.md" target="_blank">Wiki note</a></div>${cmds.map(row).join('')}`;}
function cit(w){const o=OUT[w.slug]||[],i=INN[w.slug]||[];const L=(l)=>l.map(s=>`<div><a href="#" onclick="openWork(W[BYS['${s}']]);return false">${esc(W[BYS[s]].title)}</a> <span class="dim">${esc(W[BYS[s]].published)}</span></div>`).join('')||'<div class="dim">none found yet</div>';return `<h3>Citations within the corpus</h3><div class="dim">Reference lists extracted for ${DATA.refs_done} of ${W.length} papers so far.</div><b>Cites</b>${L(o)}<b>Cited by</b>${L(i)}`;}
function panelHead(w){if(!PANEL)return '';const u=location.pathname+'#open='+encodeURIComponent(w.slug);return `<p class="pnl"><a href="${esc(u)}" target="_top">Open in the explorer</a> <span class="lybadge">${esc(w.layer||'unlayered')}</span></p>`;}
function openWork(w){sel=w;const d=$('#detail');d.classList.add('open');
 const row=(o)=>Object.keys(o).map(k=>`<div><b>${esc(k)}</b>: ${esc(o[k].v)}${o[k].q&&o[k].q!==o[k].v?`<div class="q">“${esc(o[k].q)}” <span class="dim">${esc(o[k].a)}</span></div>`:''}</div>`).join('');
 d.innerHTML=`<button class="xbtn" onclick="document.querySelector('#detail').classList.remove('open')" style="float:right">×</button>${panelHead(w)}<h2>${esc(w.title)}</h2>
 <div class="dim">${esc(w.authors.join(', '))} · ${esc(w.published)} · ${esc(w.venue)}${w.cited_by!=null?' · cited by '+w.cited_by:''}</div>
 ${layerBadge(w)}
 <p>${docLink(w)} · ${paperLink(w)}</p>
 <details><summary><b>Abstract</b></summary><p>${esc(w.abstract)||'—'}</p></details>
 ${sumHtml(w)}${cit(w)}<h3>Lifecycle stages</h3>${w.stages.map(s=>`<div><span class="tag" style="border-color:${colorOf(s.stage)}">${esc(s.stage)}</span> <span class="dim">${esc(s.mode)}</span><div class="q">“${esc(s.quote)}” <span class="dim">${esc(s.anchor)}</span></div></div>`).join('')||'<div class="dim">none recorded</div>'}
 <h3>Classification</h3>${row(w.cls)}<h3>Process, human role, blueprint</h3>${row(w.map)}
 <h3>Descriptors</h3>${row(w.desc)}
 <h3>Results (${w.n_design} rows)</h3>${w.design.slice(0,12).map(r=>`<div>${esc(r.system)} · ${esc(r.stage)} · ${esc(r.approach)} <span class="dim">${esc(r.system_role)} ${esc(r.evidence_grade)}</span></div>`).join('')}
 ${actionsHtml(w)}${layerActs(w)} <p class="dim">Evidence: pass A reading by a model, every value quoted from the converted document; second pass on a 10% sample.</p>`;
}
function groups(ws){const d=DIMS.find(d=>d.key===grp);const g={};
 for(const w of ws){const vs=grp==='stage'?stagesOf(w):[val(w,d)||'(none)'];for(const v of (vs.length?vs:['(none)']))(g[v]=g[v]||[]).push(w);}
 return Object.entries(g).sort((a,b)=>grp==='year'?(sortBy==='old'?a[0].localeCompare(b[0]):b[0].localeCompare(a[0])):b[1].length-a[1].length);}
const SELX=new Set();
const EXCAP=200;let NF=0;
function exUpdate(){const n=SELX.size,b=$('#exgo'),m=$('#exmsg'),a=$('#exall');b.textContent='Export selected ('+n+')';
 const over=n>EXCAP;b.disabled=!n||!TOKEN||over;b.title=TOKEN?'':'Open this page with factory site serve to export.';
 a.title=NF>EXCAP?NF+' works are in this filter; an export takes at most '+EXCAP+'. Narrow the filter first.':'';
 if(over)m.textContent=n+' works selected; an export takes at most '+EXCAP+'. Clear some or narrow the filter.';else if(m.textContent.indexOf('at most')>=0)m.textContent='';}
function exFilename(r){const m=/filename="([^"]+)"/.exec(r.headers.get('Content-Disposition')||'');return m?m[1]:'works-export.zip';}
function exGo(){const out=$('#exmsg');if(!TOKEN||!SELX.size)return;out.textContent='preparing...';$('#exgo').disabled=true;
 fetch(API+'/api/export/works',{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':TOKEN},body:JSON.stringify({work_ids:[...SELX],pdfs:$('#expdf').checked,confirm:$('#expdf').checked&&confirm('The PDFs are licensed files. Copy them out of the library into the download?')})})
 .then(r=>{if(r.ok&&(r.headers.get('Content-Type')||'').startsWith('application/zip'))return r.blob().then(b=>{const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=exFilename(r);document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),10000);out.textContent='downloaded; see MANIFEST.md for skipped works';});
  return r.json().catch(()=>({issues:[{field:'response',reason:'status '+r.status}]})).then(j=>{out.textContent=(j.issues||[]).map(i=>i.field+': '+i.reason).join('; ');});})
 .catch(e=>{out.textContent='failed: '+e;}).finally(exUpdate);}
function renderList(ws){let h='<table><tr><th></th><th>Published</th><th>Title</th><th>Cited in corpus</th><th>Technique</th><th>Field</th><th>Human</th><th>Stages</th></tr>';
 for(const [g,l] of groups(ws)){h+=`<tr><td colspan="8" class="grp">${esc(g)} <span class="dim">(${l.length})</span></td></tr>`;
  for(const w of l.sort(wcmp))h+=`<tr class="w" data-i="${W.indexOf(w)}"><td><input type="checkbox" class="xs" data-id="${esc(w.id)}" ${SELX.has(w.id)?'checked':''} title="Select for export"></td><td>${esc(w.published)}</td><td>${esc(w.title)}</td><td>${w.cited_in_corpus==null?'—':w.cited_in_corpus}</td><td>${esc(val(w,DIMS[0]))}</td><td>${esc(val(w,DIMS[1]))}</td><td>${esc(val(w,DIMS[5]))}</td><td>${stagesOf(w).map(s=>`<span class="tag">${esc(s)}</span>`).join('')}</td></tr>`;}
 $('#view').innerHTML=h+'</table>';$('#view').querySelectorAll('tr.w').forEach(r=>r.onclick=()=>openWork(W[+r.dataset.i]));$('#view').querySelectorAll('input.xs').forEach(c=>{c.onclick=e=>e.stopPropagation();c.onchange=()=>{c.checked?SELX.add(c.dataset.id):SELX.delete(c.dataset.id);exUpdate();};});}
function renderTimeline(ws){const months=[...new Set(W.map(w=>w.month).filter(Boolean))].sort();
 const d=DIMS.find(d=>d.key===grp)||DIMS[0];
 let h=`<div id="tl"><div class="axis">${months.map(m=>`<div>${m.slice(2)}</div>`).join('')}</div>`;
 for(const [g,l] of groups(ws)){const by={};for(const w of l)(by[w.month]=by[w.month]||[]).push(w);
  h+=`<div class="lane"><b>${esc(g)} <span class="dim">${l.length}</span></b><div class="cells">${months.map(m=>`<div class="cell">${(by[m]||[]).map(w=>`<span class="dot" title="${esc(w.title)}" data-i="${W.indexOf(w)}" style="background:${colorOf(val(w,DIMS[0])||g)}"></span>`).join('')}</div>`).join('')}</div></div>`;}
 $('#view').innerHTML=h+'</div>';$('#view').querySelectorAll('.dot').forEach(r=>r.onclick=()=>openWork(W[+r.dataset.i]));}
function renderChrono(ws){const months=[...new Set(ws.map(w=>w.month).filter(Boolean))].sort();if(CH.newest)months.reverse();
 const by={};for(const w of ws)(by[w.month]=by[w.month]||[]).push(w);
 let h=`<div style="padding:6px 12px" class="dim">Horizontal chronology, ${CH.newest?'newest on the left, scroll right to go back in time':'oldest on the left'}. <button onclick="CH.newest=!CH.newest;render()">Reverse order</button> Dots = lifecycle stages covered; colour = primary technique.</div><div id="ch" style="height:calc(100% - 34px)">`;
 for(const m of months){const l=by[m].sort(wcmp);
  h+=`<div class="mon"><h4>${esc(m)} <span class="dim">(${l.length})</span></h4><div class="col">`+l.map(w=>{const c=w.desc.contribution;const qt=c&&c.q?c.q:(w.cls.technique_primary?w.cls.technique_primary.q:'');
   return `<div class="card" data-i="${W.indexOf(w)}"><span class="dim">${esc(w.published)}</span><b>${esc(w.title)}</b>`+
   `<span class="tag" style="border-color:${colorOf(val(w,DIMS[0]))}">${esc(val(w,DIMS[0]))}</span><span class="tag">${esc(val(w,DIMS[1]))}</span><span class="tag">${esc(val(w,DIMS[5]))}</span><div>${stagesOf(w).map(s=>`<span class="sd" title="${esc(s)}" style="background:${colorOf(s)}"></span>`).join('')}</div>`+
   ((OUT[w.slug]||[]).length||(INN[w.slug]||[]).length?`<div class="dim">cites ${(OUT[w.slug]||[]).length} · cited by ${(INN[w.slug]||[]).length} in corpus</div>`:'')+(qt?`<div class="qt">“${esc(qt.slice(0,200))}”</div>`:'')+(w.doc?`<div><a href="${esc(w.doc.path)}" target="_blank" onclick="event.stopPropagation()">Open ${w.doc.kind.toUpperCase()}</a></div>`:'')+`</div>`;}).join('')+`</div></div>`;}
 $('#view').innerHTML=h+'</div>';$('#view').querySelectorAll('.card').forEach(r=>r.onclick=()=>openWork(W[+r.dataset.i]));}
function renderLineage(ws){const inSet=new Set(ws.map(w=>w.slug));const edges=(DATA.cites||[]).filter(([a,b])=>inSet.has(a)&&inSet.has(b));
 const linked=new Set();edges.forEach(([a,b])=>{linked.add(a);linked.add(b);});
 const list=(LN.all?ws:ws.filter(w=>linked.has(w.slug)));
 const months=[...new Set(list.map(w=>w.month).filter(Boolean))].sort().reverse();const col={};months.forEach((m,i)=>col[m]=i);
 const by={};for(const w of list)(by[w.month]=by[w.month]||[]).push(w);
 const pos={};let maxRows=0;const CW=196,RH=62,TOP=26;
 for(const m of months){by[m].sort((a,b)=>b.published.localeCompare(a.published)).forEach((w,i)=>{pos[w.slug]={x:col[m]*CW+8,y:TOP+i*RH};});maxRows=Math.max(maxRows,by[m].length);}
 const Wd=months.length*CW+20,Ht=TOP+maxRows*RH+20;
 let h=`<div style="padding:6px 12px" class="dim">Lineage: papers by month, newest on the left; an arrow runs from a paper to each earlier paper in the corpus it cites. Click a paper: red = what it builds on (ancestors), green = what builds on it. ${linked.size} papers have at least one citation link here (${edges.length} links). <label><input type="checkbox" ${LN.all?'checked':''} onchange="LN.all=this.checked;render()"> show papers without links</label></div><div id="ln" style="height:calc(100% - 52px)"><div style="position:relative;width:${Wd}px;height:${Ht}px"><svg width="${Wd}" height="${Ht}"></svg>`;
 h+=months.map(m=>`<div class="mh" style="left:${col[m]*CW+8}px">${esc(m)} (${by[m].length})</div>`).join('');
 h+=list.map(w=>{const p=pos[w.slug];const c=colorOf(val(w,DIMS[0]));const bo=w.sum&&w.sum.builds_on?` · builds on: ${w.sum.builds_on.v}`:'';return `<div class="nd" data-s="${esc(w.slug)}" title="${esc(w.title+bo)}" style="left:${p.x}px;top:${p.y}px;border-left-color:${c}"><div class="d">${esc(w.published)} · ${esc(val(w,DIMS[0]))}</div>${esc(w.title.slice(0,70))}</div>`;}).join('')+'</div></div>';
 $('#view').innerHTML=h;const svg=$('#ln svg');
 const path=(a,b,cls)=>{const pa=pos[a],pb=pos[b];if(!pa||!pb)return '';const x1=pa.x+176,y1=pa.y+27,x2=pb.x,y2=pb.y+27;const dx=Math.max(30,Math.abs(x2-x1)/2);
  const d=pb.x>pa.x?`M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`:`M${x1},${y1} C${x1+60},${y1-30} ${x1+60},${y2+30} ${pb.x+176},${y2}`;return `<path d="${d}" fill="none" class="${cls}" data-a="${esc(a)}" data-b="${esc(b)}" stroke="${cls==='hl'?'#d33':'rgba(90,100,130,.5)'}" stroke-width="${cls==='hl'?2.4:1.2}"/>`;};
 const drawLines=(hl)=>{svg.innerHTML=edges.filter(([a,b])=>pos[a]&&pos[b]).map(([a,b])=>path(a,b,hl&&hl.has(a+'>'+b)?'hl':'')).join('');};
 drawLines(null);
 const chain=(s)=>{const anc=new Set(),desc=new Set(),he=new Set();const up=[s];while(up.length){const x=up.pop();for(const y of OUT[x]||[])if(!anc.has(y)){anc.add(y);he.add(x+'>'+y);up.push(y);}else he.add(x+'>'+y);}
  const dn=[s];while(dn.length){const x=dn.pop();for(const y of INN[x]||[])if(!desc.has(y)){desc.add(y);he.add(y+'>'+x);dn.push(y);}else he.add(y+'>'+x);}return {anc,desc,he};};
 $('#ln').querySelectorAll('.nd').forEach(n=>n.onclick=()=>{const s=n.dataset.s;const c=chain(s);
  $('#ln').querySelectorAll('.nd').forEach(m=>{const k=m.dataset.s;m.classList.remove('sel','anc','desc','dim');if(k===s)m.classList.add('sel');else if(c.anc.has(k))m.classList.add('anc');else if(c.desc.has(k))m.classList.add('desc');else m.classList.add('dim');});
  drawLines(c.he);openWork(W[BYS[s]]);});}
const LN={all:false};
const CH={newest:true};
// --- graph: works linked to the categories they were placed in
let sim=null;const GD=new Set(['technique','stage','cites']);
function renderGraph(ws){const v=$('#view');v.innerHTML='<canvas></canvas><div class="note" style="position:absolute;left:8px;top:4px;background:var(--panel);border:1px solid var(--line);border-radius:6px">Links: '+['technique','field','human','stage','cites'].map(k=>`<label style="margin-right:8px"><input type="checkbox" data-g="${k}" ${GD.has(k)?'checked':''}> ${k}</label>`).join('')+' <span class="dim">drag, scroll to zoom, click a work</span></div>';v.querySelectorAll('input[data-g]').forEach(i=>i.onchange=()=>{i.checked?GD.add(i.dataset.g):GD.delete(i.dataset.g);render();});
 const cv=v.querySelector('canvas');const dpr=window.devicePixelRatio||1;cv.width=v.clientWidth*dpr;cv.height=v.clientHeight*dpr;const g=cv.getContext('2d');
 const nodes=[],idx={},edges=[];
 function node(k,o){if(!(k in idx)){idx[k]=nodes.length;nodes.push(Object.assign({k,x:Math.random()*600-300,y:Math.random()*400-200,vx:0,vy:0,deg:0},o));}return idx[k];}
 const cedges=[];const catDims=[['technique',DIMS[0]],['field',DIMS[1]],['human',DIMS[5]]];
 for(const w of ws){const a=node('w:'+w.id,{w,r:3});
  for(const [n,d] of catDims){const v2=GD.has(n)?val(w,d):'';if(v2){const b=node(n+':'+v2,{label:v2,cat:n,r:6});edges.push([a,b]);nodes[b].deg++;}}
  for(const s of (GD.has('stage')?stagesOf(w):[])){const b=node('stage:'+s,{label:s,cat:'stage',r:6});edges.push([a,b]);nodes[b].deg++;}}
 if(GD.has('cites'))for(const [a,b] of (DATA.cites||[])){const wa=W[BYS[a]],wb=W[BYS[b]];if(wa&&wb&&('w:'+wa.id) in idx&&('w:'+wb.id) in idx)cedges.push([idx['w:'+wa.id],idx['w:'+wb.id]]);}
 for(const n of nodes)if(n.cat)n.r=5+Math.sqrt(n.deg)*1.6;
 let cam={x:0,y:0,z:0.9},drag=null,hover=null;
 const catCol={technique:'#e15759',field:'#59a14f',human:'#b07aa1',stage:'#f28e2b'};
 let it=0;const step=()=>{const a=Math.max(0.02,1-it/400);it++;
  for(let i=0;i<nodes.length;i++){const p=nodes[i];for(let j=i+1;j<nodes.length;j++){const q=nodes[j];let dx=p.x-q.x,dy=p.y-q.y,d2=dx*dx+dy*dy+0.1;if(d2>250000)continue;const f=(p.cat&&q.cat?9000:(p.cat||q.cat?1800:220))/d2;p.vx+=dx*f;p.vy+=dy*f;q.vx-=dx*f;q.vy-=dy*f;}}
  for(const [i,j] of edges){const p=nodes[i],q=nodes[j];const dx=q.x-p.x,dy=q.y-p.y;const dist=Math.sqrt(dx*dx+dy*dy)+0.01;const L=28+Math.sqrt(q.deg||1)*9;const f=0.02*(dist-L)/dist;p.vx+=dx*f;p.vy+=dy*f;q.vx-=dx*f;q.vy-=dy*f;}
  for(const [i,j] of cedges){const p=nodes[i],q=nodes[j];const dx=q.x-p.x,dy=q.y-p.y;const dist=Math.sqrt(dx*dx+dy*dy)+0.01;const f=0.05*(dist-45)/dist;p.vx+=dx*f;p.vy+=dy*f;q.vx-=dx*f;q.vy-=dy*f;}
  for(const p of nodes){p.vx-=p.x*0.0012;p.vy-=p.y*0.0012;if(p!==drag){p.x+=p.vx*a*0.5;p.y+=p.vy*a*0.5;}p.vx*=0.6;p.vy*=0.6;}};
 const draw=()=>{g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,cv.width,cv.height);g.translate(cv.width/dpr/2+cam.x,cv.height/dpr/2+cam.y);g.scale(cam.z,cam.z);
  g.strokeStyle='rgba(120,130,150,.10)';g.lineWidth=1/cam.z;g.beginPath();for(const [i,j] of edges){g.moveTo(nodes[i].x,nodes[i].y);g.lineTo(nodes[j].x,nodes[j].y);}g.stroke();
  g.strokeStyle='rgba(220,60,60,.8)';g.lineWidth=1.6/cam.z;for(const [i,j] of cedges){const p=nodes[i],q=nodes[j];g.beginPath();g.moveTo(p.x,p.y);g.lineTo(q.x,q.y);g.stroke();const ang=Math.atan2(q.y-p.y,q.x-p.x),s=6/cam.z;g.beginPath();g.moveTo(q.x-Math.cos(ang)*q.r,q.y-Math.sin(ang)*q.r);g.lineTo(q.x-Math.cos(ang)*(q.r+s)+Math.sin(ang)*s/2,q.y-Math.sin(ang)*(q.r+s)-Math.cos(ang)*s/2);g.lineTo(q.x-Math.cos(ang)*(q.r+s)-Math.sin(ang)*s/2,q.y-Math.sin(ang)*(q.r+s)+Math.cos(ang)*s/2);g.closePath();g.fillStyle='rgba(220,60,60,.9)';g.fill();}
  for(const n of nodes){g.beginPath();g.arc(n.x,n.y,n.r,0,7);g.fillStyle=n.cat?catCol[n.cat]:colorOf(val(n.w,DIMS[0])||'x');g.globalAlpha=n===hover||(sel&&n.w===sel)?1:.85;g.fill();g.globalAlpha=1;if(sel&&n.w===sel){g.lineWidth=2/cam.z;g.strokeStyle='#ddf7ff';g.stroke();}}
  g.fillStyle=getComputedStyle(document.body).color;g.font=(11/cam.z)+'px system-ui';
  for(const n of nodes)if(n.cat||n===hover)g.fillText(n.label||n.w.title.slice(0,70),n.x+n.r+2,n.y+3);};
 const loop=()=>{if(!document.body.contains(cv))return;step();draw();requestAnimationFrame(loop);};loop();
 const pos=e=>{const r=cv.getBoundingClientRect();return [(e.clientX-r.left-r.width/2-cam.x)/cam.z,(e.clientY-r.top-r.height/2-cam.y)/cam.z];};
 const pick=e=>{const [x,y]=pos(e);let b=null,bd=1e9;for(const n of nodes){const d=(n.x-x)**2+(n.y-y)**2;if(d<(n.r+4)**2&&d<bd){b=n;bd=d;}}return b;};
 cv.onmousedown=e=>{const n=pick(e);if(n){drag=n;it=Math.min(it,300);}else drag={pan:true,sx:e.clientX,sy:e.clientY,cx:cam.x,cy:cam.y};};
 cv.onmousemove=e=>{if(drag&&drag.pan){cam.x=drag.cx+e.clientX-drag.sx;cam.y=drag.cy+e.clientY-drag.sy;}else if(drag){[drag.x,drag.y]=pos(e);}else hover=pick(e);};
 cv.onmouseup=e=>{const n=pick(e);if(drag&&!drag.pan&&n===drag&&n.w)openWork(n.w);drag=null;};
 cv.onwheel=e=>{e.preventDefault();cam.z=Math.min(4,Math.max(.2,cam.z*(e.deltaY<0?1.1:.9)));};}
function drawChips(){const c=$('#chips');c.replaceChildren();let n=0;
 for(const k in FILT)for(const v of FILT[k]){n++;const b=document.createElement('button');b.className='chip';b.textContent=k.replace('.',' / ')+': '+v+'  \u00d7';b.title='remove this filter';b.onclick=()=>{FILT[k].delete(v);drawSide();render();};c.append(b);}
 if(citeMin>0){n++;const b=document.createElement('button');b.className='chip';b.textContent='cited by '+citeMin+' or more corpus works  \u00d7';b.onclick=()=>{citeMin=0;$('#citemin').value='';render();};c.append(b);}
 if(query){n++;const b=document.createElement('button');b.className='chip';b.textContent='search: '+query+'  \u00d7';b.onclick=()=>{query='';$('#q').value='';render();};c.append(b);}
 c.hidden=!n;}
function render(){const ws=filtered();NF=ws.length;exUpdate();drawChips();$('#count').textContent=ws.length+' of '+W.length+' works';
 if(view==='list')renderList(ws);else if(view==='timeline')renderTimeline(ws);else if(view==='chrono')renderChrono(ws);else if(view==='lineage')renderLineage(ws);else renderGraph(ws);}
document.querySelectorAll('header button[data-v]').forEach(b=>b.onclick=()=>{view=b.dataset.v;document.querySelectorAll('header button[data-v]').forEach(x=>x.classList.toggle('on',x===b));render();});
const gs=$('#grp');for(const d of DIMS.concat([{key:'stage',label:'Lifecycle stage'}]))gs.insertAdjacentHTML('beforeend',`<option value="${d.key}">${esc(d.label)}</option>`);
gs.onchange=()=>{grp=gs.value;render();};const sb=$('#sortby');sb.value=sortBy;sb.onchange=()=>{sortBy=sb.value;render();};$('#helpbtn').onclick=()=>{const b=$('#helpbox');b.hidden=!b.hidden;};if(query)$('#q').value=query;$('#q').oninput=e=>{query=e.target.value;render();};
$('#citemin').value=citeMin||'';$('#citemin').closest('label').title='Counts only works whose reference lists were extracted ('+DATA.refs_done+' of '+W.length+'); a work whose citers were never extracted shows 0 or a dash, not a known zero.';$('#citemin').oninput=e=>{citeMin=parseInt(e.target.value,10)||0;render();};$('#gen').textContent='Generated '+DATA.generated;document.querySelectorAll('header button[data-v]').forEach(x=>x.classList.toggle('on',x.dataset.v===view));if(H.get('grp')){grp=H.get('grp');gs.value=grp;}drawSide();render();if(H.get('open')&&BYS[H.get('open')]!==undefined)openWork(W[BYS[H.get('open')]]);else if(H.get('openfirst')){const w=W.find(x=>x.sum&&Object.keys(x.sum).length>6);if(w)openWork(w);}
$('#exall').onclick=()=>{const f=filtered();if(f.length>EXCAP&&!confirm(f.length+' works are in this filter; an export takes at most '+EXCAP+'. Select them anyway? (Export will stay disabled until you narrow the selection.)'))return;f.forEach(w=>SELX.add(w.id));exUpdate();render();};$('#exclear').onclick=()=>{SELX.clear();exUpdate();render();};$('#exgo').onclick=exGo;exUpdate();if(PANEL)$('#exbox').hidden=true;
addEventListener('keydown',e=>{if(e.key==='Escape'&&PANEL&&parent!==window)parent.postMessage('rfp-close',location.origin);});
addEventListener('hashchange',()=>{H=new URLSearchParams(location.hash.slice(1));PANEL=H.get('panel')==='1';document.documentElement.classList.toggle('panel',PANEL);const o=H.get('open');if(o&&BYS[o]!==undefined)openWork(W[BYS[o]]);});
</script></body></html>
"""

PAGE = (
    PAGE.replace("<!--THEME-->", THEME_SCRIPT)
    .replace("/*LIGHT*/", LIGHT_CSS)
    .replace("<!--TOGGLE-->", THEME_TOGGLE)
)
