/* Write & export page: synthesis pages (list, scope coverage, reading view), bibliography (table, BibTeX, year
   histogram), the PRISMA 2020 diagram and the wiki vault. Payload: write. Every number comes from the payload;
   downloads are Blobs of strings the service built. State in the URL hash: tab, page, year, q, sort. */
HUB.load(['shell', 'write']).then(d => {
const H = HUB.init(d.shell), {esc} = HUB, W = d.write, M = W.methods || {};
const main = H.mount({page: 'write', crumb: 'Write & export'});

document.head.insertAdjacentHTML('beforeend', `<style id="write-css">
.wtabs{margin:6px 0 18px}
.wgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:var(--gap)}
.wpage{display:block;text-align:left;width:100%;border:0;color:var(--fg);font:inherit;cursor:pointer}.wpage:hover{background:var(--raised)}
.wpage b{display:block;font-weight:600;margin-bottom:6px}.wpage .meta{margin:4px 0 0}
.wbadge{display:inline-block;font:500 var(--t-xs) var(--f-ui);padding:3px 8px;border-radius:999px;background:var(--raised);color:var(--mut);margin-right:6px}
.wbadge.warn{background:var(--exc-soft);color:var(--exc)}.wbadge.ok{color:var(--inc)}
.cov{display:flex;flex-direction:column;gap:14px}.covk{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.covk .lbl{width:84px;flex:none;color:var(--mut);font-size:var(--t-xs)}
.cell{border:0;cursor:pointer;font:500 var(--t-xs) var(--f-ui);padding:6px 9px;border-radius:var(--r-s);color:var(--fg);background:var(--raised);box-shadow:inset 0 0 0 1px var(--line)}
.cell.checked{background:var(--acc-soft);box-shadow:inset 0 0 0 1px var(--inc)}.cell.flagged,.cell.stale{background:var(--exc-soft);box-shadow:inset 0 0 0 1px var(--exc)}
.cell[disabled]{cursor:default}.cell.none{background:transparent;color:var(--dim);box-shadow:inset 0 0 0 1px var(--line);border-style:dashed}.cell:hover{outline:2px solid var(--acc)}
.leg{display:flex;flex-wrap:wrap;gap:14px;font-size:var(--t-xs);color:var(--mut);margin-top:10px}.leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.leg .checked{background:var(--inc)}.leg .flagged,.leg .stale{background:var(--exc)}.leg .none{background:var(--line)}
.wread{max-width:78ch}.wread h2{font:600 var(--t-xl) var(--f-display);margin:22px 0 8px}.wread h3{font:600 var(--t-l) var(--f-ui);margin:18px 0 6px}
.wread p,.wread li{line-height:1.6}.wread .cite{font:500 var(--t-xs) var(--f-ui);background:var(--acc-soft);color:var(--fg);border:0;border-radius:4px;padding:1px 6px;margin:0 2px;cursor:pointer}
.wread .cite:hover{outline:1px solid var(--acc)}.wflag{color:var(--exc);margin:3px 0;font-size:var(--t-s)}
table.t td.n,table.t th.n{text-align:right}table.t th button{all:unset;cursor:pointer;font-weight:600}table.t th button:hover{color:var(--acc)}
.wbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 12px}.wbar input{flex:1;min-width:200px;max-width:380px}
.whist{display:flex;align-items:flex-end;gap:3px;height:86px;margin:6px 0 16px}.whist button{all:unset;cursor:pointer;flex:1;min-width:10px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.whist i{display:block;width:100%;background:var(--acc);border-radius:3px 3px 0 0;opacity:.75}.whist button:hover i,.whist button[aria-pressed=true] i{opacity:1}.whist span{font:400 10px var(--f-mono);color:var(--dim);margin-top:3px}
pre.wbib{white-space:pre-wrap;word-break:break-word;background:var(--surface);border-radius:var(--r);padding:14px;font:12px var(--f-mono);max-height:60vh;overflow:auto}
.wsvg{background:white;color:black;border-radius:var(--r);padding:14px;overflow:auto}.wsvg svg{display:block;max-width:100%;height:auto;margin:0 auto}
.wpath{display:flex;gap:8px;align-items:center;margin:10px 0}.wpath code{flex:1;overflow-x:auto;white-space:nowrap;background:var(--surface);border-radius:var(--r-s);padding:8px 10px;font:12px var(--f-mono)}
</style>`);

const WORKS = new Map((d.shell.works || []).map(w => [w.id, w]));
const TABS = [['synthesis', 'Synthesis pages'], ['bibliography', 'Bibliography'], ['prisma', 'PRISMA diagram'], ['wiki', 'Wiki vault']];
const ST = {tab: 'synthesis', page: '', year: '', q: '', sort: 'year', rev: false};
const STATE = {checked: 'Checked', flagged: 'Flagged', stale: 'Stale', none: 'No page yet'};
const KIND = {overview: 'Whole corpus', technique: 'Technique', stage: 'Lifecycle stage', field: 'Field of science'};
const pageById = new Map((W.pages || []).map(p => [p.page_id, p]));
const readHash = () => { const p = HUB.hash.get();
  ST.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'synthesis';
  ST.page = pageById.has(p.get('page')) ? p.get('page') : ''; ST.year = p.get('year') || ''; ST.q = p.get('q') || '';
  ST.sort = ['year', 'title', 'author', 'venue'].includes(p.get('sort')) ? p.get('sort') : 'year'; ST.rev = p.get('rev') === '1'; };
const writeHash = () => HUB.hash.set({tab: ST.tab === 'synthesis' ? null : ST.tab, page: ST.page || null, year: ST.year || null, q: ST.q || null,
  sort: ST.sort === 'year' ? null : ST.sort, rev: ST.rev ? 1 : null});
const gone = key => W.errors && W.errors[key] ? `<p class="meta" role="status">This part could not be built: ${esc(W.errors[key])}</p>` : '';
const methodInfo = k => H.info('<b>What it shows</b><p><span class="k">How it\'s computed.</span> ' + esc(M[k] || '') + '</p>');

/* A string saved as a file in the browser: no route needed. */
function save(text, name, type) {
  const url = URL.createObjectURL(new Blob([text], {type}));
  const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function copy(btn, text, again) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
    () => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = again; }, 1500); },
    () => { btn.textContent = 'Select and copy'; });
}

