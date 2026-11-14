# ruff: noqa: E501
"""The Search and deduplication page: one HTML string, inline CSS and JS, no external resource.

`PAGE` carries a `/*DATA*/null` marker that `site_search` replaces with the payload. The palette
and theme follow the flow page.
"""

from __future__ import annotations

from factory.services.site_theme import LIGHT_CSS, THEME_SCRIPT, THEME_TOGGLE

DATA_MARKER = "/*DATA*/null"

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<!--THEME-->
<title>Search and deduplication</title>
<style>
:root{color-scheme:dark;--bg:#0B0C16;--panel:#151828;--ink:#ddf7ff;--dim:#6a6e95;--line:#2d3450;--acc:#82FB9C;--red:#ff8a80;--green:#4fe88f;--hi:#1f253a}
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
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}
details{margin:2px 0}details summary{cursor:pointer;color:var(--dim)}
.q{border:1px solid var(--line);border-radius:6px;margin:10px 0;padding:8px 12px;background:var(--panel)}
.q h3{margin:0 0 4px;font-size:14px}.q code{background:var(--hi);padding:1px 5px;border-radius:4px;word-break:break-word}
.tag{display:inline-block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--bg);background:var(--acc);padding:0 6px;border-radius:4px;margin-right:6px}
.tag.rev{background:var(--red)}
FUTURE_OVERLAY/*LIGHT*/</style></head><body>
<header><h1>Search and deduplication</h1><!--TOGGLE--><span class="dim" style="margin-left:auto" id="gen"></span></header>
<main>
<h2>Searches</h2>
<p class="dim">Each registered query with its runs. The gap is the total the source reported less the records retrieved; records of an archived page that did not become works are listed under their query.</p>
<div id="err"></div><div id="queries"></div>
<h2>Deduplication</h2>
<div id="rules"></div>
<div class="bar"><input id="q" placeholder="Search titles, ids…" size="30"><select id="fr"></select><select id="fs"></select><button id="clear">Clear filters</button><span id="count" class="dim"></span></div>
<div style="overflow:auto"><table><thead><tr><th>merge</th><th>status</th><th>rule</th><th class="n">records</th><th>primary</th><th>absorbed</th></tr></thead><tbody id="merges"></tbody></table></div>
<p><button id="more" hidden>Show more</button></p>
<h2>Merged after screening</h2>
<p class="dim" id="anote"></p><div id="after"></div>
</main>
<script>
const DATA=/*DATA*/null;
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NOTE=160;
$('#gen').textContent=DATA.project+' · '+DATA.generated;
function note(t){if(!t)return '';return t.length<=NOTE?esc(t):'<details><summary>'+esc(t.slice(0,NOTE))+'…</summary>'+esc(t)+'</details>';}
function drawQueries(){
 if(DATA.error)$('#err').innerHTML='<p class="red">The archived search pages could not be read: '+esc(DATA.error)+'</p>';
 if(!DATA.queries.length){$('#queries').innerHTML='<p class="dim">No searches registered.</p>';return;}
 $('#queries').innerHTML=DATA.queries.map(q=>{
  const f=Object.entries(q.filters).map(([k,v])=>esc(k)+'='+esc(v)).join(', ')||'none';
  let h='<div class="q"><h3>'+esc(q.id)+' <span class="dim">· '+esc(q.source)+' · '+esc(q.kind)+' · '+esc(q.purpose)+' · '+esc(q.at)+'</span></h3>'+
   '<div><code>'+esc(q.text)+'</code></div><div class="dim">filters: '+f+(q.round?' · round '+esc(q.round):'')+'</div>'+
   '<div>reported <b>'+esc(q.reported==null?'not reported':q.reported)+'</b> · retrieved <b>'+q.retrieved+'</b> · gap <b class="'+(q.gap?'red':'')+'">'+esc(q.gap==null?'n/a':q.gap)+'</b>'+(q.shortfall?' · shortfall: '+note(q.shortfall):'')+'</div>';
  h+='<table><thead><tr><th>run</th><th>status</th><th class="n">reported</th><th class="n">retrieved</th><th class="n">skipped</th><th class="n">new works</th><th class="n">pages</th><th>note</th></tr></thead><tbody>'+
   q.runs.map(r=>'<tr><td>'+esc(r.id)+'</td><td>'+esc(r.status)+'</td><td class="n">'+esc(r.rep==null?'':r.rep)+'</td><td class="n">'+r.got+'</td><td class="n">'+r.skip+'</td><td class="n">'+r.new+'</td><td class="n">'+r.pages+'</td><td>'+note(r.note)+'</td></tr>').join('')+'</tbody></table>';
  if(q.skipped.length)h+='<details><summary>'+q.skipped.length+' skipped records</summary><table><thead><tr><th>reason</th><th>run</th><th>native id</th><th>title</th></tr></thead><tbody>'+q.skipped.slice(0,1000).map(s=>'<tr><td>'+esc(s[3])+'</td><td>'+esc(s[0])+'</td><td>'+esc(s[1])+'</td><td>'+esc(s[2])+'</td></tr>').join('')+'</tbody></table>'+(q.skipped.length>1000?'<p class="dim">The first 1000 are shown.</p>':'')+'</details>';
  return h+'</div>';}).join('');}
