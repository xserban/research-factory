/* Research hub shared shell (ported from the round-2 demo). Served from /p/<slug>/ui/assets/shell.js.
   Page scripts call HUB.init(payload) once, then HUB.mount({page, crumb}). Nothing is read from
   globals at load time. Payload (services/hub_build.build_shell): {slug, generated, project, prisma, sets, works, cites (index pairs into works), dna_dims, glossary, labels}. */
/* Acts (one helper for every researcher write; none runs in the static build, where HUB.served is false):
     HUB.act(path, body)         POST JSON to `/p/<slug>/api...` (path as the route is named, e.g. '/api/queue/process')
                                 with the project token (X-Factory-Token) and the page's origin. Resolves to the Response.
     HUB.post(path, body)        the same, resolved to {ok, status, json, message}; `message` is the structured
                                 issues of a refusal as text, or a network error. Never rejects.
     HUB.issues(json)            'field message; ...' from a refusal body.
     HUB.confirm(host, message, onYes, extra?)  inline Confirm / Cancel in `host` (no browser dialog); onYes(host) may
                                 return a promise, a rejection is shown in host.
     HUB.get(path)               GET under the same prefix.
   Pattern: if (HUB.served) HUB.confirm(host, 'Do it?', () => HUB.post(path, body).then(r => { host.textContent = r.ok ? 'Done.' : 'Refused: ' + r.message; })). */
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
  mined:['Read in full','A paper whose full text a miner has read and recorded fields for, each with the sentence it was based on. Usually close to the included set; the Flow page lists every difference by id.'],
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
  criteria:['Exclusion criteria','The protocol\'s reasons to exclude a record, each with an EX-prefixed id. Each excluded record carries exactly one.'],
  protocol:['Protocol','The registered plan of the review: question, sources, criteria and stop rules. Changes are recorded as amendments.'],
  stoprule:['Stop rule','Screening of a ranked list stops after the run of consecutive exclusions the protocol sets; the unscreened rest is reported, not hidden.'],
  dna:['Paper DNA','A strip of six colours, one per field: technique, architecture, automated span, human role, layer and half-year. Similar strips mean similar systems.'],
  similar:['Similar','Papers ranked by how many field values they share with this one, plus how many cited papers they share. A plain count; no model is involved.'],
  gap:['Gap','A combination no paper has. Ranked by how many papers we would expect there if the two fields were unrelated.'],
  passA:['First reading','Pass A: a miner reads every paper in scope and records its fields with quotes.'],
  passB:['Check reading','Pass B: a second, independent reading of a sample of papers, usually by a different model, to test pass A.'],
  agreement:['Agreement','Share of checked papers where both readings recorded the same value. Exact matching here; it understates agreement on free-text fields.'],
  hole:['Hole','A paper the miner read but left a field empty, or gave a gap value (not-determinable, none-stated, not-stated, other, unclear) instead of a finding.'],
};

/* term: dotted word with a definition on hover/focus.  info: an (i) button with an explanation panel. */
const POPS = new Map(); let popN = 0;
function term(key, shown){ const g=GLOSSARY[key]; if(!g) return esc(shown??key); return `<span class="term" tabindex="0" data-term="${esc(key)}">${esc(shown??g[0].toLowerCase())}</span>`; }
function info(html, label='About this'){ const id='p'+(++popN); POPS.set(id, html); return `<button type="button" class="info" data-pop="${id}" aria-label="${esc(label)}">i</button>`; }

