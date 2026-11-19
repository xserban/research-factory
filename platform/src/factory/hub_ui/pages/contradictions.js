/* Contradictions page. Payload: shell, contradictions (services/hub_contradictions.py). Every count comes from the payload.
   Read-only: an agent proposes a pair, the researcher decides on the command line. Hash: state, topic. */
HUB.load(['shell', 'contradictions']).then(d => {
  const H = HUB.init(d.shell);
  const C = d.contradictions || {};
  const main = H.mount({ page: 'contradictions', crumb: 'Contradictions' });
  const { esc, fmt } = H;
  const M = C.methods || {};
  const COUNTS = C.counts || {};
  const TOPICS = C.topics || [];

  if (!document.getElementById('ct-style')) {
    const st = document.createElement('style'); st.id = 'ct-style';
    st.textContent = `
.ct-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:22px 0 14px}
.ct-topic{margin-top:26px}
.ct-topic h3{margin:0 0 8px;font:500 var(--t-m) var(--f-ui)}
.ct-pair{padding:16px 18px;margin-top:var(--gap)}
.ct-head{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px}
.ct-state{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:var(--r);background:var(--raised);color:var(--mut)}
.ct-state.accepted{background:var(--acc-soft);color:var(--acc)}
.ct-state.rejected,.ct-state.stale{color:var(--dim)}
.ct-sides{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.ct-side{background:var(--surface);border-radius:var(--r);padding:12px 14px}
.ct-side h4{margin:0 0 6px;font:500 var(--t-s) var(--f-ui);overflow-wrap:anywhere}
.ct-quote{margin:6px 0;padding-left:10px;border-left:2px solid var(--acc);overflow-wrap:anywhere}
.ct-para{margin:8px 0 0;font:400 var(--t-s) var(--f-ui);color:var(--mut);overflow-wrap:anywhere}
.ct-para mark{background:var(--acc-soft);color:var(--fg)}
.ct-cmd{margin-top:10px;font:400 var(--t-xs) var(--f-mono);color:var(--mut);overflow-wrap:anywhere}
.ct-empty{color:var(--dim);font:400 var(--t-m) var(--f-ui);padding:30px 8px;text-align:center}`;
    document.head.appendChild(st);
  }

  const STATES = [['all', 'All'], ['proposed', 'Proposed'], ['accepted', 'Accepted'], ['rejected', 'Rejected'], ['stale', 'Stale']];
  const st = { state: 'all', topic: null };
  const readHash = () => {
    const p = H.hash.get();
    st.state = STATES.some(s => s[0] === p.get('state')) ? p.get('state') : 'all';
    st.topic = p.get('topic') || null;
  };
  const writeHash = () => H.hash.set({ state: st.state === 'all' ? null : st.state, topic: st.topic });

  const panel = (what, how) => `<b>What it shows</b> ${what}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const PROPOSED_INFO = 'An agent found the two claims in different papers and quoted both exactly. The platform checked each quote against its paragraph. Nothing is settled until you decide.';

  /* the quote is marked inside its paragraph; both are escaped, the mark wraps escaped text only */
  function paragraph(side) {
    const p = side.paragraph || '', q = side.quote || '';
    if (!p) return '<p class="ct-para meta">The paragraph is not available for this claim.</p>';
    const at = q ? p.indexOf(q) : -1;
    if (at < 0) return `<p class="ct-para">${esc(p)}</p>`;
    return `<p class="ct-para">${esc(p.slice(0, at))}<mark>${esc(q)}</mark>${esc(p.slice(at + q.length))}</p>`;
  }
  function sideCard(label, side) {
    const kind = [side.claim_type, side.direction].filter(Boolean).join(' · ');
    return `<div class="ct-side"><h4>${esc(label)}. ${esc(side.title || side.work_id)}</h4>` +
      `<div class="meta mono">${esc(side.work_id)}${side.anchor ? ' · ' + esc(side.anchor) : ''}${kind ? ' · ' + esc(kind) : ''}</div>` +
      `<blockquote class="ct-quote">${esc(side.quote)}</blockquote>${paragraph(side)}</div>`;
  }
  function pairCard(p) {
    const stateInfo = p.state === 'proposed' ? ' ' + H.info(PROPOSED_INFO, 'About a proposed pair') : '';
    return `<article class="card ct-pair" id="pair-${esc(p.id)}"><div class="ct-head"><span class="ct-state ${esc(p.state)}">${esc(p.state)}</span>${stateInfo}<span class="meta mono">${esc(p.id)}</span></div>` +
      (p.note ? `<p>${esc(p.note)}</p>` : '') +
      `<div class="ct-sides">${sideCard('A', p.a)}${sideCard('B', p.b)}</div>` +
      (p.state === 'proposed' ? `<div class="ct-cmd">To decide: <code>${esc(p.decide.confirm)}</code> or <code>${esc(p.decide.reject)}</code></div>` : '') +
      `<details class="ct-cmd"><summary>Start a spar from this pair</summary>` +
      `<div>Hypothesis: ${esc(p.seed.hypothesis)}</div><div>Papers: <span class="mono">${esc(p.seed.selection.include.join(', '))}</span> · layer ${esc(p.seed.selection.layers.join(', '))}</div></details></article>`;
  }

  function render() {
    const total = COUNTS.all || 0;
    const chips = STATES.map(([k, l]) => `<button type="button" class="chip" data-state="${k}" aria-pressed="${st.state === k}">${esc(l)} <span class="n">${fmt(k === 'all' ? total : (COUNTS[k] || 0))}</span></button>`).join('');
    const shown = TOPICS.map(t => ({ ...t, pairs: t.pairs.filter(p => st.state === 'all' || p.state === st.state) }))
      .filter(t => t.pairs.length && (!st.topic || t.topic === st.topic));
    const body = !total
      ? '<div class="card ct-empty">No contradiction is proposed yet. Ask Claude for the Contradictions mode of the chat skill.</div>'
      : !shown.length ? '<div class="card ct-empty">No pair in this state.</div>'
      : shown.map(t => `<section class="ct-topic"><h3>${esc(t.topic)} <span class="meta">${fmt(t.pairs.length)}</span></h3>${t.pairs.map(pairCard).join('')}</section>`).join('');
    const topicBar = TOPICS.length > 1 ? `<div class="ct-bar"><span class="meta">Topic</span><button type="button" class="chip" data-topic="" aria-pressed="${!st.topic}">All</button>${TOPICS.map(t => `<button type="button" class="chip" data-topic="${esc(t.topic)}" aria-pressed="${st.topic === t.topic}">${esc(t.topic)} <span class="n">${fmt(t.count)}</span></button>`).join('')}</div>` : '';
    main.innerHTML = H.header({ title: 'Contradictions', sub: 'Pairs of claims from different papers that disagree.', level: 1, infoHtml: panel('Pairs an agent proposed, each with both exact quotes and their paragraphs, and what you decided.', M.pairs) }) +
      `<div class="ct-bar">${chips}</div>${topicBar}${body}`;
    main.querySelectorAll('[data-state]').forEach(el => { el.onclick = () => { st.state = el.dataset.state; writeHash(); render(); }; });
    main.querySelectorAll('[data-topic]').forEach(el => { el.onclick = () => { st.topic = el.dataset.topic || null; writeHash(); render(); }; });
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