const M=DATA.merges;let SHOWN=300;const F={q:'',r:'',s:''};
function drawRules(){const R=DATA.rule_counts,keys=Object.keys(R);
 $('#rules').innerHTML=keys.length?'<table><thead><tr><th>rule</th><th class="n">active</th><th class="n">reverted</th></tr></thead><tbody>'+keys.map(k=>'<tr><td>'+esc(k)+'</td><td class="n">'+(R[k].active||0)+'</td><td class="n">'+(R[k].reverted||0)+'</td></tr>').join('')+'</tbody></table>':'<p class="dim">No merges recorded.</p>';
 $('#fr').innerHTML='<option value="">Rule: all</option>'+keys.map(k=>'<option>'+esc(k)+'</option>').join('');
 $('#fs').innerHTML='<option value="">Status: all</option><option>active</option><option>reverted</option>';}
function render(){const q=F.q.toLowerCase();
 const rows=M.filter(m=>(!F.r||m.rule===F.r)&&(!F.s||m.status===F.s)&&(!q||(m.id+' '+m.primary+' '+m.pt+' '+m.absorbed.map(a=>a.join(' ')).join(' ')).toLowerCase().includes(q)));
 $('#count').textContent=rows.length+' of '+M.length+' merges';
 $('#merges').innerHTML=rows.slice(0,SHOWN).map(m=>'<tr><td>'+esc(m.id)+'</td><td><span class="tag'+(m.status==='reverted'?' rev':'')+'">'+esc(m.status)+'</span>'+(m.reason?'<div class="dim">'+note(m.reason)+'</div>':'')+'</td><td>'+esc(m.rule)+'</td><td class="n">'+m.records+'</td><td>'+esc(m.pt||m.primary)+'<div class="dim">'+esc(m.primary)+'</div></td><td>'+m.absorbed.map(a=>esc(a[1]||a[0])+' <span class="dim">'+esc(a[0])+'</span>').join('<br>')+'</td></tr>').join('');
 $('#more').hidden=rows.length<=SHOWN;}
$('#more').onclick=()=>{SHOWN+=300;render();};
$('#q').oninput=e=>{F.q=e.target.value;SHOWN=300;render();};
$('#fr').onchange=e=>{F.r=e.target.value;SHOWN=300;render();};
$('#fs').onchange=e=>{F.s=e.target.value;SHOWN=300;render();};
$('#clear').onclick=()=>{F.q=F.r=F.s='';$('#q').value='';$('#fr').value='';$('#fs').value='';SHOWN=300;render();};
function drawAfter(){$('#anote').textContent=DATA.after_note;const A=DATA.after;
 $('#after').innerHTML=A.length?'<table><thead><tr><th>merge</th><th>rule</th><th>primary (kept)</th><th>outcome</th><th>absorbed</th><th>outcome</th></tr></thead><tbody>'+A.map(a=>'<tr><td>'+esc(a[0])+'</td><td>'+esc(a[1])+'</td><td>'+esc(a[3]||a[2])+'</td><td>'+esc(a[4])+'</td><td>'+esc(a[6]||a[5])+'</td><td>'+esc(a[7])+'</td></tr>').join('')+'</tbody></table>':'<p class="dim">None.</p>';}
drawQueries();drawRules();render();drawAfter();
</script></body></html>
"""

PAGE = (
    PAGE.replace("<!--THEME-->", THEME_SCRIPT)
    .replace("/*LIGHT*/", LIGHT_CSS)
    .replace("<!--TOGGLE-->", THEME_TOGGLE)
)
