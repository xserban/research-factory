/* Lenses page: nine ways to look at the same papers. Every count, expected value, residual, chain link,
   share, association and adoption cell is read from the `lenses` payload; the shell supplies the per-paper rows
   behind each mark (for the lists), titles and citation links. */
HUB.load(['shell', 'lenses']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'lenses', crumb: 'Lenses' });
  const LZ = d.lenses, esc = H.esc, fmt = H.fmt, T = H.term, cv = H.cssv;
  const EW = H.RF.works, EBY = H.byId, SHELL = H.byId;

  /* ---------- page style (kit tokens only) ---------- */
  if (!document.getElementById('lenses-css')) {
    const s = document.createElement('style'); s.id = 'lenses-css';
    s.textContent = `
.lens-sw{display:grid;grid-template-columns:repeat(9,minmax(0,1fr));gap:8px;margin:16px 0 18px}
.lcard{background:var(--surface);border-radius:var(--r);padding:10px;color:var(--fg);text-decoration:none;display:flex;flex-direction:column;gap:6px}
.lcard:hover{background:var(--raised)}
.lcard[aria-current=true]{box-shadow:inset 0 0 0 2px var(--acc);background:var(--raised)}
.lcard svg{width:100%;height:30px;color:var(--mut);fill:currentColor}
.lcard .nm{font-weight:600;font-size:12.5px;line-height:1.25}
.lens{padding:24px}
.lens .sec-head{margin:0}
.lens .lead{max-width:64ch;font-size:24px;margin-top:12px}
.lens .ctl{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0 8px}
.lens .two{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:28px;align-items:start}
.lens .scrollx,.lens #chart{overflow-x:auto;overflow-y:hidden}
.lens svg text{user-select:none}
.lens svg{display:block}
.halo{paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.lens button.lnk{background:none;border:0;color:var(--acc);font:inherit;text-decoration:underline;text-underline-offset:3px;cursor:pointer;padding:0}
.sidelist{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:2px}
.sidelist button{all:unset;display:block;cursor:pointer;padding:7px 8px;border-radius:6px;font-size:13px;line-height:1.35;width:calc(100% - 16px)}
.sidelist button:hover{background:var(--raised)}
.sidelist button:focus-visible{outline:2px solid var(--acc)}
.sidelist .e{color:var(--mut);display:block;font-size:12px}
.sidelist .bar{display:block;height:4px;border-radius:2px;background:var(--acc);margin-top:5px}
.listpanel{margin-top:16px;padding:20px 24px}
.listpanel .hd{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.listpanel td .meta2{display:none;font-size:12px;color:var(--mut)}
.t td .ttl{color:var(--fg)}
.t .lay{white-space:nowrap}
.empty{color:var(--mut);padding:14px 0;font-size:var(--t-s)}
.wall{column-width:300px;column-gap:14px;margin-top:14px}
.wcard{break-inside:avoid;background:var(--raised);border-radius:var(--r);padding:14px 16px;margin:0 0 14px;cursor:pointer;display:block}
.wcard:hover{background:var(--line)}
.wcard .quote{margin:0 0 10px;font-size:15px}
.wcard .meta{font-size:12px;line-height:1.4}
.wcard .meta b{color:var(--fg);font-weight:500}
mark{background:var(--acc-soft);color:var(--fg);box-shadow:inset 0 -2px 0 var(--acc);border-radius:2px}
.vchips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.wallsum{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--mut)}
.legend span{display:inline-flex;gap:6px;align-items:center}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block;flex:none}
.pt{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
@media (max-width:1100px){.lens-sw{grid-template-columns:repeat(5,minmax(0,1fr))}.lens .two{grid-template-columns:minmax(0,1fr)}}
@media (max-width:760px){
  .lens-sw{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.lcard{padding:8px}.lcard svg{height:22px}.lcard .nm{font-size:11.5px}
  .lens{padding:16px}.lens .lead{font-size:20px}
  .t .c-h,.t .c-m{display:none}.listpanel td .meta2{display:block}.listpanel{padding:16px}
}`;
    document.head.appendChild(s);
  }

  /* ---------- vocabulary ---------- */
  Object.assign(H.GLOSSARY, {
    expected: ['Expected count', 'How many papers a cell would hold if the two fields were unrelated: row total times column total, divided by the number of papers.'],
    residual: ['Residual', 'How far a cell is from its expected count, in standard steps: (found - expected) divided by the square root of expected. Beyond +2 or -2 is clearly more or less than chance.'],
    hop: ['Hop', 'One citation step. At hop 1 a paper cites, or is cited by, the focus paper directly; hop 2 is one step further out.'],
    coded: ['Coded', 'A paper whose value for this field a miner has recorded, with the sentence it was based on.'],
    chain: ['Design chain', 'One paper’s path through the four fields: technique, architecture, automated span and human role.'],
    gini: ['Gini coefficient', 'A measure of concentration: 0 when every paper is cited equally, close to 1 when a few papers receive nearly all citations.'],
    cramer: ['Cramér’s V', 'Strength of association between two coded fields, from 0 (unrelated) to 1 (one fixes the other). Corrected for small samples.'],
  });
  const FLD = { technique: 'Technique', architecture: 'Architecture', span: 'Automated span', human: 'Human role', layer: 'Layer' };
  const FNAME = { technique: T('technique', 'technique'), architecture: T('architecture', 'architecture'), span: T('span', 'automated span'), human: T('human', 'human role'), layer: T('layer', 'layer') };
  const NC = 'Not coded', REST = 'Rest';
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const monthName = w => (w.month ? MON[w.month - 1] + ' ' : '') + (w.year ?? '');
  const mkey = w => (w.year ?? 0) * 100 + (w.month ?? 0);
  const lab = (dim, v) => v == null || v === NC || v === '_' ? NC : v === '~rest' ? REST : dim === 'human' ? H.humanLabel(v) : dim === 'layer' ? H.layerLabel(v) : H.pretty(v);
  const lc = s => s.charAt(0).toLowerCase() + s.slice(1);
  const short = (s, n) => s.length > n ? s.slice(0, n - 1).trim() + '…' : s;
  const pc = (a, b) => b ? Math.round(100 * a / b) : 0;
  const shareTxt = x => Math.round(x * 100) + '%';
  const raw = (w, f) => f === 'layer' ? w.layer : f === 'year' ? String(w.year) : f === 'half' ? (w.year == null || w.month == null ? null : w.year + 'H' + (w.month <= 6 ? 1 : 2)) : (w[f] ? w[f].v : null);
  const quote = (w, f) => (w[f] && w[f].q) || '';
  const byCic = (a, b) => b.cited_here - a.cited_here || a.title.localeCompare(b.title);
  const isLight = () => document.documentElement.dataset.theme === 'light';
  const mixc = (a, b, p) => `color-mix(in srgb, ${a} ${Math.round(p)}%, ${b})`;
  const INK = p => p > 50 ? 'var(--bg)' : 'var(--fg)';
  const spec1 = (f, name) => f + ':' + (name === NC ? '_' : name);

  /* kept values per chain column (everything else is "Rest") */
  const keptOf = {}; LZ.chains.dims.forEach((f, i) => { keptOf[f] = new Set(LZ.chains.columns[i].map(c => c[0]).filter(n => n !== REST)); });
  const catName = (w, f) => { const v = raw(w, f); return v == null ? NC : v; };
  function matchCond(w, f, v) {
    const x = raw(w, f);
    if (v === '_') return x == null;
    if (v === '~rest') return !keptOf[f] || !keptOf[f].has(x == null ? NC : x);
    return x === v;
  }
  const cites = H.RF.cites || [];
  const cOut = H.citesOut, cIn = H.citesIn;
  function lineage(id, hops) {
    const seen = new Set([id]), left = [[]], right = [[]];
    const bfs = (map, out) => { let fr = [id]; for (let h = 1; h <= hops; h++) { const nx = []; for (const x of fr) for (const y of (map.get(x) || [])) if (!seen.has(y) && EBY.has(y)) { seen.add(y); nx.push(y); } out.push(nx.map(i => EBY.get(i))); fr = nx; } };
    bfs(cOut, left); bfs(cIn, right); return { left, right, seen };
  }
  function resolve(spec) {
    if (!spec) return null;
    let ws = EW; const parts = [], conds = [];
    for (const part of spec.split('|')) {
      const i = part.indexOf(':'), f = part.slice(0, i), v = part.slice(i + 1);
      if (f === 'top') { ws = [...ws].sort(byCic).slice(0, +v); parts.push('Top ' + v + ' most cited'); }
      else if (f === 'cin' || f === 'cout') { const w0 = EBY.get(v); ws = ws.filter(w => ((f === 'cin' ? cIn : cOut).get(v) || []).includes(w.id)); parts.push((f === 'cin' ? 'Built on by: ' : 'Builds on: ') + short(w0 ? w0.title : v, 48)); }
      else if (f === 'ctx') { const [id, h] = v.split('/'); const L = lineage(id, +h || 2); const ids = new Set([...L.left.flat(), ...L.right.flat()].map(w => w.id)); ws = ws.filter(w => ids.has(w.id)); parts.push('Lineage of ' + short((EBY.get(id) || {}).title || id, 40)); }
      else if (f === 'cell') { const [t, per] = v.split('/'); const c = LZ.adoption.cells.find(x => x.technique === t && x.period === per); const ids = new Set(c ? c.ids : []); ws = ws.filter(w => ids.has(w.id)); parts.push((LZ.adoption.labels[t] || t) + ', ' + per.replace('H', ' H')); }
      else if (f === 'period') { ws = ws.filter(w => raw(w, v.length === 4 ? 'year' : 'half') === v); parts.push('Published ' + v.replace('H', ' H')); }
      else { ws = ws.filter(w => matchCond(w, f, v)); parts.push((FLD[f] || f) + ': ' + lab(f, v)); conds.push([f, v]); }
    }
    return { spec, ws: [...ws].sort(byCic), parts, conds };
  }

  /* ---------- svg helpers ---------- */
  const NS = 'http://www.w3.org/2000/svg';
  function mk(tag, a = {}, par) { const e = document.createElementNS(NS, tag); for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]); if (par) par.appendChild(e); return e; }
  function tx(par, x, y, t, cls, a = {}) { if (a.fill) { a = { ...a, style: 'fill:' + a.fill + ';' + (a.style || '') }; delete a.fill; } const e = mk('text', { x, y, class: cls, ...a }, par); e.textContent = t; return e; }
  function svgIn(host, w, h) { const s = mk('svg', { width: w, height: h, viewBox: `0 0 ${w} ${h}`, role: 'group' }); host.appendChild(s); return s; }
  function act(el, o) {
    el.style.cursor = 'pointer'; if (o.label) el.setAttribute('aria-label', o.label);
    if (o.kb) { el.setAttribute('tabindex', '0'); el.setAttribute('role', 'button'); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); o.click(e); } }); }
    if (o.click) el.addEventListener('click', o.click);
    if (o.tip) {
      el.addEventListener('mousemove', e => H.tipHtml(o.tip, e)); el.addEventListener('mouseleave', () => H.tipHtml(null));
      if (o.kb) { el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); H.tipHtml(o.tip, { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }); }); el.addEventListener('blur', () => H.tipHtml(null)); }
    }
    if (o.over) { el.addEventListener('mouseenter', o.over); el.addEventListener('mouseleave', o.out); }
    return el;
  }
  let userAct = false;
  const go = o => { userAct = true; H.hash.set(o); render(); };
  const pick = spec => go({ sel: spec });
  const wrap = (t, n) => { const out = []; let cur = ''; for (const w of t.split(' ')) { if ((cur + ' ' + w).trim().length > n && cur) { out.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); } if (cur) out.push(cur); return out; };
  const emptyView = msg => `<p class="empty">${msg}</p>`;

  /* ---------- lenses ---------- */
  const GL = {
    matrix: '<svg viewBox="0 0 56 34"><rect x="2" y="2" width="12" height="12" opacity=".95"/><rect x="19" y="4" width="8" height="8" opacity=".7"/><rect x="33" y="6" width="4" height="4" opacity=".6"/><rect x="42" y="2" width="12" height="12" fill="none" stroke="currentColor" stroke-dasharray="2 2"/><rect x="4" y="20" width="8" height="8" opacity=".7"/><rect x="18" y="18" width="10" height="10" opacity=".9"/><rect x="32" y="20" width="6" height="6" opacity=".6"/><rect x="42" y="20" width="12" height="12" fill="none" stroke="currentColor" stroke-dasharray="2 2"/></svg>',
    chains: '<svg viewBox="0 0 56 34"><g opacity=".35"><path d="M5 4C20 4 20 8 29 8S40 4 51 4V12C40 12 40 18 29 18S20 12 5 12Z"/><path d="M5 18C20 18 20 24 29 24S40 22 51 22V30C40 30 40 30 29 30S20 30 5 30Z"/></g><rect x="3" y="3" width="3" height="10"/><rect x="3" y="17" width="3" height="14"/><rect x="27.5" y="7" width="3" height="12"/><rect x="27.5" y="23" width="3" height="8"/><rect x="50" y="3" width="3" height="10"/><rect x="50" y="21" width="3" height="10"/></svg>',
    constellation: '<svg viewBox="0 0 56 34"><g stroke="currentColor" opacity=".4" fill="none"><path d="M10 8L28 17M8 24L28 17M46 9L28 17M48 26L28 17M5 15L10 8"/></g><circle cx="28" cy="17" r="6"/><circle cx="10" cy="8" r="3"/><circle cx="8" cy="24" r="2.5"/><circle cx="46" cy="9" r="3.5"/><circle cx="48" cy="26" r="2"/><circle cx="5" cy="15" r="1.5" opacity=".5"/></svg>',
    time: '<svg viewBox="0 0 56 34"><rect x="4" y="4" width="10" height="28" opacity=".35"/><rect x="4" y="16" width="10" height="16" opacity=".7"/><rect x="23" y="2" width="10" height="30" opacity=".35"/><rect x="23" y="12" width="10" height="20" opacity=".7"/><rect x="42" y="6" width="10" height="26" opacity=".35"/><rect x="42" y="10" width="10" height="22" opacity=".7"/></svg>',
    icicle: '<svg viewBox="0 0 56 34"><rect x="2" y="2" width="52" height="9"/><rect x="2" y="13" width="30" height="9" opacity=".7"/><rect x="34" y="13" width="20" height="9" opacity=".7"/><rect x="2" y="24" width="14" height="8" opacity=".45"/><rect x="18" y="24" width="14" height="8" opacity=".45"/><rect x="34" y="24" width="20" height="8" opacity=".45"/></svg>',
    wall: '<svg viewBox="0 0 56 34"><rect x="2" y="2" width="16" height="14" rx="2" opacity=".6"/><rect x="2" y="19" width="16" height="13" rx="2" opacity=".35"/><rect x="21" y="2" width="16" height="20" rx="2" opacity=".35"/><rect x="21" y="25" width="16" height="7" rx="2" opacity=".6"/><rect x="40" y="2" width="14" height="10" rx="2" opacity=".6"/><rect x="40" y="15" width="14" height="17" rx="2" opacity=".35"/></svg>',
    swarm: '<svg viewBox="0 0 56 34"><g><circle cx="6" cy="9" r="2"/><circle cx="6" cy="14" r="2"/><circle cx="6" cy="4" r="2"/><circle cx="12" cy="9" r="2"/><circle cx="12" cy="13" r="2"/><circle cx="19" cy="9" r="2"/><circle cx="29" cy="8" r="2"/><circle cx="46" cy="9" r="2.4"/><circle cx="6" cy="24" r="2"/><circle cx="6" cy="29" r="2"/><circle cx="12" cy="26" r="2"/><circle cx="22" cy="26" r="2"/><circle cx="36" cy="25" r="2"/></g></svg>',
    assoc: '<svg viewBox="0 0 56 34"><g>' + [0, 1, 2, 3].flatMap(r => [0, 1, 2, 3].map(c => `<rect x="${6 + c * 11}" y="${1 + r * 8}" width="9" height="7" opacity="${r === c ? .12 : (.25 + ((r * 3 + c * 5) % 7) / 10).toFixed(2)}"/>`)).join('') + '</g></svg>',
    results: '<svg viewBox="0 0 56 34"><g>' + [0, 1, 2].flatMap(r => [0, 1, 2, 3].map(c => `<rect x="${5 + c * 12}" y="${2 + r * 10.4}" width="10" height="9" opacity="${(.2 + ((r * 5 + c * 3) % 6) / 8).toFixed(2)}"/>`)).join('') + '</g></svg>',
    rate: '<svg viewBox="0 0 56 34"><rect x="4" y="6" width="44" height="5" opacity=".8"/><rect x="4" y="15" width="30" height="5" opacity=".6"/><rect x="4" y="24" width="16" height="5" opacity=".4"/></svg>',
    adopt: '<svg viewBox="0 0 56 34"><g>' + [0, 1, 2].flatMap(r => [0, 1, 2, 3, 4].map(c => `<rect x="${3 + c * 10.4}" y="${2 + r * 10.4}" width="9" height="9" opacity="${c < r ? .1 : (.3 + c * .12).toFixed(2)}"/>`)).join('') + '</g></svg>',
  };
  const LENSES = [
    ['matrix', 'Design space'], ['assoc', 'What goes together'], ['chains', 'How systems are built'], ['constellation', 'Lineage'],
    ['time', 'Trends'], ['adopt', 'Technique adoption'], ['icicle', 'Taxonomy'], ['wall', 'Evidence'], ['swarm', 'Influence'],
    ['results', 'Results by stage'], ['rate', 'Citation rate'],
  ];
  const build = {};
  const methodsText = k => esc((LZ.methods && LZ.methods[k]) || '');
  const infoPanel = (what, read, comp) => `<b>What it shows</b> ${what}<p><span class=k>How to read it.</span> ${read}</p><p><span class=k>How it’s computed.</span> ${comp}</p>`;

  /* ================= 1. design space ================= */
  /* matrix model: every ordered pair of fields is computed server-side (`matrices`, keyed "row|col") */
  function matrixFor(rf, cf) {
    const M = LZ.matrices[rf + '|' + cf] || LZ.matrix;
    return { ...M, rowDim: M.row_dim, colDim: M.col_dim };
  }
  build.matrix = p => {
    const dims = Object.keys(FLD).filter(d => LZ.matrices[d + '|' + LZ.matrix.row_dim] || d === LZ.matrix.row_dim);
    const rf = dims.includes(p.get('rows')) ? p.get('rows') : LZ.matrix.row_dim;
    let cf = dims.includes(p.get('cols')) ? p.get('cols') : LZ.matrix.col_dim; if (cf === rf) cf = dims.find(x => x !== rf);
    const M = matrixFor(rf, cf);
    /* order rows and columns: biggest first, Not coded last; human role in its own order */
    const perm = (names, tot, f) => names.map((_, i) => i).sort((a, b) => (names[a] === NC) - (names[b] === NC) || (f === 'human' ? H.HUMAN.findIndex(h => h[0] === names[a]) - H.HUMAN.findIndex(h => h[0] === names[b]) : tot[b] - tot[a]) || names[a].localeCompare(names[b]));
    const ri = perm(M.rows, M.row_totals, rf), ci = perm(M.cols, M.col_totals, cf);
    const rows = ri.map(i => M.rows[i]), cols = ci.map(i => M.cols[i]);
    const at = a => ri.map(i => ci.map(j => a[i][j]));
    const obs = at(M.observed), exp = at(M.expected), res = at(M.residuals), rt = ri.map(i => M.row_totals[i]), ct = ci.map(j => M.col_totals[j]);
    const nr = rows.filter(r => r !== NC), nc = cols.filter(c => c !== NC);
    let best = null, zero = 0; const gaps = [];
    rows.forEach((r, i) => cols.forEach((c, j) => { if (r === NC || c === NC) return; if (!best || obs[i][j] > best.n) best = { r, c, n: obs[i][j] }; if (!obs[i][j]) { zero++; gaps.push({ r, c, e: exp[i][j] }); } }));
    gaps.sort((a, b) => b.e - a.e);
    const coded = M.n - (M.row_not_coded ?? 0) - (M.col_not_coded ?? 0);
    const gapInfo = infoPanel('The empty cells that would hold the most papers if the two fields were unrelated.', 'Each line gives the expected count and what was found. A large expected count with nothing found is a real hole in the field. Click one to confirm it is empty.', 'Expected count = row total × column total ÷ papers in the table.');
    const side = `<h3 class="h3">Largest gaps ${H.info(gapInfo, 'About largest gaps')}</h3>
      <ul class="sidelist">${gaps.slice(0, 6).map(g => `<li><button data-sel="${esc(spec1(rf, g.r) + '|' + spec1(cf, g.c))}">${esc(lab(rf, g.r))} × ${esc(lc(lab(cf, g.c)))}<span class="e">${T('expected', 'expected')} ${g.e.toFixed(1)}, found 0</span></button></li>`).join('') || '<li class="empty">No empty combinations.</li>'}</ul>`;
    const opt = (sel, name, excl) => `<select data-dim="${name}" aria-label="${name === 'rows' ? 'Rows' : 'Columns'}">${dims.filter(d => d !== excl).map(d => `<option value="${d}" ${d === sel ? 'selected' : ''}>${FLD[d]}</option>`).join('')}</select>`;
    return {
      title: 'Design space',
      info: infoPanel(`Which combinations of ${FNAME[rf]} and ${FNAME[cf]} exist in the corpus, and which are gaps.`,
        'Each cell holds the number of papers with that pair of values. Colour is the ' + T('residual', 'residual') + ': warm accent where a pair is more common than chance, red where it is less common, plain where it is about as expected. A dashed outline marks a combination no paper has. Click a cell, row or column to list its papers.',
        `${methodsText('design_matrix')} ${fmt(M.n)} papers; ${fmt(coded)} ${T('coded', 'coded')} on both fields.`),
      lead: best ? `<b>${esc(lab(rf, best.r))}</b> with <b>${esc(lc(lab(cf, best.c)))}</b> is the biggest group: <b>${fmt(best.n)}</b> papers. Of ${fmt(nr.length * nc.length)} combinations, <b>${fmt(zero)}</b> have no paper at all.` : '',
      controls: `<span class="meta">Rows</span>${opt(rf, 'rows', null)}<span class="meta">Columns</span>${opt(cf, 'cols', rf)}`,
      side,
      draw(host, W, sel) {
        const avail = host.clientWidth || W, narrow = avail < 520;
        const labelW = narrow ? 112 : 190, barW = narrow ? 0 : 90, nCol = cols.length;
        const cs = Math.max(30, Math.min(62, Math.floor((avail - labelW - barW - (barW ? 50 : 8)) / nCol)));
        const hdr = 118, x0 = labelW, y0 = hdr;
        const Wd = x0 + nCol * cs + (barW ? barW + 50 : 8), bw = 34, Hd = y0 + rows.length * cs + 14 + bw + 20;
        const wr = document.createElement('div'); wr.className = 'scrollx'; host.appendChild(wr);
        const svg = svgIn(wr, Wd, Hd);
        const maxRT = Math.max(...rt, 1), maxCT = Math.max(...ct, 1);
        const selc = sel ? sel.conds : [];
        const isSel = (r, c) => selc.some(([f, v]) => f === rf && lab(rf, v) === lab(rf, r)) && selc.some(([f, v]) => f === cf && lab(cf, v) === lab(cf, c));
        tx(svg, x0, 12, FLD[cf] + (cf === 'human' ? ', least to most involved →' : ''), 'axis');
        cols.forEach((c, j) => {
          const cx = x0 + j * cs + cs / 2, g = mk('g', {}, svg);
          tx(g, cx + 4, hdr - 8, short(lab(cf, c), 22), 'lbl-m', { transform: `rotate(-50 ${cx + 4} ${hdr - 8})` });
          const hit = mk('rect', { x: x0 + j * cs, y: 14, width: cs, height: hdr - 14, fill: 'transparent' }, g);
          act(hit, { click: () => pick(spec1(cf, c)), kb: true, label: `${lab(cf, c)}: ${ct[j]} papers`, tip: `<b>${esc(lab(cf, c))}</b><br>${ct[j]} papers` });
        });
        rows.forEach((r, i) => {
          const cy = y0 + i * cs + cs / 2, g = mk('g', {}, svg);
          tx(g, x0 - 10, cy + 4, short(lab(rf, r), narrow ? 15 : 30), r === NC ? 'lbl-m' : 'lbl', { 'text-anchor': 'end' });
          const hit = mk('rect', { x: 0, y: y0 + i * cs, width: x0, height: cs, fill: 'transparent' }, g);
          act(hit, { click: () => pick(spec1(rf, r)), kb: true, label: `${lab(rf, r)}: ${rt[i]} papers`, tip: `<b>${esc(lab(rf, r))}</b><br>${rt[i]} papers` });
          cols.forEach((c, j) => {
            const n = obs[i][j], e = exp[i][j], z = res[i][j], nul = r === NC || c === NC, cx = x0 + j * cs + cs / 2;
            const t = Math.min(1, Math.abs(z) / 4), pcnt = 12 + t * 78;
            const fill = nul ? 'var(--raised)' : mixc(z >= 0 ? 'var(--acc)' : 'var(--exc)', 'var(--raised)', pcnt);
            const cell = mk('g', {}, svg);
            mk('rect', { x: cx - cs / 2 + 1.5, y: cy - cs / 2 + 1.5, width: cs - 3, height: cs - 3, rx: 3, style: 'fill:' + fill, opacity: nul ? .55 : 1 }, cell);
            if (!n) mk('rect', { x: cx - cs / 2 + 3.5, y: cy - cs / 2 + 3.5, width: cs - 7, height: cs - 7, rx: 2, fill: 'none', stroke: nul ? cv('--hair') : cv('--dim'), 'stroke-dasharray': '3 3' }, cell);
            tx(cell, cx, cy + 4, n, 'lbl', { 'text-anchor': 'middle', fill: nul ? 'var(--mut)' : INK(pcnt), style: n ? 'font-weight:600' : 'font-weight:400;opacity:.8' });
            if (isSel(r, c)) mk('rect', { x: cx - cs / 2 + 1, y: cy - cs / 2 + 1, width: cs - 2, height: cs - 2, fill: 'none', stroke: cv('--fg'), 'stroke-width': 2, rx: 4 }, cell);
            const hit = mk('rect', { x: cx - cs / 2, y: cy - cs / 2, width: cs, height: cs, fill: 'transparent' }, cell);
            const tipH = `<b>${esc(lab(rf, r))}</b> × <b>${esc(lab(cf, c))}</b><br>${n ? `${n} paper${n > 1 ? 's' : ''} (${pc(n, rt[i])}% of this row, ${pc(n, ct[j])}% of this column)` : 'No papers: a gap'}<br><span class="meta">Expected ${e.toFixed(1)} · residual ${z >= 0 ? '+' : ''}${z.toFixed(1)}</span>`;
            act(hit, { click: () => pick(spec1(rf, r) + '|' + spec1(cf, c)), kb: true, label: `${lab(rf, r)} and ${lab(cf, c)}: ${n} papers, expected ${e.toFixed(1)}`, tip: tipH });
          });
          if (barW) { const L = Math.max(2, rt[i] / maxRT * barW); mk('rect', { x: x0 + nCol * cs + 12, y: cy - 5, width: L, height: 10, fill: cv('--dim'), rx: 1.5 }, svg); tx(svg, x0 + nCol * cs + 12 + L + 5, cy + 4, rt[i], 'lbl-m'); }
        });
        const by = y0 + rows.length * cs + 12;
        mk('line', { x1: x0, x2: x0 + nCol * cs, y1: by - 2, y2: by - 2, class: 'gridline' }, svg);
        cols.forEach((c, j) => { const cx = x0 + j * cs + cs / 2, h = Math.max(2, ct[j] / maxCT * bw); mk('rect', { x: cx - 7, y: by, width: 14, height: h, fill: cv('--dim'), rx: 1.5 }, svg); tx(svg, cx, by + h + 12, ct[j], 'lbl-m', { 'text-anchor': 'middle' }); });
        tx(svg, x0 - 10, by + 10, 'Column totals', 'axis', { 'text-anchor': 'end' });
        if (barW) tx(svg, x0 + nCol * cs + 12, y0 - 8, 'Row totals', 'axis');
        host.insertAdjacentHTML('beforeend', `<div class="legend"><span><span class="sw" style="background:${mixc('var(--acc)', 'var(--raised)', 70)}"></span>More papers than chance</span><span><span class="sw" style="background:${mixc('var(--exc)', 'var(--raised)', 70)}"></span>Fewer than chance</span><span><svg width="14" height="14"><rect x="1.5" y="1.5" width="11" height="11" fill="none" stroke="${cv('--dim')}" stroke-dasharray="3 3"/></svg>No papers</span><span><span class="sw" style="background:var(--raised)"></span>Not coded</span></div>`);
      },
    };
  };

  /* ================= 2. what goes together ================= */
  build.assoc = p => {
    const A = LZ.association.filter(x => x.v != null);
    const fields = [...new Set(LZ.association.flatMap(x => [x.a, x.b]))];
    const vOfPair = new Map(); for (const x of LZ.association) { vOfPair.set(x.a + '|' + x.b, x); vOfPair.set(x.b + '|' + x.a, x); }
    const strength = f => A.filter(x => x.a === f || x.b === f).reduce((s, x) => s + x.v, 0) / Math.max(1, fields.length - 1);
    const order = [...fields].sort((a, b) => strength(b) - strength(a) || a.localeCompare(b));
    const top = A[0], low = A[A.length - 1];
    return {
      title: 'What goes together',
      info: infoPanel('Which coded fields move together: knowing one tells you something about the other.',
        'Each cell is the strength (' + T('cramer', 'Cramér’s V') + ') of one pair of fields, from 0 (unrelated) to 1 (one fixes the other). Darker is stronger. Fields run from the most to the least tied to the others; the list lists pairs from strongest down, with the number of papers coded on both. Click a cell or a pair to see it as a design-space table.',
        methodsText('association')),
      lead: top ? `<b>${esc(FLD[top.a] || top.a)}</b> and <b>${esc(lc(FLD[top.b] || top.b))}</b> go together most: V is <b>${top.v.toFixed(2)}</b> across ${fmt(top.n)} papers.${low && low !== top ? ` The weakest pair is ${esc(lc(FLD[low.a] || low.a))} and ${esc(lc(FLD[low.b] || low.b))}, at ${low.v.toFixed(2)}.` : ''}` : '',
      controls: '',
      side: `<h3 class="h3">Pairs by strength</h3><ul class="sidelist">${A.map(x => `<li><button data-go="matrix" data-rows="${x.a}" data-cols="${x.b}">${esc(FLD[x.a] || x.a)} × ${esc(lc(FLD[x.b] || x.b))}<span class="e">V ${x.v.toFixed(2)} · ${fmt(x.n)} papers</span><span class="bar" style="width:${Math.max(3, x.v * 100)}%"></span></button></li>`).join('')}</ul>`,
      draw(host, W) {
        const avail = host.clientWidth || W, narrow = avail < 520, n = order.length;
        const lw = narrow ? 100 : 130, cs = Math.max(44, Math.min(86, Math.floor((avail - lw - 4) / n))), hdr = 28;
        const svg = svgIn(host, lw + n * cs + 4, hdr + n * cs + 6);
        order.forEach((f, j) => tx(svg, lw + j * cs + cs / 2, hdr - 10, narrow ? short(FLD[f] || f, 8) : (FLD[f] || f), 'lbl-m', { 'text-anchor': 'middle' }));
        order.forEach((a, i) => {
          tx(svg, lw - 10, hdr + i * cs + cs / 2 + 4, FLD[a] || a, 'lbl', { 'text-anchor': 'end' });
          order.forEach((b, j) => {
            const x = lw + j * cs, y = hdr + i * cs, g = mk('g', {}, svg);
            if (a === b) { mk('rect', { x: x + 1.5, y: y + 1.5, width: cs - 3, height: cs - 3, rx: 3, fill: 'none', stroke: cv('--hair'), 'stroke-dasharray': '2 3' }, g); return; }
            const e = vOfPair.get(a + '|' + b);
            const v = e && e.v != null ? e.v : null, pcnt = v == null ? 0 : 6 + Math.min(1, v / .5) * 84;
            mk('rect', { x: x + 1.5, y: y + 1.5, width: cs - 3, height: cs - 3, rx: 3, style: 'fill:' + (v == null ? 'var(--raised)' : mixc('var(--seq-4)', 'var(--seq-0)', pcnt)) }, g);
            tx(g, x + cs / 2, y + cs / 2 + 4, v == null ? '–' : v.toFixed(2), 'lbl', { 'text-anchor': 'middle', fill: INK(pcnt), style: 'font-weight:600' });
            act(g, { click: () => go({ lens: 'matrix', rows: a, cols: b, sel: null }), kb: true, label: `${FLD[a]} and ${FLD[b]}: V ${v == null ? 'undefined' : v.toFixed(2)}, ${e ? e.n : 0} papers`, tip: `<b>${esc(FLD[a])}</b> × <b>${esc(FLD[b])}</b><br>V ${v == null ? 'not defined' : v.toFixed(2)}<br>${e ? fmt(e.n) : 0} papers coded on both<br><span class="meta">Click: open as design-space table</span>` });
          });
        });
        host.insertAdjacentHTML('beforeend', `<div class="legend"><span>Darker: stronger association</span><span><span class="sw" style="background:${mixc('var(--seq-4)', 'var(--seq-0)', 90)}"></span>V of 0.5 or more</span><span><span class="sw" style="background:${mixc('var(--seq-4)', 'var(--seq-0)', 6)}"></span>About 0</span></div>`);
      },
    };
  };

  /* ================= 3. how systems are built ================= */
  build.chains = p => {
    const C = LZ.chains, dims = C.dims;
    const humanOrder = n => { const i = H.HUMAN.findIndex(h => h[0] === n); return n === REST ? 99 : n === NC ? 98 : i < 0 ? 97 : i; };
    const cols = C.columns.map((col, ci) => { const a = col.map(([name, n]) => ({ name, n })); if (dims[ci] === 'human') a.sort((x, y) => humanOrder(x.name) - humanOrder(y.name)); a.forEach((x, i) => { x.idx = i; x.f = dims[ci]; x.out = []; x.in = []; }); return a; });
    const biggest = cols.map(c => c.filter(x => x.name !== REST && x.name !== NC)[0]);
    const topLinks = C.links.map(l => [...l].sort((a, b) => b[2] - a[2])[0]);
    return {
      title: 'How systems are built',
      info: infoPanel('How AI scientist systems are typically put together, from technique through to the human role.',
        `Each paper is one path through four columns: ${FNAME.technique}, ${FNAME.architecture}, ${FNAME.span} and ${FNAME.human}. Band and node widths show how many papers share a step. Hover a node or band to trace it, click to list its papers. “Rest” pools the less common values.`,
        `${methodsText('chains')} ${fmt(C.n)} papers.`),
      lead: biggest[0] ? `The biggest step in each column is <b>${esc(lab(dims[0], biggest[0].name))}</b>, <b>${esc(lc(lab(dims[1], biggest[1].name)))}</b>, <b>${esc(lc(lab(dims[2], biggest[2].name)))}</b> and <b>${esc(lc(lab(dims[3], biggest[3].name)))}</b>.` : '',
      controls: '',
      draw(host, W, sel) {
        const Wc = Math.max(W, W < 700 ? 720 : 900), nar = W < 700;
        const wr = document.createElement('div'); wr.className = 'scrollx'; host.appendChild(wr);
        const Lm = nar ? 120 : Math.max(190, Math.round(Wc * .15)), Rm = nar ? 160 : Math.max(230, Math.round(Wc * .17)), NW = 14, pad = 10;
        const N = C.n, maxK = Math.max(...cols.map(c => c.length));
        const sc = Math.min(1.5, 460 / N), Hmax = N * sc + (maxK - 1) * pad, Ht = Hmax + 54;
        const xs = dims.map((_, i) => Lm + i * (Wc - Lm - Rm - NW) / (dims.length - 1));
        cols.forEach(c => { const h = c.reduce((a, n) => a + n.n * sc, 0) + (c.length - 1) * pad; let y = 44 + (Hmax - h) / 2; c.forEach(n => { n.y = y; n.h = n.n * sc; y += n.h + pad; }); });
        const links = [];
        C.links.forEach((ls, ci) => ls.forEach(([a, b, n]) => { const A = cols[ci].find(x => x.name === a), B = cols[ci + 1].find(x => x.name === b); if (!A || !B) return; const l = { c: ci, a: A, b: B, n }; links.push(l); A.out.push(l); B.in.push(l); }));
        for (const n of cols.flat()) { n.out.sort((x, y) => x.b.idx - y.b.idx); let o = 0; for (const l of n.out) { l.y0 = n.y + o; o += l.n * sc; } n.in.sort((x, y) => x.a.idx - y.a.idx); o = 0; for (const l of n.in) { l.y1 = n.y + o; o += l.n * sc; } }
        const svg = svgIn(wr, Wc, Ht);
        const rib = l => { const x0 = xs[l.c] + NW, x1 = xs[l.c + 1], xm = (x0 + x1) / 2, h = l.n * sc; return `M${x0},${l.y0}C${xm},${l.y0} ${xm},${l.y1} ${x1},${l.y1}L${x1},${l.y1 + h}C${xm},${l.y1 + h} ${xm},${l.y0 + h} ${x0},${l.y0 + h}Z`; };
        dims.forEach((f, i) => tx(svg, xs[i] + (i === 0 ? 0 : i === dims.length - 1 ? NW : NW / 2), 16, FLD[f] || f, 'lbl', { 'text-anchor': i === 0 ? 'start' : i === dims.length - 1 ? 'end' : 'middle', style: 'font-weight:600' }));
        tx(svg, xs[0], 30, `${fmt(N)} papers`, 'axis');
        const gb = mk('g', {}, svg), gn = mk('g', {}, svg), hl = mk('g', { 'pointer-events': 'none' }, svg);
        const selNodes = new Set((sel ? sel.conds : []).map(([f, v]) => f + ':' + (v === '_' ? NC : v === '~rest' ? REST : v)));
        const paint = set => { hl.innerHTML = ''; gb.style.opacity = set && set.length ? .5 : 1; for (const l of set || []) mk('path', { d: rib(l), style: 'fill:var(--acc)', opacity: .85 }, hl); };
        const lblOf = n => lab(n.f, n.name === REST ? REST : n.name) + (n.name === REST ? '' : '');
        for (const l of links) {
          const e = mk('path', { d: rib(l), fill: cv('--mut'), opacity: .17 }, gb);
          act(e, { kb: true, label: `${lblOf(l.a)} to ${lblOf(l.b)}: ${l.n} papers`, tip: `<b>${esc(lblOf(l.a))}</b> → <b>${esc(lblOf(l.b))}</b><br>${l.n} papers`, click: () => pick(spec1(l.a.f, l.a.name === REST ? '~rest' : l.a.name) + '|' + spec1(l.b.f, l.b.name === REST ? '~rest' : l.b.name)), over: () => paint([l]), out: () => paint([]) });
          e.addEventListener('focus', () => paint([l])); e.addEventListener('blur', () => paint([]));
        }
        cols.forEach((c, ci) => c.forEach(n => {
          const col = n.f === 'human' && n.name !== REST && n.name !== NC ? H.humanColor(n.name) : cv('--dim');
          const chosen = selNodes.has(n.f + ':' + n.name);
          mk('rect', { x: xs[ci], y: n.y, width: NW, height: Math.max(1.5, n.h), fill: col, rx: 2, stroke: chosen ? cv('--acc') : 'none', 'stroke-width': 2 }, gn);
          const last = ci === dims.length - 1, t = tx(gn, last ? xs[ci] + NW + 8 : xs[ci] + NW + 6, n.y + n.h / 2 + 4, `${short(lblOf(n), nar ? 19 : 30)}  ${n.n}`, ci === 0 || last ? 'lbl' : 'lbl halo', { 'text-anchor': 'start' });
          if (ci === 0) { t.setAttribute('x', xs[0] - 8); t.setAttribute('text-anchor', 'end'); }
          const hit = mk('rect', { x: xs[ci] - 2, y: n.y - 1, width: NW + 4, height: Math.max(4, n.h) + 2, fill: 'transparent' }, gn);
          const touch = () => paint([...n.in, ...n.out]);
          act(hit, { kb: true, label: `${lblOf(n)}: ${n.n} papers`, tip: `<b>${esc(lblOf(n))}</b><br>${n.n} papers (${pc(n.n, N)}%)`, click: () => pick(spec1(n.f, n.name === REST ? '~rest' : n.name)), over: touch, out: () => paint([]) });
          hit.addEventListener('focus', touch); hit.addEventListener('blur', () => paint([]));
        }));
        if ((host.clientWidth || W) < Wc) host.insertAdjacentHTML('beforeend', '<p class="meta">Scroll sideways to see all four columns.</p>');
        host.insertAdjacentHTML('beforeend', '<div class="legend"><span><span class="sw" style="background:var(--acc)"></span>Accent: the band or node you point at</span><span>Last column coloured by human role</span></div>');
      },
    };
  };

  /* ================= 4. lineage ================= */
  build.constellation = p => {
    const have = cites.length > 0;
    const info = infoPanel('Where an idea came from and who built on it: the papers a chosen paper builds on, on the left, and the papers built on it, on the right.',
      `The chosen paper is in the middle. Left: papers it cites, then the papers those cite (${T('hop', 'hop')} 2). Right: papers that cite it, then papers citing those. Within a column papers run by month. Dot area is ${T('cic', 'cited here')}; colour is ${T('layer', 'layer')}. Hover for its links, click to open the paper, double-click or “Centre” to re-centre.`,
      'Links are the citations among the papers of this review. A paper reached by two routes sits at its nearest hop.');
    if (!have) return { title: 'Lineage', info, lead: '', controls: '', noList: true, draw(host) { host.innerHTML = emptyView('Citation links appear here once they are part of the page data.'); } };
    const hops = p.get('hops') === '1' ? 1 : 2;
    const def = [...EW].sort(byCic)[0];
    const f = EBY.get(p.get('focus')) || def;
    const L = lineage(f.id, hops), core = L.right[1].filter(w => w.layer === 'core').length;
    return {
      title: 'Lineage', info,
      lead: `Directly, <b>“${esc(short(f.title, 70))}”</b> builds on <b>${fmt(L.left[1].length)}</b> paper${L.left[1].length === 1 ? '' : 's'} and is built on by <b>${fmt(L.right[1].length)}</b>${L.right[1].length ? ` (${pc(core, L.right[1].length)}% of them core)` : ''}${hops === 2 ? `. Two ${T('hop', 'hops')} out it reaches ${fmt(L.left[2].length)} earlier and ${fmt(L.right[2].length)} later papers` : ''}.`,
      controls: `<span class="meta">Centre on</span><input type="search" id="fsel" list="wlist" value="${esc(f.title)}" size="46" aria-label="Choose a paper by title" placeholder="Type a title…"><datalist id="wlist">${[...EW].sort(byCic).map(w => `<option value="${esc(w.title)}">`).join('')}</datalist><span class="meta">${T('hop', 'Hops')}</span><div class="seg" role="group" aria-label="Hops">${[1, 2].map(h => `<button aria-pressed="${h === hops}" data-p="hops" data-v="${h}">${h}</button>`).join('')}</div>`,
      defSel: `ctx:${f.id}/${hops}`,
      extra: w => `<button class="btn" data-centre="${esc(w.id)}" style="height:26px;padding:0 9px">Centre</button>`,
      draw(host, W, sel) {
        const Wc = Math.max(W, hops === 2 ? 760 : 560), wr = document.createElement('div'); wr.className = 'scrollx'; host.appendChild(wr);
        const defs = hops === 2 ? [['L2', L.left[2], 'Builds on, hop 2'], ['L1', L.left[1], 'Builds on, hop 1'], ['C', [f], 'Focus'], ['R1', L.right[1], 'Built on by, hop 1'], ['R2', L.right[2], 'Built on by, hop 2']] : [['L1', L.left[1], 'Builds on, hop 1'], ['C', [f], 'Focus'], ['R1', L.right[1], 'Built on by, hop 1']];
        const maxN = Math.max(1, ...defs.filter(c => c[0] !== 'C').map(c => c[1].length));
        const wts = defs.map(c => c[0] === 'C' ? .8 : .4 + Math.sqrt(c[1].length / maxN) * 1.5), tot = wts.reduce((a, b) => a + b, 0);
        let x = 0; const cx = defs.map((c, i) => { const w = Wc * wts[i] / tot, r = { x0: x, x1: x + w, w }; x += w; return r; });
        const rad = c => 2.4 + Math.sqrt(c) * 1.5, headH = 46, pos = new Map();
        const blocks = defs.map((c, i) => {
          if (c[0] === 'C') return null;
          const arr = [...c[1]].sort((a, b) => mkey(a) - mkey(b) || a.id.localeCompare(b.id));
          const area = arr.reduce((a, w) => a + (2 * rad(w.cited_here) + 3) ** 2, 0), pw = Math.max(40, Math.min(cx[i].w - 24, Math.max(70, area / 230)));
          const left = (cx[i].x0 + cx[i].x1) / 2 - pw / 2; let px = 0, py = 0, rowH = 0, row = []; const items = [];
          const flush = () => { for (const q of row) q.y = py + rowH / 2; py += rowH + 3; rowH = 0; row = []; px = 0; };
          for (const w of arr) { const r = rad(w.cited_here); if (px + 2 * r > pw && row.length) flush(); const q = { w, r, x: left + px + r }; px += 2 * r + 3; rowH = Math.max(rowH, 2 * r); row.push(q); items.push(q); }
          flush(); return { items, h: Math.max(0, py - 3) };
        });
        const ci = defs.findIndex(c => c[0] === 'C'), fx = (cx[ci].x0 + cx[ci].x1) / 2, fr = Math.max(rad(f.cited_here), 8);
        const bh = Math.max(150, ...blocks.filter(Boolean).map(b => b.h)), fy = headH + 16 + bh / 2;
        blocks.forEach(b => { if (!b) return; const off = fy - b.h / 2; for (const q of b.items) { q.y += off; pos.set(q.w.id, q); } });
        const bottom = fy + bh / 2 + 10; pos.set(f.id, { w: f, r: fr, x: fx, y: fy });
        const others = EW.filter(w => !L.seen.has(w.id)).sort((a, b) => mkey(a) - mkey(b) || a.id.localeCompare(b.id));
        const oy0 = Math.max(bottom, fy + fr + 70) + 30; let ox = 10, oy = oy0 + 8; const orr = 2.4;
        for (const w of others) { if (ox + 2 * orr > Wc - 10) { ox = 10; oy += 7.5; } pos.set(w.id, { w, r: orr, x: ox + orr, y: oy, faded: true }); ox += 7.5; }
        const svg = svgIn(wr, Wc, oy + 14), gE = mk('g', {}, svg), gH = mk('g', { 'pointer-events': 'none' }, svg), gN = mk('g', {}, svg);
        const edge = (a, b) => { const m = (a.x + b.x) / 2; return `M${a.x},${a.y}C${m},${a.y} ${m},${b.y} ${b.x},${b.y}`; };
        for (const c of [L.left[1], L.right[1]]) for (const w of c) mk('path', { d: edge(pos.get(w.id), pos.get(f.id)), fill: 'none', stroke: cv('--mut'), 'stroke-opacity': .12 }, gE);
        defs.forEach((c, i) => {
          const t = c[0] === 'C' ? 'Focus' : c[2], n = c[1].length;
          tx(svg, (cx[i].x0 + cx[i].x1) / 2, 16, t, 'lbl', { 'text-anchor': 'middle' });
          tx(svg, (cx[i].x0 + cx[i].x1) / 2, 31, c[0] === 'C' ? 'cited ' + f.cited_here + '×' : `${fmt(n)} paper${n === 1 ? '' : 's'}`, 'axis', { 'text-anchor': 'middle' });
          if (c[0] === 'L1' || c[0] === 'R1') { const sp = (c[0] === 'L1' ? 'cout:' : 'cin:') + f.id; const h = mk('rect', { x: cx[i].x0 + 4, y: 2, width: cx[i].w - 8, height: 36, fill: 'transparent' }, svg); act(h, { click: () => pick(sp), kb: true, label: `List: ${t}, ${n} papers`, tip: `List the ${n} papers in this column` }); }
        });
        const ctxIds = new Set([...L.left.flat(), ...L.right.flat()].map(w => w.id)); ctxIds.add(f.id);
        const nbr = id => [...(cOut.get(id) || []).map(v => ['o', v]), ...(cIn.get(id) || []).map(v => ['i', v])].filter(([, v]) => ctxIds.has(v) && pos.has(v));
        const hov = w => { gH.innerHTML = ''; const a = pos.get(w.id); for (const [d, v] of nbr(w.id)) { const b = pos.get(v); mk('path', { d: d === 'o' ? edge(a, b) : edge(b, a), fill: 'none', stroke: d === 'o' ? cv('--h-collab') : cv('--acc'), 'stroke-width': 1.6, opacity: .85 }, gH); } };
        for (const q of pos.values()) {
          const w = q.w, dot = mk('circle', { cx: q.x, cy: q.y, r: q.r, fill: H.layerColor(w.layer), opacity: q.faded ? .28 : (w.id === f.id ? 1 : .88) }, gN);
          if (w.id === f.id) mk('circle', { cx: q.x, cy: q.y, r: q.r + 5, fill: 'none', stroke: cv('--acc'), 'stroke-width': 2 }, gN);
          act(dot, { click: () => H.openDrawer(w.id), tip: `<b>${esc(w.title)}</b><br>${esc(H.layerLabel(w.layer))} · ${esc(monthName(w))} · cited ${w.cited_here}×<br><span class="meta">${w.id === f.id ? 'Click: open the paper' : 'Click: open · double-click: centre here'}</span>`, label: w.title, over: () => hov(w), out: () => { gH.innerHTML = ''; } });
          if (w.id !== f.id) dot.addEventListener('dblclick', () => go({ focus: w.id, sel: null }));
        }
        wrap(short(f.title, 90), Math.max(14, Math.floor((cx[ci].w - 8) / 6.4))).forEach((l, i) => tx(gN, fx, fy + fr + 22 + i * 14, l, 'lbl halo', { 'text-anchor': 'middle', 'pointer-events': 'none' }));
        tx(svg, 10, oy0 - 8, `Not within ${hops} hop${hops === 1 ? '' : 's'} of the focus: ${fmt(others.length)} papers (faded)`, 'lbl-m');
        host.insertAdjacentHTML('beforeend', `<div class="legend"><span>Dot area: ${T('cic', 'cited here')}</span>${H.LAYERS.filter(l => EW.some(w => w.layer === l[0])).map(l => `<span><span class="dot" style="background:${H.layerColor(l[0])}"></span>${l[1]}</span>`).join('')}</div>`);
      },
    };
  };

  /* ================= 5. trends ================= */
  const techColor = i => { const h = Math.round((i * 137.5 + 20) % 360); return isLight() ? `hsl(${h} 55% 36%)` : `hsl(${h} 60% 66%)`; };
  build.time = p => {
    const by = p.get('by') === 'half' ? 'half' : 'year', mode = p.get('mode') === 'share' ? 'share' : 'count';
    const TR = LZ.trends[by], dim = TR.dim, periods = TR.periods;
    const tot = {}; for (const per of periods) for (const [v, n] of Object.entries(TR.counts[per])) tot[v] = (tot[v] || 0) + n;
    const vals = Object.keys(tot).sort((a, b) => (a === NC) - (b === NC) || tot[b] - tot[a] || a.localeCompare(b));
    const colorOf = v => v === NC ? cv('--h-null') : techColor(vals.indexOf(v));
    const first = periods[0], lastP = periods[periods.length - 1];
    let up = null, dn = null;
    if (periods.length > 1) for (const v of vals) { if (v === NC) continue; const a = (TR.shares[first] || {})[v] || 0, b = (TR.shares[lastP] || {})[v] || 0; const d = b - a; if (!up || d > up.d) up = { v, a, b, d }; if (!dn || d < dn.d) dn = { v, a, b, d }; }
    const pLab = per => by === 'half' ? per.replace('H', ' H') : per;
    return {
      title: 'Trends',
      info: infoPanel('What is gaining ground in the field and what is fading, by publication period.',
        `Each bar is one period; segments are the values of ${FNAME[dim]}, biggest at the bottom. “Papers” shows counts, “Share” stretches every bar to the same height so the mix can be compared. Click a segment to list its papers.`,
        `${methodsText('trends')} ${TR.undated ? fmt(TR.undated) + ' papers have no date and are left out.' : ''}`),
      lead: up && up.d > 0 ? `<b>${esc(lab(dim, up.v))}</b> is gaining ground, from <b>${shareTxt(up.a)}</b> of papers in ${esc(pLab(first))} to <b>${shareTxt(up.b)}</b> in ${esc(pLab(lastP))}${dn && dn.d < 0 ? `. <b>${esc(lab(dim, dn.v))}</b> is fading, from <b>${shareTxt(dn.a)}</b> to <b>${shareTxt(dn.b)}</b>` : ''}.` : (periods.length ? 'Too few periods to show a direction.' : ''),
      controls: `<span class="meta">Period</span><div class="seg" role="group" aria-label="Period">${[['year', 'Year'], ['half', 'Half-year']].map(([k, l]) => `<button aria-pressed="${k === by}" data-p="by" data-v="${k}">${l}</button>`).join('')}</div><span class="meta">Bars</span><div class="seg" role="group" aria-label="Bars">${[['count', 'Papers'], ['share', 'Share']].map(([k, l]) => `<button aria-pressed="${k === mode}" data-p="mode" data-v="${k}">${l}</button>`).join('')}</div>`,
      draw(host, W, sel) {
        if (!periods.length) { host.innerHTML = emptyView('No dated papers to show.'); return; }
        const wide = W >= 720, Lm = 40, Rm = wide ? 250 : 10, Tm = 24, Bm = 30, Hh = 340, pw = W - Lm - Rm;
        const svg = svgIn(host, W, Hh + Tm + Bm), band = pw / periods.length, bw = Math.min(110, band * .62);
        const maxT = Math.max(...periods.map(per => TR.totals[per])), ymax = mode === 'share' ? 1 : maxT;
        const y = v => Tm + Hh * (1 - v / ymax);
        const steps = mode === 'share' ? [0, .25, .5, .75, 1] : [0, .25, .5, .75, 1].map(f => Math.round(maxT * f));
        steps.forEach(s => { mk('line', { x1: Lm, x2: Lm + pw, y1: y(s), y2: y(s), class: 'gridline' }, svg); tx(svg, Lm - 6, y(s) + 4, mode === 'share' ? Math.round(s * 100) + '%' : s, 'axis', { 'text-anchor': 'end' }); });
        const selV = (sel ? sel.conds : []).find(c => c[0] === dim);
        periods.forEach((per, i) => {
          const x = Lm + i * band + (band - bw) / 2; let acc = 0;
          for (const v of vals) {
            const n = TR.counts[per][v]; if (!n) continue;
            const h0 = mode === 'share' ? TR.shares[per][v] : n, y1 = y(acc + h0), y0 = y(acc); acc += h0;
            const dimmed = selV && lab(dim, selV[1]) !== lab(dim, v);
            const r = mk('rect', { x, y: y1, width: bw, height: Math.max(1, y0 - y1 - .8), style: 'fill:' + colorOf(v), opacity: dimmed ? .25 : .92 }, svg);
            if (y0 - y1 > 16) tx(svg, x + bw / 2, (y0 + y1) / 2 + 4, n, 'lbl', { 'text-anchor': 'middle', fill: 'var(--bg)', 'pointer-events': 'none', style: 'font-weight:600' });
            act(r, { kb: true, label: `${lab(dim, v)}, ${pLab(per)}: ${n} papers`, tip: `<b>${esc(lab(dim, v))}</b> · ${esc(pLab(per))}<br>${n} paper${n === 1 ? '' : 's'} of ${TR.totals[per]} (${shareTxt(TR.shares[per][v])})`, click: () => pick(spec1(dim, v) + '|period:' + per) });
          }
          tx(svg, x + bw / 2, Tm + Hh + 18, pLab(per), 'axis', { 'text-anchor': 'middle' });
          tx(svg, x + bw / 2, y(mode === 'share' ? 1 : TR.totals[per]) - 4, TR.totals[per], 'lbl-m', { 'text-anchor': 'middle' });
        });
        if (wide) {
          const mids = []; const per = lastP; let acc = 0;
          for (const v of vals) { const n = TR.counts[per][v]; if (!n) continue; const h0 = mode === 'share' ? TR.shares[per][v] : n; mids.push({ v, y: y(acc + h0 / 2) }); acc += h0; }
          mids.sort((a, b) => a.y - b.y); const gap = 14; for (let i = 1; i < mids.length; i++) if (mids[i].y < mids[i - 1].y + gap) mids[i].y = mids[i - 1].y + gap;
          const x = Lm + (periods.length - 1) * band + (band + bw) / 2 + 8;
          for (const m of mids) { mk('rect', { x, y: m.y - 5, width: 9, height: 9, style: 'fill:' + colorOf(m.v), rx: 2 }, svg); tx(svg, x + 14, m.y + 4, `${short(lab(dim, m.v), 28)}  ${tot[m.v]}`, 'lbl'); }
        } else host.insertAdjacentHTML('beforeend', `<div class="legend">${vals.map(v => `<span><span class="dot" style="background:${colorOf(v)}"></span>${esc(lab(dim, v))} ${tot[v]}</span>`).join('')}</div>`);
      },
    };
  };

  /* ================= 6. technique adoption ================= */
  build.adopt = p => {
    const A = LZ.adoption, ok = A.cells.length > 0;
    const info = infoPanel('When each technique first appeared, and how widely it has been used since.',
      'Rows are techniques, grouped by the stage of research they belong to; columns are half-years. A cell is the number of papers using that technique in that half-year; darker is more. A ring marks the half-year in which a technique is first seen.',
      `${methodsText('technique_adoption')} ${esc(A.coverage_note)}`);
    if (!ok) return { title: 'Technique adoption', info, lead: '', controls: '', noList: true, draw(host) { host.innerHTML = emptyView('Technique adoption appears here once technique readings are recorded.'); } };
    const cellMap = new Map(A.cells.map(c => [c.technique + '|' + c.period, c]));
    const stageOf = {}; for (const c of A.cells) stageOf[c.technique] ??= c.stage;
    const totalOf = {}; for (const c of A.cells) totalOf[c.technique] = (totalOf[c.technique] || 0) + c.works;
    const stages = A.stages.slice();
    const rowsByStage = stages.map(s => ({ s, rows: A.techniques.filter(t => stageOf[t] === s).sort((a, b) => (A.first_seen[a] || '').localeCompare(A.first_seen[b] || '') || totalOf[b] - totalOf[a] || a.localeCompare(b)) }));
    const maxN = Math.max(...A.cells.map(c => c.works));
    const newest = [...A.techniques].sort((a, b) => (A.first_seen[b] || '').localeCompare(A.first_seen[a] || '') || a.localeCompare(b))[0];
    const busiest = [...A.techniques].sort((a, b) => totalOf[b] - totalOf[a] || a.localeCompare(b))[0];
    const tl = t => A.labels[t] || t;
    return {
      title: 'Technique adoption', info,
      lead: `<b>${esc(tl(busiest))}</b> is the most used technique. The newest to appear is <b>${esc(tl(newest))}</b>, first seen in ${esc((A.first_seen[newest] || '').replace('H', ' H'))}.`,
      controls: `<span class="meta">${esc(A.coverage_note)}</span>`,
      draw(host, W) {
        const avail = host.clientWidth || W, narrow = avail < 520, lw = narrow ? 130 : 230, np = A.periods.length;
        const cs = Math.max(34, Math.min(64, Math.floor((avail - lw - 8) / np))), rh = 30, hdr = 26;
        const nRows = rowsByStage.reduce((a, g) => a + g.rows.length + 1, 0);
        const wr = document.createElement('div'); wr.className = 'scrollx'; host.appendChild(wr);
        const svg = svgIn(wr, lw + np * cs + 8, hdr + nRows * rh + 8);
        A.periods.forEach((per, j) => tx(svg, lw + j * cs + cs / 2, hdr - 8, per.replace('H', ' H'), 'axis', { 'text-anchor': 'middle' }));
        let y = hdr;
        for (const g of rowsByStage) {
          tx(svg, 0, y + rh - 9, short(H.pretty(g.s), 34), 'lbl', { style: 'font-weight:600' }); y += rh;
          for (const t of g.rows) {
            tx(svg, lw - 10, y + rh / 2 + 4, short(tl(t), narrow ? 17 : 34), 'lbl-m', { 'text-anchor': 'end' });
            A.periods.forEach((per, j) => {
              const c = cellMap.get(t + '|' + per), n = c ? c.works : 0, x = lw + j * cs, pcnt = 10 + Math.sqrt(n / maxN) * 80, first = A.first_seen[t] === per;
              const gcell = mk('g', {}, svg);
              mk('rect', { x: x + 1.5, y: y + 1.5, width: cs - 3, height: rh - 3, rx: 3, style: 'fill:' + (n ? mixc('var(--seq-4)', 'var(--seq-0)', pcnt) : 'var(--raised)'), opacity: n ? 1 : .5 }, gcell);
              if (n) tx(gcell, x + cs / 2, y + rh / 2 + 4, n, 'lbl', { 'text-anchor': 'middle', fill: INK(pcnt), style: 'font-weight:600' });
              if (first) mk('rect', { x: x + 0.5, y: y + 0.5, width: cs - 1, height: rh - 1, rx: 4, fill: 'none', stroke: cv('--acc'), 'stroke-width': 2 }, gcell);
              act(gcell, { tip: `<b>${esc(tl(t))}</b> · ${esc(per.replace('H', ' H'))}<br>${n} paper${n === 1 ? '' : 's'}${first ? '<br><span class="meta">First seen here</span>' : ''}`, kb: true, label: `${tl(t)}, ${per}: ${n} papers${first ? ', first seen' : ''}`, click: () => { if (c) pick('cell:' + t + '/' + per); } });
            });
            y += rh;
          }
        }
        host.insertAdjacentHTML('beforeend', `<div class="legend"><span>Darker: more papers</span><span><svg width="16" height="14"><rect x="1.5" y="1.5" width="13" height="11" rx="3" fill="none" stroke="${cv('--acc')}" stroke-width="2"/></svg>First seen</span>${A.unlisted && A.unlisted.length ? `<span>${fmt(A.unlisted.length)} techniques are not in the codebook</span>` : ''}</div>`);
      },
    };
  };

  /* ================= 7. taxonomy ================= */
  build.icicle = p => {
    const LV = LZ.icicle.dims;
    const z = (p.get('z') || '').split('/').filter(Boolean).slice(0, LV.length - 1);
    let node = LZ.icicle; for (const nm of z) node = (node.children || []).find(c => c.name === nm) || node;
    const k = z.length, kids = node.children || [];
    const bigK = kids.filter(c => c.name !== NC)[0];
    const labelOf = (i, nm) => nm === NC ? NC : lab(LV[i], nm);
    const where = k ? `Within <b>${esc(z.map((v, i) => labelOf(i, v)).join(' › '))}</b> (${fmt(node.count)} papers)` : `Across <b>${fmt(node.count)}</b> papers`;
    const notCoded = kids.find(c => c.name === NC);
    return {
      title: 'Taxonomy',
      info: infoPanel(`How the corpus divides up: by ${FNAME.layer}, then by ${FNAME.technique}, then by ${FNAME.architecture}.`,
        `Block width is the number of papers, and each block sits exactly under its parent. Colour is the layer. Dashed blocks are papers not coded at that level. Click a block to zoom into that branch and list its papers; the path above the chart zooms back out.`,
        methodsText('icicle')),
      lead: bigK ? `${where}, the most common ${FNAME[LV[k]]} is <b>${esc(labelOf(k, bigK.name))}</b>: <b>${fmt(bigK.count)}</b> papers (${pc(bigK.count, node.count)}%).${notCoded ? ` <b>${fmt(notCoded.count)}</b> ${notCoded.count === 1 ? 'paper is' : 'papers are'} not coded at this level.` : ''}` : '',
      controls: `<nav aria-label="Zoom path" class="pt"><button class="chip" data-p="z" data-v="" ${k ? '' : 'aria-pressed="true" disabled'}>All papers</button>${z.map((v, i) => `<span class="meta">›</span><button class="chip" data-p="z" data-v="${esc(z.slice(0, i + 1).join('/'))}" data-sel-also="${esc(z.slice(0, i + 1).map((x, j) => spec1(LV[j], x)).join('|'))}" ${i === k - 1 ? 'aria-pressed="true" disabled' : ''}>${esc(labelOf(i, v))}</button>`).join('')}</nav>`,
      draw(host, W, sel) {
        const gut = W < 560 ? 70 : 104, rowH = 54, gap = 3, pw = W - gut - 4, rowsN = LV.length - k + 1;
        const svg = svgIn(host, W, rowsN * (rowH + gap) + 6);
        const levels = ['All papers', 'Layer', 'Technique', 'Architecture'];
        for (let r = 0; r < rowsN; r++) tx(svg, gut - 10, r * (rowH + gap) + rowH / 2 + 4, r === 0 ? (k ? levels[k] : 'All') : levels[k + r], 'lbl-m', { 'text-anchor': 'end' });
        const blocks = [];
        const lay = (nd, x, w, row, path) => { let cx = x; for (const c of nd.children || []) { const ww = w * c.count / nd.count; blocks.push({ row, x: cx, w: ww, c, path: [...path, c.name], lvl: path.length }); lay(c, cx, ww, row + 1, [...path, c.name]); cx += ww; } };
        blocks.push({ row: 0, x: 0, w: pw, c: node, path: z, root: true, lvl: k - 1 });
        lay(node, 0, pw, 1, z);
        const selS = sel ? sel.spec : null;
        for (const b of blocks) {
          const y = b.row * (rowH + gap), nul = b.c.name === NC && !b.root;
          const lname = b.path[0], lcol = b.root && !k ? null : (lname && lname !== NC ? `var(${(H.LAYERS.find(l => l[0] === lname) || [, , '--l-unlayered'])[2]})` : 'var(--l-unlayered)');
          const mixp = b.root && !k ? 0 : [0, 0, 78, 56, 40][Math.min(4, b.path.length)];
          const fillc = nul ? 'none' : (lcol ? mixc(lcol, 'var(--surface)', mixp || 100) : 'var(--raised)');
          const g = mk('g', {}, svg), sw = Math.max(.5, b.w - 1.5);
          const full = b.path.map((v, i) => spec1(LV[i], v)).join('|');
          const isSelected = selS && full === selS;
          mk('rect', { x: gut + b.x, y, width: sw, height: rowH, style: 'fill:' + fillc, stroke: nul ? cv('--dim') : isSelected ? cv('--acc') : 'none', 'stroke-dasharray': nul ? '3 3' : null, 'stroke-width': isSelected ? 2.5 : 1, rx: 3 }, g);
          const name = b.root && !k ? 'All papers' : labelOf(b.root ? k - 1 : b.lvl, b.c.name);
          const ink = nul ? 'var(--mut)' : 'var(--bg)';
          if (b.w > 46) { tx(g, gut + b.x + 6, y + 21, short(name, Math.floor((b.w - 10) / 6.4)), 'lbl', { fill: ink, 'pointer-events': 'none', style: 'font-weight:600' }); tx(g, gut + b.x + 6, y + 38, `${b.c.count}` + (b.w > 90 ? ` · ${pc(b.c.count, node.count)}%` : ''), 'lbl-m', { fill: ink, opacity: .85, 'pointer-events': 'none' }); }
          else if (b.w > 20) tx(g, gut + b.x + b.w / 2, y + 31, b.c.count, 'lbl-m', { fill: ink, 'text-anchor': 'middle', 'pointer-events': 'none' });
          const leaf = !(b.c.children && b.c.children.length) || b.path.length >= LV.length;
          act(g, { kb: true, label: `${name}: ${b.c.count} papers${leaf ? '' : '. Zoom in'}`, tip: `<b>${esc(name)}</b><br>${b.c.count} papers (${pc(b.c.count, LZ.icicle.count)}% of all)<br><span class="meta">${b.root || leaf ? 'Click to list these papers' : 'Click to zoom in and list these papers'}</span>`, click: () => { if (b.root) { go({ sel: full || '-' }); return; } if (leaf) go({ sel: full }); else go({ z: b.path.join('/'), sel: full }); } });
        }
      },
    };
  };

  /* ================= 8. evidence ================= */
  const STOP = new Set('the a an and or of to in for on with by as is are was were be been this that these those it its from at which their they we our not can also than into using use used based such more most each both between has have had but if then there will would may via per how when where while who whom what'.split(' '));
  build.wall = p => {
    const ef = ['technique', 'architecture', 'span', 'human'].includes(p.get('ef')) ? p.get('ef') : 'human';
    const cnts = new Map(); for (const w of EW) { const v = raw(w, ef); if (v) cnts.set(v, (cnts.get(v) || 0) + 1); }
    const vs = [...cnts.keys()].sort((a, b) => ef === 'human' ? H.HUMAN.findIndex(h => h[0] === a) - H.HUMAN.findIndex(h => h[0] === b) : cnts.get(b) - cnts.get(a));
    const ev = vs.includes(p.get('ev')) ? p.get('ev') : (ef === 'human' && vs.includes('reviews-or-approves') ? 'reviews-or-approves' : vs[0]);
    const ws = EW.filter(w => raw(w, ef) === ev).sort(byCic), wq = ws.filter(w => quote(w, ef));
    const wc = new Map(); for (const w of wq) for (const t of new Set(quote(w, ef).toLowerCase().match(/[a-z]{4,}/g) || [])) if (!STOP.has(t)) wc.set(t, (wc.get(t) || 0) + 1);
    const topw = [...wc].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0], lb = ev ? lab(ef, ev) : '';
    return {
      title: 'Evidence',
      info: infoPanel(`What papers actually say when their ${FNAME[ef]} is coded as “${esc(lb)}”.`,
        `Each card is the sentence a ${T('miner', 'miner')} recorded as ${T('quote', 'evidence')} for this value, quoted word for word, with the paper’s title, ${T('layer', 'layer')}, month and ${T('cic', 'cited here')} count. Cards run most cited first. The search box matches inside the quotes and highlights hits; click a card to open the paper.`,
        'The commonest word skips a short list of function words and is counted once per quote. Search matches any text containing it, so its count can be higher.'),
      lead: ev ? `<b>${fmt(ws.length)}</b> papers are coded “<b>${esc(lc(lb))}</b>” for ${FNAME[ef]}, and ${wq.length === ws.length ? 'each' : `${fmt(wq.length)} of them`} backs it with a quote${topw ? `. The commonest word in those quotes is <button class="lnk" data-qset="${esc(topw[0])}">${esc(topw[0])}</button>, in ${fmt(wq.filter(w => quote(w, ef).toLowerCase().includes(topw[0])).length)} of them` : ''}.` : '',
      controls: `<span class="meta">Field</span><div class="seg" role="group" aria-label="Field">${['human', 'technique', 'architecture', 'span'].map(f => `<button aria-pressed="${f === ef}" data-p="ef" data-v="${f}" data-clr="ev,q">${FLD[f]}</button>`).join('')}</div>`,
      pre: `<div class="vchips" role="group" aria-label="Value">${vs.map(v => `<button class="chip" aria-pressed="${v === ev}" data-p="ev" data-v="${esc(v)}">${esc(lab(ef, v))} <span class="n">${cnts.get(v)}</span></button>`).join('')}</div>`,
      noList: true,
      draw(host) {
        const q0 = p.get('q') || '';
        host.innerHTML = `<div class="wallsum"><input type="search" id="wq" placeholder="Search inside these quotes…" value="${esc(q0)}" aria-label="Search inside quotes" size="30"><span class="meta" id="wcount"></span></div><div class="wall" id="wallbox"></div><p style="margin:6px 0 0"><button class="btn" id="wmore" hidden></button></p>`;
        let showAll = false;
        const paint = () => {
          const q = document.getElementById('wq').value.trim();
          const m = q ? wq.filter(w => quote(w, ef).toLowerCase().includes(q.toLowerCase())) : wq;
          document.getElementById('wcount').textContent = q ? `${m.length} of ${wq.length} quotes match “${q}”` : `${wq.length} quotes`;
          const shown = showAll ? m : m.slice(0, 48), re = q ? new RegExp('(' + esc(q).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig') : null;
          const hl = t => re ? esc(t).replace(re, '<mark>$1</mark>') : esc(t);
          document.getElementById('wallbox').innerHTML = shown.length ? shown.map(w => `<article class="wcard" tabindex="0" role="button" data-open="${esc(w.id)}" aria-label="${esc(w.title)}"><blockquote class="quote">“${hl(quote(w, ef))}”</blockquote><div class="meta"><b>${esc(short(w.title, 90))}</b><br><span class="dot" style="background:${H.layerColor(w.layer)}"></span> ${esc(H.layerLabel(w.layer))} · ${esc(monthName(w))} · cited ${w.cited_here}×</div></article>`).join('') : `<p class="empty">No quote contains “${esc(q)}”. Clear the search to see all ${wq.length}.</p>`;
          const mb = document.getElementById('wmore'); mb.hidden = showAll || m.length <= 48; mb.textContent = `Show all ${m.length} quotes`; mb.onclick = () => { showAll = true; paint(); };
          H.hash.set({ q: q || null });
        };
        document.getElementById('wq').addEventListener('input', paint); paint();
      },
    };
  };

  /* ================= 9. influence ================= */
  build.swarm = p => {
    const I = LZ.influence, items = I.items.map(i => ({ ...i, title: (SHELL.get(i.id) || {}).title || i.id, month: (SHELL.get(i.id) || {}).month, year: i.year }));
    const never = items.filter(i => !i.cited_here).length;
    const t10 = items.slice(0, 10).reduce((a, i) => a + i.share, 0);
    return {
      title: 'Influence',
      info: infoPanel('Which papers carry the field, and whether influence is concentrated in a few.',
        `Each dot is one paper, placed by how many other papers in this review cite it (${T('cic', 'cited here')}), on a log scale where each step multiplies the count; one row per ${T('layer', 'layer')}. Zero cannot sit on a log axis, so never-cited papers form a separate cluster at the left. Dots in a row never overlap; they are only pushed up or down. The ten labelled papers are the most cited.`,
        `${methodsText('influence')} ${fmt(I.total_citations)} citations among ${fmt(items.length)} papers.`),
      lead: I.total_citations ? `The ten most-cited papers receive <b>${shareTxt(t10)}</b> of the citations within this review.${I.gini != null ? ` Concentration (${T('gini', 'Gini')}) is <b>${I.gini.toFixed(2)}</b>.` : ''} <b>${pc(never, items.length)}%</b> of papers are never cited.` : '',
      controls: `<button class="btn" data-sel="top:10">List the top 10</button>`,
      draw(host, W, sel) {
        const wr = document.createElement('div'); wr.className = 'scrollx'; host.appendChild(wr); const Wc = Math.max(W, 560);
        const Lm = Wc < 700 ? 86 : 132, zoneW = Wc < 700 ? 64 : 110, Rm = 24, r = 3.6, D = 2 * r + .8;
        const xA = Lm + zoneW + 34, xB = Wc - Rm, maxc = Math.max(...items.map(i => i.cited_here), 2), xs = c => xA + Math.log(c) / Math.log(maxc) * (xB - xA);
        const layers = H.LAYERS.map(l => l[0]).filter(l => items.some(i => i.layer === l));
        const rowsD = layers.map(l => {
          const arr = items.filter(i => i.layer === l), placed = [], pts = arr.filter(i => i.cited_here > 0).sort((a, b) => a.cited_here - b.cited_here || a.id.localeCompare(b.id)); let flip = 1;
          for (const w of pts) { const x = xs(w.cited_here); const cand = [0]; for (const q of placed) { const dx = Math.abs(q.x - x); if (dx < D) { const dy = Math.sqrt(D * D - dx * dx); cand.push(q.y + dy, q.y - dy); } } cand.sort((a, b) => Math.abs(a) - Math.abs(b) || (flip * (b - a))); flip = -flip; const yy = cand.find(c => placed.every(q => (q.x - x) ** 2 + (q.y - c) ** 2 >= D * D - .01)); placed.push({ x, y: yy, w }); }
          const zero = arr.filter(i => !i.cited_here).sort((a, b) => a.id.localeCompare(b.id)), perRow = Math.max(1, Math.floor((zoneW - 6) / D)), zp = [];
          zero.forEach((w, i) => { const rr = Math.floor(i / perRow), cc = i % perRow, inRow = Math.min(perRow, zero.length - rr * perRow); zp.push({ w, x: Lm + (zoneW - inRow * D) / 2 + cc * D + D / 2 + (rr % 2 ? D / 4 : 0), y: 0, rr }); });
          const zr = zero.length ? Math.ceil(zero.length / perRow) : 0; zp.forEach(q => q.y = (q.rr - (zr - 1) / 2) * (D * .9));
          const ext = Math.max(0, ...placed.map(q => Math.abs(q.y)), ...zp.map(q => Math.abs(q.y))) + r;
          return { l, n: arr.length, placed, zp, h: Math.max(46, 2 * ext + 18) };
        });
        const top = 22; let y = top; rowsD.forEach(rw => { rw.cy = y + rw.h / 2; y += rw.h; });
        const svg = svgIn(wr, Wc, y + 34);
        [1, 2, 5, 10, 20, 50, 100].filter(t => t <= maxc).forEach(t => { mk('line', { x1: xs(t), x2: xs(t), y1: top, y2: y, class: 'gridline' }, svg); tx(svg, xs(t), y + 14, t, 'axis', { 'text-anchor': 'middle' }); });
        tx(svg, (xA + xB) / 2, y + 28, 'Cited here (log scale)', 'axis', { 'text-anchor': 'middle' });
        tx(svg, Lm + zoneW / 2, top - 8, 'Never cited (0)', 'axis', { 'text-anchor': 'middle' });
        mk('line', { x1: Lm + zoneW + 17, x2: Lm + zoneW + 17, y1: top, y2: y, stroke: cv('--line'), 'stroke-dasharray': '2 3' }, svg);
        const selSet = sel ? new Set(sel.ws.map(w => w.id)) : null, top10 = new Set(items.slice(0, 10).map(i => i.id)), labelsToPlace = [];
        rowsD.forEach((rw, i) => { if (i % 2 === 0) mk('rect', { x: 0, y: rw.cy - rw.h / 2, width: Wc, height: rw.h, fill: cv('--raised'), opacity: .28, 'pointer-events': 'none' }, svg); });
        rowsD.forEach(rw => {
          const c = H.layerColor(rw.l), lg = mk('g', {}, svg);
          tx(lg, Lm - 14, rw.cy - 2, H.layerLabel(rw.l), 'lbl', { 'text-anchor': 'end' }); tx(lg, Lm - 14, rw.cy + 13, `${rw.n} paper${rw.n === 1 ? '' : 's'}`, 'axis', { 'text-anchor': 'end' });
          const hit = mk('rect', { x: 0, y: rw.cy - rw.h / 2, width: Lm - 6, height: rw.h, fill: 'transparent' }, lg); act(hit, { click: () => pick('layer:' + rw.l), kb: true, label: `${H.layerLabel(rw.l)}: ${rw.n} papers`, tip: `<b>${esc(H.layerLabel(rw.l))}</b><br>${rw.n} papers` });
          for (const q of [...rw.zp, ...rw.placed]) {
            const s_ = selSet && selSet.has(q.w.id);
            const d = mk('circle', { cx: q.x, cy: rw.cy + q.y, r: s_ ? r + 1.4 : r, fill: c, opacity: selSet && !s_ ? .45 : .92, stroke: s_ ? cv('--acc') : cv('--surface'), 'stroke-width': s_ ? 2 : .8 }, svg);
            act(d, { click: () => H.openDrawer(q.w.id), label: q.w.title, tip: `<b>${esc(q.w.title)}</b><br>${esc(H.layerLabel(q.w.layer))} · ${esc(q.w.year ?? '')} · cited ${q.w.cited_here}× (${(q.w.share * 100).toFixed(1)}% of citations)` });
            if (top10.has(q.w.id)) labelsToPlace.push({ q, y: rw.cy + q.y, w: q.w });
          }
        });
        labelsToPlace.sort((a, b) => b.w.cited_here - a.w.cited_here); const boxes = [], cw = 6.0;
        rowsD.forEach(rw => { for (const q of [...rw.placed, ...rw.zp]) boxes.push({ x: q.x - r, y: rw.cy + q.y - r, w: 2 * r, h: 2 * r, dot: true }); });
        for (const Lb of labelsToPlace) {
          const txt = `${short(Lb.w.title, 34)} · ${Lb.w.cited_here}`, w = txt.length * cw + 4, h = 13, X = Lb.q.x, Y = Lb.y; let done = false;
          for (const dy of [0, -15, 15, -30, 30, -45, 45, -60, 60]) for (const side of [-1, 1]) {
            if (done) break; const bx = side < 0 ? X - w - 8 : X + 8, by = Y + dy - h / 2, b = { x: bx, y: by, w, h };
            const own = boxes.filter(o => o.dot && Math.abs(o.x + r - X) < .5 && Math.abs(o.y + r - Y) < .5); own.forEach(o => o.skip = true);
            const bad = bx < 2 || bx + w > Wc - 2 || boxes.some(o => !o.skip && b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y); own.forEach(o => o.skip = false);
            if (bad) continue; boxes.push(b);
            if (dy) mk('line', { x1: X, y1: Y, x2: side < 0 ? bx + w : bx, y2: by + h / 2, stroke: cv('--dim'), 'stroke-width': .8, 'pointer-events': 'none' }, svg);
            tx(svg, side < 0 ? bx + w - 2 : bx + 2, by + h - 3, txt, 'lbl halo', { 'text-anchor': side < 0 ? 'end' : 'start', 'pointer-events': 'none', style: 'font-size:11px' }); done = true;
          }
        }
        if (Wc > W) host.insertAdjacentHTML('beforeend', '<p class="meta">Scroll sideways to see the whole axis.</p>');
      },
    };
  };

  /* ================= 10. results by stage and approach (RS-11, RS-12) and 11. citation rate (CT-4, CT-7) ================= */
  /* Both read the corpus payload (`results`, `citation`), loaded when the lens is opened. */
  let corpusP = null;
  const loadCorpus = () => corpusP || (corpusP = HUB.load(['corpus']).then(x => x.corpus));
  const pr = v => H.pretty(v);
  build.results = () => ({
    title: 'Results by stage and approach',
    noList: true,
    info: infoPanel('What the papers report, by lifecycle stage and approach, for the paper’s own system.',
      'Each cell counts result rows of the paper’s own system for one stage and one approach; darker is more. Click a cell to list its papers. The bars count every row by who the result is about, how strong the evidence is and what kind of value it is.',
      esc((LZ.methods && LZ.methods.results) || '')),
    lead: '', controls: '',
    draw(host) {
      host.innerHTML = '<p class="meta">Loading the result rows…</p>';
      loadCorpus().then(C => {
        if (H.hash.get().get('lens') !== 'results') return;
        const R = C.results; if (!R || !R.rows) { host.innerHTML = emptyView('No result rows are recorded yet.'); return; }
        const cell = new Map(R.cells.map(c => [c.stage + '|' + c.approach, c])), mx = Math.max(1, ...R.cells.map(c => c.n));
        const grid = `<div class="scrollx"><table class="t"><thead><tr><th>Stage</th>${R.approaches.map(a => `<th class="r">${esc(pr(a))}</th>`).join('')}</tr></thead><tbody>${R.stages.map(st => `<tr><th scope="row" style="text-align:left">${esc(pr(st))}</th>${R.approaches.map(a => { const c = cell.get(st + '|' + a); return c ? `<td class="r"><button type="button" class="chip" data-cell="${esc(st + '|' + a)}" style="background:color-mix(in srgb,var(--acc) ${Math.round(15 + 70 * c.n / mx)}%,var(--raised))" aria-label="${esc(pr(st) + ', ' + pr(a) + ': ' + c.n + ' rows over ' + c.works.length + ' papers')}">${fmt(c.n)}</button></td>` : '<td class="r meta">–</td>'; }).join('')}</tr>`).join('')}</tbody></table></div>`;
        const bars = Object.entries(R.bars).map(([f, rows]) => { const tot = rows.reduce((a, x) => a + x[1], 0) || 1; return `<div style="min-width:220px;flex:1"><h3 class="h3">${esc(pr(f))}</h3>${rows.map(([v, n]) => `<div style="display:grid;grid-template-columns:minmax(80px,140px) 1fr 40px;gap:8px;align-items:center;font-size:var(--t-xs);padding:2px 0"><span>${esc(pr(v))}</span><span style="background:var(--raised);height:8px;border-radius:4px"><i style="display:block;height:8px;border-radius:4px;background:var(--acc);width:${(100 * n / tot).toFixed(1)}%"></i></span><span class="tnum">${fmt(n)}</span></div>`).join('')}</div>`; }).join('');
        host.innerHTML = `<p class="lead">${fmt(R.rows)} result rows over ${fmt(R.works_with_rows)} papers (at most ${fmt(R.cap_per_work)} rows per paper are read${R.left_out ? `; ${fmt(R.left_out)} rows are left out by that cap` : ''}); ${fmt(R.own)} describe the paper’s own system.</p>${grid}<div id="rescell"></div><div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:18px">${bars}</div>`;
        host.querySelectorAll('[data-cell]').forEach(b => b.onclick = () => {
          const c = cell.get(b.dataset.cell), box = host.querySelector('#rescell');
          box.innerHTML = `<p class="meta" style="margin-top:12px">${fmt(c.works.length)} paper${c.works.length === 1 ? '' : 's'} with own-system results for ${esc(pr(c.stage))} and ${esc(pr(c.approach))}</p>` + c.works.map(id => `<div><button type="button" class="lnk" data-w="${esc(id)}">${esc(short(((SHELL.get(id) || {}).title) || id, 110))}</button></div>`).join('');
          box.querySelectorAll('[data-w]').forEach(x => x.onclick = () => H.openDrawer(x.dataset.w));
        });
      }).catch(e => { host.innerHTML = `<p class="empty">The result rows could not be loaded: ${esc(e.message || e)}</p>`; });
    },
  });
  build.rate = () => ({
    title: 'Citation rate',
    noList: true,
    info: infoPanel('Which papers are cited most per year since they appeared.',
      'Each row is one paper: how many works of the project cite it, that count per year since publication, and the worldwide count stored with the paper. The two counts measure different things and are never combined.',
      esc((LZ.methods && LZ.methods.citation_rate) || '')),
    lead: '', controls: '',
    draw(host) {
      host.innerHTML = '<p class="meta">Loading the citation counts…</p>';
      loadCorpus().then(C => {
        if (H.hash.get().get('lens') !== 'rate') return;
        const c = C.citation; if (!c) { host.innerHTML = emptyView('No citation data in this page.'); return; }
        if (!c.extractions) { host.innerHTML = '<p class="empty">No reference list has been extracted: every in-corpus citation count is unknown.</p>'; return; }
        host.innerHTML = `<p class="lead">Counts come from the ${fmt(c.extractions)} works whose reference list was extracted (${fmt(c.entries)} entries, ${fmt(c.resolved_links)} resolved to a work of the project) out of ${fmt(c.works_total)} works; a count is a lower bound. ${c.unknown ? `${fmt(c.unknown)} included papers have no rate (no year or no counted citation source) and are not listed.` : ''}</p>
        <div class="scrollx"><table class="t"><thead><tr><th>Paper</th><th class="r">Year</th><th class="r">Per year</th><th class="r">Cited by (in project)</th><th class="r">of which self</th><th class="r">External count (OpenAlex)</th></tr></thead><tbody>${c.rows.map(r => `<tr><td><button type="button" class="lnk" data-w="${esc(r.id)}">${esc(short(((SHELL.get(r.id) || {}).title) || r.id, 100))}</button></td><td class="r">${esc(r.year ?? '–')}</td><td class="r">${r.per_year.toFixed(2)}</td><td class="r">${fmt(r.cited_by ?? 0)}</td><td class="r">${r.self_cited_by == null ? '–' : fmt(r.self_cited_by)}</td><td class="r">${r.external == null ? 'unknown' : fmt(r.external)}</td></tr>`).join('')}</tbody></table></div><p class="meta">Top ${fmt(c.rows.length)} by rate. The as-of year ${esc(c.as_of_year)} counts the publication year as one.</p>`;
        host.querySelectorAll('[data-w]').forEach(x => x.onclick = () => H.openDrawer(x.dataset.w));
      }).catch(e => { host.innerHTML = `<p class="empty">The citation counts could not be loaded: ${esc(e.message || e)}</p>`; });
    },
  });

  /* ================= page shell ================= */
  let listAll = false, lastSel = null;
  function listHtml(res, extra) {
    const n = res.ws.length, shown = listAll ? res.ws : res.ws.slice(0, 40);
    const hv = w => raw(w, 'human');
    return `<div class="hd"><h3 class="h3" style="margin:0">Papers in this selection</h3>
      <button class="chip" aria-pressed="true" id="clrSel" aria-label="Remove selection: ${esc(res.parts.join(', '))}"><span>+</span> ${esc(res.parts.join(' and '))} <span class="n">${fmt(n)} paper${n === 1 ? '' : 's'}</span><span class="x" aria-hidden="true">×</span></button></div>
      ${n ? `<div class="scrollx"><table class="t"><thead><tr><th>Title</th><th>Layer</th><th class="c-h">Human role</th><th class="c-m">Month</th><th class="r">Cited</th>${extra ? '<th></th>' : ''}</tr></thead><tbody>
      ${shown.map(w => `<tr tabindex="0" data-open="${esc(w.id)}"><td><span class="ttl">${esc(w.title)}</span><div class="meta2">${esc(lab('human', hv(w)))} · ${esc(monthName(w))}</div></td><td class="lay"><span class="dot" style="background:${H.layerColor(w.layer)}"></span> ${esc(H.layerLabel(w.layer))}</td><td class="c-h"><span class="dot" style="background:${H.humanColor(hv(w))}"></span> ${esc(lab('human', hv(w)))}</td><td class="c-m num">${esc(monthName(w))}</td><td class="r">${w.cited_here}</td>${extra ? `<td>${extra(w)}</td>` : ''}</tr>`).join('')}</tbody></table></div>
      ${n > shown.length ? `<p><button class="btn" id="showAll">Show all ${fmt(n)} papers</button></p>` : ''}` : '<p class="empty">No paper matches this selection. This combination is a gap in the corpus.</p>'}`;
  }
  function render() {
    const sy = scrollY, p = H.hash.get();
    const id = LENSES.some(l => l[0] === p.get('lens')) ? p.get('lens') : 'matrix';
    const L = build[id](p);
    let spec = p.get('sel'); if (spec == null) spec = L.defSel || null; if (spec === '-') spec = null;
    if (spec !== lastSel) listAll = false;
    const res = resolve(spec);
    main.innerHTML = `${H.header({ level: 1, title: 'Lenses', sub: 'Different cuts through the same papers.', infoHtml: `<b>What it shows</b> The same ${fmt(EW.length)} papers, cut in different ways.<p><span class=k>How to read it.</span> Pick a lens below. Every mark in a chart leads to the papers behind it, listed underneath. Each lens has its own ⓘ with the question it answers and how to read it.</p>` })}
    <nav class="lens-sw" aria-label="Lens">${LENSES.map(([k, nm]) => `<a class="lcard" href="#lens=${k}" ${k === id ? 'aria-current="true"' : ''}><div>${GL[k]}</div><div class="nm">${nm}</div></a>`).join('')}</nav>
    <section class="card lens" aria-label="${esc(L.title)}">
      ${H.header({ title: L.title, infoHtml: L.info })}
      ${L.lead ? `<p class="lead">${L.lead}</p>` : ''}
      ${L.controls ? `<div class="ctl">${L.controls}</div>` : ''}${L.pre || ''}
      <div class="${L.side ? 'two' : ''}"><div><p class="sx-hint">Scroll sideways to see the rest →</p><div id="chart"></div></div>${L.side ? `<aside>${L.side}</aside>` : ''}</div>
    </section>
    <section class="card listpanel" id="listpanel" ${L.noList ? 'hidden' : ''} aria-live="polite">${res ? '' : '<div class="hd"><h3 class="h3" style="margin:0">Papers in this selection</h3></div><p class="empty">Nothing selected. Click a mark in the chart to list the papers behind it.</p>'}${res ? listHtml(res, L.extra) : ''}</section>
    <p class="meta" style="margin-top:22px">About these counts ${H.info(esc(H.SETS_NOTE), 'About these counts')}</p>`;
    const host = document.getElementById('chart');
    L.draw(host, host.clientWidth || 900, res);
    scrollTo(0, sy);
    if (userAct && spec !== lastSel && spec && !L.noList) { const lp = document.getElementById('listpanel'); if (lp.getBoundingClientRect().top > innerHeight - 120) lp.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth' }); }
    lastSel = spec; userAct = false;
  }
  main.addEventListener('click', e => {
    const t = e.target.closest('[data-p],[data-sel],[data-open],[data-qset],[data-centre],[data-go],#clrSel,#showAll'); if (!t) return;
    if (t.id === 'clrSel') { go({ sel: '-' }); return; }
    if (t.id === 'showAll') { listAll = true; render(); return; }
    if (t.dataset.go) { go({ lens: t.dataset.go, rows: t.dataset.rows, cols: t.dataset.cols, sel: null }); return; }
    if (t.dataset.centre) { go({ focus: t.dataset.centre, sel: null }); return; }
    if (t.dataset.open) { if (t.closest('.wcard,tr')) H.openDrawer(t.dataset.open); return; }
    if (t.dataset.qset) { const i = document.getElementById('wq'); i.value = t.dataset.qset; i.dispatchEvent(new Event('input')); return; }
    if (t.dataset.sel) { pick(t.dataset.sel); return; }
    if (t.dataset.p) { const o = { [t.dataset.p]: t.dataset.v || null }; (t.dataset.clr || 'sel').split(',').forEach(k => { if (k !== t.dataset.p) o[k] = null; }); if (t.dataset.p === 'z') o.sel = t.dataset.selAlso || '-'; go(o); }
  });
  main.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('tr[data-open],.wcard')) { e.preventDefault(); H.openDrawer(e.target.dataset.open); } });
  main.addEventListener('change', e => {
    if (e.target.id === 'fsel') { const v = e.target.value.trim().toLowerCase(); const w = EW.find(w => w.title.toLowerCase() === v) || EW.find(w => w.title.toLowerCase().includes(v)); if (w) go({ focus: w.id, sel: null }); }
    else if (e.target.dataset.dim) go({ [e.target.dataset.dim]: e.target.value, sel: null });
  });
  addEventListener('hashchange', render);
  document.addEventListener('hub:theme', render);
  let rw = innerWidth, rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if (innerWidth !== rw) { rw = innerWidth; render(); } }, 200); });
  if (!H.hash.get().get('lens')) H.hash.set({ lens: 'matrix' });
  render();
}).catch(e => {
  document.body.textContent = 'Lenses failed to load: ' + e.message;
});
