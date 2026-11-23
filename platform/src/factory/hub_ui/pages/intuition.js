/* Intuition page. Payload: shell, intuition (services/hub_intuition.py). Every number comes from the payload.
   Interpretations are agent-written readings of why an idea works; they are shown as interpretations, never as findings.
   Review acts (served hub only): POST /ui/act/intuition-review {interpretation_id, verdict: reviewed|wrong, note}. */
HUB.load(['shell', 'intuition']).then(d => {
  const H = HUB.init(d.shell);
  const D = d.intuition || {};
  const main = H.mount({ page: 'intuition', crumb: 'Intuition' });
  const { esc, fmt } = H;
  const M = D.methods || {};
  const C = D.counts || {};
  const Q = D.queue || { items: [], omitted: 0 }, R = D.reviewed || { items: [], omitted: 0 }, K = D.concepts || { items: [], total: 0, omitted: 0, links_omitted: 0 };

  if (!document.getElementById('in-style')) {
    const st = document.createElement('style'); st.id = 'in-style';
    st.textContent = `
.in-counts{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0 8px}
.in-kpi{background:var(--surface);border-radius:var(--r);padding:12px 16px;min-width:130px}
.in-kpi b{display:block;font:500 var(--t-l) var(--f-mono);color:var(--fg)}
.in-kpi span{font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.in-card{padding:18px;margin-top:var(--gap)}
.in-tag{display:inline-block;font:400 var(--t-xs) var(--f-mono);color:var(--mut);background:var(--raised);border-radius:var(--r);padding:2px 8px}
.in-text{font:400 var(--t-m) var(--f-ui);margin:10px 0;overflow-wrap:anywhere}
.in-meta{font:400 var(--t-xs) var(--f-ui);color:var(--mut);display:flex;flex-wrap:wrap;gap:4px 14px}
.in-q{margin:10px 0 0;padding:8px 12px;border-left:2px solid var(--acc);background:var(--surface)}
.in-q blockquote{margin:0 0 4px;font:400 var(--t-s) var(--f-ui);overflow-wrap:anywhere}
.in-q .meta{font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.in-pass{margin:8px 0 0;padding:10px 12px;background:var(--raised);border-radius:var(--r);font:400 var(--t-s) var(--f-ui);white-space:pre-wrap;overflow-wrap:anywhere}
.in-pass mark{background:var(--acc-soft);color:inherit}
.in-act{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:14px}
.in-act input{flex:1 1 220px;min-width:0}
.in-empty{padding:26px 22px;margin-top:var(--gap)}
.in-empty p{margin:0 0 8px;font:400 var(--t-m) var(--f-ui)}
.in-note{color:var(--mut);font:400 var(--t-s) var(--f-ui);margin:6px 0 0}
.in-con{display:grid;grid-template-columns:minmax(120px,240px) minmax(0,1fr);gap:6px 18px;padding:10px 0;border-top:1px solid var(--line)}
.in-con h4{margin:0;font:500 var(--t-s) var(--f-ui);overflow-wrap:anywhere}
@media (max-width:760px){.in-con{grid-template-columns:minmax(0,1fr)}}`;
    document.head.appendChild(st);
  }

  const panel = (what, how) => `<b>What it shows</b> ${what}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const kpi = (v, l) => `<div class="in-kpi"><b>${fmt(v)}</b><span>${esc(l)}</span></div>`;
  const sect = (title, info, body) => `<section class="card in-card">${H.header({ title, infoHtml: info })}${body}</section>`;
  const more = (n, what) => n ? `<p class="in-note">${fmt(n)} more ${esc(what)} not listed here.</p>` : '';
  const hrefOf = r => r.work_id ? `corpus.html#id=${encodeURIComponent(r.work_id)}` : '';

  const quoteHtml = (s, i) => {
    if (s.kind !== 'quote') return `<div class="in-q"><blockquote>${esc(s.reference || '')}</blockquote><div class="meta">cited reference · ${esc(s.role)}${s.link_state ? ' · ' + esc(s.link_state) : ''}</div></div>`;
    const link = s.work_id ? `<a href="${esc(hrefOf(s))}">${esc(s.work_id)}</a>` : '';
    const pass = s.paragraph ? `<button type="button" class="btn" data-pass="${i}" aria-expanded="false">Whole passage</button><div class="in-pass" hidden>${esc(s.paragraph)}${s.paragraph_cut ? ' …' : ''}</div>` : '<span class="meta">The converted passage could not be read.</span>';
    return `<div class="in-q"><blockquote>“${esc(s.quote)}”</blockquote><div class="meta">${link} · anchor ${esc(s.anchor)} · ${esc(s.role)}</div>${pass}</div>`;
  };

  const head = it => `<div class="in-meta"><span class="in-tag">${esc(it.label)}</span><span>${it.subject_kind === 'idea' ? 'Idea' : 'Paper'}: <b>${esc(it.subject_name)}</b></span></div>`;
  const body = it => `${head(it)}<div class="in-text">${esc(it.text)}</div>${it.sources.map((s, i) => quoteHtml(s, i)).join('')}
    <div class="in-meta" style="margin-top:10px"><span>Written by ${esc(it.author)}: ${esc(it.writer)}</span><span>Session ${esc(it.session)}</span>${it.source_stale.length ? '<span>A source document has been replaced since.</span>' : ''}<span class="mono">${esc(it.id)}</span></div>`;

  const queueCard = it => `<article class="card in-card" data-iid="${esc(it.id)}">${body(it)}
    <div class="in-act"><input type="text" maxlength="2000" placeholder="Note (needed if wrong)" aria-label="Note on this interpretation" ${HUB.served ? '' : 'disabled'}>
    <button type="button" class="btn primary" data-verdict="reviewed" ${HUB.served ? '' : 'disabled title="Available in the live hub"'}>Right</button>
    <button type="button" class="btn" data-verdict="wrong" ${HUB.served ? '' : 'disabled title="Available in the live hub"'}>Wrong</button>
    <span class="meta" data-msg aria-live="polite"></span></div></article>`;

  const doneCard = it => { const r = it.review || {}; return `<article class="card in-card">${body(it)}
    <div class="in-meta" style="margin-top:10px"><span>Reviewed ${esc(r.state || it.state)} by ${esc(r.by || '')}${r.self_reviewed ? ' (the author reviewed it)' : ''}</span>${r.note ? `<span>Note: ${esc(r.note)}</span>` : ''}</div></article>`; };

  const emptyHtml = () => `<div class="card in-empty"><p><b>No interpretations have been written yet.</b></p>
    <p>${esc(D.producer || '')}</p>
    <p class="in-note">Confirmed ideas now: ${fmt(C.confirmed_ideas || 0)}. Waiting for an interpretation: ${fmt(C.waiting_targets || 0)}. When some exist, the ones that need your review appear here first.</p></div>`;

  const conceptRow = c => `<div class="in-con"><div><h4>${esc(c.name)}</h4><span class="in-tag">${esc(c.label)}</span>${c.aliases.length ? `<div class="meta">Also: ${esc(c.aliases.join(', '))}</div>` : ''}</div>
    <div>${c.text ? `<div class="in-text" style="margin-top:0">${esc(c.text)}</div>` : ''}${c.source ? `<div class="meta">Source: ${esc(c.source)}</div>` : ''}
    <div class="in-meta" style="margin-top:6px">${c.ideas.length ? 'Used by: ' + c.ideas.map(u => u.kind === 'idea' ? `<span title="${esc(u.node)}">${esc(u.name)}</span>` : `<a href="corpus.html#id=${encodeURIComponent(u.node)}">${esc(u.name)}</a>`).join(', ') : 'No idea uses it yet.'}</div></div></div>`;

  const render = () => {
    const none = D.empty;
    main.innerHTML = H.header({ title: 'Intuition', sub: 'Why the ideas work, as agents read it. Interpretations, not findings.', level: 1, infoHtml: panel('Interpretations of why ideas work, each bound to quotes of its source, with your review of them. An agent wrote every one; none is a finding until you have reviewed it, and even then it stays an interpretation.', M.summary) }) +
      `<div class="in-counts">${kpi(C.unreviewed || 0, 'need your review')}${kpi(C.reviewed || 0, 'reviewed right')}${kpi(C.wrong || 0, 'reviewed wrong')}${kpi(C.superseded || 0, 'replaced')}${kpi(C.concepts || 0, 'background concepts')}</div>` +
      (none ? emptyHtml() : '') +
      (none ? '' : sect('Needs your review', panel('Interpretations nobody has reviewed. Read the reading, then the quotes beside it; open the whole passage to judge it in context.', M.queue),
        (Q.items.length ? Q.items.map(queueCard).join('') : '<p class="in-note">Nothing waits for your review.</p>') + more(Q.omitted, 'interpretations')) +
        sect('Reviewed', panel('Interpretations a human has reviewed, with the reviewer’s note.', M.reviewed),
        (R.items.length ? R.items.map(doneCard).join('') : '<p class="in-note">None reviewed yet.</p>') + more(R.omitted, 'reviewed interpretations'))) +
      sect('Background concepts', panel('Named notions the interpretations lean on, and the ideas that use each.', M.concepts),
        (K.items.length ? K.items.map(conceptRow).join('') : '<p class="in-note">No background concepts have been recorded.</p>') + more(K.omitted, 'concepts') + more(K.links_omitted, 'links'));
    wire();
  };

  const wire = () => {
    main.querySelectorAll('[data-pass]').forEach(b => { b.onclick = () => { const p = b.nextElementSibling; p.hidden = !p.hidden; b.setAttribute('aria-expanded', String(!p.hidden)); }; });
    main.querySelectorAll('article[data-iid]').forEach(card => {
      const msg = card.querySelector('[data-msg]'), note = card.querySelector('input');
      card.querySelectorAll('[data-verdict]').forEach(b => { b.onclick = () => {
        const verdict = b.dataset.verdict;
        if (verdict === 'wrong' && !note.value.trim()) { msg.textContent = 'Say why it is wrong in the note first.'; return; }
        HUB.confirm(msg, verdict === 'wrong' ? 'Record this interpretation as wrong?' : 'Record this interpretation as right?', () => HUB.post('/ui/act/intuition-review', { interpretation_id: card.dataset.iid, verdict, note: note.value })
          .then(r => { msg.textContent = r.ok ? 'Recorded as your review. The page updates on the next build.' : 'Refused: ' + r.message; if (r.ok) card.querySelectorAll('button[data-verdict]').forEach(x => { x.disabled = true; }); }));
      }; });
    });
  };
  render();
});