/* ---------- pages for the palette (the whole hub, grouped by the sections of SECTIONS) ---------- */
const PAGES = [
  ['Plan','Protocol','protocol.html'],['Plan','How this study runs','levels.html'],
  ['Overview','Overview','overview.html'],['Overview','Pipeline','pipeline.html'],['Overview','Flow','flow.html'],
  ['Papers','Corpus','corpus.html'],['Papers','Explore','explore.html'],['Papers','Lenses','lenses.html'],['Papers','Sources','sources.html'],['Papers','Method','method.html'],
  ['Map','Graph','graph.html'],['Map','Landscape','landscape.html'],['Map','Ideas','ideas.html'],
  ['Extract','Miners','miners.html'],['Extract','Extracted data','data.html'],
  ['Findings','Findings','findings.html'],['Findings','Contradictions','contradictions.html'],['Findings','Hypotheses','hypotheses.html'],['Findings','Chat with papers','chat.html'],['Findings','Intuition','intuition.html'],
  ['Write','Write & export','write.html'],
  ['Ops','Living review','living.html'],['Ops','Costs & runs','costs.html'],['Ops','Platform','platform.html'],
  ['Start','Start here','learn.html'],
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
  contradictions:'<path d="M4 8h12M12 4l4 4-4 4M20 16H8M12 12l-4 4 4 4"/>',
  hypotheses:'<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.500 10.900c.6.500 1 1.200 1 2.100h5c0-.9.4-1.600 1-2.100A6 6 0 0 0 12 3z"/>',
  intuition:'<circle cx="12" cy="10" r="5"/><path d="M9.500 15.500h5M10 18.500h4"/>',
  chat:'<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
  learn:'<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M9 8h6M9 12h6"/>',
  kit:'<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  graph:'<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 7l8 1M7 8l4 8M17 10l-4 6"/>',
  ideas:'<path d="M12 3l4 4-4 4-4-4z"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M10 11l-3 5M14 11l3 5"/>',
  landscape:'<path d="M3 18l5-8 4 4 4-7 5 11z"/><path d="M3 21h18"/>',
  living:'<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  levels:'<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
  protocol:'<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13l2 2 4-4"/>',
  pipeline:'<circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><path d="M7 12h3M14 12h3"/>',
  sources:'<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.300 8-3V6M4 12c0 1.700 3.600 3 8 3s8-1.300 8-3"/>',
  method:'<path d="M4 20h16M6 20V9l6-5 6 5v11M10 20v-6h4v6"/>',
  costs:'<circle cx="12" cy="12" r="9"/><path d="M12 7v10M15 9.500c-.5-1-1.500-1.500-3-1.500-1.700 0-3 .8-3 2s1.300 1.800 3 2 3 .800 3 2-1.300 2-3 2c-1.500 0-2.500-.5-3-1.500"/>',
  write:'<path d="M5 19l1-4L17 4l3 3L9 18zM14 7l3 3"/>',
  platform:'<rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><path d="M7 7h.01M7 17h.01"/>',
  projects:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  search:'<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  theme:'<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
};
const svgI = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;

/* ---------- theme ---------- */
/* [id, name, group]: the same ids and names as services/site_themes.py; the picker groups by Dark / Light */
const THEMES = [
  ['dark', 'Hub dark', 'Dark'],
  ['tokyo-night', 'Tokyo Night', 'Dark'],
  ['catppuccin-mocha', 'Catppuccin Mocha', 'Dark'],
  ['gruvbox', 'Gruvbox', 'Dark'],
  ['nord', 'Nord', 'Dark'],
  ['rose-pine', 'Rosé Pine', 'Dark'],
  ['lcars', 'LCARS', 'Dark'],
  ['ethereal', 'Ethereal', 'Dark'],
  ['aetheria', 'Aetheria', 'Dark'],
  ['cyberpunk-dreams', 'Cyberpunk Dreams', 'Dark'],
  ['circuit-horizon', 'Circuit Horizon', 'Dark'],
  ['moon-orbit', 'Moon Orbit', 'Dark'],
  ['solitude', 'Solitude', 'Dark'],
  ['vantablack', 'Vantablack', 'Dark'],
  ['kanagawa', 'Kanagawa', 'Dark'],
  ['light', 'Hub light', 'Light'],
  ['paper-blue', 'Paper Blue', 'Light'],
  ['sepia', 'Sepia', 'Light'],
  ['cool-grey', 'Cool Grey', 'Light'],
  ['catppuccin-latte', 'Catppuccin Latte', 'Light'],
  ['flexoki-light', 'Flexoki Light', 'Light'],
  ['solarized-light', 'Solarized Light', 'Light'],
];
/* One saved choice for every hub page: the key and ids of services/site_theme.py (SAVE_KEY), so the
   portal, the classic hub and these pages show the same theme. 'hub-r2-theme' is read once, as a fallback. */
const THEME_KEY = 'factory-theme';
const themeOk = t => THEMES.some(x => x[0] === t);
function savedTheme(){ try{ const t=localStorage.getItem(THEME_KEY); if(themeOk(t)) return t; const o=localStorage.getItem('hub-r2-theme'); return themeOk(o)?o:null; }catch(e){ return null; } }
function setTheme(t){ document.documentElement.dataset.theme = t; try{localStorage.setItem(THEME_KEY,t)}catch(e){} document.dispatchEvent(new CustomEvent('hub:theme')); }
{ const t=savedTheme(); if(t) document.documentElement.dataset.theme=t; }
window.addEventListener('storage', ev => { if(ev.key!==THEME_KEY) return; const t=savedTheme()||'dark'; document.documentElement.dataset.theme=t; const tp=document.getElementById('themePick'); if(tp) tp.value=t; document.dispatchEvent(new CustomEvent('hub:theme')); });
const q0 = new URLSearchParams(location.search); if(q0.get('theme')) document.documentElement.dataset.theme=q0.get('theme');

/* ---------- navigation: sections (tabs in the top bar, in research order) and their pages (the rail).
   A section: [id, label, icon, pages]; a page: [id, rail label, the one question it answers].
   The rail shows only the current section's pages; the All pages menu shows every page with its
   question. Start here and Kit have their own links at the foot of the rail. ---------- */