/* ---------- synthesis ---------- */
const intro = () => H.header({title: 'Synthesis pages', infoHtml: '<b>What it shows</b><p>Pages a model wrote from the recorded, quoted rows. They are interpretations, never evidence.</p>' +
  '<p><span class="k">How to read it.</span> Each page was checked when recorded and is marked stale when its rows change. To add or revise one, ask Claude for the <b>rf-synthesize</b> skill on a scope.</p>' +
  '<p><span class="k">How it\'s computed.</span> ' + esc(M.pages || '') + '</p>',
  sub: 'Model-written, quote-checked. An interpretation, not evidence.'});

function coverage() {
  const C = W.coverage || {}, T = C.tally || {};
  if (!C.total) return '';
  const rows = (C.kinds || []).map(k => `<div class="covk"><span class="lbl">${esc(KIND[k] || k)}</span>${W.scopes.filter(s => s.kind === k).map(s =>
    `<button type="button" class="cell ${esc(s.state)}" ${s.page_id ? '' : 'disabled'} data-scope="${esc(s.scope)}" title="${esc(STATE[s.state] + ' · ' + s.works + ' papers')}">${esc(s.value || 'overview')} <span class="num">${esc(s.works)}</span></button>`).join('')}</div>`).join('');
  return H.header({title: 'Coverage', infoHtml: '<b>What it shows</b><p>Which scopes already have a page, and whether it holds up.</p><p><span class="k">How it\'s computed.</span> ' + esc(M.coverage || '') + '</p>',
    sub: ['checked', 'flagged', 'stale', 'none'].map(s => esc(STATE[s]) + ' ' + esc(T[s] || 0)).join(' · ')}) +
    `<div class="card cov">${rows}<div class="leg">${['checked', 'flagged', 'stale', 'none'].map(s => `<span><i class="${s}"></i>${esc(STATE[s])}</span>`).join('')}</div></div>`;
}
function cards() {
  if (!W.pages.length) return '<p class="meta">No page is recorded yet.</p>';
  return `<div class="wgrid">${W.pages.map(p => `<button type="button" class="card wpage" data-page="${esc(p.page_id)}"><b>${esc(p.title)}</b>
    <span class="wbadge">Model-written</span><span class="wbadge ${p.stale || p.flags.length ? 'warn' : 'ok'}">${esc(STATE[p.state])}</span>${p.flags.length ? `<span class="wbadge warn">${esc(p.flags.length)} flagged</span>` : ''}
    <p class="meta">${esc(p.scope)} · ${esc(p.who)} · ${esc(p.words)} words</p></button>`).join('')}</div>`;
}
function scopesTable() {
  if (!W.scopes.length) return '';
  return H.header({title: 'Scopes', infoHtml: '<b>What it shows</b><p>Every scope a page can be written for.</p><p><span class="k">How it\'s computed.</span> ' + esc(M.scopes || '') + '</p>',
    sub: 'Open the papers of a scope, or read its page.'}) +
    `<div class="card"><table class="t"><thead><tr><th>Scope</th><th class="n">Papers</th><th>Page</th></tr></thead><tbody>${W.scopes.map(s => {
      const href = s.value ? 'corpus.html#' + encodeURIComponent(s.kind) + '=' + encodeURIComponent(s.value) : 'corpus.html';
      return `<tr><td><a href="${esc(href)}">${esc(s.scope)}</a></td><td class="n">${esc(s.works)}</td><td>${s.page_id ?
        `<a href="#" data-page="${esc(s.page_id)}">Read</a> ${s.state === 'stale' ? '<span class="wbadge warn">Stale</span>' : ''}` : '<span class="meta">No page yet</span>'}</td></tr>`; }).join('')}</tbody></table>
      <p class="meta">To write or revise a page, ask Claude for the <b>rf-synthesize</b> skill on a scope, for example <code>technique=…</code>.</p></div>`;
}
function inline(parts, cites) {
  return parts.map(p => {
    if (p.t != null) return esc(p.t);
    if (p.b != null) return '<b>' + esc(p.b) + '</b>';
    const id = cites[p.cite], w = id && WORKS.get(id), label = (w ? w.title : p.cite).slice(0, 34);
    return id ? `<button type="button" class="cite" data-open="${esc(id)}" title="${esc(w ? w.title : p.cite)}">${esc(label)}</button>` : `<span class="meta">[${esc(p.cite)}]</span>`;
  }).join('');
}
function reader(p) {
  const c = p.check, body = p.blocks.map(b => b.k === 'ul' ? '<ul>' + b.items.map(i => '<li>' + inline(i, p.cites) + '</li>').join('') + '</ul>'
    : b.k === 'h' ? `<h${b.level + 1}>${inline(b.parts, p.cites)}</h${b.level + 1}>` : '<p>' + inline(b.parts, p.cites) + '</p>').join('');
  return `<p><a href="#" id="wback">← All pages</a></p>${H.header({level: 1, title: p.title, kicker: esc(p.scope),
    infoHtml: '<b>What it shows</b><p>The page as recorded. Each citation opens the paper with the quotes behind it.</p><p><span class="k">How it\'s computed.</span> ' + esc(M.pages || '') + '</p>',
    sub: `<span class="wbadge">Model-written</span><span class="wbadge ${p.stale || p.flags.length ? 'warn' : 'ok'}">${esc(STATE[p.state])}</span>${esc(p.who)} · ${esc(p.recorded_at.slice(0, 16))} · ${esc(p.words)} words · ${esc(p.page_id)}`})}
    ${p.stale ? '<p class="wflag">The rows changed since this page was written: ask for a revision.</p>' : ''}
    <p class="note">Checked when recorded: ${esc(c.cited_sentences)} cited sentences, ${esc(c.quotes_checked)} quotations verified verbatim, ${esc(c.numbers_checked)} numbers checked against the computed statistics.</p>
    ${p.flags.map(f => `<div class="wflag">Flag: ${esc(f.sentence)}</div>`).join('')}<div class="wread">${body}</div>`;
}
function synthesis() {
  if (ST.page) return reader(pageById.get(ST.page));
  return intro() + gone('pages') + cards() + coverage() + scopesTable();
}

