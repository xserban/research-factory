/* Flow page: where the records went (Sankey, every record, record list), screening, replay, paths.
   Payloads: shell, flow (prisma figures, per-record fates), screening, journeys (replay frames;
   journey_index when the build carries it). Every number is read or computed from them. */
HUB.load(['shell', 'flow', 'screening', 'journeys']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'flow', crumb: 'Flow' });
  FlowPage(H, d);
}).catch(e => { document.body.textContent = 'Flow failed to load: ' + e.message; });

function FlowPage(H, d) {
const { esc, fmt, $ } = H;
const sum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);
const cssv = n => H.cssv(n);
const dayFmt = s => new Date(s * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const stampFmt = s => new Date(s * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC';
const durFmt = s => s < 5400 ? Math.max(1, Math.round(s / 60)) + ' min' : s < 172800 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d';
Object.assign(H.GLOSSARY, {
  kappa: ['Cohen’s kappa', 'Agreement between two readers, corrected for the agreement chance alone would give. 1 is perfect agreement, 0 is no better than chance.'],
  rank: ['Ranked order', 'Records are screened best-ranked first, so inclusions should pile up early; a straight diagonal would mean the ranking added nothing.'],
});

/* ---------- data ---------- */
const F = d.flow.prisma, FT = F.full_text || {}, R = d.flow.records, RI = new Map(R.map(r => [r.id, r]));
const st = { identified: d.flow.identified, dup: F.duplicates_removed, screened: F.screened, taEx: sum(F.excluded), taInc: F.included,
  nsg: FT.not_sought, sgt: FT.sought, nrt: FT.not_retrieved, pen: FT.pending, ass: FT.assessed, ftEx: sum(FT.excluded), inc: FT.included };
const EXK = Object.keys(F.excluded).filter(k => F.excluded[k]), FXK = Object.keys(FT.excluded || {}).filter(k => FT.excluded[k]);
const CRIT = {}; for (const w of d.screening.reasons_wall) if (!CRIT[w.criterion]) CRIT[w.criterion] = w;
const critLabel = k => (CRIT[k] && CRIT[k].label) || k;
const FATE = { duplicate: 'Duplicate', ta_excluded: 'Excluded at title and abstract', ta_pending: 'Pending at title and abstract', not_sought: 'Not sought',
  not_retrieved: 'Not retrieved', ft_excluded: 'Excluded at full text', ft_pending: 'Pending at full text', included: 'Included' };
const outcomeOf = r => (FATE[r.fate] || r.fate) + (r.criterion ? ' · ' + r.criterion : '');
const titleOf = id => (H.byId.get(id) || RI.get(id) || {}).title || id;
const lbl = s => ({ 'title-abstract': 'Title and abstract', 'full-text': 'Full text' }[s] || H.pretty(s));
const SRC = [...Object.entries(F.identified_databases || {}), ...Object.entries(F.identified_other || {})].filter(([, n]) => n);
const IDS = (...f) => r => f.includes(r.fate);
const PRED = {
  identified: () => true, duplicates: IDS('duplicate'), screened: r => r.fate !== 'duplicate',
  'ta-included': r => !['duplicate', 'ta_excluded', 'ta_pending'].includes(r.fate),
  'not-sought': IDS('not_sought'), sought: IDS('not_retrieved', 'ft_pending', 'ft_excluded', 'included'),
  'not-retrieved': IDS('not_retrieved'), pending: IDS('ft_pending'), assessed: IDS('ft_excluded', 'included'),
  'ft-excluded': IDS('ft_excluded'), included: IDS('included'),
};
/* record.source is the ledger's source group: arxiv-only, openalex-only, both, other */
SRC.forEach(([k]) => PRED['src-' + k] = (k in (F.identified_databases || {})) ? (r => r.source === k + '-only' || r.source === 'both') : (r => r.source === 'other'));
EXK.forEach(k => PRED['ta-' + k] = r => r.fate === 'ta_excluded' && r.criterion === k);
FXK.forEach(k => PRED['ft-' + k] = r => r.fate === 'ft_excluded' && r.criterion === k);
const eqs = (parts, got, expect) => `<span>${parts} = ${fmt(got)} <span class="${got === expect ? 'okc' : 'badc'}">${got === expect ? '✓' : '✗'}</span></span>`;
const EQ = {
  identified: eqs(SRC.map(([, n]) => fmt(n)).join(' + '), sum(Object.fromEntries(SRC)), st.identified),
  screened: eqs(`${fmt(st.identified)} − ${fmt(st.dup)}`, st.identified - st.dup, st.screened),
  'ta-included': eqs(`${fmt(st.screened)} − ${fmt(st.taEx)}`, st.screened - st.taEx, st.taInc),
  sought: eqs(`${fmt(st.taInc)} − ${fmt(st.nsg)}`, st.taInc - st.nsg, st.sgt),
  assessed: eqs(`${fmt(st.sgt)} − ${fmt(st.nrt)} − ${fmt(st.pen)}`, st.sgt - st.nrt - st.pen, st.ass),
  included: eqs(`${fmt(st.ass)} − ${fmt(st.ftEx)}`, st.ass - st.ftEx, st.inc),
};

/* ---------- state and hash ---------- */
const TABS = [['where', 'Where the records went'], ['screening', 'Screening'], ['replay', 'Replay'], ['paths', 'Paths']];
const S = { tab: 'where', view: 'flow', node: 'included', facet: {}, sk: 'title', sd: 1, q: '', more: 100, stage: null, dfilter: 'all', dmore: 20, lanes: [], cell: null };
const FACET_KEYS = ['layer', 'human', 'year', 'outcome', 'source', 'step'];
function loadHash() {
  const h = H.hash.get(); S.lanes = (h.get('lanes') || '').split(',').filter(Boolean).slice(0, 20);
  S.tab = TABS.some(t => t[0] === h.get('tab')) ? h.get('tab') : S.lanes.length ? 'paths' : 'where';
  S.view = h.get('view') === 'waffle' ? 'waffle' : 'flow'; S.node = h.get('node') || 'included';
  S.facet = {}; FACET_KEYS.forEach(k => { if (h.get(k)) S.facet[k] = new Set(h.get(k).split('|')); });
  S.cell = h.get('cell') ? h.get('cell').split('~') : null;
  if (h.get('sort')) { const [a, b] = h.get('sort').split(':'); S.sk = a; S.sd = +b || 1; }
  S.stage = h.get('stage'); S.dfilter = h.get('dis') || 'all';
}
function saveHash(extra = {}) {
  const o = { tab: S.tab === 'where' ? null : S.tab, view: S.tab === 'where' && S.view !== 'flow' ? S.view : null, node: S.tab === 'where' && S.node !== 'included' ? S.node : null,
    sort: S.tab === 'where' && !(S.sk === 'title' && S.sd === 1) ? S.sk + ':' + S.sd : null, lanes: S.lanes.join(',') || null, ...extra };
  FACET_KEYS.forEach(k => o[k] = S.tab === 'where' && S.facet[k] && S.facet[k].size ? [...S.facet[k]].join('|') : null);
  o.cell = S.tab === 'where' && S.cell ? S.cell.join('~') : null;
  H.hash.set(o);
}
loadHash();
let cleanup = () => {};

/* ---------- styles (kit tokens only) ---------- */
document.head.insertAdjacentHTML('beforeend', `<style id="flow-css">
.shell>div,main{min-width:0}
.fhead{padding:20px 0 4px;max-width:84ch}.fhead .lead{max-width:40ch;margin-top:10px}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px;margin:22px 0 12px}.bar .grow{flex:1}.bar .sec-head,.fpane .sec-head{margin:0}
.scroll{overflow-x:auto;padding-bottom:6px}
.okc{color:var(--inc)}.badc{color:var(--exc)}
.eqs{display:flex;flex-wrap:wrap;gap:6px 32px;margin-top:10px}.eqs span{font:400 var(--t-s) var(--f-mono);color:var(--mut)}
.pop .eqs{margin:6px 0 0;gap:4px 16px}.pop .eqs span{font-size:var(--t-xs)}
.empty{padding:22px;color:var(--mut);background:var(--surface);border-radius:var(--r)}
svg.sk{display:block;min-width:820px;width:100%;height:auto}
.sk .lk{fill-opacity:.3;cursor:pointer;transition:fill-opacity .12s}.sk .lk.main{fill:var(--mut)}.sk .lk.out{fill:var(--exc);fill-opacity:.42}.sk .lk.inc{fill:var(--inc);fill-opacity:.55}
.sk .lk.hot{fill-opacity:.8}.sk.hl .lk:not(.hot){fill-opacity:.08}.sk .nd{cursor:pointer}
.sk .nd rect.b{fill:var(--mut)}.sk .nd.out rect.b{fill:var(--exc)}.sk .nd.inc rect.b{fill:var(--inc)}
.sk .nd.sel rect.b,.sk .nd:focus-visible rect.b{stroke:var(--acc);stroke-width:2.5}.sk .nd:focus-visible{outline:none}
.sk .halo{paint-order:stroke;stroke:var(--bg);stroke-width:3.5px;stroke-linejoin:round}.sk .ch{font:500 11px var(--f-ui);fill:var(--dim)}
.wf h3{margin:18px 0 10px}.groups{display:flex;flex-wrap:wrap;gap:30px 40px;align-items:flex-start}
.g{background:none;border:0;color:var(--fg);padding:8px 10px 10px;border-radius:var(--r);cursor:pointer;text-align:left;font:inherit;display:block;transition:opacity .12s}
.groups.hl .g:not(:hover):not([aria-pressed=true]){opacity:.45}.g:hover{background:var(--raised)}
.g[aria-pressed=true]{background:var(--acc-soft);box-shadow:inset 0 0 0 1px var(--acc)}
.g .gh{font:600 var(--t-s) var(--f-ui);display:flex;flex-wrap:wrap;gap:0 6px;align-items:baseline;margin-bottom:6px;min-height:34px;align-content:flex-start}
.g .gh .n{font-family:var(--f-mono);font-weight:500;color:var(--mut)}.g .gt{font-size:var(--t-xs);color:var(--mut);margin-top:6px;line-height:1.35}.g svg{display:block}
.panel{margin-top:28px;display:grid;gap:12px}.pn-head{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline}.pn-n{font:500 var(--t-xxl)/1 var(--f-ui);font-variant-numeric:tabular-nums}
.split{display:grid;grid-template-columns:240px minmax(0,1fr);gap:28px;align-items:start}
.fg{margin-bottom:16px}.fg .fl{font:600 var(--t-xs) var(--f-ui);color:var(--mut);display:block;margin-bottom:6px}.fg .chips,.actives{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.actives{margin-bottom:10px}
.t th button{all:unset;cursor:pointer;color:inherit}.t th button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}.t td.ti{width:100%;min-width:240px}.t td:not(.ti){white-space:nowrap}
.bs{font-size:var(--t-s)}.bs td.r,.bs th.r{text-align:right}.bs .cellb{all:unset;cursor:pointer;color:var(--acc);font-family:var(--f-mono)}.bs .cellb:hover,.bs .cellb:focus-visible{text-decoration:underline}
.bs td.sel{background:var(--acc-soft)}.bs tr.d0 td:first-child{font-weight:600}.bs .zero{color:var(--dim);font-family:var(--f-mono)}
.kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 18px;font-size:var(--t-s);margin:0}.kv dt{color:var(--mut)}.kv dd{margin:0;overflow-wrap:anywhere}
.sc2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px 32px;align-items:start}.sc2 h3.h3{margin:0 0 8px}
.ck{background:var(--surface);border-radius:var(--r);padding:14px 16px;margin-top:10px}.ck .hd{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline}
.rm{margin:4px 0 0;display:flex;flex-wrap:wrap;gap:2px 16px}
.lyb{display:grid;grid-template-columns:130px minmax(0,1fr) 56px;gap:6px 10px;align-items:center;font-size:var(--t-s)}.lyb .tr{height:10px;background:var(--raised);border-radius:2px;overflow:hidden}.lyb .tr i{display:block;height:100%;transition:width .25s}.lyb .v{font-family:var(--f-mono);text-align:right;color:var(--mut)}
.fpane{display:grid;gap:22px;margin-top:6px}.fpane h3.h3{margin:0 0 8px}
.stats{display:flex;flex-wrap:wrap;gap:8px 34px;align-items:baseline}.stats .big{font:500 var(--t-xl)/1 var(--f-ui);font-variant-numeric:tabular-nums}
.curve{display:block;width:100%;height:auto;max-height:420px}.curve .ln{fill:none;stroke:var(--acc);stroke-width:2}.curve .ref{stroke:var(--dim);stroke-dasharray:4 4;fill:none}
.curve .mk{fill:var(--bg);stroke:var(--acc);stroke-width:2}.curve .gl{stroke:var(--hair)}.curve .stp{stroke:var(--exc);stroke-width:1.5}
.shares{display:flex;flex-wrap:wrap;gap:8px 28px}.shares div{font-size:var(--t-s);color:var(--mut)}.shares b{font:500 var(--t-l) var(--f-ui);color:var(--fg);margin-right:4px}
.two{display:grid;grid-template-columns:minmax(0,300px) minmax(0,1fr);gap:28px;align-items:start}
details.idl{margin-top:8px}details.idl summary{cursor:pointer;font:500 var(--t-s) var(--f-ui)}details.idl ul{margin:6px 0 0;padding-left:18px;max-height:220px;overflow:auto;font-size:var(--t-xs)}
table.mx{border-collapse:separate;border-spacing:4px;font-size:var(--t-s)}.mx th{font-weight:500;color:var(--mut);padding:4px 6px;text-align:left}
.mx td{padding:0}.mx button{all:unset;display:block;width:100%;box-sizing:border-box;cursor:pointer;text-align:center;font:500 var(--t-m) var(--f-mono);padding:14px 10px;border-radius:var(--r-s);background:var(--acc-soft);color:var(--fg)}
.mx button:hover,.mx button:focus-visible{box-shadow:inset 0 0 0 1px var(--acc)}.mx .plain{padding:14px 10px;text-align:center;font:500 var(--t-m) var(--f-mono);border-radius:var(--r-s);background:var(--raised)}
.kb{display:grid;grid-template-columns:auto minmax(60px,1fr) 44px;gap:6px 10px;align-items:center;font-size:var(--t-s)}.kb .bx{height:8px;border-radius:4px;background:var(--raised);overflow:hidden}.kb .bx i{display:block;height:100%;background:var(--acc)}
.kb .v{font-family:var(--f-mono);text-align:right;color:var(--mut)}
.dis{display:grid;gap:12px}.dc{background:var(--surface);border-radius:var(--r);padding:14px 16px}.dc h4{margin:0 0 10px;font:600 var(--t-s) var(--f-ui)}
.dc .cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}.dc .vd{font:600 var(--t-xs) var(--f-ui);color:var(--mut);margin-bottom:4px}.dc p{margin:4px 0;font-size:var(--t-s)}
.dc blockquote.quote{margin:6px 0 0;font-size:var(--t-s)}.tag{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:999px;background:var(--raised);color:var(--mut);margin-left:6px}
.wall{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}.wc{background:var(--surface);border-radius:var(--r);padding:14px 16px}
.wc .hd{display:flex;gap:8px 10px;align-items:baseline;flex-wrap:wrap}.wc .hd .cn{font:500 var(--t-xl)/1 var(--f-ui);font-variant-numeric:tabular-nums;margin-left:auto}
.wc .rule{font-size:var(--t-xs);color:var(--mut);margin:6px 0 10px}.wc .ex{border-top:1px solid var(--hair);padding-top:8px;margin-top:8px;font-size:var(--t-s)}.wc .ex .meta{display:block}
.wc blockquote.quote{margin:4px 0 0;font-size:var(--t-s)}
.rp canvas{display:block;width:100%;background:var(--surface);border-radius:var(--r)}
.ctl{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:12px 0}.ctl .when{font:500 var(--t-m) var(--f-mono);min-width:17ch}
.tl{position:relative}.tl svg{display:block;width:100%;height:56px}.tl input[type=range]{width:100%;margin:2px 0 0;accent-color:var(--acc)}
.legend{display:flex;flex-wrap:wrap;gap:6px}.stg{display:flex;flex-wrap:wrap;gap:4px 22px;font-size:var(--t-s);color:var(--mut);margin-top:10px}.stg b{color:var(--fg);font-family:var(--f-mono);font-weight:500}
.picker{position:relative;max-width:460px}.picker input{width:100%}.picker ul{position:absolute;z-index:5;left:0;right:0;list-style:none;margin:4px 0 0;padding:4px;background:var(--surface);box-shadow:var(--shadow);border-radius:var(--r);max-height:300px;overflow:auto}
.picker li{padding:7px 10px;border-radius:var(--r-s);cursor:pointer;font-size:var(--t-s)}.picker li:hover,.picker li[aria-selected=true]{background:var(--acc-soft)}
.lane{margin-top:16px}.lane .lh{display:flex;gap:8px 14px;align-items:baseline;flex-wrap:wrap}.lane .lh a{font-weight:600;color:var(--fg)}.lane svg{display:block;width:100%;height:auto}
.lane .rowl{font:400 10px var(--f-ui);fill:var(--dim)}.lane .rl{stroke:var(--hair)}.lane .gl{stroke:var(--hair);stroke-dasharray:2 4}.lane .pt{cursor:pointer}.lane .pt:focus-visible{outline:none;stroke:var(--acc);stroke-width:3}
.lane .dur{font:400 10px var(--f-mono);fill:var(--mut)}.lane .pth{fill:none;stroke:var(--line);stroke-width:1.5}.lane .ring{fill:none;stroke:var(--acc);stroke-width:2}
.lane details{margin-top:6px}.lane summary{cursor:pointer;font-size:var(--t-s);color:var(--mut)}.lane .t td{white-space:normal}
#lanes{overflow-x:auto}#lanes>svg,.lane svg{min-width:720px}.lane .scroll,.lane details{min-width:0;position:sticky;left:0;max-width:calc(100vw - 48px)}
@media (max-width:900px){.split,.two{grid-template-columns:minmax(0,1fr)}.dc .cols{grid-template-columns:1fr}.wall{grid-template-columns:1fr}}
</style>`);

/* ---------- page frame ---------- */
const protoTerm = H.term('protocol');
const topLoss = Object.entries(F.excluded).sort((a, b) => b[1] - a[1])[0];
$('#main').innerHTML = `
<section class="fhead">
  ${H.header({ kicker: `${H.term('prisma', 'PRISMA flow')} · ${protoTerm} <span class="mono">${esc(F.protocol_id || '')}</span>`, title: 'Flow', level: 1, infoHtml: (d.screening.methods || {}).tab_screening || '' })}
  <p class="lead">${fmt(st.identified)} records came in and ${fmt(st.inc)} papers made it through. The biggest loss: ${topLoss ? `${H.term(topLoss[0], topLoss[0])} (${esc(critLabel(topLoss[0]).toLowerCase())}), ${fmt(topLoss[1])} records` : 'none'}.${H.info(`<b>What it shows</b>How the records the searches found became the papers the review is about.<p><span class=k>How it's computed.</span> ${fmt(st.inc)} of ${fmt(st.identified)} is ${(100 * st.inc / st.identified).toFixed(1)}%. The biggest loss is the exclusion criterion with the most records at title and abstract. ${esc(d.flow.methods.fates)}</p><p>${fmt(st.identified - R.length)} of the ${fmt(st.identified)} records were merged into another before getting a ledger row of their own; they count in the totals but have no row in the record lists (this count is computed as identified minus listed).</p>`, 'How these figures are computed')}</p>
${d.flow.reconciles ? `<p class="meta" role="status">The ledger reconciles with the flow: the ${fmt(d.flow.groups_sum)} records in the end groups equal the ${fmt(st.identified)} identified.</p>` : `<p class="meta" role="alert" style="color:var(--exc)">The ledger does not reconcile with the flow: the end groups hold ${fmt(d.flow.groups_sum)} records, ${fmt(st.identified)} were identified.</p>`}
</section>
<div class="bar"><div class="seg" role="group" aria-label="Flow views" id="tabs">${TABS.map(t => `<button data-t="${t[0]}">${t[1]}</button>`).join('')}</div></div>
<div id="pane"></div>
<p class="meta" style="margin-top:36px">${H.info(esc(H.SETS_NOTE), 'About the paper counts')} Papers read in full: ${fmt(H.stats.mined)}; included by screening: ${fmt(st.inc)}.</p>`;
function showTab(t, keep) {
  cleanup(); cleanup = () => {}; S.tab = t; if (!keep) saveHash();
  document.querySelectorAll('#tabs [data-t]').forEach(b => b.setAttribute('aria-pressed', b.dataset.t === t));
  const p = $('#pane'); p.innerHTML = ''; ({ where: tabWhere, screening: tabScreening, replay: tabReplay, paths: tabPaths })[t](p);
}
document.querySelectorAll('#tabs [data-t]').forEach(b => b.onclick = () => showTab(b.dataset.t));
addEventListener('hashchange', () => { loadHash(); showTab(S.tab, true); });
document.addEventListener('hub:theme', () => showTab(S.tab, true));
const infoPanel = (what, read, how) => `<b>What it shows</b>${what}${read ? `<p><span class=k>How to read it.</span> ${read}</p>` : ''}${how ? `<p><span class=k>How it's computed.</span> ${how}</p>` : ''}`;
const miniTip = (html, el) => { const r = el.getBoundingClientRect(); H.tipHtml(html, { clientX: r.right, clientY: r.top }); };

/* ================= tab 1: where the records went ================= */
function nodeModel() {
  const N = [], L = []; const add = (id, col, label, n, cls, x = {}) => { const o = { id, col, label, n, cls, ...x }; N.push(o); return o; };
  const srcs = SRC.map(([k, n]) => add('src-' + k, 0, { arxiv: 'arXiv', openalex: 'OpenAlex' }[k] || H.pretty(k), n, 'main'));
  const idn = add('identified', 1, 'Identified', st.identified, 'main'), dup = add('duplicates', 2, 'Duplicates removed', st.dup, 'out'), scr = add('screened', 2, 'Screened', st.screened, 'main');
  const tx = EXK.map(k => add('ta-' + k, 3, k, F.excluded[k], 'out', { crit: k })), tin = add('ta-included', 3, 'Passed title and abstract', st.taInc, 'main');
  const nsg = add('not-sought', 4, 'Not sought', st.nsg, 'out'), sgt = add('sought', 4, 'Sought', st.sgt, 'main');
  const nrt = add('not-retrieved', 5, 'Not retrieved', st.nrt, 'out'), pen = add('pending', 5, 'Pending', st.pen, 'out'), ass = add('assessed', 5, 'Assessed', st.ass, 'main');
  const fx = FXK.map(k => add('ft-' + k, 6, k, FT.excluded[k], 'out', { crit: k, ft: true })), inc = add('included', 6, 'Included', st.inc, 'inc');
  const lk = (a, b) => b.n > 0 && L.push({ a, b, n: b.n });
  srcs.forEach(s => L.push({ a: s, b: idn, n: s.n })); [[idn, dup], [idn, scr], ...tx.map(t => [scr, t]), [scr, tin], [tin, nsg], [tin, sgt], [sgt, nrt], [sgt, pen], [sgt, ass], ...fx.map(t => [ass, t]), [ass, inc]].forEach(([a, b]) => lk(a, b));
  return { N: N.filter(n => n.n > 0 || n.cls === 'main'), Lk: L };
}
const FLOW = nodeModel(), nodeOf = id => FLOW.N.find(n => n.id === id);
const NODETXT = {
  duplicates: ['identified', 'identified', 'The same paper found more than once, merged before screening.'], 'not-sought': ['taInc', 'passed title and abstract', 'No full text was sought for these: the rapid-review cap limits how many full texts are read.'],
  pending: ['sgt', 'sought', 'The full-text decision is still to be made.'], 'not-retrieved': ['sgt', 'sought', 'A full text was sought but no copy could be obtained.'],
  included: ['ass', 'assessed', 'The papers that passed every stage.'], 'ta-included': ['screened', 'screened', 'Records that passed title-and-abstract screening.'],
  sought: ['taInc', 'passed title and abstract', 'Records for which a full text was sought.'], assessed: ['sgt', 'sought', 'Full texts read and decided.'],
  screened: ['identified', 'identified', 'Records screened on title and abstract after de-duplication.'], identified: ['identified', 'identified', 'Records found by the searches, before de-duplication.'],
};
function nodeInfo(id) {
  if (id === 'ft-excluded') return { title: 'Excluded at full text', n: st.ftEx, den: st.ass, denL: 'assessed', sign: '−', eq: EQ.included, text: 'Excluded after reading the full text: ' + Object.entries(FT.excluded || {}).map(([k, v]) => `${k} ${v}`).join(', ') + '.' };
  const n = nodeOf(id); if (!n) return null;
  const t = { n: n.n, title: n.label, sign: n.cls === 'out' ? '−' : n.cls === 'inc' ? '+' : '', text: '', eq: EQ[id] || '' };
  if (n.crit) { t.title = n.crit + ' · ' + critLabel(n.crit); t.den = n.ft ? st.ass : st.screened; t.denL = n.ft ? 'assessed' : 'screened';
    t.text = `Excluded at ${n.ft ? 'full text' : 'title and abstract'} under criterion ${n.crit}.`; t.eq = n.ft ? EQ.included : EQ['ta-included']; return t; }
  const m = NODETXT[id]; if (m) { t.den = st[m[0]]; t.denL = m[1]; t.text = m[2]; } else { t.den = st.identified; t.denL = 'identified'; t.text = 'Records found by this source, before de-duplication.'; t.eq = EQ.identified; }
  if (id === 'identified' || id === 'duplicates' || id.startsWith('src-')) t.more = d.flow.methods.identification;
  if (id === 'duplicates') t.eq = EQ.screened; if (id === 'not-sought') t.eq = EQ.sought; if (id === 'not-retrieved' || id === 'pending') t.eq = EQ.assessed;
  if (id === 'not-retrieved' && FT.not_retrieved_reasons) t.text += ' Routes tried: ' + Object.entries(FT.not_retrieved_reasons).map(([k, v]) => `${k} (${v})`).join(', ') + '.';
  return t;
}
const pctTxt = i => `${fmt(i.n)} of ${fmt(i.den)} ${i.denL} (${(100 * i.n / i.den).toFixed(1)}%)`;
function drawSankey() {
  const svg = $('#sk'), Wd = Math.max(820, Math.round(svg.parentElement.clientWidth)), { N, Lk } = FLOW;
  const cols = 7, colW = (Wd - 150) / (cols - 1), nw = 14, gap = 8, minSlot = 19, k = 470 / st.identified;
  const cn = [...Array(cols)].map((_, c) => N.filter(n => n.col === c)); let maxH = 0;
  cn.forEach(a => { let y = 24; a.forEach(n => { n.h = Math.max(2, n.n * k); const slot = Math.max(n.h, minSlot); n.y = y + (slot - n.h) / 2; y += slot + gap; n.x = n.col * colW; }); maxH = Math.max(maxH, y); });
  Lk.forEach(l => l.w = Math.min(Math.max(2, l.n * k), l.a.h, l.b.h));
  const outs = new Map(N.map(n => [n, []])), ins = new Map(N.map(n => [n, []])); Lk.forEach(l => { outs.get(l.a).push(l); ins.get(l.b).push(l); });
  outs.forEach((a, n) => { a.sort((p, q) => p.b.y - q.b.y); let o = 0; a.forEach(l => { l.sy = n.y + o + l.w / 2; o += l.w; }); });
  ins.forEach((a, n) => { a.sort((p, q) => p.a.y - q.a.y); let o = 0; a.forEach(l => { l.ty = n.y + o + l.w / 2; o += l.w; }); });
  svg.setAttribute('viewBox', `0 0 ${Wd} ${maxH + 6}`);
  const heads = ['Sources', 'Identified', 'Screening', 'Title and abstract', 'Full text sought', 'Full text', 'Outcome'];
  let s = heads.map((t, c) => `<text class="ch" x="${c * colW}" y="12">${t}</text>`).join('');
  s += Lk.map(l => { const x0 = l.a.x + nw, x1 = l.b.x, mx = (x0 + x1) / 2, w = l.w;
    return `<path class="lk ${l.b.cls}" data-n="${esc(l.b.id)}" d="M${x0},${l.sy - w / 2} C${mx},${l.sy - w / 2} ${mx},${l.ty - w / 2} ${x1},${l.ty - w / 2} L${x1},${l.ty + w / 2} C${mx},${l.ty + w / 2} ${mx},${l.sy + w / 2} ${x0},${l.sy + w / 2}Z"/>`; }).join('');
  s += N.map(n => { const sg = n.cls === 'out' ? '− ' : n.cls === 'inc' ? '+ ' : '', lab = sg + (n.crit || n.label), col = n.cls === 'out' ? 'var(--exc)' : n.cls === 'inc' ? 'var(--inc)' : 'var(--fg)';
    return `<g class="nd ${n.cls} ${S.node === n.id ? 'sel' : ''}" data-n="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)} ${n.n}"><rect class="b" x="${n.x}" y="${n.y.toFixed(1)}" width="${nw}" height="${n.h.toFixed(1)}" rx="2"/><rect x="${n.x - 2}" y="${(n.y - 3).toFixed(1)}" width="${Math.min(colW - 6, nw + 130)}" height="${(Math.max(n.h, 16) + 6).toFixed(1)}" fill="transparent"/><text class="halo lbl" x="${n.x + nw + 7}" y="${(n.y + n.h / 2 + 4.3).toFixed(1)}" style="font-size:12.5px;${n.cls !== 'out' ? 'font-weight:600' : ''}"><tspan fill="${col}">${esc(lab)}</tspan> <tspan class="lbl-m" fill="var(--mut)">${fmt(n.n)}</tspan></text></g>`; }).join('');
  svg.innerHTML = s;
  svg.querySelectorAll('.nd,.lk').forEach(el => { const id = el.dataset.n;
    el.addEventListener('click', () => selectNode(id));
    el.addEventListener('mouseenter', () => { svg.classList.add('hl'); svg.querySelectorAll(`.lk[data-n="${CSS.escape(id)}"]`).forEach(p => p.classList.add('hot')); });
    el.addEventListener('mousemove', e => { const i = nodeInfo(id); i && H.tipHtml(`<b>${esc(i.title)}</b><br>${pctTxt(i)}`, e); });
    el.addEventListener('mouseleave', () => { svg.classList.remove('hl'); svg.querySelectorAll('.lk.hot').forEach(p => p.classList.remove('hot')); H.tipHtml(null); });
    el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectNode(id); } }); });
}
const ROWS = 24, PITCH = 9;
function wGroups() {
  const g = EXK.map(k => ({ id: 'ta-' + k, code: k, sg: '−', n: F.excluded[k], txt: critLabel(k), kind: 'ex', sec: 0 }));
  g.push({ id: 'not-sought', code: 'Not sought', sg: '−', n: st.nsg, txt: 'Rapid-review cap on full texts', kind: 'ns', sec: 1 },
    { id: 'not-retrieved', code: 'Not retrieved', sg: '−', n: st.nrt, txt: 'Sought, no copy obtained', kind: 'nr', sec: 1 },
    { id: 'ft-excluded', code: 'Excluded at full text', sg: '−', n: st.ftEx, txt: Object.entries(FT.excluded || {}).map(([k, v]) => `${k} ${v}`).join(' · '), kind: 'ex', sec: 1 },
    { id: 'pending', code: 'Pending', sg: '', n: st.pen, txt: 'Decision still to make', kind: 'pe', sec: 1 },
    { id: 'included', code: 'Included', sg: '+', n: st.inc, txt: 'Passed every stage', kind: 'in', sec: 1 });
  return g.filter(x => x.n > 0);
}
function dotsSvg(g) {
  const cols = Math.ceil(g.n / ROWS), w = Math.max(cols * PITCH, g.n < 30 ? PITCH : 0), h = Math.min(g.n, ROWS) * PITCH;
  const sty = { ex: 'fill="var(--exc)"', ns: 'fill="var(--dim)"', nr: 'fill="none" stroke="var(--mut)" stroke-width="1.3"', pe: 'fill="var(--bg)" stroke="var(--fg)" stroke-width="1.6"', in: 'fill="var(--inc)"' }[g.kind]; let s = '';
  for (let i = 0; i < g.n; i++) s += `<circle cx="${Math.floor(i / ROWS) * PITCH + PITCH / 2}" cy="${(i % ROWS) * PITCH + PITCH / 2}" r="${g.kind === 'pe' ? 3.6 : 3.1}" ${sty}/>`;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${s}</svg>`;
}
function drawWaffle() {
  const gs = wGroups(), mk = sec => gs.filter(g => g.sec === sec).map(g => { const w = Math.max(Math.ceil(g.n / ROWS) * PITCH, g.sec ? 152 : 128);
    return `<button class="g" data-n="${esc(g.id)}" aria-pressed="${S.node === g.id}" style="width:${w + 20}px"><div class="gh"><span style="color:${g.sg === '−' ? 'var(--exc)' : g.sg === '+' ? 'var(--inc)' : 'var(--fg)'}">${g.sg || '·'}</span>${esc(g.code)} <span class="n">${fmt(g.n)}</span></div>${dotsSvg(g)}<div class="gt">${esc(g.txt)}</div></button>`; }).join('');
  const t1 = gs.filter(g => !g.sec).reduce((a, g) => a + g.n, 0), t2 = gs.filter(g => g.sec).reduce((a, g) => a + g.n, 0);
  $('#wf').innerHTML = `<h3 class="h3">Excluded at title and abstract <span class="meta">− ${fmt(t1)} of ${fmt(st.screened)} screened</span></h3><div class="groups">${mk(0)}</div>
   <h3 class="h3" style="margin-top:30px">Passed title and abstract <span class="meta">${fmt(t2)} of ${fmt(st.screened)} screened</span></h3><div class="groups">${mk(1)}</div>`;
  const all = document.querySelectorAll('#wf .groups');
  document.querySelectorAll('#wf .g').forEach(b => { b.onclick = () => selectNode(b.dataset.n);
    b.onmouseenter = () => all.forEach(x => x.classList.add('hl')); b.onmouseleave = () => { all.forEach(x => x.classList.remove('hl')); H.tipHtml(null); };
    b.onmousemove = e => { const i = nodeInfo(b.dataset.n); i && H.tipHtml(`<b>${esc(i.title)}</b><br>${pctTxt(i)}`, e); }; });
  return infoPanel(`What happened to each of the ${fmt(st.screened)} records that were screened.`, 'One dot is one record. Filled means decided; a ring means no decision yet (not retrieved, pending).',
    `${fmt(t1)} + ${fmt(t2)} = ${fmt(t1 + t2)} ${t1 + t2 === st.screened ? '✓' : '✗'} screened records. Dots fill column by column, ${ROWS} to a column, so a block is as wide as its count. The ${fmt(st.dup)} duplicates were removed before screening and are not shown.`);
}
function selectNode(id) { S.node = id; S.cell = null; S.more = 100; saveHash(); drawBySource(); drawPanel(); markSel(); $('#panel').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth', block: 'nearest' }); }
function markSel() { document.querySelectorAll('#sk .nd').forEach(n => n.classList.toggle('sel', n.dataset.n === S.node)); document.querySelectorAll('#wf .g').forEach(b => b.setAttribute('aria-pressed', b.dataset.n === S.node)); }
const FACETS = [['outcome', 'Outcome', r => outcomeOf(r), v => v, null], ['layer', 'Layer', r => (H.byId.get(r.id) || {}).layer, H.layerLabel, v => H.LAYERS.find(l => l[0] === v)?.[2]],
  ['human', 'Human role', r => { const w = H.byId.get(r.id); return w ? (H.val(w, 'human') || 'null') : null; }, v => H.humanLabel(v === 'null' ? null : v), v => (H.HUMAN.find(h => h[0] === v) || [, , '--h-null'])[2]],
  ['year', 'Year', r => String(r.year), v => v, null],
  ['source', 'Source group', r => r.source, v => v, null], ['step', 'Step reached', r => r.step, v => v, null]];
function cellModel(c) {
  const [tag, crit, g] = c, row = d.flow.by_source.rows.find(r => r.tag === tag && (r.criterion || '') === crit);
  if (!row) return null;
  const pred = r => r.tags.includes(tag) && (crit === '' || (r.reason || 'unspecified') === crit) && (g === '' || r.source === g);
  const total = d.flow.by_source.rows[0].counts[g === '' ? 'Total' : g];
  return { pred, info: { title: row.label + (g ? ' · ' + g : ''), n: row.counts[g === '' ? 'Total' : g], den: total, denL: g ? 'records from this source' : 'records identified', sign: '',
    text: 'The records that reached this step' + (g ? ' and were found by this source group.' : '.'), eq: '' } };
}
function downloadCsv(rows) {
  const q = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
  const cols = ['work_id', 'title', 'year', 'source_group', 'sources', 'step', 'outcome', 'criterion_or_reason', 'duplicate_of'];
  const body = rows.map(r => [r.id, r.title, r.year, r.source, (r.sources || []).join('; '), r.step, r.outcome, r.reason, r.duplicate_of].map(q).join(','));
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([[cols.join(','), ...body].join('\n')], { type: 'text/csv' }));
  a.download = 'flow-records.csv'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function drawPanel() {
  const pn = $('#panel'), cm = S.cell && cellModel(S.cell), i = cm ? cm.info : nodeInfo(S.node);
  if (!i) { pn.innerHTML = `<div class="empty">Unknown stream “${esc(S.node)}”.</div>`; return; }
  const head = `<div class="pn-head"><span class="pn-n" style="color:${i.sign === '−' ? 'var(--exc)' : i.sign === '+' ? 'var(--inc)' : 'var(--fg)'}">${i.sign ? i.sign + ' ' : ''}${fmt(i.n)}</span><h2 class="h2">${esc(i.title)} ${H.info(`<b>${esc(i.title)}</b>${esc(i.text)}${i.more ? `<p>${esc(i.more)}</p>` : ''}<p><span class=k>How it's computed.</span> ${cm ? esc(d.flow.methods.by_source) : 'The arithmetic below is recomputed from the counts.'}</p><div class="eqs">${i.eq}</div>`, 'About ' + i.title)}</h2></div><p class="meta" style="margin:0">${pctTxt(i)}</p>`;
  const pred = cm ? cm.pred : PRED[S.node];
  if (!pred) { pn.innerHTML = head + '<div class="empty">The record list is not split by source, so there is no list behind this count.</div>'; return; }
  const base = R.filter(pred); let note = '';
  if (cm) note = 'Showing one cell of the table of steps by source.';
  if (!cm && S.node === 'identified') note = `The list holds the ${fmt(base.length)} records that kept a record of their own; the other ${fmt(i.n - base.length)} were merged into one before getting one.`;
  if (!cm && S.node.startsWith('src-')) note = `The list holds the ${fmt(base.length)} records of this source that kept a record of their own; the other ${fmt(i.n - base.length)} were merged into one before getting one.`;
  if (!cm && S.node === 'duplicates') note = `${fmt(base.length)} duplicates kept a record of their own and are listed; the other ${fmt(i.n - base.length)} were merged away before getting one.`;
  const isW = base.filter(r => H.byId.has(r.id)).length * 2 > base.length;
  const fdefs = FACETS.filter(f => (isW || (f[0] !== 'layer' && f[0] !== 'human'))).map(f => { const m = new Map(); base.forEach(r => { const v = f[2](r); if (v != null) m.set(v, (m.get(v) || 0) + 1); }); return { f, m }; }).filter(x => x.m.size > 1);
  const act = fdefs.flatMap(x => [...(S.facet[x.f[0]] || [])].filter(v => x.m.has(v)).map(v => [x.f[0], v, x.f[3](v)]));
  const keep = r => fdefs.every(x => { const s = S.facet[x.f[0]]; return !s || !s.size || s.has(x.f[2](r)); }) && (!S.q || titleOf(r.id).toLowerCase().includes(S.q.toLowerCase()));
  const val = r => S.sk === 'source' ? r.source : S.sk === 'step' ? r.step : S.sk === 'year' ? r.year : S.sk === 'cic' ? (H.byId.get(r.id) || {}).cic || 0 : titleOf(r.id).toLowerCase();
  const rows = base.filter(keep).sort((a, b) => { const x = val(a), y = val(b); return (x > y ? 1 : x < y ? -1 : 0) * S.sd; });
  const th = (k, l, c = '') => `<th class="${c}" aria-sort="${S.sk === k ? (S.sd > 0 ? 'ascending' : 'descending') : 'none'}"><button data-sort="${k}">${l}${S.sk === k ? (S.sd > 0 ? ' ↑' : ' ↓') : ''}</button></th>`;
  const chip = (x, v, n) => { const tok = x.f[4] && x.f[4](v), hol = v === 'unlayered' || v === 'null';
    return `<button class="chip" aria-pressed="${!!(S.facet[x.f[0]] && S.facet[x.f[0]].has(v))}" data-f="${x.f[0]}" data-v="${esc(v)}">${tok ? `<span class="dot" style="${hol ? `border:1.5px solid var(${tok})` : `background:var(${tok})`}"></span>` : ''}${esc(x.f[3](v))} <span class="n">${n}</span></button>`; };
  const order = (x, a, b) => x.f[0] === 'year' ? a[0].localeCompare(b[0]) : b[1] - a[1];
  pn.innerHTML = head + (note ? `<p class="meta" style="margin:0">${esc(note)}${cm ? ' <button class="chip" data-nocell="1">Back to the flow</button>' : ''}</p>` : '') + `<div class="split" style="margin-top:8px"><div>
    ${fdefs.map(x => `<div class="fg"><span class="fl">${x.f[1]}</span><div class="chips">${[...x.m].sort((a, b) => order(x, a, b)).map(([v, n]) => chip(x, v, n)).join('')}</div></div>`).join('')}</div>
   <div><div class="actives"><b class="num" style="margin-right:6px">${fmt(rows.length)}</b><span class="meta">of ${fmt(base.length)} records${act.length ? ', filtered by' : ''}</span>${act.map(([k, v, l]) => `<span class="chip" aria-pressed="true">${esc(l)} <button data-rm="${k}" data-v="${esc(v)}" aria-label="Remove filter ${esc(l)}" style="all:unset;cursor:pointer">×</button></span>`).join('')}${act.length ? '<button class="chip" data-clear="1">Clear</button>' : ''}
     <button class="btn" data-csv="1" style="margin-left:auto" ${rows.length ? '' : 'disabled'}>Download CSV</button><input type="search" id="rq" placeholder="Search titles" aria-label="Search titles" value="${esc(S.q)}" style="min-width:180px"></div>
   ${rows.length ? `<p class="sx-hint">Scroll sideways to see the rest →</p><div class="scroll"><table class="t"><thead><tr>${th('title', 'Title')}${th('source', 'Source group')}<th>Sources</th>${th('step', 'Step reached')}<th>Outcome</th>${isW ? '<th>Layer</th>' : ''}${th('year', 'Year', 'r')}${isW ? th('cic', 'Cited here', 'r') : ''}<th>Path</th></tr></thead><tbody>${rows.slice(0, S.more).map(r => { const w = H.byId.get(r.id);
      return `<tr tabindex="0" data-id="${esc(r.id)}"><td class="ti">${esc(clip(r.title, 160))}</td><td>${esc(r.source)}</td><td>${esc((r.sources || []).join(', '))}</td><td>${esc(r.step)}</td><td>${esc(outcomeOf(r))}</td>${isW ? `<td>${w ? `<span class="dot" style="background:${H.layerColor(w.layer)};margin-right:6px"></span>${esc(H.layerLabel(w.layer))}` : ''}</td>` : ''}<td class="r">${esc(r.year)}</td>${isW ? `<td class="r">${w ? w.cic : ''}</td>` : ''}<td><a href="#lanes=${encodeURIComponent(r.id)}" data-lane="${esc(r.id)}">See path</a></td></tr>`; }).join('')}</tbody></table></div>
     ${rows.length > S.more ? `<p><button class="btn" data-more="1">Show ${Math.min(100, rows.length - S.more)} more</button> <span class="meta">${fmt(S.more)} of ${fmt(rows.length)} shown</span></p>` : ''}`
     : `<div class="empty"><b>No records match these filters.</b> <button class="chip" data-clear="1">Show all</button></div>`}</div></div>`;
  pn.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { const s = S.facet[b.dataset.f] || (S.facet[b.dataset.f] = new Set()); s.has(b.dataset.v) ? s.delete(b.dataset.v) : s.add(b.dataset.v); S.more = 100; saveHash(); drawPanel(); });
  pn.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { S.facet[b.dataset.rm].delete(b.dataset.v); saveHash(); drawPanel(); });
  pn.querySelectorAll('[data-nocell]').forEach(b => b.onclick = () => { S.cell = null; saveHash(); tabWhereRefresh(); });
  pn.querySelectorAll('[data-csv]').forEach(b => b.onclick = () => downloadCsv(rows));
  pn.querySelectorAll('[data-clear]').forEach(b => b.onclick = () => { S.facet = {}; S.q = ''; saveHash(); drawPanel(); });
  pn.querySelectorAll('[data-sort]').forEach(b => b.onclick = () => { if (S.sk === b.dataset.sort) S.sd *= -1; else { S.sk = b.dataset.sort; S.sd = S.sk === 'cic' ? -1 : 1; } saveHash(); drawPanel(); });
  pn.querySelectorAll('[data-more]').forEach(b => b.onclick = () => { S.more += 100; drawPanel(); });
  const rq = $('#rq'); if (rq) rq.oninput = () => { S.q = rq.value; S.more = 100; const p = rq.selectionStart; drawPanel(); const n = $('#rq'); n.focus(); n.setSelectionRange(p, p); };
  pn.querySelectorAll('[data-lane]').forEach(a => a.onclick = e => { e.preventDefault(); e.stopPropagation(); S.lanes = [a.dataset.lane]; showTab('paths'); });
  pn.querySelectorAll('tbody tr').forEach(r => { const go = () => H.byId.has(r.dataset.id) && H.openDrawer(r.dataset.id); r.onclick = go; r.onkeydown = e => { if (e.key === 'Enter') go(); }; });
}
function drawBySource() {
  const BS = d.flow.by_source, el = $('#bysrc'); if (!el || !BS || !BS.rows.length) return;
  const sel = (r, g) => S.cell && S.cell[0] === r.tag && S.cell[1] === (r.criterion || '') && S.cell[2] === g;
  const cell = (r, g, key) => { const n = r.counts[key]; return `<td class="r ${sel(r, g) ? 'sel' : ''}">${n ? `<button class="cellb" data-cell="${esc([r.tag, r.criterion || '', g].join('~'))}" aria-label="${esc(r.label)}: ${n}">${fmt(n)}</button>` : '<span class="zero">0</span>'}</td>`; };
  el.innerHTML = `<div style="margin-top:26px">${H.header({ title: 'Steps by source', infoHtml: infoPanel('How many records reached each step, by the source that found them.', 'Rows are steps, columns are source groups. Click a number to list those records below.', esc(d.flow.methods.by_source) + '<p>' + esc(d.flow.methods.identification) + '</p>') })}</div>
   <p class="sx-hint">Scroll sideways to see the rest →</p><div class="scroll card" style="padding:8px 12px"><table class="t bs"><thead><tr><th>Step</th>${BS.groups.map(g => `<th class="r">${esc(g)}</th>`).join('')}<th class="r">Total</th></tr></thead><tbody>
   ${BS.rows.map(r => `<tr class="d${Math.min(r.depth, 1)}"><td style="padding-left:${10 + 16 * r.depth}px">${esc(r.label)}</td>${BS.groups.map(g => cell(r, g, g)).join('')}${cell(r, '', 'Total')}</tr>`).join('')}</tbody></table></div>`;
  el.querySelectorAll('[data-cell]').forEach(b => b.onclick = () => { S.cell = b.dataset.cell.split('~'); S.more = 100; S.facet = {}; saveHash(); drawBySource(); drawPanel(); $('#panel').scrollIntoView({ behavior: 'auto', block: 'nearest' }); });
}
const tabWhereRefresh = () => { drawBySource(); drawPanel(); };
function tabWhere(p) {
  p.innerHTML = `<div class="bar" style="margin-top:6px"><div class="seg" role="group" aria-label="Lens"><button data-v="flow">Flow</button><button data-v="waffle">Every record</button></div><span class="grow" id="lensq"></span></div>
    <div id="lens"></div><section id="bysrc"></section><section class="panel" id="panel" aria-live="polite"></section>`;
  drawBySource();
  const lens = () => { document.querySelectorAll('.seg [data-v]').forEach(b => b.setAttribute('aria-pressed', b.dataset.v === S.view)); const L = $('#lens');
    if (S.view === 'flow') {
      $('#lensq').innerHTML = H.header({ title: 'Records at each step', infoHtml: infoPanel('How many records survive each stage, and why the rest leave.', 'Band width is proportional to the record count, on one scale for every column. Click a band or box to list its records below.', `Every band is drawn at ${(st.identified ? 470 / st.identified * 1000 : 0).toFixed(0)} px per 1,000 records; bands under 2 px are drawn at 2 px. The checks under the figure are recomputed from the counts.`) });
      L.innerHTML = `<div class="card" style="padding:16px 12px"><div class="scroll"><svg class="sk" id="sk" role="img" aria-label="PRISMA flow, band width proportional to record count"></svg></div><p class="sx-hint">Scroll sideways to see the rest →</p></div><div class="eqs">${['identified', 'screened', 'ta-included', 'sought', 'assessed', 'included'].map(k => EQ[k]).join('')}</div>`; drawSankey();
    } else { L.innerHTML = '<div class="card wf" id="wf"></div>'; const ip = drawWaffle(); $('#lensq').innerHTML = H.header({ title: 'Every record', sub: `<span class="meta">${fmt(st.screened)} records screened</span>`, infoHtml: ip }); }
    markSel(); };
  p.querySelectorAll('.seg [data-v]').forEach(b => b.onclick = () => { S.view = b.dataset.v; saveHash(); lens(); });
  lens(); drawPanel();
  let rz; const onr = () => { clearTimeout(rz); rz = setTimeout(() => { if (S.view === 'flow' && $('#sk')) drawSankey(); }, 150); };
  addEventListener('resize', onr); cleanup = () => removeEventListener('resize', onr);
}

