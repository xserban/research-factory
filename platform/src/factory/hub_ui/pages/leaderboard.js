/* Leaderboard page. Payload: shell, leaderboard (services/hub_leaderboard.py). One entry per final row of the
   results miner; the page ranks them again over the rows whose source paper is in scope (HS-20, HS-22) with the
   same steps as `rank()` in the service. Row keys: w work, p published, t task, m model (named), mr model as
   extracted, mh how an own name was set, r role, d/s/x [as extracted, as merged] dataset/setting/metric,
   v value, vr value as extracted, g averaging, ac data access as stated, ap effective access, q quote, a anchor.
   Hash: task, metric, plus the scope.* keys. */
HUB.load(['shell', 'leaderboard']).then(d => {
  const H = HUB.init(d.shell);
  const L = d.leaderboard || {};
  const main = H.mount({ page: 'leaderboard', crumb: 'Leaderboard' });
  const { esc, fmt } = H;
  const SC = window.HUB_SCOPE;
  const ROWS = L.rows || [], WORKS = L.works || [], M = L.methods || {}, K = L.constants || {};
  const TITLES = L.titles || {};
  const VOC = L.vocabulary || {};

  if (!document.getElementById('lb-style')) {
    const st = document.createElement('style'); st.id = 'lb-style';
    st.textContent = `
.lb-sel{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:14px 0}
.lb-card{padding:16px 18px 10px;margin-top:var(--gap)}
.lb-card h3{margin:0 0 6px;font:500 var(--t-m) var(--f-ui)}
.lb-tbl{overflow-x:auto}
.lb-tbl td.r,.lb-tbl th.r{text-align:right}
.lb-val{all:unset;cursor:pointer;font:400 var(--t-s) var(--f-mono);color:var(--acc);border-bottom:1px dotted var(--acc)}
.lb-val:hover,.lb-val:focus-visible{color:var(--fg)}
.lb-q td{background:var(--raised);font:400 var(--t-s) var(--f-ui)}
.lb-q blockquote{margin:4px 0;color:var(--mut)}
.lb-dot{border-bottom:1px dotted var(--dim);cursor:help}
.lb-hidden{color:var(--exc);font:400 var(--t-s) var(--f-ui);margin:8px 0}
.lb-empty{color:var(--dim);font:400 var(--t-m) var(--f-ui);padding:30px 8px;text-align:center}
.lb-vocab{font:400 var(--t-xs) var(--f-ui);color:var(--mut);margin:4px 0}`;
    document.head.appendChild(st);
  }

  const st = { task: '', metric: '', open: new Set() };
  const readHash = () => { const p = HUB.hash.get(); st.task = p.get('task') || ''; st.metric = p.get('metric') || ''; };
  const writeHash = () => HUB.hash.set({ task: st.task, metric: st.metric });
  const panel = (what, how) => `<b>What it shows</b> ${what}<p><span class=k>How it’s computed.</span> ${esc(how)}</p>`;
  const num = v => (+v).toFixed(3);
  const paper = w => `<a href="#" data-open="${esc(w)}" title="${esc(TITLES[w] || w)}">${esc(String(w).replace(/^rf:/, '').split('-')[0])}</a>`;
  const tipped = (pair, label) => pair[0] !== pair[1]
    ? `<span class="lb-dot" title="${esc('as extracted: ' + (pair[0] || '(empty)') + ' → as merged: ' + pair[1])}">${esc(label || pair[1])}</span>`
    : esc(label || pair[1]);
  const modelCell = r => r.mh
    ? `<span class="lb-dot" title="${esc('as extracted: ' + r.mr + '. Named by rule: ' + (M.names || ''))}">${esc(r.m)}</span>`
    : esc(r.m);

  /* The same steps as hub_leaderboard.rank(): best per (model, paper), public only, at least K.min_models. */
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0); /* code-point order, as the service sorts */
  function rank(works) {
    const own = new Map(), base = new Map();
    let hb = 0, ho = 0;
    for (const r of ROWS) {
      if (works && !works.has(r.w)) { if (r.r === 'baseline') hb++; else if (r.r === 'own') ho++; continue; }
      if (r.ap !== 'public') continue;
      if (r.r === 'own') {
        const key = JSON.stringify([r.t, r.x[1], r.d[1], r.s[1]]);
        if (!own.has(key)) own.set(key, new Map());
        const slot = own.get(key), who = JSON.stringify([r.m, r.w]);
        if (!slot.has(who) || r.v > slot.get(who).v) slot.set(who, r);
      } else if (r.r === 'baseline') {
        const name = r.m.replace(/\s+/g, ' ').trim(), key = JSON.stringify([name, r.t, r.x[1], r.d[1], r.s[1]]);
        if (!base.has(key)) base.set(key, new Map());
        const slot = base.get(key);
        if (!slot.has(r.w) || r.v > slot.get(r.w).v) slot.set(r.w, r);
      }
    }
    const tables = [];
    for (const [key, slot] of own) {
      if (slot.size < K.min_models) continue;
      const [task, metric, dataset, setting] = JSON.parse(key);
      const top = [...slot.values()].sort((a, b) => b.v - a.v || cmp(a.m, b.m) || cmp(a.w, b.w));
      tables.push({ task, metric, dataset, setting, models: slot.size, top: top.slice(0, K.top) });
    }
    tables.sort((a, b) => cmp(a.task, b.task) || cmp(a.metric, b.metric) || b.models - a.models || cmp(a.dataset, b.dataset) || cmp(a.setting, b.setting));
    const baselines = [];
    for (const [key, slot] of base) {
      if (slot.size < K.min_papers) continue;
      const [model, task, metric, dataset, setting] = JSON.parse(key);
      const vs = [...slot.values()].map(r => r.v).sort((a, b) => a - b), n = vs.length;
      const median = n % 2 ? vs[(n - 1) / 2] : (vs[n / 2 - 1] + vs[n / 2]) / 2;
      baselines.push({ model, task, metric, dataset, setting, papers: n, median, min: vs[0], max: vs[n - 1] });
    }
    baselines.sort((a, b) => b.papers - a.papers || cmp(a.model, b.model) || cmp(a.task, b.task) || cmp(a.metric, b.metric) || cmp(a.dataset, b.dataset) || cmp(a.setting, b.setting));
    return { tables, baselines, hiddenBaseline: hb, hiddenOwn: ho };
  }

  function view() {
    const sc = SC ? SC.current() : {};
    const res = SC ? SC.apply(WORKS, w => w.published, sc, { includeUndated: SC.includeUndated() }) : null;
    const inSet = res ? new Set(res.inScope.map(w => w.id)) : null;
    const scoped = !!(SC && SC.active(sc));
    return { res, rk: rank(scoped ? inSet : null), scoped };
  }

  function evidence(r) {
    return `<tr class="lb-q"><td colspan="5"><blockquote class="quote">“${esc(r.q || 'No quote recorded.')}”</blockquote>` +
      `<span class="meta">${paper(r.w)} · as extracted: ${esc(r.vr)} · anchor ${esc(r.a || 'none')} · access ${esc(r.ac || 'not stated')}</span></td></tr>`;
  }

  function tableCard(t) {
    const rows = t.top.map((r, i) => {
      const id = `${t.task}|${t.metric}|${t.dataset}|${t.setting}|${r.m}|${r.w}`;
      return `<tr><td class="r">${i + 1}</td><td>${modelCell(r)}</td>` +
        `<td class="r"><button type="button" class="lb-val" data-ev="${esc(id)}" aria-expanded="${st.open.has(id)}">${num(r.v)}</button></td>` +
        `<td>${esc(r.g)}</td><td>${paper(r.w)}</td></tr>` + (st.open.has(id) ? evidence(r) : '');
    }).join('');
    const sample = ROWS.find(x => x.d[1] === t.dataset && x.s[1] === t.setting && x.x[1] === t.metric) || { d: [t.dataset, t.dataset], s: [t.setting, t.setting], x: [t.metric, t.metric] };
    return `<section class="card lb-card"><h3>${tipped(sample.d)} · ${tipped(sample.s)} · ${tipped(sample.x)}</h3>` +
      `<p class="meta">${esc(t.task)} · ${fmt(t.models)} models${t.models > t.top.length ? `, top ${fmt(t.top.length)} shown` : ''}</p>` +
      `<div class="lb-tbl"><table class="t"><thead><tr><th class="r">#</th><th>Model</th><th class="r">Value</th><th>Averaging</th><th>Paper</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }

  function render() {
    const { res, rk, scoped } = view();
    const tasks = [...new Set(rk.tables.map(t => t.task))], metrics = [...new Set(rk.tables.filter(t => !st.task || t.task === st.task).map(t => t.metric))];
    const tables = rk.tables.filter(t => (!st.task || t.task === st.task) && (!st.metric || t.metric === st.metric));
    const bases = rk.baselines.filter(b => (!st.task || b.task === st.task) && (!st.metric || b.metric === st.metric));
    const opt = (list, cur, all) => `<option value="">${all}</option>` + list.map(v => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(v)}</option>`).join('');
    const nRows = ROWS.length;
    const lead = !L.miner ? 'No results miner is registered in this project.'
      : !nRows ? 'The results miner has no usable row yet.'
      : `${fmt(tables.length)} tables rank own models; ${fmt(bases.length)} baselines were reported by several papers.`;
    const vocab = Object.entries(VOC).map(([k, v]) => `${k}: ${v.approved ? 'merged through ' + v.key : 'no approved property, shown as extracted'}`).join(' · ');
    const hidden = scoped ? `<p class="lb-hidden" id="lbHidden" role="status">${fmt(rk.hiddenBaseline)} baseline rows hidden (source paper out of scope)${rk.hiddenOwn ? `; ${fmt(rk.hiddenOwn)} own-model rows outside the scope` : ''}.</p>` : '';
    const body = !nRows ? `<div class="card lb-empty">No result rows to rank.</div>` : `
      <div class="lb-sel"><label class="meta">Task <select class="btn" id="lbTask" aria-label="Task">${opt(tasks, st.task, 'All tasks')}</select></label>
      <label class="meta">Metric <select class="btn" id="lbMetric" aria-label="Metric">${opt(metrics, st.metric, 'All metrics')}</select></label></div>
      ${hidden}
      <h2 class="h2">Own models ${H.info(panel('Per table, the best value of each own model and paper, public datasets only.', (M.part_a || '') + ' ' + (M.names || '')))}</h2>
      ${tables.length ? tables.map(t => tableCard(t)).join('') : `<div class="card lb-empty">${scoped ? 'No table has enough models in this scope.' : 'No table has enough models.'}</div>`}
      <h2 class="h2" style="margin-top:28px">Re-reported baselines ${H.info(panel('How often another paper reported the same baseline, and how far the numbers spread.', (M.part_b || '') + ' ' + (M.scope || '')))}</h2>
      ${bases.length ? `<section class="card lb-card"><div class="lb-tbl"><table class="t" id="lbBase"><thead><tr><th>Baseline</th><th>Data · setting · metric</th><th class="r">Papers</th><th class="r">Median</th><th class="r">Min</th><th class="r">Max</th></tr></thead><tbody>` +
        bases.map(b => `<tr><td>${esc(b.model)}</td><td>${esc(b.dataset)} · ${esc(b.setting)} · ${esc(b.metric)}</td><td class="r">${fmt(b.papers)}</td><td class="r">${num(b.median)}</td><td class="r">${num(b.min)}</td><td class="r">${num(b.max)}</td></tr>`).join('') +
        `</tbody></table></div></section>` : `<div class="card lb-empty">No baseline was reported by enough papers${scoped ? ' in this scope' : ''}.</div>`}`;
    main.innerHTML = H.header({ title: 'Leaderboard', sub: 'Reported results of the papers, ranked per table.', level: 1,
        infoHtml: panel('Result rows read from the papers by ' + (L.miner ? L.miner : 'a results miner') + ', ranked per dataset, setting and metric.', (M.source || '') + ' ' + (M.vocabulary || '') + ' ' + (M.access || '') + ' ' + (M.values || '')) }) +
      `<p class="lead" id="lbLead">${esc(lead)}</p><div id="lbLine"></div><p class="lb-vocab" id="lbVocab">${esc(vocab)}${L.skipped && L.skipped.value ? ' · ' + fmt(L.skipped.value) + ' rows without a usable value left out' : ''}</p>${body}`;
    if (SC) SC.renderLine(document.getElementById('lbLine'), res, {});
    wire();
  }
  function wire() {
    const t = document.getElementById('lbTask'), m = document.getElementById('lbMetric');
    if (t) t.onchange = () => { st.task = t.value; st.metric = ''; writeHash(); render(); };
    if (m) m.onchange = () => { st.metric = m.value; writeHash(); render(); };
    main.querySelectorAll('[data-ev]').forEach(b => b.onclick = () => { const k = b.dataset.ev; st.open.has(k) ? st.open.delete(k) : st.open.add(k); render(); });
    main.querySelectorAll('[data-open]').forEach(a => a.onclick = e => { e.preventDefault(); H.openDrawer(a.dataset.open); });
  }
  readHash(); render();
  if (SC) SC.onChange(render);
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
