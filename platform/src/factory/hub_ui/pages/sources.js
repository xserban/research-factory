/* Sources page: searches and dedup, full-text acquisition, conversion coverage, study documents.
   Payload: shell, sources (services/hub_sources.py). Tabs keep their state in the hash (#tab=, conv=, q=, rule=, status=).
   Per-document inspector detail (gaps, extracted text) loads lazily from data/sources-doc-<id>.json when the server has
   that route; until then the panel links to the classic inspector page. */
HUB.load(['shell', 'sources']).then(d => {
  const H = HUB.init(d.shell);
  const { esc, fmt, term, info, header, byId, $ } = H;
  const S = d.sources, M = S.methods || {};
  H.mount({ page: 'sources', crumb: 'Sources' });
  const main = $('#main');
  const SE = S.search, AC = S.acquisition, CV = S.conversion, DC = S.documents;

  if (!document.getElementById('sources-css')) {
    const st = document.createElement('style'); st.id = 'sources-css';
    st.textContent = `
.sx-tabs{margin:14px 0 22px}
.sx-sec{margin:34px 0 0}
.sx-kpis{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 4px}
.sx-kpi{background:var(--surface);border-radius:var(--r);padding:12px 16px;min-width:120px}
.sx-kpi .n{font:500 var(--t-xl) var(--f-mono);display:block}
.sx-kpi .l{font-size:var(--t-xs);color:var(--mut)}
.sx-kpi.warn .n{color:var(--exc)}
.sx-bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}
.sx-bar .grow{flex:1}
.sx-yield{display:grid;grid-template-columns:minmax(120px,220px) 1fr 150px;gap:6px 12px;align-items:center;font-size:var(--t-s)}
.sx-yield .tr{position:relative;height:12px;background:var(--hair);border-radius:3px}
.sx-yield .fill{position:absolute;left:0;top:0;bottom:0;background:var(--acc);border-radius:3px}
.sx-yield .rep{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--fg)}
.sx-yield .gapn{font-family:var(--f-mono);color:var(--mut);text-align:right}
.sx-yield .gapn.bad{color:var(--exc)}
.sx-yield .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sx-stack{display:flex;height:22px;border-radius:4px;overflow:hidden;background:var(--hair)}
.sx-stack i{display:block;height:100%}
.sx-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--mut);margin-top:8px}
.sx-legend .dot{margin-right:5px}
.sx-q{background:var(--surface);border-radius:var(--r);margin:0 0 8px}
.sx-q>summary{cursor:pointer;padding:12px 16px;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;list-style:none}
.sx-q>summary::-webkit-details-marker{display:none}
.sx-q>summary:before{content:'+';font-family:var(--f-mono);color:var(--mut);width:10px}
.sx-q[open]>summary:before{content:'-'}
.sx-q .body{padding:0 16px 16px}
.sx-q code,.sx-cmd code{font:400 12px var(--f-mono);background:var(--bg);padding:3px 7px;border-radius:4px;overflow-wrap:anywhere}
.sx-bad{color:var(--exc)}.sx-warn{color:var(--h-feedback)}.sx-ok{color:var(--inc)}
.sx-tag{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:999px;background:var(--raised);color:var(--mut)}
.sx-tag.rev{background:var(--exc-soft);color:var(--exc)}
.sx-cmd{display:flex;gap:8px;align-items:center;margin:5px 0}
.sx-cmd code{flex:1;white-space:pre-wrap}
pre.sx-pre{background:var(--bg);border-radius:var(--r-s);padding:10px;font:400 12px var(--f-mono);overflow:auto;white-space:pre-wrap;margin:6px 0}
.t td.l,.t th.l{text-align:left;font-family:var(--f-ui)}
.t.sx-plain tbody tr{cursor:default}.t.sx-plain tbody tr:hover{background:transparent}
.t tr.sx-det>td{background:var(--surface);padding:14px 16px;cursor:default}
.sx-hist{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.sx-hcard{background:var(--surface);border-radius:var(--r);padding:12px 14px}
.sx-bins{display:flex;align-items:flex-end;gap:3px;height:72px;margin-top:8px}
.sx-bins button{flex:1;border:0;padding:0;background:var(--acc);border-radius:2px 2px 0 0;min-height:2px;cursor:pointer;opacity:.85}
.sx-bins button:hover,.sx-bins button[aria-pressed=true]{opacity:1;outline:2px solid var(--fg);outline-offset:1px}
.sx-bins button.lo{background:var(--exc)}
.sx-axis{display:flex;justify-content:space-between;font:400 11px var(--f-mono);color:var(--dim);margin-top:3px}
.sx-plot{background:var(--surface);border-radius:var(--r);padding:8px;max-width:640px}
.sx-plot svg{width:100%;height:auto;display:block}
.sx-plot a{cursor:pointer}
.sx-plot circle{cursor:pointer;stroke:var(--bg);stroke-width:1}
.sx-plot circle:hover,.sx-plot circle:focus{stroke:var(--fg);stroke-width:2}
.sx-split{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.sx-split pre{max-height:360px}
.sx-kind{display:flex;gap:10px;flex-wrap:wrap}
.sx-kind .sx-kpi{min-width:150px}
@media (max-width:900px){.sx-split{grid-template-columns:1fr}.sx-yield{grid-template-columns:1fr 1fr}.sx-yield .nm{grid-column:1/-1}}`;
    document.head.appendChild(st);
  }

  /* ---------- small helpers ---------- */
  const f3 = v => v == null ? 'n/a' : Number(v).toFixed(3);
  const palette = ['--h-none', '--h-goal', '--h-collab', '--h-review', '--h-feedback', '--l-adjacent'];
  const convColour = {};
  Object.keys(CV.summary || {}).concat((CV.documents || []).map(x => x.converter)).forEach(c => {
    if (!(c in convColour)) convColour[c] = 'var(' + palette[Object.keys(convColour).length % palette.length] + ')';
  });
  const copyCmd = c => `<div class="sx-cmd"><code>${esc(c)}</code><button class="btn" type="button" data-copy="${esc(c)}">Copy</button></div>`;
  const openPaper = id => byId.has(id)
    ? `<a href="#" data-open="${esc(id)}">Open the paper</a>` : '<span class="meta">Not in the included set.</span>';
  const kpi = (n, l, cls = '') => `<div class="sx-kpi ${cls}"><span class="n">${n == null ? 'n/a' : fmt(n)}</span><span class="l">${l}</span></div>`;
  const empty = t => `<p class="meta">${t}</p>`;
  const titleLink = (id, t) => byId.has(id) ? `<a href="#" data-open="${esc(id)}">${esc(t || id)}</a>` : esc(t || id);
  const sum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);

  /* ---------- tabs and hash ---------- */
  const TABS = [['search', 'Search and dedup'], ['acquisition', 'Full text'], ['conversion', 'Conversion'], ['documents', 'Study documents']];
  const st = { tab: H.hash.get().get('tab') || 'search' };
  if (!TABS.some(t => t[0] === st.tab)) st.tab = 'search';
  const hp = () => H.hash.get();

  main.innerHTML = header({ title: 'Sources', level: 1, kicker: 'Where the papers came from',
    sub: 'Searches, full texts, conversion and the study files.' }) +
    `<div class="sx-tabs"><div class="seg" role="tablist" aria-label="Sources view">${TABS.map(([k, l]) =>
      `<button role="tab" data-tab="${k}" aria-pressed="${k === st.tab}">${l}</button>`).join('')}</div></div><div id="sxBody"></div>`;
  const body = $('#sxBody');

  const wire = root => {
    root.querySelectorAll('[data-open]').forEach(a => a.onclick = e => { e.preventDefault(); H.openDrawer(a.dataset.open); });
    root.querySelectorAll('[data-copy]').forEach(b => b.onclick = () => {
      try { navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy'; }, 1200); } catch (e) { b.textContent = 'Not copied'; }
    });
  };
  const show = () => {
    main.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tab === st.tab)));
    H.hash.set({ tab: st.tab === 'search' ? '' : st.tab });
    ({ search: renderSearch, acquisition: renderAcq, conversion: renderConv, documents: renderDocs })[st.tab]();
    wire(body);
  };
  main.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { st.tab = b.dataset.tab; show(); });

  /* ======================================================= SEARCH AND DEDUP ======================================================= */
  const ms = { q: '', rule: '', status: '', shown: 300 };
  function renderSearch() {
    const qs = SE.queries || [], tiles = SE.merge_tiles || {}, ident = SE.identification || {};
    const nIdent = sum(ident.databases) + sum(ident.other);
    const peak = Math.max(1, ...qs.map(q => Math.max(q.reported || 0, q.retrieved || 0)));
    const rules = Object.keys(SE.rule_counts || {});
    const maxRule = Math.max(1, ...rules.map(r => sum(SE.rule_counts[r])));
    body.innerHTML = `
    ${SE.error ? `<p class="sx-bad" role="alert">The archived search pages could not be read: ${esc(SE.error)}</p>` : ''}
    <section>${header({ title: 'Searches', infoHtml: M.search, sub: 'What each source reported and what was retrieved.' })}
      <div class="sx-kpis">${kpi(qs.length, 'queries run')}${kpi(SE.runs_complete, 'runs complete')}${kpi(SE.runs_partial, 'runs partial', SE.runs_partial ? 'warn' : '')}
        ${kpi(nIdent, 'records identified')}${kpi(ident.duplicates_removed, term('duplicates', 'duplicates') + ' removed')}${kpi(tiles.active, 'merges active')}${kpi(tiles.reverted, 'merges reverted')}</div>
    </section>
    <section class="sx-sec">${header({ title: 'Yield per query', infoHtml: M.yield })}
      ${qs.length ? `<div class="sx-yield" role="list">${qs.map(q => {
        const gap = q.gap;
        return `<span class="nm" role="listitem" title="${esc(q.text)}"><b class="mono">${esc(q.id)}</b> ${esc(q.source)}</span>
        <span class="tr" role="img" aria-label="${esc(q.id)}: retrieved ${q.retrieved}${q.reported != null ? ' of ' + q.reported + ' reported' : ', no total reported'}"
          data-tip="${esc(q.id + ': ' + fmt(q.retrieved) + ' retrieved' + (q.reported != null ? ', ' + fmt(q.reported) + ' reported' : ', no total reported'))}">
          <span class="fill" style="width:${100 * q.retrieved / peak}%"></span>${q.reported != null ? `<span class="rep" style="left:calc(${100 * q.reported / peak}% - 1px)"></span>` : ''}</span>
        <span class="gapn ${gap ? 'bad' : ''}">${q.reported == null ? 'not reported' : gap ? fmt(gap) + ' short' : 'complete'}</span>`;
      }).join('')}</div><div class="sx-legend"><span><span class="dot" style="background:var(--acc)"></span>retrieved</span><span><span class="dot" style="background:var(--fg)"></span>reported by the source</span></div>` : empty('No query is registered yet.')}
    </section>
    <section class="sx-sec">${header({ title: 'Query by query' })}
      ${qs.map(q => `<details class="sx-q" id="q-${esc(q.id)}"><summary><b class="mono">${esc(q.id)}</b><span>${esc(q.source)}</span><span class="meta">${esc(q.kind)} · ${esc(q.purpose)} · ${esc(q.at)}${q.round ? ' · round ' + esc(q.round) : ''}</span>
          <span class="grow" style="flex:1"></span><span class="meta">reported <b class="num">${q.reported == null ? 'not reported' : fmt(q.reported)}</b> · retrieved <b class="num">${fmt(q.retrieved)}</b>${q.gap ? ` · <b class="sx-bad num">gap ${fmt(q.gap)}</b>` : ''}</span></summary>
        <div class="body"><p><code>${esc(q.text)}</code></p>
          <p class="meta">Filters: ${Object.keys(q.filters).length ? Object.entries(q.filters).map(([k, v]) => '<code>' + esc(k + '=' + v) + '</code>').join(' ') : 'none'}</p>
          ${q.shortfall ? `<details><summary class="meta">Why it fell short</summary><p class="meta">${esc(q.shortfall)}</p></details>` : ''}
          <table class="t sx-plain"><thead><tr><th class="l">Run</th><th class="l">Status</th><th class="r">Reported</th><th class="r">Retrieved</th><th class="r">Skipped</th><th class="r">New works</th><th class="r">Pages</th><th class="l">Note</th></tr></thead><tbody>
          ${q.runs.map(r => `<tr><td class="mono">${esc(r.id)}</td><td>${esc(r.status)}</td><td class="r">${r.rep == null ? 'n/a' : fmt(r.rep)}</td><td class="r">${fmt(r.got)}</td><td class="r">${fmt(r.skip)}</td><td class="r">${fmt(r.new)}</td><td class="r">${fmt(r.pages)}</td><td>${esc(r.note || '')}</td></tr>`).join('')}</tbody></table>
          ${q.skipped_n ? `<details style="margin-top:10px"><summary>Records that never became works: <b class="num">${fmt(q.skipped_n)}</b>${q.skipped_n > q.skipped.length ? ` <span class="meta">(first ${fmt(q.skipped.length)} shown)</span>` : ''}</summary>
            <table class="t sx-plain"><thead><tr><th class="l">Reason</th><th class="l">Run</th><th class="l">Id</th><th class="l">Title</th></tr></thead><tbody>
            ${q.skipped.map(s => `<tr><td>${esc(s[3])}</td><td class="mono">${esc(s[0])}</td><td class="mono">${esc(s[1] || '')}</td><td>${esc(s[2] || '')}</td></tr>`).join('')}</tbody></table></details>` : ''}
        </div></details>`).join('')}
      ${SE.skipped_total ? `<p class="meta" style="margin-top:12px">Records that never became works, all queries: <b class="num">${fmt(SE.skipped_total)}</b>${info(M.skipped)} ${Object.entries(SE.skipped_by_reason || {}).map(([k, v]) => `<span class="sx-tag">${esc(k)} <b class="num">${fmt(v)}</b></span>`).join(' ')}</p>` : ''}
    </section>
    <section class="sx-sec">${header({ title: 'Records by source', infoHtml: M.identification })}
      <table class="t sx-plain" style="max-width:640px"><thead><tr><th class="l">Source</th><th class="r">Queries</th><th class="r">Records retrieved</th></tr></thead><tbody>
      ${Object.entries(SE.per_source || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r">${fmt(v.queries)}</td><td class="r">${fmt(v.retrieved)}</td></tr>`).join('')}</tbody></table>
      <p class="meta" style="margin-top:10px">Identification: databases ${Object.entries(ident.databases || {}).map(([k, v]) => `${esc(k)} <b class="num">${fmt(v)}</b>`).join(', ') || 'none'};
        other sources ${Object.entries(ident.other || {}).map(([k, v]) => `${esc(k)} <b class="num">${fmt(v)}</b>`).join(', ') || 'none'}; duplicates removed <b class="num">${fmt(ident.duplicates_removed)}</b>.</p>
    </section>
    <section class="sx-sec">${header({ title: 'Duplicates', infoHtml: M.dedup, sub: 'Merges by the rule that matched. Reverting is done on the command line.' })}
      ${rules.length ? `<div style="max-width:640px">${rules.map(r => { const c = SE.rule_counts[r], a = c.active || 0, v = c.reverted || 0;
        return `<div style="display:grid;grid-template-columns:150px 1fr 90px;gap:10px;align-items:center;margin:6px 0;font-size:var(--t-s)"><span>${esc(r)}</span>
          <span class="sx-stack" role="img" aria-label="${esc(r)}: ${a} active, ${v} reverted"><i style="width:${100 * a / maxRule}%;background:var(--acc)"></i><i style="width:${100 * v / maxRule}%;background:var(--exc)"></i></span>
          <span class="mono meta">${fmt(a)} / ${fmt(v)}</span></div>`; }).join('')}</div>
        <div class="sx-legend"><span><span class="dot" style="background:var(--acc)"></span>active</span><span><span class="dot" style="background:var(--exc)"></span>reverted</span></div>` : empty('No merges recorded.')}
      <div class="sx-bar"><input type="search" id="mq" placeholder="Search merge id or title" aria-label="Search merges" value="${esc(ms.q)}">
        <select id="mr" aria-label="Rule"><option value="">All rules</option>${rules.map(r => `<option ${r === ms.rule ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select>
        <select id="ms" aria-label="Status"><option value="">All statuses</option><option ${ms.status === 'active' ? 'selected' : ''}>active</option><option ${ms.status === 'reverted' ? 'selected' : ''}>reverted</option></select>
        <button class="btn" type="button" id="mclear">Clear</button><span class="meta" id="mcount"></span></div>
      <div id="mlist"></div>
    </section>
    <section class="sx-sec">${header({ title: 'Merged after screening', infoHtml: M.after })}
      ${(SE.after || []).length ? `<p class="meta">${esc(SE.after_note)}</p><table class="t sx-plain"><thead><tr><th class="l">Merge</th><th class="l">Rule</th><th class="l">Primary kept</th><th class="l">Outcome</th><th class="l">Absorbed</th><th class="l">Outcome</th></tr></thead><tbody>
      ${SE.after.map(a => `<tr><td class="mono">${esc(a[0])}</td><td>${esc(a[1])}</td><td>${titleLink(a[2], a[3])}</td><td>${esc(a[4] || '')}</td><td>${titleLink(a[5], a[6])}</td><td>${esc(a[7] || '')}</td></tr>`).join('')}</tbody></table>` : empty('No merged pair was screened differently.')}
    </section>
    <p class="meta" style="margin-top:28px">Next: <a href="flow.html">the flow of records</a>, <a href="#tab=acquisition" data-go="acquisition">full text that could not be retrieved</a>.</p>`;
    body.querySelectorAll('[data-go]').forEach(a => a.onclick = e => { e.preventDefault(); st.tab = a.dataset.go; show(); });
    body.querySelectorAll('.sx-yield .tr').forEach(el => { el.onmousemove = e => H.tip(el.dataset.tip, e); el.onmouseleave = () => H.tip(''); });
    const p = hp(); ms.q = p.get('q') || ms.q; ms.rule = p.get('rule') || ms.rule; ms.status = p.get('status') || ms.status;
    $('#mq').value = ms.q; $('#mr').value = ms.rule; $('#ms').value = ms.status;
    const drawMerges = () => {
      const q = ms.q.toLowerCase();
      const rows = (SE.merges || []).filter(m => (!ms.rule || m.rule === ms.rule) && (!ms.status || m.status === ms.status) &&
        (!q || (m.id + ' ' + m.pt + ' ' + m.absorbed.map(a => a[0] + ' ' + a[1]).join(' ')).toLowerCase().includes(q)));
      $('#mcount').textContent = fmt(Math.min(ms.shown, rows.length)) + ' of ' + fmt(rows.length) + ' merges';
      $('#mlist').innerHTML = rows.length ? `<table class="t sx-plain"><thead><tr><th class="l">Merge</th><th class="l">Status</th><th class="l">Rule</th><th class="r">Records</th><th class="l">Primary</th><th class="l">Absorbed</th></tr></thead><tbody>
        ${rows.slice(0, ms.shown).map(m => `<tr><td class="mono">${esc(m.id)}</td><td><span class="sx-tag ${m.status === 'reverted' ? 'rev' : ''}">${esc(m.status)}</span>${m.status === 'reverted' ? `<div class="meta">${esc(m.rat || '')}${m.reason ? ': ' + esc(m.reason) : ''}</div>` : ''}${m.manual ? '<div class="meta">manual</div>' : ''}</td>
          <td>${esc(m.rule)}</td><td class="r">${fmt(m.records)}</td><td>${titleLink(m.primary, m.pt)}<div class="meta mono">${esc(m.primary || '')}</div></td>
          <td>${m.absorbed.map(a => `<div>${titleLink(a[0], a[1])} <span class="meta mono">${esc(a[0])}</span></div>`).join('')}</td></tr>`).join('')}</tbody></table>
        ${rows.length > ms.shown ? '<p><button class="btn" type="button" id="mmore">Show more</button></p>' : ''}` : empty('No merge matches.');
      wire($('#mlist'));
      const more = $('#mmore'); if (more) more.onclick = () => { ms.shown += 300; drawMerges(); };
    };
    const upd = () => { ms.shown = 300; H.hash.set({ q: ms.q, rule: ms.rule, status: ms.status }); drawMerges(); };
    $('#mq').oninput = e => { ms.q = e.target.value; upd(); };
    $('#mr').onchange = e => { ms.rule = e.target.value; upd(); };
    $('#ms').onchange = e => { ms.status = e.target.value; upd(); };
    $('#mclear').onclick = () => { ms.q = ms.rule = ms.status = ''; $('#mq').value = ''; $('#mr').value = ''; $('#ms').value = ''; upd(); };
    drawMerges();
  }

  /* ======================================================= FULL-TEXT ACQUISITION ======================================================= */
  const ROUTE_COLOUR = { 'arxiv-html': '--h-none', 'arxiv-source': '--h-goal', 'pmc-jats': '--h-review', 'europepmc-jats': '--h-feedback', 'oa-pdf': '--h-collab', 'researcher-supplied': '--l-adjacent' };
  function renderAcq() {
    const undeclared = AC.undeclared.length;
    const routes = Object.entries(AC.by_route || {}).filter(([, v]) => v);
    const declaredN = AC.not_retrieved - undeclared;
    const seg = [...routes.map(([k, v]) => ({ k, v, c: 'var(' + (ROUTE_COLOUR[k] || '--h-null') + ')', l: k })),
      { k: 'declared', v: declaredN, c: 'var(--h-feedback)', l: 'not retrieved, declared', hatch: true },
      { k: 'undeclared', v: undeclared, c: 'var(--exc)', l: 'not retrieved, not declared' },
      { k: 'unsought', v: AC.unsought, c: 'var(--line)', l: 'not yet sought' }].filter(s => s.v);
    const tot = Math.max(1, AC.promoted);
    body.innerHTML = `
    <section>${header({ title: 'Full text', infoHtml: M.acquisition,
      sub: AC.not_retrieved ? (undeclared ? fmt(undeclared) + ' papers without a full text have no deviation yet.' : 'Every paper without a full text is declared by a deviation.') : 'Every sought paper has a full text.' })}
      <div class="sx-kpis">${kpi(AC.promoted, 'promoted to full text')}${kpi(AC.unsought, 'unsought (later tranche)')}${kpi(AC.retrieved, 'retrieved')}${kpi(AC.not_retrieved, term('notretrieved', 'not retrieved'), AC.not_retrieved ? 'warn' : '')}</div>
    </section>
    <section class="sx-sec">${header({ title: 'Where the papers stand', infoHtml: M.funnel })}
      <div class="sx-stack" role="img" aria-label="Promoted papers by state">${seg.map(s => `<i style="width:${100 * s.v / tot}%;background:${s.c}" data-tip="${esc(s.l + ': ' + fmt(s.v))}"></i>`).join('')}</div>
      <div class="sx-legend">${seg.map(s => `<span><span class="dot" style="background:${s.c}"></span>${esc(s.l)} <b class="num">${fmt(s.v)}</b></span>`).join('')}</div>
      <table class="t sx-plain" style="max-width:720px;margin-top:14px"><thead><tr><th class="l">Route</th><th class="l">What it is</th><th class="r">Retrieved</th></tr></thead><tbody>
      ${Object.keys(AC.by_route).map(k => `<tr><td>${esc(k)}</td><td>${esc(AC.route_help[k] || '')}</td><td class="r">${fmt(AC.by_route[k])}</td></tr>`).join('')}</tbody></table>
    </section>
    <section class="sx-sec">${header({ title: 'Not retrieved', sub: 'Click a paper for what was tried and what to do.' })}
      ${AC.works.length ? `<table class="t" id="acT"><thead><tr><th class="l">Paper</th><th class="l">DOI</th><th class="l">Published</th><th class="l">Reasons</th><th class="l">Declared by</th></tr></thead><tbody>
      ${AC.works.map(w => `<tr data-w="${esc(w.id)}" tabindex="0"><td>${esc(w.title)}</td><td class="mono">${esc(w.doi || '')}</td><td>${esc((w.published || '').slice(0, 10))}</td>
        <td>${esc(Object.entries(w.reasons).map(([k, v]) => k + ': ' + v).join('; ').slice(0, 110))}</td><td>${w.declared_by ? esc(w.declared_by) : '<span class="sx-warn">not declared</span>'}</td></tr>`).join('')}</tbody></table>` : empty('No paper is waiting for a full text.')}
    </section>
    ${undeclared ? `<section class="sx-sec">${header({ title: 'Declare them together', sub: 'Save as deviation.json and record it, or open one paper to declare it alone.' })}
      <pre class="sx-pre">${esc(JSON.stringify(AC.batch_deviation, null, 2))}</pre>${copyCmd(AC.commands.deviation)}</section>` : ''}
    <section class="sx-sec">${header({ title: 'Deviations', infoHtml: M.deviations })}
      <p class="meta"><b class="num">${fmt(AC.deviations.length)}</b> recorded. Screening stops by a declared rule and unscreened papers are reported in <a href="flow.html">the flow</a>.</p>
      ${AC.deviations.length ? `<table class="t sx-plain"><thead><tr><th class="l">Deviation</th><th class="r">Papers</th><th class="l">Description</th></tr></thead><tbody>
      ${AC.deviations.map(v => `<tr><td class="mono">${esc(v.id)}</td><td class="r">${fmt(v.works)}</td><td>${esc(v.description)}</td></tr>`).join('')}</tbody></table>` : ''}
    </section>`;
    body.querySelectorAll('.sx-stack i').forEach(el => { el.onmousemove = e => H.tip(el.dataset.tip, e); el.onmouseleave = () => H.tip(''); });
    const open = tr => {
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('sx-det')) { next.remove(); tr.setAttribute('aria-selected', 'false'); return; }
      const w = AC.works.find(x => x.id === tr.dataset.w); tr.setAttribute('aria-selected', 'true');
      const q = encodeURIComponent(w.title);
      const links = [w.doi ? ['https://doi.org/' + w.doi, 'The publisher page (DOI)'] : null,
        w.openalex ? ['https://openalex.org/' + w.openalex, 'The OpenAlex record'] : null,
        ['https://scholar.google.com/scholar?q=' + q, 'Search the title on Google Scholar'],
        ['https://arxiv.org/search/?query=' + q + '&searchtype=title', 'Search the title on arXiv'],
        ['https://www.semanticscholar.org/search?q=' + q, 'Search the title on Semantic Scholar']].filter(Boolean);
      const det = document.createElement('tr'); det.className = 'sx-det';
      det.innerHTML = `<td colspan="5"><p class="meta">${esc([w.authors, (w.published || '').slice(0, 10), w.venue].filter(Boolean).join(' · '))}
        · ${w.declared_by ? `<span class="sx-ok">declared by ${esc(w.declared_by)}</span>` : '<span class="sx-warn">not declared by any deviation</span>'} · ${openPaper(w.id)}
        · <a href="../acquisition/work/${esc(w.slug)}.html">Classic page</a></p>
        <h3 class="h3">What the automatic routes tried</h3>
        <table class="t sx-plain"><thead><tr><th class="l">Route</th><th class="l">What it is</th><th class="l">Result</th><th class="l">Meaning</th></tr></thead><tbody>
        ${Object.entries(w.reasons).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(AC.route_help[k] || '')}</td><td>${esc(v)}</td><td>${esc(AC.reason_help[String(v).split(' ')[0]] || '')}</td></tr>`).join('')}</tbody></table>
        <h3 class="h3" style="margin-top:14px">Look for a copy yourself</h3>
        <ul>${links.map(([u, l]) => `<li><a href="${esc(u)}" target="_blank" rel="noopener">${esc(l)}</a></li>`).join('')}</ul>
        <h3 class="h3">What you can do</h3>
        <p class="meta">1. Retry the automatic routes, for example after a new arXiv version.</p>${copyCmd(w.fetch_command)}
        <p class="meta">2. Import a copy: save the PDF under this name, then import the folder.</p>${copyCmd(w.file_name || '<DOI with / replaced by _>.pdf')}${copyCmd(AC.commands.import)}
        ${w.declared_by ? `<p class="meta">3. Already declared by ${esc(w.declared_by)}.</p>` : `<p class="meta">3. Declare it not acquired: record a deviation from a file with this content.</p><pre class="sx-pre">${esc(JSON.stringify(w.deviation, null, 2))}</pre>${copyCmd(AC.commands.deviation)}`}</td>`;
      tr.after(det); wire(det);
    };
    body.querySelectorAll('#acT tbody tr[data-w]').forEach(tr => { tr.onclick = () => open(tr); tr.onkeydown = e => { if (e.key === 'Enter') open(tr); }; });
  }

  /* ======================================================= CONVERSION ======================================================= */
  const cs = { q: '', conv: '', low: false, sort: 'recall', dir: 1, bin: null, binConv: null };
  function renderConv() {
    const docs = CV.documents || [], conv = Object.keys(CV.summary || {});
    if (!docs.length) { body.innerHTML = header({ title: 'Conversion', infoHtml: M.conversion }) + empty('No document has been converted yet.'); return; }
    const p = hp(); cs.q = p.get('cq') || cs.q;
    body.innerHTML = `
    <section>${header({ title: 'Conversion coverage', infoHtml: M.conversion, sub: CV.computed ? 'Computed ' + esc(String(CV.computed_at || '').replace('T', ' ').slice(0, 16)) + '. Low is below ' + CV.low + '.' : '' })}
      ${CV.computed ? '' : `<p class="meta">Coverage has not been computed yet. Run it, then rebuild:</p>${copyCmd(CV.commands.coverage)}`}
      ${conv.length ? `<table class="t sx-plain" style="max-width:760px"><thead><tr><th class="l">Converter</th><th class="r">Documents</th><th class="r">Median recall</th><th class="r">Median precision</th><th class="r">Low recall</th><th class="r">Low precision</th></tr></thead><tbody>
      ${conv.map(c => { const s = CV.summary[c]; return `<tr><td><span class="dot" style="background:${convColour[c]}"></span> ${esc(c)}</td><td class="r">${fmt(s.documents)}</td><td class="r">${f3(s.median_recall)}</td><td class="r">${f3(s.median_precision)}</td><td class="r">${fmt(s.low_recall)}</td><td class="r">${fmt(s.low_precision)}</td></tr>`; }).join('')}</tbody></table>` : ''}
      ${Object.keys(CV.not_measured || {}).length ? `<p class="meta" style="margin-top:10px">Not measured: ${Object.entries(CV.not_measured).map(([k, v]) => esc(k) + ' <b class="num">' + fmt(v) + '</b>').join('; ')}.</p>` : ''}
    </section>
    ${conv.length ? `<section class="sx-sec">${header({ title: 'How much text survives', infoHtml: M.survival })}
      <div class="sx-hist">${conv.map(c => { const b = (CV.distribution.by_converter[c] || []), mx = Math.max(1, ...b);
        return `<div class="sx-hcard"><b>${esc(c)}</b> <span class="meta">${fmt(CV.summary[c].documents)} documents</span>
        <div class="sx-bins" role="group" aria-label="Recall histogram for ${esc(c)}">${b.map((n, i) => `<button type="button" data-conv="${esc(c)}" data-bin="${i}" class="${(i + 1) / b.length <= CV.low ? 'lo' : ''}" style="height:${Math.max(3, 100 * n / mx)}%" aria-pressed="${cs.bin === i && cs.binConv === c}" aria-label="recall ${(i / b.length).toFixed(1)} to ${((i + 1) / b.length).toFixed(1)}: ${n} documents" data-tip="${esc('recall ' + (i / b.length).toFixed(1) + ' to ' + ((i + 1) / b.length).toFixed(1) + ': ' + fmt(n))}"></button>`).join('')}</div>
        <div class="sx-axis"><span>0</span><span>recall</span><span>1</span></div></div>`; }).join('')}</div></section>
    <section class="sx-sec">${header({ title: 'Recall against precision' })}
      <div class="sx-plot">${scatter(docs)}</div>
      <div class="sx-legend">${conv.map(c => `<span><span class="dot" style="background:${convColour[c]}"></span>${esc(c)}</span>`).join('')}<span>dashed box: low on either axis</span></div></section>` : ''}
    <section class="sx-sec">${header({ title: 'Documents', sub: 'Lowest recall first: the ones to check.' })}
      <div class="sx-bar"><input type="search" id="cq" placeholder="Filter by title" aria-label="Filter by title" value="${esc(cs.q)}">
        <select id="cc" aria-label="Converter"><option value="">All converters</option>${conv.map(c => `<option ${c === cs.conv ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
        <label class="meta"><input type="checkbox" id="cl" ${cs.low ? 'checked' : ''}> only low (below ${CV.low})</label>
        ${cs.bin != null ? '<button class="chip" type="button" id="cbin" aria-pressed="true">Recall bin <span class="x">x</span></button>' : ''}<span class="meta" id="ccount"></span></div>
      <div id="clist"></div><div id="cdet"></div></section>`;
    body.querySelectorAll('.sx-bins button').forEach(b => {
      b.onclick = () => { const same = cs.bin === +b.dataset.bin && cs.binConv === b.dataset.conv; cs.bin = same ? null : +b.dataset.bin; cs.binConv = same ? null : b.dataset.conv; cs.conv = same ? '' : b.dataset.conv; renderConv(); wire(body); };
      b.onmousemove = e => H.tip(b.dataset.tip, e); b.onmouseleave = () => H.tip('');
    });
    const draw = () => {
      const n = (CV.distribution.bins || 10), q = cs.q.toLowerCase();
      const rows = docs.filter(x => (!cs.conv || x.converter === cs.conv) && (!cs.low || (x.recall != null && (x.recall < CV.low || x.precision < CV.low))) &&
        (cs.bin == null || (x.recall != null && Math.min(Math.floor(x.recall * n), n - 1) === cs.bin)) && (!q || x.title.toLowerCase().includes(q)));
      const key = { recall: x => x.recall ?? 2, precision: x => x.precision ?? 2, words: x => x.words ?? -1, title: x => x.title.toLowerCase() }[cs.sort];
      rows.sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * cs.dir);
      $('#ccount').textContent = fmt(rows.length) + ' of ' + fmt(docs.length) + ' documents';
      const th = (k, l, r) => `<th class="${r ? 'r' : 'l'}"><button class="chip" data-s="${k}" type="button" aria-label="Sort by ${l}">${l}${cs.sort === k ? (cs.dir > 0 ? ' ↑' : ' ↓') : ''}</button></th>`;
      $('#clist').innerHTML = `<table class="t"><thead><tr>${th('recall', 'Recall', 1)}${th('precision', 'Precision', 1)}${th('words', 'Words', 1)}<th class="l">Converter</th>${th('title', 'Document')}</tr></thead><tbody>
        ${rows.slice(0, 400).map(x => `<tr data-d="${esc(x.id)}" tabindex="0" aria-selected="${hp().get('conv') === x.id}"><td class="r ${x.recall != null && x.recall < CV.low ? 'sx-bad' : ''}">${f3(x.recall)}</td><td class="r ${x.precision != null && x.precision < CV.low ? 'sx-bad' : ''}">${f3(x.precision)}</td><td class="r">${x.words == null ? 'n/a' : fmt(x.words)}</td><td>${esc(x.converter)}</td><td>${esc(x.title)}</td></tr>`).join('')}</tbody></table>
        ${rows.length > 400 ? '<p class="meta">The first 400 are shown; narrow the filter.</p>' : ''}`;
      $('#clist').querySelectorAll('[data-s]').forEach(b => b.onclick = () => { cs.dir = cs.sort === b.dataset.s ? -cs.dir : 1; cs.sort = b.dataset.s; draw(); });
      $('#clist').querySelectorAll('tr[data-d]').forEach(tr => { tr.onclick = () => openDoc(tr.dataset.d); tr.onkeydown = e => { if (e.key === 'Enter') openDoc(tr.dataset.d); }; });
    };
    $('#cq').oninput = e => { cs.q = e.target.value; H.hash.set({ cq: cs.q }); draw(); };
    $('#cc').onchange = e => { cs.conv = e.target.value; if (cs.binConv !== cs.conv) { cs.bin = null; cs.binConv = null; } draw(); };
    $('#cl').onchange = e => { cs.low = e.target.checked; draw(); };
    const cb = $('#cbin'); if (cb) cb.onclick = () => { cs.bin = null; cs.binConv = null; renderConv(); wire(body); };
    draw();
    const want = p.get('conv'); if (want) openDoc(want, true);
    body.querySelectorAll('.sx-plot circle').forEach(c => { c.onclick = () => openDoc(c.dataset.d); c.onkeydown = e => { if (e.key === 'Enter') openDoc(c.dataset.d); }; c.onmousemove = e => H.tip(c.dataset.tip, e); c.onmouseleave = () => H.tip(''); });
  }

  /* Scatter of every measured document: recall (x) against precision (y), a dashed low region, marks open the panel. */
  function scatter(docs) {
    const W = 600, Hh = 420, L = 44, B = 36, T = 10, R = 10, w = W - L - R, h = Hh - T - B;
    const x = v => L + v * w, y = v => T + (1 - v) * h;
    const lowX = x(CV.low), lowY = y(CV.low);
    const marks = docs.filter(x => x.recall != null).map(m => `<circle tabindex="0" r="4" cx="${x(m.recall)}" cy="${y(m.precision)}" fill="${convColour[m.converter]}" data-d="${esc(m.id)}"
      data-tip="${esc(m.title.slice(0, 70) + ': recall ' + f3(m.recall) + ', precision ' + f3(m.precision))}" aria-label="${esc(m.title.slice(0, 70) + ', recall ' + f3(m.recall) + ', precision ' + f3(m.precision))}"></circle>`).join('');
    const ticks = [0, 0.2, 0.4, 0.6, 0.8, 1];
    return `<svg viewBox="0 0 ${W} ${Hh}" role="group" aria-label="Recall against precision, one mark per document">
      ${ticks.map(t => `<line class="gridline" x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${T + h}"></line><line class="gridline" x1="${L}" x2="${L + w}" y1="${y(t)}" y2="${y(t)}"></line>
        <text class="axis" x="${x(t)}" y="${Hh - 18}" text-anchor="middle">${t}</text><text class="axis" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join('')}
      <rect x="${L}" y="${lowY}" width="${lowX - L}" height="${T + h - lowY}" fill="none" stroke="var(--exc)" stroke-dasharray="4 3"></rect>
      <text class="axis" x="${L + w / 2}" y="${Hh - 3}" text-anchor="middle">recall</text><text class="axis" x="10" y="${T + h / 2}" transform="rotate(-90 10 ${T + h / 2})" text-anchor="middle">precision</text>
      ${marks}</svg>`;
  }

  /* Per-document panel: scores and commands from the payload; gaps and text from the lazy route when it exists. */
  async function openDoc(id, quiet) {
    const x = (CV.documents || []).find(r => r.id === id) || (CV.documents || []).find(r => r.work_id === id), host = $('#cdet'); if (!x || !host) return;
    id = x.id;
    H.hash.set({ conv: id });
    body.querySelectorAll('tr[data-d]').forEach(tr => tr.setAttribute('aria-selected', String(tr.dataset.d === id)));
    const others = (CV.converters || []).filter(c => c.accepts.includes(x.media) && c.name !== x.converter && c.available);
    const cmds = others.map(c => `factory --project ${CV.commands.slug} document convert --work ${x.work_id} --converter ${c.name}`);
    if (!others.length) cmds.unshift(CV.commands.converters);
    cmds.push(`factory --project ${CV.commands.slug} document read ${x.work_id} --document ${x.id}`);
    host.innerHTML = `<div class="card" style="margin-top:16px" tabindex="-1" id="cdetCard"><div class="sx-bar"><h3 class="h3 grow">${esc(x.title)}</h3><button class="btn" type="button" id="cdx">Close</button></div>
      <p class="meta">${x.recall == null ? 'Not measured (no comparable plain text).' : `Recall <b class="num ${x.recall < CV.low ? 'sx-bad' : ''}">${f3(x.recall)}</b> · precision <b class="num ${x.precision < CV.low ? 'sx-bad' : ''}">${f3(x.precision)}</b> · <b class="num">${fmt(x.words)}</b> words to <b class="num">${fmt(x.md_words)}</b>`}
        · converted with <b>${esc(x.converter)}</b> · ${openPaper(x.work_id)} · <a href="../conversion/doc/${esc(x.slug)}.html">Classic inspector page</a></p>
      <div id="cdetLazy"><p class="meta">Loading the original beside the extracted text.</p></div>
      <h4 class="h3" style="margin-top:14px">What to do</h4>${others.length ? `<p class="meta">Other converters that accept this format and run here: ${others.map(c => esc(c.name)).join(', ')}. Converting again adds a second conversion beside this one.</p>` : '<p class="meta">No other converter that accepts this format runs here.</p>'}
      ${cmds.map(copyCmd).join('')}</div>`;
    wire(host); $('#cdx').onclick = () => { host.innerHTML = ''; H.hash.set({ conv: '' }); body.querySelectorAll('tr[data-d]').forEach(tr => tr.setAttribute('aria-selected', 'false')); };
    if (!quiet) $('#cdetCard').scrollIntoView({ block: 'nearest' });
    const lazy = $('#cdetLazy');
    const fallback = () => { lazy.innerHTML = '<p class="meta">The original beside the extracted text, and the lost-text lists, open in the classic inspector page for now. ' +
      info('This view will load them here once the server offers <span class="mono">data/sources-doc-&lt;id&gt;.json</span>.') + '</p>'; };
    if (!HUB.served) { fallback(); return; }
    try {
      const r = await fetch('data/sources-doc-' + encodeURIComponent(id) + '.json');
      if (!r.ok) { fallback(); return; }
      const j = await r.json(), runs = (t, rs) => rs.length ? `<ul>${rs.slice(0, 30).map(g => `<li class="meta"><span class="mono">${g[0]}</span> ${esc(g[1])}</li>`).join('')}</ul>` : `<p class="meta">${t}</p>`;
      lazy.innerHTML = `<div class="sx-split"><div><h4 class="h3">Original${j.files && j.files.original ? ` <a href="${esc(j.files.original)}" target="_blank" rel="noopener">Open</a>` : ''}</h4><pre class="sx-pre">${esc(j.original_text || (j.tar_listing || 'No plain text of the original.'))}</pre></div>
        <div><h4 class="h3">Extracted Markdown${j.files && j.files.markdown ? ` <a href="${esc(j.files.markdown)}" target="_blank" rel="noopener">Raw</a>` : ''}</h4><pre class="sx-pre">${esc(String(j.markdown || '').replace(/<a id="([^"]+)"><\/a>\s*/g, '[$1] '))}</pre></div></div>
        <div class="sx-split"><div><h4 class="h3">In the original, not found in the Markdown</h4>${runs('No run of six or more words is missing.', j.lost || [])}</div>
        <div><h4 class="h3">In the Markdown, not found in the original</h4>${runs('No run of six or more words is extra.', j.added || [])}</div></div>`;
    } catch (e) { fallback(); }
  }

  /* ======================================================= STUDY DOCUMENTS ======================================================= */
  function renderDocs() {
    body.innerHTML = `
    <section>${header({ title: 'Study documents', infoHtml: M.documents, sub: DC.registered ? '' : 'Nothing is registered yet.' })}
      ${DC.registered ? `<div class="sx-kpis">${kpi(DC.registered, 'registered files')}${kpi(DC.changed, 'changed since registration', DC.changed ? 'warn' : '')}${kpi(DC.missing, 'missing', DC.missing ? 'warn' : '')}</div>
      <div class="sx-kind">${DC.kinds.map(k => `<div class="sx-kpi"><span class="n">${fmt(k.files.length)}</span><span class="l">${esc(k.title)}${k.changed ? ` · <span class="sx-warn">${fmt(k.changed)} changed</span>` : ''}${k.missing ? ` · <span class="sx-bad">${fmt(k.missing)} missing</span>` : ''}</span></div>`).join('')}</div>`
        : empty('No file is registered yet. Use <code>factory files register</code>.')}
    </section>
    ${DC.kinds.map(k => `<section class="sx-sec">${header({ title: k.title })}
      <table class="t sx-plain"><thead><tr><th class="l">File</th><th class="l">Version</th><th class="l">Registered</th><th class="l">Status</th><th class="l">Earlier versions</th></tr></thead><tbody>
      ${k.files.map(f => `<tr><td>${f.href ? `<a href="${esc(f.href)}">${esc(f.title || f.path)}</a>` : esc(f.title || f.path)}${f.outside ? ' <span class="sx-bad">outside the project</span>' : ''}<div class="meta mono">${esc(f.path)}</div></td>
        <td class="mono">v${fmt(f.version)}</td><td>${esc(f.registered)}</td>
        <td>${f.state === 'changed' ? '<span class="sx-warn">changed since registration</span>' : f.state === 'missing' ? '<span class="sx-bad">missing</span>' : 'unchanged'}</td>
        <td>${f.history.map(r => `<div class="meta mono">v${fmt(r.version)}: ${esc(r.at)}, ${esc(r.sha)}</div>`).join('')}</td></tr>`).join('')}</tbody></table></section>`).join('')}`;
  }

  show();
});