/* ================= tab 2: screening ================= */
const clip = (t, n = 120) => t.length > n ? t.slice(0, n - 1) + '\u2026' : t;
const recLink = id => H.byId.has(id) ? `<a href="#" data-open="${esc(id)}" title="${esc(titleOf(id))}">${esc(clip(titleOf(id)))}</a>` : `<span title="${esc(titleOf(id))}">${esc(clip(titleOf(id)))}</span>`;
const idList = (ids, label) => ids && ids.length ? `<details class="idl"><summary>${esc(label)} <span class="meta">${fmt(ids.length)}</span></summary><ul>${ids.slice(0, 200).map(id => `<li>${recLink(id)}</li>`).join('')}</ul>${ids.length > 200 ? `<p class="meta">First 200 of ${fmt(ids.length)}.</p>` : ''}</details>` : '';
const wireOpen = root => root.querySelectorAll('[data-open]').forEach(a => a.onclick = e => { e.preventDefault(); H.openDrawer(a.dataset.open); });
function curveSvg(rc) {
  const W = 920, Ht = 380, m = { l: 62, r: 20, t: 20, b: 66 }, pts = rc.points, N = pts.length, Y = rc.included_total || pts[N - 1] || 1;
  const x = i => m.l + (W - m.l - m.r) * i / (rc.screened || N), y = v => Ht - m.b - (Ht - m.t - m.b) * v / Y, step = Math.max(1, Math.ceil(N / 900));
  let path = `M${x(0)},${y(0)}`; for (let i = 0; i < N; i += step) path += `L${x(i + 1).toFixed(1)},${y(pts[i]).toFixed(1)}`; path += `L${x(N)},${y(pts[N - 1])}`;
  let s = [0, .25, .5, .75, 1].map(f => `<line class="gl" x1="${m.l}" x2="${W - m.r}" y1="${y(Y * f)}" y2="${y(Y * f)}"/><text class="axis" x="${m.l - 8}" y="${y(Y * f) + 4}" text-anchor="end">${fmt(Math.round(Y * f))}</text>`).join('');
  s += [0, .25, .5, .75, 1].map(f => `<text class="axis" x="${x((rc.screened || N) * f)}" y="${Ht - m.b + 18}" text-anchor="middle">${fmt(Math.round((rc.screened || N) * f))}</text>`).join('');
  s += `<text class="axis" x="${(W + m.l) / 2}" y="${Ht - 4}" text-anchor="middle">Records screened, best-ranked first</text><text class="axis" transform="rotate(-90 14 ${(Ht - m.b) / 2})" x="14" y="${(Ht - m.b) / 2}" text-anchor="middle">Included so far</text>`;
  s += `<line class="ref" x1="${x(0)}" y1="${y(0)}" x2="${x(N)}" y2="${y(Y)}"/><path class="ln" d="${path}"/>`;
  Object.entries(rc.shares || {}).forEach(([k, f]) => { const idx = Math.ceil(N * +k / 100), px = x(idx), py = y(pts[Math.min(N, idx) - 1]);
    s += `<line class="gl" x1="${px}" x2="${px}" y1="${py}" y2="${Ht - m.b}"/><circle class="mk" cx="${px}" cy="${py}" r="5"/><text class="axis" x="${px < 150 ? px + 10 : px - 10}" y="${px < 150 ? py + 18 : py - 10}" text-anchor="${px < 150 ? 'start' : 'end'}" style="fill:var(--fg)">${Math.round(100 * f)}% of inclusions</text><text class="axis" x="${px}" y="${Ht - m.b + 32}" text-anchor="middle">${k}% of records</text>`; });
  if (rc.stop_at != null) s += `<line class="stp" x1="${x(rc.stop_at)}" x2="${x(rc.stop_at)}" y1="${m.t}" y2="${Ht - m.b}"/><text class="axis" x="${x(rc.stop_at) - 6}" y="${m.t + 10}" text-anchor="end" style="fill:var(--exc)">Stopped here</text>`;
  return `<svg class="curve" id="curve" viewBox="0 0 ${W} ${Ht}" role="img" aria-label="Inclusions found against records screened, best-ranked first">${s}<rect id="cvh" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${Ht - m.t - m.b}" fill="transparent"/></svg>`;
}
function tabScreening(p) {
  const SC = d.screening, rc = SC.ranked_curve, N = rc.points.length, sh = k => Math.round(100 * (rc.shares[k] || 0));
  const two = SC.two_screeners; if (!two.length) { p.innerHTML = '<div class="empty">Screening is not recorded yet.</div>'; return; }
  const cur = two.find(t => t.stage + '|' + t.phase === S.stage) || two.filter(t => t.phase === 'screening').sort((a, b) => b.n - a.n)[0] || two[0];
  const wallStages = [...new Set(SC.reasons_wall.map(w => w.stage))].sort((a, b) => (a === 'title-abstract' ? -1 : 1) - (b === 'title-abstract' ? -1 : 1));
  p.innerHTML = `<div class="fpane">
  <section>${H.header({ title: 'Ranked screening', sub: `${sh(10)}% of inclusions sit in the first tenth of the ranked records; ${sh(25)}% in the first quarter.`, infoHtml: infoPanel('How quickly screening finds the papers that matter.', `The line counts inclusions as records are screened, best-ranked first. The dashed diagonal is what an unranked order would find. The further the line bends above it, the more the ranking helps. A ${H.term('stoprule')} would show as a red vertical line.`, esc(SC.methods.ranked_curve)) })}
   <div class="card" style="margin-top:12px;padding:14px">${curveSvg(rc)}</div>
   <div class="shares" style="margin-top:12px">${Object.keys(rc.shares).map(k => `<div><b>${sh(k)}%</b>of inclusions in the first ${k}% of records</div>`).join('')}<div><b>${fmt(rc.included_total)}</b>included in ${fmt(rc.screened)} records screened</div>
   <div>${rc.stop_at != null ? `Screening stopped after ${fmt(rc.stop_at)} records.` : `No stop point yet: ${H.term('stoprule', 'the stop rule')} has not fired.`}</div></div></section>
  ${panelSections(SC.panel, SC.methods)}
  <section id="two">${H.header({ title: 'Two screeners', infoHtml: infoPanel('How closely two independent readers agree on which records to keep.', `Each record was read by screener A and screener B. ${H.term('kappa', 'κ')} corrects the agreement for chance. Disagreements are listed with both readings side by side.`, esc(SC.methods.two_screeners)) })}
   <div class="bar" style="margin:10px 0"><div class="seg" role="group" aria-label="Stage and phase">${two.map(t => `<button data-s="${t.stage}|${t.phase}" aria-pressed="${t === cur}">${lbl(t.stage)} · ${t.phase}</button>`).join('')}</div></div>
   <div id="twoBody"></div></section>
  <section>${H.header({ title: 'Reasons for exclusion', sub: 'Why records were left out, with the reader’s own words.', infoHtml: infoPanel('Each exclusion criterion, how many records cited it, and examples of the reasoning.', 'Every example shows the reader’s rationale and the sentence it was based on. Counts are records with an exclude verdict from either screener, so they can differ slightly from the final counts in the flow.', esc(SC.methods.reasons_wall)) })}
   ${wallStages.map(sg => `<h3 class="h3" style="margin:18px 0 10px">${lbl(sg)}</h3><div class="wall">${SC.reasons_wall.filter(w => w.stage === sg).map(w => `<article class="wc"><div class="hd">${H.term(w.criterion, w.criterion)}<b>${esc(w.label || '')}</b><span class="cn">${fmt(w.count)}</span></div>
     <p class="rule">${esc(w.rule || '')}</p>${w.examples.map(e => `<div class="ex"><span class="meta">${recLink(e.work_id)} · screener ${esc(e.pass_label)}</span>${esc(e.rationale)}${e.quote ? `<blockquote class="quote">“${esc(e.quote)}”</blockquote>` : ''}</div>`).join('')}
     ${idList(w.works, 'All records excluded under this criterion')}
     ${sg === 'title-abstract' && PRED['ta-' + w.criterion] ? `<p style="margin:10px 0 0"><a href="#" data-node="ta-${esc(w.criterion)}">See the ${fmt(F.excluded[w.criterion])} excluded in the flow</a></p>` : ''}</article>`).join('')}</div>`).join('')}</section>
  ${criteriaSection(SC.panel, SC.methods)}</div>`;
  const cv = $('#curve'), hv = $('#cvh');
  hv.onmousemove = e => { const b = cv.getBoundingClientRect(), f = Math.min(1, Math.max(0, ((e.clientX - b.left) / b.width * 920 - 62) / (920 - 62 - 20))), i = Math.max(1, Math.round(f * N));
    H.tipHtml(`After <b>${fmt(i)}</b> records: <b>${fmt(rc.points[i - 1])}</b> included (${Math.round(100 * rc.points[i - 1] / rc.included_total)}% of all inclusions)`, e); };
  hv.onmouseleave = () => H.tipHtml(null);
  p.querySelectorAll('[data-s]').forEach(b => b.onclick = () => { S.stage = b.dataset.s; S.dmore = 20; saveHash({ stage: S.stage }); showTab('screening', true); });
  p.querySelectorAll('[data-node]').forEach(a => a.onclick = e => { e.preventDefault(); S.node = a.dataset.node; S.facet = {}; showTab('where'); });
  wireOpen(p); twoBody(cur);
}
const dash = v => v == null ? '<span class="meta">–</span>' : fmt(v);
const kv = rows => `<dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
const passTable = (o, label) => `<table class="t"><thead><tr><th>${label}</th><th class="r">Queued</th><th class="r">Decided</th><th class="r">Remaining</th></tr></thead><tbody>${Object.entries(o).sort().map(([k, v]) => `<tr><td>Screener ${esc(k)}</td><td class="r">${dash(v.queued)}</td><td class="r">${dash(v.decided)}</td><td class="r">${dash(v.remaining)}</td></tr>`).join('')}</tbody></table>`;
const viewTxt = v => v ? `${esc(H.pretty(v.verdict))}${v.criterion ? ' · ' + esc(v.criterion) : ''}${v.quote ? `<blockquote class="quote">“${esc(clip(v.quote, 220))}”</blockquote>` : ''}${v.anchor ? `<div class="meta">Anchor ${esc(v.anchor)}</div>` : ''}` : '<span class="meta">not decided</span>';
function panelSections(P, M) {
  if (!P) return '';
  const ruleTxt = s => `${fmt(s.n)} in a row ${s.below_score != null ? `scored below ${fmt(s.below_score)}` : 'excluded'}`;
  const rank = P.ranking ? kv([['Ranking', `<span class="mono">${esc(P.ranking.ranking_id)}</span>`], ['Model', esc(P.ranking.model_id)], ['Weights', `<span class="mono">${esc(P.ranking.weights_hash)}</span>`], ['Records ranked', fmt(P.ranking.count)]]) : '<div class="empty">No ranking has been recorded.</div>';
  const cal = P.calibration || {};
  const checks = (P.checks || []).map(c => `<article class="ck"><div class="hd"><b>${esc(c.name || c.draw_id)}</b><span class="tag">${esc(H.pretty(c.kind))}</span><span class="tag">${c.current ? 'Current' : 'Outdated'}</span><span class="meta">${fmt(c.labelled)} of ${fmt(c.drawn)} labelled${c.agreement != null ? ` · ${Math.round(100 * c.agreement)}% agreement` : ''} · ${fmt(c.disagreements)} disagreements</span></div>
    ${c.agreement_note ? `<p class="meta" style="margin:6px 0 0">${esc(c.agreement_note)}</p>` : ''}
    ${c.bands.length ? `<details class="idl"><summary>Bands</summary><div class="scroll"><table class="t"><thead><tr><th>Band</th><th class="r">Drawn</th><th class="r">Labelled</th><th class="r">Compared</th><th class="r">Agreed</th><th class="r">Agreement</th><th class="r">Would add includes</th><th class="r">Would add excludes</th><th class="r">Undecided</th></tr></thead><tbody>${c.bands.map(b => `<tr><td>${esc(b.band)}</td><td class="r">${fmt(b.drawn)}</td><td class="r">${fmt(b.labelled)}</td><td class="r">${fmt(b.compared)}</td><td class="r">${fmt(b.agreed)}</td><td class="r">${b.agreement == null ? '–' : Math.round(100 * b.agreement) + '%'}</td><td class="r">${fmt(b.would_add_includes)}</td><td class="r">${fmt(b.would_add_excludes)}</td><td class="r">${fmt(b.undecided)}</td></tr>`).join('')}</tbody></table></div></details>` : ''}</article>`).join('');
  const ca = P.cannot_assess || [];
  return `<section>${H.header({ title: 'Screening status', infoHtml: infoPanel('Where each screening pass stands, how the ranking was made and what the stop rules did.', 'Queued is what the pass was given, decided what it has finished, remaining what is left. A stale decision was made under an earlier protocol version.', esc(M.ranking) + '<p>' + esc(M.passes) + '</p><p>' + esc(M.stops) + '</p>') })}
   <div class="sc2" style="margin-top:12px"><div><h3 class="h3">Ranking</h3>${rank}</div>
   <div><h3 class="h3">Title and abstract</h3>${passTable(P.passes || {}, 'Pass')}<p class="meta" style="margin:8px 0 0">${P.records_left != null ? `${fmt(P.records_left)} records left for screener A · ` : ''}${fmt(P.stale_decisions)} stale decisions</p></div>
   ${P.full_text_passes ? `<div><h3 class="h3">Full text</h3>${passTable(P.full_text_passes, 'Pass')}</div>` : ''}</div>
   <h3 class="h3" style="margin:20px 0 8px">Stop rules</h3>
   ${(P.stops || []).length ? `<table class="t"><thead><tr><th>Rule</th><th class="r">Run so far</th><th>State</th><th class="r">Not screened</th></tr></thead><tbody>${P.stops.map(x => `<tr><td>Stop after ${esc(ruleTxt(x))}</td><td class="r">${fmt(x.run)} of ${fmt(x.n)}</td><td>${x.stopped ? 'Stopped' : 'Running'}</td><td class="r">${fmt(x.not_screened)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No stop rule is declared.</div>'}
   <p class="meta" style="margin:8px 0 0">Screening at title and abstract stops by a declared rule, and records not screened because of it are reported. ${fmt(P.deviations)} ${H.term('protocol', 'protocol')} deviations recorded.</p></section>
  <section>${H.header({ title: 'Calibration and checks', infoHtml: infoPanel('Whether the screeners were tested against the researcher’s own labels.', 'A draw is a sample of records the researcher labels; agreement compares those labels with the screener’s verdicts, band by band.', esc(M.calibration) + '<p>' + esc(M.checks) + '</p>') })}
   <div style="margin-top:12px">${kv([['Records drawn', dash(cal.drawn)], ['Labelled', dash(cal.labelled)], ['Required', cal.required ? 'Yes' : 'No'], ['Passed', Object.entries(cal.passed || {}).map(([k, v]) => `screener ${esc(k)}: ${v ? 'yes' : 'no'}`).join(', ') || '–']])}</div>
   ${checks || '<p class="meta" style="margin:10px 0 0">No calibration or audit draws yet.</p>'}</section>
  ${ca.length ? `<section>${H.header({ title: 'Full text to resolve', sub: `<span class="meta">${fmt(ca.length)} papers</span>`, infoHtml: infoPanel('Papers a screener could not assess from the full text and nobody has settled yet.', 'They stay promoted until resolved; the list blocks nothing.', esc(M.cannot_assess)) })}
   <div class="scroll"><table class="t" style="margin-top:12px"><thead><tr><th>Paper</th><th>Screener A</th><th>Screener B</th><th>Read</th></tr></thead><tbody>${ca.map(x => `<tr><td class="ti">${recLink(x.work_id)}<div class="meta"><a href="sources.html#tab=conversion&amp;conv=${encodeURIComponent(x.work_id)}">Conversion inspector</a></div></td><td style="white-space:normal">${viewTxt(x.passes.A)}</td><td style="white-space:normal">${viewTxt(x.passes.B)}</td><td>${x.read_command ? `<code class="mono">${esc(x.read_command)}</code>` : ''}</td></tr>`).join('')}</tbody></table></div>
   <p class="meta" style="margin:8px 0 0">To settle one: <code class="mono">${esc(ca[0].resolve_command)}</code></p></section>` : ''}`;
}
function criteriaSection(P, M) {
  const C = P && P.criteria || []; if (!C.length) return '';
  const bg = (n, b) => `${fmt(n)}${b ? ` <span class="meta">(${fmt(b)} kept as background)</span>` : ''}`;
  return `<section>${H.header({ title: 'Criteria', infoHtml: infoPanel('Each exclusion criterion, what it excludes, and how many records it removed at each stage.', 'Background means the excluded works are kept for context, not simply dropped.', esc(M.criteria)) })}
   <div class="scroll"><table class="t" style="margin-top:12px"><thead><tr><th>Criterion</th><th>What it excludes</th><th class="r">Title and abstract</th><th class="r">Full text</th></tr></thead><tbody>${C.map(c => `<tr><td>${H.term(c.id, c.id)}</td><td style="white-space:normal">${esc(c.statement || '')}</td><td class="r">${bg(c.ta_excluded, c.ta_background)}</td><td class="r">${bg(c.ft_excluded, c.ft_background)}</td></tr>`).join('')}</tbody></table></div></section>`;
}
const proceeds = v => v === 'include' || v === 'cannot-assess';
function twoBody(t) {
  const kv = k => k == null ? '<span class="meta">n/a</span>' : k.toFixed(2), tb = t.table, dis = t.disagreements;
  const F2 = { all: ['All', () => true], oa: ['A keeps, B excludes', x => proceeds(x.a_verdict) && !proceeds(x.b_verdict)], ob: ['B keeps, A excludes', x => !proceeds(x.a_verdict) && proceeds(x.b_verdict)], un: ['One was unsure', x => x.reason === 'unsure'] };
  const f = F2[S.dfilter] || F2.all, list = dis.filter(f[1]), crit = Object.entries(t.kappa_by_criterion);
  const cell = (n, key) => key ? `<td><button data-df="${key}" aria-label="${F2[key][0]}: ${n}">${fmt(n)}</button></td>` : `<td><div class="plain">${fmt(n)}</div></td>`;
  const dc = x => `<article class="dc"><h4>${recLink(x.work_id)}<span class="tag">${x.reason === 'unsure' ? 'One was unsure' : 'Different outcome'}</span></h4><div class="cols">${['a', 'b'].map(k => `<div><div class="vd">Screener ${k.toUpperCase()}: ${esc(H.pretty(x[k + '_verdict']))}${x[k + '_criterion'] ? ' · ' + esc(x[k + '_criterion']) : ''}</div><p>${esc(x[k + '_rationale'] || '')}</p>${x[k + '_quote'] ? `<blockquote class="quote">“${esc(x[k + '_quote'])}”</blockquote>` : ''}</div>`).join('')}</div></article>`;
  $('#twoBody').innerHTML = `<div class="two"><div>
    <div class="stats"><span><span class="big">${t.kappa == null ? 'n/a' : t.kappa.toFixed(2)}</span> <span class="h3">${H.term('kappa', 'κ')}</span></span><span class="meta">${fmt(t.n)} records read by both · ${Math.round(100 * t.agreement)}% same outcome</span></div>
    <table class="mx" style="margin-top:12px"><thead><tr><th></th><th>B keeps</th><th>B excludes</th></tr></thead><tbody><tr><th>A keeps</th>${cell(tb.both_proceed)}${cell(tb.only_a_proceeds, 'oa')}</tr><tr><th>A excludes</th>${cell(tb.only_b_proceeds, 'ob')}${cell(tb.neither_proceeds)}</tr></tbody></table>
    ${[['both_proceed', 'Both keep'], ['only_a_proceeds', 'Only A keeps'], ['only_b_proceeds', 'Only B keeps'], ['neither_proceeds', 'Neither keeps']].map(([k, l]) => idList((t.table_works || {})[k], l)).join('')}
    <p class="meta">Among the ${fmt(t.both_excluded)} both excluded, ${fmt(t.same_criterion)} cite the same criterion.</p></div>
   <div><h3 class="h3" style="margin-bottom:8px">κ by criterion</h3><div class="kb">${crit.map(([k, v]) => `<span>${H.term(k, k)} <span class="meta">${esc(critLabel(k))}</span></span><div class="bx"><i style="width:${v == null ? 0 : Math.max(0, v) * 100}%"></i></div><span class="v">${v == null ? 'n/a' : v.toFixed(2)}</span>`).join('')}</div></div></div>
   <div class="bar" style="margin:22px 0 10px"><h3 class="h3">Disagreements</h3><div class="legend">${Object.entries(F2).map(([k, v]) => `<button class="chip" data-df="${k}" aria-pressed="${k === S.dfilter}">${v[0]} <span class="n">${dis.filter(v[1]).length}</span></button>`).join('')}</div></div>
   ${list.length ? `<div class="dis">${list.slice(0, S.dmore).map(dc).join('')}</div>${list.length > S.dmore ? `<p><button class="btn" id="dmore">Show ${Math.min(20, list.length - S.dmore)} more</button> <span class="meta">${S.dmore} of ${fmt(list.length)} shown</span></p>` : ''}` : '<div class="empty">No disagreements in this group.</div>'}`;
  const b = $('#twoBody'); b.querySelectorAll('[data-df]').forEach(x => x.onclick = () => { S.dfilter = x.dataset.df; S.dmore = 20; saveHash({ dis: S.dfilter === 'all' ? null : S.dfilter }); twoBody(t); });
  const m = $('#dmore'); if (m) m.onclick = () => { S.dmore += 20; twoBody(t); }; wireOpen(b);
}

/* ================= tab 3: replay ================= */
const STG = { found: 'Found', deduplicated: 'De-duplicated', 'title-abstract': 'Title and abstract', retrieval: 'Full text sought', conversion: 'Converted', 'full-text': 'Full-text review', 'read-in-full': 'Read in full', 'references-extracted': 'References read', 'cited-by-corpus': 'Cited by the corpus' };
const stgL = s => STG[s] || H.pretty(s);
const FATE_TOK = { duplicate: '--h-null', ta_excluded: '--exc', ta_pending: '--mut', not_sought: '--h-feedback', not_retrieved: '--h-collab', ft_excluded: '--h-physical', ft_pending: '--l-benchmark', included: '--inc' };
function tabReplay(p) {
  const RP = d.journeys.replay, T1 = RP.days * 86400, nS = RP.stages.length, reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const recs = RP.records.map(([i, f, s]) => ({ i, f, s: s.slice().sort((a, b) => a[1] - b[1]), u: (i * 0.7548776662466927) % 1, v: (i * 0.5698402909980532) % 1 }));
  const byFate = RP.fates.map((_, f) => recs.filter(r => r.f === f)), fcount = byFate.map(a => a.length), TR = reduce ? 0 : Math.max(1800, T1 * 0.004);
  let T = Math.min(T1, Math.max(0, +(H.hash.get().get('t')) || T1)), playing = false, speed = 86400 / 4, hl = -1, raf = 0, last = 0, cols = {};
  const perDay = Array.from({ length: RP.days }, (_, k) => Object.values(RP.hist).reduce((a, h) => a + (h[k] || 0), 0)), maxDay = Math.max(1, ...perDay);
  const bars = perDay.map((n, k) => { const w = 100 / RP.days, h = Math.sqrt(n / maxDay) * 46; return `<rect x="${(k * w + w * .08).toFixed(2)}%" width="${(w * .84).toFixed(2)}%" y="${52 - h}" height="${h}" fill="var(--seq-3)"><title>${esc(dayFmt(RP.t0 + k * 86400))}: ${fmt(n)} stage entries</title></rect>`; }).join('');
  p.innerHTML = `<div class="fpane rp"><section>${H.header({ title: 'Replay', sub: 'Every record moves through the stages at the time it really did.', infoHtml: infoPanel('How the review unfolded over time.', 'Each dot is a record. It sits in the stage it had reached at the chosen moment and moves on when the next event happens. Colour is the record’s final outcome. Drag the slider to any moment; the bars under it show how much happened each day.', esc(d.journeys.methods.replay)) })}
   <div class="card" style="padding:12px;margin-top:12px"><canvas id="cv" role="img" aria-label="Records moving through the review stages"></canvas>
   <div class="ctl"><button class="btn primary" id="play" ${reduce ? 'disabled title="Animation is off because your system prefers reduced motion"' : ''}>Play</button>
    <div class="seg" role="group" aria-label="Speed">${[[3600 * 6, '6 h per s'], [86400, '1 day per s'], [86400 * 3, '3 days per s']].map(([v, l]) => `<button data-sp="${v}" aria-pressed="${v === speed}">${l}</button>`).join('')}</div>
    <span class="when" id="when"></span>${reduce ? '<span class="meta">Animation is off; use the slider.</span>' : ''}</div>
   <div class="tl"><svg viewBox="0 0 100 56" preserveAspectRatio="none" aria-hidden="true" style="overflow:visible"><g>${bars}</g></svg><input type="range" id="sl" min="0" max="${T1}" step="60" value="${T}" aria-label="Moment in the review's history"></div>
   <div class="stg" id="stg" aria-live="off"></div></div>
   <div class="legend" style="margin-top:12px" id="lg">${RP.fates.map((f, i) => `<button class="chip" data-f="${i}" aria-pressed="false"><span class="dot" style="background:var(${FATE_TOK[f] || '--mut'})"></span>${esc(FATE[f] || f)} <span class="n">${fmt(fcount[i])}</span></button>`).join('')}</div></section></div>`;
  const cv = $('#cv'), ctx = cv.getContext('2d'), HT = 400; let W = 0;
  const size = () => { const dpr = devicePixelRatio || 1; W = cv.clientWidth || 900; cv.width = W * dpr; cv.height = HT * dpr; cv.style.height = HT + 'px'; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
  const pos = (r, s) => { const cw = W / nS; return [s * cw + 10 + r.u * (cw - 20), 46 + r.v * (HT - 58)]; };
  const draw = () => { ctx.clearRect(0, 0, W, HT); const cw = W / nS, cnt = Array(nS).fill(0);
    ctx.fillStyle = cssv('--raised'); for (let s = 0; s < nS; s++) ctx.fillRect(s * cw + 3, 34, cw - 6, HT - 40);
    byFate.forEach((arr, f) => { ctx.fillStyle = cssv(FATE_TOK[RP.fates[f]] || '--mut'); ctx.globalAlpha = hl < 0 || hl === f ? 1 : 0.12;
      for (const r of arr) { let k = -1; for (let j = 0; j < r.s.length && r.s[j][1] <= T; j++) k = j; if (k < 0) continue;
        let [x, y] = pos(r, r.s[k][0]); if (hl < 0 || hl === f) cnt[r.s[k][0]]++;
        if (k > 0 && TR && T - r.s[k][1] < TR) { const [x0, y0] = pos(r, r.s[k - 1][0]), a = (T - r.s[k][1]) / TR; x = x0 + (x - x0) * a; y = y0 + (y - y0) * a; }
        ctx.fillRect(x - 1.4, y - 1.4, 2.8, 2.8); } });
    ctx.globalAlpha = 1; ctx.fillStyle = cssv('--mut'); ctx.font = '500 11px ' + cssv('--f-ui'); ctx.textAlign = 'left';
    RP.stages.forEach((s, i) => { ctx.fillText(stgL(s), i * cw + 8, 18); ctx.fillStyle = cssv('--fg'); ctx.fillText(fmt(cnt[i]), i * cw + 8, 30); ctx.fillStyle = cssv('--mut'); });
    $('#when').textContent = stampFmt(RP.t0 + T); $('#sl').value = T;
    $('#stg').innerHTML = RP.stages.map((s, i) => `<span>${stgL(s)} <b>${fmt(cnt[i])}</b></span>`).join(''); };
  const frame = ts => { if (!playing) return; const dt = Math.min(0.1, (ts - last) / 1000); last = ts; T = Math.min(T1, T + dt * speed); draw();
    if (T >= T1) setPlay(false); else raf = requestAnimationFrame(frame); };
  const setPlay = on => { playing = on && !reduce; $('#play').textContent = playing ? 'Pause' : (T >= T1 ? 'Play again' : 'Play'); cancelAnimationFrame(raf);
    if (playing) { if (T >= T1) T = 0; last = performance.now(); raf = requestAnimationFrame(frame); } };
  $('#play').onclick = () => setPlay(!playing);
  $('#sl').oninput = e => { T = +e.target.value; draw(); }; $('#sl').onchange = () => { H.hash.set({ t: T >= T1 ? null : Math.round(T) }); };
  p.querySelectorAll('[data-sp]').forEach(b => b.onclick = () => { speed = +b.dataset.sp; p.querySelectorAll('[data-sp]').forEach(x => x.setAttribute('aria-pressed', x === b)); });
  p.querySelectorAll('#lg [data-f]').forEach(b => b.onclick = () => { hl = hl === +b.dataset.f ? -1 : +b.dataset.f; p.querySelectorAll('#lg [data-f]').forEach(x => x.setAttribute('aria-pressed', +x.dataset.f === hl)); draw(); });
  size(); draw(); setPlay(false);
  const rs = () => { size(); draw(); }; addEventListener('resize', rs);
  const stopLayers = layerReplay(p.querySelector('.fpane'), reduce);
  cleanup = () => { playing = false; cancelAnimationFrame(raf); removeEventListener('resize', rs); stopLayers(); };
}
/* The researcher's layer moves, one step per day, as bars per layer. Returns a stop function. */
function layerReplay(root, reduce) {
  const LR = d.flow.layer_replay; if (!LR) return () => {};
  const names = [...LR.layers, 'unlayered'], steps = LR.steps || [], nS = steps.length;
  const sec = document.createElement('section');
  sec.innerHTML = `${H.header({ title: 'Layer moves', sub: 'How the researcher’s moves changed the layers, day by day.', infoHtml: infoPanel('How the researcher’s moves changed which layer each paper sits in.', 'The first position is every paper on the layer the layer miner gave it. Each later step is one day of moves; the bars show how many papers sit on each layer after it.', esc(LR.methods)) })}
   ${nS ? `<div class="card" style="padding:14px;margin-top:12px"><div class="lyb" id="lyb"></div>
   <div class="ctl"><button class="btn primary" id="lyPlay" ${reduce ? 'disabled title="Animation is off because your system prefers reduced motion"' : ''}>Play</button><span class="when" id="lyWhen"></span><span class="meta" id="lyMv"></span></div>
   <input type="range" id="lySl" min="0" max="${nS}" step="1" value="${nS}" aria-label="Day of layer moves" style="width:100%;accent-color:var(--acc)"></div>` : '<div class="empty">No layer moves have been recorded; every paper is on the layer the layer miner gave it.</div>'}`;
  root.appendChild(sec); if (!nS) return () => {};
  const state = k => { const a = LR.start.slice(); for (let i = 0; i < k; i++) steps[i].mv.forEach(([w, l]) => { a[w] = l; }); return a; };
  const tok = n => (H.LAYERS.find(l => l[0] === n) || [, , '--l-unlayered'])[2];
  let k = nS, tm = 0;
  const draw = () => { const a = state(k), c = names.map(() => 0); a.forEach(l => { c[l < 0 ? names.length - 1 : l]++; }); const mx = Math.max(1, ...c);
    sec.querySelector('#lyb').innerHTML = names.map((n, i) => `<span>${esc(H.layerLabel(n))}</span><span class="tr"><i style="width:${100 * c[i] / mx}%;background:var(${tok(n)})"></i></span><span class="v">${fmt(c[i])}</span>`).join('');
    sec.querySelector('#lyWhen').textContent = k === 0 ? 'Layer miner’s reading' : steps[k - 1].d;
    sec.querySelector('#lyMv').textContent = k === 0 ? '' : `${fmt(steps[k - 1].mv.length)} papers moved that day`; sec.querySelector('#lySl').value = k; sec.querySelector('#lyPlay').textContent = tm ? 'Pause' : 'Play'; };
  const stop = () => { clearInterval(tm); tm = 0; };
  sec.querySelector('#lySl').oninput = e => { stop(); k = +e.target.value; draw(); };
  sec.querySelector('#lyPlay').onclick = () => { if (tm) { stop(); draw(); return; } if (k >= nS) k = 0; tm = setInterval(() => { k++; if (k >= nS) stop(); draw(); }, 600); draw(); };
  draw();
  return stop;
}

/* ================= tab 4: paths (swimlanes) ================= */
const FINAL = d.journeys.replay.stages.length;
const replayIdx = (() => { const m = new Map(); d.journeys.replay.ids.forEach((id, k) => m.set(id, d.journeys.replay.records[k])); return m; })();
const JI = d.journeys.journey_index && d.journeys.journey_index.works || null;
function laneOf(id) {
  const RP = d.journeys.replay, rr = replayIdx.get(id), rec = RI.get(id), ji = JI && JI[id];
  if (!rr && !ji) return { id, none: true };
  const fate = rr ? RP.fates[rr[1]] : (rec && rec.fate), crit = rec && rec.criterion;
  let stops, detail = false;
  if (ji && ji.length) { detail = true; stops = ji.map(([si, ts, kind, model, outcome, criterion, text, quote, eid, doc, prim]) => ({ si, t: Date.parse(ts) / 1000, kind, model, outcome, criterion, text, quote, eid, doc, prim })); }
  else stops = rr[2].map(([si, sec]) => ({ si, t: RP.t0 + sec, outcome: 'reached' }));
  stops.sort((a, b) => a.t - b.t);
  const last = stops[stops.length - 1], fin = { si: FINAL, t: last ? last.t : RP.t0, outcome: (FATE[fate] || fate) + (crit ? ' · ' + crit : ''), fate, final: true };
  const outs = {}; stops.forEach(s => outs[s.si] = s.outcome); outs[FINAL] = fin.outcome;
  return { id, title: titleOf(id), fate, crit, stops, fin, detail, outs };
}
function diverge(lanes) {
  if (lanes.length < 2) return;
  for (let s = 0; s <= FINAL; s++) { const have = lanes.filter(l => s in l.outs); if (have.length < 2) continue; const c = {}; have.forEach(l => c[l.outs[s]] = (c[l.outs[s]] || 0) + 1);
    const top = Object.entries(c).sort((a, b) => b[1] - a[1])[0]; if (top[1] * 2 <= have.length) continue;
    have.forEach(l => { if (l.outs[s] !== top[0] && l.div == null) l.div = s; }); }
}
const outTok = o => /exclu|not |fail|merged|pending/i.test(o || '') ? '--exc' : /includ|kept|read|retriev|convert|found/i.test(o || '') ? '--inc' : '--mut';
function recMeta(id) {
  const r = RI.get(id); if (!r) return '';
  const abs = R.filter(x => x.duplicate_of === id).map(x => x.id);
  const part = (k, v) => v ? `<span class="meta">${k} ${v}</span>` : '';
  return `<div class="rm">${part('Year', esc(r.year || ''))}${part('Source group', esc(r.source))}${part('Sources', esc((r.sources || []).join(', ')))}${part('Step reached', esc(r.step + ', ' + r.outcome + (r.reason ? ' (' + r.reason + ')' : '')))}${r.duplicate_of ? part('Duplicate of', recLink(r.duplicate_of)) : ''}</div>${idList(abs, 'Duplicates merged into it')}`;
}
function tabPaths(p) {
  const RP = d.journeys.replay, ids = S.lanes.slice(0, 20), lanes = ids.map(laneOf), real = lanes.filter(l => !l.none); diverge(real);
  p.innerHTML = `<div class="fpane"><section>${H.header({ title: ids.length === 1 && real[0] ? 'Path of one paper' : 'Paths', sub: 'One lane per paper on a shared time axis.', infoHtml: infoPanel('The route each chosen paper took through the review, and where the routes parted.', 'Time runs left to right on one axis for every paper. Each dot is a stop: hover or focus it for the stage, who acted, the outcome and the evidence. A ring marks where a path first differs from what most of the papers did at that stage. Open the list under a lane for every stop with the time spent between them.', esc(d.journeys.methods.swimlanes)) })}
   <div class="bar" style="margin:12px 0"><div class="picker"><input type="search" id="pk" placeholder="Add a paper by title" aria-label="Add a paper to compare" autocomplete="off"><ul id="pkl" hidden></ul></div>
    <div class="actives" id="lch">${lanes.map(l => `<span class="chip" aria-pressed="true">${esc((l.title || l.id).length > 48 ? (l.title || l.id).slice(0, 47) + '\u2026' : (l.title || l.id))} <button data-rm="${esc(l.id)}" aria-label="Remove ${esc(l.title || l.id)}" style="all:unset;cursor:pointer">×</button></span>`).join('')}${ids.length ? '<button class="chip" id="clr">Clear</button>' : ''}</div></div>
   ${ids.length ? '<p class="sx-hint" style="margin-top:0">Scroll sideways to see the rest →</p>' : ''}<div id="lanes">${ids.length ? '' : '<div class="empty">Pick one or more papers to see their paths. Links from a paper’s panel, from Corpus and from Explore bring you here with the papers filled in.</div>'}</div></section></div>`;
  const edit = f => { S.lanes = f(S.lanes).slice(0, 20); saveHash(); showTab('paths', true); };
  p.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => edit(a => a.filter(x => x !== b.dataset.rm)));
  const clr = $('#clr'); if (clr) clr.onclick = () => edit(() => []);
  const pk = $('#pk'), pl = $('#pkl');
  pk.oninput = () => { const q = pk.value.trim().toLowerCase(); if (q.length < 2) { pl.hidden = true; return; }
    const hits = H.RF.works.filter(w => w.title.toLowerCase().includes(q) && !S.lanes.includes(w.id)).slice(0, 8); pl.hidden = !hits.length;
    pl.innerHTML = hits.map(w => `<li role="option" tabindex="0" data-id="${esc(w.id)}">${esc(w.title)} <span class="meta">${esc(w.year || '')}</span></li>`).join('');
    pl.querySelectorAll('li').forEach(li => { const pick = () => edit(a => [...a, li.dataset.id]); li.onclick = pick; li.onkeydown = e => { if (e.key === 'Enter') pick(); }; }); };
  pk.onkeydown = e => { if (e.key === 'Enter') { const f = pl.querySelector('li'); f && f.click(); } else if (e.key === 'Escape') pl.hidden = true; };
  if (!ids.length) return;
  const rows = [...new Set(real.flatMap(l => [...l.stops.map(s => s.si), FINAL]))].sort((a, b) => a - b), RH = 16;
  const all = real.flatMap(l => [...l.stops, l.fin]).map(s => s.t); let t0 = Math.min(...all, Infinity), t1 = Math.max(...all, -Infinity);
  if (!isFinite(t0)) t0 = t1 = RP.t0; if (t1 - t0 < 3600) { t0 -= 1800; t1 += 1800; } const pad = (t1 - t0) * 0.02; t0 -= pad; t1 += pad;
  const Wd = 960, gx = 128, X = t => gx + (Wd - gx - 24) * (t - t0) / (t1 - t0), step = (t1 - t0) > 30 * 86400 ? 7 * 86400 : 86400, ticks = []; for (let t = Math.ceil(t0 / step) * step; t < t1; t += step) ticks.push(t);
  const rowY = si => 14 + rows.indexOf(si) * RH, Hl = rows.length * RH + 22, rowName = si => si === FINAL ? 'Final outcome' : stgL(RP.stages[si]);
  const axis = `<svg viewBox="0 0 ${Wd} 24" aria-hidden="true">${ticks.map(t => `<text class="axis" x="${X(t)}" y="16" text-anchor="middle">${dayFmt(t)}</text>`).join('')}</svg>`;
  $('#lanes').innerHTML = axis + lanes.map((l, li) => {
    if (l.none) return `<div class="lane"><div class="lh"><b>${esc(titleOf(l.id))}</b></div>${recMeta(l.id)}<div class="empty">This paper’s path is available in the live hub; this copy carries paths for the records of the review only.</div></div>`;
    const pts = [...l.stops, l.fin];
    const svg = `<svg viewBox="0 0 ${Wd} ${Hl}" role="img" aria-label="Path of ${esc(l.title)}">${ticks.map(t => `<line class="gl" x1="${X(t)}" x2="${X(t)}" y1="0" y2="${Hl}"/>`).join('')}
     ${rows.map(si => `<line class="rl" x1="${gx}" x2="${Wd - 24}" y1="${rowY(si)}" y2="${rowY(si)}"/><text class="rowl" x="0" y="${rowY(si) + 3}">${esc(rowName(si))}</text>`).join('')}
     <polyline class="pth" points="${pts.map(s => `${X(s.t).toFixed(1)},${rowY(s.si)}`).join(' ')}"/>
     ${pts.slice(1).map((s, k) => { const a = pts[k], dx = X(s.t) - X(a.t); return dx > 52 ? `<text class="dur" x="${((X(s.t) + X(a.t)) / 2).toFixed(1)}" y="${((rowY(s.si) + rowY(a.si)) / 2 - 5).toFixed(1)}" text-anchor="middle">${durFmt(s.t - a.t)}</text>` : ''; }).join('')}
     ${pts.map((s, k) => { const x = X(s.t).toFixed(1), y = rowY(s.si), tok = s.final ? (s.fate === 'included' ? '--inc' : /pending/.test(s.fate) ? '--mut' : '--exc') : outTok(s.outcome);
       return `${s.si === l.div ? `<circle class="ring" cx="${x}" cy="${y}" r="9"/>` : ''}${s.final ? `<rect class="pt" tabindex="0" data-l="${li}" data-k="${k}" x="${x - 5}" y="${y - 5}" width="10" height="10" rx="2" fill="var(${tok})"/>` : `<circle class="pt" tabindex="0" data-l="${li}" data-k="${k}" cx="${x}" cy="${y}" r="5" fill="var(${tok})"/>`}`; }).join('')}</svg>`;
    const dur = (s, k) => k ? durFmt(Math.max(0, s.t - pts[k - 1].t)) : '';
    const tbl = `<table class="t"><thead><tr><th>When</th><th>Stage</th><th>Who</th><th>Outcome</th><th>Criterion</th><th class="r">After</th><th>Reason</th><th>Quote</th><th>Document</th><th>Primary</th></tr></thead><tbody>${pts.map((s, k) => `<tr><td>${esc(stampFmt(s.t))}</td><td>${esc(rowName(s.si))}</td><td>${s.kind ? esc(s.kind) + (s.model ? ' · ' + esc(s.model) : '') : '<span class="meta">—</span>'}</td><td>${esc(s.outcome === 'reached' ? '' : s.outcome)}</td><td>${esc(s.criterion || '')}</td><td class="r">${dur(s, k)}</td><td>${esc(s.text || '')}</td><td>${esc(s.quote || '')}</td><td class="mono">${esc(s.doc || '')}</td><td class="mono">${esc(s.prim || '')}</td></tr>`).join('')}</tbody></table>`;
    return `<div class="lane"><div class="lh">${H.byId.has(l.id) ? `<a href="#" data-open="${esc(l.id)}">${esc(l.title)}</a>` : `<b>${esc(l.title)}</b>`}<span class="meta">${esc(FATE[l.fate] || l.fate)}${l.crit ? ' · ' + esc(l.crit) : ''}${l.div != null ? ` · parts from the others at ${esc(rowName(l.div).toLowerCase())}` : ''}</span></div>${recMeta(l.id)}${svg}
      <details ${real.length === 1 ? 'open' : ''}><summary>All stops</summary>${l.detail ? '' : '<p class="meta">Here the stops carry stage and time. Who acted, the outcome and the quote are in the live hub.</p>'}<div class="scroll">${tbl}</div></details></div>`; }).join('');
  const root = $('#lanes'); wireOpen(root);
  root.querySelectorAll('.pt').forEach(el => { const l = lanes[+el.dataset.l], s = [...l.stops, l.fin][+el.dataset.k];
    const html = `<b>${esc(rowName(s.si))}</b><br>${esc(stampFmt(s.t))}${s.kind ? `<br>${esc(s.kind)}${s.model ? ' · ' + esc(s.model) : ''}` : ''}<br>${esc(s.outcome === 'reached' ? '' : s.outcome)}${s.criterion ? ' · ' + esc(s.criterion) : ''}${s.text ? `<br><i>${esc(s.text)}</i>` : ''}${s.quote ? `<br>“${esc(s.quote)}”` : ''}`;
    el.onmousemove = e => H.tipHtml(html, e); el.onmouseleave = () => H.tipHtml(null); el.onfocus = () => miniTip(html, el); el.onblur = () => H.tipHtml(null); });
}

showTab(S.tab, true);
}