const SECTIONS = [
  ['plan','Plan','protocol',[
    ['protocol','Protocol','What did we commit to before searching?'],
    ['levels','How this study runs','Which tier and autonomy level, and what does it skip?'],
  ]],
  ['overview','Overview','overview',[
    ['overview','Overview','Where does the study stand?'],
    ['pipeline','Pipeline','What is waiting at each stage?'],
    ['flow','Flow','Where did each record go, and why?'],
  ]],
  ['papers','Papers','corpus',[
    ['corpus','Corpus','Which papers are in, by layer and year?'],
    ['explore','Explore','Which papers match any field I pick?'],
    ['lenses','Lenses','How do the papers split under each taxonomy?'],
    ['sources','Sources','Where did the full texts come from?'],
    ['method','Method','How were the papers found and screened?'],
  ]],
  ['map','Map','graph',[
    ['graph','Graph','How do the papers cite each other?'],
    ['landscape','Landscape','Which combinations exist, and which are gaps?'],
    ['ideas','Ideas','Which ideas does each paper contribute?'],
  ]],
  ['extract','Extract','miners',[
    ['miners','Miners','How well do the miners agree?'],
    ['data','Data','Every extracted value, with its quote.'],
  ]],
  ['findings','Findings','findings',[
    ['findings','Findings','What does the evidence say?'],
    ['contradictions','Contradictions','Where do papers disagree?'],
    ['hypotheses','Hypotheses','Which conjectures are registered, and how did they fare?'],
    ['chat','Chat','What do the papers say about my question, with quotes?'],
    ['intuition','Intuition','Which readings and background concepts frame the papers?'],
  ]],
  ['write','Write','write',[
    ['write','Write & export','Drafts, reports and exports.'],
  ]],
  ['ops','Ops','costs',[
    ['living','Living','What changed since the last cycle?'],
    ['costs','Costs & runs','What did the runs cost?'],
    ['platform','Platform','Which tools and skills stand behind the study?'],
  ]],
];
const sectionOf = page => SECTIONS.find(s => s[3].some(p => p[0] === page)) || null;
const RAIL_FOLD_KEY = 'hub-rail-folded';

/* ---------- mount ---------- */
function mount(opts){
  const page = opts.page;
  const sec = sectionOf(page);
  const svg16 = k => svgI(k).replace('<svg','<svg width=16 height=16 style="stroke:currentColor;fill:none;stroke-width:1.6"');
  document.body.innerHTML = `
  <div class="shell">
    <nav class="rail" aria-label="${esc(sec ? sec[1] : 'Start')} pages">
      <a id="homeLink" class="home" href="/" hidden aria-label="All projects" title="All projects">${svgI('projects')}Projects</a>
      ${(sec ? sec[3] : []).map(p=>`<a href="${p[0]}.html" data-page="${p[0]}" title="${esc(p[2])}" ${p[0]===page?'aria-current="page"':''}>${svgI(p[0])}${esc(p[1])}</a>`).join('')}
      <span class="spacer"></span>
      <a href="#" data-menu>${svgI('search')}All pages</a>
      <a href="learn.html" ${page==='learn'?'aria-current="page"':''}>${svgI('learn')}Start here</a>
      <a href="kit.html" ${page==='kit'?'aria-current="page"':''}>${svgI('kit')}Kit</a>
    </nav>
    <div>
      <header class="topbar">
        <span class="crumb">${esc((RF.project&&RF.project.title)||RF.slug||'')} · <b>${esc(opts.crumb||'')}</b></span>
        <span class="grow"></span>
        <span id="projSwitch" class="proj-sw" hidden></span>
        <a id="classicHub" class="btn" hidden title="The classic hub, served beside this one">&larr; Classic hub</a>
        <span class="meta">as of <span class="mono">${esc((RF.generated||'').replace('T',' ').slice(0,16))} UTC</span></span>
        <button class="btn" data-palette aria-label="Go to a page or paper">${svg16('search')} Go to a page or paper <span class="kbd">Ctrl K</span></button>
        <select class="theme-pick" id="themePick" aria-label="Colour theme">${['Dark','Light'].map(g=>`<optgroup label="${g}">${THEMES.filter(t=>t[2]===g).map(([k,l])=>`<option value="${k}">${l}</option>`).join('')}</optgroup>`).join('')}</select>
      </header>
      <nav class="sec-tabs" aria-label="Sections">${SECTIONS.map(s=>`<a href="${s[3][0][0]}.html" data-section="${s[0]}" ${sec&&sec[0]===s[0]?'aria-current="true"':''}>${svg16(s[2])}${esc(s[1])}</a>`).join('')}</nav>
      <div id="scopeBar" hidden></div>
      <main id="main"></main>
    </div>
  </div>
  <aside class="drawer" id="drawer" aria-label="Paper" tabindex="-1"></aside>
  <div class="menu" id="menu" role="dialog" aria-modal="true" aria-label="All pages" hidden><div class="menu-box">
    <div class="menu-head"><h2>All pages</h2><span class="note">Esc closes · Ctrl K searches pages and papers</span><button type="button" class="btn" data-menu-close>Close</button></div>
    <div class="menu-grid">${SECTIONS.map(s=>`<section><h3>${svg16(s[2])}${esc(s[1])}</h3>${s[3].map(p=>`<a href="${p[0]}.html" data-page="${p[0]}" ${p[0]===page?'aria-current="page"':''}><b>${esc(p[1])}</b><span>${esc(p[2])}</span></a>`).join('')}</section>`).join('')}</div>
  </div></div>
  <div class="palette" id="palette" role="dialog" aria-label="Go to"><div class="box"><input id="palIn" type="text" placeholder="Type a page or a paper title…" aria-label="Search pages and papers"><ul id="palList" role="listbox"></ul></div></div>
  <div class="tip" id="tip" role="tooltip"></div>
  <div class="pop" id="pop" role="tooltip"></div>`;
  wirePops();
  if (window.HUB_SCOPE && HUB_SCOPE.mountBar) HUB_SCOPE.mountBar($('#scopeBar'), {page});
  if (HUB.served) projectSwitcher($('#projSwitch'));
  if (HUB.served) navStatus();
  /* served under the main hub (/p/<slug>/ui/): the portal at / is home; a single-project server has none */
  if (HUB.served && /^\/p\/[^/]+\/ui(\/|$)/.test(location.pathname)) $('#homeLink').hidden = false;
  /* served only: the classic hub lives at the prefix this hub sits under (<prefix>/ui/ → <prefix>/) */
  if (HUB.served) { const a = $('#classicHub'); a.href = location.pathname.replace(/\/ui(\/.*)?$/, '/'); a.hidden = false; }
  document.querySelectorAll('[data-palette]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();openPalette();}));
  document.querySelectorAll('[data-menu]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();openMenu();}));
  $('#menu').addEventListener('click', e=>{ if(e.target.id==='menu' || e.target.closest('[data-menu-close]')) closeMenu(); });
  foldRail(railFolded());
  alignRail(); requestAnimationFrame(alignRail); addEventListener('resize', alignRail);
  const tp=$('#themePick'); tp.value=document.documentElement.dataset.theme||'dark'; tp.onchange=()=>setTheme(tp.value);
  document.addEventListener('keydown', e=>{
    if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); openPalette(); }
    else if(e.key==='/' && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)){ e.preventDefault(); openPalette(); }
    else if(e.key==='Escape'){ closeMenu(); closePalette(); closeDrawer(); }
    else if(e.key==='[' && !e.ctrlKey && !e.metaKey && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)){ foldRail(!railFolded()); }
  });
  return $('#main');
}

