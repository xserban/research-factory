/* Corpus page: port of the explorer (facets, search, five views, selection, detail pane), with grouped facets,
   chips, DNA strips and the whole state in the URL hash. Numbers come from the payloads; nothing is typed. */
HUB.load(['shell', 'corpus']).then(d => {
const H = HUB.init(d.shell), {esc, fmt, pretty, $} = HUB, C = d.corpus, W = C.works;
H.mount({page: 'corpus', crumb: 'Corpus'});

/* ---------- styles (kit tokens only) ---------- */
document.head.insertAdjacentHTML('beforeend', `<style id="corpus-css">
.cwrap{display:grid;grid-template-columns:272px minmax(0,1fr);gap:24px;align-items:start;margin-top:14px}
.cside{position:sticky;top:60px;max-height:calc(100vh - 76px);overflow:auto;padding-right:6px}
.ftoggle{display:none}
.fg{border-top:1px solid var(--hair);padding:6px 0}.fg>summary{cursor:pointer;display:flex;align-items:center;gap:8px;font:600 var(--t-s) var(--f-ui);padding:6px 0;list-style:none}
.fg>summary::-webkit-details-marker{display:none}.fg>summary::before{content:'▸';color:var(--dim);font-size:10px;width:10px}.fg[open]>summary::before{content:'▾'}
.fg .ga{font-weight:400;color:var(--acc);font-size:var(--t-xs)}.fg .lnk{margin-left:auto;font:400 var(--t-xs) var(--f-ui);color:var(--mut);background:none;border:0;cursor:pointer;text-decoration:underline;padding:0}
.fg .lnk:hover{color:var(--fg)}.fc{margin:6px 0 12px}.fh{display:flex;align-items:center;gap:4px;font:500 var(--t-xs) var(--f-ui);color:var(--mut);margin-bottom:4px}
.fh input{margin-left:auto;width:112px;padding:4px 8px;font-size:var(--t-xs)}
.fi{display:flex;align-items:center;gap:7px;padding:3px 4px;border-radius:4px;font-size:var(--t-s);cursor:pointer}.fi:hover{background:var(--raised)}
.fi input{margin:0;accent-color:var(--acc)}.fi .fl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fi .n{font:400 11px var(--f-mono);color:var(--mut)}
.fi.z:not(.on){opacity:.4}.fmore{font:400 var(--t-xs) var(--f-ui);color:var(--acc);background:none;border:0;cursor:pointer;padding:3px 4px}
.ctool{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin-bottom:12px}
.ctool .q{flex:1;min-width:220px;max-width:520px}.ctool label{font-size:var(--t-s);color:var(--mut);display:inline-flex;gap:6px;align-items:center}
.ctool input[type=number]{width:64px;font:400 var(--t-s) var(--f-ui);background:var(--raised);color:var(--fg);border:0;border-radius:var(--r-s);padding:8px 10px}.ctool select{max-width:200px}.btn[aria-pressed=true]{background:var(--acc-soft);box-shadow:inset 0 0 0 1px var(--acc)}
.cbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}.cbar .cnt{font:500 var(--t-m) var(--f-ui);margin-right:6px}
.cbar .sp{flex:1}.cbar a{font-size:var(--t-s)}.csel{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0 10px}
mark{background:var(--acc-soft);color:var(--fg);border-radius:2px;box-shadow:0 0 0 1px var(--acc-soft)}
.cr{display:flex;gap:10px;align-items:flex-start;padding:9px 8px;border-bottom:1px solid var(--hair);cursor:pointer;border-radius:4px}
.cr:hover{background:var(--raised)}.cr.cur{box-shadow:inset 2px 0 0 var(--acc);background:var(--raised)}.cr[aria-selected=true]{background:var(--acc-soft)}
.cr input{margin-top:5px;accent-color:var(--acc)}.cm{flex:1;min-width:0}.cm .ct{font-weight:500;line-height:1.35}.cm .mt{font-size:var(--t-xs);color:var(--mut);margin-top:2px;display:flex;flex-wrap:wrap;gap:2px 10px}
.cm .mt .dot{margin-right:4px}.sn{font-size:var(--t-xs);color:var(--dim);margin-top:3px}.stg{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}
.tag{font-size:11px;padding:2px 7px;border-radius:999px;background:var(--raised);color:var(--mut);white-space:nowrap}
.cr .rt{display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex:none}.cr .ci{font:400 11px var(--f-mono);color:var(--mut)}
.dna{display:inline-flex;gap:1px}.dna i{display:block;width:12px;height:12px;background:var(--c);border-radius:2px}
.cg{font:600 var(--t-s) var(--f-ui);padding:16px 8px 6px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:baseline}.cg span{font-weight:400;color:var(--mut)}
.scroll{overflow-x:auto;padding-bottom:8px}.lane{display:flex;border-bottom:1px solid var(--hair);padding:5px 0;align-items:flex-start}
.lane>b{width:170px;flex:none;font-size:var(--t-xs);font-weight:500;padding-right:8px}.lane>b span{color:var(--dim);font-weight:400}
.cells{display:flex}.cell{width:36px;flex:none;border-left:1px dashed var(--hair);padding:0 2px}.td{display:block;height:9px;margin:1px 0;border-radius:3px;cursor:pointer}.td:hover{outline:2px solid var(--fg)}
.axs{display:flex;margin-left:170px;font-size:10px;color:var(--dim)}.axs div{width:36px;flex:none;padding-left:2px;border-left:1px dashed var(--hair);white-space:nowrap}
.chr{display:flex;gap:12px;align-items:flex-start}.mon{width:250px;flex:none}.mon h4{margin:0 0 8px;font:600 var(--t-s) var(--f-ui)}.mon h4 span{color:var(--dim);font-weight:400}
.card2{background:var(--surface);border-radius:var(--r-s);padding:10px;margin-bottom:8px;cursor:pointer;font-size:var(--t-xs);color:var(--mut)}.card2:hover{background:var(--raised)}.card2 b{display:block;color:var(--fg);font-size:var(--t-s);font-weight:500;margin:2px 0 5px}
.card2 .qt{font:italic 400 var(--t-xs) var(--f-display);margin-top:5px;color:var(--fg)}.sd{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:3px}
.lnw{position:relative;overflow:auto;height:min(68vh,700px);background:var(--surface);border-radius:var(--r)}.lnw svg{position:absolute;left:0;top:0;pointer-events:none;z-index:0}
.ed{fill:none;stroke:var(--dim);stroke-width:1.2;opacity:.5}.ed.hl{stroke:var(--exc);stroke-width:2.4;opacity:1}
.nd{position:absolute;width:176px;height:54px;border-radius:6px;padding:4px 7px;background:var(--raised);border-left:5px solid var(--acc);font-size:11.5px;line-height:1.25;overflow:hidden;cursor:pointer;z-index:1}
.nd .d{color:var(--dim);font-size:10.5px}.nd:hover{outline:2px solid var(--acc);z-index:3}.nd.dim{opacity:.2}.nd.sel{outline:3px solid var(--fg);z-index:4}.nd.anc{outline:2px solid var(--exc)}.nd.desc{outline:2px solid var(--inc)}
.mh{position:absolute;top:4px;font-size:12px;font-weight:600;color:var(--mut)}
.gwrap{position:relative;background:var(--surface);border-radius:var(--r);overflow:hidden}.gwrap canvas{display:block;width:100%;height:min(68vh,700px);touch-action:none}
.gtog{position:absolute;left:10px;top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;z-index:2}
#cdet{position:fixed;top:0;right:0;height:100vh;width:min(600px,100vw);background:var(--surface);box-shadow:var(--shadow);transform:translateX(100%);transition:transform .2s;z-index:45;overflow:auto;padding:22px 26px 60px}
#cdet[open]{transform:none}#cdet h3.h3{margin:22px 0 6px}#cdet .kv{margin:8px 0;font-size:var(--t-s)}#cdet .kv b{font-weight:600;margin-right:4px}#cdet .kv .quote{font-size:var(--t-s);margin:3px 0}
#cdet .cmd{display:flex;gap:6px;margin:4px 0}#cdet code{flex:1;overflow-x:auto;white-space:nowrap;background:var(--bg);border-radius:4px;padding:6px 8px;font:12px var(--f-mono)}
#cdet ul{margin:4px 0;padding-left:18px;font-size:var(--t-s)}#cdet a{cursor:pointer}.acts{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.cfoot{margin-top:28px;display:flex;align-items:center;gap:6px}
@media (max-width:900px){.cwrap{grid-template-columns:1fr}.cside{display:none;position:static;max-height:none}.cside.show{display:block}.ftoggle{display:inline-flex}.cr .rt,.ctool .kbd{display:none}
 .lane>b{width:90px}.axs{margin-left:90px}#cdet{padding:18px 16px 80px}}
</style>`);

/* ---------- data prep ---------- */
const DD = [ // key, label, group, glossary key, plain definition
 ['layer','Layer','Paper','layer'],['year','Year','Paper',0,'Year the paper was published.'],
 ['field','Field of science','Paper',0,'The scientific field the system is applied to.'],['data','Data','Paper',0,'The kind of data the system works on.'],
 ['technique','Technique','System','technique'],['architecture','Architecture','System','architecture'],
 ['human','Human role','Human & process','human'],['process','Process','Human & process',0,'The shape of the research process the system follows.'],
 ['span','Automated span','Human & process','span'],['assess','Idea assessment','Human & process',0,'How the system judges the ideas it produces.'],
 ['stage','Lifecycle stage','Human & process',0,'Stages of the research cycle a paper covers. A paper can cover several.'],
 ['evaluation','Evaluation','Evaluation',0,'How the system is evaluated.']];
const GROUPS = ['Paper','System','Human & process','Evaluation'], DIM = Object.fromEntries(DD.map(x => [x[0], x]));
const dsrc = Object.fromEntries(C.dims.map(x => [x.key, x]));
const LORD = [...(C.layer_order || []), 'unlayered'], HORD = HUB.HUMAN.map(h => h[0]);
const eraOf = m => m ? m.slice(0,4) + '-H' + (+m.slice(5,7) <= 6 ? 1 : 2) : null;
const eraLabel = e => { const [y,h] = e.split('-H'); return (h === '1' ? 'Jan–Jun ' : 'Jul–Dec ') + y; };
const slugMap = new Map(), idMap = new Map();
for (const w of W) {
  w._d = {};
  for (const [k] of DD) {
    if (k === 'stage') w._d[k] = [...new Set(w.stages.map(s => s.stage))];
    else if (k === 'year') w._d[k] = (w.published || w.year) ? [String(w.published || w.year).slice(0,4)] : [];
    else if (k === 'layer') w._d[k] = [w.layer || 'unlayered'];
    else { const x = dsrc[k], o = x && w[x.src] && w[x.src][x.field]; w._d[k] = o && o.v ? [o.v] : []; }
  }
  w._era = eraOf(w.month);
  w._q = [w.cls, w.map, w.desc, w.sum].flatMap(o => Object.values(o || {}).map(x => x.q)).concat(w.stages.map(s => s.quote)).filter(Boolean);
  w._t = (w.title + ' ' + (w.abstract || '') + ' ' + w._q.join(' ')).toLowerCase();
  slugMap.set(w.slug, w); idMap.set(w.id, w); if (w.mapped_from) idMap.set(w.mapped_from, w);
}
const OUT = {}, INN = {};
for (const [a, b] of C.cites) { (OUT[a] = OUT[a] || []).push(b); (INN[b] = INN[b] || []).push(a); }
const TOT = {}; // total counts per dim value, for stable ordering
for (const [k] of DD) { TOT[k] = {}; for (const w of W) for (const v of w._d[k]) TOT[k][v] = (TOT[k][v] || 0) + 1; }
const ORD = {};
for (const [k] of DD) ORD[k] = k === 'layer' ? LORD : k === 'human' ? HORD : k === 'year' ? Object.keys(TOT[k]).sort().reverse()
  : Object.keys(TOT[k]).sort((a, b) => TOT[k][b] - TOT[k][a] || a.localeCompare(b));
ORD.era = [...new Set(W.map(w => w._era).filter(Boolean))].sort();
const lab = (k, v) => k === 'human' ? H.humanLabel(v) : k === 'layer' ? H.layerLabel(v) : k === 'year' ? v : pretty(v);
const FL = k => pretty(k.replace(/_/g, '-'));

/* ---------- colours: shared meaning with the Explore DNA ---------- */
let SC = {};
const refreshColors = () => { SC = {nul: HUB.cssv('--h-null'), s2: HUB.cssv('--seq-2'), s4: HUB.cssv('--seq-4')}; };
const H0 = {technique: 20, architecture: 150, span: 280, field: 60, data: 200, process: 330, assess: 100, evaluation: 240, stage: 0, year: 180};
const lerpC = (a, b, t) => { const p = h => { h = h.trim(); if (h[0] !== '#') return [128,128,128]; if (h.length === 4) h = '#' + [...h.slice(1)].map(c => c + c).join(''); return [1,3,5].map(i => parseInt(h.substr(i,2), 16)); };
  const A = p(a), B = p(b); return 'rgb(' + A.map((x, i) => Math.round(x + (B[i] - x) * t)).join(',') + ')'; };
function colorOf(k, v) {
  if (v == null || v === '') return SC.nul;
  if (k === 'human') return HUB.humanColor(v);
  if (k === 'layer') return HUB.layerColor(v);
  if (k === 'era') return lerpC(SC.s2, SC.s4, ORD.era.indexOf(v) / Math.max(1, ORD.era.length - 1));
  const i = Math.max(0, (ORD[k] || []).indexOf(v)), light = document.documentElement.dataset.theme === 'light', hue = ((H0[k] || 0) + i * 137.508) % 360;
  return light ? `hsl(${hue} 52% ${i % 2 ? 36 : 46}%)` : `hsl(${hue} 56% ${i % 2 ? 58 : 70}%)`;
}
const SEGS = [['technique','Technique'],['architecture','Architecture'],['span','Automated span'],['human','Human role'],['layer','Layer'],['era','Era (half-year)']];
const sv = (w, k) => k === 'era' ? w._era : w._d[k][0];
const segName = (k, v) => v == null ? 'not coded' : k === 'era' ? eraLabel(v) : lab(k, v);
const dnaHTML = w => `<span class="dna" data-dna="${esc(w.id)}">${SEGS.map(([k]) => `<i style="--c:${colorOf(k, sv(w, k))}"></i>`).join('')}</span>`;
const tipDNA = w => `<div style="font-weight:600;margin-bottom:4px">DNA</div>` + SEGS.map(([k, l]) => `<div style="font-size:12px"><span class="dot" style="background:${colorOf(k, sv(w, k))};margin-right:6px"></span>${l} · <b>${esc(segName(k, sv(w, k)))}</b></div>`).join('');

/* ---------- state and URL hash ---------- */
const ST = {view: 'list', grp: 'technique', sort: 'new', rev: false, q: '', cite: 0, ft: false, id: '', f: {}, sel: new Set(), fq: {}, all: {}, cur: -1, lnAll: false, month: ''};
const GD = new Set(['technique', 'stage', 'cites']);
const VIEWS = [['list','List'],['timeline','Timeline'],['chrono','Chronology'],['lineage','Lineage'],['graph','Graph']];
const SORTS = [['new','Date, newest first'],['old','Date, oldest first'],['cited','Most cited here'],['title','Title A to Z']];
let TERMS = [], RX = null, VIS = [];
const setQ = q => { ST.q = q; TERMS = q.toLowerCase().split(/\s+/).filter(Boolean);
  RX = TERMS.length ? new RegExp('(' + TERMS.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi') : null; };
const hl = s => { s = String(s ?? ''); return RX ? s.split(RX).map((p, i) => i % 2 ? `<mark>${esc(p)}</mark>` : esc(p)).join('') : esc(s); };
function readHash() {
  const p = HUB.hash.get();
  ST.view = VIEWS.some(v => v[0] === p.get('view')) ? p.get('view') : 'list';
  ST.grp = p.get('grp') && (p.get('grp') === 'none' || DIM[p.get('grp')]) ? p.get('grp') : 'technique';
  ST.sort = SORTS.some(s => s[0] === p.get('sort')) ? p.get('sort') : 'new'; ST.rev = p.get('rev') === '1';
  setQ(p.get('q') || ''); ST.cite = parseInt(p.get('cite'), 10) || 0; ST.ft = p.get('ft') === '1'; ST.month = /^\d{4}-\d{2}$/.test(p.get('month') || '') ? p.get('month') : '';
  ST.f = {}; for (const [k] of DD) { const v = (p.get(k) || '').split(/[~,]/).filter(Boolean); if (v.length) ST.f[k] = new Set(v); }
  ST.id = p.get('id') || '';
}
function writeHash() {
  const o = {view: ST.view === 'list' ? null : ST.view, grp: ST.grp === 'technique' ? null : ST.grp, sort: ST.sort === 'new' ? null : ST.sort,
    rev: ST.rev ? 1 : null, q: ST.q || null, cite: ST.cite || null, ft: ST.ft ? 1 : null, month: ST.month || null, id: ST.id || null};
  for (const [k] of DD) o[k] = ST.f[k] && ST.f[k].size ? [...ST.f[k]].join('~') : null;
  HUB.hash.set(o);
}

/* ---------- scope (HS-02, HS-03, HS-11, HS-20): the date range narrows every list and count ---------- */
const SCOPE = window.HUB_SCOPE;
let INS = new Set(W.map(w => w.id)), SRES = null; // ids in scope; the last apply() result
function applyScope() {
  SRES = SCOPE.apply(W, w => w.published, SCOPE.current(), {includeUndated: SCOPE.includeUndated()});
  INS = new Set(SRES.inScope.map(w => w.id));
  for (const id of [...ST.sel]) if (!INS.has(id)) ST.sel.delete(id);
}

/* ---------- filtering ---------- */
function ok(w, skip) {
  if (!INS.has(w.id)) return false;
  if (ST.cite > 0 && !(w.cited_in_corpus >= ST.cite)) return false;
  if (ST.ft && !w.doc) return false;
  if (ST.month && w.month !== ST.month) return false;
  if (TERMS.length && !TERMS.every(t => w._t.includes(t))) return false;
  for (const k in ST.f) { const s = ST.f[k]; if (k !== skip && s.size && !w._d[k].some(v => s.has(v))) return false; }
  return true;
}
const cmp = (a, b) => { const da = a.published || '', db = b.published || '';
  const r = ST.sort === 'title' ? a.title.localeCompare(b.title) : ST.sort === 'cited' ? (b.cited_in_corpus || 0) - (a.cited_in_corpus || 0) || db.localeCompare(da)
    : ST.sort === 'old' ? da.localeCompare(db) : db.localeCompare(da);
  return ST.rev ? -r : r; };
function groups(ws, k) {
  if (k === 'none') return [['', ws.slice().sort(cmp)]];
  const g = new Map();
  for (const w of ws) for (const v of (w._d[k].length ? w._d[k] : [''])) (g.get(v) || g.set(v, []).get(v)).push(w);
  const ix = v => ORD[k].indexOf(v);
  return [...g].sort((a, b) => !a[0] - !b[0] || (k === 'layer' || k === 'human' || k === 'year' ? ix(a[0]) - ix(b[0]) : b[1].length - a[1].length)).map(([v, l]) => [v, l.sort(cmp)]);
}
const glab = (k, v) => v === '' ? 'Not coded' : lab(k, v);

/* ---------- facets (skeleton once; values refreshed) ---------- */
const LAYER_NOTE = k => k === 'layer' ? '<p><span class="k">A first triage.</span> A layer comes from the layer miner or from a researcher’s move. The layer pass has not been calibrated, so a layer is a starting sort, not a finding. A paper moved by hand is marked “moved by the researcher”; the miner’s own layer is given in its detail.</p>' : '';
function citeNote() {
  const c = C.citation;
  if (!c) return 'Reference lists have been read for ' + fmt(C.refs_done) + ' papers so far. A paper whose citers were never read shows none, which is not a known zero.';
  if (!c.extractions) return 'No reference list has been extracted, so every in-corpus citation count is unknown (not zero).';
  return 'Counts come from the ' + fmt(c.extractions) + ' works whose reference list was extracted (' + fmt(c.entries) + ' entries, ' + fmt(c.resolved_links) + ' resolved to a work of the project) out of ' + fmt(c.works_total) + ' works. A count is a lower bound: a citing work counts once, and a paper whose citers were never read shows none, which is not a known zero.';
}
const infoOf = ([k, l, , gk, def]) => HUB.info(`<b>${esc(l)}</b><p>${esc(gk && HUB.GLOSSARY[gk] ? HUB.GLOSSARY[gk][1] : def)}</p>${LAYER_NOTE(k)}<p><span class="k">How it's counted.</span> Each number is the papers that match your other filters and have this value. Values with none are dimmed.</p>`, 'About ' + l);
function sideSkeleton() {
  return GROUPS.map(g => `<details class="fg" data-g="${esc(g)}" ${g === 'Paper' || g === 'System' ? 'open' : ''}><summary>${esc(g)}<span class="ga"></span><button type="button" class="lnk" data-cg="${esc(g)}">Clear group</button></summary>` +
    DD.filter(x => x[2] === g).map(x => `<div class="fc" data-d="${x[0]}"><div class="fh">${esc(x[1])}${infoOf(x)}${ORD[x[0]].length > 10 ? `<input type="text" data-fq="${x[0]}" placeholder="Find a value" aria-label="Find a value in ${esc(x[1])}">` : ''}</div><div class="fv"></div></div>`).join('') + '</details>').join('');
}
function paintFacets() {
  for (const [k] of DD) {
    const cnt = {}; for (const w of W) if (ok(w, k)) for (const v of w._d[k]) cnt[v] = (cnt[v] || 0) + 1;
    const act = ST.f[k] || new Set(), fq = (ST.fq[k] || '').toLowerCase(); let vals = ORD[k];
    if (fq) vals = vals.filter(v => lab(k, v).toLowerCase().includes(fq));
    const lim = fq || ST.all[k] || vals.length <= 10 ? vals.length : 8;
    const shown = vals.filter((v, i) => i < lim || act.has(v));
    $(`.fc[data-d="${k}"] .fv`).innerHTML = shown.map(v => `<label class="fi ${act.has(v) ? 'on' : ''} ${cnt[v] ? '' : 'z'}"><input type="checkbox" data-d="${k}" data-v="${esc(v)}" ${act.has(v) ? 'checked' : ''}><i class="dot" style="background:${colorOf(k, v)}"></i><span class="fl" title="${esc(lab(k, v))}">${esc(lab(k, v))}</span><span class="n">${cnt[v] || 0}</span></label>`).join('')
      + (shown.length < vals.length ? `<button type="button" class="fmore" data-more="${k}">Show all ${fmt(vals.length)}</button>` : ST.all[k] && vals.length > 10 ? `<button type="button" class="fmore" data-more="${k}">Show fewer</button>` : '')
      + (vals.length ? '' : '<div class="meta">No match.</div>');
  }
  document.querySelectorAll('.fg').forEach(g => { const n = DD.filter(x => x[2] === g.dataset.g).reduce((a, x) => a + (ST.f[x[0]] ? ST.f[x[0]].size : 0), 0);
    g.querySelector('.ga').textContent = n ? n + ' active' : ''; g.querySelector('.lnk').style.visibility = n ? 'visible' : 'hidden'; if (n) g.open = true; });
}

/* ---------- chips and bar ---------- */
function paintBar(ws) {
  const chips = [];
  for (const [k, l] of DD.map(x => [x[0], x[1]])) for (const v of ST.f[k] || []) chips.push([`${l}: ${lab(k, v)}`, `data-k="${k}" data-v="${esc(v)}"`]);
  if (ST.q) chips.push([`Search: ${ST.q}`, 'data-x="q"']); if (ST.cite > 0) chips.push([`Cited here at least ${ST.cite}`, 'data-x="cite"']); if (ST.ft) chips.push(['With full text', 'data-x="ft"']); if (ST.month) chips.push([`Published ${ST.month}`, 'data-x="month"']);
  const one = k => ST.f[k] && ST.f[k].size === 1 ? [...ST.f[k]][0] : '';
  const ex = new URLSearchParams(); if (ST.q) ex.set('t', ST.q); if (one('human')) ex.set('h', one('human')); if (one('layer')) ex.set('l', one('layer'));
  const dp = new URLSearchParams(); for (const k of ['layer', 'human', 'technique', 'year']) if (one(k)) dp.set(k, one(k));
  const ids = ws.map(w => w.id), sel = [...ST.sel];
  const pathIds = (sel.length ? sel : ids).slice(0, 20);
  const chatIds = (sel.length ? sel : ids), layerOne = one('layer');
  const chatLinks = chatIds.length ? ` · <a href="${esc(HUB.chatHref({include: chatIds, only: true}))}" title="${chatIds.length > 60 ? 'The first 60 papers go into the basket; the Chat page says so.' : 'Open the Chat page with these papers in its basket.'}">Chat with these (${fmt(Math.min(chatIds.length, 60))})</a>` : '';
  const layerLink = layerOne ? ` · <a href="${esc(HUB.chatHref({layers: [layerOne]}))}">Chat with the whole layer: ${esc(H.layerLabel(layerOne))}</a>` : '';
  $('#cbar').innerHTML = `<span class="cnt">${fmt(ws.length)} of ${fmt(INS.size)} papers</span>${chips.map(c => `<button type="button" class="chip" ${c[1]} title="Remove this filter">${esc(c[0])} <span class="x">×</span></button>`).join('')}
    ${chips.length ? '<button type="button" class="chip" data-x="all">Clear all</button>' : ''}<span class="sp"></span>
    <a href="explore.html#${ex}">Explore these in rings</a> · <a href="data.html#${dp}">See their data</a>${pathIds.length && (sel.length || ids.length <= 20) ? ` · <a href="flow.html#lanes=${encodeURIComponent(pathIds.join(','))}">See their paths</a>` : ''}${chatLinks}${layerLink}`;
  const n = ST.sel.size, over = n > 200;
  $('#xgo').textContent = `Export selected (${n})`; $('#xgo').disabled = !n || over;
  $('#xmsg').textContent = over ? `${fmt(n)} selected; an export takes at most 200. Clear some or narrow the filter.` : ($('#xmsg').dataset.keep || '');
}

/* ---------- views ---------- */
const tagsOf = w => w._d.stage.map(s => `<span class="tag">${esc(pretty(s))}</span>`).join('');
const dateOf = w => w.published || w.year || '';
function snip(w) {
  if (!TERMS.length) return ''; const tl = w.title.toLowerCase(); if (TERMS.every(t => tl.includes(t))) return '';
  for (const s of [w.abstract || '', ...w._q]) { const i = s.toLowerCase().indexOf(TERMS[0]); if (i >= 0) { const a = Math.max(0, i - 60); return `<div class="sn">${a ? '…' : ''}${hl(s.slice(a, a + 200))}…</div>`; } }
  return '';
}
function rowHTML(w) {
  const hv = w._d.human[0], c = w.cited_in_corpus;
  return `<div class="cr" role="button" tabindex="-1" data-id="${esc(w.id)}" aria-selected="${ST.sel.has(w.id)}"><input type="checkbox" class="xs" data-id="${esc(w.id)}" ${ST.sel.has(w.id) ? 'checked' : ''} aria-label="Select this paper" title="Select"><div class="cm">
    <div class="ct">${hl(w.title)}${w.mapped_from ? ' <span class="meta" title="Its fields were read from a duplicate record of the same paper.">(read under a duplicate)</span>' : ''}${w.not_read_yet ? ' <span class="meta" title="Included, but no miner has read it yet.">(not read yet)</span>' : ''}</div>
    <div class="mt"><span>${esc(dateOf(w))}</span>${w._d.technique[0] ? `<span>${esc(lab('technique', w._d.technique[0]))}</span>` : ''}${w._d.field[0] ? `<span>${esc(lab('field', w._d.field[0]))}</span>` : ''}${hv ? `<span><i class="dot" style="background:${colorOf('human', hv)}"></i>${esc(lab('human', hv))}</span>` : ''}${w.layer_source === 'moved' ? `<span title="${esc('Moved to this layer by the researcher' + (w.layer_miner ? '; the miner said ' + H.layerLabel(w.layer_miner) : ''))}">moved by the researcher</span>` : ''}</div>
    ${snip(w)}<div class="stg">${tagsOf(w)}</div></div><div class="rt">${dnaHTML(w)}<span class="ci" title="Cited here: papers in this review that cite it (counted over the whole corpus, not the scope)">${c == null ? '–' : c} cited here</span><a class="chatadd meta" href="${esc(HUB.chatHref({include: [w.id], only: true}))}" title="Open the Chat page with this paper in its basket">Add to chat</a></div></div>`;
}
function viewList(ws) {
  VIS = []; let h = '';
  if (SRES && !SRES.n && SRES.N) return emptyScope();
  for (const [g, l] of groups(ws, ST.grp)) { if (ST.grp !== 'none') h += `<div class="cg">${esc(glab(ST.grp, g))} <span>${fmt(l.length)}</span></div>`; h += l.map(rowHTML).join(''); VIS.push(...l.map(w => w.id)); }
  return h || '<p class="meta">No papers match. Remove a filter to see more.</p>';
}
/* HS-04: an empty scope names itself and offers the reset. */
function emptyScope() {
  const f = SCOPE.format(SCOPE.current()).replace(/&/g, ', ');
  return `<p class="meta scope-empty-state" id="cempty">No paper falls in this scope${f ? ' (' + esc(f) + ')' : ''}. <button type="button" class="btn" data-scope-reset>Reset the scope</button></p>`;
}
function viewTimeline(ws) {
  const gk = ST.grp === 'none' ? 'technique' : ST.grp, months = [...new Set(W.map(w => w.month).filter(Boolean))].sort();
  let h = `<div class="scroll"><div class="axs">${months.map(m => `<div>${m.slice(2)}</div>`).join('')}</div>`;
  for (const [g, l] of groups(ws, gk)) { const by = {}; for (const w of l) (by[w.month] = by[w.month] || []).push(w);
    h += `<div class="lane"><b>${esc(glab(gk, g))} <span>${l.length}</span></b><div class="cells">${months.map(m => `<div class="cell">${(by[m] || []).map(w => `<span class="td" data-id="${esc(w.id)}" data-tt="${esc(w.title)}" style="background:${colorOf('technique', w._d.technique[0])}"></span>`).join('')}</div>`).join('')}</div></div>`; }
  return h + '</div><p class="meta">Colour is the technique.</p>';
}
function viewChrono(ws) {
  const months = [...new Set(ws.map(w => w.month).filter(Boolean))].sort(); if (!ST.rev) months.reverse();
  const by = {}; for (const w of ws) (by[w.month] = by[w.month] || []).push(w);
  return `<div class="scroll"><div class="chr">${months.map(m => `<div class="mon"><h4>${esc(m)} <span>${by[m].length}</span></h4>${by[m].sort(cmp).map(w => {
    const q = (w.desc.contribution && w.desc.contribution.q) || (w.cls.technique_primary && w.cls.technique_primary.q) || '', o = (OUT[w.slug] || []).length, i = (INN[w.slug] || []).length;
    return `<div class="card2" data-id="${esc(w.id)}">${esc(dateOf(w))}<b>${hl(w.title)}</b><span class="tag">${esc(lab('technique', w._d.technique[0] || ''))}</span> <span class="tag">${esc(lab('architecture', w._d.architecture[0] || ''))}</span> <span class="tag">${esc(lab('human', w._d.human[0] || ''))}</span>
      <div style="margin-top:5px">${w._d.stage.map(s => `<span class="sd" title="${esc(pretty(s))}" style="background:${colorOf('stage', s)}"></span>`).join('')}</div>${o || i ? `<div>cites ${o} · cited by ${i} here</div>` : ''}${q ? `<div class="qt">“${esc(q.slice(0, 200))}”</div>` : ''}${w.doc ? `<div><a href="${esc(w.doc.inspector)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Open the converted document (${esc(w.doc.kind)})</a></div>` : ''}</div>`; }).join('')}</div>`).join('') || '<p class="meta">No papers match.</p>'}</div></div>`;
}
function viewLineage(ws) {
  const inSet = new Set(ws.map(w => w.slug)), edges = C.cites.filter(([a, b]) => inSet.has(a) && inSet.has(b)), linked = new Set(edges.flat());
  const list = ST.lnAll ? ws : ws.filter(w => linked.has(w.slug)), months = [...new Set(list.map(w => w.month).filter(Boolean))].sort().reverse(), col = {}; months.forEach((m, i) => col[m] = i);
  const by = {}; for (const w of list) (by[w.month] = by[w.month] || []).push(w);
  const pos = {}, CW = 196, RH = 62, TOP = 26; let mr = 0;
  for (const m of months) { by[m].sort((a, b) => (b.published || '').localeCompare(a.published || '')).forEach((w, i) => { pos[w.slug] = {x: col[m] * CW + 8, y: TOP + i * RH}; }); mr = Math.max(mr, by[m].length); }
  const Wd = months.length * CW + 20, Ht = TOP + mr * RH + 20;
  return `<label class="meta" style="display:inline-flex;gap:6px;margin-bottom:8px"><input type="checkbox" id="lnall" ${ST.lnAll ? 'checked' : ''}> Show papers without links</label>
   <div class="lnw" id="lnw"><div style="position:relative;width:${Wd}px;height:${Ht}px"><svg width="${Wd}" height="${Ht}"></svg>${months.map(m => `<div class="mh" style="left:${col[m] * CW + 8}px">${esc(m)} (${by[m].length})</div>`).join('')}
   ${list.map(w => { const p = pos[w.slug], bo = w.sum && w.sum.builds_on ? ' · builds on: ' + w.sum.builds_on.v : ''; return `<div class="nd" data-s="${esc(w.slug)}" data-id="${esc(w.id)}" title="${esc(w.title + bo)}" style="left:${p.x}px;top:${p.y}px;border-left-color:${colorOf('technique', w._d.technique[0])}"><div class="d">${esc(dateOf(w))} · ${esc(lab('technique', w._d.technique[0] || ''))}</div>${esc(w.title.slice(0, 70))}</div>`; }).join('')}</div></div>
   <p class="meta">${fmt(linked.size)} papers have a citation link here (${fmt(edges.length)} links).</p>`;
}
function wireLineage(ws) {
  const wrap = $('#lnw'); if (!wrap) return; $('#lnall').onchange = e => { ST.lnAll = e.target.checked; render(); };
  const inSet = new Set(ws.map(w => w.slug)), edges = C.cites.filter(([a, b]) => inSet.has(a) && inSet.has(b)), pos = {};
  wrap.querySelectorAll('.nd').forEach(n => { pos[n.dataset.s] = {x: parseInt(n.style.left), y: parseInt(n.style.top)}; });
  const svg = wrap.querySelector('svg'), P = (a, b, cls) => { const pa = pos[a], pb = pos[b]; if (!pa || !pb) return ''; const x1 = pa.x + 176, y1 = pa.y + 27, x2 = pb.x, y2 = pb.y + 27, dx = Math.max(30, Math.abs(x2 - x1) / 2);
    return `<path class="ed ${cls}" d="${pb.x > pa.x ? `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` : `M${x1},${y1} C${x1 + 60},${y1 - 30} ${x1 + 60},${y2 + 30} ${pb.x + 176},${y2}`}"/>`; };
  const draw = hl2 => { svg.innerHTML = edges.filter(([a, b]) => pos[a] && pos[b]).map(([a, b]) => P(a, b, hl2 && hl2.has(a + '>' + b) ? 'hl' : '')).join(''); }; draw(null);
  const chain = s => { const anc = new Set(), desc = new Set(), he = new Set(); let st = [s];
    while (st.length) { const x = st.pop(); for (const y of OUT[x] || []) { he.add(x + '>' + y); if (!anc.has(y)) { anc.add(y); st.push(y); } } }
    st = [s]; while (st.length) { const x = st.pop(); for (const y of INN[x] || []) { he.add(y + '>' + x); if (!desc.has(y)) { desc.add(y); st.push(y); } } } return {anc, desc, he}; };
  wrap.querySelectorAll('.nd').forEach(n => n.onclick = () => { const s = n.dataset.s, c = chain(s);
    wrap.querySelectorAll('.nd').forEach(m => { const k = m.dataset.s; m.classList.remove('sel', 'anc', 'desc', 'dim'); m.classList.add(k === s ? 'sel' : c.anc.has(k) ? 'anc' : c.desc.has(k) ? 'desc' : 'dim'); });
    draw(c.he); openWork(slugMap.get(s)); });
}
function viewGraph() {
  return `<div class="gwrap"><div class="gtog">${[['technique','Technique'],['field','Field'],['human','Human role'],['stage','Lifecycle stage'],['cites','Citations']].map(([k, l]) => `<button type="button" class="chip" data-g="${k}" aria-pressed="${GD.has(k)}">${l}</button>`).join('')}<span class="meta">Drag, scroll to zoom, click a paper</span></div><canvas></canvas></div>`;
}
let gstop = null;
function wireGraph(ws) {
  if (gstop) gstop(); const box = $('.gwrap'); if (!box) return;
  box.querySelectorAll('[data-g]').forEach(b => b.onclick = () => { GD.has(b.dataset.g) ? GD.delete(b.dataset.g) : GD.add(b.dataset.g); render(); });
  const cv = box.querySelector('canvas'), dpr = window.devicePixelRatio || 1, cw = cv.clientWidth, ch = cv.clientHeight; cv.width = cw * dpr; cv.height = ch * dpr; const g = cv.getContext('2d');
  const nodes = [], idx = {}, edges = [], ced = [], node = (k, o) => { if (!(k in idx)) { idx[k] = nodes.length; nodes.push(Object.assign({k, x: Math.random() * 600 - 300, y: Math.random() * 400 - 200, vx: 0, vy: 0, deg: 0}, o)); } return idx[k]; };
  for (const w of ws) { const a = node('w:' + w.id, {w, r: 3});
    for (const k of ['technique', 'field', 'human']) { const v = GD.has(k) ? w._d[k][0] : ''; if (v) { const b = node(k + ':' + v, {label: lab(k, v), cat: k, r: 6}); edges.push([a, b]); nodes[b].deg++; } }
    if (GD.has('stage')) for (const s of w._d.stage) { const b = node('stage:' + s, {label: pretty(s), cat: 'stage', r: 6}); edges.push([a, b]); nodes[b].deg++; } }
  if (GD.has('cites')) for (const [a, b] of C.cites) { const x = slugMap.get(a), y = slugMap.get(b); if (x && y && ('w:' + x.id) in idx && ('w:' + y.id) in idx) ced.push([idx['w:' + x.id], idx['w:' + y.id]]); }
  for (const n of nodes) if (n.cat) n.r = 5 + Math.sqrt(n.deg) * 1.6;
  const catCol = () => ({technique: HUB.cssv('--l-core'), field: HUB.cssv('--l-benchmark'), human: HUB.cssv('--h-collab'), stage: HUB.cssv('--h-physical')});
  let cam = {x: 0, y: 0, z: 0.9}, drag = null, hover = null, it = 0, alive = true, CC = catCol(); const fg = HUB.cssv('--fg'), edge = HUB.cssv('--dim'), cite = HUB.cssv('--exc');
  const step = () => { const a = Math.max(0.02, 1 - it / 400); it++;
    for (let i = 0; i < nodes.length; i++) { const p = nodes[i]; for (let j = i + 1; j < nodes.length; j++) { const q = nodes[j]; const dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy + 0.1; if (d2 > 250000) continue; const f = (p.cat && q.cat ? 9000 : (p.cat || q.cat ? 1800 : 220)) / d2; p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f; } }
    const spring = (list, k, rest) => { for (const [i, j] of list) { const p = nodes[i], q = nodes[j], dx = q.x - p.x, dy = q.y - p.y, dist = Math.sqrt(dx * dx + dy * dy) + 0.01, f = k * (dist - rest(q)) / dist; p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f; } };
    spring(edges, 0.02, q => 28 + Math.sqrt(q.deg || 1) * 9); spring(ced, 0.05, () => 45);
    for (const p of nodes) { p.vx -= p.x * 0.0012; p.vy -= p.y * 0.0012; if (p !== drag) { p.x += p.vx * a * 0.5; p.y += p.vy * a * 0.5; } p.vx *= 0.6; p.vy *= 0.6; } };
  const draw = () => { g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, cw, ch); g.translate(cw / 2 + cam.x, ch / 2 + cam.y); g.scale(cam.z, cam.z);
    g.globalAlpha = .18; g.strokeStyle = edge; g.lineWidth = 1 / cam.z; g.beginPath(); for (const [i, j] of edges) { g.moveTo(nodes[i].x, nodes[i].y); g.lineTo(nodes[j].x, nodes[j].y); } g.stroke(); g.globalAlpha = .8;
    g.strokeStyle = cite; g.fillStyle = cite; g.lineWidth = 1.4 / cam.z;
    for (const [i, j] of ced) { const p = nodes[i], q = nodes[j]; g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(q.x, q.y); g.stroke(); const an = Math.atan2(q.y - p.y, q.x - p.x), s = 6 / cam.z, cx = q.x - Math.cos(an) * q.r, cy = q.y - Math.sin(an) * q.r;
      g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx - Math.cos(an) * s + Math.sin(an) * s / 2, cy - Math.sin(an) * s - Math.cos(an) * s / 2); g.lineTo(cx - Math.cos(an) * s - Math.sin(an) * s / 2, cy - Math.sin(an) * s + Math.cos(an) * s / 2); g.closePath(); g.fill(); }
    for (const n of nodes) { g.beginPath(); g.arc(n.x, n.y, n.r, 0, 7); g.fillStyle = n.cat ? CC[n.cat] : colorOf('technique', n.w._d.technique[0]); g.globalAlpha = n === hover || (n.w && n.w.id === ST.id) ? 1 : .85; g.fill();
      if (n.w && n.w.id === ST.id) { g.lineWidth = 2 / cam.z; g.strokeStyle = fg; g.stroke(); } }
    g.globalAlpha = 1; g.fillStyle = fg; g.font = (11 / cam.z) + 'px Inter,system-ui,sans-serif'; for (const n of nodes) if (n.cat || n === hover) g.fillText(n.label || n.w.title.slice(0, 70), n.x + n.r + 2, n.y + 3); };
  const loop = () => { if (!alive || !document.body.contains(cv)) return; if (it < 700 || drag) step(); draw(); requestAnimationFrame(loop); }; loop();
  gstop = () => { alive = false; };
  const pos = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left - r.width / 2 - cam.x) / cam.z, (e.clientY - r.top - r.height / 2 - cam.y) / cam.z]; };
  const pick = e => { const [x, y] = pos(e); let b = null, bd = 1e9; for (const n of nodes) { const dd = (n.x - x) ** 2 + (n.y - y) ** 2; if (dd < (n.r + 4) ** 2 && dd < bd) { b = n; bd = dd; } } return b; };
  let moved = 0;
  cv.onpointerdown = e => { cv.setPointerCapture(e.pointerId); moved = 0; const n = pick(e); if (n) { drag = n; it = Math.min(it, 300); } else drag = {pan: true, sx: e.clientX, sy: e.clientY, cx: cam.x, cy: cam.y}; };
  cv.onpointermove = e => { if (drag && drag.pan) { cam.x = drag.cx + e.clientX - drag.sx; cam.y = drag.cy + e.clientY - drag.sy; moved++; } else if (drag) { [drag.x, drag.y] = pos(e); moved++; } else { hover = pick(e); HUB.tipHtml(hover ? esc(hover.label || hover.w.title) : '', e); } };
  cv.onpointerup = e => { const n = pick(e); if (drag && !drag.pan && n === drag && n.w && moved < 4) openWork(n.w); drag = null; };
  cv.onpointerleave = () => { hover = null; HUB.tipHtml('', {}); };
  cv.onwheel = e => { e.preventDefault(); cam.z = Math.min(4, Math.max(.2, cam.z * (e.deltaY < 0 ? 1.1 : .9))); };
}

/* ---------- detail pane ---------- */
const SUMF = [['problem_gap','Problem and gap'],['core_innovation','Core innovation'],['contribution_type','Contribution type'],['innovation_axis','Novelty is about'],['builds_on','Builds on'],['builds_on_relation','Relation'],['improves_over','Improves over'],['improvement_aspect','Improves'],['benchmark_role','Benchmark'],['benchmark_named','Benchmark named'],['headline_result','Headline result'],['validation_level','Validation'],['claimed_discovery','Claimed discovery'],['failure_modes','Failure modes'],['limitations','Limitations'],['future_work','Future work'],['availability','Availability'],['cost_compute','Cost and compute']];
const fv = (k, v) => k === 'human_position' ? H.humanLabel(v) : /^[a-z0-9][a-z0-9-]*$/.test(String(v)) && String(v).length < 48 ? pretty(v) : String(v);
const qb = o => o.q && o.q !== o.v ? `<blockquote class="quote">“${hl(o.q)}” <span class="meta">${esc(o.a || '')}</span></blockquote>` : '';
const kv = o => Object.keys(o || {}).sort().map(k => `<div class="kv"><b>${esc(FL(k))}</b> ${esc(fv(k, o[k].v))}${qb(o[k])}</div>`).join('') || '<div class="meta">None recorded.</div>';
const copy = c => `<div class="cmd"><code>${esc(c)}</code><button type="button" class="btn" data-copy="${esc(c)}">Copy</button></div>`;
const off = t => `<button type="button" class="btn" disabled title="Available in the live hub">${t}</button>`;
/* Researcher acts (served mode only): the existing mine / layer routes, each behind an inline confirmation. */
const actsHTML = w => HUB.served
  ? `<button type="button" class="btn" data-act="mine-work">Mine this work</button>
     <select id="mvl" aria-label="Layer to move to"></select><input id="mvr" type="text" placeholder="Reason (required)" aria-label="Reason for moving" size="22">
     <button type="button" class="btn" data-act="move">Move to layer</button>
     <button type="button" class="btn" data-act="mine-layer"${w.layer && w.layer !== 'unlayered' ? '' : ' disabled'}>Mine this layer</button>
     <div id="actmsg" class="meta" aria-live="polite"></div>`
  : `${off('Mine this work')}${off('Move to layer')}${off('Mine this layer')}`;
let LAYER_IDS = null;
const say = (host, ok, j, what) => { host.textContent = ok ? what : 'Refused: ' + HUB.issues(j); };
function wireActs(w) {
  const p = $('#cdet'), host = p.querySelector('#actmsg'), sel = p.querySelector('#mvl');
  if (!host || !sel) return;
  (LAYER_IDS ? Promise.resolve(LAYER_IDS) : HUB.get('/api/layers').then(r => r.json()).then(j => (LAYER_IDS = j.layers || []))).then(ids => {
    sel.innerHTML = ids.map(l => `<option value="${esc(l)}"${l === w.layer ? ' selected' : ''}>${esc(H.layerLabel(l))}</option>`).join('');
  }).catch(() => { sel.disabled = true; });
  const run = (path, body, done) => HUB.act(path, body).then(r => r.json().then(j => say(host, r.ok, j, done)));
  p.querySelector('[data-act="mine-work"]').onclick = () =>
    HUB.confirm(host, 'Ask for this paper to be mined?', () => run('/api/mine/work', {work_id: w.id}, 'Mining requested for this paper.'));
  p.querySelector('[data-act="mine-layer"]').onclick = () =>
    HUB.confirm(host, 'Ask for every included paper of this layer to be mined?', () => run('/api/mine/layer', {layer: w.layer}, 'Mining requested for the layer.'));
  p.querySelector('[data-act="move"]').onclick = () => {
    const reason = p.querySelector('#mvr').value.trim();
    if (!reason) { host.textContent = 'Give a reason first; it is recorded with the move.'; return; }
    HUB.confirm(host, 'Move this paper to “' + H.layerLabel(sel.value) + '”?', () => run('/api/layers/move', {work_id: w.id, layer: sel.value, reason}, 'Moved. The page shows it after the next update.'));
  };
}
function detailHTML(w) {
  const s = w.sum || {}, o = OUT[w.slug] || [], i = INN[w.slug] || [], P = d.shell.slug || 'PROJECT';
  const L = l => l.map(x => slugMap.get(x)).filter(Boolean).map(x => `<li><a data-open="${esc(x.id)}">${esc(x.title)}</a> <span class="meta">${esc(dateOf(x))}</span></li>`).join('') || '<li class="meta">None found yet.</li>';
  const src = w.layer_source === 'moved' ? ` (moved by the researcher${w.layer_miner ? '; the miner said ' + esc(H.layerLabel(w.layer_miner)) : ''})` : w.layer_source === 'miner' ? ' (from the miner)' : '';
  const links = [w.doi ? `<a href="https://doi.org/${esc(w.doi)}" target="_blank" rel="noopener">DOI</a>` : '', w.arxiv ? `<a href="https://arxiv.org/abs/${esc(w.arxiv)}" target="_blank" rel="noopener">arXiv</a>` : '', `<a href="flow.html#lanes=${encodeURIComponent(w.id)}">See its path</a>`, `<a href="${esc(HUB.chatHref({include: [w.id], only: true}))}">Spar with this paper</a>`].filter(Boolean).join(' · ');
  return `<div style="display:flex;justify-content:space-between;align-items:center"><span class="meta"><i class="dot" style="background:${colorOf('layer', w._d.layer[0])}"></i> ${esc(H.layerLabel(w._d.layer[0]))}${src}</span><button type="button" class="btn" id="cdClose">Close <span class="kbd">Esc</span></button></div>
  <h2 class="display" style="font-size:28px;margin:14px 0 8px">${hl(w.title)}</h2>
  <p class="meta">${esc((w.authors || []).join(', ') || 'No author recorded')} · ${esc(dateOf(w))}${w.venue ? ' · ' + esc(w.venue) : ''}${w.cited_by != null ? ' · cited by ' + w.cited_by + ' elsewhere' : ''}</p>
  <p class="meta">${HUB.term('cic', 'Cited here')} <b class="num">${w.cited_in_corpus ?? 0}</b> times · ${links}${w.doc ? ` · full text on file (${esc(w.doc.kind)}): <a href="${esc(w.doc.inspector)}" target="_blank" rel="noopener">Conversion inspector</a> ${HUB.served ? `<a class="btn" href="file/original/${encodeURIComponent(w.id)}" target="_blank" rel="noopener">Open the original ${esc(w.doc.kind)}</a>` : `<button type="button" class="btn" disabled title="Available in the live hub">Open the original ${esc(w.doc.kind)}</button>`} ${HUB.info('The stored original file, as it was fetched. The conversion inspector shows it beside the extracted text.', 'About the original file')}` : ' · no full text on file'}</p>
  ${w.not_read_yet ? `<p class="meta">Included, but no miner has read it yet, so it has no coded values.</p>` : ''}
  ${w.mapped_from ? `<p class="meta">Its fields were read from a duplicate record of the same paper (<span class="mono">${esc(w.mapped_from)}</span>).</p>` : ''}
  <p style="margin:8px 0">${dnaHTML(w)}</p>
  <details><summary class="h3" style="cursor:pointer">Abstract</summary><p style="font-size:var(--t-s)">${w.abstract ? hl(w.abstract) : '<span class="meta">No abstract recorded.</span>'}</p></details>
  <h3 class="h3">Structured summary</h3>${Object.keys(s).length ? SUMF.filter(([k]) => s[k]).map(([k, l]) => `<div class="kv"><b>${l}</b> ${esc(s[k].v)}${s[k].q && s[k].q !== s[k].v && !s[k].v.startsWith(s[k].q.slice(0, 30)) ? `<blockquote class="quote">“${hl(s[k].q)}” <span class="meta">${esc(s[k].a || '')}</span></blockquote>` : ''}</div>`).join('') : '<div class="meta">Not read for this paper yet.</div>'}
  <h3 class="h3">Citations within the corpus ${HUB.info(esc(citeNote()), 'About citations')} ${SCOPE.label('corpus')}</h3>
  <b class="meta">Cites</b><ul>${L(o)}</ul><b class="meta">Cited by</b><ul>${L(i)}</ul>
  <h3 class="h3">Lifecycle stages</h3>${w.stages.map(x => `<div class="kv"><span class="tag">${esc(pretty(x.stage))}</span> <span class="meta">${esc(x.mode || '')}</span><blockquote class="quote">“${hl(x.quote)}” <span class="meta">${esc(x.anchor || '')}</span></blockquote></div>`).join('') || '<div class="meta">None recorded.</div>'}
  <h3 class="h3">Classification</h3>${kv(w.cls)}<h3 class="h3">Process, human role, blueprint</h3>${kv(w.map)}<h3 class="h3">Descriptors</h3>${kv(w.desc)}
  <h3 class="h3">Results ${w.n_design ? `<span class="meta">${fmt(w.n_design)} rows</span>` : ''}</h3>${w.design.slice(0, 12).map(r => `<div class="kv">${esc(r.system)} · ${esc(pretty(r.stage))} · ${esc(pretty(r.approach))} <span class="meta">${esc(pretty(r.system_role || ''))} · ${esc(pretty(r.evidence_grade || ''))}</span></div>`).join('') || '<div class="meta">No rows.</div>'}
  <h3 class="h3">Mine and layer</h3><div class="acts">${actsHTML(w)}</div>
  <h3 class="h3">What you can do</h3>${w.doc ? `<p class="meta"><a href="sources.html#tab=conversion&amp;conv=${encodeURIComponent(w.id)}">Conversion inspector</a>: the original beside its extracted text. <a href="${esc(w.doc.inspector)}" target="_blank" rel="noopener">Classic page</a></p>` : ''}${copy(`factory --project ${P} document read ${w.id}`)}${copy(`factory --project ${P} trace ${w.id}`)}<p class="meta">Each value was read by a model from the converted document (pass A), and every value is quoted from it; a second reading of a sample checks the first. The Miners page gives the sample and the agreement.</p>`;
}
function openWork(w, silent) {
  if (!w) return; ST.id = w.id; const p = $('#cdet'); p.innerHTML = detailHTML(w); p.setAttribute('open', ''); p.scrollTop = 0; if (!silent) writeHash();
  if (HUB.served) wireActs(w);
  $('#cdClose').onclick = closeWork; p.querySelectorAll('[data-open]').forEach(a => a.onclick = () => openWork(idMap.get(a.dataset.open)));
  p.querySelectorAll('[data-copy]').forEach(b => b.onclick = () => { try { navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; } catch (e) { b.textContent = 'Select and copy'; } });
}
function closeWork() { ST.id = ''; $('#cdet').removeAttribute('open'); writeHash(); }

/* ---------- render ---------- */
function render() {
  if (gstop) gstop();
  applyScope(); SCOPE.renderLine($('#cscope'), SRES, {});
  const ws = W.filter(w => ok(w)); paintFacets(); paintBar(ws);
  $('#viewSeg').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === ST.view));
  $('#cq').value !== ST.q && ($('#cq').value = ST.q); $('#sortby').value = ST.sort; $('#grp').value = ST.grp; $('#rev').setAttribute('aria-pressed', ST.rev);
  $('#cite').value = ST.cite || ''; $('#ft').checked = ST.ft; $('#grp').disabled = false;
  const v = ST.view, cv = $('#cv');
  if (SRES.n === 0 && SRES.N > 0) VIS = [];
  cv.innerHTML = SRES.n === 0 && SRES.N > 0 ? emptyScope() : v === 'list' ? viewList(ws) : v === 'timeline' ? viewTimeline(ws) : v === 'chrono' ? viewChrono(ws) : v === 'lineage' ? viewLineage(ws) : viewGraph();
  if (v === 'lineage') wireLineage(ws); if (v === 'graph') wireGraph(ws);
  if (v === 'list') { ST.cur = Math.min(ST.cur, VIS.length - 1); mark(); }
  writeHash();
}
function mark() { document.querySelectorAll('.cr.cur').forEach(r => r.classList.remove('cur')); const id = VIS[ST.cur]; if (id) { const r = document.querySelector(`.cr[data-id="${CSS.escape(id)}"]`); if (r) { r.classList.add('cur'); r.scrollIntoView({block: 'nearest'}); } } }

