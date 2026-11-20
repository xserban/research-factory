/* Costs & runs page. Payload: shell, costs (services/hub_costs.py). Every number comes from the payload.
   Tabs: Costs (run costs, budgets, events per model) and Runs (the files under ops/). Hash: tab, run, view, kind. */
HUB.load(['shell', 'costs']).then(d => {
  const H = HUB.init(d.shell);
  const C = d.costs || {};
  const main = H.mount({ page: 'costs', crumb: 'Costs & runs' });
  const { esc, fmt } = H;
  const M = C.methods || {};
  const S = C.summary || {};
  const GROUPS = C.groups || [], RUNS = C.runs || [], OT = C.over_time || { days: [], by_stage: {}, by_model: {} };
  const GROWTH = C.growth || {}, BUD = C.budgets || { lines: [], reported_usage: {}, notice: null };
  const EVM = C.events_per_model || [], OPS = C.ops || { groups: [], files: 0, unlinked: 0, file_cap: 0 };

  if (!document.getElementById('co-style')) {
    const st = document.createElement('style'); st.id = 'co-style';
    st.textContent = `
.co-tabs{margin:22px 0 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.co-kpis{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0 8px}
.co-kpi{background:var(--surface);border-radius:var(--r);padding:12px 16px;min-width:150px}
.co-kpi b{display:block;font:500 var(--t-l) var(--f-mono);color:var(--fg)}
.co-kpi span{font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.co-card{padding:18px 18px 12px;margin-top:var(--gap)}
.co-svg{display:block;width:100%;height:auto}
.co-svg text{fill:var(--mut);font:400 11px var(--f-ui)}
.co-svg .v{fill:var(--fg);font-family:var(--f-mono)}
.co-legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 4px;font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.co-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.co-row{display:grid;grid-template-columns:minmax(120px,260px) minmax(0,1fr) 90px;gap:12px;align-items:center;padding:5px 0;font:400 var(--t-s) var(--f-ui)}
.co-row .tr{height:12px;background:var(--raised);border-radius:2px;position:relative}
.co-row .tr i{position:absolute;left:0;top:0;bottom:0;border-radius:2px;background:var(--acc)}
.co-row .tr i.dot{width:10px;height:10px;top:1px;border-radius:50%;transform:translateX(-5px)}
.co-row .v{text-align:right;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.co-row .nm{overflow-wrap:anywhere}
.co-tbl{overflow-x:auto}
.co-tbl th button{all:unset;cursor:pointer;color:inherit}
.co-tbl th button:hover,.co-tbl th button:focus-visible{color:var(--fg);text-decoration:underline}
.co-tbl tr.hit{background:var(--acc-soft)}
.co-tbl tbody tr{cursor:default}
.co-grow{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.co-grow h4{margin:0 0 4px;font:500 var(--t-s) var(--f-ui)}
.co-st-link{color:var(--acc)}.co-st-unlinked{color:var(--exc)}
.co-files{margin:6px 0 2px;padding-left:18px;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.co-files li{margin:1px 0;overflow-wrap:anywhere}
.co-gauge{height:10px;background:var(--raised);border-radius:5px;overflow:hidden}.co-gauge i{display:block;height:100%;background:var(--acc)}
.co-gauge.full i{background:var(--exc)}
.co-empty{color:var(--dim);font:400 var(--t-m) var(--f-ui);padding:30px 8px;text-align:center}
.co-sel{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
@media (max-width:760px){.co-row{grid-template-columns:minmax(0,1fr) 70px}.co-row .tr{grid-column:1/-1;order:3}}`;
    document.head.appendChild(st);
  }

  const panel = (what, read, how) => `<b>What it shows</b> ${what}${read ? `<p><span class=k>How to read it.</span> ${read}</p>` : ''}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const empty = msg => `<div class="card co-empty">${esc(msg)}</div>`;
  const usd = v => v == null ? '–' : '$' + (Math.abs(v) >= 100 ? fmt(Math.round(v)) : v.toFixed(Math.abs(v) < 1 ? 4 : 2));
  const num = (v, dg = 0) => v == null ? '–' : v.toLocaleString('en', { maximumFractionDigits: dg });
  const SER = ['--acc', '--h-review', '--h-feedback', '--h-collab', '--h-physical', '--h-none', '--l-adjacent', '--h-goal'];
  const col = i => `var(${SER[i % SER.length]})`;
  const gname = g => g.stage + ' · ' + g.model + (g.miner ? ' · ' + g.miner : '');
  const kpi = (v, l, info) => `<div class="co-kpi"><b>${v}</b><span>${esc(l)}${info ? ' ' + H.info(info) : ''}</span></div>`;
  const hist = d => d.slice(5);

  const TABS = [['costs', 'Costs'], ['runs', 'Runs']];
  const st = { tab: 'costs', view: 'stage', kind: 'input', run: null, sort: 'cost', dir: -1, allRuns: false, folder: 'all', link: 'all' };
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'costs';
    st.view = p.get('view') === 'model' ? 'model' : 'stage';
    st.kind = ['input', 'output', 'cache_read', 'cache_write'].includes(p.get('kind')) ? p.get('kind') : 'input';
    st.run = p.get('run') || null;
  };
  const writeHash = () => H.hash.set({ tab: st.tab === 'costs' ? null : st.tab, view: st.view === 'stage' ? null : st.view, kind: st.kind === 'input' ? null : st.kind, run: st.run });

  /* ---------- stacked area: reported cost per day, by stage or model ---------- */
  function areaChart() {
    const days = OT.days, series = st.view === 'model' ? OT.by_model : OT.by_stage, names = Object.keys(series);
    if (!days.length) return empty('Costs appear here once runs report them.');
    const W = 860, Hh = 260, L = 56, R = 12, T = 12, B = 26, n = days.length;
    const tot = days.map((_, i) => names.reduce((a, k) => a + series[k][i], 0)), max = Math.max(...tot, 1e-9);
    const x = i => L + (n === 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1)), y = v => T + (Hh - T - B) * (1 - v / max);
    const base = days.map(() => 0);
    let paths = '';
    names.forEach((k, si) => {
      const top = days.map((_, i) => base[i] + series[k][i]);
      if (n === 1) {
        const w = 30; paths += `<rect x="${x(0) - w / 2}" y="${y(top[0])}" width="${w}" height="${Math.max(y(base[0]) - y(top[0]), 0)}" fill="${col(si)}"><title>${esc(k)}: ${usd(series[k][0])}</title></rect>`;
      } else {
        const up = top.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`), dn = base.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).reverse();
        paths += `<path d="M${up.join('L')}L${dn.join('L')}Z" fill="${col(si)}" fill-opacity=".85"><title>${esc(k)}: ${usd(series[k].reduce((a, b) => a + b, 0))} in total</title></path>`;
      }
      top.forEach((v, i) => { base[i] = v; });
    });
    const grid = [0, .5, 1].map(f => `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="var(--hair)"/><text x="${L - 6}" y="${y(max * f) + 4}" text-anchor="end">${usd(max * f)}</text>`).join('');
    const ticks = days.map((dd, i) => (n <= 8 || i % Math.ceil(n / 8) === 0) ? `<text x="${x(i)}" y="${Hh - 8}" text-anchor="middle">${esc(hist(dd))}</text>` : '').join('');
    const legend = names.map((k, i) => `<span><i style="background:${col(i)}"></i>${esc(k)}</span>`).join('');
    return `<svg class="co-svg" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Reported cost per day, stacked by ${st.view}">${grid}${paths}${ticks}</svg><div class="co-legend">${legend}</div>`;
  }

  /* ---------- ranked bars: cost by stage, model and miner ---------- */
  function costBars() {
    const rows = GROUPS.filter(g => g.cost != null).sort((a, b) => b.cost - a.cost);
    if (!rows.length) return empty('No run has reported a cost yet.');
    const max = rows[0].cost || 1;
    return rows.map(g => `<div class="co-row"><span class="nm">${esc(gname(g))}</span><span class="tr"><i style="width:${(100 * g.cost / max).toFixed(1)}%"></i></span><span class="v">${usd(g.cost)}</span></div>`).join('');
  }

  /* ---------- dot plot: tokens per unit, per group ---------- */
  const KINDS = [['input', 'Input'], ['output', 'Output'], ['cache_read', 'Cache read'], ['cache_write', 'Cache write']];
  function dotPlot() {
    const rows = GROUPS.filter(g => g.per_unit && g.per_unit[st.kind] != null);
    if (!rows.length) return empty('No group has served units yet.');
    const max = Math.max(...rows.map(g => g.per_unit[st.kind]), 1);
    const sel = '<div class="co-sel seg" role="group" aria-label="Token kind">' + KINDS.map(([k, l]) => `<button type="button" data-kind="${k}" aria-pressed="${st.kind === k}">${l}</button>`).join('') + '</div>';
    return sel + [...rows].sort((a, b) => b.per_unit[st.kind] - a.per_unit[st.kind]).map(g => `<div class="co-row"><span class="nm">${esc(gname(g))}</span><span class="tr"><i class="dot" style="left:${(100 * g.per_unit[st.kind] / max).toFixed(1)}%;background:var(--acc)"></i></span><span class="v">${num(g.per_unit[st.kind])}</span></div>`).join('');
  }

  /* ---------- table per stage, model and miner (sortable) ---------- */
  const COLS = [
    ['stage', 'Stage', g => g.stage, 'l'], ['model', 'Model', g => g.model, 'l'], ['miner', 'Miner', g => g.miner || '', 'l'],
    ['runs', 'Runs', g => g.runs], ['complete_runs', 'Complete', g => g.complete_runs], ['units', 'Units', g => g.units],
    ['cost', 'Reported cost', g => g.cost, 'u'], ['cost_per_unit', 'Per unit', g => g.cost_per_unit, 'u'],
    ['median_turns', 'Median turns', g => g.median_turns, 'f'], ['median_duration_s', 'Median seconds', g => g.median_duration_s, 'f'],
    ['input', 'Input / unit', g => g.per_unit.input], ['output', 'Output / unit', g => g.per_unit.output],
    ['cache_read', 'Cache read / unit', g => g.per_unit.cache_read], ['cache_write', 'Cache write / unit', g => g.per_unit.cache_write],
  ];
  function groupTable() {
    if (!GROUPS.length) return empty('No headless run is recorded for this project yet.');
    const c = COLS.find(x => x[0] === st.sort) || COLS[6];
    const rows = [...GROUPS].sort((a, b) => {
      const va = c[2](a), vb = c[2](b);
      if (va == null && vb == null) return 0; if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * st.dir;
    });
    const cell = (c, g) => { const v = c[2](g); return c[3] === 'l' ? `<td>${esc(v || '–')}</td>` : `<td class="r">${c[3] === 'u' ? usd(v) : num(v, c[3] === 'f' ? 1 : 0)}</td>`; };
    const head = COLS.map(c => `<th class="${c[3] === 'l' ? '' : 'r'}" aria-sort="${st.sort === c[0] ? (st.dir > 0 ? 'ascending' : 'descending') : 'none'}"><button type="button" data-sort="${c[0]}">${esc(c[1])}</button></th>`).join('');
    return `<div class="co-tbl"><table class="t"><thead><tr>${head}</tr></thead><tbody>${rows.map(g => '<tr>' + COLS.map(c => cell(c, g)).join('') + '</tr>').join('')}</tbody></table></div>`;
  }

  /* ---------- token growth: one small line chart per stage ---------- */
  function growthCharts() {
    const stages = Object.keys(GROWTH);
    if (!stages.length) return empty('No run log with turns is recorded yet.');
    return '<div class="co-grow">' + stages.map((s, si) => {
      const pts = GROWTH[s], W = 300, Hh = 140, L = 44, R = 8, T = 8, B = 22;
      const mx = Math.max(...pts.map(p => p.mean), 1), nt = Math.max(pts[pts.length - 1].turn, 2);
      const x = t => L + (W - L - R) * (t - 1) / (nt - 1), y = v => T + (Hh - T - B) * (1 - v / mx);
      const line = pts.map(p => `${x(p.turn).toFixed(1)},${y(p.mean).toFixed(1)}`).join('L');
      return `<div><h4>${esc(s)}</h4><svg class="co-svg" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Token growth, ${esc(s)}"><line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--hair)"/><text x="${L - 4}" y="${y(mx) + 4}" text-anchor="end">${num(mx)}</text><text x="${L - 4}" y="${y(0) + 4}" text-anchor="end">0</text><path d="M${line}" fill="none" stroke="${col(si)}" stroke-width="2"/><text x="${L}" y="${Hh - 6}">turn 1</text><text x="${W - R}" y="${Hh - 6}" text-anchor="end">turn ${nt}</text></svg></div>`;
    }).join('') + '</div>';
  }

  /* ---------- budgets, reported usage, events per model ---------- */
  function budgets() {
    const lines = BUD.lines || [], ru = Object.entries(BUD.reported_usage || {});
    let h = '';
    h += lines.length ? '<table class="t"><thead><tr><th>Unit</th><th>Scope</th><th>Period</th><th class="r">Limit</th><th class="r">Consumed</th><th class="r">Remaining</th><th>Used</th></tr></thead><tbody>' + lines.map(l => `<tr><td>${esc(l.unit)}</td><td>${esc(l.scope)}</td><td>${esc(l.period)}</td><td class="r">${num(l.limit)}</td><td class="r">${num(l.consumed)}</td><td class="r">${num(l.remaining)}</td><td style="min-width:120px"><div class="co-gauge${l.share != null && l.share >= 1 ? ' full' : ''}"><i style="width:${Math.min(100, 100 * (l.share || 0)).toFixed(1)}%"></i></div></td></tr>`).join('') + '</tbody></table>'
      : `<p class="meta">${esc(BUD.notice || 'No budget is set.')}</p>`;
    if (ru.length) h += '<p class="meta" style="margin-top:12px">Reported by agents, never enforced</p><table class="t"><tbody>' + ru.map(([k, v]) => `<tr><td>${esc(H.pretty(k))}</td><td class="r">${num(v, 2)}</td></tr>`).join('') + '</tbody></table>';
    return h;
  }
  function eventBars() {
    if (!EVM.length) return empty('No agent event is recorded yet.');
    const max = Math.max(...EVM.map(m => m.events), 1);
    return EVM.map(m => `<div class="co-row"><span class="nm">${esc(m.model)}</span><span class="tr"><i style="width:${(100 * m.events / max).toFixed(1)}%"></i></span><span class="v">${fmt(m.events)}</span></div>`).join('');
  }

  /* ---------- runs list (cross-link target of the Runs tab) ---------- */
  function runList() {
    if (!RUNS.length) return '';
    const rows = [...RUNS].sort((a, b) => (b.day + b.run_id).localeCompare(a.day + a.run_id));
    const shown = st.allRuns || st.run ? rows : rows.slice(0, 25);
    const body = shown.map(r => `<tr id="run-${esc(r.run_id)}" class="${r.run_id === st.run ? 'hit' : ''}"><td class="mono">${esc(r.run_id)}</td><td>${esc(r.day)}</td><td>${esc(r.stage)}</td><td>${esc(r.model)}${r.miner ? ' · ' + esc(r.miner) : ''}</td><td class="r">${num(r.units)}</td><td class="r">${usd(r.cost)}</td><td>${esc(r.outcome || (r.complete ? '' : 'no result line'))}</td></tr>`).join('');
    return `<div class="co-tbl"><table class="t"><thead><tr><th>Run</th><th>Day</th><th>Stage</th><th>Model</th><th class="r">Units</th><th class="r">Reported cost</th><th>Outcome</th></tr></thead><tbody>${body}</tbody></table></div>` +
      (shown.length < rows.length ? `<p><button type="button" class="btn" data-allruns>Show all ${fmt(rows.length)} runs</button></p>` : '');
  }

  const sect = (title, info, body, key) => `<section class="card co-card">${H.header({ title, infoHtml: info })}${body}</section>`;

  function costsTab() {
    if (!GROUPS.length && !RUNS.length) {
      return empty('No headless run is recorded for this project yet.') + sect('Budgets', panel('The budgets in force and what has been used of each.', '', M.budgets), budgets()) + sect('Events per model', panel('How many events each model wrote. Events are not cost.', '', M.events), eventBars());
    }
    const over = '<div class="co-sel seg" role="group" aria-label="Stack by">' + [['stage', 'By stage'], ['model', 'By model']].map(([k, l]) => `<button type="button" data-view="${k}" aria-pressed="${st.view === k}">${l}</button>`).join('') + '</div>';
    return `<div class="co-kpis">${kpi(fmt(S.runs), 'runs')}${kpi(fmt(S.units), 'units served', M.summary && panel('How many records or tasks the runs served.', '', M.summary))}${kpi(usd(S.cost), 'reported cost', panel('What the CLI reported for the runs, as the API-equivalent price.', esc(S.caveat || ''), M.summary))}</div>` +
      `<p class="meta">${esc(S.caveat || '')}</p>` +
      sect('Cost over time', panel('Reported cost per day.', 'Each band is a stage or model; the height is the total of that day.', M.over_time), over + areaChart()) +
      sect('Where the cost went', panel('Reported cost by stage, model and miner.', 'Longest bar first.', M.treemap), costBars()) +
      sect('Tokens per unit', panel('How many tokens a unit of work took, per stage, model and miner.', 'A dot further right is a heavier unit.', M.dots), dotPlot()) +
      sect('Stages in detail', panel('One row per stage, model and miner.', 'Click a column name to sort. A dash means the figure does not exist for that group.', M.groups), groupTable()) +
      sect('Token growth', panel('How the context grows as a run goes on.', 'A rising line is the transcript being re-read each turn.', M.growth), growthCharts()) +
      sect('Runs', panel('Each run with its reported cost.', 'A run linked from the Runs tab is highlighted.', M.summary), runList()) +
      sect('Budgets', panel('The budgets in force and what has been used of each.', 'The bar is consumed over limit.', M.budgets), budgets()) +
      sect('Events per model', panel('How many events each model wrote.', 'Events are not cost.', M.events), eventBars());
  }

  /* ---------- Runs tab: files under ops/ ---------- */
  const size = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' kB' : (n / 1048576).toFixed(1) + ' MB';
  function runsTab() {
    if (!OPS.groups.length) return empty('There is no ops/ folder, or it holds no file.');
    const folders = [...new Set(OPS.groups.map(g => g.folder))].sort();
    const chip = (k, v, l, n) => `<button type="button" class="chip" data-${k}="${esc(v)}" aria-pressed="${st[k] === v}">${esc(l)}${n != null ? ` <span class="n">${fmt(n)}</span>` : ''}</button>`;
    const shown = OPS.groups.filter(g => (st.folder === 'all' || g.folder === st.folder) && (st.link === 'all' || (st.link === 'linked') === g.linked));
    const rows = shown.map(g => {
      const link = g.linked ? `<span class="co-st-link">linked</span> ` + g.ids.slice(0, 3).map(i => g.run_ids.includes(i) ? `<a href="#" data-run="${esc(i)}" class="mono">${esc(i)}</a>` : `<span class="mono">${esc(i)}</span>`).join(', ') : '<span class="co-st-unlinked">unlinked</span>';
      const fileLink = f => HUB.served ? `<a href="ops/${f.path.split('/').map(encodeURIComponent).join('/')}" target="_blank" rel="noopener">${esc(f.path)}</a>` : esc(f.path);
      const list = g.listed.map(f => `<li>${fileLink(f)} <span class="meta">${esc(f.day)}, ${size(f.size)}</span></li>`).join('');
      const more = g.files > g.listed.length ? `<li class="meta">and ${fmt(g.files - g.listed.length)} more</li>` : '';
      return `<tr><td>${esc(g.folder)}</td><td>${esc(g.prefix)}</td><td class="r">${fmt(g.files)}</td><td>${esc(g.first === g.last ? g.first : g.first + ' to ' + g.last)}</td><td class="r">${size(g.size)}</td><td>${link}</td><td><details><summary>Files</summary><ul class="co-files">${list}${more}</ul></details></td></tr>`;
    }).join('');
    return `<div class="co-kpis">${kpi(fmt(OPS.files), 'files', panel('The files under the ops/ folder, which are not events.', '', M.runs))}${kpi(fmt(OPS.groups.length), 'groups')}${kpi(fmt(OPS.unlinked), 'unlinked groups', panel('Groups with no run or task id in a file name that an event names.', '', M.runs))}</div>` +
      `<div class="co-sel"><span class="meta">Folder</span>${chip('folder', 'all', 'All')}${folders.map(f => chip('folder', f, f)).join('')}<span class="meta" style="margin-left:12px">Status</span>${chip('link', 'all', 'All')}${chip('link', 'unlinked', 'Unlinked')}${chip('link', 'linked', 'Linked')}</div>` +
      `<section class="card co-card"><div class="co-tbl"><table class="t"><thead><tr><th>Folder</th><th>Batch</th><th class="r">Files</th><th>Modified</th><th class="r">Size</th><th>Linked to a run</th><th>Files</th></tr></thead><tbody>${rows}</tbody></table></div>` +
      `<p class="meta">${HUB.served ? 'A file opens as plain text.' : 'Files open only when the hub is served.'} ${H.info('Files open through a read-only route restricted to the ops/ folder of the project (no links out of it, size capped). The folder is not part of the published project, so this page is not meant to be copied or published as is.')}</p></section>`;
  }

  /* ---------- render ---------- */
  function render() {
    const lead = S.runs ? `${fmt(S.runs)} runs served ${fmt(S.units)} units for ${usd(S.cost)} reported.` : 'No headless run is recorded yet.';
    const tabs = '<div class="seg" role="tablist" aria-label="Costs and runs">' + TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${st.tab === k}" aria-pressed="${st.tab === k}">${l}</button>`).join('') + '</div>';
    main.innerHTML = H.header({ title: 'Costs & runs', sub: 'What the work cost and which runs produced it.', level: 1, infoHtml: (M.tab_cost ? M.tab_cost + '<br><br>' : '') + panel('The headless runs of the project, their reported cost, and the files they left.', '', M.summary) }) +
      `<p class="lead co-lead">${esc(lead)}</p><div class="co-tabs">${tabs}</div>` + (st.tab === 'costs' ? costsTab() : runsTab());
    wire();
    if (st.run) { const el = document.getElementById('run-' + st.run); if (el) el.scrollIntoView({ block: 'center' }); }
  }
  function wire() {
    const on = (sel, fn) => main.querySelectorAll(sel).forEach(el => { el.onclick = e => { e.preventDefault(); fn(el); }; });
    on('[data-tab]', el => { st.tab = el.dataset.tab; st.run = null; writeHash(); render(); });
    on('[data-view]', el => { st.view = el.dataset.view; writeHash(); render(); });
    on('[data-kind]', el => { st.kind = el.dataset.kind; writeHash(); render(); });
    on('[data-sort]', el => { st.dir = st.sort === el.dataset.sort ? -st.dir : (el.dataset.sort.match(/^(stage|model|miner)$/) ? 1 : -1); st.sort = el.dataset.sort; render(); });
    on('[data-allruns]', () => { st.allRuns = true; render(); });
    on('[data-folder]', el => { st.folder = el.dataset.folder; render(); });
    on('[data-link]', el => { st.link = el.dataset.link; render(); });
    on('[data-run]', el => { st.tab = 'costs'; st.run = el.dataset.run; writeHash(); render(); });
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
