/* How this study runs (levels) page. Payload: shell, levels (services/hub_levels.py). Read-only. Every figure is computed
   in the payload; the page judges nothing. Sections: level, statement, plan, gates, trust, deferred review, conductor.
   Deciding a deferred act is a command-line act: the page shows the command and writes nothing. No hash state. */
HUB.load(['shell', 'levels']).then(d => {
  const H = HUB.init(d.shell);
  const L = d.levels || {};
  const main = H.mount({ page: 'levels', crumb: 'How this study runs' });
  const { esc, fmt } = H;
  const M = L.methods || {};

  if (!document.getElementById('lv-style')) {
    const st = document.createElement('style'); st.id = 'lv-style';
    st.textContent = `
.lv-badges{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.lv-badge{background:var(--surface);border-radius:var(--r);padding:10px 16px;min-width:160px}
.lv-badge .k{font:500 var(--t-xs) var(--f-ui);color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.lv-badge .v{font:500 var(--t-l) var(--f-ui);margin-top:2px}
.lv-badge .d{font:400 var(--t-xs) var(--f-ui);color:var(--mut);margin-top:4px;max-width:34ch}
.lv-card{margin:0 0 var(--gap)}
.lv-lines{margin:0;padding-left:18px;max-width:72ch}.lv-lines li{margin:4px 0}
.lv-warn{box-shadow:inset 0 0 0 1px var(--acc);padding:10px 12px;border-radius:var(--r);margin:0 0 12px}
.lv-tbl{overflow-x:auto}
.lv-st{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:999px;background:var(--raised);color:var(--mut)}
.lv-st.ok{color:var(--inc)}.lv-st.watch{color:var(--acc)}.lv-st.pause{color:var(--exc);box-shadow:inset 0 0 0 1px var(--exc)}
.lv-st.moved{color:var(--acc)}
.lv-cmd{font:400 var(--t-xs) var(--f-mono);color:var(--dim);overflow-wrap:anywhere}
.lv-empty{color:var(--dim);padding:12px 4px}
.lv-skip{color:var(--dim)}`;
    document.head.appendChild(st);
  }

  const empty = t => `<p class="lv-empty">${esc(t)}</p>`;
  const broken = (what, v) => `<p class="lv-empty">${esc(what)} could not be read: ${esc(v.error)}</p>`;
  const sect = (title, info, body) => `<section class="card lv-card">${H.header({ title, infoHtml: info })}${body}</section>`;
  const caps = c => { const k = Object.keys(c || {}); return k.length ? k.map(x => `${esc(H.pretty(x))} ${fmt(c[x])}`).join(', ') : '—'; };
  const pol = p => p.kind === 'agent_audit' ? `agent, audited${p.fraction != null ? ` (${Math.round(100 * p.fraction)}%, at least ${fmt(p.minimum)})` : ''}` : p.kind;

  function levelSection() {
    const v = L.levels || {};
    if (v.error) return broken('The level', v);
    const b = (k, val, dsc) => `<div class="lv-badge"><div class="k">${k}</div><div class="v">${esc(val)}</div><div class="d">${esc(dsc || '')}</div></div>`;
    return `<div class="lv-badges">${b('Tier', v.tier || 'not declared', v.tier_blurb)}${b('Autonomy', v.autonomy_level, v.level_blurb)}${b('Rigour mode', v.rigor_mode, 'Set by the tier at creation.')}</div>`;
  }
  function statementSection() {
    const s = L.statement || {};
    if (s.error) return sect('What reports say', M.statement, broken('The statement', s));
    const warn = s.human_confirmed ? '' : '<div class="lv-warn"><b>Not human-confirmed.</b> An agent closed acts that no person has reviewed.</div>';
    return sect('What reports say', M.statement, warn + `<ul class="lv-lines">${(s.lines || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`);
  }
  function planSection() {
    const p = L.plan || {};
    if (p.error) return sect('The tier plan', M.plan, broken('The plan', p));
    if (!p.declared) return sect('The tier plan', M.plan, empty('This project predates tiers, so it has no tier plan. Create new studies with a tier to get one.'));
    const rows = (p.stages || []).map(s => `<tr class="${s.skipped ? 'lv-skip' : ''}"><td>${esc(H.pretty(s.stage_id))}</td><td class="mono">${esc(s.skill)}</td><td>${s.skipped ? 'skipped' : 'run'}</td><td>${caps(s.caps)}</td><td>${esc(s.note || '')}</td></tr>`).join('');
    const lim = p.limits ? `<p class="meta">Limits: ${fmt(p.limits.max_papers)} papers, ${fmt(p.limits.max_minutes)} minutes, ${fmt(p.limits.max_runs)} runs.</p>` : '<p class="meta">No limits: this tier is not capped.</p>';
    const sk = (p.skipped || []).length ? `<p>Compared with a systematic review: ${(p.skipped).map(esc).join('; ')}.</p>` : '<p>Nothing is skipped compared with a systematic review.</p>';
    return sect('The tier plan', M.plan, sk + lim + `<div class="lv-tbl"><table class="t"><thead><tr><th>Stage</th><th>Skill</th><th>Step</th><th>Caps</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  function gatesSection() {
    const g = L.gates;
    if (g && g.error) return sect('Who closes each gate', M.gates, broken('The gate table', g));
    if (!g || !g.length) return sect('Who closes each gate', M.gates, empty('No decision gate is registered.'));
    const moved = g.filter(x => x.differs_from_preset).length;
    const rows = g.map(x => `<tr><td class="mono">${esc(x.gate_id)}</td><td>${esc(pol(x.policy))}${x.differs_from_preset ? ` <span class="lv-st moved">moved from ${esc(pol(x.preset))}</span>` : ''}</td><td>${esc(x.floor)}</td><td>${esc(x.who)}</td></tr>`).join('');
    return sect('Who closes each gate', M.gates, `<p class="meta">${fmt(g.length)} decision gates; ${fmt(moved)} differ from the rigour preset.</p><div class="lv-tbl"><table class="t"><thead><tr><th>Gate</th><th>Policy in force</th><th>Floor</th><th>Who may close it</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  function trustSection() {
    const t = L.trust || {};
    if (t.error) return sect('Trust ledger', M.trust, broken('The ledger', t));
    const rows = (t.rows || []).map(r => `<tr><td class="mono">${esc(r.gate_id)}</td><td class="r">${fmt(r.closed_by_agent)}</td><td class="r">${fmt(r.audited)}</td><td class="r">${fmt(r.overturned)}</td><td class="r">${r.overturn_rate == null ? 'n/a' : (100 * r.overturn_rate).toFixed(1) + '%'}</td><td><span class="lv-st ${esc(r.state)}">${esc(r.state)}</span></td></tr>`).join('');
    const body = rows ? `<div class="lv-tbl"><table class="t"><thead><tr><th>Gate</th><th class="r">Closed by an agent</th><th class="r">Audited</th><th class="r">Overturned</th><th class="r">Rate</th><th>State</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('No agent has closed a gate in this study, so the ledger is empty.');
    return sect('Trust ledger', M.trust, body);
  }
  function deferredSection() {
    const q = L.deferred || {};
    if (q.error) return sect('Deferred review', M.deferred, broken('The queue', q));
    if (!q.count) return sect('Deferred review', M.deferred, empty('Nothing waits for review.'));
    const rows = (q.items || []).map(i => `<tr><td class="mono">${esc(i.gate_id)}</td><td class="mono">${esc(i.act_event_id)}</td><td><span class="lv-st ${esc(i.trust_state)}">${esc(i.trust_state)}</span></td><td class="lv-cmd">${esc(i.command)}</td></tr>`).join('');
    const more = q.capped ? `<p class="meta">Showing the first ${fmt((q.items || []).length)} of ${fmt(q.count)}.</p>` : '';
    return sect('Deferred review', M.deferred, `<p>${fmt(q.count)} agent-closed acts wait for a person. Decide each on the command line: <span class="lv-cmd">${esc(q.list_command)}</span></p>${more}<div class="lv-tbl"><table class="t"><thead><tr><th>Gate</th><th>Act</th><th>Trust</th><th>Command</th></tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  function conductorSection() {
    const c = L.conductor || {};
    if (c.error) return sect('Conductor', M.conductor, broken('The conductor', c));
    if (!c.present) return sect('Conductor', M.conductor, empty('The conductor is not part of this platform version.'));
    const s = c.status || {};
    if (s.state === 'none') return sect('Conductor', M.conductor, empty('No conductor run is recorded for this study.'));
    const kv = [['State', s.state], ['Steps done', `${fmt(s.steps_done)} of ${fmt((s.steps || []).length)}`], ['Runs', fmt(s.runs)], ['Minutes', s.minutes != null ? String(s.minutes) : '—'], ['At', s.stage_id ? s.stage_id + (s.role ? ` (${s.role})` : '') : '—'], ['Stopped', s.reason || '—']];
    return sect('Conductor', M.conductor, `<table class="t"><tbody>${kv.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table><ul class="lv-lines">${(s.lines || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`);
  }

  function render() {
    const lv = L.levels || {};
    const lead = lv.error ? 'The level of this study could not be read.' : `This study is ${lv.tier ? 'a ' + lv.tier + ' study' : 'a study from before tiers'} run at the ${lv.autonomy_level} level.`;
    main.innerHTML = H.header({ title: 'How this study runs', sub: 'Tier, autonomy level, who closes each gate, and what still waits for you.', level: 1, infoHtml: M.levels || '' }) +
      `<p class="lead">${esc(lead)}</p>` + levelSection() + statementSection() + planSection() + gatesSection() + trustSection() + deferredSection() + conductorSection();
  }
  render();
  document.addEventListener('hub:theme', render);
});