/* ---------- page shell ---------- */
const infoPage = `<b>What it shows</b> The included papers, with what the miners read from each one.<p><span class="k">How to read it.</span> Tick values on the left to narrow every view; the counts update as you go. Open a paper to see each value beside the sentence it came from. List, Timeline, Chronology, Lineage and Graph are five ways to look at the same filtered set.</p><p><span class="k">How it's computed.</span> Counts come from the corpus payload. Search looks in titles, abstracts and the quotes. Select papers to download their ids for the factory export command.</p><p>Other pages link here with a filter in the address (for example <span class="mono">#technique=…</span>, <span class="mono">#month=2025-03</span> or <span class="mono">#id=…</span>); the filters shown above the list are those in force, and each can be removed.</p>`;
$('#main').innerHTML = H.header({title: 'Corpus', level: 1, infoHtml: infoPage, sub: 'Filter the papers, then open one to see each value with its quote.'}) + `
<div class="ctool"><input type="text" class="q" id="cq" placeholder="Search titles, abstracts and quotes" aria-label="Search titles, abstracts and quotes"><span class="kbd" title="Press f to search">f</span>
 <span class="seg" id="viewSeg">${VIEWS.map(v => `<button type="button" data-v="${v[0]}">${v[1]}</button>`).join('')}</span><button type="button" class="btn ftoggle" id="ftog">Filters</button></div>
<div class="ctool"><label>Group by <select id="grp">${DD.map(x => `<option value="${x[0]}">${x[1]}</option>`).join('')}<option value="none">None</option></select></label>
 <label>Sort <select id="sortby">${SORTS.map(s => `<option value="${s[0]}">${s[1]}</option>`).join('')}</select></label><button type="button" class="btn" id="rev" aria-pressed="false">Reverse</button>
 <label>${HUB.term('cic', 'Cited here')} at least <input type="number" id="cite" min="0" step="1"></label><label><input type="checkbox" id="ft"> With full text</label></div>
<div id="cscope"></div>
<div class="cbar" id="cbar"></div>
<div class="csel"><button type="button" class="btn" id="xall">Select all in filter</button><button type="button" class="btn primary" id="xgo" disabled>Export selected (0)</button><button type="button" class="btn" id="xclr">Clear</button><span class="meta" id="xmsg"></span><span id="xact"></span></div>
<div class="cwrap"><aside class="cside" id="cside" aria-label="Filters">${sideSkeleton()}</aside><section id="cv" aria-live="polite"></section></div>
<p class="note cfoot">${HUB.info(esc(H.SETS_NOTE), 'About the paper sets')}<span class="meta">About these sets</span></p>`;
document.body.insertAdjacentHTML('beforeend', '<aside id="cdet" aria-label="Paper"></aside>');
refreshColors(); readHash();