/* ---------- bibliography ---------- */
function bibRows() {
  const B = W.bibliography, q = ST.q.toLowerCase();
  const rows = B.entries.filter(e => (!ST.year || e.year === ST.year) && (!q || (e.title + ' ' + e.author + ' ' + e.year + ' ' + e.venue + ' ' + e.key).toLowerCase().includes(q)));
  const dir = ST.rev ? -1 : 1, by = {year: e => +e.year || 0, title: e => e.title.toLowerCase(), author: e => e.author.toLowerCase(), venue: e => e.venue.toLowerCase()}[ST.sort];
  const base = ST.sort === 'year' ? -1 : 1;
  return rows.sort((a, b) => { const x = by(a), y = by(b); return (x < y ? -1 : x > y ? 1 : 0) * base * dir || a.title.localeCompare(b.title); });
}
function hist() {
  const Y = W.bibliography.years, top = Math.max(1, ...Y.map(y => y.n));
  return `<div class="whist" role="group" aria-label="Entries per year">${Y.map(y => `<button type="button" data-year="${esc(y.year)}" aria-pressed="${ST.year === String(y.year)}" title="${esc(y.year + ': ' + y.n)}"><i style="height:${Math.max(4, Math.round(100 * y.n / top))}%"></i><span>${esc(String(y.year).slice(2))}</span></button>`).join('')}</div>`;
}
function bibTable(host) {
  const B = W.bibliography, rows = bibRows();
  const dir = k => k === 'year' ? (ST.rev ? ' ↑' : ' ↓') : (ST.rev ? ' ↓' : ' ↑');
  host.innerHTML = `<div class="wbar"><input type="search" id="bq" class="q" placeholder="Filter by title, author, year, venue" aria-label="Filter" value="${esc(ST.q)}">
    <span class="meta" role="status">${esc(rows.length)} of ${esc(B.count)} papers</span>${ST.year ? `<button type="button" class="chip" id="byear" aria-pressed="true">${esc(ST.year)} <span class="x">×</span></button>` : ''}</div>
    <div class="card"><table class="t"><thead><tr>${[['year', 'Year'], ['title', 'Title'], ['author', 'First author'], ['venue', 'Venue']].map(([k, l]) =>
      `<th><button type="button" data-sort="${k}">${l}${ST.sort === k ? dir(k) : ''}</button></th>`).join('')}<th>Key</th></tr></thead><tbody>${rows.map(e => `<tr><td class="num">${esc(e.year)}</td><td>${e.id ?
      `<a href="#" data-open="${esc(e.id)}">${esc(e.title)}</a>` : esc(e.title)}</td><td>${esc(e.author)}${e.more ? ' ' + esc(e.more) : ''}</td><td>${esc(e.venue)}</td><td class="meta">${esc(e.key)}</td></tr>`).join('')}</tbody></table></div>`;
  const q = host.querySelector('#bq');
  q.oninput = () => { ST.q = q.value; writeHash(); const pos = q.selectionStart; bibTable(host); const n = host.querySelector('#bq'); n.focus(); n.setSelectionRange(pos, pos); };
  host.querySelectorAll('[data-sort]').forEach(b => b.onclick = () => { if (ST.sort === b.dataset.sort) ST.rev = !ST.rev; else { ST.sort = b.dataset.sort; ST.rev = false; } writeHash(); bibTable(host); });
  const by = host.querySelector('#byear'); if (by) by.onclick = () => { ST.year = ''; writeHash(); bibTable(host); histHost(); };
  host.querySelectorAll('[data-open]').forEach(a => a.onclick = e => { e.preventDefault(); H.openDrawer(a.dataset.open); });
}
function histHost() { const h = $q('#whist'); if (h) { h.innerHTML = hist(); bindHist(h); } }
const $q = s => main.querySelector(s);
function bindHist(h) { h.querySelectorAll('[data-year]').forEach(b => b.onclick = () => { ST.year = ST.year === b.dataset.year ? '' : b.dataset.year; writeHash(); histHost(); bibTable($q('#btable')); }); }
function bibliography() {
  const B = W.bibliography;
  const head = H.header({title: 'Bibliography', infoHtml: '<b>What it shows</b><p>The included works of the review as a list and as BibTeX for a reference manager.</p><p><span class="k">How it\'s computed.</span> ' + esc(M.bibliography || '') + '</p>',
    sub: 'Entries are the papers that made it through screening.'});
  if (!B) return head + gone('bibliography') + '<p class="meta">The bibliography appears once papers are included.</p>';
  return head + `<div class="wbar"><button type="button" class="btn primary" id="bdl">Download .bib</button><button type="button" class="btn" id="bcopy">Copy BibTeX</button>
    <button type="button" class="btn" id="bshow" aria-pressed="false">Show BibTeX</button></div>
    ${B.years.length ? `<div class="meta">Papers per year${B.undated ? ' (' + esc(B.undated) + ' undated)' : ''}</div><div id="whist">${hist()}</div>` : ''}
    <div id="btable"></div><pre class="wbib" id="braw" hidden>${esc(B.bibtex)}</pre>`;
}
function bindBib() {
  const B = W.bibliography; if (!B) return;
  bibTable($q('#btable')); const h = $q('#whist'); if (h) bindHist(h);
  $q('#bdl').onclick = () => save(B.bibtex, B.filename, 'application/x-bibtex');
  const c = $q('#bcopy'); c.onclick = () => copy(c, B.bibtex, 'Copy BibTeX');
  const s = $q('#bshow'); s.onclick = () => { const raw = $q('#braw'); raw.hidden = !raw.hidden; s.setAttribute('aria-pressed', String(!raw.hidden)); s.textContent = raw.hidden ? 'Show BibTeX' : 'Hide BibTeX'; };
}

