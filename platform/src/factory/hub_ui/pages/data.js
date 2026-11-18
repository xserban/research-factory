/* Extracted data page: paper-by-field grid, who read what (coverage), holes.
   Payloads: shell (titles), mining (grid manifest, coverage, holes, methods) and, loaded on demand when a miner is
   picked, grid-<miner> (that miner's fields and, for every included paper it read, each value with its quote and anchor). */
HUB.load(['shell', 'mining']).then(d => {
  const H = HUB.init(d.shell);
  const {esc, fmt, term, info, header, byId, $} = H;
  const M = d.mining, RF = H.RF;
  H.mount({page: 'data', crumb: 'Extracted data'});
  const main = $('#main');

  /* ---------- scoped styles (kit tokens only) ---------- */
  if (!document.getElementById('data-css')) {
    const st = document.createElement('style'); st.id = 'data-css';
    st.textContent = `
.dbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0 10px}
.dbar .grow{flex:1}
.dchips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.dgwrap{background:var(--surface);border-radius:var(--r);overflow:auto;max-height:calc(100vh - 250px);min-height:300px;position:relative}
table.dg{border-collapse:separate;border-spacing:0;font-size:var(--t-s);table-layout:fixed}
.dg th,.dg td{padding:0 8px;border-bottom:1px solid var(--hair);text-align:left;font-weight:400;vertical-align:middle}
.dg td{height:34px;width:170px;max-width:170px;overflow:hidden;white-space:nowrap;cursor:pointer}
.dg td:hover{background:var(--raised)}
.dg td:focus{outline:2px solid var(--acc);outline-offset:-2px}
.dg .t1{position:sticky;left:0;width:250px;min-width:250px;max-width:250px;background:var(--surface);z-index:3;white-space:normal;line-height:1.25;font-weight:500;border-right:1px solid var(--line)}
.dg td.t1{overflow:hidden;font-size:12.5px;cursor:default}
.dg td.t1 a{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:var(--fg);text-decoration:none}
.dg td.t1 a:hover{color:var(--acc)}
.dg thead th{position:sticky;background:var(--surface);z-index:4}
.dg thead tr.g th{top:0;height:28px;background:var(--raised);font:600 12px var(--f-ui);color:var(--mut);z-index:5;border-bottom:0;border-left:1px solid var(--bg)}
.dg thead tr.c th{top:28px;padding:6px 8px 7px;vertical-align:top;border-bottom:1px solid var(--line)}
.dg thead th.t1{z-index:6}
.dg th .nm{display:flex;align-items:center;justify-content:space-between;gap:4px;font:600 12px var(--f-ui);color:var(--fg);white-space:nowrap}
.dg th .nm span{overflow:hidden;text-overflow:ellipsis}
.dg th .em{font:400 11px var(--f-mono);color:var(--dim)}
.srt{border:0;background:transparent;color:var(--dim);font:12px var(--f-mono);cursor:pointer;padding:0 2px}
.srt:hover,.srt[data-on]{color:var(--acc)}
.dist{display:flex;height:8px;border-radius:3px;overflow:hidden;background:var(--hair);margin:5px 0 3px;cursor:help}
.dist i{display:block;height:100%}
.pill.m{max-width:calc(100% - 62px)}
.more{margin-left:6px;font:400 11px var(--f-mono);color:var(--mut)}
.pill{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle;padding:3px 9px;border-radius:999px;background:var(--raised);color:var(--fg);font-size:12px}
.pill .dot{margin-right:6px;width:7px;height:7px}
.pill.gap{background:transparent;color:var(--mut);box-shadow:inset 0 0 0 1px var(--line)}
.pill.on{box-shadow:inset 0 0 0 1.5px var(--acc)}
td.empty{background:repeating-linear-gradient(135deg,transparent 0 5px,var(--hair) 5px 6px);color:var(--dim)}
.pager{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}
.picker{position:relative}
.picker .panel{position:absolute;top:40px;right:0;z-index:30;background:var(--raised);border-radius:8px;box-shadow:var(--shadow);padding:12px 14px;width:min(380px,86vw);max-height:60vh;overflow:auto;display:none}
.picker[open] .panel{display:block}
.panel h4{margin:8px 0 4px;font:600 12px var(--f-ui);color:var(--mut)}
.panel label{display:flex;gap:8px;align-items:center;font-size:var(--t-s);padding:3px 0;cursor:pointer}
.hbar{display:grid;grid-template-columns:minmax(120px,230px) 1fr 130px;gap:12px;align-items:center;width:100%;padding:7px 8px;border:0;background:transparent;color:var(--fg);font:var(--t-s) var(--f-ui);text-align:left;border-radius:6px}
button.hbar{cursor:pointer}
button.hbar:hover{background:var(--raised)}
.hbar .trk{height:14px;background:var(--hair);border-radius:3px;display:flex;overflow:hidden}
.hbar .trk i{display:block;height:100%;background:var(--exc)}
.hbar .lab small{color:var(--dim);display:block;font-size:11px}
.dleg{display:flex;gap:16px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--mut);margin:8px 0}
.dleg i{display:inline-block;width:12px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
canvas#cov{display:block;width:100%;background:var(--surface);border-radius:var(--r)}
canvas#cov:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.covcap{min-height:2.6em;margin:8px 0;font-size:var(--t-s);color:var(--mut)}
.covcap b{color:var(--fg)}
table.cvt{width:100%;border-collapse:collapse;font-size:var(--t-s);margin-top:14px}
.cvt th,.cvt td{padding:7px 8px;border-bottom:1px solid var(--hair);text-align:left;font-weight:400}
.cvt th{color:var(--mut);font-weight:600;font-size:12px}
.cvt td.n{text-align:right;font-family:var(--f-mono)}
.cvt th.n{text-align:right}
.unread{background:var(--surface);border-radius:var(--r);padding:12px 16px;margin-top:10px}
.unread ul{margin:6px 0 0;padding-left:18px;columns:2;column-gap:28px;font-size:var(--t-s)}
.unread li{margin:2px 0;break-inside:avoid}
.dfoot{margin:28px 0 0}
@media (max-width:760px){.dg .t1,.dg td.t1{width:150px;min-width:150px;max-width:150px}.hbar{grid-template-columns:1fr 90px}.hbar .trk{grid-column:1/3;grid-row:2}.unread ul{columns:1}}`;
    document.head.appendChild(st);
  }

  /* ---------- labels ---------- */
  const MN = {'m-classification': 'Classification', 'm-mapping': 'Human role and span', 'm-layer': 'Layer', 'm-descriptors': 'Descriptors', 'm-design-approach': 'Design approach', 'm-lifecycle': 'Lifecycle', 'm-release': 'Release', 'm-stage-steps': 'Stage steps', 'm-stages': 'Stages', 'm-summary': 'Summary', 'm-claims': 'Claims'};
  const mname = n => MN[n] || (n.startsWith('m-tech-') ? 'Technique: ' + n.slice(7).replace(/-/g, ' ') : H.pretty(n.replace(/^m-/, '')));
  const fname = f => H.pretty(f.replace(/_primary$/, '').replace(/_/g, '-'));
  const GAPV = new Set(['not-determinable', 'other', 'not-stated', 'none-stated', 'unclear']);

  /* Grid columns come from the loaded grid-<miner> payload. */
  const MAN = M.grids || [], MANIFEST = new Map(MAN.map(g => [g.miner, g]));
  const DEFAULT_MINER = MANIFEST.has('m-classification') ? 'm-classification' : (MAN[0] ? MAN[0].miner : null);
  let COLS = [], COL = {}, ROWS = [], G = null;
  const CB = M.codebook || {};
  const codeLabel = v => { const e = CB[String(v).split('/').pop()]; return e && e.label ? e.label : H.pretty(String(v).split('/').pop()); };
  const vlFor = (c, k) => k === 'm-layer.category' ? H.layerLabel : k === 'm-mapping.human_position' ? H.humanLabel : c.type !== 'enum' ? (v => String(v)) : k.startsWith('m-tech-') && /\.category$/.test(k) ? codeLabel : H.pretty;
  const getter = i => r => { const x = r.c[i]; return x ? {v: x[0], q: x[1], a: x[2], n: x[3] || 1, all: x[4] || null} : null; };
  function setGrid(g) {
    G = g;
    COLS = g.columns.map((c, i) => ({k: c.key, m: g.miner, label: fname(c.name), type: c.type, group: c.group || '', req: c.required, get: getter(i), vl: vlFor(c, c.key)}));
    COL = Object.fromEntries(COLS.map(c => [c.k, c]));
    ROWS = g.rows.map(r => ({id: r.id, title: (byId.get(r.id) || {}).title || r.id, c: r.c}));
  }
  const cell = (r, c) => { const e = c.get(r); return e && e.v != null && e.v !== '' ? e : null; };
  const cv = (r, c) => { const e = cell(r, c); return e ? e.v : null; };
  const gridCache = new Map();
  const loadGrid = m => gridCache.has(m) ? Promise.resolve(gridCache.get(m)) : HUB.load(['grid-' + m]).then(x => { gridCache.set(m, x['grid-' + m]); return x['grid-' + m]; });

  /* ---------- state (hash) ---------- */
  const S = {view: 'grid', filters: [], hidden: new Set(), sort: null, page: 0, cur: {r: 0, c: 0}, miner: DEFAULT_MINER, minerMissing: false};
  const PS = 100;
  let hashPending = null;
  function readHash() {
    const h = H.hash.get();
    if (['grid', 'coverage', 'holes'].includes(h.get('view'))) S.view = h.get('view');
    const mi = h.get('miner');
    if (mi) { if (MANIFEST.has(mi)) S.miner = mi; else S.minerMissing = true; }
    hashPending = h;
  }
  /* Filters, hidden columns, sort and page can be checked only once the miner's columns are known. */
  function applyHash() {
    const h = hashPending; hashPending = null; if (!h) return;
    try {
      if (h.get('f')) S.filters = JSON.parse(h.get('f')).filter(f => COL[f[0]]).map(f => ({col: f[0], val: f[1]}));
      if (h.get('hide') != null) S.hidden = new Set(h.get('hide').split(',').filter(k => COL[k]));
    } catch (e) { /* a malformed hash is ignored */ }
    if (h.get('sort')) { const [c, dd] = h.get('sort').split('|'); if (COL[c] || c === '__title') S.sort = {col: c, dir: dd === 'd' ? -1 : 1}; }
    S.page = +h.get('p') || 0;
  }
  function writeHash() {
    H.hash.set({view: S.view === 'grid' ? '' : S.view, miner: S.miner && S.miner !== DEFAULT_MINER ? S.miner : '',
      f: S.filters.length ? JSON.stringify(S.filters.map(f => [f.col, f.val])) : '',
      hide: S.hidden.size ? [...S.hidden].join(',') : '', sort: S.sort ? S.sort.col + '|' + (S.sort.dir < 0 ? 'd' : 'a') : '', p: S.page ? S.page : ''});
  }
  readHash();

  /* ---------- grid logic ---------- */
  const visCols = () => COLS.filter(c => !S.hidden.has(c.k));
  const vlab = (c, v) => v == null ? 'No value' : c.vl(v);
  function filtered() {
    const by = {}; for (const f of S.filters) (by[f.col] = by[f.col] || []).push(f);
    let rows = ROWS.filter(r => Object.values(by).every(fs => fs.some(f => { const v = cv(r, COL[f.col]); return f.val === '__empty' ? v == null : f.val === '__gap' ? (v == null || GAPV.has(v)) : v === f.val; })));
    if (S.sort) {
      const {col, dir} = S.sort, g = r => col === '__title' ? r.title : cv(r, COL[col]), lab = x => col === '__title' ? x : vlab(COL[col], x);
      rows = rows.map((r, i) => [r, i]).sort((a, b) => {
        const x = g(a[0]), y = g(b[0]); if (x == null && y == null) return a[1] - b[1]; if (x == null) return 1; if (y == null) return -1;
        const c = lab(x).localeCompare(lab(y)); return c ? c * dir : a[1] - b[1];
      }).map(a => a[0]);
    }
    return rows;
  }
  const filtLabel = f => COL[f.col].label + ': ' + (f.val === '__empty' ? 'no value' : f.val === '__gap' ? 'no value or undetermined' : vlab(COL[f.col], f.val));
  function toggleFilter(col, val) {
    const i = S.filters.findIndex(f => f.col === col && f.val === val);
    if (i >= 0) S.filters.splice(i, 1); else S.filters.push({col, val});
    S.page = 0; writeHash(); drawGrid();
  }
  function dotFor(c, v) {
    if (c.k === 'm-mapping.human_position') return `<span class=dot style="background:${H.humanColor(v)}"></span>`;
    if (c.k === 'm-layer.category') return `<span class=dot style="background:${H.layerColor(v)}"></span>`;
    return '';
  }
  function td(r, c, ri, ci) {
    const e = cell(r, c), v = e ? e.v : null, tab = (ri === S.cur.r && ci === S.cur.c) ? 0 : -1, more = e && e.n > 1;
    const lab = esc(c.label + ': ' + (v == null ? 'no value' : vlab(c, v)) + (more ? '. ' + e.n + ' values: ' + e.all.map(x => vlab(c, x)).join(', ') : '') + (e && e.q ? '. Evidence: ' + e.q : ''));
    if (v == null) return `<td class=empty data-r=${ri} data-c=${ci} tabindex=${tab} aria-label="${lab}">—</td>`;
    const sel = S.filters.some(f => f.col === c.k && f.val === v);
    return `<td data-r=${ri} data-c=${ci} tabindex=${tab} aria-label="${lab}"><span class="pill ${GAPV.has(v) ? 'gap' : ''} ${sel ? 'on' : ''} ${more ? 'm' : ''}">${dotFor(c, v)}${esc(vlab(c, v))}</span>${more ? `<span class=more>+${fmt(e.n - 1)} more</span>` : ''}</td>`;
  }
  function dist(rows, c) {
    const cnt = new Map(); let emp = 0;
    for (const r of rows) { const v = cv(r, c); if (v == null) emp++; else cnt.set(v, (cnt.get(v) || 0) + 1); }
    return {n: rows.length, emp, top: [...cnt].sort((a, b) => b[1] - a[1])};
  }
  const RAMP = ['--seq-4', '--seq-3', '--seq-2', '--seq-1'];
  function distBar(dd, c) {
    if (!dd.n || c.type === 'quote') return '<div class=dist></div>';
    const segs = dd.top.slice(0, 4).map((t, i) => [t[1], `var(${RAMP[i]})`]);
    const rest = dd.top.slice(4).reduce((a, t) => a + t[1], 0); if (rest) segs.push([rest, 'var(--dim)']);
    const txt = dd.top.slice(0, 3).map(t => vlab(c, t[0]) + ' ' + t[1]).join(', ');
    return `<div class=dist role=img aria-label="${esc(c.label + ' values in view: ' + txt)}" data-dist="${c.k}">${segs.map(s => `<i style="width:${100 * s[0] / dd.n}%;background:${s[1]}"></i>`).join('')}</div>`;
  }

  /* ---------- page frame ---------- */
  const TITLE = {grid: 'Paper by paper', coverage: 'Who read what', holes: 'Holes'};
  const INFO = {
    grid: `<b>What it shows</b>One row per paper, one column per field a miner records, each value with the sentence it was based on.<p><span class=k>How to read it.</span> Hover or focus a cell for its evidence. Click a value to keep only the papers that share it, and click again to drop the filter. Arrow keys move between cells; Enter opens the paper. The bar over a column is the spread of its values among the papers in view; the number under it counts empty cells. Filters on one column combine as "or", across columns as "and". Pick a miner to see its fields. Some miners record several values per paper; the cell shows the first, with “+n more” and the full list on hover.</p><p><span class=k>How it's computed.</span> ${esc(M.methods.grid)}</p>`,
    coverage: `<b>What it shows</b>Which miner has read which paper.<p><span class=k>How to read it.</span> Each row is a miner, each thin column a paper, grouped by layer and then by month. Bright cells were also read by the check reading (${term('passB', 'pass B')}); dim cells were read once. Hover a cell or move through the map with the arrow keys to see the paper; Enter opens it. The table below lists the same counts and the papers each miner has not read.</p><p><span class=k>How it's computed.</span> ${esc(M.coverage.methods)}</p>`,
    holes: `<b>What it shows</b>Where the extraction is thin.<p><span class=k>How to read it.</span> Each bar is a coded field, ranked by the share of the papers its miner read that have no usable value. Red: nothing recorded. Grey: the miner answered “not determinable”, “not stated”, “unclear” or “other”. Bars share one scale of papers. Secondary fields and free text are left out. Click a bar to see those papers in the grid.</p><p><span class=k>How it's computed.</span> ${esc(M.holes.methods)}</p>`};

  function frame() {
    main.innerHTML = `${header({kicker: `Mining · ${fmt((M.coverage.miners || []).length)} ${term('miner', 'miners')} · first reading, ${term('passA', 'pass A')}`, title: 'Extracted data', level: 1,
      infoHtml: '<b>What it shows</b>Everything the miners recorded about each paper, with the sentence it was based on one hover away.<p><span class=k>How it\'s computed.</span> Read from the project\'s extraction records; nothing is typed by hand.</p>'})}
    <div class=dbar><div class=seg role=group aria-label="View">${['grid', 'coverage', 'holes'].map(v => `<button data-v="${v}" aria-pressed="${S.view === v}">${{grid: 'Grid', coverage: 'Who read what', holes: 'Holes'}[v]}</button>`).join('')}</div>
      <span class=grow></span><span id=ctl class=dbar style="margin:0"></span></div>
    <h2 class=h2 id=vt>${esc(TITLE[S.view])} ${info(INFO[S.view], 'About ' + TITLE[S.view])}</h2>
    <p class=lead id=lead style="max-width:62ch;margin:6px 0 12px"></p>
    <div class=dchips id=chips></div><div id=view></div>
    <p class="meta dfoot">About these paper counts ${info(H.SETS_NOTE, 'About the paper counts')}</p>`;
    main.querySelectorAll('[data-v]').forEach(b => b.onclick = () => { S.view = b.dataset.v; writeHash(); render(); });
  }
  const view = () => $('#view');
  let cur = {rows: [], cols: [], page: []};

  /* ---------- grid view ---------- */
  function leadGrid(rows, cols) {
    if (!rows.length) return 'No paper matches these filters.';
    if (!cols.length) return 'No column is shown. Pick some under Columns.';
    let filled = 0; const emp = {}; for (const c of cols) emp[c.k] = 0;
    for (const r of rows) for (const c of cols) { if (cell(r, c)) filled++; else emp[c.k]++; }
    const worst = cols.slice().sort((a, b) => emp[b.k] - emp[a.k])[0];
    return `<b>${fmt(rows.length)}</b> papers; <b>${Math.round(100 * filled / (rows.length * cols.length))}%</b> of cells filled. Emptiest column: <b>${esc(worst.label)}</b>, ${fmt(emp[worst.k])} blank.${G.not_read ? ` ${fmt(G.not_read)} included papers were not read by this miner and are not listed.` : ''}`;
  }
  function drawGrid() {
    const rows = filtered(), cols = visCols(); cur = {rows, cols};
    const pages = Math.max(1, Math.ceil(rows.length / PS)); if (S.page >= pages) S.page = pages - 1;
    const pr = rows.slice(S.page * PS, S.page * PS + PS); cur.page = pr;
    S.cur.r = Math.min(S.cur.r, Math.max(0, pr.length - 1)); S.cur.c = Math.min(S.cur.c, Math.max(0, cols.length - 1));
    const groups = []; for (const c of cols) { const g = groups[groups.length - 1]; if (g && g.m === c.group) g.n++; else groups.push({m: c.group, n: 1}); }
    const dists = cols.map(c => dist(rows, c));
    const sc = $('.dgwrap'), sl = sc ? sc.scrollLeft : 0;
    $('#lead').innerHTML = leadGrid(rows, cols);
    $('#chips').innerHTML = (S.minerMissing ? `<span class=meta>That miner has no recorded values. Showing ${esc(mname(S.miner))} instead.</span>` : '') +
      S.filters.map((f, i) => `<button class=chip aria-pressed=true data-rm=${i} aria-label="Remove filter ${esc(filtLabel(f))}">${esc(filtLabel(f))} <span class=x>×</span></button>`).join('') + (S.filters.length > 1 ? '<button class=chip data-clear>Clear all</button>' : '');
    if ($('#pickBtn')) $('#pickBtn').textContent = `Columns (${cols.length} of ${COLS.length})`;
    const sortMark = k => S.sort && S.sort.col === k ? (S.sort.dir > 0 ? '↑' : '↓') : '⇅';
    view().innerHTML = `<div class=dgwrap><table class=dg role=grid aria-label="Extracted data, one row per paper"><thead>
      <tr class=g><th class=t1 style="background:var(--raised)"></th>${groups.map(g => `<th colspan=${g.n}>${esc(g.m ? H.pretty(g.m) : mname(S.miner))}</th>`).join('')}</tr>
      <tr class=c><th class=t1><div class=nm><span>Paper</span><button class=srt data-sort="__title" ${S.sort && S.sort.col === '__title' ? 'data-on' : ''} aria-label="Sort by title">${sortMark('__title')}</button></div><div class=em>${fmt(rows.length)} papers</div></th>
      ${cols.map((c, i) => `<th scope=col><div class=nm><span title="${esc(c.label)}">${esc(c.label)}</span><button class=srt data-sort="${c.k}" ${S.sort && S.sort.col === c.k ? 'data-on' : ''} aria-label="Sort by ${esc(c.label)}">${sortMark(c.k)}</button></div>${distBar(dists[i], c)}<div class=em>— ${fmt(dists[i].emp)}</div></th>`).join('')}</tr></thead>
      <tbody>${pr.map((r, ri) => `<tr><td class=t1><a href="#" data-open="${esc(r.id)}">${esc(r.title)}</a></td>${cols.map((c, ci) => td(r, c, ri, ci)).join('')}</tr>`).join('') || `<tr><td colspan=${cols.length + 1} style="height:120px;text-align:center;color:var(--mut)">No paper matches. <a href="#" data-clear>Clear the filters</a></td></tr>`}</tbody></table></div>
      <div class=pager><button class=btn data-pg=-1 ${S.page === 0 ? 'disabled' : ''}>Previous</button><span class=meta>Papers ${rows.length ? S.page * PS + 1 : 0}–${S.page * PS + pr.length} of ${fmt(rows.length)}</span><button class=btn data-pg=1 ${S.page >= pages - 1 ? 'disabled' : ''}>Next</button></div>`;
    const sc2 = $('.dgwrap'); if (sc2) sc2.scrollLeft = sl;
  }

  /* ---------- coverage view ---------- */
  const LORD = H.LAYERS.map(l => l[0]);
  const covWorks = M.coverage.works || [];
  const covRows = (M.coverage.miners || []).map(m => ({n: m.name, version: m.version, A: new Set(m.a.map(i => covWorks[i])), B: new Set(m.b.map(i => covWorks[i])), unread: m.unread}))
    .sort((a, b) => b.A.size - a.A.size || a.n.localeCompare(b.n));
  const CW = covWorks.map(id => byId.get(id)).filter(Boolean)
    .sort((a, b) => (LORD.indexOf(a.layer) - LORD.indexOf(b.layer)) || String(a.month).localeCompare(String(b.month)) || a.title.localeCompare(b.title));
  const covState = {r: 0, c: 0, geom: null};
  const covText = (m, w) => { const a = m.A.has(w.id), b = m.B.has(w.id); return {head: w.title, line: `${mname(m.n)}: ${b ? 'read, and checked by a second reading' : a ? 'read once' : 'not read'}`, meta: `${H.layerLabel(w.layer)} · month ${w.month}`}; };
  function leadCov() {
    const N = CW.length, near = covRows.filter(m => m.A.size >= 0.8 * N).length, none = (M.coverage.not_read_by_any || []).length;
    return `<b>${fmt(near)}</b> of the ${fmt(covRows.length)} ${term('miner', 'miners')} have read almost every paper. ${none ? `<b>${fmt(none)}</b> ${none === 1 ? 'paper has' : 'papers have'} not been read by any.` : 'Every paper has been read by at least one.'}`;
  }
  function announce() {
    const m = covRows[covState.r], w = CW[covState.c]; if (!m || !w) return;
    const t = covText(m, w);
    $('#covcap').innerHTML = `<b>${esc(t.head)}</b> <span class=meta>${esc(t.meta)}</span><br>${esc(t.line)}`;
    $('#covlive').textContent = `${t.line}. ${t.head}`;
  }
  function drawCov() {
    const host = view(), N = CW.length;
    host.innerHTML = `<canvas id=cov tabindex=0 role=application aria-label="Coverage map: ${covRows.length} miners by ${N} papers. Use the arrow keys to move between cells, Enter to open the paper. The table below holds the same counts."></canvas>
      <div class=covcap id=covcap>Hover or focus a cell to see the paper and whether the miner read it.</div><div id=covlive class=sr aria-live=polite style="position:absolute;left:-9999px"></div>
      <div class=dleg><span><i style="background:var(--seq-4)"></i>Read, and checked by a second reading</span><span><i style="background:var(--seq-2)"></i>Read once</span><span><i style="background:var(--hair)"></i>Not read</span></div>
      <table class=cvt><caption class=meta style="text-align:left;padding:0 0 6px">The same map as a table</caption><thead><tr><th>Miner</th><th class=n>Read</th><th class=n>Checked twice</th><th class=n>Not read</th><th></th></tr></thead>
      <tbody>${covRows.map((m, i) => `<tr><td>${esc(mname(m.n))}</td><td class=n>${fmt(m.A.size)}</td><td class=n>${fmt(m.B.size)}</td><td class=n>${fmt(N - m.A.size)}</td><td>${N - m.A.size ? `<button class=btn data-unread="${i}" aria-expanded=false>Show unread</button>` : ''}</td></tr><tr hidden data-ur="${i}"><td colspan=5></td></tr>`).join('')}</tbody></table>`;
    $('#lead').innerHTML = leadCov();
    paintCov();
    const c = $('#cov');
    c.onkeydown = e => {
      const mv = {ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], PageUp: [0, -20], PageDown: [0, 20], Home: [0, -1e9], End: [0, 1e9]}[e.key];
      if (mv) { e.preventDefault(); covState.r = Math.max(0, Math.min(covRows.length - 1, covState.r + mv[0])); covState.c = Math.max(0, Math.min(N - 1, covState.c + mv[1])); paintCov(); announce(); }
      else if (e.key === 'Enter') { e.preventDefault(); const w = CW[covState.c]; if (w) H.openDrawer(w.id); }
    };
    c.onfocus = () => { paintCov(); announce(); };
    c.onblur = () => paintCov();
    c.onmousemove = e => { const h = covHit(e); if (!h) { H.tip('', e); return; } c.style.cursor = 'pointer'; const t = covText(covRows[h.r], CW[h.c]); H.tip(`<b>${esc(t.head)}</b><div class=meta>${esc(t.meta)}</div><div>${esc(t.line)}</div>`, e); };
    c.onmouseleave = e => H.tip('', e);
    c.onclick = e => { const h = covHit(e); if (h) { covState.r = h.r; covState.c = h.c; paintCov(); announce(); H.openDrawer(CW[h.c].id); } };
  }
  function covHit(e) {
    const g = covState.geom; if (!g) return null;
    const r = $('#cov').getBoundingClientRect(), c = Math.floor((e.clientX - r.left - g.left) / g.cw), m = Math.floor((e.clientY - r.top - g.top) / g.rh);
    return c < 0 || c >= CW.length || m < 0 || m >= covRows.length ? null : {c, r: m};
  }
  function paintCov() {
    const cvs = $('#cov'); if (!cvs) return;
    const host = view(), W = host.clientWidth || 1000, left = W < 600 ? 120 : 236, right = W < 600 ? 60 : 130, top = 44, rh = 22, Hh = top + covRows.length * rh + 6, dpr = window.devicePixelRatio || 1;
    cvs.width = W * dpr; cvs.height = Hh * dpr; cvs.style.height = Hh + 'px';
    const g = cvs.getContext('2d'); g.scale(dpr, dpr);
    const css = n => H.cssv(n), cw = (W - left - right) / CW.length; covState.geom = {left, top, rh, cw};
    g.fillStyle = css('--surface'); g.fillRect(0, 0, W, Hh); g.font = '500 12px system-ui,sans-serif'; g.textBaseline = 'middle';
    let i = 0;
    while (i < CW.length) {
      let j = i; while (j < CW.length && CW[j].layer === CW[i].layer) j++;
      const x0 = left + i * cw, x1 = left + j * cw;
      g.fillStyle = H.layerColor(CW[i].layer); g.fillRect(x0, 28, x1 - x0 - 1, 6);
      g.fillStyle = css('--mut'); g.textAlign = 'left'; if (x1 - x0 > 60) g.fillText(H.layerLabel(CW[i].layer) + ' ' + (j - i), x0, 14);
      i = j;
    }
    g.fillStyle = css('--dim'); g.textAlign = 'right'; g.fillText('Papers, by layer and month', left - 10, 14);
    covRows.forEach((m, r) => {
      const y = top + r * rh; g.textAlign = 'right'; g.fillStyle = css('--fg'); g.font = '500 12px system-ui,sans-serif';
      let lab = mname(m.n); const maxw = left - 14; while (lab.length > 4 && g.measureText(lab).width > maxw) lab = lab.slice(0, -2) + '…';
      g.fillText(lab, left - 10, y + rh / 2);
      CW.forEach((w, c) => { g.fillStyle = m.B.has(w.id) ? css('--seq-4') : m.A.has(w.id) ? css('--seq-2') : css('--hair'); g.fillRect(left + c * cw, y + 2, Math.max(cw - (cw > 2.5 ? 0.6 : 0), 0.8), rh - 4); });
      g.textAlign = 'left'; g.fillStyle = css('--mut'); g.font = '400 12px monospace'; g.fillText(`${m.A.size} · B ${m.B.size}`, left + CW.length * cw + 8, y + rh / 2);
    });
    if (document.activeElement === cvs) {   /* the cell under keyboard focus */
      const x = left + covState.c * cw, y = top + covState.r * rh;
      g.strokeStyle = css('--acc'); g.lineWidth = 2; g.strokeRect(x - 2, y, Math.max(cw, 1) + 4, rh); g.strokeRect(left - 1, y - 1, W - left - right + 2, rh + 2);
    }
  }
  function showUnread(i, btn) {
    const row = main.querySelector(`tr[data-ur="${i}"]`), m = covRows[i];
    if (!row.hidden) { row.hidden = true; btn.setAttribute('aria-expanded', 'false'); btn.textContent = 'Show unread'; return; }
    const un = CW.filter(w => !m.A.has(w.id));
    row.firstElementChild.innerHTML = `<div class=unread><span class=meta>${fmt(un.length)} papers ${esc(mname(m.n))} has not read${un.length > 60 ? ' (first 60 shown)' : ''}</span><ul>${un.slice(0, 60).map(w => `<li><a href="#" data-open="${esc(w.id)}">${esc(w.title)}</a></li>`).join('')}</ul></div>`;
    row.hidden = false; btn.setAttribute('aria-expanded', 'true'); btn.textContent = 'Hide unread';
  }

  /* ---------- holes view ---------- */
  const holeRows = () => (M.holes.fields || []).filter(f => f.primary && f.read > 0).map(f => Object.assign({label: fname(f.field), tot: f.missing + f.undetermined}, f))
    .sort((a, b) => (b.tot / b.read - a.tot / a.read) || (b.tot - a.tot) || a.key.localeCompare(b.key));
  function drawHoles() {
    const all = holeRows(), thin = all.filter(f => f.tot > 0), top = thin[0], mx = Math.max(...all.map(f => f.read), 1);
    const near = all.filter(f => f.tot <= Math.max(3, 0.01 * f.read)).length;
    $('#lead').innerHTML = top ? `The thinnest field is <b>${esc(top.label)}</b> (${esc(mname(top.miner))}): ${fmt(top.tot)} of the ${fmt(top.read)} papers it read have no value or an undetermined one (${Math.round(100 * top.tot / top.read)}%). <b>${fmt(near)}</b> of the ${fmt(all.length)} coded fields are nearly complete.` : 'Every coded field has a usable value for every paper read.';
    const wk = M.holes.works || [];
    view().innerHTML = `<div class=dleg><span><i style="background:var(--exc)"></i>No value</span><span><i style="background:var(--dim)"></i>Not determinable, not stated, unclear or other</span></div>
      <div class=card style="padding:10px 8px">${thin.map(f => `<button class=hbar data-hole="${esc(f.key)}" aria-label="${esc(f.label)}: ${f.tot} papers with no usable value. Show them in the grid"><span class=lab>${esc(f.label)}<small>${esc(mname(f.miner))} · ${fmt(f.read)} read${f.required ? ' · required' : ''}</small></span><span class=trk><i style="width:${100 * f.missing / mx}%;background:var(--exc)"></i><i style="width:${100 * f.undetermined / mx}%;background:var(--dim)"></i></span><span class="num tnum">${fmt(f.tot)} <span class=meta>(${(100 * f.tot / f.read).toFixed(1)}%)</span></span></button>`).join('') || '<p class=meta style="padding:8px">No field has a gap.</p>'}</div>
      ${wk.length ? `<h3 class=h3 style="margin-top:22px">Papers missing most coded fields</h3><ul>${wk.map(w => `<li><a href="#" data-open="${esc(w.id)}">${esc((byId.get(w.id) || {}).title || w.title)}</a> <span class=meta>${fmt(w.missing.length)} empty · ${fmt(w.undetermined.length)} undetermined</span></li>`).join('')}</ul>` : ''}`;
  }

  /* ---------- controls and render ---------- */
  const loadingGrid = () => S.view === 'grid' && S.miner && (!G || G.miner !== S.miner);
  function render() {
    frame();
    const grid = S.view === 'grid';
    if (grid && !S.miner) { $('#lead').textContent = 'No miner has recorded values yet.'; return; }
    if (loadingGrid()) {
      $('#ctl').innerHTML = '';
      view().innerHTML = '<p class=meta role=status style="padding:24px 0">Loading the fields…</p>';
      const want = S.miner;
      loadGrid(want).then(g => { if (S.miner !== want) return; setGrid(g); applyHash(); render(); })
        .catch(e => { view().innerHTML = `<p class=meta>The fields could not be loaded: ${esc(e.message)}</p>`; });
      return;
    }
    const sel = `<select class=btn id=minerSel aria-label="Miner">${MAN.map(g => `<option value="${esc(g.miner)}" ${g.miner === S.miner ? 'selected' : ''}>${esc(mname(g.miner))} · ${fmt(g.works_read)} papers</option>`).join('')}</select>`;
    $('#ctl').innerHTML = (grid ? sel + `<div class=picker id=picker><button class=btn id=pickBtn aria-expanded=false></button><div class=panel id=panel>${[...new Set(COLS.map(c => c.group))].map(gp => `<h4>${esc(gp ? H.pretty(gp) : mname(S.miner))}</h4>${COLS.filter(c => c.group === gp).map(c => `<label><input type=checkbox data-col="${esc(c.k)}" ${S.hidden.has(c.k) ? '' : 'checked'}> ${esc(c.label)}</label>`).join('')}`).join('')}</div></div>` : '') + `<button class=btn id=csv>Download CSV</button>`;
    if (grid) drawGrid(); else if (S.view === 'coverage') drawCov(); else drawHoles();
  }
  function pickMiner(m, filters) {
    S.miner = m; S.minerMissing = false; S.hidden = new Set(); S.sort = null; S.filters = filters || []; S.page = 0; S.cur = {r: 0, c: 0}; hashPending = null;
    G = null; writeHash(); render();
  }

  main.addEventListener('click', e => {
    const t = e.target;
    const pb = t.closest('#pickBtn'); if (pb) { const p = $('#picker'); p.toggleAttribute('open'); pb.setAttribute('aria-expanded', p.hasAttribute('open')); return; }
    const op = t.closest('[data-open]'); if (op) { e.preventDefault(); H.openDrawer(op.dataset.open); return; }
    const rm = t.closest('[data-rm]'); if (rm) { S.filters.splice(+rm.dataset.rm, 1); S.page = 0; writeHash(); drawGrid(); return; }
    if (t.closest('[data-clear]')) { e.preventDefault(); S.filters = []; S.page = 0; writeHash(); drawGrid(); return; }
    const so = t.closest('[data-sort]'); if (so) { const k = so.dataset.sort; if (!S.sort || S.sort.col !== k) S.sort = {col: k, dir: 1}; else if (S.sort.dir === 1) S.sort.dir = -1; else S.sort = null; writeHash(); drawGrid(); return; }
    const pg = t.closest('[data-pg]'); if (pg) { S.page += +pg.dataset.pg; S.cur.r = 0; writeHash(); drawGrid(); $('.dgwrap').scrollTop = 0; return; }
    const hb = t.closest('[data-hole]'); if (hb) { S.view = 'grid'; pickMiner(hb.dataset.hole.split('.')[0], [{col: hb.dataset.hole, val: '__gap'}]); return; }
    const ub = t.closest('[data-unread]'); if (ub) { showUnread(+ub.dataset.unread, ub); return; }
    const c = t.closest('td[data-r]'); if (c) { const r = cur.page[+c.dataset.r], col = cur.cols[+c.dataset.c]; S.cur = {r: +c.dataset.r, c: +c.dataset.c}; if (col.type === 'quote') return; const v = cv(r, col); toggleFilter(col.k, v == null ? '__empty' : v); const n = document.querySelector(`td[data-r="${S.cur.r}"][data-c="${S.cur.c}"]`); if (n) n.focus({preventScroll: true}); return; }
    if (t.closest('#csv')) download();
  });
  main.addEventListener('change', e => {
    if (e.target.id === 'minerSel') { pickMiner(e.target.value); return; }
    const c = e.target.dataset.col; if (!c) return;
    if (e.target.checked) S.hidden.delete(c); else S.hidden.add(c);
    S.filters = S.filters.filter(f => !S.hidden.has(f.col)); if (S.sort && S.hidden.has(S.sort.col)) S.sort = null;
    writeHash(); drawGrid();
  });
  function cellTip(c) {
    const r = cur.page[+c.dataset.r], col = cur.cols[+c.dataset.c]; if (!r || !col) return '';
    const e = cell(r, col);
    return e ? `<b>${esc(vlab(col, e.v))}</b> <span class=meta>· ${esc(col.label)}</span>${e.n > 1 ? `<div class=meta style="margin-top:6px">${fmt(e.n)} values recorded for this paper</div>` + e.all.map(x => `<div>${esc(vlab(col, x))}</div>`).join('') : ''}${e.q ? `<div class=quote style="font-size:13px;margin:6px 0 0">“${esc(e.q)}”</div>` : '<div class=meta>No quotation recorded.</div>'}` : `<b>${esc(col.label)}</b><div class=meta>No value recorded for this paper.</div>`;
  }
  main.addEventListener('mouseover', e => {
    const c = e.target.closest('td[data-r]'); if (c) { H.tip(cellTip(c), e); return; }
    const d = e.target.closest('[data-dist]');
    if (d) { const col = COL[d.dataset.dist], dd = dist(cur.rows, col); H.tip(`<b>${esc(col.label)}</b><div class=meta>${fmt(dd.n)} papers in view</div>` + dd.top.slice(0, 6).map(t => `<div>${esc(vlab(col, t[0]))} <span class=num>${fmt(t[1])}</span></div>`).join('') + `<div class=meta>No value <span class=num>${fmt(dd.emp)}</span></div>`, e); return; }
    if (!e.target.closest('#cov')) H.tip('', e);
  });
  main.addEventListener('mousemove', e => {
    if (!e.target.closest('td[data-r],[data-dist]')) return;
    const t = $('#tip'); if (t.style.display === 'block') { t.style.left = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8) + 'px'; t.style.top = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8) + 'px'; }
  });
  main.addEventListener('mouseleave', e => H.tip('', e));
  main.addEventListener('focusin', e => {
    const c = e.target.closest('td[data-r]'); if (!c) return;
    S.cur = {r: +c.dataset.r, c: +c.dataset.c}; document.querySelectorAll('td[tabindex="0"]').forEach(x => x.tabIndex = -1); c.tabIndex = 0;
    const r = c.getBoundingClientRect(); H.tip(cellTip(c), {clientX: r.left + 10, clientY: r.bottom - 6});
  });
  main.addEventListener('focusout', e => { if (e.target.closest('td[data-r]')) H.tip('', e); });
  main.addEventListener('keydown', e => {
    const c = e.target.closest('td[data-r]'); if (!c) return;
    const r = +c.dataset.r, k = +c.dataset.c, mv = {ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1]}[e.key];
    if (mv) { e.preventDefault(); const n = document.querySelector(`td[data-r="${r + mv[0]}"][data-c="${k + mv[1]}"]`); if (n) n.focus(); }
    else if (e.key === 'Enter') { e.preventDefault(); const row = cur.page[r]; if (row) H.openDrawer(row.id); }
    else if (e.key === ' ') { e.preventDefault(); c.click(); }
    else if (e.key === 'Escape') H.tip('', e);
  });
  document.addEventListener('click', e => { const p = $('#picker'); if (p && p.hasAttribute('open') && !e.target.closest('#picker')) p.removeAttribute('open'); });
  const redraw = () => { if (S.view === 'coverage' && $('#cov')) paintCov(); };
  document.addEventListener('hub:theme', redraw);
  window.addEventListener('resize', redraw);

  /* ---------- CSV (client-side, the grid as filtered and with the columns shown) ---------- */
  const q = s => { s = String(s ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  function download() {
    let out, name;
    if (S.view === 'grid') {
      const rows = filtered(), cols = visCols();
      out = [['id', 'title', ...cols.flatMap(c => [c.label, c.label + ' evidence', c.label + ' all values'])], ...rows.map(r => [r.id, r.title, ...cols.flatMap(c => { const e = cell(r, c); return [e ? e.v : '', e ? e.q || '' : '', e && e.all ? e.all.join('; ') : '']; })])];
      name = 'extracted-data-grid.csv';
    } else if (S.view === 'coverage') {
      out = [['id', 'title', 'layer', 'month', ...covRows.map(m => mname(m.n))], ...CW.map(w => [w.id, w.title, w.layer, w.month, ...covRows.map(m => m.B.has(w.id) ? 'read and checked' : m.A.has(w.id) ? 'read' : '')])];
      name = 'extracted-data-coverage.csv';
    } else {
      out = [['field', 'miner', 'papers_read', 'no_value', 'undetermined', 'share_no_usable_value'], ...holeRows().map(f => [f.key, f.miner, f.read, f.missing, f.undetermined, f.tot / f.read])];
      name = 'extracted-data-holes.csv';
    }
    const b = new Blob([out.map(r => r.map(q).join(',')).join('\n')], {type: 'text/csv'}), a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 500);
  }
  render();
}).catch(e => {
  document.body.textContent = 'Extracted data failed to load: ' + e.message;
});