/* ---------- events ---------- */
const side = $('#cside');
side.addEventListener('change', e => { const t = e.target; if (!t.dataset.d) return; const s = ST.f[t.dataset.d] || (ST.f[t.dataset.d] = new Set()); t.checked ? s.add(t.dataset.v) : s.delete(t.dataset.v); render(); });
side.addEventListener('input', e => { const k = e.target.dataset.fq; if (k) { ST.fq[k] = e.target.value; paintFacets(); } });
side.addEventListener('click', e => {
  const m = e.target.closest('[data-more]'); if (m) { ST.all[m.dataset.more] = !ST.all[m.dataset.more]; paintFacets(); }
  const c = e.target.closest('[data-cg]'); if (c) { e.preventDefault(); e.stopPropagation(); DD.filter(x => x[2] === c.dataset.cg).forEach(x => delete ST.f[x[0]]); render(); } });
$('#cbar').addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return;
  if (b.dataset.k) ST.f[b.dataset.k].delete(b.dataset.v); else if (b.dataset.x === 'q') setQ(''); else if (b.dataset.x === 'cite') ST.cite = 0; else if (b.dataset.x === 'ft') ST.ft = false; else if (b.dataset.x === 'month') ST.month = ''; else if (b.dataset.x === 'all') { ST.f = {}; setQ(''); ST.cite = 0; ST.ft = false; ST.month = ''; }
  render(); });