/* ---------- which pages are building: served only. Polls ui/status.json every 5 s while the tab is
   visible and marks nav links in place. A page is building when any of its payloads is building or
   queued, failed when any failed. data-hub-pages (on <html>) maps each page to its payloads. ---------- */
const NAV_POLL_MS = 5000;
function navStatus(){
  let map = {}; try { map = JSON.parse(document.documentElement.dataset.hubPages || '{}'); } catch(e){}
  if (!Object.keys(map).length) return;
  const names = {}; SECTIONS.forEach(s => s[3].forEach(p => { names[p[0]] = p[1]; }));
  const state = {};
  const mark = (a, st) => {
    let el = a.querySelector(':scope > .nav-state');
    if (!st) { if (el) el.remove(); return; }
    if (!el) { el = document.createElement('span'); a.appendChild(el); el.className = 'nav-state'; }
    el.dataset.state = st;
    el.title = st === 'failed' ? 'Data for this page failed to build' : 'Data for this page is being rebuilt';
    el.innerHTML = st === 'failed' ? '<span class="ns-icon" aria-hidden="true">!</span><span class="ns-text">failed</span>'
      : '<span class="ns-icon" aria-hidden="true"></span><span class="ns-text">building</span>';
  };
  const apply = status => {
    Object.keys(map).forEach(pg => {
      const rows = map[pg].map(n => status[n]).filter(r => r && typeof r === 'object');
      state[pg] = rows.some(r => r.state === 'failed') ? 'failed'
        : rows.some(r => r.state === 'building' || r.state === 'queued') ? 'building' : '';
    });
    document.querySelectorAll('.rail a[data-page], .menu a[data-page]').forEach(a => mark(a, state[a.dataset.page] || ''));
    SECTIONS.forEach(s => {
      const a = document.querySelector('.sec-tabs a[data-section="' + s[0] + '"]'); if (!a) return;
      const busy = s[3].filter(p => state[p[0]] === 'building').map(p => names[p[0]]);
      let b = a.querySelector(':scope > .nav-count');
      if (!busy.length) { if (b) b.remove(); a.removeAttribute('title'); return; }
      if (!b) { b = document.createElement('span'); b.className = 'nav-count'; a.appendChild(b); }
      b.textContent = busy.length + ' building'; a.title = 'Building: ' + busy.join(', ');
    });
  };
  let timer = null;
  const poll = () => fetch('status.json', {cache: 'no-store'}).then(r => r.ok ? r.json() : null)
    .then(j => { if (j && typeof j === 'object') apply(j); }).catch(() => {});
  const start = () => { if (timer === null) { poll(); timer = setInterval(poll, NAV_POLL_MS); } };
  const stop = () => { if (timer !== null) { clearInterval(timer); timer = null; } };
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else start(); });
  if (!document.hidden) start();
}

