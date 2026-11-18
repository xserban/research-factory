/* Research hub shared shell (ported from the round-2 demo). Served from /p/<slug>/ui/assets/shell.js.
   Page scripts call HUB.init(payload) once, then HUB.mount({page, crumb}). Nothing is read from
   globals at load time. Payload: {slug, generated, prisma, works, cites}. */
(function(){
let RF = null, P = {}, byId = new Map(), citesOut = new Map(), citesIn = new Map(), stats = {}, SETS_NOTE = '';
const $ = (s, r=document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => Number(n).toLocaleString('en-GB');
const pct = (a,b) => b ? Math.round(100*a/b) : 0;

/* ---------- vocabulary (one term per concept) ---------- */
const HUMAN = [ // ordinal: least to most human involvement
  ['none','No human in the loop','--h-none'],
  ['sets-goal','Human sets the goal','--h-goal'],
  ['reviews-or-approves','Human reviews or approves','--h-review'],
  ['expert-feedback-in-loop','Expert feedback in the loop','--h-feedback'],
  ['collaborator','Human as collaborator','--h-collab'],
  ['runs-physical-steps','Human runs physical steps','--h-physical'],
];
const LAYERS = [
  ['core','Core','--l-core'],['benchmark','Benchmark','--l-benchmark'],['applied','Applied','--l-applied'],
  ['adjacent','Adjacent','--l-adjacent'],['background','Background','--l-background'],['off-topic','Off-topic','--l-off'],['unlayered','Unlayered','--l-unlayered'],
];
const FIELDS = [['technique','Technique'],['architecture','Architecture'],['span','Automated span'],['human','Human role']];
const humanLabel = v => (HUMAN.find(h=>h[0]===v)||[,v==null?'Not coded':pretty(v)])[1];
const layerLabel = v => (LAYERS.find(l=>l[0]===v)||[,v])[1];
const LABELS = {
  'multi-agent':'Multi-agent','retrieval-grounding':'Retrieval / grounding','iterative-loop':'Iterative loop','tree-search':'Tree search',
  'code-execution-tools':'Code execution & tools','evolutionary-search':'Evolutionary search','training-finetuning-rl':'Training / fine-tuning / RL',
  'memory-skills':'Memory & skills','prompting-single-llm':'Prompting a single LLM','symbolic-regression':'Symbolic regression','formal-verification':'Formal verification',
  'staged-pipeline':'Staged pipeline','multi-agent-roles':'Multi-agent roles','hierarchical':'Hierarchical','interactive-copilot':'Interactive copilot',
  'environment-sandbox':'Environment / sandbox','tool-integration':'Tool integration','single-agent':'Single agent',
  'experiment-to-analysis':'Experiment → analysis','ideation-to-experiment':'Ideation → experiment','not-determinable':'Not determinable',
  'single-component':'Single component','full-lifecycle':'Full lifecycle','other':'Other',
};
/* Human label for a coded value: the shared map first, then a careful fallback that keeps compound words readable. */
const pretty = v => v==null||v==='' ? 'Not coded' : (LABELS[v] || String(v).replace(/-to-/g,' → ').replace(/-/g,' ').replace(/^./,c=>c.toUpperCase()));
const cssv = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const humanColor = v => cssv((HUMAN.find(h=>h[0]===v)||[,,'--h-null'])[2]);
const layerColor = v => cssv((LAYERS.find(l=>l[0]===v)||[,,'--l-unlayered'])[2]);
const val = (w,f) => (w[f] && w[f].v) || null;
const quote = (w,f) => (w[f] && w[f].q) || '';

/* ---------- computed facts (never typed) ---------- */
const sum = o => Object.values(o||{}).reduce((a,b)=>a+b,0);

/* ---------- glossary: plain definitions behind dotted terms ---------- */
const GLOSSARY = {
  included:['Included','A paper that passed every screening step: title and abstract, then full text. These are the papers the review is about.'],
  mined:['Read in full','A paper whose full text a miner has read and recorded fields for, each with the sentence it was based on. Nearly the same set as the included papers.'],
  miner:['Miner','An extraction agent that reads a paper and records set fields (technique, human role, …), each with a quotation from the paper. A miner records; it does not judge inclusion.'],
  layer:['Layer','How central a paper is to the question. Core: builds an AI scientist. Benchmark: tests one. Applied: uses one in a field. Adjacent and background: related work.'],
  human:['Human role','What part a person plays in the system, from none (fully automated) to running the physical lab steps.'],
  technique:['Technique','The main method the system uses: several cooperating agents, an iterative loop, tree search, retrieval, and so on.'],
  architecture:['Architecture','How the system is organised: roles for several agents, a staged pipeline, a hierarchy, tool use, a sandbox.'],
  span:['Automated span','Which part of the research cycle the system automates on its own, from a single component to the full cycle.'],
  cic:['Cited here','How many other papers in this review cite it. A measure of influence inside the corpus, not worldwide citations.'],
  quote:['Evidence','The sentence from the paper that the miner used to set a value. Every value carries one.'],
  prisma:['PRISMA flow','The standard way to report a systematic review: how many records were found, removed, screened, excluded (and why) and included.'],
  screened:['Screened','Records checked against the inclusion criteria, first on title and abstract, then on the full text.'],
  duplicates:['Duplicates','The same paper found more than once (in arXiv and OpenAlex, or as two versions). Kept once.'],
  cap:['Rapid-review cap','To keep the review feasible, full texts were sought only for the highest-ranked records; the rest are reported as not sought, not as excluded.'],
  notretrieved:['Not retrieved','A full text was sought but no copy could be obtained (no open-access PDF, no arXiv source).'],
  criteria:['Exclusion criteria','The protocol\'s reasons to exclude a record, EX01 to EX07. Each excluded record carries exactly one.'],
  protocol:['Protocol','The registered plan of the review: question, sources, criteria and stop rules. Changes are recorded as amendments.'],
  stoprule:['Stop rule','Screening of a ranked list stops after 30 exclusions in a row; the unscreened rest is reported, not hidden.'],
  dna:['Paper DNA','A strip of six colours, one per field: technique, architecture, automated span, human role, layer and half-year. Similar strips mean similar systems.'],
  similar:['Similar','Papers ranked by how many field values they share with this one, plus how many cited papers they share. A plain count; no model is involved.'],
  gap:['Gap','A combination no paper has. Ranked by how many papers we would expect there if the two fields were unrelated.'],
  passA:['First reading','Pass A: a miner reads every paper in scope and records its fields with quotes.'],
  passB:['Check reading','Pass B: a second, independent reading of a sample of papers, usually by a different model, to test pass A.'],
  agreement:['Agreement','Share of checked papers where both readings recorded the same value. Exact matching here; it understates agreement on free-text fields.'],
  hole:['Hole','A paper the miner read but left a field empty, or marked it not determinable or other.'],
};

/* term: dotted word with a definition on hover/focus.  info: an (i) button with an explanation panel. */
const POPS = new Map(); let popN = 0;
function term(key, shown){ const g=GLOSSARY[key]; if(!g) return esc(shown??key); return `<span class="term" tabindex="0" data-term="${esc(key)}">${esc(shown??g[0].toLowerCase())}</span>`; }
function info(html, label='About this'){ const id='p'+(++popN); POPS.set(id, html); return `<button type="button" class="info" data-pop="${id}" aria-label="${esc(label)}">i</button>`; }

/* ---------- pages for the palette (the whole hub, grouped) ---------- */
const PAGES = [
  ['Overview','Overview','overview.html'],['Overview','Flow','flow.html'],
  ['Corpus','Corpus','corpus.html'],['Corpus','Lenses','lenses.html'],['Corpus','Explore','explore.html'],['Corpus','Graph','graph.html'],
  ['Mining','Miners','miners.html'],['Mining','Extracted data','data.html'],
  ['Findings','Findings','findings.html'],['Living','Living review','living.html'],
  ['Design','Brand kit','kit.html'],
];

const ICON = {
  overview:'<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  flow:'<path d="M3 5h18M6 12h12M10 19h4"/>',
  corpus:'<path d="M5 4h10l4 4v12H5z"/><path d="M9 10h6M9 14h6M9 18h4"/>',
  lenses:'<circle cx="9" cy="9" r="5"/><circle cx="15" cy="15" r="5"/>',
  explore:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
  miners:'<path d="M4 20l6-6M14 4l6 6-8 8-6-6z"/><path d="M12 6l6 6"/>',
  data:'<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 9h18M3 14h18M9 4v16M15 4v16"/>',
  findings:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  kit:'<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  graph:'<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 7l8 1M7 8l4 8M17 10l-4 6"/>',
  living:'<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  search:'<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  theme:'<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
};
const svgI = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;

/* ---------- theme ---------- */
const THEMES = [['dark', 'Hub dark'], ['light', 'Hub light'], ['tokyo-night', 'Tokyo Night'], ['catppuccin-mocha', 'Catppuccin Mocha'], ['gruvbox', 'Gruvbox'], ['nord', 'Nord'], ['rose-pine', 'Rosé Pine'], ['lcars', 'LCARS']];
function setTheme(t){ document.documentElement.dataset.theme = t; try{localStorage.setItem('hub-r2-theme',t)}catch(e){} document.dispatchEvent(new CustomEvent('hub:theme')); }
try{ const t=localStorage.getItem('hub-r2-theme'); if(t) document.documentElement.dataset.theme=t; }catch(e){}
const q0 = new URLSearchParams(location.search); if(q0.get('theme')) document.documentElement.dataset.theme=q0.get('theme');

/* ---------- mount ---------- */
function mount(opts){
  const page = opts.page;
  const nav = [['overview','Overview','overview.html'],['corpus','Corpus','corpus.html'],['flow','Flow','flow.html'],['lenses','Lenses','lenses.html'],['explore','Explore','explore.html'],['graph','Graph','graph.html'],'-',['miners','Miners','miners.html'],['data','Data','data.html'],['findings','Findings','findings.html'],['living','Living','living.html']];
  document.body.innerHTML = `
  <div class="shell">
    <nav class="rail" aria-label="Hub">
      ${nav.map(n=>n==='-'?'<span class="rail-sep" aria-hidden="true"></span>':`<a href="${n[2]}" ${n[0]===page?'aria-current="page"':''}>${svgI(n[0])}${n[1]}</a>`).join('')}
      <a href="#" data-palette>${svgI('search')}All pages</a>
      <span class="spacer"></span>
      <a href="kit.html" ${page==='kit'?'aria-current="page"':''}>${svgI('kit')}Kit</a>
    </nav>
    <div>
      <header class="topbar">
        <span class="crumb">${esc(RF.slug||'')} · <b>${esc(opts.crumb||'')}</b></span>
        <span class="grow"></span>
        <span class="meta">as of <span class="mono">${esc((RF.generated||'').replace('T',' ').slice(0,16))} UTC</span></span>
        <button class="btn" data-palette aria-label="Go to a page or paper">${svgI('search').replace('<svg','<svg width=16 height=16 style="stroke:currentColor;fill:none;stroke-width:1.6"')} Go to a page or paper <span class="kbd">Ctrl K</span></button>
        <select class="theme-pick" id="themePick" aria-label="Colour theme">${THEMES.map(([k,l])=>`<option value="${k}">${l}</option>`).join('')}</select>
      </header>
      <main id="main"></main>
    </div>
  </div>
  <aside class="drawer" id="drawer" aria-label="Paper" tabindex="-1"></aside>
  <div class="palette" id="palette" role="dialog" aria-label="Go to"><div class="box"><input id="palIn" type="text" placeholder="Type a page or a paper title…" aria-label="Search pages and papers"><ul id="palList" role="listbox"></ul></div></div>
  <div class="tip" id="tip" role="tooltip"></div>
  <div class="pop" id="pop" role="tooltip"></div>`;
  wirePops();
  document.querySelectorAll('[data-palette]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();openPalette();}));
  const tp=$('#themePick'); tp.value=document.documentElement.dataset.theme||'dark'; tp.onchange=()=>setTheme(tp.value);
  document.addEventListener('keydown', e=>{
    if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); openPalette(); }
    else if(e.key==='/' && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)){ e.preventDefault(); openPalette(); }
    else if(e.key==='Escape'){ closePalette(); closeDrawer(); }
  });
  return $('#main');
}

/* ---------- term and info popovers ---------- */
let popPinned=null;
function showPop(el){ const p=$('#pop'); let h='';
  if(el.dataset.term){ const g=GLOSSARY[el.dataset.term]; h=`<b>${esc(g[0])}</b><div>${esc(g[1])}</div>`; }
  else h=POPS.get(el.dataset.pop)||'';
  p.innerHTML=h; p.style.display='block';
  const r=el.getBoundingClientRect(); const w=p.offsetWidth, ht=p.offsetHeight;
  let x=Math.min(Math.max(8,r.left), innerWidth-w-8), y=r.bottom+8; if(y+ht>innerHeight-8) y=Math.max(8,r.top-ht-8);
  p.style.left=x+'px'; p.style.top=y+'px'; }
function hidePop(){ if(popPinned) return; $('#pop').style.display='none'; }
function wirePops(){
  const sel='.term,.info';
  document.addEventListener('mouseover',e=>{ const t=e.target.closest(sel); if(t && !popPinned) showPop(t); });
  document.addEventListener('mouseout',e=>{ const t=e.target.closest(sel); if(t && !t.contains(e.relatedTarget)) hidePop(); });
  document.addEventListener('focusin',e=>{ const t=e.target.closest(sel); if(t) showPop(t); });
  document.addEventListener('focusout',e=>{ if(e.target.closest(sel)) { popPinned=null; hidePop(); } });
  document.addEventListener('click',e=>{ const t=e.target.closest(sel); if(t){ e.stopPropagation(); popPinned = popPinned===t?null:t; if(popPinned) showPop(t); else hidePop(); } else if(popPinned){ popPinned=null; hidePop(); } });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape'){ popPinned=null; hidePop(); } });
}

/* ---------- section header: short human title, optional info ---------- */
function header({kicker='', title, sub='', infoHtml='', level=2}){
  const H = level===1?'h1':'h2', cls = level===1?'display':'h2';
  return `<header class="sec-head">${kicker?`<div class="kicker">${kicker}</div>`:''}<${H} class="${cls}">${esc(title)}${infoHtml?' '+info(infoHtml,'About '+title):''}</${H}>${sub?`<p class="sub">${sub}</p>`:''}</header>`;
}

/* ---------- palette ---------- */
let palSel = 0, palItems = [];
function openPalette(){ const p=$('#palette'); p.setAttribute('open',''); const i=$('#palIn'); i.value=''; renderPal(''); i.focus(); i.oninput=()=>renderPal(i.value);
  i.onkeydown=e=>{ if(e.key==='ArrowDown'){palSel=Math.min(palSel+1,palItems.length-1);paintPal();e.preventDefault();}
    else if(e.key==='ArrowUp'){palSel=Math.max(palSel-1,0);paintPal();e.preventDefault();}
    else if(e.key==='Enter'){ palItems[palSel] && palItems[palSel].go(); } };
  p.onclick=e=>{ if(e.target===p) closePalette(); }; }
function closePalette(){ $('#palette')?.removeAttribute('open'); }
function renderPal(q){
  q=q.trim().toLowerCase();
  const pages = PAGES.filter(p=>!q || (p[1]+' '+p[0]).toLowerCase().includes(q)).map(p=>({label:p[1],group:p[0]+(p[2]?'':' · coming soon'),go:()=>{ if(p[2]) location.href=p[2]; }}));
  const works = q.length<2?[]:RF.works.filter(w=>w.title.toLowerCase().includes(q)).slice(0,8).map(w=>({label:w.title,group:'Paper · '+layerLabel(w.layer),go:()=>{closePalette();openDrawer(w.id);}}));
  palItems=[...pages.slice(0,q?8:30),...works]; palSel=0; paintPal();
}
function paintPal(){ $('#palList').innerHTML = palItems.map((it,i)=>`<li role="option" aria-selected="${i===palSel}" data-i="${i}"><span>${esc(it.label)}</span><span class="g">${esc(it.group)}</span></li>`).join('') || '<li>No match.</li>';
  $('#palList').querySelectorAll('li[data-i]').forEach(li=>li.onclick=()=>palItems[+li.dataset.i].go()); }

/* ---------- drawer: every value shows its evidence ---------- */
let lastFocus=null;
function openDrawer(id){
  const w = byId.get(id); if(!w) return;
  lastFocus = document.activeElement;
  const out=(citesOut.get(id)||[]).map(x=>byId.get(x)).filter(Boolean), inn=(citesIn.get(id)||[]).map(x=>byId.get(x)).filter(Boolean);
  const link = w.arxiv?`https://arxiv.org/abs/${w.arxiv}`:(w.doi?`https://doi.org/${w.doi}`:null);
  const d=$('#drawer');
  d.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center"><span class="meta">Paper · <span class="dot" style="background:${layerColor(w.layer)}"></span> ${esc(layerLabel(w.layer))}</span><button class="btn" id="dClose">Close <span class="kbd">Esc</span></button></div>
    <h2 class="display" style="font-size:30px;margin-top:14px">${esc(w.title)}</h2>
    <p class="meta">${esc((w.authors||[]).join('; ')||'No author recorded')} · ${esc(w.month||w.year)}${w.venue?' · '+esc(w.venue):''}</p>
    <p class="meta">Cited <b class="num">${w.cic}</b> times inside the corpus; cites <b class="num">${out.length}</b> works inside it.${link?` <a href="${link}" target="_blank" rel="noopener">Open source</a>`:''}</p>
    <div class="field"><div class="k">Abstract</div><p style="margin:4px 0">${esc(w.abstract)||'<span class="meta">No abstract recorded.</span>'}</p></div>
    <h3 class="h3" style="margin-top:22px">What the paper says, field by field</h3>
    ${FIELDS.map(([f,l])=>`<div class="field"><div class="k">${l}</div><div class="v">${esc(f==='human'?humanLabel(val(w,f)):pretty(val(w,f)))}</div>${quote(w,f)?`<blockquote class="quote">“${esc(quote(w,f))}”</blockquote>`:'<div class="meta">No quote recorded.</div>'}</div>`).join('')}
    ${inn.length||out.length?`<h3 class="h3" style="margin-top:22px">Inside the corpus</h3>
      ${inn.length?`<p class="meta">Built on by ${inn.length}:</p><ul>${inn.slice(0,8).map(x=>`<li><a href="#" data-open="${x.id}">${esc(x.title)}</a></li>`).join('')}</ul>`:''}
      ${out.length?`<p class="meta">Builds on ${out.length}:</p><ul>${out.slice(0,8).map(x=>`<li><a href="#" data-open="${x.id}">${esc(x.title)}</a></li>`).join('')}</ul>`:''}`:''}`;
  d.setAttribute('open',''); d.focus();
  $('#dClose').onclick=closeDrawer;
  d.querySelectorAll('[data-open]').forEach(a=>a.onclick=e=>{e.preventDefault();openDrawer(a.dataset.open);});
  document.dispatchEvent(new CustomEvent('hub:open',{detail:id}));
}
function closeDrawer(){ const d=$('#drawer'); if(d && d.hasAttribute('open')){ d.removeAttribute('open'); lastFocus && lastFocus.focus && lastFocus.focus(); document.dispatchEvent(new CustomEvent('hub:close')); } }

/* ---------- tooltip ---------- */
function tip(html, ev){ const t=$('#tip'); if(!html){t.style.display='none';return;} t.innerHTML=html; t.style.display='block';
  const x=Math.min(ev.clientX+14, innerWidth-t.offsetWidth-8), y=Math.min(ev.clientY+14, innerHeight-t.offsetHeight-8); t.style.left=x+'px'; t.style.top=y+'px'; }

/* ---------- hash state (shareable views) ---------- */
const hash = { get(){ return new URLSearchParams(location.hash.slice(1)); }, set(obj){ const p=new URLSearchParams(location.hash.slice(1)); for(const [k,v] of Object.entries(obj)){ if(v==null||v==='') p.delete(k); else p.set(k,v);} history.replaceState(null,'','#'+p.toString()); } };

const HUB = { $, esc, fmt, pct, HUMAN, LAYERS, FIELDS, humanLabel, layerLabel, pretty, humanColor, layerColor, cssv, val, quote,
  LABELS, GLOSSARY, term, info, header, mount, openDrawer, closeDrawer, openPalette, tip, hash, setTheme, init };

/* Set once by the page script. Derives every count from the payload; nothing is typed. */
function init(payload){
  RF = payload;
  RF.works = RF.works || []; RF.cites = RF.cites || [];
  /* The Python copies (services/hub_ui.py) are the source: the payload's wins when present. */
  if (RF.labels) Object.assign(LABELS, RF.labels);
  if (RF.glossary) Object.assign(GLOSSARY, RF.glossary);
  P = RF.prisma || {};
  byId = new Map(RF.works.map(w=>[w.id,w]));
  citesOut = new Map(); citesIn = new Map();
  for (const [a,b] of RF.cites){ (citesOut.get(a)||citesOut.set(a,[]).get(a)).push(b); (citesIn.get(b)||citesIn.set(b,[]).get(b)).push(a); }
  stats = {
    identified: sum(P.identified), duplicates: P.duplicates_removed, screened: P.screened,
    taExcluded: sum(P.ta_excluded), taIncluded: P.ta_included, ftNotSought: P.ft_not_sought, ftSought: P.ft_sought,
    ftNotRetrieved: P.ft_not_retrieved, ftAssessed: P.ft_assessed, ftExcluded: sum(P.ft_excluded), ftPending: P.ft_pending,
    included: P.included, mined: RF.works.length, links: RF.cites.length,
  };
  /* Two named sets, never conflated: PRISMA 'included' (screening decisions) vs 'mined' (works with a miner row; the explorer's scope). */
  SETS_NOTE = `This page shows the ${fmt(stats.mined)} papers that have been read in full. Screening included ${fmt(stats.included)}; the ${stats.mined-stats.included} extra papers are still being traced.`;
  for (const [k,v] of Object.entries(P.criteria||{})) GLOSSARY[k]=[k, v+'. One of the protocol\'s exclusion criteria.'];
  Object.assign(HUB, {RF, stats, SETS_NOTE, byId, citesOut, citesIn});
  return HUB;
}
/* Payloads: the static build writes data/<name>.js (file:// blocks fetch); the server serves
   data/<name>.json. Resolves to {name: payload}. */
HUB.load = function(names){
  window.HUB_DATA = window.HUB_DATA || {};
  return Promise.all(names.map(n => n in window.HUB_DATA ? window.HUB_DATA[n]
    : fetch('data/'+n+'.json').then(r=>{ if(!r.ok) throw new Error(n+': HTTP '+r.status); return r.json(); })
        .then(j=>(window.HUB_DATA[n]=j))))
    .then(vals=>Object.fromEntries(names.map((n,i)=>[n,vals[i]])));
};
window.HUB = HUB;

})();
