/* Landscape page: the approaches (techniques) AI-science systems use, stage by stage. EXPLORATORY: derived from the
   technique miners' first-reading (pass A) rows, uncalibrated, never enters a report. Payloads: shell,
   landscape (services/hub_landscape: counts, compact rows, edges, candidates) and landscape_uses (evidence rows
   with the verbatim quote and anchor, loaded only when an approach is opened). Every figure is counted in this
   script from the rows or read from the payload; nothing is typed. The lens (layer, evidence, status) is
   recomputed here from the rows; candidates, co-use and agreement are the server's, default lens. */
/*ego-layout-begin*/
/* Ego-graph geometry, a pure function of the neighbour count: two label columns (right and left of the centre),
   neighbours dealt alternately, evenly spaced from top to bottom, so no label touches another or a line's end.
   Returns one {x, y, tx, anchor, side} per neighbour; same count, same numbers. */
const EGO = { W: 760, H: 440, colDx: 150, pad: 28, chars: 26, cw: 6.4, lineH: 26 };
function egoLayout(n) {
  const right = Math.ceil(n / 2), left = n - right, out = [];
  const ys = k => i => k <= 1 ? EGO.H / 2 : EGO.pad + i * (EGO.H - 2 * EGO.pad) / (k - 1);
  const yr = ys(right), yl = ys(left);
  for (let i = 0; i < n; i++) {
    const isRight = i % 2 === 0, k = i >> 1;
    const x = EGO.W / 2 + (isRight ? EGO.colDx : -EGO.colDx), y = (isRight ? yr : yl)(k);
    out.push({ x, y, tx: x + (isRight ? 9 : -9), anchor: isRight ? 'start' : 'end', side: isRight ? 'right' : 'left' });
  }
  return out;
}
/*ego-layout-end*/
HUB.load(['shell']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'landscape', crumb: 'Landscape' });
  const { esc, fmt } = H;
  main.classList.add('ls');

  /* ---------- page style (kit tokens only) ---------- */
  if (!document.getElementById('ls-css')) {
    const s = document.createElement('style'); s.id = 'ls-css';
    s.textContent = `
.ls{padding-top:16px}
.ls .lead{max-width:60ch;margin:10px 0 14px}
.ls .xnote{border-left:4px solid var(--h-feedback);background:var(--surface);border-radius:var(--r-s);padding:10px 14px;margin:10px 0 16px;font-size:var(--t-s);color:var(--mut);max-width:80ch}
.ls .xnote b{color:var(--fg);letter-spacing:.06em;text-transform:uppercase;font-size:var(--t-xs)}
.ls .lensbar{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:6px 0 4px}
.ls .lensbar label{display:flex;flex-direction:column;gap:4px;font-size:var(--t-xs);color:var(--mut)}
.ls .lensbar select{min-width:150px}
.ls .nowlens{font-size:var(--t-s);color:var(--mut);margin:4px 0 18px}
.ls .sec{margin:30px 0 0}
.ls .stages{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin-top:10px}
.ls .scard{background:var(--surface);border-radius:var(--r);padding:14px 16px;min-width:0}
.ls .scard h3{margin:0 0 6px}
.ls .scard dl{margin:0;display:grid;grid-template-columns:1fr auto;gap:3px 12px;font-size:var(--t-s)}
.ls .scard dt{color:var(--mut)}.ls .scard dd{margin:0;text-align:right;font-family:var(--f-mono)}
.ls .scard .ag{margin-top:8px;padding-top:8px;border-top:1px solid var(--hair);font-size:var(--t-xs);color:var(--mut)}
.ls .legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:var(--t-xs);color:var(--mut);margin:8px 0}
.ls .legend span{display:inline-flex;align-items:center;gap:6px}
.ls .sw{width:11px;height:11px;border-radius:2px;display:inline-block;flex:none}
.ls .mix{display:flex;height:12px;min-width:120px;background:var(--raised);border-radius:3px;overflow:hidden}
.ls .mix i{display:block;height:100%}
.ls .e-independent-test{background:var(--inc)}.ls .e-own-ablation{background:var(--acc)}.ls .e-own-comparison{background:var(--seq-3)}
.ls .e-asserted-only{background:var(--h-feedback)}.ls .e-reported-failure{background:var(--exc)}.ls .e-not-stated{background:var(--l-off)}
.ls .grp{margin:22px 0 0}
.ls .grp h3{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.ls table.t td.name button,.ls .lnk{all:unset;cursor:pointer;color:var(--acc);text-decoration:underline;text-underline-offset:3px}
.ls .lnk:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.ls .wbar{display:inline-block;height:8px;border-radius:2px;background:var(--seq-3);vertical-align:middle;margin-right:8px}
.ls .zero{font-size:var(--t-xs);color:var(--dim);margin:6px 0 0}
.ls .cand{background:var(--surface);border-radius:var(--r);padding:12px 14px;margin:8px 0;min-width:0}
.ls .cand .st{margin:0 0 6px}
.ls .cand small,.ls .cand .meta{display:block;margin-top:4px}
.ls .flag{display:inline-block;border:1px solid var(--h-feedback);border-radius:999px;padding:0 8px;margin:2px 4px 2px 0;font-size:var(--t-xs);color:var(--fg)}
.ls details{margin:8px 0}
.ls summary{cursor:pointer;color:var(--fg);font-weight:500}
.ls .crumbs{font-size:var(--t-s);margin-bottom:10px}
.ls .two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start}
.ls .scrollx{overflow-x:auto}
.ls svg.ego{width:100%;height:auto;max-width:800px;background:var(--surface);border-radius:var(--r)}
.ls svg.ego text{fill:var(--fg);font:400 11px var(--f-ui)}
.ls svg.ego .dimt{fill:var(--mut)}
.ls svg.ego .ed{stroke:var(--mut);fill:none}
.ls svg.ego .nd{fill:var(--raised);stroke:var(--line)}
.ls svg.ego .cn{fill:var(--acc-soft);stroke:var(--acc);stroke-width:1.5}
.ls svg.ego a{cursor:pointer;text-decoration:none}
.ls svg.ego a:hover text{text-decoration:underline}
.ls svg.ego .dot{fill:var(--acc)}
.ls .gseg{display:inline-flex;gap:0;margin:8px 0 6px;border:1px solid var(--line);border-radius:var(--r-s);overflow:hidden}
.ls .gseg button{all:unset;cursor:pointer;padding:6px 14px;font-size:var(--t-s);color:var(--mut)}
.ls .gseg button[aria-pressed=true]{background:var(--acc-soft);color:var(--fg);font-weight:500}
.ls .gseg button:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
.ls svg.gr{display:block;width:100%;min-width:880px;height:auto;background:var(--surface);border-radius:var(--r)}
.ls svg.gr text{fill:var(--fg);font:400 11px var(--f-ui);paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.ls svg.gr .colh{fill:var(--mut);font-weight:500;letter-spacing:.04em;text-transform:uppercase;font-size:10px}
.ls svg.gr .ge{fill:none;opacity:.5}
.ls svg.gr .gn{cursor:pointer}
.ls svg.gr .gn circle,.ls svg.gr .gn rect{stroke:var(--fg);stroke-width:1}
.ls svg.gr .gn:focus-visible circle,.ls svg.gr .gn:focus-visible rect{stroke-width:3;stroke:var(--acc)}
.ls svg.gr.hot .ge,.ls svg.gr.hot .gn{opacity:.18}
.ls svg.gr.hot .ge.on{opacity:.95}.ls svg.gr.hot .gn.on{opacity:1}
.ls svg.gr .gn:hover text{text-decoration:underline}
.ls .empty{color:var(--mut);padding:10px 0;font-size:var(--t-s)}
.ls td.q{max-width:520px}
.ls .t td.r{white-space:nowrap}
.ls .status{color:var(--mut);padding:18px 0}
.ls .foot{margin-top:36px;color:var(--dim);font-size:var(--t-xs);display:flex;gap:4px;align-items:center;flex-wrap:wrap}
@media (max-width:1100px){.ls .two{grid-template-columns:minmax(0,1fr)}}
@media (max-width:760px){.ls .lead{font-size:20px}.ls .lensbar select{min-width:0;width:100%}.ls .lensbar label{flex:1 1 100%}.ls .mix{min-width:70px}.ls td.q{max-width:none}}`;
    document.head.appendChild(s);
  }

  /* ---------- vocabulary: an approach is what the code calls a technique ---------- */
  const NOTICE_HEAD = 'Exploratory';
  /* the same words as the payload's notice (hub_landscape / model.technique_graph.NOTICE), for the states before it arrives */
  const NOTICE_TEXT = 'uncalibrated miners, pass A, interpretation layer, not evidence; not found in this corpus is not absent from the field; no figure here enters a report';
  const noticeBox = (text, more) => `<div class="xnote" role="note"><b>${esc(NOTICE_HEAD)}</b> ${esc(text)}.${more ? '<br>' + esc(more) : ''}</div>`;
  const EV_LABEL = { 'independent-test': 'Tested by others', 'own-ablation': 'Own ablation', 'own-comparison': 'Own comparison', 'asserted-only': 'Asserted only', 'reported-failure': 'Reported failure', 'not-stated': 'Not stated' };
  const evLabel = e => EV_LABEL[e] || H.pretty(e);
  const stLabel = s => H.pretty(s);
  const short = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1).trim() + '…' : s; };
  const cap = t => String(t).charAt(0).toUpperCase() + String(t).slice(1);
  const nf = v => v == null ? 'none' : Number(v).toFixed(2);

  /* the shell lists the included papers; a work outside it cannot open the drawer, so it is plain text */
  const paper = (id, title) => H.byId.has(id)
    ? `<button type="button" class="lnk" data-paper="${esc(id)}">${esc(title || H.byId.get(id).title)}</button>`
    : `<span>${esc(title || id)}</span>`;

  main.innerHTML = H.header({ level: 1, kicker: esc(NOTICE_HEAD) + ' · ' + H.term('technique', 'techniques') + ' by stage', title: 'Landscape' })
    + noticeBox(NOTICE_TEXT)
    + '<p class="status" role="status" id="ls-wait">Building the landscape. It reads every technique reading once, so the first build takes about a minute. This page fills in by itself.</p>';

  H.load(['landscape']).then(p => start(p.landscape)).catch(e => {
    const w = document.getElementById('ls-wait');
    if (w) w.classList.remove('status'), w.classList.add('empty');
    if (w) w.textContent = 'The landscape is not ready: ' + String(e && e.message || e) + '. Reload in a moment.';
  });

  function start(D) {
    const CAT = D.catalogue, W = D.works, R = D.rows, EVA = D.evidence_all, STA = D.statuses;
    const catById = new Map(CAT.map((c, i) => [c.id, i]));
    const workIdx = new Map(W.map((w, i) => [w.id, i]));
    const stages = (D.stage_order.length ? [...D.stage_order] : [...new Set(CAT.map(c => c.stage))]).sort((a, b) => (a === 'other') - (b === 'other'));
    const stageSum = new Map(D.stages.map(s => [s.stage, s]));
    const M = D.methods || {};
    let USES = null; /* landscape_uses, loaded on first detail view */
    const lens = { layer: D.lens.layer, ev: '', st: '' };
    /* Scope (HS-02, HS-03, HS-11, HS-20): INS holds the indices of the papers in the date range; every count, matrix
       cell, graph line and quote row is recomputed over them. The server's aggregates (set-aside counts, agreement,
       the default-lens co-use list, candidates, earliest, the loaded-set note) cannot be cut and carry the label. */
    const SCOPE = window.HUB_SCOPE;
    let SRES = null, INS = new Set(), SIDS = new Set();
    const scopeOn = () => SCOPE.active(SCOPE.current());
    const WHOLE = () => scopeOn() ? ' ' + SCOPE.label('corpus') : '';
    function applyScope() {
      SRES = SCOPE.apply(W, w => w.published, SCOPE.current(), { includeUndated: SCOPE.includeUndated() });
      SIDS = new Set(SRES.inScope.map(w => w.id)); INS = new Set([...SIDS].map(id => workIdx.get(id)));
    }
    const emptyScopeHTML = () => { const f = SCOPE.format(SCOPE.current()).replace(/&/g, ', ');
      return `<p class="empty scope-empty-state" id="lsempty">No paper falls in this scope${f ? ' (' + esc(f) + ')' : ''}. <button type="button" class="btn" data-scope-reset>Reset the scope</button></p>`; };
    applyScope();
    const layerOptions = ['all', ...D.layers, ...(W.some(w => w.layer === D.layer_unset) ? [D.layer_unset] : [])];

    const infoPanel = k => H.info(M[k] || '', 'About this');
    const layerName = l => l === 'all' ? 'All layers' : H.layerLabel(l);

    /* ---------- the lens, recomputed from the rows (same filter as the service) ---------- */
    function inLens(r) {
      return INS.has(r[1]) && (lens.layer === 'all' || W[r[1]].layer === lens.layer) && (!lens.ev || EVA[r[2]] === lens.ev) && (!lens.st || STA[r[3]] === lens.st);
    }
    function compute() {
      const by = new Map(), per = new Map(), all = new Set(); let rows = 0, noEv = 0;
      for (const r of R) {
        if (!inLens(r)) continue;
        const a = CAT[r[0]];
        let x = by.get(a.id); if (!x) by.set(a.id, x = { works: new Set(), rows: 0, ev: {} });
        x.works.add(r[1]); x.rows++; x.ev[EVA[r[2]]] = (x.ev[EVA[r[2]]] || 0) + 1;
        let s = per.get(a.stage); if (!s) per.set(a.stage, s = { works: new Set(), approaches: new Set(), rows: 0, noEv: 0 });
        s.works.add(r[1]); s.approaches.add(a.id); s.rows++; if (EVA[r[2]] === 'not-stated') s.noEv++;
        all.add(r[1]); rows++; if (EVA[r[2]] === 'not-stated') noEv++;
      }
      return { by, per, all, rows, noEv };
    }
    const mixBar = ev => {
      const t = Object.values(ev).reduce((a, b) => a + b, 0);
      if (!t) return '<span class="mix" aria-hidden="true"></span>';
      return '<span class="mix" role="img" aria-label="' + esc(EVA.filter(e => ev[e]).map(e => evLabel(e) + ' ' + ev[e]).join(', ')) + '">'
        + EVA.filter(e => ev[e]).map(e => `<i class="e-${esc(e)}" style="width:${(100 * ev[e] / t).toFixed(1)}%" title="${esc(evLabel(e))}: ${ev[e]}"></i>`).join('') + '</span>';
    };
    const legend = () => '<div class="legend" aria-label="Evidence levels">' + D.evidence_levels.map(e => `<span><i class="sw e-${esc(e)}"></i>${esc(evLabel(e))}</span>`).join('') + '</div>';
    const lensText = () => layerName(lens.layer) + (lens.ev ? ', ' + evLabel(lens.ev) : ', any evidence level') + (lens.st ? ', status ' + stLabel(lens.st) : ', any status');

    /* ---------- hash: lens and open approach ---------- */
    function readHash() {
      const h = H.hash.get(), l = h.get('layer');
      lens.layer = l && layerOptions.includes(l) ? l : D.lens.layer;
      const e = h.get('ev'); lens.ev = e && D.evidence_levels.includes(e) ? e : '';
      const s = h.get('st'); lens.st = s && D.statuses.includes(s) ? s : '';
      const a = h.get('a'); return a && catById.has(a) ? a : null;
    }
    const hashParams = a => ({ layer: lens.layer === D.lens.layer ? '' : lens.layer, ev: lens.ev, st: lens.st, a: a || '' });
    /* a lens change replaces the history entry; opening or leaving an approach adds one, so Back returns */
    function writeHash(a) { H.hash.set(hashParams(a)); }
    function hashFor(a) { const p = new URLSearchParams(); for (const [k, v] of Object.entries(hashParams(a))) if (v) p.set(k, v); return SCOPE.merge(p.toString(), SCOPE.current()); }

    /* ---------- overview ---------- */
    function lensBar() {
      const sel = (id, label, opts, cur) => `<label>${esc(label)}<select id="${id}">${opts.map(([v, t]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
      return '<div class="lensbar">'
        + sel('f-layer', 'Layer', layerOptions.map(l => [l, layerName(l)]), lens.layer)
        + sel('f-ev', 'Evidence level', [['', 'Any'], ...D.evidence_levels.map(e => [e, evLabel(e)])], lens.ev)
        + sel('f-st', 'Status', [['', 'Any'], ...D.statuses.map(s => [s, stLabel(s)])], lens.st)
        + '</div>';
    }
    function notice() {
      return noticeBox(D.notice.replace(/^exploratory:\s*/i, ''), D.corpus + ' ' + cap(D.cross_stage_note) + '.');
    }
    function bindLens(redraw) {
      for (const [id, key] of [['f-layer', 'layer'], ['f-ev', 'ev'], ['f-st', 'st']]) {
        const el = document.getElementById(id); if (el) el.onchange = () => { lens[key] = el.value; writeHash(currentA); redraw(); const again = document.getElementById(id); if (again) again.focus(); };
      }
    }
    function bindPapers(root) {
      root.querySelectorAll('[data-paper]').forEach(b => b.onclick = () => H.openDrawer(b.dataset.paper));
      root.querySelectorAll('[data-a]').forEach(b => b.onclick = e => { e.preventDefault(); go(b.dataset.a); });
    }
    const aLink = (id, text) => catById.has(id) ? `<button type="button" class="lnk" data-a="${esc(id)}">${esc(text || CAT[catById.get(id)].name)}</button>` : esc(text || id);

    function agreementLine(s) {
      if (!s || s.agreement == null) return 'Second reading: none yet.';
      return `Second reading (pass B) agrees on ${(100 * s.agreement).toFixed(0)}% of the rows it checked`
        + (s.agreement_aligned != null ? `, ${(100 * s.agreement_aligned).toFixed(0)}% where both readings cover the same row` : '')
        + `; ${esc(s.agreement_note)}.`;
    }
    function stagesView(C) {
      return `<div class="stages">${stages.map(st => {
        const s = C.per.get(st), sm = stageSum.get(st) || {};
        return `<div class="scard"><h3 class="h3">${esc(stLabel(st))}</h3><dl>
          <dt>Approaches found</dt><dd>${fmt(s ? s.approaches.size : 0)}</dd>
          <dt>Papers</dt><dd>${fmt(s ? s.works.size : 0)}</dd>
          <dt>First-reading rows (pass A)</dt><dd>${fmt(s ? s.rows : 0)}</dd>
          <dt>Rows with no evidence level</dt><dd>${s && s.rows ? (100 * s.noEv / s.rows).toFixed(0) + '%' : 'none'}</dd>
          <dt>Set aside as other or not stated</dt><dd>${fmt(sm.residual_rows || 0)}${WHOLE()}</dd></dl>
          <div class="ag">${agreementLine(sm)}${WHOLE()} ${H.info(M.agreement || '', 'About agreement')}</div></div>`;
      }).join('')}</div>`;
    }
    function matrixView(C) {
      return stages.map(st => {
        const here = CAT.filter(c => c.stage === st);
        const live = here.filter(c => C.by.has(c.id)).sort((a, b) => C.by.get(b.id).works.size - C.by.get(a.id).works.size || a.name.localeCompare(b.name));
        const dead = here.filter(c => !C.by.has(c.id));
        const max = live.reduce((m, c) => Math.max(m, C.by.get(c.id).works.size), 1);
        const rows = live.map(c => { const x = C.by.get(c.id); return `<tr><td class="name">${aLink(c.id)}<div class="meta">${esc(short(c.definition, 140))}</div></td>
          <td class="r"><span class="wbar" style="width:${Math.max(2, Math.round(70 * x.works.size / max))}px"></span>${fmt(x.works.size)}</td><td class="r">${fmt(x.rows)}</td><td>${mixBar(x.ev)}</td></tr>`; }).join('');
        return `<div class="grp"><h3 class="h3">${esc(stLabel(st))} <span class="meta">${fmt(live.length)} of ${fmt(here.length)} approaches in this lens</span></h3>
          ${live.length ? `<div class="scrollx"><table class="t"><thead><tr><th>Approach</th><th class="r">Papers</th><th class="r">Uses</th><th>Evidence mix</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="empty">No paper uses an approach of this stage in this lens.</p>'}
          ${dead.length ? `<p class="zero">No paper in this lens: ${dead.map(c => aLink(c.id)).join(', ')}.</p>` : ''}</div>`;
      }).join('');
    }
    function coUsedView() {
      const edges = D.default.co_used.slice(0, 12);
      const whole = scopeOn() ? `<p class="meta lens-whole">${SCOPE.label('corpus')} This list is the server's count over the core layer and every paper of the corpus; the graph below follows the scope.</p>` : '';
      if (!edges.length) return whole + '<p class="empty">No two approaches are used together by enough papers in the core layer.</p>';
      return whole + `<div class="scrollx"><table class="t"><thead><tr><th>Approach</th><th>Used together with</th><th class="r">Papers</th></tr></thead><tbody>${edges.map(e => `<tr><td>${aLink(e.source)}</td><td>${aLink(e.target)}</td><td class="r">${fmt(e.weight)}</td></tr>`).join('')}</tbody></table></div>
        <p class="meta">${fmt(D.default.co_used.length)} pairs listed (core layer, at least ${fmt(D.default.min_co_works)} papers each)${D.default.co_used_omitted ? `; ${fmt(D.default.co_used_omitted)} more left out by the cap of ${fmt(D.default.max_edges)}` : ''}.</p>`;
    }

    /* ---------- candidates (default lens, ranked on the server) ---------- */

    /* ---------- graph view: approaches as nodes, co-use or descent as edges ---------- */
    /* Deterministic layout: one column per stage (co-used) or per year (descent), nodes in a column ordered by
       papers (ties by id), evenly spaced; edges are cubic curves. No randomness, no library. */
    const GCOL = ['--l-core', '--l-benchmark', '--l-applied', '--l-adjacent', '--h-collab', '--h-review', '--h-none', '--h-feedback', '--h-physical', '--l-background'];
    const GMAX = 120, GX = 210, GY = 24, GTOP = 46;
    let graphKind = 'co-used';
    const stCol = st => 'var(' + GCOL[Math.max(0, stages.indexOf(st)) % GCOL.length] + ')';
    const plural = (n, w) => fmt(n) + ' ' + w + (n === 1 ? '' : 's');
    function graphModel(C) {
      if (graphKind === 'co-used') {
        /* papers per approach and per pair, in the current lens (layer, evidence, status), counted from the rows */
        const byWork = new Map();
        for (const r of R) { if (!inLens(r)) continue; (byWork.get(r[1]) || byWork.set(r[1], new Set()).get(r[1])).add(CAT[r[0]].id); }
        const pair = new Map();
        for (const set of byWork.values()) { const a = [...set].sort(); for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) { const k = a[i] + '\u0000' + a[j]; pair.set(k, (pair.get(k) || 0) + 1); } }
        const all = [...pair].map(([k, w]) => { const [s, t] = k.split('\u0000'); return { s, t, w }; }).filter(e => e.w >= D.default.min_co_works)
          .sort((x, y) => y.w - x.w || (x.s + x.t < y.s + y.t ? -1 : 1));
        const edges = all.slice(0, GMAX), used = new Set(edges.flatMap(e => [e.s, e.t]));
        const nodes = [...used].map(id => { const c = CAT[catById.get(id)], x = C.by.get(id); return { id, label: c.name, col: c.stage, n: x ? x.works.size : 0, tip: c.name + ' · ' + stLabel(c.stage) + ' · ' + plural(x ? x.works.size : 0, 'paper') }; });
        return { nodes, edges: edges.map(e => ({ s: e.s, t: e.t, w: e.w, st: CAT[catById.get(e.s)].stage, tip: CAT[catById.get(e.s)].name + ' with ' + CAT[catById.get(e.t)].name + ' · ' + plural(e.w, 'paper') + ' together' })),
          omitted: all.length - edges.length, colKeys: stages.filter(st => nodes.some(n => n.col === st)), colName: stLabel, directed: false };
      }
      /* descent: a paper reports reusing an approach it cites; shown between the two papers, arrow from the cited one */
      const all = D.derives_from.filter(e => SIDS.has(e.source) && SIDS.has(e.target)).filter(e => lens.layer === 'all' || (e.source_layer === lens.layer && e.target_layer === lens.layer))
        .map(e => ({ s: e.target, t: e.source, ap: e.approach })).sort((x, y) => (x.s + x.t + x.ap < y.s + y.t + y.ap ? -1 : 1));
      const edges = all.slice(0, GMAX), used = new Set(edges.flatMap(e => [e.s, e.t]));
      const nodes = [...used].filter(id => workIdx.has(id)).map(id => { const w = W[workIdx.get(id)];
        return { id, label: w.title, col: String(w.year || 'undated'), n: 1, work: true, tip: w.title + ' · ' + (w.year || 'undated') }; });
      const ok = new Set(nodes.map(n => n.id));
      const kept = edges.filter(e => ok.has(e.s) && ok.has(e.t) && catById.has(e.ap));
      return { nodes, edges: kept.map(e => ({ s: e.s, t: e.t, w: 1, st: CAT[catById.get(e.ap)].stage, ap: e.ap,
        tip: W[workIdx.get(e.t)].title + ' reuses ' + CAT[catById.get(e.ap)].name + ' from ' + W[workIdx.get(e.s)].title })),
        omitted: all.length - kept.length, colKeys: [...new Set(nodes.map(n => n.col))].sort(), colName: x => x, directed: true };
    }
    function graphSvg(g) {
      const NS = 'http://www.w3.org/2000/svg';
      const mk = (tag, at, par) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); if (par) par.appendChild(e); return e; };
      const cols = g.colKeys, byCol = new Map(cols.map(c => [c, []]));
      for (const n of g.nodes) byCol.get(n.col).push(n);
      let rows = 1;
      for (const [, a] of byCol) { a.sort((x, y) => y.n - x.n || (x.id < y.id ? -1 : 1)); rows = Math.max(rows, a.length); }
      const Wd = 60 + cols.length * GX, Ht = GTOP + rows * GY + 16, maxN = g.nodes.reduce((m, n) => Math.max(m, n.n), 1);
      const pos = new Map();
      cols.forEach((c, ci) => byCol.get(c).forEach((n, i) => pos.set(n.id, { x: 30 + ci * GX + 8, y: GTOP + i * GY + GY / 2 })));
      const svg = mk('svg', { viewBox: `0 0 ${Wd} ${Ht}`, class: 'gr', role: 'group', 'aria-label': g.directed ? 'Candidate lines of descent between papers' : 'Approaches used together, by stage' }, null);
      const defs = mk('defs', {}, svg);
      if (g.directed) stages.forEach((st, i) => { const m = mk('marker', { id: 'gar' + i, viewBox: '0 0 8 8', refX: 8, refY: 4, markerWidth: 6, markerHeight: 6, orient: 'auto' }, defs); mk('path', { d: 'M0,0 L8,4 L0,8 z', fill: stCol(st) }, m); });
      cols.forEach((c, ci) => { const t = mk('text', { x: 30 + ci * GX, y: 20, class: 'colh' }, svg); t.textContent = short(g.colName(c), 24); });
      const maxW = g.edges.reduce((m, e) => Math.max(m, e.w), 1), eEls = [], nEls = new Map();
      for (const e of g.edges) {
        const a = pos.get(e.s), b = pos.get(e.t), same = Math.abs(a.x - b.x) < 1, bow = same ? -(40 + Math.abs(a.y - b.y) / 6) : (b.x - a.x) / 2;
        const d = same ? `M${a.x},${a.y} C${a.x + bow},${a.y} ${b.x + bow},${b.y} ${b.x},${b.y}` : `M${a.x},${a.y} C${a.x + bow},${a.y} ${b.x - bow},${b.y} ${b.x},${b.y}`;
        const at = { d, class: 'ge', stroke: stCol(e.st), 'stroke-width': (g.directed ? 1.6 : 1 + 5 * e.w / maxW).toFixed(1) };
        if (g.directed) at['marker-end'] = 'url(#gar' + Math.max(0, stages.indexOf(e.st)) + ')';
        const p = mk('path', at, svg); mk('title', {}, p).textContent = e.tip; eEls.push([p, e]);
        if (g.directed) { p.style.cursor = 'pointer'; p.setAttribute('data-go', e.ap); }
      }
      for (const n of g.nodes) {
        const q = pos.get(n.id), gg = mk('g', { class: 'gn', tabindex: 0, role: 'button', 'aria-label': n.tip, transform: `translate(${q.x},${q.y})` }, svg);
        if (!g.directed) gg.setAttribute('data-go', n.id); else if (H.byId.has(n.id)) gg.setAttribute('data-paper', n.id);
        mk(n.work ? 'rect' : 'circle', n.work ? { x: -4, y: -4, width: 8, height: 8, fill: 'var(--raised)' } : { r: (3.5 + 6 * Math.sqrt(n.n / maxN)).toFixed(1), fill: stCol(n.col) }, gg);
        const t = mk('text', { x: 13, y: 4 }, gg); t.textContent = short(n.label, 26) + (n.work ? '' : ' · ' + fmt(n.n));
        mk('title', {}, gg).textContent = n.tip; nEls.set(n.id, gg);
      }
      const hot = id => { const on = new Set([id]); svg.classList.add('hot'); for (const [p, e] of eEls) if (e.s === id || e.t === id) { p.classList.add('on'); on.add(e.s); on.add(e.t); } for (const i of on) nEls.get(i).classList.add('on'); };
      const cool = () => { svg.classList.remove('hot'); svg.querySelectorAll('.on').forEach(x => x.classList.remove('on')); };
      for (const [id, gg] of nEls) { gg.addEventListener('mouseenter', () => hot(id)); gg.addEventListener('mouseleave', cool); gg.addEventListener('focus', () => hot(id)); gg.addEventListener('blur', cool); }
      return svg;
    }
    function graphView(C) {
      const g = graphModel(C);
      const kinds = [['co-used', 'Used together'], ['descent', 'Descent']];
      const info = '<b>What it shows</b> Approaches as dots, grouped in columns by stage.<p><span class=k>How to read it.</span> '
        + 'In <i>Used together</i>, a line joins two approaches that share at least ' + fmt(D.default.min_co_works) + ' papers in the current lens; a thicker line means more shared papers, and a bigger dot means more papers use the approach. '
        + 'In <i>Descent</i>, dots are papers in columns by year, and an arrow runs from a cited paper to a paper that reports reusing the same approach from it; the colour is the approach’s stage. Click a dot (or an arrow, in Descent) to open the approach.</p>'
        + '<p><span class=k>Caution.</span> Exploratory. Shared papers show that approaches appear together, not that one builds on the other; a descent arrow is a candidate to check, not an origin claim. The layout carries no meaning beyond the columns and the order by papers.</p>';
      const note = g.directed
        ? `${esc(D.derives_lens_note)}. ${fmt(g.edges.length)} lines between ${fmt(g.nodes.length)} papers${g.omitted ? `; ${fmt(g.omitted)} more left out by the cap of ${fmt(GMAX)}` : ''}.`
        : `${fmt(g.edges.length)} pairs among ${fmt(g.nodes.length)} approaches, at least ${fmt(D.default.min_co_works)} papers each, in the current lens${g.omitted ? `; ${fmt(g.omitted)} weaker pairs left out by the cap of ${fmt(GMAX)}` : ''}.`;
      return `<section class="sec">${H.header({ title: 'Graph', level: 2, infoHtml: info, sub: 'Exploratory. Follows the lens above' })}
        <div class="gseg" role="group" aria-label="Kind of line">${kinds.map(([k, t]) => `<button type="button" data-gk="${k}" aria-pressed="${k === graphKind}">${esc(t)}</button>`).join('')}</div>
        ${g.nodes.length ? `<div class="scrollx" id="ls-graph"></div><p class="meta">${note}</p>` : `<p class="empty">${graphKind === 'co-used' ? 'No two approaches share enough papers in this lens. Widen the lens above.' : 'No candidate line of descent in this layer.'}</p>`}</section>`;
    }
    function bindGraph(C) {
      const host = document.getElementById('ls-graph');
      if (host) {
        const g = graphModel(C), svg = graphSvg(g); host.appendChild(svg);
        const open = el => { const id = el.getAttribute('data-go'), pp = el.getAttribute('data-paper'); if (id) go(id); else if (pp) H.openDrawer(pp); };
        svg.addEventListener('click', e => { const t = e.target.closest('[data-go],[data-paper]'); if (t) open(t); });
        svg.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.getAttribute && (e.target.getAttribute('data-go') || e.target.getAttribute('data-paper'))) { e.preventDefault(); open(e.target); } });
      }
      main.querySelectorAll('[data-gk]').forEach(b => b.onclick = () => { graphKind = b.dataset.gk; overview(); const again = main.querySelector(`[data-gk="${graphKind}"]`); if (again) again.focus(); });
    }
    function scoreLine(sc) {
      if (!sc) return '';
      const parts = [['composite', sc.composite], ['popularity', sc.popularity], ['stage', sc.stage], ['strength', sc.strength], ['bridge', sc.bridge], ['evidence', sc.evidence], ['generic', sc.generic]].filter(x => x[1] != null);
      let out = `<small class="meta">Score components: ${parts.map(([k, v]) => esc(k) + ' ' + nf(v)).join(' · ')}</small>`;
      if (sc.flags && sc.flags.length) out += `<small>Flags to judge by hand: ${sc.flags.map(f => `<span class="flag">${esc(f)}</span>`).join('')}</small>`;
      for (const lk of sc.lookalikes || []) out += `<small class="meta">Lookalike: ${esc(lk.of)} resembles ${esc(lk.approach_id)} (${esc(lk.name)}, stage ${esc(lk.stage)}, name overlap ${nf(lk.jaccard)}).</small>`;
      return out;
    }
    function quoteLine(q, who) {
      if (!q || !q.quote) return '';
      return `<blockquote class="quote">“${esc(q.quote)}”<div class="meta">${who ? esc(who) + ' · ' : ''}${paper(q.work_id)}${q.anchor ? ' · ' + esc(q.anchor) : ''}</div></blockquote>`;
    }
    function candidatesView() {
      const C = D.candidates;
      const gaps = C.gaps.map(l => `<details><summary>${esc(stLabel(l.from_stage))} to ${esc(stLabel(l.to_stage))}: showing ${fmt(l.shown)} of ${fmt(l.total)}, ranked within this list</summary>
        ${l.items.map(g => `<div class="cand"><p class="st"><b>#${fmt(g.rank)}</b> ${esc(g.statement)}</p>${aLink(g.approach.id)}${scoreLine(g.score)}${quoteLine(g.quote, g.approach.id)}</div>`).join('')}</details>`).join('')
        || '<p class="empty">None found in this corpus under the default lens.</p>';
      const combos = C.combinations.items.map(c => `<div class="cand"><p class="st"><b>#${fmt(c.rank)}</b> ${esc(c.statement)}</p>${aLink(c.a.id)} · ${aLink(c.b.id)}${scoreLine(c.score)}${quoteLine(c.quote_a, c.a.id)}${quoteLine(c.quote_b, c.b.id)}</div>`).join('')
        || '<p class="empty">None found in this corpus under the default lens.</p>';
      const chal = C.challenges.items.map(c => `<div class="cand"><p class="st">${esc(c.statement)}</p>${aLink(c.approach.id)}</div>`).join('')
        || '<p class="empty">None found in this corpus under the default lens.</p>';
      return `${scopeOn() ? `<p class="meta lens-whole">${SCOPE.label('corpus')} Candidates are ranked by the server over the whole corpus and do not follow the scope.</p>` : ''}<p class="meta">${esc(C.label)}. Default lens: ${esc(layerName(C.lens.layer))}, first reading; it does not follow the lens above. A score orders one list only.</p>
        <h3 class="h3" style="margin-top:14px">Used at one stage, not found at another</h3>${gaps}
        <h3 class="h3" style="margin-top:18px">Each used often, never together <span class="meta">showing ${fmt(C.combinations.shown)} of ${fmt(C.combinations.total)}, ranked</span></h3>${combos}
        <h3 class="h3" style="margin-top:18px">Reported failing in one paper, supported in another <span class="meta">showing ${fmt(C.challenges.shown)} of ${fmt(C.challenges.total)}</span></h3>${chal}`;
    }

    /* ---------- overview page ---------- */
    let currentA = null;
    function overview() {
      applyScope();
      const C = compute();
      const empty = !CAT.length, emptyScope = SRES.n === 0 && SRES.N > 0;
      main.innerHTML = H.header({ level: 1, kicker: esc(NOTICE_HEAD) + ' · ' + H.term('technique', 'techniques') + ' by stage', title: 'Landscape', infoHtml: M.page })
        + (empty ? '' : `<p class="lead">In ${lens.layer === 'all' ? 'all layers' : 'the ' + esc(layerName(lens.layer).toLowerCase()) + ' layer'}, <b>${fmt(C.all.size)}</b> papers use <b>${fmt(C.by.size)}</b> approaches across <b>${fmt(C.per.size)}</b> stages.</p>`)
        + '<div id="lscope"></div>' + (emptyScope ? emptyScopeHTML() : '')
        + notice() + (empty ? '<p class="empty">No technique readings are recorded yet. The landscape appears here once the technique miners have read papers.</p>' : lensBar()
          + `<p class="nowlens" id="nowlens">Lens now: <b>${esc(lensText())}</b>. Counts are papers with a current pass-A row. The lens drives the stage cards\u2019 approaches, papers, rows and evidence share; the set-aside count and the second-reading agreement cover every layer${scopeOn() ? ' and every paper of the corpus' : ''}.${scopeOn() ? ' Only papers in the scope are counted.' : ''}</p>
          <section class="sec">${H.header({ title: 'Stages', level: 2, infoHtml: M.agreement })}${stagesView(C)}</section>
          <section class="sec">${H.header({ title: 'Approaches by stage', level: 2, infoHtml: M.matrix })}${legend()}${matrixView(C)}</section>
          <section class="sec">${H.header({ title: 'Used together', level: 2, sub: 'Core layer, the server’s default lens' })}${coUsedView()}</section>
          ${graphView(C)}
          <section class="sec">${H.header({ title: 'Candidates to check', level: 2, infoHtml: M.candidates })}${candidatesView()}</section>`)
        + `<p class="foot">${esc(D.sets.what)}: ${fmt(D.sets.works)} papers, ${fmt(D.sets.rows)} rows${WHOLE()}; ${esc(H.SETS_NOTE)} ${H.info('The Landscape counts papers read by the technique miners. That set can differ from the included papers; the Flow page lists every difference by id.', 'About these papers')}</p>`;
      SCOPE.renderLine(document.getElementById('lscope'), SRES, { onToggle: () => render() });
      bindLens(overview); bindPapers(main); if (!empty) bindGraph(C);
    }

    /* ---------- one approach ---------- */
    function ego(a, neigh) {
      const NS = 'http://www.w3.org/2000/svg', Wd = EGO.W, Ht = EGO.H, cx = Wd / 2, cy = Ht / 2;
      const mk = (tag, at, par) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); if (par) par.appendChild(e); return e; };
      const svg = mk('svg', { viewBox: `0 0 ${Wd} ${Ht}`, class: 'ego', role: 'img', 'aria-label': 'Approaches used together with ' + a.name }, null);
      const maxW = neigh.reduce((m, x) => Math.max(m, x.weight), 1), lay = egoLayout(neigh.length);
      neigh.forEach((x, i) => mk('line', { x1: cx, y1: cy, x2: lay[i].x, y2: lay[i].y, class: 'ed', 'stroke-width': (1 + 4 * x.weight / maxW).toFixed(1) }, svg));
      neigh.forEach((x, i) => { const L = lay[i], g = mk('a', { href: '#' + SCOPE.merge('a=' + encodeURIComponent(x.id), SCOPE.current()), 'data-go': x.id, class: 'eg' }, svg);
        mk('circle', { cx: L.x, cy: L.y, r: 4, class: 'dot' }, g);
        const t = mk('text', { x: L.tx, y: L.y - 3, 'text-anchor': L.anchor }, g); t.textContent = short(x.name, EGO.chars);
        const t2 = mk('text', { x: L.tx, y: L.y + 10, 'text-anchor': L.anchor, class: 'dimt' }, g); t2.textContent = `${x.weight} paper${x.weight === 1 ? '' : 's'} together`;
        mk('title', {}, g).textContent = x.name; });
      const c = mk('g', {}, svg); mk('rect', { x: cx - 78, y: cy - 20, width: 156, height: 40, rx: 8, class: 'nd' }, c); mk('rect', { x: cx - 78, y: cy - 20, width: 156, height: 40, rx: 8, class: 'cn' }, c);
      const ct = mk('text', { x: cx, y: cy + 4, 'text-anchor': 'middle' }, c); ct.textContent = short(a.name, 22);
      return svg;
    }
    function detail(id) {
      applyScope();
      const ai = catById.get(id), a = CAT[ai];
      const mine = R.filter(r => r[0] === ai && inLens(r));
      const users = [...new Set(mine.map(r => r[1]))].sort((x, y) => W[x].id < W[y].id ? -1 : 1);
      const uset = new Set(users), ev = {}, per = new Map(), reach = new Map(), other = new Map();
      for (const r of mine) { ev[EVA[r[2]]] = (ev[EVA[r[2]]] || 0) + 1; (per.get(r[1]) || per.set(r[1], { n: 0, ev: new Set() }).get(r[1])).n++; per.get(r[1]).ev.add(EVA[r[2]]); }
      /* neighbours and stages reached: the same lens, every approach the approach's papers also use */
      for (const r of R) { if (!inLens(r) || !uset.has(r[1])) continue; const c = CAT[r[0]];
        (reach.get(c.stage) || reach.set(c.stage, new Set()).get(c.stage)).add(r[1]);
        if (r[0] !== ai) (other.get(c.id) || other.set(c.id, new Set()).get(c.id)).add(r[1]); }
      const neigh = [...other].map(([k, s]) => ({ id: k, name: CAT[catById.get(k)].name, stage: CAT[catById.get(k)].stage, weight: s.size })).sort((x, y) => y.weight - x.weight || (x.id < y.id ? -1 : 1));
      const derives = D.derives_from.filter(e => e.approach === id && SIDS.has(e.source) && SIDS.has(e.target) && (lens.layer === 'all' || (e.source_layer === lens.layer && e.target_layer === lens.layer)));
      const ek = D.earliest[lens.layer] ? lens.layer : null, early = ek ? D.earliest[ek].by_approach[id] : null;
      const title = w => paper(W[w].id, W[w].title);
      const wid = i => W[workIdx.get(i)];
      main.innerHTML = `<p class="crumbs"><a href="#" id="ls-back">Landscape</a> · ${esc(stLabel(a.stage))}</p>`
        + H.header({ level: 1, kicker: esc(NOTICE_HEAD) + ' · ' + esc(stLabel(a.stage)), title: a.name, infoHtml: M.page, sub: esc(a.definition) })
        + '<div id="lscope"></div>' + (SRES.n === 0 && SRES.N > 0 ? emptyScopeHTML() : '')
        + notice() + lensBar()
        + `<p class="nowlens">Lens now: <b>${esc(lensText())}</b>. <b>${fmt(users.length)}</b> papers, <b>${fmt(mine.length)}</b> uses. ${mixBar(ev).replace('class="mix"', 'class="mix" style="display:inline-flex;vertical-align:middle;width:160px"')}</p>${legend()}`
        + (users.length ? '' : '<p class="empty">No paper uses this approach in this lens. Widen the lens above.</p>')
        + `<div class="two"><section class="sec"><h2 class="h2">Used together with</h2><div class="scrollx" id="ls-ego"></div>
            ${neigh.length ? `<p class="meta">${neigh.slice(0, 12).map(x => aLink(x.id) + ' (' + fmt(x.weight) + ')').join(' · ')}</p>` : '<p class="empty">No other approach shares a paper with this one in this lens.</p>'}</section>
          <section class="sec"><h2 class="h2">Where its papers also work</h2>
            ${[...reach].sort((x, y) => y[1].size - x[1].size || (x[0] < y[0] ? -1 : 1)).map(([s, set]) => `<p class="meta">${esc(stLabel(s))}: <b class="num">${fmt(set.size)}</b> of ${fmt(users.length)} papers</p>`).join('') || '<p class="empty">None.</p>'}
            <h2 class="h2" style="margin-top:18px">Earliest in this corpus ${H.info(M.earliest || '', 'About earliest')}${WHOLE()}</h2>
            ${early ? `<p>${title(workIdx.get(early.work))} <span class="meta">${esc(wid(early.work).date || '')}</span></p><p class="meta">${esc(cap(early.note || 'a date rule, not a claim of origin'))}. It follows the layer, not the evidence level or status.</p>` : '<p class="empty">No dated paper to name in this layer.</p>'}
            <h2 class="h2" style="margin-top:18px">Possible lines of descent ${H.info(M.derives || '', 'About descent')}</h2>
            ${derives.length ? `<ul>${derives.map(e => `<li>${paper(e.source, (wid(e.source) || {}).title)} reuses it from ${paper(e.target, (wid(e.target) || {}).title)}</li>`).join('')}</ul><p class="meta">${esc(D.derives_lens_note)}.</p>` : '<p class="empty">No candidate line of descent in this layer.</p>'}</section></div>
        <section class="sec"><h2 class="h2">Papers</h2>${users.length ? `<div class="scrollx"><table class="t"><thead><tr><th>Paper</th><th>Layer</th><th class="r">Year</th><th class="r">Uses</th><th>Evidence levels</th></tr></thead><tbody>${users.map(i => { const p = per.get(i); return `<tr><td>${title(i)}</td><td>${esc(layerName(W[i].layer))}</td><td class="r">${esc(W[i].year || '')}</td><td class="r">${fmt(p.n)}</td><td>${esc([...p.ev].map(evLabel).join(', '))}</td></tr>`; }).join('')}</tbody></table></div>` : '<p class="empty">None.</p>'}</section>
        <section class="sec"><h2 class="h2">What the papers say ${H.info(H.GLOSSARY.quote[1], 'About evidence')}</h2><div id="ls-uses"><p class="status" role="status">Loading the quotes.</p></div></section>`;
      SCOPE.renderLine(document.getElementById('lscope'), SRES, { onToggle: () => render() });
      document.getElementById('ls-back').onclick = e => { e.preventDefault(); go(null); };
      const eg = document.getElementById('ls-ego');
      if (neigh.length) { eg.appendChild(ego(a, neigh.slice(0, 12))); eg.querySelectorAll('[data-go]').forEach(l => l.addEventListener('click', e => { e.preventDefault(); go(l.dataset.go); })); }
      bindLens(() => detail(id)); bindPapers(main);
      H.load(['landscape_uses']).then(p => { USES = p['landscape_uses']; fillUses(id); }).catch(err => { const h = document.getElementById('ls-uses'); if (h) h.innerHTML = `<p class="empty">The quotes are not ready: ${esc(String(err && err.message || err))}. Reload in a moment.</p>`; });
    }
    function fillUses(id) {
      const host = document.getElementById('ls-uses'); if (!host || currentA !== id) return;
      const box = (USES.approaches || {})[id];
      if (!box) { host.innerHTML = '<p class="empty">No rows recorded.</p>'; return; }
      const cut = box.rows_shown < box.rows_total;
      const rows = box.uses.filter(u => SIDS.has(u.work) && (lens.layer === 'all' || u.layer === lens.layer) && (!lens.ev || u.evidence === lens.ev) && (!lens.st || u.status === lens.st));
      host.innerHTML = (rows.length ? `<div class="scrollx"><table class="t"><thead><tr><th>Paper</th><th>Evidence</th><th>Status</th><th>Quote and where it is</th></tr></thead><tbody>${rows.map(u => `<tr><td>${paper(u.work, (workIdx.has(u.work) ? W[workIdx.get(u.work)].title : u.work))}</td><td>${esc(evLabel(u.evidence))}</td><td>${esc(stLabel(u.status))}</td>
          <td class="q">${u.quote ? `<blockquote class="quote">“${esc(u.quote)}”</blockquote>` : '<span class="meta">No quote recorded.</span>'}<div class="meta">${u.anchor ? esc(u.anchor) + ' · ' : ''}${esc(u.extraction)}${u.described_as ? ' · described as: ' + esc(u.described_as) : ''}</div></td></tr>`).join('')}</tbody></table></div>` : '<p class="empty">' + (cut
            ? `The matching rows are beyond the ${fmt(box.rows_shown)} loaded (${fmt(box.rows_total)} rows in total, every layer). The papers table above is complete for this lens; widen the lens to see loaded quotes.`
            : 'No row in this lens.') + '</p>')
        + `<p class="meta">Showing ${fmt(rows.length)} rows in this lens among the ${fmt(box.rows_shown)} loaded of ${fmt(box.rows_total)} rows of this approach in every layer${scopeOn() ? ' and every date' : ''}${cut ? `; the load is cut at ${fmt(USES.max_uses)} rows and keeps a share of every layer` : ''}.</p>`;
      bindPapers(host);
    }

    /* ---------- routing and the palette ---------- */
    function render() { currentA = readHash(); if (currentA) detail(currentA); else overview(); }
    function go(a) { const h = hashFor(a); window.scrollTo(0, 0); if (location.hash.slice(1) === h) render(); else location.hash = h; }
    window.addEventListener('hashchange', render);
    document.addEventListener('click', e => { if (e.target.closest('[data-scope-reset]')) SCOPE.reset(); });
    SCOPE.onChange(() => render());
    H.paletteExtra = q => { const k = q.trim().toLowerCase();
      return CAT.filter(c => (c.name + ' ' + c.id).toLowerCase().includes(k)).map(c => ({ label: c.name, group: 'Approach · ' + stLabel(c.stage), go: () => { H.closePalette(); go(c.id); } })); };
    render();
  }
});