$('#cq').oninput = e => { setQ(e.target.value); render(); };
$('#viewSeg').onclick = e => { const b = e.target.closest('button'); if (b) { ST.view = b.dataset.v; render(); } };
$('#grp').onchange = e => { ST.grp = e.target.value; render(); }; $('#sortby').onchange = e => { ST.sort = e.target.value; render(); };
$('#rev').onclick = () => { ST.rev = !ST.rev; render(); }; $('#cite').oninput = e => { ST.cite = parseInt(e.target.value, 10) || 0; render(); }; $('#ft').onchange = e => { ST.ft = e.target.checked; render(); };
$('#ftog').onclick = () => side.classList.toggle('show');
$('#xall').onclick = () => { W.filter(w => ok(w)).forEach(w => ST.sel.add(w.id)); $('#xmsg').dataset.keep = ''; render(); };
$('#xclr').onclick = () => { ST.sel.clear(); $('#xmsg').dataset.keep = ''; render(); };
/* Served: a zip of the converted Markdown and a manifest from the existing export route (optionally with the PDFs). */
function serveExport() {
  const host = $('#xact'), ids = [...ST.sel], box = document.createElement('label');
  box.className = 'meta'; box.innerHTML = '<input type="checkbox" id="xpdf"> include the PDFs (licensed files)';
  HUB.confirm(host, 'Export ' + fmt(ids.length) + ' selected paper' + (ids.length === 1 ? '' : 's') + ' as a zip?', () => {
    const pdfs = box.querySelector('input').checked;
    return HUB.act('/api/export/works', {work_ids: ids, pdfs, confirm: pdfs}).then(r => {
      if (!r.ok) return r.json().then(j => { host.textContent = 'Refused: ' + HUB.issues(j); });
      const name = (/filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '') || [])[1] || 'export.zip';
      return r.blob().then(b => {
        const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
        host.textContent = 'Saved ' + name + '.';
      });
    });
  }, box);
}
$('#xgo').onclick = () => {
  if (HUB.served) return serveExport();
  const ids = [...ST.sel], cmd = 'factory export works --from-file work-ids.txt --out export.zip';
  const txt = '# Work ids selected in the hub Corpus page. Export their converted documents with:\n# ' + cmd + '\n' + ids.join('\n') + '\n';
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([txt], {type: 'text/plain'})); a.download = 'work-ids.txt'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  $('#xmsg').dataset.keep = 'Saved work-ids.txt. To get the documents, run: ' + cmd; paintBar(W.filter(w => ok(w))); };
const cv = $('#cv');
cv.addEventListener('click', e => {
  if (e.target.closest('[data-scope-reset]')) { SCOPE.reset(); return; }
  if (e.target.closest('a.chatadd')) return; /* a plain link to the Chat page: no server write */
  if (e.target.closest('input.xs')) { const c = e.target.closest('input.xs'); c.checked ? ST.sel.add(c.dataset.id) : ST.sel.delete(c.dataset.id); c.closest('.cr').setAttribute('aria-selected', c.checked); paintBar(W.filter(w => ok(w))); return; }
  const r = e.target.closest('.cr, .td, .card2'); if (r && r.dataset.id) { if (r.classList.contains('cr')) { ST.cur = VIS.indexOf(r.dataset.id); mark(); } openWork(idMap.get(r.dataset.id)); } });
