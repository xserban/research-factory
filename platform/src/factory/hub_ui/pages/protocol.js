/* Protocol page. Payload: protocol (services/hub_protocol.py). Tabs: Plan, Versions, Decisions, Reviews, Probes.
   Read-only. Every number comes from the payload. URL hash: tab, sec (plan section), ver (version), dec (decision). */
HUB.load(['shell', 'protocol']).then(d => {
  const H = HUB.init(d.shell);
  const P = d.protocol || {};
  const main = H.mount({ page: 'protocol', crumb: 'Protocol' });
  const { esc, fmt } = H;
  const M = P.methods || {};
  const PV = P.protocol || {};
  const SPEC = PV.spec || null;
  const Q = P.question || {};
  const DEC = P.decisions || [];
  const VERS = P.versions || [];
  const byId = Object.fromEntries(DEC.map(x => [x.decision_id, x]));

  if (!document.getElementById('pr-style')) {
    const st = document.createElement('style'); st.id = 'pr-style';
    st.textContent = `
.pr-tabs{margin:20px 0}
.pr-stats{display:flex;flex-wrap:wrap;gap:var(--gap);margin:16px 0}
.pr-stat{background:var(--surface);border-radius:var(--r);padding:12px 18px;min-width:120px}
.pr-stat .v{font:500 var(--t-l) var(--f-mono)}.pr-stat .k{font-size:var(--t-xs);color:var(--mut)}
.pr-chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
.pr-card{margin:0 0 var(--gap)}
.pr-card h3{margin:0 0 10px}
.pr-kv{width:100%;border-collapse:collapse;font-size:var(--t-s)}
.pr-kv td{padding:6px 8px;border-bottom:1px solid var(--hair);vertical-align:top}
.pr-kv td:first-child{color:var(--mut);white-space:nowrap;width:1%}
.pr-kv table{margin:0}
.pr-badge{font:500 var(--t-xs) var(--f-ui);padding:3px 8px;border-radius:999px;background:var(--raised);color:var(--mut)}
.pr-badge.ok{color:var(--inc)}.pr-badge.bad{color:var(--exc)}.pr-badge.act{color:var(--acc)}
.pr-dec{background:var(--surface);border-radius:var(--r);margin:0 0 10px}
.pr-dec.sup{opacity:.6}
.pr-dec>button{all:unset;box-sizing:border-box;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;width:100%;padding:12px 16px;cursor:pointer}
.pr-dec>button:focus-visible{outline:2px solid var(--acc)}
.pr-dec .id{font:400 var(--t-xs) var(--f-mono);color:var(--dim)}
.pr-dec .bd{padding:0 16px 14px}
.pr-dec .it{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:8px;padding:6px 0;border-top:1px solid var(--hair);align-items:baseline}
.pr-dec a{color:var(--acc);cursor:pointer}
.pr-grp{margin:22px 0 8px;color:var(--mut);font:500 var(--t-s) var(--f-ui)}
.pr-svg{display:block;width:100%;height:auto}
.pr-svg .dotp{cursor:pointer}.pr-svg .dotp:focus{outline:none}
.pr-svg .ln{stroke:var(--dim);fill:none;stroke-width:1.4}
.pr-mx td.chg,.pr-mx th.sel{background:var(--acc-soft)}
.pr-mx td{font:400 var(--t-xs) var(--f-mono);cursor:pointer}
.pr-mx td.chg{color:var(--fg);box-shadow:inset 0 0 0 1px var(--acc)}
.pr-diff{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap)}
.pr-diff pre{margin:0;white-space:pre-wrap;word-break:break-word;font:400 var(--t-xs) var(--f-mono);background:var(--raised);padding:10px;border-radius:var(--r-s);max-height:360px;overflow:auto}
.pr-diff pre.old{background:var(--exc-soft)}.pr-diff pre.new{box-shadow:inset 0 0 0 1px var(--inc)}
.pr-empty{color:var(--dim);padding:28px 8px;text-align:center}
@media (max-width:800px){.pr-diff{grid-template-columns:1fr}.pr-dec .it{grid-template-columns:1fr}.pr-scroll{overflow-x:auto}}`;
    document.head.appendChild(st);
  }

  HUB.GLOSSARY.amendment = ['Amendment', 'A recorded change to the protocol. A change that matters gives a new protocol id; a rewording keeps the id.'];
  HUB.GLOSSARY.deviation = ['Deviation', 'A declared departure from the registered protocol, with its reason and what it affects.'];
  HUB.GLOSSARY.press = ['PRESS review', 'An independent critique of the search strategy; each finding is answered by a human.'];
  HUB.GLOSSARY.probe = ['Probe', 'A trial run of the planned queries that counts what each retrieves, before the real search.'];

  const empty = t => '<p class="pr-empty">' + esc(t) + '</p>';
  const badge = (t, cls) => '<span class="pr-badge ' + (cls || '') + '">' + esc(t) + '</span>';
  const short = id => String(id || '').replace(/^dec_/, '').slice(0, 8);
  const hs = HUB.hash;
  const state = { tab: hs.get().get('tab') || 'plan', sec: hs.get().get('sec') || '', ver: hs.get().get('ver') || '',
    dec: hs.get().get('dec') || '', level: '', status: '', q: '' };
  const open = new Set(state.dec ? [state.dec] : []);
  const TABS = [['plan', 'Plan'], ['versions', 'Versions'], ['decisions', 'Decisions'], ['reviews', 'Reviews'], ['probes', 'Probes']];

  const label = k => H.pretty ? H.pretty(String(k)) : String(k).replace(/_/g, ' ');
  /* Generic key-value rendering of a declared plan section. */
  const val = v => {
    if (v === null || v === undefined || v === '') return '<span class="meta">none</span>';
    if (Array.isArray(v)) return v.length ? (v.every(x => typeof x !== 'object' || x === null)
      ? v.map(x => esc(String(x))).join(', ') : v.map(x => '<div>' + val(x) + '</div>').join('')) : '<span class="meta">none</span>';
    if (typeof v === 'object') return kv(v);
    return esc(String(v));
  };
  const kv = o => '<table class="pr-kv"><tbody>' + Object.entries(o).map(([k, v]) => '<tr><td>' + esc(label(k)) + '</td><td>' + val(v) + '</td></tr>').join('') + '</tbody></table>';
  const table = (cols, rows) => rows.length ? '<div class="pr-scroll"><table class="t"><thead><tr>' + cols.map(c => '<th>' + esc(c[0]) + '</th>').join('') + '</tr></thead><tbody>' +
    rows.map(r => '<tr>' + cols.map(c => '<td' + (c[2] ? ' class="r"' : '') + '>' + (c[1](r) ?? '') + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>' : empty('Nothing declared.');
  const card = (title, body, info) => '<section class="card pr-card">' + H.header({ title, infoHtml: info || '' }) + body + '</section>';

  /* ---------- header and stats ---------- */
  const pressWord = { none: 'Not reviewed', reviewed: 'Reviewed, not confirmed', confirmed: 'Confirmed' };
  const nAm = (PV.amendments || []).length;
  const head = () => H.header({
    kicker: 'Living review · ' + HUB.term('protocol') + (PV.protocol_id ? ' <span class="meta">' + esc(PV.protocol_id) + '</span>' : ''),
    title: 'Protocol',
    sub: 'The registered plan, how it changed, and the decisions behind it.', level: 1,
    infoHtml: (M.tab_protocol || '') + '<p><b>What it shows</b> The plan the review follows, its versions, the decisions taken, the search critique and the trial queries.' +
      '<p><span class=k>How it\'s computed.</span> ' + esc(M.plan || '') + '</p>' }) +
    (PV.protocol_id ? '<div class="pr-stats">' +
      [['Protocol', PV.protocol_id], ['Status', PV.status], ['Review', pressWord[PV.press] || PV.press], ['Amendments', fmt(nAm)], ['Deviations', fmt((P.deviations || []).length)]]
        .map(([k, v]) => '<div class="pr-stat"><div class="v">' + esc(String(v ?? '')) + '</div><div class="k">' + esc(k) + '</div></div>').join('') + '</div>'
      : empty('No protocol is registered yet.'));

  /* ---------- decision cards ---------- */
  const stateCls = s => s === 'selected' ? 'ok' : s === 'open' ? 'act' : '';
  const itemCls = s => s === 'validated' || s === 'added' ? 'ok' : s === 'rejected' ? 'bad' : '';
  const link = id => byId[id] ? '<a data-jump="' + esc(id) + '">' + esc(byId[id].subject) + ' <span class="id">' + esc(short(id)) + '</span></a>' : esc(short(id));
  const decCard = x => {
    const isOpen = open.has(x.decision_id);
    const sel = x.selection;
    let body = '';
    if (isOpen) {
      body = '<div class="bd" id="dec-' + esc(x.decision_id) + '"><p>' + esc(x.explanation) + '</p>' +
        (x.supersedes ? '<p class="meta">Supersedes ' + link(x.supersedes) + '</p>' : '') +
        (x.superseded_by ? '<p class="meta">Superseded by ' + link(x.superseded_by) + '</p>' : '') +
        (x.items || []).map(it => '<div class="it">' + badge(it.status, itemCls(it.status)) + '<span class="id">' + esc(it.item_id) + '</span><span>' + esc(it.text) +
          (it.recommended ? ' ' + badge('recommended', 'act') : '') + ((it.grounds || []).length ? '<div class="meta">Grounds: ' + it.grounds.map(link).join(', ') + '</div>' : '') + '</span></div>').join('') +
        '<p class="meta">' + (sel ? 'Selected by ' + esc(sel.actor) + ' via ' + esc(sel.channel) + ' at ' + esc(sel.ts) + (sel.reconstructed ? ' (reconstructed)' : '') + (sel.note ? ' — ' + esc(sel.note) : '') : 'No selection yet.') +
        ' Suggested by ' + esc(x.actor) + ', decision <span class="id">' + esc(x.decision_id) + '</span></p></div>';
    }
    return '<div class="pr-dec' + (x.state === 'superseded' ? ' sup' : '') + '" data-id="' + esc(x.decision_id) + '"><button type="button" aria-expanded="' + isOpen + '" data-toggle="' + esc(x.decision_id) + '">' +
      '<b>' + esc(x.subject) + '</b>' + badge(x.level) + '<span class="id">' + esc(short(x.decision_id)) + '</span><span class="meta">' + esc(String(x.suggested_at).slice(0, 16).replace('T', ' ')) + '</span>' + badge(x.state, stateCls(x.state)) + '</button>' + body + '</div>';
  };
  const wireDecs = root => {
    root.querySelectorAll('[data-toggle]').forEach(b => b.onclick = () => { const id = b.dataset.toggle; open.has(id) ? open.delete(id) : open.add(id); hs.set({ dec: open.has(id) ? id : '' }); draw(); });
    root.querySelectorAll('[data-jump]').forEach(a => a.onclick = () => jump(a.dataset.jump));
  };
  const jump = id => { open.add(id); state.tab = 'decisions'; state.level = ''; state.status = ''; state.q = ''; hs.set({ tab: 'decisions', dec: id }); draw();
    const el = main.querySelector('[data-id="' + id.replace(/"/g, '') + '"]'); if (el) el.scrollIntoView({ block: 'center' }); };

  /* ---------- Plan tab ---------- */
  const secKeys = () => {
    const base = (P.sections || []).map(s => ({ key: s[0], title: s[1] }));
    const known = new Set(base.map(s => s.key));
    Object.keys(P.decision_sections || {}).filter(k => !known.has(k)).sort().forEach(k => base.push({ key: k, title: k.replace('other:', 'Other: ') }));
    return base;
  };
  const section = key => {
    const S = SPEC || {};
    const exc = P.criteria_excluded || {};
    if (key === 'question') {
      const sp = Q.spec;
      if (!sp) return empty('No question recorded.');
      return card('Question', '<p class="lead" style="max-width:60ch">' + esc(sp.primary_question) + '</p>' + (sp.objectives ? '<p>' + esc(sp.objectives) + '</p>' : '') +
        table([['Slot', s => esc(s.name)], ['Value', s => s.value != null ? esc(s.value) : '<span class="meta">open</span>'], ['Open until', s => esc(s.open ? s.open + (s.resolve_in ? ' (' + s.resolve_in + ')' : '') : '')]], sp.slots || []) +
        ((sp.sub_questions || []).length ? '<h3 class="h3" style="margin-top:18px">Sub-questions</h3>' + table([['Id', s => esc(s.id)], ['Question', s => esc(s.text)], ['Serves', s => esc(s.serves || '')]], sp.sub_questions) : '') +
        ((sp.non_goals || []).length ? '<h3 class="h3" style="margin-top:18px">Out of scope</h3>' + table([['Id', s => esc(s.id)], ['Statement', s => esc(s.text)]], sp.non_goals) : ''));
    }
    if (!SPEC) return empty('No protocol is registered yet.');
    if (key === 'criteria') {
      const cnt = (c, st) => { const n = (exc[c.id] || {})[st]; return n == null ? (c.id.startsWith('EX') ? '0' : '') : fmt(n); };
      return card('Criteria', table([['Id', c => '<span class="id">' + esc(c.id) + '</span>'], ['Parent', c => esc(c.parent || '')], ['Applies at', c => esc(label(c.applies_at))], ['Statement', c => esc(c.statement)], ['Rule', c => esc(c.rule)],
        ['Excluded (title)', c => cnt(c, 'title_abstract'), 1], ['Excluded (full text)', c => cnt(c, 'full_text'), 1]], S.criteria || []),
        '<b>What it shows</b> Each inclusion and exclusion rule, and how many works each one excluded.<p><span class=k>How it\'s computed.</span> ' + esc(M.criteria || '') + '</p>');
    }
    if (key === 'sources') {
      return card('Sources', table([['Source', s => esc(s.name || s.source || '')], ['Excluded', s => s.excluded ? 'yes' : 'no'], ['Why', s => esc(s.why || s.reason || '')]], S.sources || [])) +
        card('Queries', table([['Source', q => esc(q.source || '')], ['Kind', q => esc(q.kind || '')], ['Text', q => esc(q.text || '')], ['Filters', q => q.filters ? kv(q.filters) : '']], S.queries || [])) +
        card('Limits', table([['Field', l => esc(l.field || '')], ['Value', l => esc(String(l.value ?? ''))], ['Why', l => esc(l.why || l.reason || '')]], S.limits || []));
    }
    if (key === 'screening') return card('Title and abstract screening', S.screening ? kv(S.screening) : empty('Not declared.')) + card('Full-text screening', S.full_text_screening ? kv(S.full_text_screening) : empty('Not declared.'));
    if (key === 'extraction') return card('Extraction schema', S.extraction_schema ? kv(S.extraction_schema) : empty('Not declared.'));
    if (key === 'snowball') return card('Snowball plan', S.snowball_plan ? kv(S.snowball_plan) : empty('Not declared.'));
    return '';
  };
  const planTab = () => {
    const keys = secKeys();
    if (!state.sec || !keys.some(s => s.key === state.sec)) state.sec = 'question';
    const decs = DEC.filter(x => x.section === state.sec);
    return '<div class="pr-chips" role="group" aria-label="Sections">' + keys.map(s => '<button type="button" class="chip" aria-pressed="' + (s.key === state.sec) + '" data-sec="' + esc(s.key) + '">' + esc(s.title) +
      ' <span class="n">' + fmt((P.decision_sections || {})[s.key] || 0) + '</span></button>').join('') + '</div>' + section(state.sec) +
      '<h2 class="h2">Decisions behind this section</h2>' + (decs.length ? decs.map(decCard).join('') : empty('No decision is filed under this section.'));
  };

  /* ---------- Versions tab ---------- */
  const SECS = () => { const s = new Set(); VERS.forEach(v => Object.keys(v.fingerprints || {}).forEach(k => s.add(k))); return [...s]; };
  const versionsTab = () => {
    if (!VERS.length) return empty('No protocol version is recorded yet.');
    const vi = Math.min(Math.max(+state.ver || 0, 0), VERS.length - 1);
    const sel = VERS[vi];
    const W = 120, X0 = 40, svgW = X0 * 2 + W * (VERS.length - 1);
    const nodes = VERS.map((v, i) => '<g class="dotp" tabindex="0" role="button" data-v="' + i + '" aria-label="Version ' + esc(v.protocol_id) + '"><circle cx="' + (X0 + i * W) + '" cy="30" r="' + (i === vi ? 9 : 6) + '" fill="' + (v.semantic ? 'var(--acc)' : 'var(--dim)') + '"/>' +
      '<text class="axis" x="' + (X0 + i * W) + '" y="58" text-anchor="middle">' + esc(v.protocol_id) + '</text><text class="axis" x="' + (X0 + i * W) + '" y="14" text-anchor="middle">' + esc(v.kind === 'initial' ? 'registered' : 'amendment ' + i) + '</text></g>').join('');
    const line = '<line x1="' + X0 + '" x2="' + (svgW - X0) + '" y1="30" y2="30" stroke="var(--line)" stroke-width="2"/>';
    const rows = SECS();
    const matrix = '<div class="pr-scroll"><table class="t pr-mx"><thead><tr><th>Section</th>' + VERS.map((v, i) => '<th class="' + (i === vi ? 'sel' : '') + '">' + esc(v.protocol_id) + (v.amendment_id ? '<br><span class="meta">' + esc(v.amendment_id.slice(0, 12)) + '</span>' : '') + '</th>').join('') + '</tr></thead><tbody>' +
      rows.map(r => '<tr><td>' + esc(label(r)) + '</td>' + VERS.map((v, i) => '<td class="' + ((v.changed || []).includes(r) ? 'chg' : '') + '" data-v="' + i + '" data-s="' + esc(r) + '">' + esc((v.fingerprints || {})[r] || '–') + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
    let diff = '';
    if (sel.kind === 'initial') diff = '<p class="meta">First registered version.</p>';
    else {
      diff = '<p>' + esc(sel.reason) + ' ' + badge(sel.semantic ? 'changes the plan' : 'wording only', sel.semantic ? 'act' : '') + '</p>' +
        ((sel.changed || []).length ? sel.changed.map(k => { const df = sel.diff[k] || {};
          const items = df.items ? '<div>' + df.items.map(it => '<div class="meta">' + badge(it.change, it.change === 'removed' ? 'bad' : it.change === 'added' ? 'ok' : 'act') + ' <b>' + esc(it.key) + '</b></div>').join('') + '</div>' : '';
          return '<h3 class="h3" style="margin-top:14px">' + esc(label(k)) + '</h3>' + items + '<div class="pr-diff"><pre class="old">' + esc(df.before == null ? '(not declared)' : JSON.stringify(df.before, null, 2)) + '</pre><pre class="new">' + esc(df.after == null ? '(removed)' : JSON.stringify(df.after, null, 2)) + '</pre></div>'; }).join('') : '<p class="meta">No hashed section changed.</p>');
    }
    const dev = P.deviations || [];
    return card('Version history', '<svg class="pr-svg" viewBox="0 0 ' + svgW + ' 70" role="img" aria-label="Protocol versions">' + line + nodes + '</svg>' + matrix,
      '<b>What it shows</b> The registered protocol and each amendment, with a fingerprint per section.<p><span class=k>How it\'s computed.</span> ' + esc(M.versions || '') + '</p>') +
      card('What changed in ' + sel.protocol_id, diff) +
      card('Deviations', dev.length ? table([['Id', x => '<span class="id">' + esc(x.deviation_id) + '</span>'], ['Protocol', x => esc(x.protocol_id)], ['What', x => esc(x.description)], ['Why', x => esc(x.reason)], ['Affects', x => esc((x.affects || []).join(', '))]], dev) : empty('No deviation has been declared.'),
        '<b>What it shows</b> Departures from the protocol.<p><span class=k>How it\'s computed.</span> ' + esc(M.deviations || '') + '</p>');
  };

  /* ---------- Decisions tab ---------- */
  const decisionsTab = () => {
    const levels = [...new Set(DEC.map(x => x.level))], states = [...new Set(DEC.map(x => x.state))];
    const q = state.q.toLowerCase();
    const shown = DEC.filter(x => (!state.level || x.level === state.level) && (!state.status || x.state === state.status) &&
      (!q || (x.subject + ' ' + x.explanation + ' ' + (x.items || []).map(i => i.text).join(' ')).toLowerCase().includes(q)));
    const groups = {}; shown.forEach(x => (groups[x.level] = groups[x.level] || []).push(x));
    return decisionMap(levels) + '<div class="pr-chips" role="group" aria-label="Filters"><select data-f="level" aria-label="Level"><option value="">All levels</option>' + levels.map(l => '<option' + (l === state.level ? ' selected' : '') + '>' + esc(l) + '</option>').join('') + '</select>' +
      states.map(s => '<button type="button" class="chip" aria-pressed="' + (state.status === s) + '" data-st="' + esc(s) + '">' + esc(s) + '</button>').join('') +
      '<input type="text" data-f="q" placeholder="Search decisions" aria-label="Search decisions" value="' + esc(state.q) + '"> <span class="meta">' + fmt(shown.length) + ' of ' + fmt(DEC.length) + ' decisions</span></div>' +
      (shown.length ? Object.keys(groups).map(l => '<div class="pr-grp">' + esc(l) + '</div>' + groups[l].map(decCard).join('')).join('') : empty('No decision matches.'));
  };
  /* Decision map: one lane per level, dots in order of suggestion, a line from each decision to the one that replaced it. */
  const decisionMap = levels => {
    if (!DEC.length) return '';
    const lv = levels, step = 34, X0 = 110, H0 = 28, svgW = X0 + step * DEC.length + 20, svgH = H0 * lv.length + 24;
    const pos = {}; DEC.forEach((x, i) => { pos[x.decision_id] = [X0 + i * step, 18 + lv.indexOf(x.level) * H0]; });
    const lines = DEC.filter(x => x.superseded_by && pos[x.superseded_by]).map(x => { const a = pos[x.decision_id], b = pos[x.superseded_by];
      return '<path class="ln" d="M' + a[0] + ' ' + a[1] + ' C' + ((a[0] + b[0]) / 2) + ' ' + a[1] + ' ' + ((a[0] + b[0]) / 2) + ' ' + b[1] + ' ' + b[0] + ' ' + b[1] + '"/>'; }).join('');
    const fillOf = s => s === 'selected' ? 'var(--inc)' : s === 'open' ? 'var(--acc)' : 'var(--dim)';
    const dots = DEC.map(x => '<circle class="dotp" tabindex="0" role="button" data-jump="' + esc(x.decision_id) + '" aria-label="' + esc(x.subject + ', ' + x.state) + '" cx="' + pos[x.decision_id][0] + '" cy="' + pos[x.decision_id][1] + '" r="' + (x.decision_id === state.dec ? 8 : 5.5) + '" fill="' + fillOf(x.state) + '"><title>' + esc(x.subject + ' · ' + x.state) + '</title></circle>').join('');
    const lab = lv.map((l, i) => '<text class="axis" x="4" y="' + (22 + i * H0) + '">' + esc(l) + '</text>').join('');
    return '<section class="card pr-card">' + H.header({ title: 'Decision map', infoHtml: (M.tab_decisions || '') + '<p><b>What it shows</b> Every decision by level, in the order it was suggested. Lines join a decision to the one that replaced it.' +
      '<p><span class=k>How to read it.</span> Green is selected, blue open, grey superseded. Click a dot to open its card.</p><p><span class=k>How it\'s computed.</span> ' + esc(M.decisions || '') + '</p>' }) +
      '<div class="pr-scroll"><svg class="pr-svg" style="min-width:' + Math.min(svgW, 900) + 'px" viewBox="0 0 ' + svgW + ' ' + svgH + '" role="img" aria-label="Decision map">' + lab + lines + dots + '</svg></div></section>';
  };

  /* ---------- Reviews and probes ---------- */
  const reviewsTab = () => {
    const R = P.press || [];
    if (!R.length) return empty('No PRESS review has been recorded.');
    return R.map(r => card('Review ' + r.review_id, '<p class="meta">Protocol ' + esc(r.protocol_id) + ' · ' + fmt((r.findings || []).length) + ' findings ' + badge(r.confirmed ? 'confirmed' : 'not confirmed', r.confirmed ? 'ok' : 'act') + '</p>' +
      table([['#', f => fmt(f.n), 1], ['Severity', f => badge(f.severity, f.severity === 'major' ? 'bad' : '')], ['Element', f => esc(label(f.element))], ['Finding', f => esc(f.finding)], ['Response', f => esc(f.response || '')]],
        (r.findings || []).map((f, i) => Object.assign({ n: i + 1, response: (r.responses || [])[i] }, f))),
      (M.tab_press || '') + '<p><b>What it shows</b> An independent critique of the search strategy.</p><p><span class=k>How it\'s computed.</span> ' + esc(M.press || '') + '</p>')).join('');
  };
  const probesTab = () => {
    const R = P.probes || [];
    if (!R.length) return empty('No probe has been run.');
    return R.map(r => card('Round ' + r.round, '<p class="meta">Probe ' + esc(r.probe_id) + ' · ' + fmt((r.queries || []).length) + ' queries</p>' +
      table([['Source', q => esc(q.source)], ['Reported', q => q.reported_count == null ? '' : fmt(q.reported_count), 1], ['Seeds retrieved', q => q.failed ? '' : fmt(q.development_retrieved) + ' of ' + fmt(q.development_tested), 1],
        ['Negatives retrieved', q => q.failed ? '' : fmt(q.negatives_retrieved), 1], ['Query', q => esc(q.text) + (q.failed ? '<div class="meta">' + badge('failed', 'bad') + ' ' + esc(q.reason || '') + '</div>' : '')]], r.queries || []),
      (M.tab_probes || '') + '<p><b>What it shows</b> What each planned query retrieved in a trial run.</p><p><span class=k>How it\'s computed.</span> ' + esc(M.probes || '') + '</p>')).join('');
  };

  /* ---------- draw ---------- */
  function draw() {
    const body = { plan: planTab, versions: versionsTab, decisions: decisionsTab, reviews: reviewsTab, probes: probesTab }[state.tab] || planTab;
    main.innerHTML = head() + '<div class="pr-tabs"><div class="seg" role="group" aria-label="Protocol views">' + TABS.map(t => '<button type="button" aria-pressed="' + (state.tab === t[0]) + '" data-tab="' + t[0] + '">' + t[1] + '</button>').join('') + '</div></div>' + '<div id="pr-body">' + body() + '</div>';
    main.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { state.tab = b.dataset.tab; hs.set({ tab: state.tab }); draw(); });
    main.querySelectorAll('[data-sec]').forEach(b => b.onclick = () => { state.sec = b.dataset.sec; hs.set({ sec: state.sec }); draw(); });
    main.querySelectorAll('[data-v]').forEach(b => { const go = () => { state.ver = b.dataset.v; hs.set({ ver: state.ver }); draw(); };
      b.onclick = go; b.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }; });
    main.querySelectorAll('[data-st]').forEach(b => b.onclick = () => { state.status = state.status === b.dataset.st ? '' : b.dataset.st; draw(); });
    main.querySelectorAll('select[data-f]').forEach(s => s.onchange = () => { state.level = s.value; draw(); });
    main.querySelectorAll('input[data-f]').forEach(i => i.oninput = () => { state.q = i.value; const pos = i.selectionStart; draw(); const n = main.querySelector('input[data-f]'); if (n) { n.focus(); n.setSelectionRange(pos, pos); } });
    main.querySelectorAll('circle[data-jump]').forEach(c => c.onkeydown = e => { if (e.key === 'Enter') jump(c.dataset.jump); });
    wireDecs(main);
  }
  draw();
  document.addEventListener('hub:theme', draw);
});