/* ---------- All pages menu, rail fold and rail alignment ---------- */
function openMenu(){ const m=$('#menu'); m.hidden=false; (m.querySelector('[aria-current]')||m.querySelector('a')).focus(); }
function closeMenu(){ const m=$('#menu'); if(m) m.hidden=true; }
function railFolded(){ try{ return localStorage.getItem(RAIL_FOLD_KEY)==='1'; }catch(e){ return false; } }
/* `[` folds the rail away (remembered in this browser); the section tabs stay */
function foldRail(v){ document.querySelector('.shell')?.classList.toggle('folded', v); try{ localStorage.setItem(RAIL_FOLD_KEY, v?'1':''); }catch(e){} alignRail(); }
/* the rail's first page sits level with the content: below the top bar and the section tabs */
function alignRail(){ const r=document.querySelector('.rail'), t=document.querySelector('.topbar'), s=document.querySelector('.sec-tabs');
  if(!r||!t) return; r.style.paddingTop = matchMedia('(max-width:760px)').matches ? '' : ((t.offsetHeight||0)+(s?s.offsetHeight:0)+8)+'px'; }

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
  const extra = (HUB.paletteExtra && q.length>=2) ? HUB.paletteExtra(q).slice(0,8) : [];
  const works = q.length<2?[]:RF.works.filter(w=>w.title.toLowerCase().includes(q)).slice(0,8).map(w=>({label:w.title,group:'Paper · '+layerLabel(w.layer),go:()=>{closePalette();openDrawer(w.id);}}));
  palItems=[...pages.slice(0,q?8:30),...extra,...works]; palSel=0; paintPal();
}
function paintPal(){ $('#palList').innerHTML = palItems.map((it,i)=>`<li role="option" aria-selected="${i===palSel}" data-i="${i}"><span>${esc(it.label)}</span><span class="g">${esc(it.group)}</span></li>`).join('') || '<li>No match.</li>';
  $('#palList').querySelectorAll('li[data-i]').forEach(li=>li.onclick=()=>palItems[+li.dataset.i].go()); }