/* ---------- PRISMA ---------- */
function prisma() {
  const P = W.prisma;
  const head = H.header({title: 'PRISMA diagram', infoHtml: '<b>What it shows</b><p>The standard PRISMA 2020 flow of the review, for a paper or a registration.</p><p><span class="k">How it\'s computed.</span> ' + esc(M.prisma || '') + '</p>',
    sub: 'The same numbers as the Flow page, in the standard drawing.'});
  if (!P) return head + gone('prisma') + '<p class="meta">The diagram appears once records are screened.</p>';
  return head + `<div class="wbar"><button type="button" class="btn primary" id="pdl">Download ${esc(P.filename)}</button><a class="btn" href="flow.html">Open the flow</a></div><div class="wsvg" id="psvg">${P.svg}</div>`;
}
/* ---------- wiki ---------- */
function wiki() {
  const K = W.wiki;
  const head = H.header({title: 'Wiki vault', infoHtml: '<b>What it shows</b><p>An Obsidian vault of the corpus: one note per paper and per category, a timeline, an index, and the synthesis pages marked as model-written.</p><p><span class="k">How it\'s computed.</span> ' + esc(M.wiki || '') + '</p>',
    sub: 'Open the folder as a vault in Obsidian.'});
  if (!K) return head + gone('wiki');
  return head + `<div class="card"><p>Open the folder as a vault, start at <code>${esc(K.start)}</code> and use the graph view (Ctrl+G). Every placement in a note shows the quote behind it.</p>
    <div class="wpath"><code id="wpath">${esc(K.path)}</code><button type="button" class="btn" id="wcopy">Copy path</button></div>
    <p class="meta">${esc(K.works)} papers, coded in pass A. ${K.built ? 'The vault is built.' : 'The vault is not built yet; the classic hub builds it on demand.'}</p>
    <div class="wbar"><a class="btn" href="../#wiki">Open the classic wiki</a><button type="button" class="btn" disabled>Download vault (zip)</button>
    ${H.info('A zip download needs a server route that packs the vault; it is not wired yet. Until then open the folder directly or use the classic wiki.', 'Why the download is off')}</div></div>`;
}