document.addEventListener('mouseover', e => { const t = e.target.closest('.td'); if (t) return HUB.tip(t.dataset.tt, e); const n = e.target.closest('[data-dna]'); if (n) HUB.tipHtml(tipDNA(idMap.get(n.dataset.dna)), e); });
document.addEventListener('mousemove', e => { if (e.target.closest('.td, [data-dna]') && $('#tip').style.display === 'block') HUB.tipAt(e); });
document.addEventListener('mouseout', e => { if (e.target.closest('.td, [data-dna]')) HUB.tipHtml('', e); });
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === 'Escape' && $('#cdet').hasAttribute('open') && !$('#drawer').hasAttribute('open')) { closeWork(); return; }
  if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
  if (e.key === 'f') { e.preventDefault(); $('#cq').focus(); return; }
  if (ST.view !== 'list' || !VIS.length) return;
  if (e.key === 'j' || e.key === 'k') { ST.cur = Math.max(0, Math.min(VIS.length - 1, ST.cur + (e.key === 'j' ? 1 : -1))); mark(); }
  else if (e.key === 'Enter' && VIS[ST.cur]) openWork(idMap.get(VIS[ST.cur]));
  else if (e.key === 'x' && VIS[ST.cur]) { const id = VIS[ST.cur]; ST.sel.has(id) ? ST.sel.delete(id) : ST.sel.add(id); const r = document.querySelector(`.cr[data-id="${CSS.escape(id)}"]`); if (r) { r.setAttribute('aria-selected', ST.sel.has(id)); r.querySelector('input.xs').checked = ST.sel.has(id); } paintBar(W.filter(w => ok(w))); } });
SCOPE.onChange(() => render());
document.addEventListener('hub:theme', () => { refreshColors(); render(); });
window.addEventListener('hashchange', () => { const before = ST.id; readHash(); render(); if (ST.id && ST.id !== before) openWork(idMap.get(ST.id), true); else if (!ST.id) $('#cdet').removeAttribute('open'); });
render(); if (ST.id) openWork(idMap.get(ST.id), true);
}).catch(e => {
  document.body.textContent = 'Corpus failed to load: ' + e.message;
});
