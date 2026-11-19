/* Platform page: what the platform can do (capabilities by lifecycle stage) and the backlog board.
   Payload: platform (services/hub_platform.py). Every number comes from the payload. Read-only.
   Tabs: Capabilities, Backlog. Hash keys: tab, stage, q, view, area, state, slice, idea. */
HUB.load(['shell', 'platform']).then(d => {
  const H = HUB.init(d.shell);
  const P = d.platform || {};
  const main = H.mount({ page: 'platform', crumb: 'Platform' });
  const { esc, info } = H;
  const M = P.methods || {};
  const C = P.catalog, B = P.backlog;

  if (!document.getElementById('pl-style')) {
    const st = document.createElement('style'); st.id = 'pl-style';
    st.textContent = `
.pl-tabs{margin:18px 0 20px}
.pl-kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:var(--gap);margin:0 0 14px}
.pl-kpi{padding:14px 16px}.pl-kpi .v{font:500 var(--t-xl) var(--f-mono);line-height:1.1}.pl-kpi .k{font-size:var(--t-xs);color:var(--mut);margin-top:4px}
.pl-kpi.bad .v{color:var(--exc)}
.pl-line{margin:6px 0;font-size:var(--t-s);color:var(--mut)}.pl-line.ok b{color:var(--inc)}.pl-line.bad{color:var(--exc)}
.pl-cmds{margin:10px 0 0;display:grid;gap:6px}.pl-cmds code{font:400 var(--t-s) var(--f-mono);color:var(--fg)}
.pl-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0 10px}
.pl-in{background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:7px 10px;font:inherit;font-size:var(--t-s);min-width:240px;flex:1;max-width:420px}
.pl-sel{background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:6px 8px;font:inherit;font-size:var(--t-s)}
.pl-mx{width:100%;border-collapse:collapse;font-size:var(--t-s)}
.pl-mx th{font-weight:500;color:var(--mut);text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}
.pl-mx td{padding:8px;border-bottom:1px solid var(--hair);vertical-align:middle}
.pl-mx tbody tr{cursor:pointer}.pl-mx tbody tr:hover,.pl-mx tbody tr:focus-visible{background:var(--raised)}
.pl-mx tr[aria-selected=true]{background:var(--acc-soft)}.pl-mx tr.dim{opacity:.35}
.pl-mx td.n,.pl-mx th.n{text-align:right;font-family:var(--f-mono)}
.pl-st b{font-weight:600}.pl-st small{display:block;color:var(--dim);font-size:var(--t-xs)}
.pl-seg{display:flex;height:10px;min-width:120px;background:var(--raised);border-radius:3px;overflow:hidden}
.pl-seg i{display:block;height:100%;background:var(--acc)}
.pl-flag{font:600 var(--t-xs) var(--f-mono);color:var(--exc);background:var(--exc-soft);padding:2px 7px;border-radius:9px}
.pl-mk{font:500 var(--t-xs) var(--f-mono);color:var(--mut)}
.pl-panel{margin:14px 0 24px;padding:18px 20px}
.pl-panel h3{margin:0 0 2px}.pl-panel h4{margin:18px 0 6px;font:500 var(--t-xs) var(--f-ui);color:var(--mut);text-transform:uppercase;letter-spacing:.08em}
.pl-sk{padding:10px 0;border-top:1px solid var(--hair)}.pl-sk:first-of-type{border-top:0}
.pl-sk .nm{font:600 var(--t-s) var(--f-mono)}.pl-sk ol{margin:6px 0 0;padding-left:20px;color:var(--mut);font-size:var(--t-s)}
.pl-sk ol small{color:var(--dim)}
.pl-tl{padding:8px 0;border-top:1px solid var(--hair);font-size:var(--t-s)}
.pl-tl .nm{font:600 var(--t-s) var(--f-mono)}.pl-tl .meta{display:block;margin-top:2px}
.pl-tl details{margin-top:4px}.pl-tl summary{cursor:pointer;color:var(--mut);font-size:var(--t-xs)}
.pl-tl pre{margin:6px 0 0;padding:10px;background:var(--raised);border-radius:var(--r-s);overflow:auto;max-height:260px;font:400 var(--t-xs) var(--f-mono)}
.pl-tag{display:inline-block;font:500 var(--t-xs) var(--f-mono);padding:1px 7px;border-radius:9px;background:var(--raised);color:var(--mut);margin-left:6px}
.pl-sec{margin:34px 0 0}
.pl-sec table{width:100%;border-collapse:collapse;font-size:var(--t-s)}
.pl-sec th{font-weight:500;color:var(--mut);text-align:left;padding:8px;border-bottom:1px solid var(--line)}
.pl-sec td{padding:8px;border-bottom:1px solid var(--hair);vertical-align:top}
.pl-sec td.mono{font:400 var(--t-xs) var(--f-mono);word-break:break-all}
.pl-foot{margin-top:30px;font:400 var(--t-xs) var(--f-mono);color:var(--dim);overflow-wrap:anywhere}
.pl-empty{color:var(--dim);padding:24px 4px}
.pl-areas{display:grid;gap:6px;margin:6px 0 14px}
.pl-ar{display:grid;grid-template-columns:minmax(120px,220px) minmax(0,1fr) 50px;gap:12px;align-items:center;cursor:pointer;background:none;border:0;color:var(--fg);font:inherit;text-align:left;padding:3px 4px;border-radius:var(--r-s);width:100%}
.pl-ar:hover,.pl-ar[aria-pressed=true]{background:var(--raised)}.pl-ar .t{font-size:var(--t-s);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pl-ar .c{text-align:right;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.pl-stack{display:flex;height:12px;border-radius:3px;overflow:hidden;background:var(--raised)}.pl-stack i{display:block;height:100%}
.pl-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:var(--t-xs);color:var(--mut);margin:4px 0 10px}
.pl-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.pl-s-ready{--sc:var(--inc)}.pl-s-blocked{--sc:var(--exc)}.pl-s-specified{--sc:var(--acc)}.pl-s-done{--sc:var(--mut)}.pl-s-parked{--sc:var(--h-null)}
.pl-lay{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:var(--gap);align-items:start}
.pl-cols{display:grid;grid-template-columns:repeat(5,minmax(190px,1fr));gap:var(--gap);overflow-x:auto;padding-bottom:6px}
.pl-col h3{margin:0;font:600 var(--t-s) var(--f-ui);display:flex;gap:8px;align-items:center}
.pl-col h3 i{width:9px;height:9px;border-radius:50%;background:var(--sc)}.pl-col h3 span{font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.pl-col .help{font-size:var(--t-xs);color:var(--dim);margin:2px 0 8px;min-height:2.6em}
.pl-card{display:block;width:100%;text-align:left;font:inherit;color:var(--fg);background:var(--surface);border:0;border-left:3px solid var(--sc);border-radius:var(--r-s);padding:8px 10px;margin:0 0 8px;cursor:pointer}
.pl-card:hover,.pl-card[aria-current=true]{background:var(--raised)}.pl-card[aria-current=true]{box-shadow:inset 0 0 0 1px var(--acc)}
.pl-card .id{font:500 var(--t-xs) var(--f-mono);color:var(--mut)}.pl-card .ti{display:block;font-size:var(--t-s);margin-top:2px}
.pl-card .ft{display:flex;gap:8px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--dim);margin-top:4px}
.pl-more{font-size:var(--t-xs);color:var(--dim);padding:2px 4px}
.pl-det{position:sticky;top:70px;padding:16px 18px;max-height:calc(100vh - 100px);overflow:auto}
.pl-det h3{margin:2px 0 8px;font:500 var(--t-m) var(--f-ui)}.pl-det .f{margin:10px 0}.pl-det .f .k{font-size:var(--t-xs);color:var(--mut)}
.pl-det .f .v{font-size:var(--t-s);white-space:pre-wrap}.pl-det a{cursor:pointer}
.pl-tray{margin-top:var(--gap);padding:14px 18px}.pl-tray ul{margin:8px 0;padding-left:18px;font-size:var(--t-s)}
.pl-tree{overflow:auto;padding:6px}.pl-tree svg{display:block}.pl-tree .nd{cursor:pointer}
.pl-tree .nd circle{fill:var(--sc);stroke:var(--bg);stroke-width:2}.pl-tree .nd.on circle{stroke:var(--acc);stroke-width:3}
.pl-tree .nd.off{opacity:.18}.pl-tree .ed{stroke:var(--line);stroke-width:1.2;fill:none}.pl-tree .ed.on{stroke:var(--acc);stroke-width:2}.pl-tree .ed.off{opacity:.15}
.pl-tree text{font:500 10px var(--f-mono);fill:var(--mut);pointer-events:none}
@media (max-width:1100px){.pl-lay{grid-template-columns:minmax(0,1fr)}.pl-det{position:static;max-height:none}}
@media (max-width:760px){.pl-ar{grid-template-columns:90px minmax(0,1fr) 36px}}`;
    document.head.appendChild(st);
  }

  const TABS = [['cap', 'Capabilities'], ['backlog', 'Backlog']];
  const st = { tab: 'cap', stage: '', q: '', view: 'board', area: '', state: '', slice: '', idea: '', sel: [] };
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'cap';
    st.stage = p.get('stage') || ''; st.q = p.get('q') || ''; st.view = p.get('view') === 'tree' ? 'tree' : 'board';
    st.area = p.get('area') || ''; st.state = p.get('state') || ''; st.slice = p.get('slice') || ''; st.idea = p.get('idea') || '';
  };
  const go = o => { H.hash.set(o); readHash(); render(); };
  const fmt = n => (n == null ? '' : String(n));
  const lc = s => String(s || '').toLowerCase();
  const empty = msg => `<p class="pl-empty">${esc(msg)}</p>`;

  /* ---------------- Capabilities ---------------- */
  const ACCESS_HELP = 'The permission row of the access table: the right a caller needs to run the tool.';
  function kpis(c) {
    const s = c.summary;
    const items = [
      [s.tools_registered, 'Tools registered'], [s.tools_listed, 'Tools listed'], [s.skills, 'Skills'],
      [s.prompts == null ? 'not derived' : s.prompts, 'Prompts'], [s.examples, 'Worked examples'],
      [s.marked, 'Marked tools'], [s.orphan_tools, 'Orphan tools', s.orphan_tools > 0], [s.flags, 'Flags', s.flags > 0],
    ];
    return `<div class="pl-kpis">${items.map(([v, k, bad]) => `<div class="card pl-kpi${bad ? ' bad' : ''}"><div class="v">${esc(fmt(v))}</div><div class="k">${esc(k)}</div></div>`).join('')}</div>`;
  }
  function countCheck(c) {
    const cc = c.count_check, s = c.summary;
    let h;
    if (cc.ok) h = `<div class="pl-line ok"><b>Count check passed.</b> ${esc(fmt(s.tools_registered))} tools in the source, all listed by the built server.</div>`;
    else {
      const parts = [['not listed', cc.missing], ['not in source', cc.extra], ['duplicate', cc.duplicates]].filter(p => p[1].length).map(p => p[0] + ': ' + p[1].join(', '));
      h = `<div class="pl-line bad">Count check failed. Registered ${esc(fmt(s.tools_registered))}, listed ${esc(fmt(s.tools_listed))}. ${esc(parts.join('; '))}</div>`;
    }
    const sk = Object.entries(c.skipped || {}).map(([k, v]) => `<div class="pl-line">Not derived: ${esc(k)} (${esc(v)}). Absent, not zero.</div>`).join('');
    return h + sk;
  }
  function matches(c) {
    const q = lc(st.q); if (!q) return null;
    const hit = new Set();
    c.tools.forEach(t => { if (lc(t.n).includes(q) || lc(t.d).includes(q)) hit.add(t.stage || 'unassigned'); });
    c.skills.forEach(s => { if (lc(s.n).includes(q) || lc(s.d).includes(q)) hit.add(s.stages[0] || 'unassigned'); });
    return hit;
  }
  function matrix(c) {
    const hit = matches(c), maxT = Math.max(1, ...c.stages.map(r => r.n_tools));
    const rows = c.stages.map(r => {
      const mk = Object.entries(r.markers).map(([k, n]) => `${k} ${n}`).join(' · ');
      const ac = Object.entries(r.access).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(' · ');
      const dim = hit && !hit.has(r.id) ? ' dim' : '';
      return `<tr tabindex="0" data-stage="${esc(r.id)}" class="${dim.trim()}" aria-selected="${st.stage === r.id}">
        <td class="pl-st"><b>${esc(r.label)}</b><small>${esc(r.covers)}</small></td>
        <td class="n">${esc(fmt(r.n_skills))}</td><td class="n">${esc(fmt(r.n_tools))}</td>
        <td style="min-width:130px"><div class="pl-seg" role="img" aria-label="${esc(r.label)}: ${esc(fmt(r.n_tools))} tools"><i style="width:${Math.round(100 * r.n_tools / maxT)}%"></i></div></td>
        <td class="pl-mk">${esc(mk || '—')}</td><td class="pl-mk">${esc(ac || '—')}</td>
        <td class="n">${r.n_flags ? `<span class="pl-flag" title="Flags in this stage">${esc(fmt(r.n_flags))}</span>` : ''}</td></tr>`;
    }).join('');
    return `<div class="card" style="overflow-x:auto"><table class="pl-mx"><thead><tr><th>Stage</th><th class="n">Skills</th><th class="n">Tools</th><th>Share of tools</th><th>Markers</th><th>Access rows ${info(esc(ACCESS_HELP), 'About access rows')}</th><th class="n">Flags</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  const toolHtml = (t, c) => {
    const tags = (t.marker ? `<span class="pl-tag">${esc(t.marker)}</span>` : '') + (t.access ? `<span class="pl-tag" title="Access row">${esc(t.access)}</span>` : '');
    const first = String(t.d || '').split('\n')[0];
    return `<div class="pl-tl" id="tool-${esc(t.n)}"><span class="nm">${esc(t.n)}</span>${tags}<span class="meta">${esc(first)}</span>
      <span class="meta">Inputs: ${esc((t.params || []).join(', ') || 'none')}${t.skills.length ? ' · named by ' + esc(t.skills.join(', ')) : ''}${t.also.length ? ' · also used in ' + esc(t.also.join(', ')) : ''}</span>
      <details><summary>Input schema</summary><pre>${esc(t.schema)}</pre></details></div>`;
  };
  const skillHtml = s => `<div class="pl-sk"><span class="nm">${esc(s.n)}</span>${s.stages.length > 1 ? `<span class="pl-tag">also ${esc(s.stages.slice(1).join(', '))}</span>` : ''}
    <div class="meta" style="color:var(--mut);font-size:var(--t-s)">${esc(s.d)}</div>
    ${s.steps.length ? `<ol>${s.steps.map(x => `<li>${esc(x.text)} <small>${esc(x.file)}:${esc(fmt(x.line))}</small></li>`).join('')}</ol>` : ''}</div>`;
  function panel(c) {
    const r = c.stages.find(x => x.id === st.stage); if (!r) return '';
    const q = lc(st.q), keep = x => !q || lc(x.n).includes(q) || lc(x.d).includes(q);
    const skills = c.skills.filter(s => (s.stages[0] || 'unassigned') === r.id).filter(keep);
    const tools = c.tools.filter(t => (t.stage || 'unassigned') === r.id).filter(keep);
    const flags = r.flags || [];
    return `<div class="card raised pl-panel" id="pl-panel"><h3>${esc(r.label)}</h3><div class="meta">${esc(r.covers)}</div>
      <h4>Skills (${esc(fmt(skills.length))})</h4>${skills.map(skillHtml).join('') || empty('No skill has this stage' + (q ? ' that matches the search.' : '.'))}
      <h4>Tools (${esc(fmt(tools.length))})</h4>${tools.map(t => toolHtml(t, c)).join('') || empty('No tool is assigned here' + (q ? ' that matches the search.' : '.'))}
      ${flags.length ? `<h4>Flags (${esc(fmt(flags.length))})</h4>${flags.map(f => `<div class="pl-tl"><span class="nm">${esc(f.c)}</span><span class="meta mono">${esc(f.w)}</span><span class="meta">${esc(f.m)}</span></div>`).join('')}` : ''}</div>`;
  }
  function unassigned(c) {
    const orph = c.tools.filter(t => c.orphans.includes(t.n)), sl = c.skills.filter(s => c.stageless.includes(s.n));
    return `<section class="pl-sec">${H.header({ title: 'Unassigned', sub: 'Tools no skill names and no marker covers, and skills with no valid stage.' })}
      ${orph.length || sl.length ? sl.map(skillHtml).join('') + orph.map(t => toolHtml(t, c)).join('') : empty('None.')}</section>`;
  }
  function marked(c) {
    const rows = c.marked.map(m => `<tr><td class="mono">${esc(m.tool)}</td><td>${esc(m.kind)}</td><td>${esc(m.why)}${m.accepted ? ' <i>Access row differs: ' + esc(m.accepted) + '</i>' : ''}</td><td class="mono">${esc(m.access || 'no access row')}</td><td>${esc(m.skills.join(', ') || 'none')}</td></tr>`).join('');
    return `<section class="pl-sec">${H.header({ title: 'Marked tools', infoHtml: esc(M.markers || ''), sub: 'A marked tool that no skill names is not an orphan.' })}
      ${rows ? `<div class="card" style="overflow-x:auto"><table><thead><tr><th>Tool</th><th>Marker</th><th>Why</th><th>Access row</th><th>Named by</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('No tool is marked.')}</section>`;
  }
  function flags(c) {
    const rows = c.flags.map(f => `<tr><td class="mono">${esc(f.code)}</td><td class="mono">${esc(f.where)}</td><td>${esc(f.msg)}${f.other ? '<br><span class="meta">' + esc(f.other) + '</span>' : ''}</td></tr>`).join('');
    return `<section class="pl-sec">${H.header({ title: 'Flags', infoHtml: esc(M.flags || ''), sub: 'Mechanical findings, listed for the researcher to judge. The platform rules on none of them.' })}
      ${rows ? `<div class="card" style="overflow-x:auto"><table><thead><tr><th>Code</th><th>Where</th><th>Finding</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('No flags.')}</section>`;
  }
  function cap() {
    if (!C) return empty('The capability catalog could not be built' + (P.catalog_error ? ': ' + P.catalog_error : '.'));
    const cmds = (P.commands || []).map(x => `<div><code>${esc(x.cmd)}</code> <span class="meta">${esc(x.what)}</span></div>`).join('');
    const f = C.footer || {};
    return `${H.header({ title: 'What the platform can do', infoHtml: esc(M.catalog || ''), sub: 'Tools, skills and flags by lifecycle stage.' })}
      ${kpis(C)}${countCheck(C)}
      <details class="pl-line"><summary>Commands that build and serve the hubs</summary><div class="pl-cmds">${cmds}</div></details>
      <div class="pl-bar"><input class="pl-in" type="search" id="pl-q" placeholder="Search tools and skills" aria-label="Search tools and skills" value="${esc(st.q)}">
        <span class="meta">Click a stage for its skills, tools and flags.</span></div>
      <section>${H.header({ title: 'Stages', infoHtml: esc(M.matrix || '') })}${matrix(C)}</section>
      ${panel(C)}${unassigned(C)}${marked(C)}${flags(C)}
      <div class="pl-foot">Code ${esc(f.code || '')} · decisions ${esc(f.decisions_sha || 'not derived')} · skills ${esc(Object.entries(f.skills || {}).map(([k, v]) => k + ' ' + v).join(', '))}</div>`;
  }
  function wireCap() {
    main.querySelectorAll('[data-stage]').forEach(el => {
      const f = () => go({ stage: st.stage === el.dataset.stage ? '' : el.dataset.stage });
      el.addEventListener('click', f); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); f(); } });
    });
    const q = main.querySelector('#pl-q');
    if (q) q.addEventListener('input', () => { H.hash.set({ q: q.value }); readHash(); const pos = q.selectionStart; render(); const n = main.querySelector('#pl-q'); if (n) { n.focus(); n.setSelectionRange(pos, pos); } });
  }

  /* ---------------- Backlog ---------------- */
  const SL = { ready: 'Ready', blocked: 'Blocked', specified: 'Specified', done: 'Done', parked: 'Parked' };
  const SHELP = {
    ready: 'Open, with every dependency done. Sorted by how many ideas it unlocks.',
    blocked: 'Waiting on a dependency that is not done.',
    specified: 'Accepted, with a spec or plan; not built.',
    done: 'Built.',
    parked: 'Parked or rejected.',
  };
  const byId = () => Object.fromEntries(B.ideas.map(i => [i.id, i]));
  function visible() {
    const q = lc(st.q);
    return B.ideas.filter(i => (!st.area || i.area === st.area) && (!st.state || i.state === st.state) && (!st.slice || i.slice === st.slice) &&
      (!q || lc(i.id + ' ' + i.title + ' ' + i.what).includes(q)));
  }
  function areaBars() {
    const total = Math.max(1, ...B.areas.map(a => Object.values(B.by_area[a]).reduce((x, y) => x + y, 0)));
    return `<div class="pl-areas" role="group" aria-label="Ideas per area">${B.areas.map(a => {
      const row = B.by_area[a], n = Object.values(row).reduce((x, y) => x + y, 0);
      const seg = (B.states || []).map(s => row[s] ? `<i class="pl-s-${s}" style="width:${100 * row[s] / total}%;background:var(--sc)" title="${esc(SL[s])}: ${esc(fmt(row[s]))}"></i>` : '').join('');
      return `<button type="button" class="pl-ar" data-area="${esc(a)}" aria-pressed="${st.area === a}"><span class="t">${esc(a)}</span><span class="pl-stack">${seg}</span><span class="c">${esc(fmt(n))}</span></button>`;
    }).join('')}</div>
    <div class="pl-legend">${(B.states || []).map(s => `<span><i class="pl-s-${s}" style="background:var(--sc)"></i>${esc(SL[s])} ${esc(fmt(B.by_state[s]))}</span>`).join('')}</div>`;
  }
  const card = i => `<button type="button" class="pl-card pl-s-${esc(i.state)}" data-idea="${esc(i.id)}" aria-current="${st.idea === i.id}">
    <span class="id">${esc(i.id)}</span><span class="ti">${esc(i.title)}</span>
    <span class="ft"><span>${esc(i.area)}</span>${i.unmet.length ? `<span>${esc(fmt(i.unmet.length))} unmet</span>` : ''}${i.unlocks ? `<span>unlocks ${esc(fmt(i.unlocks))}</span>` : ''}</span></button>`;
  function board(list) {
    return `<div class="pl-cols">${(B.states || []).map(s => {
      const items = list.filter(i => i.state === s).sort((a, b) => (s === 'ready' ? b.unlocks - a.unlocks : 0) || a.n - b.n);
      return `<div class="pl-col pl-s-${s}"><h3><i></i>${esc(SL[s])} <span>${esc(fmt(items.length))}</span></h3><div class="help">${esc(SHELP[s])}</div>${items.map(card).join('') || '<div class="pl-more">None.</div>'}</div>`;
    }).join('')}</div>`;
  }
  function tree(list) {
    const ids = new Set(list.map(i => i.id)), all = byId();
    const nodes = list.filter(i => i.deps.some(d => ids.has(d)) || i.dependents.some(d => ids.has(d)));
    if (!nodes.length) return empty('No idea in this view has a recorded idea dependency.');
    const layers = {}; nodes.forEach(n => (layers[n.layer] = layers[n.layer] || []).push(n));
    const keys = Object.keys(layers).map(Number).sort((a, b) => a - b), W = 170, Hh = 22, pos = {};
    let maxRows = 0;
    keys.forEach((k, ci) => { layers[k].sort((a, b) => a.n - b.n).forEach((n, r) => { pos[n.id] = [30 + ci * W, 24 + r * Hh]; }); maxRows = Math.max(maxRows, layers[k].length); });
    const w = 60 + keys.length * W, h = 40 + maxRows * Hh;
    const lit = new Set(); const hov = st.idea;
    if (hov && pos[hov]) { const walk = (id, f) => { (all[id][f] || []).forEach(x => { if (pos[x] && !lit.has(x)) { lit.add(x); walk(x, f); } }); }; lit.add(hov); walk(hov, 'deps'); walk(hov, 'dependents'); }
    const edges = nodes.flatMap(n => n.deps.filter(d => pos[d]).map(d => {
      const [x1, y1] = pos[d], [x2, y2] = pos[n.id], on = lit.has(d) && lit.has(n.id), off = hov && !on;
      return `<path class="ed${on ? ' on' : ''}${off ? ' off' : ''}" d="M${x1},${y1} C${x1 + 70},${y1} ${x2 - 70},${y2} ${x2},${y2}"/>`;
    })).join('');
    const circ = nodes.map(n => `<g class="nd pl-s-${esc(n.state)}${hov && !lit.has(n.id) ? ' off' : ''}${st.idea === n.id ? ' on' : ''}" data-idea="${esc(n.id)}" transform="translate(${pos[n.id][0]},${pos[n.id][1]})"><title>${esc(n.id + ' ' + n.title + ' (' + SL[n.state] + ')')}</title><circle r="7"/><text x="12" y="3">${esc(n.id.replace('IDEA-', ''))} ${esc(n.title.slice(0, 18))}</text></g>`).join('');
    const listAlt = `<details style="margin-top:12px"><summary class="meta">The same dependencies as a list</summary><ul style="font-size:var(--t-s)">${nodes.map(n => `<li><a href="#" data-idea="${esc(n.id)}">${esc(n.id)} ${esc(n.title)}</a> (${esc(SL[n.state])})${n.deps.length ? ', depends on ' + esc(n.deps.join(', ')) : ''}</li>`).join('')}</ul></details>`;
    return `<div class="card pl-tree">${H.header({ title: 'Dependency tree', infoHtml: esc(M.tree || ''), sub: 'Dependencies on the left. Select an idea to light its chain.' })}<svg width="${w}" height="${h}" role="img" aria-label="Dependency tree of backlog ideas">${edges}${circ}</svg>${listAlt}</div>`;
  }
  function detail() {
    const i = byId()[st.idea];
    if (!i) return `<aside class="card pl-det" aria-label="Idea detail"><div class="meta">Select an idea to read its detail.</div></aside>`;
    const fld = (k, v) => v ? `<div class="f"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>` : '';
    const links = i.deps.length ? i.deps.map(d => `<a data-idea="${esc(d)}">${esc(d)}</a>`).join(', ') : '';
    const inSel = st.sel.includes(i.id);
    return `<aside class="card pl-det pl-s-${esc(i.state)}" aria-label="Idea detail"><div class="meta">${esc(i.id)} · ${esc(i.area)}</div><h3>${esc(i.title)}</h3>
      <div class="f"><span class="pl-tag" style="margin:0;color:var(--sc)">${esc(SL[i.state])}</span></div>
      ${fld('Status (as written)', i.status_raw)}${fld('Added', i.added)}${fld('Slice', i.slice)}
      ${links ? `<div class="f"><div class="k">Depends on</div><div class="v">${links}</div></div>` : fld('Depends on', i.depends_raw)}
      ${i.unmet.length ? fld('Still needs first', i.unmet.join(', ')) : ''}${fld('Unlocks', i.unlocks ? String(i.unlocks) + ' open ideas' : '')}
      ${fld('What', i.what)}${fld('Why', i.why)}${fld('Rigour notes', i.rigour)}${fld('Open questions', i.open)}
      <button type="button" class="btn" id="pl-sel">${inSel ? 'Remove from selection' : 'Add to selection'}</button></aside>`;
  }
  function brief() {
    const all = byId();
    return 'Brief for the orchestrator. Ideas selected from the backlog:\n' + st.sel.map(id => {
      const i = all[id]; if (!i) return '';
      return '- ' + i.id + ' ' + i.title + ' (' + SL[i.state] + (i.unmet.length ? '; first needs ' + i.unmet.join(', ') : '') + ')\n  What: ' + i.what;
    }).join('\n') + '\nWork on them in dependency order, one atomic task each. Nothing here is a decision.';
  }
  function tray() {
    if (!st.sel.length) return '';
    const all = byId();
    return `<div class="card pl-tray"><b>Selection (${esc(fmt(st.sel.length))})</b><ul>${st.sel.map(id => { const i = all[id]; return i ? `<li><a data-idea="${esc(id)}">${esc(id)}</a> ${esc(i.title)}${i.unmet.length ? ' <span class="meta">needs ' + esc(i.unmet.join(', ')) + ' first</span>' : ''}</li>` : ''; }).join('')}</ul>
      <button type="button" class="btn" id="pl-copy">Copy brief</button> <button type="button" class="btn" id="pl-clear">Clear</button> <span class="meta" id="pl-copied" role="status"></span>
      <div class="meta" style="margin-top:6px">Kept in this page only. Nothing is written back.</div></div>`;
  }
  function backlog() {
    if (!B) return empty('The backlog could not be read' + (P.backlog_error ? ': ' + P.backlog_error : '.'));
    if (!B.found) return empty('The backlog document was not found. Set FACTORY_BACKLOG to its path.');
    const list = visible();
    const chips = `<button class="chip" data-area="" aria-pressed="${!st.area}">All areas</button>` + B.areas.map(a => `<button class="chip" data-area="${esc(a)}" aria-pressed="${st.area === a}">${esc(a)}</button>`).join('');
    const note = st.area && B.notes[st.area] ? `<p class="note">${esc(B.notes[st.area])}</p>` : '';
    return `${H.header({ title: 'Backlog', infoHtml: esc(M.backlog || ''), sub: 'Every idea on the board, ready ones first by how many they unlock.' })}
      ${areaBars()}
      <div class="pl-bar"><div class="seg" role="group" aria-label="View"><button data-view="board" aria-pressed="${st.view === 'board'}">Board</button><button data-view="tree" aria-pressed="${st.view === 'tree'}">Dependency tree</button></div>
        <input class="pl-in" type="search" id="pl-q" placeholder="Filter ideas" aria-label="Filter ideas" value="${esc(st.q)}">
        <select class="pl-sel" id="pl-slice" aria-label="Slice"><option value="">All slices</option>${B.slices.map(s => `<option value="${esc(s)}"${st.slice === s ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select>
        <span class="meta" role="status">${esc(fmt(list.length))} of ${esc(fmt(B.ideas.length))} ideas</span></div>
      <div class="pl-bar" style="margin-top:0">${chips}</div>${note}
      <div class="pl-lay"><div>${st.view === 'tree' ? tree(list) : board(list)}</div><div>${detail()}${tray()}</div></div>
      <div class="pl-foot">Source ${esc(B.path)} · digest ${esc(B.digest)}</div>`;
  }
  function wireBacklog() {
    main.querySelectorAll('[data-area]').forEach(el => el.addEventListener('click', () => go({ area: st.area === el.dataset.area ? '' : el.dataset.area })));
    main.querySelectorAll('[data-view]').forEach(el => el.addEventListener('click', () => go({ view: el.dataset.view })));
    main.querySelectorAll('[data-idea]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); go({ idea: el.dataset.idea }); }));
    const sl = main.querySelector('#pl-slice'); if (sl) sl.addEventListener('change', () => go({ slice: sl.value }));
    const q = main.querySelector('#pl-q');
    if (q) q.addEventListener('input', () => { H.hash.set({ q: q.value }); readHash(); const pos = q.selectionStart; render(); const n = main.querySelector('#pl-q'); if (n) { n.focus(); n.setSelectionRange(pos, pos); } });
    const s = main.querySelector('#pl-sel');
    if (s) s.addEventListener('click', () => { st.sel = st.sel.includes(st.idea) ? st.sel.filter(x => x !== st.idea) : [...st.sel, st.idea]; render(); });
    const cl = main.querySelector('#pl-clear'); if (cl) cl.addEventListener('click', () => { st.sel = []; render(); });
    const cp = main.querySelector('#pl-copy');
    if (cp) cp.addEventListener('click', () => {
      const say = t => { const n = main.querySelector('#pl-copied'); if (n) n.textContent = t; };
      try { navigator.clipboard.writeText(brief()).then(() => say('Copied.'), () => say('Copy was blocked by the browser.')); } catch (e) { say('Copy was blocked by the browser.'); }
    });
  }

  function render() {
    const hdr = H.header({ title: 'Platform', sub: 'What the platform can do, and what is planned.', level: 1 });
    const tabs = `<div class="pl-tabs"><div class="seg" role="tablist" aria-label="View">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-pressed="${k === st.tab}">${l}</button>`).join('')}</div></div>`;
    main.innerHTML = hdr + tabs + (st.tab === 'cap' ? cap() : backlog());
    main.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => go({ tab: b.dataset.tab })));
    if (st.tab === 'cap') wireCap(); else wireBacklog();
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
});