/* ---------- drawer: every value shows its evidence ---------- */
let lastFocus=null;
function openDrawer(id){
  const w = byId.get(id); if(!w) return;
  lastFocus = document.activeElement;
  const out=(citesOut.get(id)||[]).map(x=>byId.get(x)).filter(Boolean), inn=(citesIn.get(id)||[]).map(x=>byId.get(x)).filter(Boolean);
  const links = [w.arxiv?`<a href="https://arxiv.org/abs/${esc(w.arxiv)}" target="_blank" rel="noopener">arXiv</a>`:'', w.doi?`<a href="https://doi.org/${esc(w.doi)}" target="_blank" rel="noopener">DOI</a>`:''].filter(Boolean).join(' · ');
  const d=$('#drawer');
  const authors = (w.authors||[]).join('; '), more = (w.authors||[]).length>=8 ? ' et al.' : '';
  d.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center"><span class="meta">Paper · <span class="dot" style="background:${layerColor(w.layer)}"></span> ${esc(layerLabel(w.layer))}${w.mapped_from?' · '+info('Its fields were read from a duplicate record of the same paper.','About duplicate records'):''}</span><button class="btn" id="dClose">Close <span class="kbd">Esc</span></button></div>
    <h2 class="display" style="font-size:30px;margin-top:14px">${esc(w.title)}</h2>
    <p class="meta">${esc(authors?authors+more:'No author recorded')} · ${esc(w.year||'')}${w.venue?' · '+esc(w.venue):''}</p>
    <p class="meta">${term('cic','Cited here')} <b class="num">${w.cited_here??0}</b> times; cites <b class="num">${out.length}</b> works inside the corpus.${links?' '+links:''}</p>
    <p class="meta"><a href="flow.html#lanes=${encodeURIComponent(id)}">See its path</a> · <a href="corpus.html#id=${encodeURIComponent(id)}">Open in Corpus</a> · <a href="${esc(HUB.chatHref({include:[id], only:true}))}">Spar with this paper</a></p>
    <div class="field"><div class="k">Abstract</div><p style="margin:4px 0">${w.abstract?esc(w.abstract):'<span class="meta">No abstract recorded.</span>'}</p></div>
    <h3 class="h3" style="margin-top:22px">What the paper says, field by field</h3>
    ${FIELDS.map(([f,l])=>`<div class="field"><div class="k">${l}</div><div class="v">${esc(f==='human'?humanLabel(val(w,f)):pretty(val(w,f)))}</div>${quote(w,f)?`<blockquote class="quote">“${esc(quote(w,f))}”</blockquote>`:'<div class="meta">No quote recorded.</div>'}</div>`).join('')}
    ${inn.length||out.length?`<h3 class="h3" style="margin-top:22px">Inside the corpus</h3>
      ${inn.length?`<p class="meta">Built on by ${inn.length}:</p><ul>${inn.slice(0,8).map(x=>`<li><a href="#" data-open="${esc(x.id)}">${esc(x.title)}</a></li>`).join('')}</ul>`:''}
      ${out.length?`<p class="meta">Builds on ${out.length}:</p><ul>${out.slice(0,8).map(x=>`<li><a href="#" data-open="${esc(x.id)}">${esc(x.title)}</a></li>`).join('')}</ul>`:''}`:''}`;
  d.setAttribute('open',''); d.focus();
  $('#dClose').onclick=closeDrawer;
  d.querySelectorAll('[data-open]').forEach(a=>a.onclick=e=>{e.preventDefault();openDrawer(a.dataset.open);});
  document.dispatchEvent(new CustomEvent('hub:open',{detail:id}));
}
function closeDrawer(){ const d=$('#drawer'); if(d && d.hasAttribute('open')){ d.removeAttribute('open'); lastFocus && lastFocus.focus && lastFocus.focus(); document.dispatchEvent(new CustomEvent('hub:close')); } }

/* ---------- tooltip ---------- */
/* tip(text) shows plain text (textContent; "\n" breaks lines): safe for any payload or dataset string.
   tipHtml(html) is for HTML built in JS from HUB.esc()-escaped parts only; never pass dataset/getAttribute values to it. */
function tipShow(ev){ const t=$('#tip'); t.style.display='block';
  const x=Math.min(ev.clientX+14, innerWidth-t.offsetWidth-8), y=Math.min(ev.clientY+14, innerHeight-t.offsetHeight-8); t.style.left=x+'px'; t.style.top=y+'px'; }
function tip(text, ev){ const t=$('#tip'); if(!text){t.style.display='none';return;} t.classList.add('pl'); t.textContent=String(text); tipShow(ev||{clientX:0,clientY:0}); }
function tipHtml(html, ev){ const t=$('#tip'); if(!html){t.style.display='none';return;} t.classList.remove('pl'); t.innerHTML=html; tipShow(ev||{clientX:0,clientY:0}); }
function tipAt(ev){ if($('#tip').style.display==='block') tipShow(ev); }

/* ---------- hash state (shareable views) ---------- */
const hash = { get(){ return new URLSearchParams(location.hash.slice(1)); }, set(obj){ const p=new URLSearchParams(location.hash.slice(1)); for(const [k,v] of Object.entries(obj)){ if(v==null||v==='') p.delete(k); else p.set(k,v);} history.replaceState(null,'','#'+p.toString()); } };

/* A page may set HUB.paletteExtra = q => [{label, group, go}] to add its own entries (approaches, …) to Ctrl-K. */
const HUB = { $, esc, fmt, pct, HUMAN, LAYERS, FIELDS, humanLabel, layerLabel, pretty, humanColor, layerColor, cssv, val, quote,
  LABELS, GLOSSARY, term, info, header, mount, openDrawer, closeDrawer, openPalette, closePalette, tip, tipHtml, tipAt, hash, setTheme, THEMES, init };

/* Set once by the page script. Derives every count from the payload; nothing is typed. */
function init(payload){
  RF = payload;
  RF.works = RF.works || [];
  /* cites arrive as index pairs into works (smaller); the page-facing RF.cites holds work ids. */
  RF.cites = (RF.cites || []).map(([a,b]) => [RF.works[a] && RF.works[a].id, RF.works[b] && RF.works[b].id]).filter(([a,b]) => a && b);
  for (const w of RF.works) w.cic = w.cited_here ?? w.cic ?? 0;
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
  const S = RF.sets || {}, nInc = S.included ?? RF.works.length, nRead = S.read_in_full ?? nInc;
  stats.mined = nRead;
  SETS_NOTE = `This page shows the ${fmt(nInc)} included papers; ${fmt(nRead)} of them have been read in full.` +
    (S.duplicate_mapped ? ` ${fmt(S.duplicate_mapped)} were read under a duplicate record.` : '') +
    (S.not_read_yet ? ` ${fmt(S.not_read_yet)} not read yet.` : '') +
    (S.mined_but_excluded ? ` ${fmt(S.mined_but_excluded)} read papers were excluded.` : '');
  for (const [k,v] of Object.entries(P.criteria||{})) GLOSSARY[k]=[k, v+'. One of the protocol\'s exclusion criteria.'];
  Object.assign(HUB, {RF, stats, SETS_NOTE, byId, citesOut, citesIn});
  return HUB;
}
/* Payloads: the static build writes data/<name>.js (file:// blocks fetch); the server serves
   data/<name>.json. A name the page did not preload is loaded on demand: by a script tag when the
   page itself was loaded by script tags (static build), otherwise by fetch. Resolves to {name: payload}. */
/* Decided once, while shell.js runs: mounting a page may replace the body and its script tags. */
const STATIC_BUILD = !!document.querySelector('script[src^="data/"]');
const loaders = {};
/* Served mode: a payload being built answers 503 with Retry-After; ask again, with a quiet note. */
let waiting = 0;
function updating(on){
  waiting += on ? 1 : -1;
  let el = document.getElementById('hub-updating');
  if (waiting > 0 && !el) {
    el = document.createElement('div'); el.id = 'hub-updating'; el.setAttribute('role', 'status');
    el.style.cssText = 'position:fixed;right:16px;bottom:14px;z-index:50;padding:6px 12px;border-radius:999px;background:var(--raised,#222);color:var(--mut,#999);font:400 12px var(--f-ui,sans-serif)';
    el.textContent = 'Updating…'; document.body.appendChild(el);
  } else if (waiting <= 0 && el) el.remove();
}
/* Total wait is capped at about five minutes; the pause grows gently from Retry-After to 15 s. */
const WAIT_CAP_MS = 300000;
function fetchPayload(n){
  let started = false, waited = 0, pause = 0;
  /* no-cache: revalidate with the ETag; a 304 reuses the stored body (stale or fresh) */
  const attempt = () => fetch('data/' + n + '.json', {cache: 'no-cache'}).then(r => {
    if (r.status === 503) {
      if (!started) { started = true; updating(true); }
      const s = Math.max(1, parseInt(r.headers.get('Retry-After') || '2', 10));
      pause = pause ? Math.min(pause * 1.5, 15000) : s * 1000;
      if (waited + pause > WAIT_CAP_MS) {
        const el = document.getElementById('hub-updating');
        if (el) el.textContent = 'Still updating \u2014 reload later';
        started = false; /* skip the decrement: the note stays up and we stop asking */
        throw new Error(n + ': still updating');
      }
      waited += pause;
      return new Promise(res => setTimeout(res, pause)).then(attempt);
    }
    if (!r.ok) throw new Error(n + ': HTTP ' + r.status);
    if (r.headers.get('X-Hub-Stale')) watchFresh(n);
    return r.json();
  });
  return attempt().finally(() => { if (started) updating(false); });
}
/* A payload served from an older build: say so quietly, then ask every 20 s (at most 10 min) whether
   the fresh one is ready and offer a refresh link; the page itself is never swapped under the reader. */
const STALE_POLL_MS = 20000, STALE_CAP_MS = 600000;
let staleWatch = 0;
function watchFresh(n){
  if (staleWatch++) return;
  const el = document.createElement('div'); el.id = 'hub-stale'; el.setAttribute('role', 'status');
  el.style.cssText = 'position:fixed;right:16px;bottom:14px;z-index:50;padding:6px 12px;border-radius:999px;background:var(--raised,#222);color:var(--mut,#999);font:400 12px var(--f-ui,sans-serif)';
  el.textContent = 'Updating in the background'; document.body.appendChild(el);
  let waited = 0;
  const tick = () => {
    waited += STALE_POLL_MS;
    fetch('fresh?name=' + encodeURIComponent(n), {cache: 'no-store'}).then(r => r.json()).then(j => {
      if (j.fresh) {
        el.textContent = 'Newer data ready \u2014 ';
        const a = document.createElement('a'); a.href = '#'; a.textContent = 'refresh';
        a.style.color = 'inherit'; a.onclick = e => { e.preventDefault(); location.reload(); };
        el.appendChild(a);
      } else if (waited < STALE_CAP_MS) setTimeout(tick, STALE_POLL_MS); else el.remove();
    }).catch(() => { if (waited < STALE_CAP_MS) setTimeout(tick, STALE_POLL_MS); else el.remove(); });
  };
  setTimeout(tick, STALE_POLL_MS);
}
function loadOne(n){
  const D = window.HUB_DATA;
  if (n in D) return Promise.resolve(D[n]);
  if (loaders[n]) return loaders[n];
  const done = STATIC_BUILD
    ? new Promise((res, rej) => {
        const el = document.createElement('script');
        el.src = 'data/' + n + '.js';
        el.onload = () => (n in D) ? res(D[n]) : rej(new Error(n + ': script did not define the payload'));
        el.onerror = () => rej(new Error(n + ': script failed to load'));
        document.head.appendChild(el);
      })
    : fetchPayload(n).then(j => (D[n] = j));
  loaders[n] = done.catch(e => { delete loaders[n]; throw e; });
  return loaders[n];
}
HUB.load = function(names){
  window.HUB_DATA = window.HUB_DATA || {};
  return Promise.all(names.map(loadOne))
    .then(vals => Object.fromEntries(names.map((n, i) => [n, vals[i]])));
};
/* Served mode (the server adds <meta name="factory-served">, the write token and the API prefix); the
   static build has none of them, so every act stays off there. */
const meta = n => { const m = document.querySelector('meta[name="' + n + '"]'); return m ? m.content : ''; };
HUB.served = !!meta('factory-served');
/* POST a researcher act to the server; resolves to the Response (the caller reads json or a zip).
   Always the project route with the project token (no hub token is on any page). The browser adds the
   Origin header; the server refuses any origin but its own loopback address. */
HUB.act = (path, body) => fetch(meta('factory-api') + path, {method: 'POST', body: JSON.stringify(body),
  headers: {'Content-Type': 'application/json', 'X-Factory-Token': meta('factory-token')}});
/* A link to the Chat page with a basket set in its address (no server write): spec = {layers, include, exclude, only, hyp, mode, kind}; only: true means just the listed papers
   (lists of ids or layer names; hyp is prefilled text). Long lists are cut at 60 ids, the page says so. */
HUB.chatHref = spec => { const p = new URLSearchParams(), s = spec || {};
  for (const k of ['layers', 'include', 'exclude']) if (s[k] && s[k].length) p.set(k, s[k].slice(0, 60).join(','));
  for (const k of ['hyp', 'mode', 'kind']) if (s[k]) p.set(k, s[k]);
  if (s.only) p.set('only', '1');
  return 'chat.html#' + p.toString(); };
HUB.get = path => fetch(meta('factory-api') + path);
/* The server's refusals are {issues: [{field, message|reason}]}; both spellings are read. */
HUB.issues = j => ((j && j.issues) || []).map(i => i.field + ' ' + (i.message || i.reason || '')).join('; ') || 'refused';
/* HUB.act resolved to {ok, status, json, message}; never rejects. */
HUB.post = (path, body) => HUB.act(path, body)
  .then(r => r.json().catch(() => null).then(json => ({ok: r.ok && !(json && json.ok === false), status: r.status, json,
    message: r.ok ? '' : HUB.issues(json) === 'refused' && r.status === 403 ? 'not allowed (open the hub from this machine)' : HUB.issues(json)})))
  .catch(e => ({ok: false, status: 0, json: null, message: 'request failed: ' + (e && e.message || e)}));

/* ---------- project switcher (served only): the projects of /api/projects, and a "New project" link to the portal ---------- */
function projectSwitcher(host){
  host.hidden = false;
  host.innerHTML = '<button type="button" class="btn" aria-haspopup="true" aria-expanded="false">' + svgI('projects').replace('<svg','<svg width=16 height=16 style="stroke:currentColor;fill:none;stroke-width:1.6"') + ' Projects</button><div class="proj-panel" hidden></div>';
  const btn = host.querySelector('button'), panel = host.querySelector('.proj-panel');
  const close = () => { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
  const here = (RF && RF.slug) || '';
  const render = rows => {
    panel.innerHTML = '<ul>' + rows.map(p => `<li><a href="/p/${encodeURIComponent(p.slug)}/ui/" ${p.slug===here?'aria-current="true"':''}>${esc(p.title||p.slug)}<span class="meta"> ${esc(p.slug)}</span></a></li>`).join('') + '</ul>' +
      '<div class="proj-new"><a class="btn" href="/">New project</a></div>';
  };
  btn.onclick = () => {
    if (!panel.hidden) return close();
    panel.hidden = false; btn.setAttribute('aria-expanded', 'true');
    panel.textContent = 'Loading…';
    fetch('/api/projects').then(r => r.json()).then(j => render(j.projects || []))
      .catch(() => { panel.textContent = 'The project list is not available.'; });
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  document.addEventListener('click', e => { if (!host.contains(e.target)) close(); });
}
/* An inline confirmation inside `host` (no browser dialog): the message, then Confirm and Cancel. */
HUB.confirm = (host, message, onYes, extra) => {
  host.innerHTML = '';
  const box = document.createElement('span'); box.className = 'meta'; box.setAttribute('role', 'alert');
  box.textContent = message + ' ';
  const yes = document.createElement('button'); yes.type = 'button'; yes.className = 'btn primary'; yes.textContent = 'Confirm';
  const no = document.createElement('button'); no.type = 'button'; no.className = 'btn'; no.textContent = 'Cancel';
  if (extra) box.append(extra, ' ');
  box.append(yes, ' ', no); host.appendChild(box);
  no.onclick = () => { host.innerHTML = ''; };
  yes.onclick = () => { yes.disabled = true; Promise.resolve(onYes(host)).catch(e => { host.textContent = String(e && e.message || e); }); };
  yes.focus();
};
window.HUB = HUB;

})();