/* ---------- shell of the page ---------- */
function render() {
  const body = {synthesis, bibliography, prisma, wiki}[ST.tab]();
  main.innerHTML = H.header({level: 1, title: 'Write & export', sub: 'Pages, bibliography, diagram and vault.'}) +
    `<div class="seg wtabs" role="tablist">${TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-pressed="${ST.tab === k}">${esc(l)}</button>`).join('')}</div><div id="wbody">${body}</div>`;
  main.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { ST.tab = b.dataset.tab; ST.page = ''; writeHash(); render(); });
  main.querySelectorAll('[data-page]').forEach(b => b.onclick = e => { e.preventDefault(); ST.page = b.dataset.page; writeHash(); render(); window.scrollTo(0, 0); });
  main.querySelectorAll('[data-scope]').forEach(b => b.onclick = () => { const s = W.scopes.find(x => x.scope === b.dataset.scope); if (s && s.page_id) { ST.page = s.page_id; writeHash(); render(); window.scrollTo(0, 0); } });
  main.querySelectorAll('.cite[data-open]').forEach(b => b.onclick = () => H.openDrawer(b.dataset.open));
  const back = $q('#wback'); if (back) back.onclick = e => { e.preventDefault(); ST.page = ''; writeHash(); render(); };
  if (ST.tab === 'bibliography') bindBib();
  if (ST.tab === 'prisma' && W.prisma) $q('#pdl').onclick = () => save(W.prisma.svg, W.prisma.filename, 'image/svg+xml');
  if (ST.tab === 'wiki' && W.wiki) { const c = $q('#wcopy'); c.onclick = () => copy(c, W.wiki.path, 'Copy path'); }
}
readHash(); render();
window.addEventListener('hashchange', () => { readHash(); render(); });
});
