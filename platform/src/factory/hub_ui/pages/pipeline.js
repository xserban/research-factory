/* Pipeline page: Control room, Work queue and Activity. Payloads: shell (papers for the drawer) and pipeline
   (services/hub_pipeline.py). Every number comes from the payloads or from the live routes the old hub used
   (GET /api/activity, /api/queue/runs, /api/queue/interrupted). Acts (Process all, per-stage run, Preview, Resume)
   post to the existing /api/queue/process and /api/queue/resume routes, only when the hub is served, only on a click
   and only after an inline confirmation (Preview writes nothing and needs none). */
HUB.load(['shell', 'pipeline']).then(d => {
  const H = HUB.init(d.shell);
  const D = d.pipeline || {};
  const main = H.mount({ page: 'pipeline', crumb: 'Pipeline' });
  const { esc, fmt } = H;
  const M = D.methods || {};
  const ok = x => x && !x.error;
  const STATUS = ok(D.status) ? D.status : {};
  const STATIONS = ok(D.stations) ? D.stations : [];
  const HEART = Array.isArray(D.heartbeat) ? D.heartbeat : [];
  const STAGES = D.stages || [];
  const CAP = D.unit_cap || { default: 25, max: 200 };
  const Q = ok(D.queue) ? D.queue : { items: [], pending: {}, columns: [], progress: {}, stage_counts: {}, by_stage: {} };
  const live = { runs: ok(D.runs) ? D.runs : { runs: [], pipelines: [] }, intr: ok(D.interrupted) ? D.interrupted : null,
    act: ok(D.activity) ? D.activity : null, scr: null, status: null, actAt: null, actErr: false, resume: null, busy: false };
  live.busy = !!(live.runs.run_open || live.runs.pipeline_open);

  if (!document.getElementById('pl-style')) {
    const st = document.createElement('style'); st.id = 'pl-style';
    st.textContent = `
.pl-tabs{margin:18px 0 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.pl-lead{max-width:46ch;margin:14px 0 0}
.pl-sec{margin-top:28px}
.pl-strip{display:flex;flex-wrap:wrap;gap:8px 22px;margin:14px 0 0;font:400 var(--t-s) var(--f-ui);color:var(--mut)}
.pl-strip b{font:500 var(--t-s) var(--f-mono);color:var(--fg)}
.pl-line{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding:6px 2px 10px}
.pl-st{flex:1 0 118px;display:block;padding:14px;border-radius:var(--r);background:var(--surface);color:var(--fg);text-decoration:none;position:relative}
.pl-st:hover{background:var(--raised)}
.pl-st .k{font:500 var(--t-xs) var(--f-ui);color:var(--mut);letter-spacing:.04em;text-transform:uppercase}
.pl-st .v{font:500 26px/1.2 var(--f-mono);margin:4px 0 2px}
.pl-st .s{font-size:var(--t-xs);color:var(--dim)}
.pl-st .w{margin-top:8px;font-size:var(--t-xs);color:var(--acc)}
.pl-st .q{margin-top:6px;height:4px;border-radius:2px;background:var(--raised);overflow:hidden}.pl-st .q i{display:block;height:100%;background:var(--acc)}
.pl-st:hover .q{background:var(--line)}
.pl-arr{flex:0 0 34px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--dim);font:400 var(--t-xs) var(--f-mono)}
.pl-arr svg{width:22px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6}
.pl-pages{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:var(--gap)}
.pl-pages a{display:block;text-decoration:none;color:var(--fg)}
.pl-pages .card{height:100%;padding:14px 16px}.pl-pages .card:hover{background:var(--raised)}
.pl-pages .nm{font-weight:600}.pl-pages .bl{color:var(--mut);font-size:var(--t-s);margin-top:2px}
.pl-beat{display:block;width:100%;height:auto}
.pl-beat rect{fill:var(--acc)}.pl-beat rect:hover{opacity:.75}
.pl-act{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:var(--gap)}
.pl-act .card{padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.pl-act .nm{font-weight:600}.pl-act .host{min-height:22px}
.pl-cap{display:inline-flex;gap:6px;align-items:center;font-size:var(--t-s);color:var(--mut)}
.pl-cap input{width:72px;font:400 var(--t-s) var(--f-mono)}
.pl-run{margin:0 0 14px;padding:10px 14px;border-radius:var(--r);background:var(--surface);display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.pl-run .dot.busy{background:var(--acc);animation:pl-pulse 1.4s ease-in-out infinite}
@keyframes pl-pulse{50%{opacity:.35}}
.pl-bars{display:grid;gap:8px}
.pl-bar{display:grid;grid-template-columns:150px minmax(0,1fr) auto;gap:12px;align-items:center;font-size:var(--t-s)}
.pl-bar .tr{height:10px;border-radius:5px;background:var(--raised);overflow:hidden;display:flex}
.pl-bar .tr i{display:block;height:100%}
.s-done{background:var(--inc)}.s-pending{background:var(--mut);opacity:.55}.s-na{background:var(--line)}.s-stopped{background:var(--exc)}
.pl-lg{display:flex;flex-wrap:wrap;gap:14px;margin:8px 0 0;font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.pl-lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.pl-filt{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}
.pl-filt input[type=search]{min-width:200px}
.pl-grid{overflow-x:auto}
.pl-grid td,.pl-grid th{vertical-align:top}
.pl-grid .ttl{max-width:420px}.pl-grid .ttl a,.pl-grid .ttl button{color:var(--fg);text-decoration:none;background:none;border:0;padding:0;font:inherit;text-align:left;cursor:pointer}
.pl-grid .ttl a:hover,.pl-grid .ttl button:hover{color:var(--acc);text-decoration:underline}
.pl-grid tbody tr{cursor:default}
.cell{display:inline-block;min-width:22px;text-align:center;font:500 var(--t-xs) var(--f-mono);padding:2px 6px;border-radius:4px;background:var(--raised);color:var(--dim)}
.cell.done{color:var(--inc)}.cell.pending{color:var(--fg)}.cell.stopped{color:var(--exc);background:var(--exc-soft)}
.pl-badge{font:500 var(--t-xs) var(--f-ui);padding:2px 7px;border-radius:999px;background:var(--raised);color:var(--mut);white-space:nowrap}
.pl-badge.stopped{color:var(--exc);background:var(--exc-soft)}.pl-badge.extracted{color:var(--acc);background:var(--acc-soft)}
.pl-lines{margin:6px 0;padding-left:18px}.pl-lines li{margin:3px 0}
.pl-lines li.limit{color:var(--fg)}
.pl-out{white-space:pre-wrap;margin:10px 0 0;font:400 var(--t-s) var(--f-mono);color:var(--mut)}
.pl-out.err{color:var(--exc)}
.pl-bad{color:var(--exc)}.pl-warn{color:var(--l-core)}
.pl-pass{padding:12px 0;border-top:1px solid var(--hair)}.pl-pass:first-child{border-top:0}
.pl-pass .hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.pl-pass .nm{font-weight:600}
.pl-pass .tr{height:12px;margin:8px 0 6px;border-radius:6px;background:var(--raised);overflow:hidden;position:relative}
.pl-pass .tr i{display:block;height:100%;background:var(--acc)}.pl-pass .tr i.h{position:absolute;top:0;background:var(--l-core);opacity:.8}
.pl-pass .ft{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:var(--t-s);color:var(--mut)}
.pl-pass .ft b{font:500 var(--t-s) var(--f-mono);color:var(--fg)}
.pl-tiles{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}
.pl-tile{padding:10px 14px;border-radius:var(--r);background:var(--raised);min-width:120px}
.pl-tile .v{font:500 20px var(--f-mono)}.pl-tile .k{font-size:var(--t-xs);color:var(--mut)}
.pl-mono{font:400 var(--t-xs) var(--f-mono);color:var(--mut);word-break:break-all}
.pl-note{color:var(--mut);font-size:var(--t-s)}
@media (max-width:760px){.pl-bar{grid-template-columns:100px minmax(0,1fr)}.pl-bar>:last-child{grid-column:1/-1}}`;
    document.head.appendChild(st);
  }

  /* ---------- helpers ---------- */
  const TABS = [['control', 'Control room'], ['queue', 'Work queue'], ['activity', 'Activity']];
  const st = { tab: 'control', state: 'all', stage: 'all', q: '' };
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'control';
    st.state = ['all', 'done', 'pending', 'n/a', 'stopped'].includes(p.get('state')) ? p.get('state') : 'all';
    st.stage = p.get('stage') || 'all'; st.q = p.get('q') || '';
  };
  const go = o => { H.hash.set(o); readHash(); render(); };
  const plural = (n, a, b) => fmt(n) + ' ' + (n === 1 ? a : b);
  const card = (title, infoKey, body, sub) => `<section class="pl-sec">${H.header({ title, sub: sub || '', infoHtml: M[infoKey] || '' })}${body}</section>`;
  const empty = t => `<p class="meta" style="margin:10px 0">${esc(t)}</p>`;
  const when = s => { if (!s) return ''; const t = new Date(s); return isNaN(t) ? String(s) : t.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }); };
  const clock = s => { const t = new Date(s); return isNaN(t) ? String(s || '') : t.toLocaleTimeString('en-GB'); };
  const mins = m => m == null ? 'unknown' : m < 90 ? Math.round(m) + ' min' : (m / 60).toFixed(1) + ' h';
  const secs = s => s == null ? '–' : s < 90 ? Math.round(s) + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : (s / 3600).toFixed(1) + ' h';
  const wid = id => id && H.byId && H.byId.has(id);
  const served = HUB.served;
  const notServed = 'Available when the hub is served (the static build only shows the state).';

  /* ================= Control room ================= */
  function control() {
    const by = Object.fromEntries(STATIONS.map(s => [s.key, s]));
    const n = k => by[k] && by[k].n != null ? fmt(by[k].n) : null;
    const parts = [];
    if (n('search')) parts.push(`${n('search')} records found`);
    if (n('screen')) parts.push(`${n('screen')} screened`);
    if (n('fulltext')) parts.push(`${n('fulltext')} read in full`);
    const lead = parts.length ? parts.join(', ') + '.' : 'No records yet.';
    const intr = live.intr && !live.intr.is_clean ? ' Some work was interrupted.' : '';
    const strip = ok(D.status) ? `<div class="pl-strip">
      <span>Events <b>${fmt(STATUS.events_total)}</b></span>
      <span>Newest event <b>${esc(STATUS.last_event_id || 'none')}</b> ${H.info('The newest event id is the data version: when it changes, the pages are out of date.', 'About the newest event')}</span>
      ${STATUS.code_version ? `<span>Code <b>${esc(STATUS.code_version)}</b></span>` : ''}
      <span>Built <b>${esc(when(STATUS.built_at))}</b></span>${H.info(M.status || '', 'About this strip')}</div>` : '';
    return { lead: lead + intr, body: strip + lineSec() + beatSec() + nextSec() + pagesSec() };
  }

  function lineSec() {
    if (!STATIONS.length) return card('Production line', 'stations', empty('The line appears once the review has records.'));
    const arrow = s => `<div class="pl-arr" aria-hidden="true"><svg viewBox="0 0 22 14"><path d="M1 7h19M14 2l6 5-6 5"/></svg>${s.pct == null ? '' : '<span>' + esc(s.pct) + '%</span>'}</div>`;
    const html = STATIONS.map((s, i) => `${i ? arrow(s) : ''}<a class="pl-st" href="${esc(s.page)}.html" aria-label="${esc(s.label)}: ${s.n == null ? 'not run' : fmt(s.n)} ${esc(s.sub)}">
      <div class="k">${esc(s.label)}</div><div class="v">${s.n == null ? '–' : fmt(s.n)}</div><div class="s">${esc(s.sub)}</div>
      ${s.pct != null ? `<div class="q" title="${esc(s.pct)}% of the previous stage"><i style="width:${Math.min(100, s.pct)}%"></i></div>` : ''}
      ${s.pending ? `<div class="w">${fmt(s.pending)} waiting</div>` : ''}</a>`).join('');
    return card('Production line', 'stations', `<div class="pl-line">${html}</div>`, 'Work moves left to right. Open a station for its page.');
  }

  function beatSec() {
    if (!HEART.length) return card('Activity', 'heartbeat', empty('No events recorded yet.'));
    const W = 1300, Hh = 130, B = 106, T = 10, mx = Math.max(...HEART.map(x => x[1])), bw = W / HEART.length;
    const bars = HEART.map(([day, c], i) => {
      const h = Math.max(2, (B - T) * c / mx);
      return `<rect x="${(i * bw + 2).toFixed(1)}" y="${(B - h).toFixed(1)}" width="${Math.max(2, bw - 4).toFixed(1)}" height="${h.toFixed(1)}" rx="2"><title>${esc(day)}: ${plural(c, 'event', 'events')}</title></rect>` +
        (i % Math.ceil(HEART.length / 8) === 0 ? `<text class="axis" x="${(i * bw + bw / 2).toFixed(1)}" y="${B + 14}" text-anchor="middle">${esc(day.slice(5))}</text>` : '');
    }).join('');
    return card('Activity', 'heartbeat', `<div class="card"><svg class="pl-beat" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Events recorded per day">${bars}</svg></div>`,
      'Events recorded per day.');
  }

  function nextSec() {
    const items = Array.isArray(D.next_actions) ? D.next_actions : [];
    if (!items.length) return '';
    const rows = items.map(i => `<li><b class="num">${fmt(i.count)}</b> ${esc(H.pretty(i.gate))}${i.stage ? ' (' + esc(i.stage) + ')' : ''}${i.assignee ? ' <span class="meta">' + esc(i.assignee) + '</span>' : ''}<br><span class="pl-mono">${esc(i.command)}</span></li>`).join('');
    return card('Where to start', 'status', `<ul class="pl-lines">${rows}</ul>`, 'What needs a person now.');
  }

  function pagesSec() {
    const cards = (D.pages || []).map(p => `<a href="${esc(p.id)}.html"><div class="card"><div class="nm">${esc(p.title)}</div><div class="bl">${esc(p.blurb)}</div></div></a>`).join('');
    return card('Pages', 'status', `<p class="pl-note" id="pl-fresh" role="status">${esc(freshText())}</p><div class="pl-pages">${cards}</div>`, 'Where each product lives.');
  }

  /* ================= Work queue ================= */
  const stageLabel = k => (STAGES.find(s => s.key === k) || {}).label || k;
  const applying = STAGES.filter(s => s.applies);
  const MARK = { done: '✓', pending: '…', 'n/a': '–', stopped: '■' };
  const WORD = { done: 'Done', pending: 'Pending', 'n/a': 'Not applicable', stopped: 'Stopped' };
  const CLS = { done: 's-done', pending: 's-pending', 'n/a': 's-na', stopped: 's-stopped' };

  function runLine() {
    const R = live.runs || {}, runs = R.runs || [], pls = R.pipelines || [];
    const open = runs.find(r => r.status === 'running' || r.status === 'lost?'), pl = pls.find(p => p.status === 'running');
    const last = open || runs[0];
    let t = 'No run yet.';
    if (pl) t = `Pipeline ${pl.pipeline_id} is running${last ? ' (' + last.stage + ': ' + last.status + ')' : ''}.`;
    else if (last) t = `Last run ${last.run_id} (${last.stage}): ${last.status}${pls[0] ? '; pipeline ' + pls[0].pipeline_id + ': ' + pls[0].status : ''}.`;
    return `<div class="pl-run" id="pl-runline" role="status" aria-live="polite"><span class="dot${live.busy ? ' busy' : ''}" style="background:${live.busy ? '' : 'var(--dim)'}"></span><span>${esc(t)}</span>` +
      `${live.busy ? '<span class="meta">A run is open; the buttons wait.</span>' : ''}${H.info(M.runs || '', 'About runs')}</div>`;
  }

  function actions() {
    const total = applying.reduce((a, s) => a + s.pending, 0);
    const capIn = `<label class="pl-cap">Unit cap <input type="number" min="1" max="${CAP.max}" value="${CAP.default}" data-cap aria-label="Unit cap"></label>`;
    const stageCards = applying.map(s => `<div class="card"><div class="nm">${esc(s.label)}</div>
      <div class="meta">${fmt(s.pending)} pending (${esc(s.model)})</div>
      <div><button class="btn" data-run="${esc(s.key)}" ${s.pending ? '' : 'disabled'}>Process now</button></div><div class="host" data-host="${esc(s.key)}"></div></div>`).join('');
    const skipped = STAGES.filter(s => !s.applies);
    return `${runLine()}
      <div class="pl-act"><div class="card"><div class="nm">All stages</div>
        <div class="meta">${fmt(total)} units pending across the stages below.</div>
        <div><button class="btn primary" data-run="all" ${total ? '' : 'disabled'}>Process all</button></div><div class="host" data-host="all"></div></div>${stageCards}</div>
      <p class="pl-note" style="margin-top:12px">${capIn} <span id="pl-act-note">${served ? '' : esc(notServed)}</span></p>
      ${skipped.length ? `<details class="pl-note"><summary>${plural(skipped.length, 'stage does', 'stages do')} not apply to this project</summary><ul class="pl-lines">${skipped.map(s => `<li><b>${esc(s.label)}</b>: ${esc(s.reason)}</li>`).join('')}</ul></details>` : ''}`;
  }

  function stageBars() {
    const cols = Q.columns || [];
    if (!cols.length || !(Q.items || []).length) return '';
    const bars = cols.map(c => {
      const k = Q.stage_counts[c.key] || {}, tot = Object.values(k).reduce((a, b) => a + b, 0) || 1;
      return `<div class="pl-bar"><span>${esc(c.label)}</span><div class="tr" role="img" aria-label="${esc(c.label)}: ${Object.keys(WORD).map(s => (k[s] || 0) + ' ' + WORD[s].toLowerCase()).join(', ')}">${Object.keys(WORD).map(s => k[s] ? `<i class="${CLS[s]}" style="width:${100 * k[s] / tot}%" title="${esc(WORD[s])}: ${k[s]}"></i>` : '').join('')}</div>
        <span class="meta">${fmt(k.done || 0)} of ${fmt(tot)} done</span></div>`;
    }).join('');
    const lg = Object.keys(WORD).map(s => `<span><i class="${CLS[s]}"></i>${WORD[s]}</span>`).join('');
    return `<div class="card"><div class="pl-bars">${bars}</div><div class="pl-lg">${lg}</div></div>`;
  }

  function gridRows() {
    const cols = Q.columns || [], q = st.q.toLowerCase();
    return (Q.items || []).filter(it => {
      const cells = Q.progress[it.entry_id] || {};
      const states = (st.stage === 'all' ? cols.map(c => c.key) : [st.stage]).map(k => cells[k] || 'n/a');
      if (st.state !== 'all' && !states.includes(st.state)) return false;
      return !q || (it.title + ' ' + it.entry_id).toLowerCase().includes(q);
    });
  }

  function titleCell(it) {
    if (wid(it.work_id)) return `<button type="button" data-open="${esc(it.work_id)}">${esc(it.title || it.entry_id)}</button>`;
    if (it.entry_id) return `<a href="https://arxiv.org/abs/${esc(encodeURI(it.entry_id))}" target="_blank" rel="noopener">${esc(it.title || it.entry_id)}</a>`;
    return esc(it.title);
  }

  function gridBody() {
    const cols = Q.columns || [], rows = gridRows();
    if (!(Q.items || []).length) return empty('No paper has been added from the feed yet.');
    if (!rows.length) return empty('No paper matches this filter.');
    return `<div class="card pl-grid"><table class="t"><thead><tr><th>Paper</th><th>Stage</th>${cols.map(c => `<th title="${esc(c.label)}">${esc(c.label)}</th>`).join('')}<th>Added</th></tr></thead><tbody>${rows.map(it => {
      const cells = Q.progress[it.entry_id] || {};
      const badge = `<span class="pl-badge${it.stopped ? ' stopped' : ''}${it.stage === 'extracted' ? ' extracted' : ''}">${esc(it.stage)}${it.stopped ? ' · stopped' : ''}</span>`;
      return `<tr><td class="ttl">${titleCell(it)}<div class="meta">${esc(it.entry_id)}${it.detail ? ' · ' + esc(it.detail) : ''}</div></td><td>${badge}</td>${cols.map(c => {
        const v = cells[c.key] || 'n/a';
        return `<td><span class="cell ${v === 'n/a' ? 'na' : v}" title="${esc(c.label)}: ${esc(WORD[v] || v)}" aria-label="${esc(c.label)}: ${esc(WORD[v] || v)}">${MARK[v] || esc(v)}</span></td>`;
      }).join('')}<td class="meta">${esc(when(it.sent_at))}</td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function filters() {
    const cols = Q.columns || [];
    const chip = (key, val, label) => `<button class="chip" data-f="${key}" data-v="${esc(val)}" aria-pressed="${st[key] === val}">${esc(label)}</button>`;
    return `<div class="pl-filt" role="group" aria-label="Filters">
      ${['all', 'done', 'pending', 'n/a', 'stopped'].map(s => chip('state', s, s === 'all' ? 'All states' : WORD[s])).join('')}
      <select data-stage aria-label="Stage"><option value="all">Every stage</option>${cols.map(c => `<option value="${esc(c.key)}" ${st.stage === c.key ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}</select>
      <input type="search" data-q placeholder="Find a paper" value="${esc(st.q)}" aria-label="Find a paper"></div>`;
  }

  function pendingTable() {
    const rows = Object.entries(Q.pending || {});
    if (!rows.length) return empty('No unit of work is defined yet.');
    return `<div class="card"><table class="t"><thead><tr><th>Task kind</th><th class="r">Open units</th></tr></thead><tbody>${rows.map(([k, v]) => `<tr><td>${esc(H.pretty(k))}</td><td class="r">${fmt(v)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  /* The interrupted lines: the same words the old Work queue used. */
  function intrLines(x) {
    const lines = [];
    (x.runs || []).forEach(r => {
      const lim = r.kind === 'limit' ? (r.limit_reset_at ? ` (usage limit; resets ${when(r.limit_reset_at)}${r.limit_reset_estimated ? ' (estimated)' : ''})` : r.limit_reset_text ? ` (usage limit; resets ${r.limit_reset_text})` : ' (usage limit; reset unknown)') : '';
      lines.push([`run ${r.run_id} (${r.stage}): ${r.kind}${lim}${r.stage_pending ? '' : ', no pending units'}`, r.kind === 'limit']);
    });
    (x.pipelines || []).forEach(p => lines.push([`pipeline ${p.pipeline_id}: ${p.kind}; stages left: ${(p.stages_left || []).join(', ') || 'none'}`]));
    (x.leases || []).forEach(l => lines.push([`expired leases, ${l.kind}: ${l.count}`]));
    (x.passes || []).forEach(p => lines.push([`stale pass ${p.module === 'screening' ? p.stage : p.scope} ${p.label}: ${p.pending} pending, session ${p.session} silent since ${when(p.last_activity)}`]));
    const a = x.automatic || {};
    if (a.resolve) lines.push([`papers never looked up: ${a.resolve}`]);
    if (a.fetch) lines.push([`screened-in papers without full text sought: ${a.fetch}`]);
    if (a.convert) lines.push([`full texts not converted: ${a.convert}`]);
    return lines;
  }
  const planLines = p => {
    const l = [];
    if (p.reconcile && p.reconcile.length) l.push('reconciled (process gone): ' + p.reconcile.join(', '));
    (p.leases || []).forEach(x => l.push(`leases lapsed, released by expiry: ${x.kind} ×${x.count}`));
    if (p.pipeline) l.push(`pipeline ${p.pipeline.resumes} resumed from stage ${p.pipeline.from_stage} (${p.pipeline.stages.join(', ')})`);
    if (p.run) l.push(`run ${p.run.resumes} resumed: stage ${p.run.stage} with model ${p.run.model}`);
    (p.waiting || []).forEach(w => l.push('waiting (not resumed): ' + w));
    if (p.queued && p.queued.length) l.push('queued (resumed by a later call): ' + p.queued.join(', '));
    (p.stale_passes || []).forEach(s => l.push(`stale pass (not resumed): ${s.module} ${s.module === 'screening' ? s.stage : s.scope} ${s.label}, ${s.pending} pending, session ${s.session}`));
    const a = p.automatic || {};
    if (a.resolve || a.fetch || a.convert) l.push(`automatic steps undone: resolve ${a.resolve || 0}, fetch ${a.fetch || 0}, convert ${a.convert || 0}`);
    return l.length ? l : ['nothing interrupted'];
  };
  const resultLines = r => {
    if (!r) return [];
    if (r.error) return ['error: ' + r.error];
    const l = [];
    (r.reconciled || []).forEach(x => l.push('reconciled run ' + x));
    if (r.pipeline_id) l.push('started pipeline ' + r.pipeline_id);
    if (r.run_id) l.push('started run ' + r.run_id);
    (r.refused || []).forEach(x => l.push('refused: ' + x));
    return l.length ? l : ['nothing started'];
  };

  function intrList() {
    if (!live.intr) return '<p class="meta">Interrupted work is unavailable.</p>';
    const lines = intrLines(live.intr);
    const last = resultLines(live.resume);
    return (lines.length ? `<ul class="pl-lines">${lines.map(([t, lim]) => `<li${lim ? ' class="limit pl-warn"' : ''}>${esc(t)}</li>`).join('')}</ul>` : empty('Nothing is interrupted.')) +
      (last.length ? `<p class="meta" style="margin-bottom:2px">Last resume</p><ul class="pl-lines">${last.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : '');
  }

  function interrupted() {
    const clean = !live.intr || live.intr.is_clean;
    return card('Interrupted', 'interrupted', `<div class="card"><div id="pl-intr">${intrList()}</div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><button class="btn" data-preview ${served ? '' : 'disabled'} ${served ? '' : `title="${esc(notServed)}"`}>Preview</button>
        <button class="btn primary" data-resume ${served && !clean && !live.busy ? '' : 'disabled'} ${served ? '' : `title="${esc(notServed)}"`}>Resume</button></div>
      <div id="pl-resume-host" style="margin-top:8px"></div><pre class="pl-out" id="pl-resume-out" role="status"></pre></div>`,
      'Runs, leases and papers left half-done.');
  }

  function queue() {
    const n = (Q.items || []).length;
    const stopped = Q.stopped || 0;
    const lead = n ? `${plural(n, 'paper has', 'papers have')} been added from the feed${stopped ? ', ' + fmt(stopped) + ' stopped on the way' : ''}.` : 'No paper has been added from the feed yet.';
    const run = card('Process', 'process', `<div id="pl-act">${actions()}</div><div id="pl-act-out" class="pl-out" role="status"></div>`, 'Start the runner for the work that is waiting.');
    const papers = card('Papers added', 'grid', stageBars() + (n ? filters() : '') + `<div id="pl-gridbody">${gridBody()}</div>`, 'Each paper and the stages it has been through.');
    return { lead, body: run + papers + card('Pending work', 'pending', pendingTable()) + interrupted() };
  }

  /* ================= Activity ================= */
  const A = () => live.act;
  function passRow(p) {
    const pct = p.total ? 100 * p.done / p.total : 0, held = p.total ? 100 * p.claimed / p.total : 0;
    const name = p.kind === 'miner' ? `${p.name}${p.version != null ? '@' + esc(p.version) : ''}${p.pass_label ? ' · pass ' + p.pass_label : ''}${p.mode ? ' · ' + p.mode : ''}` : H.pretty(p.name);
    return `<div class="pl-pass"><div class="hd"><span class="nm">${esc(name)}</span><span class="meta">${fmt(p.done)} of ${fmt(p.total)} done</span></div>
      <div class="tr" role="img" aria-label="${esc(name)}: ${fmt(p.done)} of ${fmt(p.total)} done"><i style="width:${pct}%"></i><i class="h" style="left:${pct}%;width:${Math.min(held, 100 - pct)}%"></i></div>
      <div class="ft"><span>Held <b>${fmt(p.claimed)}</b></span><span>Abandoned <b>${fmt(p.abandoned)}</b></span><span>Done in ${esc(A().rate_window_minutes)} min <b>${fmt(p.completed_recent)}</b></span>
      <span>Rate, estimated <b>${p.rate_estimate_per_hour ? fmt(Math.round(p.rate_estimate_per_hour)) + ' per hour' : 'none'}</b></span><span>Time left, estimated <b>${esc(mins(p.eta_estimate_minutes))}</b></span><span>Released <b>${fmt(p.released)}</b></span></div></div>`;
  }
  function activityBody() {
    const a = A();
    if (!a) return empty('Activity is not available.');
    const passes = a.passes.length ? a.passes.map(passRow).join('') : empty('No pass is open.');
    const dormant = a.dormant.length ? `<details class="pl-note" style="margin-top:10px"><summary>${plural(a.dormant.length, 'dormant pass', 'dormant passes')}</summary>${a.dormant.map(p => `<div class="meta" style="padding:4px 0">${esc(p.name)}${p.version != null ? '@' + esc(p.version) : ''}: ${fmt(p.done)} of ${fmt(p.total)}${p.abandoned ? ', ' + fmt(p.abandoned) + ' abandoned' : ''}</div>`).join('')}</details>` : '';
    const held = a.active.length ? `<div class="card"><table class="t"><thead><tr><th>Session</th><th>Task</th><th>Paper</th><th class="r">Held</th><th class="r">Lease left</th><th class="r">Rows</th><th>Last event</th><th>State</th></tr></thead><tbody>${a.active.slice(0, 6).map(r => `<tr><td class="num">${esc(String(r.session).slice(-8))}</td>
      <td>${esc(r.scope)}${r.miner_version != null ? '@' + esc(r.miner_version) : ''}${r.pass_label ? ' · ' + esc(r.pass_label) : ''}${r.mode ? ' · ' + esc(r.mode) : ''}</td>
      <td>${wid(r.work_id) ? `<button type="button" class="chip" data-open="${esc(r.work_id)}">${esc((r.title || r.work_id).slice(0, 60))}</button>` : esc(r.title || r.work_id || '')}</td>
      <td class="r">${esc(mins(r.minutes_held))}</td><td class="r">${esc(mins(r.lease_minutes_left))}</td><td class="r">${fmt(r.rows_recorded)}</td><td class="meta">${esc(r.last_event_at ? clock(r.last_event_at) : '')}</td>
      <td>${r.stale ? `<span class="pl-warn">stale (no event for ${esc(a.stale_minutes)} min)</span>` : 'active'}</td></tr>`).join('')}</tbody></table></div>` : empty('No task is held.');
    const ops = a.operations.length ? `<div class="card"><div class="pl-bars">${a.operations.map(o => {
      const pct = o.total ? Math.min(100, 100 * o.done / o.total) : 0;
      return `<div class="pl-bar" style="grid-template-columns:180px minmax(0,1fr) auto"><span>${esc(o.label || o.kind)} <span class="meta">${esc(o.state)}</span></span><div class="tr"><i class="${o.state === 'failed' ? 's-stopped' : 's-done'}" style="width:${pct}%"></i></div>
        <span class="meta">${fmt(o.done)}${o.total != null ? ' of ' + fmt(o.total) : ''} ${esc(o.unit || '')} · ${esc(secs(o.elapsed_seconds))}${o.eta_seconds != null ? ' · about ' + esc(secs(o.eta_seconds)) + ' left' : ''}</span></div>`;
    }).join('')}</div></div>` : empty('No long operation is running.');
    const traces = a.traces.length ? `<div class="card"><table class="t"><thead><tr><th>File</th><th>Modified</th><th>Last line</th><th class="r">Size</th></tr></thead><tbody>${a.traces.map(t => `<tr><td class="pl-mono">${esc(t.path)}</td><td class="meta">${esc(when(t.modified_at))}</td><td class="pl-mono">${esc(t.last_line)}</td><td class="r">${fmt(t.size)}</td></tr>`).join('')}</tbody></table></div>` : empty(`No trace file changed in the last ${Math.round(a.trace_window_minutes / 60)} hours.`);
    return card('Open passes', 'passes', `<div class="card">${passes}${dormant}</div>`, 'Progress, rate and time left are estimates.') +
      card('Tasks held now', 'held', held) + card('Long operations', 'operations', ops) + card('Worker traces', 'traces', traces) + screeningSec();
  }
  function screeningSec() {
    const s = live.scr || D.screening_live;
    if (!ok(s) || !s || !(s.recent || s.totals)) return card('Screening live', 'screening', empty('No screening decisions yet.'));
    const tot = Object.entries(s.totals || {}).map(([pass, v]) => `<div class="pl-tile"><div class="k">Pass ${esc(pass)}</div><div class="v">${fmt(Object.values(v).reduce((a, b) => a + b, 0))}</div><div class="k">${Object.entries(v).map(([k, n]) => esc(k) + ' ' + fmt(n)).join(' · ')}</div></div>`).join('');
    const sess = (s.sessions || []).map(x => `<span class="chip" title="${esc(x.actor)}"><span class="dot" style="background:${x.active ? 'var(--inc)' : 'var(--dim)'}"></span>${esc(x.session)} <span class="n">${fmt(x.decisions)} decisions · ${fmt(x.includes)} included${x.rate_per_minute != null ? ' · ' + x.rate_per_minute + '/min' : ''}</span></span>`).join(' ');
    const stops = (s.stops || []).map(x => `<div class="pl-bar"><span>Stop rule${x.below_score ? ' (score below ' + esc(x.below_score) + ')' : ''}</span><div class="tr"><i class="${x.stopped ? 's-stopped' : 's-done'}" style="width:${Math.min(100, 100 * x.run / x.n)}%"></i></div><span class="meta">${fmt(x.run)} of ${fmt(x.n)}${x.stopped ? ' · stopped' : ''}</span></div>`).join('');
    const rec = (s.recent || []).length ? `<table class="t" style="margin-top:12px"><thead><tr><th>Time</th><th>Pass</th><th>Paper</th><th>Verdict</th><th class="r">Score</th><th>Criterion</th></tr></thead><tbody>${s.recent.map(r => `<tr><td class="meta">${esc(clock(r.ts))}</td><td>${esc(r.pass)}</td><td title="${esc(r.rationale || '')}">${esc(r.title || '')}</td><td>${esc(r.verdict)}</td><td class="r">${r.score == null ? '' : esc(r.score)}</td><td class="meta">${esc(r.criterion || '')}</td></tr>`).join('')}</tbody></table>` : '';
    return card('Screening live', 'screening', `<div class="card"><div class="pl-tiles">${tot}</div><div>${sess}</div><div class="pl-bars" style="margin-top:10px">${stops}</div>${rec}</div>`, 'As of the time this page was built.');
  }
  /* Per-payload freshness (GET ui/status.json): which hub payloads are current, building or failed. */
  function freshText() {
    const S = live.status;
    if (!served) return '';
    if (!S) return 'Checking whether the hub data is current.';
    const names = Object.keys(S), stale = names.filter(n => !S[n].fresh), bad = names.filter(n => S[n].error);
    if (bad.length) return 'Some hub data failed to build: ' + bad.join(', ') + '.';
    const built = names.map(n => S[n].built_at).filter(Boolean).sort().pop(), at = built ? ` Newest build ${when(built)}.` : '';
    return stale.length ? `Hub data updating: ${stale.length} of ${names.length} payloads are being rebuilt (${stale.slice(0, 6).join(', ')}${stale.length > 6 ? ', ...' : ''}).${at}` : `All ${names.length} hub payloads are current.${at}`;
  }
  function liveLine() {
    const a = A();
    if (!served) return `Snapshot as of ${a ? clock(a.now) : esc(when(D.generated))}.`;
    if (live.actErr) return 'Live update unavailable.';
    return live.actAt ? `Live, as of ${clock(live.actAt)}, refreshed every ${POLL.activity / 1000} s.` : `Snapshot as of ${a ? clock(a.now) : ''}; refreshing.`;
  }
  function activity() {
    const a = A();
    const lead = !a ? 'Activity is not available.' : a.passes.length || a.active.length ? `${plural(a.active.length, 'task is', 'tasks are')} held in ${plural(a.passes.length, 'open pass', 'open passes')}.` : 'Nothing is running right now.';
    return { lead, body: `<p class="pl-note" id="pl-liveline" role="status" style="margin-top:14px">${esc(liveLine())}</p><div id="pl-act-body">${activityBody()}</div>` };
  }

  /* ================= render ================= */
  function render() {
    const view = { control, queue, activity }[st.tab]();
    main.innerHTML = H.header({ title: 'Pipeline', sub: 'Where the work stands and what runs next.', level: 1 }) +
      `<p class="lead pl-lead" id="pl-lead">${esc(view.lead)}</p>` +
      `<div class="pl-tabs"><div class="seg" role="group" aria-label="View">${TABS.map(t => `<button type="button" data-tab="${t[0]}" aria-pressed="${st.tab === t[0]}">${t[1]}</button>`).join('')}</div></div>` + view.body +
      (H.SETS_NOTE ? `<p class="meta" style="margin-top:32px">${H.info(esc(H.SETS_NOTE), 'About the paper counts')}</p>` : '');
    wire();
    schedule();
  }

  function wire() {
    main.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => go({ tab: b.dataset.tab === 'control' ? null : b.dataset.tab }); });
    wireOpen(main);
    main.querySelectorAll('[data-f]').forEach(b => { b.onclick = () => go({ [b.dataset.f]: b.dataset.v === 'all' ? null : b.dataset.v }); });
    const sel = main.querySelector('[data-stage]'); if (sel) sel.onchange = () => go({ stage: sel.value === 'all' ? null : sel.value });
    const q = main.querySelector('[data-q]');
    if (q) q.oninput = () => { st.q = q.value; H.hash.set({ q: q.value || null }); main.querySelector('#pl-gridbody').innerHTML = gridBody(); wireOpen(main); };
    main.querySelectorAll('[data-run]').forEach(b => { b.onclick = () => runStage(b); });
    const pv = main.querySelector('[data-preview]'); if (pv) pv.onclick = preview;
    const rs = main.querySelector('[data-resume]'); if (rs) rs.onclick = resume;
    syncButtons();
  }
  function wireOpen(root) { root.querySelectorAll('[data-open]').forEach(b => { b.onclick = e => { e.preventDefault(); H.openDrawer(b.dataset.open); }; }); }

  /* ================= acts ================= */
  const capValue = () => { const i = main.querySelector('[data-cap]'); return i ? Number(i.value) : CAP.default; };
  const capOk = n => Number.isInteger(n) && n >= 1 && n <= CAP.max;
  const outBox = id => main.querySelector(id);
  function syncButtons() {
    main.querySelectorAll('[data-run]').forEach(b => {
      const off = !served || live.busy || live.starting;
      b.disabled = off;
      b.title = !served ? notServed : live.busy || live.starting ? 'A run is open.' : '';
    });
    const rs = main.querySelector('[data-resume]');
    if (rs) rs.disabled = !served || live.busy || live.starting || !live.intr || live.intr.is_clean;
  }
  function runStage(btn) {
    const key = btn.dataset.run, host = main.querySelector(`[data-host="${key}"]`), out = outBox('#pl-act-out');
    if (!served || !host || live.busy || live.starting) return;
    const cap = capValue();
    if (!capOk(cap)) { out.className = 'pl-out err'; out.textContent = `The unit cap must be a whole number from 1 to ${CAP.max}.`; return; }
    const what = key === 'all' ? 'Start the whole pipeline' : 'Start ' + stageLabel(key);
    HUB.confirm(host, `${what}, at most ${cap} units per run? This calls a model through the runner.`, () => {
      if (live.busy || live.starting) { host.innerHTML = ''; out.className = 'pl-out err'; out.textContent = 'A run is already open or starting.'; return; }
      out.className = 'pl-out'; out.textContent = 'Starting…';
      live.starting = true; syncButtons();
      return HUB.post('/api/queue/process', { stage: key, unit_cap: cap }).then(r => {
        live.starting = false; syncButtons();
        host.innerHTML = '';
        if (!r.ok) { out.className = 'pl-out err'; out.textContent = 'Refused: ' + r.message; return; }
        const j = r.json || {};
        out.textContent = j.pipeline_id ? `Started pipeline ${j.pipeline_id} (${j.stage}, cap ${j.unit_cap}).` : `Started run ${j.run_id} (${j.stage}, cap ${j.unit_cap}).`;
        live.busy = true; syncButtons(); setTimeout(pollRuns, 3000);
      });
    });
  }
  function preview() {
    const out = outBox('#pl-resume-out'); out.className = 'pl-out'; out.textContent = 'Planning…';
    HUB.post('/api/queue/resume', { dry_run: true }).then(r => {
      if (!r.ok) { out.className = 'pl-out err'; out.textContent = 'Refused: ' + r.message; return; }
      out.textContent = 'Plan (nothing was written):\n' + planLines((r.json || {}).plan || {}).join('\n');
    });
  }
  function resume() {
    const host = outBox('#pl-resume-host'), out = outBox('#pl-resume-out');
    const cap = document.createElement('input'); cap.type = 'number'; cap.min = 1; cap.max = CAP.max; cap.placeholder = 'cap'; cap.setAttribute('aria-label', 'Unit cap for the resume'); cap.style.width = '72px';
    HUB.confirm(host, 'Resume the interrupted work? This can start a model run. Unit cap (optional):', () => {
      const v = cap.value === '' ? undefined : Number(cap.value);
      if (v !== undefined && !capOk(v)) { out.className = 'pl-out err'; out.textContent = `The unit cap must be a whole number from 1 to ${CAP.max}.`; host.innerHTML = ''; return; }
      if (live.busy || live.starting) { host.innerHTML = ''; out.className = 'pl-out err'; out.textContent = 'A run is already open or starting.'; return; }
      out.className = 'pl-out'; out.textContent = 'Starting…';
      live.starting = true; syncButtons();
      return HUB.post('/api/queue/resume', v === undefined ? {} : { unit_cap: v }).then(r => {
        live.starting = false; syncButtons();
        host.innerHTML = '';
        if (!r.ok) { out.className = 'pl-out err'; out.textContent = 'Refused: ' + r.message; pollIntr(); return; }
        out.textContent = 'Resume started; the outcome appears under Interrupted when it ends.';
        live.busy = true; syncButtons(); setTimeout(pollIntr, 3000); setTimeout(pollRuns, 3000);
      });
    }, cap);
  }

  /* ================= live polling (served only, bounded, paused while the tab is hidden) ================= */
  const POLL = { activity: 10000, runsBusy: 5000, runsIdle: 20000, intr: 15000 };
  const timers = {};
  const fetchJson = path => HUB.get(path).then(r => { if (!r.ok) throw new Error('status ' + r.status); return r.json(); });
  function pollActivity() {
    return fetchJson('/api/activity').then(j => { live.act = j; live.actAt = j.now || new Date().toISOString(); live.actErr = false; })
      .catch(() => { live.actErr = true; })
      .then(() => fetchJson('/api/screening').then(j => { live.scr = j; }).catch(() => {}))
      .then(() => {
        if (st.tab !== 'activity') return;
        const ab = main.querySelector('#pl-act-body'), ll = main.querySelector('#pl-liveline');
        if (ab) { ab.innerHTML = activityBody(); wireOpen(ab); }
        if (ll) ll.textContent = liveLine();
        const ld = main.querySelector('#pl-lead'); if (ld) ld.textContent = activity().lead;
      });
  }
  function pollStatus() {
    return fetchJson('/ui/status.json').then(j => { live.status = j; })
      .catch(() => { live.status = null; })
      .then(() => main.querySelectorAll('#pl-fresh').forEach(e => { e.textContent = freshText(); }));
  }
  function pollRuns() {
    return fetchJson('/api/queue/runs').then(j => {
      live.runs = j; live.busy = (j.runs || []).some(r => r.status === 'running') || (j.pipelines || []).some(p => p.status === 'running');
      const rl = main.querySelector('#pl-runline'); if (rl) rl.outerHTML = runLine();
      syncButtons();
    }).catch(() => {});
  }
  function pollIntr() {
    return fetchJson('/api/queue/interrupted').then(j => {
      live.intr = j; live.resume = j.last_resume || null;
      const b = main.querySelector('#pl-intr'); if (b) b.innerHTML = intrList();
      syncButtons();
    }).catch(() => { const b = main.querySelector('#pl-intr'); if (b) b.innerHTML = '<p class="meta">Interrupted work is unavailable.</p>'; });
  }
  /* One loop per feed while its tab is open: the next call is planned only after the last one ends. */
  function loop(name, fn, ms) {
    clearTimeout(timers[name]);
    const tick = () => { if (!document.hidden) fn().then(next, next); else next(); };
    const next = () => { timers[name] = setTimeout(tick, typeof ms === 'function' ? ms() : ms); };
    tick();
  }
  function schedule() {
    Object.values(timers).forEach(clearTimeout);
    if (!served) return;
    loop('status', pollStatus, 30000);
    if (st.tab === 'activity') loop('activity', pollActivity, POLL.activity);
    if (st.tab === 'queue') {
      loop('runs', pollRuns, () => live.busy ? POLL.runsBusy : POLL.runsIdle);
      loop('intr', pollIntr, POLL.intr);
    }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); });
  window.addEventListener('hashchange', () => { readHash(); render(); });
  readHash();
  render();
});
