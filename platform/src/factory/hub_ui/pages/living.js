/* Living review page. Payloads: shell (as-of stamp) and living (feed river, horizon, heartbeat, methods,
   from services/hub_living.py). Every number comes from the payloads. Tabs: Feed, Updates, By day, How current, Heartbeat.
   Acts (served only, each behind an inline confirm, never on load): feed react / add / configure, watch configure, close week,
   add a link, and the hub-level feed run / refetch with a bounded runner poll. */
HUB.load(['shell', 'living']).then(d => {
  const H = HUB.init(d.shell);
  const L = d.living || {};
  const main = H.mount({ page: 'living', crumb: 'Living review' });
  const { esc, fmt } = H;
  const M = L.methods || {};
  const RIV = L.feed_river || { total: 0, days: [] };
  const HOR = L.horizon || { sources: [], years: [] };
  const HB = L.heartbeat || { total: 0, days: [], family_totals: {} };
  const FAMS = L.families || [];
  const FEED = L.feed || { cards: [], further: [], reactions: { over_time: [], by_category: [] } };
  const UPD = L.updates || { additions: [], growth: [], watch: { sources: [] }, routes: {}, included_sources: [] };
  const SLUG = d.shell.slug || '';
  const SHELL_IDS = new Set((d.shell.works || []).map(w => w.id));

  if (!document.getElementById('lv-style')) {
    const st = document.createElement('style'); st.id = 'lv-style';
    st.textContent = `
.lv-lead{max-width:44ch;margin:14px 0 0}
.lv-tabs{margin:22px 0 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.lv-card{padding:18px 18px 12px}
.lv-svg{display:block;width:100%;height:auto}
.lv-svg .bar{cursor:pointer}
.lv-svg .bar:hover rect.b,.lv-svg .bar:focus rect.b{opacity:.8}
.lv-svg .bar:focus{outline:none}
.lv-svg .sel{stroke:var(--acc);stroke-width:2;fill:none}
.lv-legend{display:flex;flex-wrap:wrap;gap:16px;margin:8px 0 4px;font:400 var(--t-xs) var(--f-ui);color:var(--mut);align-items:center}
.lv-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.lv-day{margin-top:var(--gap)}
.lv-day .stats{display:flex;flex-wrap:wrap;gap:6px 22px;margin:6px 0 12px}
.lv-day .stats b{font:500 var(--t-m) var(--f-mono);color:var(--fg)}
.lv-day .stats span{color:var(--mut);font-size:var(--t-s)}
.lv-list{list-style:none;margin:0;padding:0}
.lv-list li{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:12px;align-items:baseline;padding:9px 4px;border-top:1px solid var(--hair)}
.lv-list .rk{font:500 var(--t-s) var(--f-mono);color:var(--mut);text-align:right}
.lv-list .rk.none{color:var(--dim)}
.lv-list a{color:var(--fg);text-decoration:none}.lv-list a:hover{color:var(--acc);text-decoration:underline}
.lv-list .sc{display:block;font:400 var(--t-xs) var(--f-mono);color:var(--dim);margin-top:2px}
.lv-react{font:500 var(--t-xs) var(--f-ui);color:var(--mut);white-space:nowrap;display:inline-flex;gap:5px;align-items:center}
.lv-react svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.7}
.lv-react.like,.lv-react.save{color:var(--inc)}.lv-react.dislike{color:var(--exc)}
.lv-react.sent{color:var(--acc)}
.lv-empty{color:var(--dim);font:400 var(--t-m) var(--f-ui);padding:36px 8px;text-align:center}
.lv-src{display:grid;grid-template-columns:110px minmax(0,1fr) 150px;gap:14px;align-items:center;padding:12px 0;border-top:1px solid var(--hair)}
.lv-src:first-child{border-top:0}
.lv-src .nm{font:500 var(--t-s) var(--f-ui)}
.lv-src .bhind{font:500 var(--t-s) var(--f-mono);text-align:right;color:var(--fg)}
.lv-src .tr{position:relative;height:28px}
.lv-hb{display:grid;grid-template-columns:minmax(0,auto) minmax(260px,1fr);gap:var(--gap);align-items:start}.lv-hb .lv-day{margin-top:0}
.lv-hb-head{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.lv-hb-wrap{overflow-x:auto;padding-bottom:6px}
.lv-hb-wrap svg{display:block}
.lv-hb-wrap rect.cell{cursor:pointer}
.lv-hb-wrap rect.cell:hover,.lv-hb-wrap rect.cell.on{stroke:var(--acc);stroke-width:2}
.lv-fam{display:grid;grid-template-columns:110px minmax(0,1fr) 70px;gap:8px;align-items:center;font:400 var(--t-s) var(--f-ui);padding:2px 0}
.lv-fam .tr{height:8px;background:var(--raised);border-radius:2px;overflow:hidden}.lv-fam .tr i{display:block;height:100%;background:var(--acc)}
.lv-fam .v{text-align:right;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}

.lv-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 var(--gap)}
.lv-bar .run{color:var(--mut);font:400 var(--t-s) var(--f-ui)}
.lv-kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin:0 0 var(--gap)}
.lv-kpis .k{padding:12px 14px}.lv-kpis .k b{display:block;font:500 var(--t-l) var(--f-mono);color:var(--fg)}.lv-kpis .k span{color:var(--mut);font:400 var(--t-xs) var(--f-ui)}
.lv-tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}
.lv-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px;margin:0}
.lv-cards.list{grid-template-columns:1fr}
.lv-pc{padding:14px 16px;display:flex;flex-direction:column;min-width:0}
.lv-pc.beyond{border-left:3px solid var(--line)}
.lv-pc .hd{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.lv-pc .hd .rk{color:var(--acc);font-weight:500}
.lv-pc h3{margin:6px 0;font:500 var(--t-m) var(--f-ui)}.lv-pc h3 a{color:var(--fg);text-decoration:none}.lv-pc h3 a:hover{color:var(--acc);text-decoration:underline}
.lv-pc .abs{color:var(--mut);font:400 var(--t-s) var(--f-ui);margin:6px 0;display:-webkit-box;-webkit-line-clamp:3;line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.lv-pc.open .abs{display:block;overflow:visible}
.lv-pc .au{display:none;color:var(--dim);font:400 var(--t-xs) var(--f-ui)}.lv-pc.open .au{display:block}
.lv-pc .acts{margin-top:auto;padding-top:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.lv-pc .msg,.lv-msg{color:var(--mut);font:400 var(--t-s) var(--f-ui)}
.lv-badge{border:1px solid var(--line);border-radius:10px;padding:0 7px;font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.lv-more{margin:14px 0}
.lv-form{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:8px 0}
.lv-form label{display:flex;flex-direction:column;gap:3px;font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.lv-form input[type=text],.lv-form input[type=number],.lv-form input[type=date]{font:400 var(--t-s) var(--f-ui);padding:5px 8px;background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:6px}
.lv-form .chk{flex-direction:row;align-items:center;gap:6px;font-size:var(--t-s);color:var(--fg)}
.lv-tbl{width:100%;border-collapse:collapse;font:400 var(--t-s) var(--f-ui)}
.lv-tbl th{text-align:left;color:var(--mut);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--hair)}
.lv-tbl td{padding:7px 8px;border-top:1px solid var(--hair);vertical-align:top}
.lv-tbl .num{text-align:right;font-family:var(--f-mono)}
.lv-tbl a,.lv-tbl .lnk{color:var(--fg);background:none;border:0;padding:0;font:inherit;text-align:left;cursor:pointer;text-decoration:none}.lv-tbl .lnk:hover{color:var(--acc);text-decoration:underline}
.lv-sec{margin-top:var(--gap)}
.lv-cat{display:grid;grid-template-columns:90px minmax(0,1fr) 120px;gap:10px;align-items:center;padding:4px 0;font:400 var(--t-s) var(--f-ui)}
.lv-cat .tr{display:flex;height:10px;background:var(--raised);border-radius:2px;overflow:hidden}.lv-cat .tr i{display:block;height:100%}
.lv-cat .v{font:400 var(--t-xs) var(--f-mono);color:var(--mut);text-align:right}
@media (max-width:760px){.lv-cards{grid-template-columns:1fr}.lv-cat{grid-template-columns:70px minmax(0,1fr)}.lv-cat .v{grid-column:1 / -1;text-align:left}}
@media (max-width:1000px){.lv-hb{grid-template-columns:minmax(0,1fr)}}
@media (max-width:760px){.lv-scroll{overflow-x:auto}.lv-scroll svg{min-width:640px}.lv-src{grid-template-columns:70px minmax(0,1fr);}.lv-src .bhind{grid-column:1 / -1;text-align:left}.lv-list li{grid-template-columns:30px minmax(0,1fr)}.lv-list li .lv-react{grid-column:2}}`;
    document.head.appendChild(st);
  }

  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const utc = s => { const [y, m, d] = s.slice(0, 10).split('-').map(Number); return Date.UTC(y, m - 1, d); };
  const iso = t => new Date(t).toISOString().slice(0, 10);
  const DAY = 86400000;
  const dlab = s => { const t = new Date(utc(s)); return t.getUTCDate() + ' ' + MON[t.getUTCMonth()]; };
  const dlabY = s => dlab(s) + ' ' + s.slice(0, 4);
  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
  const FAM_LABEL = { search: 'Search', screening: 'Screening', acquisition: 'Acquisition', conversion: 'Conversion', mining: 'Mining', references: 'References', feed: 'Feed', other: 'Other' };
  const SRC = { arxiv: 'arXiv', openalex: 'OpenAlex' };
  const srcName = s => SRC[s] || H.pretty(s);
  const famLabel = f => FAM_LABEL[f] || H.pretty(f);
  const ICO = {
    like: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
    dislike: '<path d="M6 6l12 12M18 6L6 18"/>',
    save: '<path d="M6 4h12v16l-6-4-6 4z"/>',
    dismiss: '<path d="M5 12h14"/>',
    sent: '<path d="M4 12l16-7-6 16-3-6z"/>',
  };
  const RWORD = { like: 'Liked', dislike: 'Disliked', save: 'Saved', dismiss: 'Dismissed' };
  const react = (k, word) => `<span class="lv-react ${k}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICO[k] || ICO.dismiss}</svg>${esc(word || RWORD[k] || H.pretty(k))}</span>`;
  const panel = (what, read, how) => `<b>What it shows</b> ${what}${read ? `<p><span class=k>How to read it.</span> ${read}</p>` : ''}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const empty = msg => `<div class="card lv-empty">${esc(msg)}</div>`;

  const TABS = [['feed', 'Feed'], ['updates', 'Updates'], ['river', 'By day'], ['horizon', 'How current'], ['beat', 'Heartbeat']];
  const st = { tab: 'feed', day: null, fam: 'all', route: 'all', order: 'rank', layout: 'grid' };
  try { st.layout = localStorage.getItem('hub-living-layout') === 'list' ? 'list' : 'grid'; } catch (e) { /* storage may be blocked */ }
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'feed';
    st.day = p.get('day') || null; st.fam = p.get('fam') || 'all';
    st.route = p.get('route') || 'all'; st.order = ['new', 'old'].includes(p.get('order')) ? p.get('order') : 'rank';
  };
  const go = o => { H.hash.set(o); readHash(); render(); };


  /* ---------------- acts ---------------- */
  /* One inline-confirmed act: the host shows the question, then the server's structured answer (or refusal). Never runs on load. */
  const act = (host, question, path, body, done, opts) => {
    if (!HUB.served) { host.textContent = 'Available in the live hub.'; return; }
    HUB.confirm(host, question, () => HUB.post(path, body, opts).then(r => {
      host.textContent = r.ok ? done(r.json || {}) : 'Refused: ' + (r.message || 'refused');
      return r;
    }));
  };
  const off = HUB.served ? '' : ' disabled title="Available in the live hub"';
  const OFFNOTE = 'Acts are off in the static build; open the hub with the server to use them.';
  const LINKMSG = j => j.duplicate ? 'Already in the inbox (' + j.item_id + ').' : 'Added to the inbox (' + j.item_id + ').';

  function addLinkBox() {
    return `<section class="card lv-card lv-sec"><h3 class="h3">Add a link ${H.info('Puts one link or identifier (DOI, arXiv id, URL) in this project’s inbox as your own entry. Nothing is fetched here; the pipeline picks it up. See the work queue on the <a href="pipeline.html">Pipeline</a> page.', 'About adding a link')}</h3>
      <div class="lv-form"><label>Link or identifier<input type="text" id="lvLink" size="34" placeholder="10.1000/xyz or arxiv.org/abs/…"${off}></label>
      <label>Note (optional)<input type="text" id="lvLinkNote" size="24"${off}></label>
      <button type="button" class="btn primary" id="lvLinkGo"${off}>Add to the inbox (as you)</button></div>
      <div class="lv-msg" id="lvLinkMsg" aria-live="polite">${HUB.served ? '' : OFFNOTE}</div></section>`;
  }
  function wireAddLink() {
    const go = main.querySelector('#lvLinkGo'); if (!go) return;
    go.onclick = () => {
      const v = main.querySelector('#lvLink').value.trim(), note = main.querySelector('#lvLinkNote').value.trim();
      const host = main.querySelector('#lvLinkMsg');
      if (!v) { host.textContent = 'Enter a link or identifier first.'; return; }
      act(host, 'Add this link to the inbox?', '/api/inbox/add', { value: v, note: note || null }, LINKMSG);
    };
  }

  /* ---------------- Feed ---------------- */
  const RUN = { available: null, running: false, last: null, polls: 0, timer: null };
  const runLine = () => {
    if (RUN.available === false) return 'The feed runner is off (start the hub with the feed on).';
    if (RUN.available === null) return HUB.served ? 'Checking the runner…' : OFFNOTE;
    if (RUN.running) return 'A run is in progress.';
    const l = RUN.last; if (!l) return 'No run yet.';
    if (l.error) return 'Last run failed: ' + l.error;
    const parts = (l.outcomes || []).map(o => { const r = o.result; return o.slug + ': ' + (o.error ? o.error : r ? `${r.status}, ${r.fetched} fetched, ${r.shown} shown${r.cached ? ' (cache)' : ''}` : 'skipped'); });
    return 'Last run' + (l.refetch ? ' (refetch)' : '') + ': exit ' + l.exit_code + (parts.length ? ' (' + parts.join('; ') + ')' : '');
  };
  const paintRun = () => {
    const ln = main.querySelector('#lvRunLine'); if (ln) ln.textContent = runLine();
    main.querySelectorAll('[data-run]').forEach(b => { b.disabled = !HUB.served || !RUN.available || RUN.running; });
  };
  /* Bounded poll: at most 90 reads per run, one every 2 s, paused while the tab is hidden. Reading only; never starts a run. */
  function pollRunner() {
    if (!HUB.served) return;
    clearTimeout(RUN.timer);
    if (document.hidden) return;
    fetch('/api/feed/runner').then(r => r.json()).then(s => {
      RUN.available = !!s.available; RUN.running = !!s.running; RUN.last = s.last || null; paintRun();
      if (RUN.running && ++RUN.polls < 90) RUN.timer = setTimeout(pollRunner, 2000);
    }).catch(() => { RUN.available = false; paintRun(); });
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && RUN.running) pollRunner(); });

  const dayOf = s => s ? dlabY(s) : 'none';
  function statusBlock() {
    const S = FEED.status, LF = FEED.last_fetch;
    if (FEED.error) return `<div class="card lv-empty">Could not read this project’s feed: ${esc(FEED.error)}</div>`;
    if (!S || !FEED.configured) return `<div class="card lv-empty">The feed is not configured for this project. Accept the proposed categories below to start it.</div>`;
    const k = (v, l) => `<div class="card k"><b>${v}</b><span>${l}</span></div>`;
    const refs = FEED.references ? esc(H.pretty(FEED.references)) + (FEED.reference_count != null ? ', ' + plural(FEED.reference_count, 'reference', 'references') : '') : 'not yet used';
    return `<div class="lv-kpis">
      ${k(dayOf(S.last_complete_window_to), 'Last complete fetch')}
      ${k(LF ? `${dlab(LF.window_from)} to ${dlab(LF.window_to)}${LF.complete ? '' : ' (incomplete)'}` : 'none', 'Window of the latest fetch')}
      ${k(refs, 'Reference set of the latest ranking')}
      ${k(`${fmt(S.held_entries)} of ${fmt(S.entries)}`, 'Entries held back')}
      ${k(esc((FEED.config.categories || []).join(', ')), 'Categories')}
      ${k(S.due ? 'Due now' : 'Not due', `Next window from ${dayOf(S.next_window_from)}`)}
      ${k(FEED.ranking_id ? `${fmt(FEED.total_shown)} of ${fmt(FEED.total_ranked)}` : 'none', FEED.ranking_id ? 'Shown of ranked' : 'No ranking yet')}
      ${k(`${fmt(FEED.config.shown_per_cycle)} · ${fmt(FEED.config.interval_days)} d`, 'Shown per cycle · interval')}</div>`;
  }

  const cardHtml = c => {
    const open = c.abstract ? `<p class="abs">${esc(c.abstract)}</p>${c.authors.length ? `<p class="au">${esc(c.authors.join(', '))}</p>` : ''}<button type="button" class="btn tog" aria-expanded="false">More</button>` : '';
    const acts = ['like', 'dislike'].map(a => `<button type="button" class="btn" data-fa="${a}"${off}>${a === 'like' ? 'Like' : 'Dislike'}</button>`).join('') + `<button type="button" class="btn" data-fa="add"${off}>Add to inbox</button>`;
    return `<article class="card lv-pc${c.beyond ? ' beyond' : ''}" data-id="${esc(c.entry_id)}" data-rank="${c.rank}" data-sub="${esc(c.submitted)}"${c.beyond ? ' hidden' : ''}>
      <div class="hd"><span class="rk">#${fmt(c.rank)}</span><span>${c.score.toFixed(3)}</span>${c.explore ? '<span class="lv-badge">explore</span>' : ''}${c.beyond ? '<span class="lv-badge">beyond the shown list</span>' : ''}${c.sent ? '<span class="lv-badge">added</span>' : ''}${c.submitted ? `<span>${esc(c.submitted)}</span>` : ''}${c.category ? `<span>${esc(c.category)}</span>` : ''}</div>
      <h3><a href="https://arxiv.org/abs/${esc(c.entry_id)}" target="_blank" rel="noopener">${esc(c.title)}</a></h3>
      ${c.beyond ? '' : `<div class="meta">Nearest core work: ${c.nearest ? esc(c.nearest) : 'none nearby'}</div>`}
      <div class="meta">Reaction: ${c.reaction ? esc((RWORD[c.reaction] || c.reaction).toLowerCase()) : 'none'}</div>
      ${open}
      <div class="meta"><a href="https://arxiv.org/abs/${esc(c.entry_id)}" target="_blank" rel="noopener">abstract page</a> · <a href="https://arxiv.org/pdf/${esc(c.entry_id)}" target="_blank" rel="noopener">pdf</a></div>
      <div class="acts">${acts}<span class="msg" aria-live="polite"></span></div></article>`;
  };
  const sortCards = list => {
    const a = list.slice();
    if (st.order === 'rank') return a.sort((x, y) => x.rank - y.rank);
    return a.sort((x, y) => (!x.submitted || !y.submitted) ? (x.submitted ? -1 : y.submitted ? 1 : x.rank - y.rank)
      : x.submitted === y.submitted ? x.rank - y.rank : (st.order === 'old' ? (x.submitted < y.submitted ? -1 : 1) : (x.submitted < y.submitted ? 1 : -1)));
  };

  function reactionViz() {
    const R = FEED.reactions || {}, T = R.over_time || [], C = R.by_category || [];
    if (!R.total) return `<section class="card lv-card lv-sec"><h3 class="h3">Your reactions ${H.info(panel('How you reacted to feed papers, over time and by arXiv category.', '', M.reactions), 'About reactions')}</h3><div class="lv-empty">No reactions yet. Like or dislike a paper above to start the picture.</div></section>`;
    const mx = Math.max(...T.map(x => x.total), 1), W = 600, Hh = 120, B = 96, step = (W - 30) / Math.max(T.length, 1), bw = Math.min(40, step * .7);
    const KIND = [['like', 'var(--inc)'], ['save', 'var(--acc)'], ['dismiss', 'var(--dim)'], ['dislike', 'var(--exc)']];
    const bars = T.map((x, i) => {
      let yy = B; const bx = 30 + step * i + (step - bw) / 2;
      const segs = KIND.map(([k, col]) => { const v = x.kinds[k] || 0; if (!v) return ''; const h = (B - 10) * v / mx; yy -= h; return `<rect x="${bx}" y="${yy}" width="${bw}" height="${h}" fill="${col}"><title>${dlabY(x.day)}: ${v} ${k}</title></rect>`; }).join('');
      return segs + `<text class="axis" x="${bx + bw / 2}" y="${B + 14}" text-anchor="middle">${dlab(x.day)}</text>`;
    }).join('');
    const cats = C.map(c => `<div class="lv-cat"><span>${esc(c.category)}</span><span class="tr" role="img" aria-label="${c.accepted} accepted, ${c.rejected} rejected of ${c.reacted}"><i style="width:${(100 * c.accept_rate).toFixed(1)}%;background:var(--inc)"></i><i style="width:${(100 * (1 - c.accept_rate - c.reject_rate)).toFixed(1)}%;background:var(--raised)"></i><i style="width:${(100 * c.reject_rate).toFixed(1)}%;background:var(--exc)"></i></span><span class="v">${fmt(c.accepted)} yes · ${fmt(c.rejected)} no · ${fmt(c.reacted)} total</span></div>`).join('');
    return `<section class="card lv-card lv-sec"><h3 class="h3">Your reactions ${H.info(panel('How you reacted to feed papers: per day, and the share accepted or rejected in each arXiv category.', 'Top: reactions per day by kind. Below: one bar per category, green for liked or saved, red for disliked or dismissed.', M.reactions), 'About reactions')}</h3>
      <div class="lv-scroll"><svg class="lv-svg" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Reactions per day">${bars}</svg></div>
      <div class="lv-legend">${KIND.map(([k, col]) => `<span><i style="background:${col}"></i>${esc(RWORD[k])}</span>`).join('')}</div>${cats}</section>`;
  }

  function settingsBlock() {
    const P = FEED.proposal, cfg = FEED.config;
    const cur = cfg ? `<table class="lv-tbl"><tr><th>Categories</th><td>${esc(cfg.categories.join(', '))}</td></tr><tr><th>Interval</th><td>${fmt(cfg.interval_days)} d</td></tr><tr><th>Shown per cycle</th><td>${fmt(cfg.shown_per_cycle)}</td></tr><tr><th>Exploration share</th><td>${esc(cfg.exploration_share)}</td></tr><tr><th>References</th><td>${esc(H.pretty(cfg.references))}</td></tr><tr><th>Overlap</th><td>${fmt(cfg.overlap_days)} d</td></tr></table>` : '<p class="meta">Not configured: the feed skips this project until categories are accepted.</p>';
    let prop;
    if (!P || !P.shares.length) prop = '<p class="meta">No proposal: no core-layer work has an arXiv category.</p>';
    else prop = `<table class="lv-tbl"><tr><th>Category</th><th class="num">Works</th><th class="num">Share</th><th></th></tr>${P.shares.map(x => `<tr><td>${esc(x.category)}</td><td class="num">${fmt(x.works)}</td><td class="num">${Math.round(100 * x.share)}%</td><td>${x.proposed ? 'proposed' : ''}</td></tr>`).join('')}</table>
      <p class="meta">The proposed set covers ${Math.round(100 * P.covered)}% of the ${fmt(P.with_category)} core works that have a category.</p>
      <div class="lv-form"><button type="button" class="btn primary" id="lvAccept"${off}>Accept proposed categories (as you)</button><span class="lv-msg" id="lvAcceptMsg" aria-live="polite">${HUB.served ? '' : OFFNOTE}</span></div>`;
    return `<section class="card lv-card lv-sec"><h3 class="h3">Feed settings ${H.info('The configuration now in force, and the categories the core layer suggests. Accepting records the feed configuration as you and keeps the other settings. The proposal is computed from the arXiv categories of core works.', 'About feed settings')}</h3>${cur}<h4 class="h3" style="margin-top:16px">Proposal from the core layer</h4>${prop}</section>`;
  }

  function feed() {
    const info = panel('The newest arXiv papers compared with your core works, ranked. A ranking orders; it judges nothing.', 'Cards show the latest ranking. Like or dislike records your reaction; Add puts the paper in the inbox.', M.feed_cards);
    const cards = sortCards(FEED.cards), further = sortCards(FEED.further);
    const lead = FEED.ranking_id ? `${fmt(FEED.total_shown)} of ${fmt(FEED.total_ranked)} ranked papers are shown${FEED.last_fetch ? `, window ${dlab(FEED.last_fetch.window_from)} to ${dlab(FEED.last_fetch.window_to)}` : ''}.` : (FEED.configured ? 'No ranking yet: nothing has been fetched.' : 'The feed is not set up yet.');
    const bar = `<div class="lv-bar"><button type="button" class="btn" data-run="run"${off}>Fetch now</button><button type="button" class="btn" data-run="refetch"${off}>Refetch (no cache)</button><span class="run" id="lvRunLine" aria-live="polite">${esc(runLine())}</span><span class="lv-msg" id="lvRunMsg"></span></div>`;
    const tools = cards.length || further.length ? `<div class="lv-tools"><div class="seg" role="group" aria-label="Layout"><button data-layout="grid" aria-pressed="${st.layout === 'grid'}">Grid</button><button data-layout="list" aria-pressed="${st.layout === 'list'}">List</button></div>
      <label class="meta">Order <select id="lvOrder" aria-label="Order of the cards"><option value="rank"${st.order === 'rank' ? ' selected' : ''}>Rank</option><option value="new"${st.order === 'new' ? ' selected' : ''}>Date, newest first</option><option value="old"${st.order === 'old' ? ' selected' : ''}>Date, oldest first</option></select></label></div>` : '';
    const grid = cards.length || further.length ? `<div class="lv-cards ${st.layout}" id="lvCards">${cards.map(cardHtml).join('')}${further.map(cardHtml).join('')}</div>` : (FEED.configured ? '<div class="card lv-empty">The latest ranking shows no items.</div>' : '');
    const rest = further.length ? `<div class="lv-more"><button type="button" class="btn" id="lvMore">Show next ${Math.min(30, further.length)}</button> <span class="meta">${fmt(further.length)} ranked beyond the shown ones${FEED.cut ? `; the first ${fmt(FEED.cap)} are listed, ${fmt(FEED.cut)} more are not` : ''}. A reaction or add here is recorded as beyond the shown list.</span></div>` : '';
    const body = bar + statusBlock() + tools + grid + rest + `<p class="meta" id="lvAddNote"></p>` + reactionViz() + addLinkBox() + settingsBlock();
    return { lead, info, body, draw: drawFeed };
  }
  function drawFeed() {
    paintRun();
    if (HUB.served && RUN.available === null) pollRunner();
    main.querySelectorAll('[data-run]').forEach(b => b.onclick = () => {
      const host = main.querySelector('#lvRunMsg'), refetch = b.dataset.run === 'refetch';
      act(host, refetch ? 'Refetch now without the cache?' : 'Fetch now for every project?', '/api/feed/' + b.dataset.run, {}, () => 'Started.');
      /* the poll starts after the answer, not before */
      const t = setInterval(() => { if (!host.querySelector('button')) { clearInterval(t); RUN.polls = 0; setTimeout(pollRunner, 500); } }, 400);
      setTimeout(() => clearInterval(t), 20000);
    });
    main.querySelectorAll('.lv-pc .tog').forEach(b => b.onclick = () => { const c = b.closest('.lv-pc'), o = c.classList.toggle('open'); b.setAttribute('aria-expanded', o); b.textContent = o ? 'Less' : 'More'; });
    main.querySelectorAll('[data-layout]').forEach(b => b.onclick = () => { st.layout = b.dataset.layout; try { localStorage.setItem('hub-living-layout', st.layout); } catch (e) { /* ignore */ } render(); });
    const ord = main.querySelector('#lvOrder'); if (ord) ord.onchange = () => go({ order: ord.value === 'rank' ? null : ord.value });
    const more = main.querySelector('#lvMore');
    if (more) more.onclick = () => {
      const hid = [...main.querySelectorAll('.lv-pc.beyond[hidden]')]; hid.slice(0, 30).forEach(c => c.hidden = false);
      const left = hid.length - 30; if (left <= 0) more.hidden = true; else more.textContent = 'Show next ' + Math.min(30, left);
    };
    main.querySelectorAll('.lv-pc [data-fa]').forEach(b => b.onclick = () => {
      const card = b.closest('.lv-pc'), host = card.querySelector('.msg'), a = b.dataset.fa, id = card.dataset.id;
      const base = { entry_id: id, ranking_id: FEED.ranking_id };
      if (a === 'add') act(host, 'Add this paper to the inbox?', '/api/feed/add', base, j => 'Added: ' + j.outcome + (j.reason ? ' (' + j.reason + ')' : '') + '. It enters the work queue; see Pipeline.');
      else act(host, (a === 'like' ? 'Record a like' : 'Record a dislike') + ' for this paper?', '/api/feed/react', { ...base, reaction: a }, j => 'Saved: ' + j.reaction + '.');
    });
    const acc = main.querySelector('#lvAccept');
    if (acc) acc.onclick = () => act(main.querySelector('#lvAcceptMsg'), 'Record the feed configuration with ' + FEED.proposal.categories.join(', ') + '?', '/api/feed/configure', { categories: FEED.proposal.categories }, j => 'Accepted: feed configured (' + j.event_id + '). Reload to see it.');
    wireAddLink();
  }

  /* ---------------- Updates ---------------- */
  const when = s => s ? dlabY(String(s)) : 'none';
  function growthChart() {
    const G = UPD.growth || [];
    if (!G.length) return '<div class="lv-empty">No snapshot yet.</div>';
    const mx = Math.max(...G.map(g => g.included_count), 1), W = 600, Hh = 170, L0 = 40, B = 140, T = 18;
    const xs = i => G.length === 1 ? L0 + (W - L0 - 20) / 2 : L0 + (W - L0 - 20) * i / (G.length - 1), y = v => B - (B - T) * v / mx;
    const pts = G.map((g, i) => `${xs(i)},${y(g.included_count)}`).join(' ');
    return `<div class="lv-scroll"><svg class="lv-svg" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Included works per snapshot">
      <line class="gridline" x1="${L0}" x2="${W}" y1="${y(0)}" y2="${y(0)}"/><line class="gridline" x1="${L0}" x2="${W}" y1="${y(mx)}" y2="${y(mx)}"/>
      <text class="axis" x="${L0 - 6}" y="${y(0) + 4}" text-anchor="end">0</text><text class="axis" x="${L0 - 6}" y="${y(mx) + 4}" text-anchor="end">${fmt(mx)}</text>
      <polyline points="${pts}" fill="none" stroke="var(--acc)" stroke-width="2"/>
      ${G.map((g, i) => `<circle cx="${xs(i)}" cy="${y(g.included_count)}" r="4" fill="var(--acc)"><title>${esc(g.snapshot_id)}: ${fmt(g.included_count)} included</title></circle><text class="lbl" x="${xs(i)}" y="${y(g.included_count) - 9}" text-anchor="middle">${fmt(g.included_count)}</text><text class="axis" x="${xs(i)}" y="${B + 18}" text-anchor="middle">v${i + 1}</text>`).join('')}</svg></div>`;
  }
  const countsStr = o => o ? Object.entries(o).map(([k, v]) => `${esc(srcName(k))} ${fmt(v)}`).join(', ') : '';
  function updates() {
    const B = UPD.baseline, O = UPD.open_period, A = UPD.additions || [], W = UPD.watch || { sources: [] };
    const info = panel('What entered the corpus since the frozen review (v1), how the review grew, and the weekly watch.', '', M.updates);
    const lead = B ? `${fmt(B.included_count)} works were included at v1; ${plural(A.length, 'work was', 'works were')} added since.` : 'No snapshot yet: the review has not been frozen.';
    const head = B ? `<div class="lv-kpis"><div class="card k"><b>${fmt(B.included_count)}</b><span>Included at v1 (${esc(B.snapshot_id)}, ${when(B.recorded_at)})</span></div><div class="card k"><b>${fmt(A.length)}</b><span>Works added since v1</span></div>
      ${O ? `<div class="card k"><b>${fmt(O.new_works)}</b><span>New since ${esc(O.since_snapshot || 'the start')} (open period)</span></div><div class="card k"><b>${fmt(O.included_at_title_abstract)}</b><span>Included at title and abstract</span></div>` : ''}</div>` : `<div class="card lv-empty">No snapshot yet. Close the week below to record the first one.</div>`;
    const RT = ['all', 'inbox', 'feed', 'watch', 'chase', 'search', 'other'];
    const route = RT.includes(st.route) ? st.route : 'all';
    const rn = r => r === 'all' ? A.length : ((UPD.routes || {})[r] || 0);
    const rows = A.filter(a => route === 'all' || a.route === route).map(a => `<tr><td>${a.added_at ? esc(String(a.added_at).slice(0, 10)) : ''}</td><td>${SHELL_IDS.has(a.work_id) ? `<button type="button" class="lnk" data-open="${esc(a.work_id)}">${esc(a.title)}</button>` : esc(a.title)}</td><td>${esc(a.year || '')}</td><td>${esc(a.route)}</td><td>${esc(a.note || '')}</td><td>${esc([a.ta_outcome, a.ft_state, a.ft_outcome].filter(Boolean).join(' / '))}</td><td>${a.layer ? esc(H.layerLabel ? H.layerLabel(a.layer) : a.layer) : ''}</td><td>${esc((a.mined || []).join(', '))}</td></tr>`).join('');
    const adds = `<section class="card lv-card lv-sec"><h3 class="h3">Additions since v1</h3>
      <div class="lv-tools" role="group" aria-label="Route">${RT.map(r => `<button class="chip" data-route="${r}" aria-pressed="${r === route}" ${rn(r) || r === 'all' ? '' : 'disabled'}>${r === 'all' ? 'All' : H.pretty(r)} <span class="n">${fmt(rn(r))}</span></button>`).join('')}</div>
      ${rows ? `<div class="lv-scroll"><table class="lv-tbl"><tr><th>Added</th><th>Title</th><th>Year</th><th>Route</th><th>Note</th><th>Outcome</th><th>Layer</th><th>Mined</th></tr>${rows}</table></div>` : '<div class="lv-empty">No work has entered the corpus since v1.</div>'}</section>`;
    const G = UPD.growth || [];
    const grow = `<section class="card lv-card lv-sec"><h3 class="h3">Growth ${H.info(panel('Included works at each snapshot.', '', M.growth), 'About growth')}</h3>${growthChart()}
      ${G.length ? `<div class="lv-scroll"><table class="lv-tbl"><tr><th>Version</th><th>Snapshot</th><th>Recorded</th><th class="num">Included</th><th class="num">Identified</th><th class="num">Screened</th><th class="num">Passed T/A</th><th>By route</th></tr>${G.map((g, i) => `<tr><td>v${i + 1}</td><td>${esc(g.snapshot_id)}</td><td>${when(g.recorded_at)}</td><td class="num">${fmt(g.included_count)}</td><td class="num">${g.identified == null ? '' : fmt(g.identified)}</td><td class="num">${g.screened == null ? '' : fmt(g.screened)}</td><td class="num">${g.included == null ? '' : fmt(g.included)}</td><td>${[countsStr(g.identified_databases), countsStr(g.identified_other)].filter(Boolean).join('; ')}</td></tr>`).join('')}</table></div>` : ''}</section>`;
    const first = (W.sources || [])[0], chosen = new Set((W.sources || []).map(s => s.source)), interval = first ? first.interval_days : 7;
    const srcs = [...new Set([...(UPD.included_sources || []), ...chosen])];
    const tbl = W.has_plan ? `<p>Weekly watch is on. Ends: ${W.until ? when(W.until) : 'no end date'}; open cycle: ${esc(W.open_cycle || 'none')}.</p><div class="lv-scroll"><table class="lv-tbl"><tr><th>Source</th><th>Mode</th><th>Every</th><th>Last cycle</th><th>Next</th><th>Last full run</th><th class="num">Weekly windows since</th></tr>${W.sources.map(s => `<tr><td>${esc(srcName(s.source))}</td><td>${esc(s.mode)}</td><td>${fmt(s.interval_days)} d</td><td>${when(s.last_finished_at)}</td><td>${s.due ? 'due now' : when(s.next_due)}</td><td>${s.last_full_replay ? when(s.last_full_replay) : 'none in the watch'}</td><td class="num">${fmt(s.windows_since_full_replay)}</td></tr>`).join('')}</table></div>` : '<p>Weekly watch: <b>not configured</b>.</p>';
    const form = `<div class="lv-form">${srcs.length ? srcs.map(s => `<label class="chk"><input type="checkbox" name="lvSrc" value="${esc(s)}" ${chosen.has(s) || !chosen.size ? 'checked' : ''}${off}> ${esc(srcName(s))}</label>`).join('') : '<span class="meta">No included source in the protocol.</span>'}
      <label>Interval (days)<input type="number" id="lvInt" min="1" value="${interval}"${off}></label><label>End date (optional)<input type="date" id="lvUntil" value="${W.until ? esc(String(W.until)) : ''}"${off}></label>
      <button type="button" class="btn primary" id="lvWatch"${off}>Save watch settings (as you)</button><span class="lv-msg" id="lvWatchMsg" aria-live="polite">${HUB.served ? '' : OFFNOTE}</span></div>
      <div class="lv-form"><button type="button" class="btn" id="lvSnap"${off}>Close week now (as you)</button><span class="lv-msg" id="lvSnapMsg" aria-live="polite"></span></div>`;
    const watch = `<section class="card lv-card lv-sec"><h3 class="h3">Weekly watch ${H.info(panel('How often each source is searched again, and the settings that drive it.', 'Saving records a protocol amendment as you. Closing the week records a snapshot.', M.watch), 'About the weekly watch')}</h3>${tbl}${form}
      <p class="meta">Sources run in window mode: each weekly window covers the days since the last. A full re-run never happens automatically. To run one: <code>factory --project ${esc(SLUG)} watch run --full-replay</code>.</p></section>`;
    return { lead, info, body: head + adds + grow + watch + addLinkBox(), draw: drawUpdates };
  }
  function drawUpdates() {
    main.querySelectorAll('[data-route]').forEach(b => b.onclick = () => go({ route: b.dataset.route === 'all' ? null : b.dataset.route }));
    main.querySelectorAll('[data-open]').forEach(b => b.onclick = () => HUB.openDrawer(b.dataset.open));
    const w = main.querySelector('#lvWatch');
    if (w) w.onclick = () => {
      const sources = [...main.querySelectorAll('input[name=lvSrc]:checked')].map(x => x.value), host = main.querySelector('#lvWatchMsg');
      const interval = parseInt(main.querySelector('#lvInt').value, 10) || 0, until = main.querySelector('#lvUntil').value || null;
      if (!sources.length) { host.textContent = 'Pick at least one source.'; return; }
      act(host, `Save the watch (${sources.join(', ')}, every ${interval} d${until ? ', until ' + until : ''})?`, '/api/watch/configure', { sources, interval_days: interval, until }, j => 'Saved: protocol ' + j.protocol_id + '. Reload to see it.');
    };
    const sn = main.querySelector('#lvSnap');
    if (sn) sn.onclick = () => act(main.querySelector('#lvSnapMsg'), 'Close the week and record a snapshot now?', '/api/living/snapshot', {}, j => 'Week closed: snapshot ' + j.snapshot_id + '. Reload to see it.');
    wireAddLink();
  }

  /* ---------------- By day ---------------- */
  function river() {
    const days = RIV.days || [];
    if (!days.length) return { lead: 'No feed runs yet.', info: panel('New arXiv papers per day, with the best-ranked ones and your reactions.', '', M.feed_river), body: empty('No feed runs yet. New papers appear here once the feed has fetched.') };
    const byDay = new Map(days.map(x => [x.day, x]));
    const first = utc(days[0].day), last = utc(days[days.length - 1].day);
    const all = []; for (let t = first; t <= last; t += DAY) all.push(iso(t));
    const mx = Math.max(...days.map(x => x.count));
    const sel = byDay.has(st.day) ? st.day : days[days.length - 1].day;
    const n = all.length, W = 880, Hh = 220, L0 = 44, B = 190, T = 14, step = (W - L0 - 8) / n, bw = Math.min(64, step * .7);
    const y = v => B - (B - T) * v / mx;
    const ticks = [0, .5, 1].map(f => Math.round(mx * f));
    const sx = i => L0 + step * i + (step - bw) / 2;
    const lblEvery = Math.ceil(n / 12);
    const svg = `<svg class="lv-svg" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="New papers per day">
      ${ticks.map(v => `<line class="gridline" x1="${L0}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L0 - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`).join('')}
      ${all.map((dy, i) => {
        const x = byDay.get(dy); const bx = sx(i);
        const lab = i % lblEvery === 0 || dy === sel ? `<text class="axis" x="${bx + bw / 2}" y="${B + 16}" text-anchor="middle">${dlab(dy)}</text>` : '';
        if (!x) return lab;
        const sh = x.shown, rest = x.count - sh;
        return `<g class="bar" tabindex="0" role="button" data-day="${dy}" aria-label="${dlab(dy)}: ${plural(x.count, 'new paper', 'new papers')}" aria-pressed="${dy === sel}">
          <rect class="b" x="${bx}" y="${y(x.count)}" width="${bw}" height="${B - y(x.count)}" rx="2" fill="var(--mut)" opacity=".55"/>
          ${sh ? `<rect class="b" x="${bx}" y="${y(sh)}" width="${bw}" height="${B - y(sh)}" rx="2" fill="var(--acc)"/>` : ''}
          <rect x="${bx - 2}" y="${T - 2}" width="${bw + 4}" height="${B - T + 4}" fill="transparent"/>
          ${dy === sel ? `<rect class="sel" x="${bx - 3}" y="${y(x.count) - 3}" width="${bw + 6}" height="${B - y(x.count) + 6}" rx="3"/>` : ''}
          <text class="lbl" x="${bx + bw / 2}" y="${y(x.count) - 6}" text-anchor="middle">${fmt(x.count)}</text></g>${lab}`;
      }).join('')}</svg>`;
    const cur = byDay.get(sel);
    const lastDay = days[days.length - 1], shownDays = days.filter(x => x.shown).length;
    const lead = `${fmt(RIV.total)} new papers came in over ${plural(days.length, 'day', 'days')}. ${shownDays ? `The latest ${plural(lastDay.shown, 'was ranked', 'were ranked')} for you.` : 'None have been ranked yet.'}`;
    const rx = Object.entries(cur.reactions || {});
    const list = cur.top.map(t => {
      const rk = t.rank == null ? `<span class="rk none" title="Not shown by the ranking">–</span>` : `<span class="rk">#${fmt(t.rank)}</span>`;
      const re = [t.reaction ? react(t.reaction) : '', t.sent ? react('sent', 'Sent to inbox') : ''].filter(Boolean).join(' ');
      return `<li>${rk}<span><a href="https://arxiv.org/abs/${esc(t.entry_id)}" target="_blank" rel="noopener">${esc(t.title)}</a>${t.score != null ? `<span class="sc">score ${t.score.toFixed(3)}</span>` : ''}</span><span>${re}</span></li>`;
    }).join('');
    const detail = `<section class="card lv-day">
      ${H.header({ title: dlabY(sel), sub: `<span class="meta">${plural(cur.count, 'new paper', 'new papers')}</span>` })}
      <div class="stats"><span><b>${fmt(cur.count)}</b> new</span><span><b>${fmt(cur.shown)}</b> shown</span><span><b>${fmt(cur.sent)}</b> sent to inbox</span>
        <span><b>${fmt(rx.reduce((a, r) => a + r[1], 0))}</b> reacted${rx.length ? ' (' + rx.map(([k, v]) => `${fmt(v)} ${esc((RWORD[k] || k).toLowerCase())}`).join(', ') + ')' : ''}</span></div>
      <ul class="lv-list">${list}</ul>
      ${cur.count > cur.top.length ? `<p class="meta" style="margin:10px 0 0">Best ${fmt(cur.top.length)} of ${fmt(cur.count)}</p>` : ''}</section>`;
    const body = `<div class="card lv-card"><div class="lv-scroll">${svg}</div><div class="lv-legend"><span><i style="background:var(--acc)"></i>Shown by the ranking</span><span><i style="background:var(--mut);opacity:.55"></i>Not shown</span></div></div>${detail}`;
    return { lead, info: panel('How many new arXiv papers the feed found each day, and what you did with the best-ranked ones.', 'Each bar is one day. The tinted part of a bar is the share the ranking put in front of you. Click a day to list its best-ranked papers with your reaction.', M.feed_river), body };
  }

  /* ---------------- How current ---------------- */
  function horizon() {
    const src = HOR.sources || [];
    const info = panel('How fresh each source is: when it was last searched, against today.', 'Each row runs from the date of the latest search to today. The longer the line, the further behind the source is.', M.horizon);
    if (!src.length) return { lead: 'No searches recorded yet.', info, body: empty('No searches recorded yet. Each source appears here once it has been searched.') };
    const todayT = utc((d.shell.generated || new Date().toISOString()));
    const ages = src.map(s => s.days_ago).filter(a => a != null);
    const worst = src.slice().sort((a, b) => (b.days_ago ?? -1) - (a.days_ago ?? -1))[0];
    const same = ages.length && ages.every(a => a === ages[0]);
    const lead = same ? `Every source was last searched ${plural(ages[0], 'day', 'days')} ago.` : `${esc(srcName(worst.source))} is the furthest behind, last searched ${plural(worst.days_ago, 'day', 'days')} ago.`;
    const t0 = Math.min(...src.map(s => utc(s.latest_search)), todayT - DAY * 7), span = todayT - t0 || DAY, W = 760;
    const X = t => 20 + (W - 40) * (t - t0) / span;
    const rows = src.map(s => {
      const t = utc(s.latest_search), x = X(t), x1 = X(todayT);
      const msg = s.days_ago == null ? 'date unknown' : s.days_ago === 0 ? 'searched today' : `${plural(s.days_ago, 'day', 'days')} behind`;
      return `<div class="lv-src"><span class="nm">${esc(srcName(s.source))}</span>
        <svg class="lv-svg" viewBox="0 0 ${W} 28" role="img" aria-label="${esc(srcName(s.source))}: ${esc(msg)}"><line x1="${x}" x2="${x1}" y1="14" y2="14" stroke="var(--line)" stroke-width="3" stroke-linecap="round"/>
          <circle cx="${x}" cy="14" r="6" fill="var(--acc)"/><circle cx="${x1}" cy="14" r="5" fill="none" stroke="var(--mut)" stroke-width="1.8"/></svg>
        <span class="bhind">${esc(msg)}</span></div>`;
    }).join('');
    const axis = `<div class="lv-src" style="border:0;padding-top:0"><span></span><svg class="lv-svg" viewBox="0 0 ${W} 22"><text class="axis" x="20" y="14">${dlab(iso(t0))}</text><text class="axis" x="${W - 20}" y="14" text-anchor="end">Today, ${dlab(iso(todayT))}</text></svg><span></span></div>`;
    const years = HOR.years || [];
    const pub = years.length ? `<p class="meta" style="margin:12px 0 0">Newest publications found: ${fmt(HOR.latest_year)}.</p>` : '';
    const notes = (HOR.notices || []).map(n => esc(n)).join(' ');
    const body = `<div class="card lv-card">${rows}${axis}
      <div class="lv-legend"><span><i style="background:var(--acc);border-radius:50%"></i>Latest search</span><span><i style="background:none;border:1.8px solid var(--mut);border-radius:50%;width:8px;height:8px"></i>Today</span></div>${pub}</div>
      ${notes ? `<p class="meta" style="margin:12px 4px 0">${notes}</p>` : ''}`;
    return { lead, info, body };
  }

  /* ---------------- Heartbeat ---------------- */
  function beat() {
    const days = HB.days || [];
    const info = panel('How active the project was on each day, and in which kind of work.', 'Each square is a day, weeks run in columns, Monday at the top. Darker means more events. Pick a family to see only that kind of work; hover a day for the split.', M.heartbeat);
    if (!days.length) return { lead: 'No activity yet.', info, body: empty('No activity yet. Days appear here as events are recorded.') };
    const fam = st.fam === 'all' || FAMS.includes(st.fam) ? st.fam : 'all';
    const val = x => fam === 'all' ? x.total : (x.families[fam] || 0);
    const byDay = new Map(days.map(x => [x.day, x]));
    const totals = HB.family_totals || {};
    const firstT = utc(HB.first_day), lastT = utc(HB.last_day);
    const dowOf = t => (new Date(t).getUTCDay() + 6) % 7;
    const MINW = 14;
    let endT = lastT + (6 - dowOf(lastT)) * DAY;
    let startT = firstT - dowOf(firstT) * DAY;
    const weeks = Math.max(MINW, Math.round((endT - startT) / DAY / 7) + 1);
    startT = endT - (weeks * 7 - 1) * DAY;
    const nonzero = days.map(val).filter(v => v > 0).sort((a, b) => a - b);
    const q = f => nonzero.length ? nonzero[Math.min(nonzero.length - 1, Math.floor(f * nonzero.length))] : 0;
    const cuts = [q(0), q(.25), q(.5), q(.75)];
    const level = v => v <= 0 ? 0 : v >= cuts[3] ? 4 : v >= cuts[2] ? 3 : v >= cuts[1] ? 2 : 1;
    const C = 30, G = 5, LX = 34, TY = 20, W = LX + weeks * (C + G), Hh = TY + 7 * (C + G) + 4;
    let cells = '', months = '', lastM = -1;
    for (let w = 0; w < weeks; w++) {
      const wt = startT + w * 7 * DAY, mo = new Date(wt).getUTCMonth();
      if (mo !== lastM) { months += `<text class="axis" x="${LX + w * (C + G)}" y="12">${MON[mo]}</text>`; lastM = mo; }
      for (let r = 0; r < 7; r++) {
        const t = wt + r * DAY, dy = iso(t), x = byDay.get(dy), v = x ? val(x) : 0, inRange = t >= firstT && t <= lastT;
        const f = v ? `var(--seq-${level(v)})` : (inRange ? 'var(--raised)' : 'none');
        cells += `<rect class="cell${st.day === dy ? ' on' : ''}" data-day="${dy}" x="${LX + w * (C + G)}" y="${TY + r * (C + G)}" width="${C}" height="${C}" rx="3" style="fill:${f}" ${inRange ? '' : 'stroke="var(--hair)" stroke-dasharray="2 3"'}${inRange ? ` tabindex="0" aria-label="${dlabY(dy)}: ${fmt(v)} events"` : ''}/>`;
      }
    }
    const dows = [0, 2, 4].map(r => `<text class="axis" x="0" y="${TY + r * (C + G) + C - 6}">${DOW[r]}</text>`).join('');
    const svg = `<svg width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Events per day">${months}${dows}${cells}</svg>`;
    const busiest = days.reduce((a, x) => val(x) > val(a) ? x : a, days[0]);
    const lastActive = days.filter(x => val(x) > 0).pop();
    const what = fam === 'all' ? 'events' : famLabel(fam).toLowerCase() + ' events';
    const lead = val(busiest) ? `The busiest day was ${dlab(busiest.day)}, with ${fmt(val(busiest))} ${what}. Last activity: ${dlab(lastActive.day)}.` : `No ${what} yet.`;
    const chips = ['all', ...FAMS].map(f => {
      const n = f === 'all' ? HB.total : (totals[f] || 0);
      return `<button class="chip" data-fam="${f}" aria-pressed="${f === fam}" ${n ? '' : 'disabled'}>${f === 'all' ? 'All' : famLabel(f)} <span class="n">${fmt(n)}</span></button>`;
    }).join('');
    const sd = byDay.get(st.day) || lastActive;
    const detail = sd ? `<section class="card lv-day">${H.header({ title: dlabY(sd.day), sub: `<span class="meta">${plural(sd.total, 'event', 'events')}</span>` })}
      ${FAMS.filter(f => sd.families[f]).map(f => `<div class="lv-fam"><span>${famLabel(f)}</span><span class="tr"><i style="width:${Math.round(100 * sd.families[f] / sd.total)}%"></i></span><span class="v">${fmt(sd.families[f])}</span></div>`).join('')}</section>` : '';
    const legend = `<div class="lv-legend"><span>Fewer</span>${[0, 1, 2, 3, 4].map(i => `<span><i style="background:${i ? `var(--seq-${i})` : 'var(--raised)'};margin:0"></i></span>`).join('')}<span>More</span></div>`;
    const body = `<div class="lv-hb"><div class="card lv-card"><div class="lv-hb-head" role="group" aria-label="Family">${chips}</div><div class="lv-hb-wrap">${svg}</div>${legend}</div>${detail}</div>`;
    return { lead, info, body };
  }

  /* ---------------- render ---------------- */
  function render() {
    const V = ({ feed, updates, river, horizon, beat })[st.tab]();
    main.innerHTML = `<section style="padding:20px 0 0">
      ${H.header({ kicker: `Living review · ${H.term('protocol')}`, title: 'Living review', level: 1, infoHtml: V.info })}
      <p class="lead lv-lead">${V.lead}</p></section>
      <div class="lv-tabs"><div class="seg" role="tablist" aria-label="View">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-pressed="${k === st.tab}">${l}</button>`).join('')}</div></div>
      <div id="lvBody">${V.body}</div>`;
    main.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => go({ tab: b.dataset.tab === 'feed' ? null : b.dataset.tab, day: null, fam: null, route: null }));
    main.querySelectorAll('[data-fam]').forEach(b => b.onclick = () => go({ fam: b.dataset.fam === 'all' ? null : b.dataset.fam }));
    if (V.draw) V.draw();
    main.querySelectorAll('.bar').forEach(g => {
      const pick = () => go({ day: g.dataset.day });
      g.onclick = pick; g.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };
    });
    main.querySelectorAll('rect.cell[tabindex]').forEach(c => {
      const x = HB.days.find(z => z.day === c.dataset.day);
      const split = x ? FAMS.filter(f => x.families[f]).map(f => `${famLabel(f)} ${fmt(x.families[f])}`).join('<br>') : '';
      c.onmousemove = e => H.tipHtml(`<b>${dlabY(c.dataset.day)}</b><br>${x ? plural(x.total, 'event', 'events') + '<br>' + split : 'No events'}`, e);
      c.onmouseleave = () => H.tipHtml('');
      c.onclick = () => go({ day: c.dataset.day });
      c.onkeydown = e => { if (e.key === 'Enter') go({ day: c.dataset.day }); };
    });
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
