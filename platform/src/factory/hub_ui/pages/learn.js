/* Start here (Learn) page. Payload: shell, learn (services/hub_learn.py). Every sentence is declared text of factory.learn;
   the only computed parts are each stage's progress and the facts under it. Read-only. Hash: stage, tab. */
HUB.load(['shell', 'learn']).then(d => {
  const H = HUB.init(d.shell);
  const L = d.learn || {};
  const main = H.mount({ page: 'learn', crumb: 'Start here' });
  const { esc } = H;
  const STAGES = L.stages || [];
  const M = L.methods || {};

  if (!document.getElementById('ln-style')) {
    const st = document.createElement('style'); st.id = 'ln-style';
    st.textContent = `
.ln-strip{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 14px}
.ln-st{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:var(--r);background:var(--raised);color:var(--mut)}
.ln-st.done{background:var(--acc-soft);color:var(--acc)}
.ln-st.blocked-by-human-gate{box-shadow:inset 0 0 0 1px var(--acc);color:var(--fg)}
.ln-st.not-started{color:var(--dim)}
.ln-card{padding:20px 22px;margin-top:var(--gap)}
.ln-card h3{margin:18px 0 6px;font:600 var(--t-m) var(--f-ui)}
.ln-card h3:first-of-type{margin-top:14px}
.ln-goal{font:400 var(--t-m) var(--f-ui);max-width:70ch}
.ln-next{margin:12px 0 0;padding:10px 12px;border-radius:var(--r);background:var(--raised);font:400 var(--t-s) var(--f-ui)}
.ln-steps{margin:0;padding:0;list-style:none;counter-reset:ln}
.ln-steps li{counter-increment:ln;display:grid;grid-template-columns:2em 5.5em 1fr;gap:8px;padding:8px 0;border-top:1px solid var(--hair)}
.ln-steps li::before{content:counter(ln);color:var(--dim);font-family:var(--f-mono)}
.ln-who{font:500 var(--t-xs) var(--f-ui);color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.ln-who.human{color:var(--acc)}
.ln-refs{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.ln-ref{font:400 var(--t-xs) var(--f-mono);padding:2px 6px;border-radius:var(--r-s);background:var(--raised);color:var(--mut);overflow-wrap:anywhere;text-decoration:none}
.ln-ref.skill{color:var(--fg)}
a.ln-ref{color:var(--acc)}
.ln-list{margin:0;padding-left:18px;max-width:72ch}
.ln-list li{margin:4px 0}
.ln-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.ln-term{padding:10px 0;border-top:1px solid var(--hair)}
.ln-term b{font:600 var(--t-s) var(--f-ui)}
.ln-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:22px 0 6px}
.ln-fresh{padding:14px 18px;margin-top:var(--gap)}
@media (max-width:640px){.ln-steps li{grid-template-columns:1.6em 1fr}.ln-steps li .ln-who{grid-column:2}}`;
    document.head.appendChild(st);
  }

  const STATE = {
    'not-started': ['Not started', 'Nothing of this stage is recorded yet.'],
    'in-progress': ['In progress', 'Something of this stage is recorded and its finish is not yet shown.'],
    'done': ['Done', 'The facts that finish this stage hold.'],
    'blocked-by-human-gate': ['Waiting for you', 'An act that only a person may perform is waiting in this stage.'],
  };
  const WHO = { human: 'You', agent: 'Claude', script: 'Platform' };
  const TABS = [['stages', 'Stages'], ['concepts', 'Ideas'], ['glossary', 'Terms']];
  const st = { tab: 'stages', stage: STAGES.length ? STAGES[0].id : '' };

  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'stages';
    const s = p.get('stage');
    if (s && STAGES.some(x => x.id === s)) st.stage = s;
    else if (!st.stage || !STAGES.some(x => x.id === st.stage)) st.stage = STAGES.length ? STAGES[0].id : '';
  };
  const writeHash = () => H.hash.set({ tab: st.tab === 'stages' ? null : st.tab, stage: st.stage });
  const panel = (what, how) => `<b>What it shows</b> ${what}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;

  const stateChip = (p) => { const s = STATE[p.state] || [p.state, '']; return `<span class="ln-st ${esc(p.state)}">${esc(s[0])}</span>`; };
  const ref = r => r.href
    ? `<a class="ln-ref ${esc(r.kind)}" href="${esc(r.href)}">${esc(r.label)}</a>`
    : `<span class="ln-ref ${esc(r.kind)}" title="${esc(r.kind)}">${esc(r.label)}</span>`;

  function card(s) {
    const p = s.progress || {};
    const facts = (p.facts || []).map(f => `<li>${esc(f)}</li>`).join('');
    const waiting = (p.waiting || []).map(w => `<li><code>${esc(w.command)}</code> <span class="meta">${esc(w.gate)}, ${esc(String(w.count))}</span></li>`).join('');
    const steps = s.steps.map(x => `<li><span class="ln-who ${esc(x.actor)}">${esc(WHO[x.actor] || x.actor)}</span><div>${esc(x.text)}<div class="ln-refs">${x.refs.map(ref).join('')}</div></div></li>`).join('');
    const next = s.next_id ? STAGES.find(y => y.id === s.next_id) : null;
    return `<article class="card ln-card" id="stage-${esc(s.id)}">
      <div class="ln-bar" style="margin:0">${stateChip(p)} ${H.info(esc((STATE[p.state] || ['', ''])[1]) + '<p>' + esc(M.progress || '') + '</p>', 'About the state')}<span class="meta">Look at: ${ref(s.page)}</span></div>
      <p class="ln-goal">${esc(s.goal)}</p>
      <div class="ln-next"><b>Next</b> ${esc(p.next_step || '')}</div>
      ${facts ? `<ul class="ln-list meta">${facts}</ul>` : ''}${waiting ? `<h3>Waiting for you</h3><ul class="ln-list">${waiting}</ul>` : ''}
      <h3>Steps ${H.info('Who acts is shown on each line. Claude works through the skill and tools named; you work through the commands and pages named.', 'About the steps')}</h3><ol class="ln-steps">${steps}</ol>
      <h3>Only you ${H.info('These acts have no agent tool, or are refused to an agent. The agent proposes and waits.', 'About the gates')}</h3><ul class="ln-list">${s.gates.map(g => `<li>${esc(g)}</li>`).join('')}</ul>
      <h3>Done looks like ${H.info('A condition that a command or a page shows. The page computes nothing here.', 'About done')}</h3><p>${esc(s.done.condition)}</p><div class="ln-refs">${s.done.shown_by.map(ref).join('')}</div>
      <div class="ln-cols"><div><h3>Five common mistakes</h3><ul class="ln-list">${s.mistakes.map(m => `<li>${esc(m)}</li>`).join('')}</ul></div>
      <div><h3>The rules behind it ${H.info('Rigour rules in plain words. The platform enforces some of them in code and the rest by convention in the skills.', 'About the rules')}</h3><ul class="ln-list">${s.rigour.map(m => `<li>${esc(m)}</li>`).join('')}</ul></div></div>
      ${next ? `<p class="meta" style="margin-top:16px">Next stage: <a href="#stage=${esc(next.id)}" data-stage="${esc(next.id)}">${esc(next.title)}</a></p>` : ''}
    </article>`;
  }

  function stagesView() {
    const strip = STAGES.map(s => `<button type="button" class="chip" data-stage="${esc(s.id)}" aria-pressed="${st.stage === s.id}">${esc(s.title)} ${stateChip(s.progress || {})}</button>`).join('');
    const cur = STAGES.find(s => s.id === st.stage);
    return `<div class="ln-strip">${strip}</div>${cur ? card(cur) : ''}`;
  }
  const conceptsView = () => (L.concepts || []).map(c => `<article class="card ln-card"><h3 style="margin-top:0">${esc(c.title)}</h3><p>${esc(c.text)}</p></article>`).join('');
  const glossaryView = () => `<div class="card ln-card">${(L.glossary || []).map(t => `<div class="ln-term"><b>${esc(t.term)}</b><div>${esc(t.meaning)}</div></div>`).join('')}</div>`;

  function render() {
    const tabs = `<div class="ln-bar"><div class="seg" role="tablist" aria-label="View">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-pressed="${k === st.tab}">${l}</button>`).join('')}</div></div>`;
    const fresh = L.fresh ? `<div class="card ln-fresh"><b>New here?</b> Nothing past the setup is recorded yet. Start with the first stage below. The overview of how the stages connect is on <a href="${esc(L.how_it_works || 'platform.html')}">How it works</a>. In a terminal, <code>factory tour</code> prints the same list.</div>` : '';
    const body = st.tab === 'concepts' ? conceptsView() : st.tab === 'glossary' ? glossaryView() : stagesView();
    main.innerHTML = H.header({ title: 'Start here', sub: 'How a project runs, stage by stage, and where yours stands.', level: 1, infoHtml: panel('The nine stages of a project with who acts in each, what only you may do, and what finished looks like. Your progress comes from the project’s own records.', M.content) }) +
      fresh + tabs + body +
      `<p class="note" style="margin-top:24px">The overview map of the stages and the loops back is on <a href="${esc(L.how_it_works || 'platform.html')}">How it works</a>.</p>`;
    main.querySelectorAll('[data-tab]').forEach(el => { el.onclick = () => { st.tab = el.dataset.tab; writeHash(); render(); }; });
    main.querySelectorAll('[data-stage]').forEach(el => { el.onclick = e => { e.preventDefault(); st.stage = el.dataset.stage; st.tab = 'stages'; writeHash(); render(); }; });
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
