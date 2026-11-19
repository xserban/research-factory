/* Chat page (night feature N5). Payload: shell, chat (services/hub_chat.py); served mode also reads `ui/chat?...` live.
   An agent proposes; you rate each argument or sentence and write the balance yourself. Every quote is shown with its
   FULL paragraph. Writes (served only): the four allow-listed acts, each as you (the local human).
   Hash: layers, include, exclude, only (the basket), kind, mode, hyp, parent (the form), sheet or answer (the open result). */
HUB.load(['shell', 'chat']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'chat', crumb: 'Chat with papers' });
  const { esc, fmt } = H;
  let C = d.chat || {};

  if (!document.getElementById('ch-style')) {
    const st = document.createElement('style'); st.id = 'ch-style';
    st.textContent = `
.ch-card{padding:16px 18px;margin-top:var(--gap)}
.ch-card h3{margin:0 0 8px;font:500 var(--t-m) var(--f-ui)}
.ch-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.ch-works{max-height:240px;overflow:auto;margin:8px 0;padding:0;list-style:none;font:400 var(--t-s) var(--f-ui)}
.ch-works li{display:flex;gap:8px;align-items:baseline;padding:3px 0;border-bottom:1px solid var(--hair)}
.ch-works .t{flex:1;overflow-wrap:anywhere}
.ch-form textarea,.ch-form input[type=text],.ch-form select{width:100%;font:400 var(--t-s) var(--f-ui);background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:8px}
.ch-state{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:var(--r);background:var(--raised);color:var(--mut)}
.ch-state.done{background:var(--acc-soft);color:var(--acc)}.ch-state.failed{color:var(--exc)}
.ch-bal{background:var(--raised);border-radius:var(--r);padding:14px 16px;margin:12px 0}
.ch-bal textarea{width:100%;min-height:110px;font:400 var(--t-m) var(--f-display);background:var(--surface);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:10px}
.ch-item{background:var(--surface);border-radius:var(--r);padding:12px 14px;margin-top:12px;border-left:3px solid var(--line)}
.ch-item.against{border-left-color:var(--exc)}.ch-item.for{border-left-color:var(--inc)}
.ch-quote{margin:6px 0;padding-left:10px;border-left:2px solid var(--acc);overflow-wrap:anywhere}
.ch-para{white-space:pre-line;margin:8px 0 0;font:400 var(--t-s) var(--f-ui);color:var(--mut);overflow-wrap:anywhere}
.ch-para mark{background:var(--acc-soft);color:var(--fg)}
.ch-rate{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}
.ch-rate input[type=text]{flex:1;min-width:160px;font:400 var(--t-s) var(--f-ui);background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:6px}
.ch-list a{overflow-wrap:anywhere}
.ch-empty{color:var(--dim);font:400 var(--t-s) var(--f-ui);padding:8px 0}`;
    document.head.appendChild(st);
  }

  /* ---------- state: the address holds the basket, the form and the open result ---------- */
  const st = { layers: [], include: [], exclude: [], only: false, kind: 'spar', mode: 'explore', hyp: '', parent: '', sheet: '', answer: '' };
  const csv = v => (v || '').split(',').map(x => x.trim()).filter(Boolean);
  const readHash = () => {
    const p = H.hash.get();
    st.layers = csv(p.get('layers')); st.include = csv(p.get('include')); st.exclude = csv(p.get('exclude'));
    st.only = p.get('only') === '1';
    st.kind = p.get('kind') === 'ask' ? 'ask' : 'spar';
    st.mode = p.get('mode') === 'prepare' ? 'prepare' : 'explore';
    st.hyp = p.get('hyp') || ''; st.parent = p.get('parent') || '';
    st.sheet = p.get('sheet') || ''; st.answer = p.get('answer') || '';
  };
  const writeHash = () => H.hash.set({
    layers: st.layers.join(',') || null, include: st.include.join(',') || null, exclude: st.exclude.join(',') || null,
    only: st.only ? '1' : null, kind: st.kind === 'ask' ? 'ask' : null, mode: st.mode === 'prepare' ? 'prepare' : null,
    hyp: st.hyp || null, parent: st.parent || null, sheet: st.sheet || null, answer: st.answer || null,
  });
  const spec = () => ({ layers: st.layers, include: st.include, exclude: st.exclude });
  const basketQuery = () => { const p = new URLSearchParams({ basket: '1' }); if (st.layers.length) p.set('layers', st.layers.join(',')); if (st.include.length) p.set('include', st.include.join(',')); if (st.exclude.length) p.set('exclude', st.exclude.join(',')); if (st.only) p.set('only', '1'); return p.toString(); };

  const getLive = q => HUB.get('/ui/chat' + (q ? '?' + q : '')).then(r => r.json().then(j => ({ ok: r.ok, j })));
  const panel = (what, how) => `<b>What it shows</b> ${what}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const M = C.methods || {};
  const say = (host, text) => { host.textContent = text; };

  /* ---------- the quote with its full paragraph, the quote marked by the payload's span ---------- */
  function paragraph(a) {
    const p = a.paragraph || '', m = a.mark;
    if (!p) return '<p class="ch-para meta">The paragraph is not available for this quote.</p>';
    if (!Array.isArray(m) || m.length !== 2) return `<p class="ch-para">${esc(p)}</p>`;
    return `<p class="ch-para">${esc(p.slice(0, m[0]))}<mark>${esc(p.slice(m[0], m[1]))}</mark>${esc(p.slice(m[1]))}</p>`;
  }
  const quoteBlock = a => `<blockquote class="ch-quote">${esc(a.quote)}</blockquote>${paragraph(a)}`;
  const where = a => `<div class="meta"><b>${esc(a.title || a.work_id)}</b> <span class="mono">${esc(a.work_id)}${a.anchor ? ' · ' + esc(a.anchor) : ''}</span></div>`;

  /* ---------- 1. the basket ---------- */
  const basketHost = () => main.querySelector('#ch-basket');
  function basketHtml(b, err) {
    const layerBtns = H.LAYERS.filter(l => l[0] !== 'unlayered').map(l => `<button type="button" class="chip" data-layer="${esc(l[0])}" aria-pressed="${st.layers.includes(l[0])}">${esc(l[1])}</button>`).join('');
    const chips = (ids, kind) => ids.map(id => `<button type="button" class="chip" data-drop="${kind}" data-id="${esc(id)}" title="Remove from this list">${esc(id)} <span class="x">×</span></button>`).join('');
    const size = b && !err ? `<div class="meta"><b class="num">${fmt(b.count)}</b> papers · about <b class="num">${fmt(b.est_tokens)}</b> tokens${b.not_picked ? ` · ${fmt(b.not_picked)} not picked` : ''}${b.left_out && b.left_out.length ? ` · left out: ${b.left_out.map(x => esc(x.work_id) + ' (' + esc(x.reason) + ')').join(', ')}` : ''}</div>` : '';
    const works = b && !err ? `<ul class="ch-works">${b.works.slice(0, 200).map(w => `<li><span class="t">${esc(w.title || w.work_id)}</span><span class="meta mono">${fmt(w.est_tokens)}</span></li>`).join('')}</ul>${b.works.length > 200 ? `<div class="meta">The first 200 of ${fmt(b.works.length)} are listed.</div>` : ''}` : '';
    return `<div class="ch-row"><span class="meta">Whole layers</span>${layerBtns}</div>
      <div class="ch-row"><span class="meta">Papers added</span>${chips(st.include, 'include') || '<span class="meta">none</span>'}
        <label class="meta"><input type="checkbox" id="ch-only" ${st.only ? 'checked' : ''}> only these papers</label></div>
      <div class="ch-row"><span class="meta">Papers removed</span>${chips(st.exclude, 'exclude') || '<span class="meta">none</span>'}</div>
      ${err ? `<div class="ch-empty">${esc(err)}</div>` : size + works}`;
  }
  function wireBasket() {
    const host = basketHost();
    host.querySelectorAll('[data-layer]').forEach(b => { b.onclick = () => { const l = b.dataset.layer; st.layers = st.layers.includes(l) ? st.layers.filter(x => x !== l) : [...st.layers, l]; changed(); }; });
    host.querySelectorAll('[data-drop]').forEach(b => { b.onclick = () => { const k = b.dataset.drop; st[k] = st[k].filter(x => x !== b.dataset.id); changed(); }; });
    const only = host.querySelector('#ch-only'); if (only) only.onchange = () => { st.only = only.checked; changed(); };
  }
  function paintBasket() {
    const host = basketHost();
    host.innerHTML = basketHtml(null, '') + (HUB.served ? '<div class="meta">Counting…</div>' : '<div class="meta">The live hub counts the papers and tokens.</div>');
    wireBasket();
    if (!HUB.served) return;
    getLive(basketQuery()).then(({ ok, j }) => {
      host.innerHTML = basketHtml(ok ? j : null, ok ? '' : HUB.issues(j)); wireBasket();
      st.size = ok ? j.count : null;
    }).catch(() => { host.innerHTML = basketHtml(null, 'The basket could not be counted just now.'); wireBasket(); });
  }

  /* ---------- 2. the form ---------- */
  function parentOptions() {
    const rows = [...(C.sheets || []).map(s => [s.sheet_id, 'Sheet: ' + s['hypothesis']]), ...(C.answers || []).map(a => [a.answer_id, 'Answer: ' + a['question']])];
    return '<option value="">No parent (a new chat)</option>' + rows.map(r => `<option value="${esc(r[0])}" ${st.parent === r[0] ? 'selected' : ''}>${esc(r[1].slice(0, 90))}</option>`).join('');
  }
  function formHtml() {
    const spar = st.kind === 'spar';
    return `<div class="ch-form"><div class="ch-row"><span class="seg" role="group" aria-label="Kind"><button type="button" data-kind="spar" aria-pressed="${spar}">Spar</button><button type="button" data-kind="ask" aria-pressed="${!spar}">Ask</button></span>
      ${H.info(spar ? 'A spar puts a hypothesis against the papers: the case against and the case for, each argument with an exact quote. You rate each one and write the balance yourself.' : 'An ask answers a question from the papers, sentence by sentence, each with an exact quote. You rate each sentence.', 'About the kind')}</div>
      <label class="meta" for="ch-text">${spar ? 'Hypothesis' : 'Question'}</label>
      <textarea id="ch-text" rows="3" maxlength="2000">${esc(st.hyp)}</textarea>
      ${spar ? `<div class="ch-row"><span class="meta">Mode</span><span class="seg" role="group" aria-label="Mode"><button type="button" data-mode="explore" aria-pressed="${st.mode === 'explore'}">Explore</button><button type="button" data-mode="prepare" aria-pressed="${st.mode === 'prepare'}">Prepare</button></span>
        ${H.info('Explore: one session writes both cases. Prepare: separate sessions write the case against and the case for, so the case for is a second order. Only a Prepare sheet may feed a lead.', 'About the mode')}</div>` : ''}
      <label class="meta" for="ch-parent">Follow up on an earlier result</label><select id="ch-parent">${parentOptions()}</select>
      <label class="meta" for="ch-note">Note (optional)</label><input type="text" id="ch-note" maxlength="600">
      <div class="ch-row">${HUB.served ? '<button type="button" class="btn primary" id="ch-go">Order it</button>' : '<button type="button" class="btn" disabled title="Available in the live hub">Order it</button>'}<span class="meta" id="ch-msg" aria-live="polite"></span></div></div>`;
  }
  function order(body, host) {
    say(host, 'Recording…');
    return HUB.post('/ui/act/chat-request', body).then(r => {
      if (!r.ok) { say(host, 'Refused: ' + r.message); return; }
      const j = r.json || {};
      say(host, j.run_id ? 'Ordered; the run has started.' : 'Ordered, but no run started' + (j.run_error ? ' (' + j.run_error + ')' : '') + (j.command ? '. Start it with: ' + j.command : '') + '.');
      refresh();
    });
  }
  function wireForm() {
    main.querySelectorAll('[data-kind]').forEach(b => { b.onclick = () => { st.kind = b.dataset.kind; writeHash(); paintForm(); }; });
    main.querySelectorAll('[data-mode]').forEach(b => { b.onclick = () => { st.mode = b.dataset.mode; writeHash(); paintForm(); }; });
    const text = main.querySelector('#ch-text'), parent = main.querySelector('#ch-parent');
    text.oninput = () => { st.hyp = text.value; };
    text.onchange = writeHash;
    parent.onchange = () => { st.parent = parent.value; writeHash(); };
    const go = main.querySelector('#ch-go'); if (!go) return;
    go.onclick = () => {
      const host = main.querySelector('#ch-msg'), note = main.querySelector('#ch-note').value.trim();
      const body = { kind: st.kind, selection: { ...spec(), only: st.only } };
      body[st.kind === 'spar' ? 'hypothesis' : 'question'] = text.value.trim();
      if (st.kind === 'spar') body.mode = st.mode;
      if (st.parent) body.parent = st.parent;
      if (note) body.note = note;
      HUB.confirm(host, 'Order this ' + (st.kind === 'spar' ? 'spar' : 'ask') + ' over ' + (st.size == null ? 'the basket' : fmt(st.size) + ' papers') + '?', () => { go.disabled = true; return order(body, host).finally(() => { go.disabled = false; }); });
    };
  }
  const paintForm = () => { main.querySelector('#ch-form').innerHTML = formHtml(); wireForm(); };

  /* ---------- 3. progress: requests and their runs ---------- */
  function requestLine(r) {
    const run = r.run ? ` · run ${esc(r.run.status)}` : '';
    const text = r[r.kind === 'spar' ? 'hypothesis' : 'question'];
    const open = r.result ? ` · <a href="#${r.result.startsWith('ans_') ? 'answer' : 'sheet'}=${encodeURIComponent(r.result)}" data-result="${esc(r.result)}">open the result</a>` : '';
    return `<li><span class="ch-state ${esc(r.state)}">${esc(r.state)}</span> <b>${esc(r.kind)}${r.mode ? ' · ' + esc(r.mode) : ''}</b> ${esc((text || '').slice(0, 120))}<span class="meta">${run}${open}${r.state === 'failed' ? ' · the run ended without a complete result; order it again' : ''}</span></li>`;
  }
  function paintProgress() {
    const rs = (C.requests || []).filter(r => r.state !== 'done').slice(0, 8), c = C.counts || {};
    main.querySelector('#ch-progress').innerHTML = `<div class="meta">Waiting <b class="num">${fmt(c.open || 0)}</b> · running <b class="num">${fmt(c.taken || 0)}</b> · done <b class="num">${fmt(c.done || 0)}</b> · failed <b class="num">${fmt(c.failed || 0)}</b></div>` +
      (rs.length ? `<ul class="ch-list">${rs.map(requestLine).join('')}</ul>` : '<div class="ch-empty">No order is waiting or running.</div>');
    wireResults(main.querySelector('#ch-progress'));
  }

  /* ---------- 4. the result: balance first, then each item with its paragraph ---------- */
  const RATINGS = [['sound', 'Sound'], ['weak', 'Weak'], ['wrong', 'Wrong']];
  function rateRow(kind, id, idx, current, note) {
    return `<div class="ch-rate" data-rk="${kind}" data-id="${esc(id)}" data-idx="${idx}"><span class="meta">Your rating</span>${RATINGS.map(r => `<button type="button" class="chip" data-rate="${r[0]}" aria-pressed="${current === r[0]}" ${HUB.served ? '' : 'disabled'}>${r[1]}</button>`).join('')}<input type="text" maxlength="600" value="${esc(note || '')}" placeholder="Note (optional)" aria-label="Note on this rating"><button type="button" class="btn" data-save ${HUB.served ? '' : 'disabled'}>Save</button><span class="meta" data-msg aria-live="polite"></span></div>`;
  }
  function balanceBox(v) {
    const b = v.balance, leans = ['', 'against', 'mixed', 'for', 'undecided'];
    return `<div class="ch-bal"><h3>Your balance ${H.info('Written by you. No agent and no count states it. It needs both cases closed. The latest one you save stands.', 'About the balance')}</h3>
      ${b.recorded ? '' : '<p class="meta">You have not written one yet.</p>'}
      <textarea id="ch-bal-text" maxlength="4000" aria-label="Your balance of the evidence" ${b.writable && HUB.served ? '' : 'disabled'}>${esc(b.text)}</textarea>
      <div class="ch-row"><label class="meta">Lean <select id="ch-bal-lean" ${b.writable && HUB.served ? '' : 'disabled'}>${leans.map(l => `<option value="${l}" ${l === (b.lean || '') ? 'selected' : ''}>${l ? l : 'not stated'}</option>`).join('')}</select></label>
      <input type="text" id="ch-bal-note" maxlength="1000" value="${esc(b.note || '')}" placeholder="Note (optional)" aria-label="Note on the balance" ${b.writable && HUB.served ? '' : 'disabled'}>
      <button type="button" class="btn primary" id="ch-bal-save" ${b.writable && HUB.served ? '' : 'disabled'}>Record my balance</button><span class="meta" id="ch-bal-msg" aria-live="polite"></span></div>
      ${b.writable ? '' : '<p class="meta">Both cases must be closed before you can write it.</p>'}<p class="note">${esc(v.balance_label || '')}</p></div>`;
  }
  function sheetHtml(v) {
    const c = v.counts, entry = (C.sheets || []).find(s => s.sheet_id === v.sheet_id) || {};
    const caseFor = entry.case_for_available ? `<div class="ch-row"><button type="button" class="btn" id="ch-casefor" ${HUB.served ? '' : 'disabled'}>Order the case for</button><span class="meta">The case against is closed. A different session writes the case for.</span><span class="meta" id="ch-cf-msg" aria-live="polite"></span></div>` : '';
    const items = v.arguments.map((a, i) => `<article class="ch-item ${esc(a.stance)}"><div class="meta"><b>${esc(a.stance)}</b> · strength ${esc(a.strength)} (the writer’s judgement)</div><p>${esc(a.claim)}</p>${where(a)}${quoteBlock(a)}${a.linked_claim ? `<div class="meta">Linked claim: ${esc(a.linked_claim.claim_type)} · ${esc(a.linked_claim.about)}<blockquote class="ch-quote">${esc(a.linked_claim.quote)}</blockquote></div>` : ''}${rateRow('argument', a.argument_id, i, a.rating, a.rating_note)}</article>`).join('');
    return `<h3>Sheet: ${esc(v.hypothesis)} <span class="meta">${esc(v.mode)}</span></h3>${balanceBox(v)}${caseFor}
      <div class="meta"><b class="num">${fmt(c.arguments)}</b> arguments (${fmt(c.against)} against, ${fmt(c.for)} for) · rated sound ${fmt(c.ratings.sound || 0)}, weak ${fmt(c.ratings.weak || 0)}, wrong ${fmt(c.ratings.wrong || 0)} · <b class="num">${fmt(c.unrated)}</b> not rated by you</div>
      ${items || '<div class="ch-empty">No argument has been written yet.</div>'}`;
  }
  function answerHtml(v) {
    const c = v.counts;
    const items = v.sentences.map((s, i) => `<article class="ch-item"><p>${esc(s.text)}</p>${where(s)}${quoteBlock(s)}${rateRow('sentence', v.answer_id, s.index, s.rating, s.rating_note)}</article>`).join('');
    return `<h3>Answer: ${esc(v.question)}</h3>
      <div class="ch-bal"><h3>Your rating of the whole answer ${H.info('The answer is a proposal. This rating is yours.', 'About the rating')}</h3>${rateRow('answer', v.answer_id, '', v.rating, v.rating_note)}${v.unanswered ? `<p class="meta">Not answered: ${esc(v.unanswered)}</p>` : ''}<p class="note">${esc(v.rating_label || '')}</p></div>
      <div class="meta"><b class="num">${fmt(c.sentences)}</b> sentences from ${fmt(c.works)} papers · rated sound ${fmt(c.ratings.sound || 0)}, weak ${fmt(c.ratings.weak || 0)}, wrong ${fmt(c.ratings.wrong || 0)} · <b class="num">${fmt(c.unrated)}</b> not rated by you</div>${items}`;
  }
  let VIEW = null;
  function paintResult(v) {
    VIEW = v;
    const host = main.querySelector('#ch-result');
    if (!v) { host.innerHTML = '<div class="ch-empty">Open a sheet or answer from the list below, or order one above.</div>'; return; }
    host.innerHTML = v.kind === 'sheet' ? sheetHtml(v) : answerHtml(v);
    host.querySelectorAll('.ch-rate').forEach(row => wireRate(row, v));
    const bs = host.querySelector('#ch-bal-save');
    if (bs) bs.onclick = () => {
      const msg = host.querySelector('#ch-bal-msg'), lean = host.querySelector('#ch-bal-lean').value, note = host.querySelector('#ch-bal-note').value.trim();
      const body = { sheet_id: v.sheet_id, text: host.querySelector('#ch-bal-text').value };
      if (lean) body.lean = lean;
      if (note) body.note = note;
      HUB.confirm(msg, 'Record this as your balance?', () => HUB.post('/ui/act/chat-balance', body).then(r => { say(msg, r.ok ? 'Recorded.' : 'Refused: ' + r.message); if (r.ok) openResult(); }));
    };
    const cf = host.querySelector('#ch-casefor');
    if (cf) cf.onclick = () => {
      const msg = host.querySelector('#ch-cf-msg');
      HUB.confirm(msg, 'Order the case for this sheet?', () => order({ kind: 'spar', hypothesis: v['hypothesis'], mode: 'prepare', parent: v.sheet_id, selection: v.selection || {} }, msg));
    };
  }
  function wireRate(row, v) {
    let pick = null;
    row.querySelectorAll('[data-rate]').forEach(b => { if (b.getAttribute('aria-pressed') === 'true') pick = b.dataset.rate; b.onclick = () => { pick = b.dataset.rate; row.querySelectorAll('[data-rate]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); }; });
    row.querySelector('[data-save]').onclick = () => {
      const msg = row.querySelector('[data-msg]'), note = row.querySelector('input[type=text]').value;
      if (!pick) { say(msg, 'Pick Sound, Weak or Wrong first.'); return; }
      const kind = row.dataset.rk;
      const route = kind === 'argument' ? '/ui/act/chat-rate-argument' : '/ui/act/chat-rate-sentence';
      const body = kind === 'argument' ? { argument_id: row.dataset.id, rating: pick, note } : { answer_id: row.dataset.id, rating: pick, note };
      if (kind === 'sentence') body.sentence = Number(row.dataset.idx);
      HUB.post(route, body).then(r => { say(msg, r.ok ? 'Saved.' : 'Refused: ' + r.message); if (r.ok) refresh(); });
    };
  }
  function openResult() {
    const q = st.sheet ? 'sheet=' + encodeURIComponent(st.sheet) : st.answer ? 'answer=' + encodeURIComponent(st.answer) : '';
    if (!q) { paintResult(null); return Promise.resolve(); }
    if (!HUB.served) { main.querySelector('#ch-result').innerHTML = '<div class="ch-empty">The live hub shows a result with its paragraphs.</div>'; return Promise.resolve(); }
    return getLive(q).then(({ ok, j }) => { if (ok) paintResult(j); else main.querySelector('#ch-result').textContent = 'Refused: ' + HUB.issues(j); })
      .catch(() => { main.querySelector('#ch-result').textContent = 'The result could not be read just now.'; });
  }
  function wireResults(host) {
    host.querySelectorAll('[data-result]').forEach(a => { a.onclick = e => { e.preventDefault(); const id = a.dataset.result; st.sheet = id.startsWith('sht_') ? id : ''; st.answer = id.startsWith('ans_') ? id : ''; writeHash(); openResult(); }; });
  }

  /* ---------- 5. earlier sheets and answers ---------- */
  function paintEarlier() {
    const sheets = C.sheets || [], answers = C.answers || [];
    const sRow = s => `<li><a href="#sheet=${encodeURIComponent(s.sheet_id)}" data-result="${esc(s.sheet_id)}">${esc(s.hypothesis.slice(0, 110))}</a> <span class="meta">${esc(s.mode)} · ${fmt(s.arguments)} arguments · ${fmt(s.unrated)} not rated · ${s.has_balance ? 'balance written' : 'no balance yet'} · ${esc(s.ts.slice(0, 10))}</span></li>`;
    const aRow = a => `<li><a href="#answer=${encodeURIComponent(a.answer_id)}" data-result="${esc(a.answer_id)}">${esc(a.question.slice(0, 110))}</a> <span class="meta">${fmt(a.sentences)} sentences · ${esc(a.ts.slice(0, 10))}</span></li>`;
    const host = main.querySelector('#ch-earlier');
    host.innerHTML = `<div class="h3">Sheets <span class="meta">${fmt(sheets.length)}</span></div>${sheets.length ? `<ul class="ch-list">${sheets.map(sRow).join('')}</ul>` : '<div class="ch-empty">No sheet yet.</div>'}
      <div class="h3" style="margin-top:14px">Answers <span class="meta">${fmt(answers.length)}</span></div>${answers.length ? `<ul class="ch-list">${answers.map(aRow).join('')}</ul>` : '<div class="ch-empty">No answer yet.</div>'}`;
    wireResults(host);
  }

  /* ---------- the whole page, and the poll while an order is waiting or running ---------- */
  function refresh() {
    if (!HUB.served) { paintProgress(); paintEarlier(); return Promise.resolve(); }
    return getLive('').then(({ ok, j }) => { if (ok) { C = j; paintProgress(); paintEarlier(); const sel = main.querySelector('#ch-parent'); if (sel && document.activeElement !== sel) sel.innerHTML = parentOptions(); } })
      .then(() => { if ((st.sheet || st.answer) && !(document.activeElement && document.activeElement.closest('.ch-rate, .ch-bal') && main.contains(document.activeElement.closest('.ch-rate, .ch-bal')))) return openResult(); })
      .catch(() => {});
  }
  const changed = () => { writeHash(); paintBasket(); };
  function render() {
    main.innerHTML = H.header({ title: 'Chat with papers', sub: 'Put a hypothesis or a question to a basket of papers. An agent proposes; you rate and write the balance.', level: 1, infoHtml: panel('A basket of papers, an order for a spar or an ask, the run’s progress, and the result with every quote beside its full paragraph.', M.proposal) }) +
      `<section class="card ch-card"><h3>1. The basket ${H.info(esc(M.basket || ''), 'About the basket')}</h3><div id="ch-basket"></div></section>
       <section class="card ch-card"><h3>2. Your order</h3><div id="ch-form"></div></section>
       <section class="card ch-card"><h3>3. Progress</h3><div id="ch-progress"></div></section>
       <section class="card ch-card"><h3>4. Result</h3><div id="ch-result"></div></section>
       <section class="card ch-card"><h3>5. Earlier sheets and answers</h3><div id="ch-earlier"></div></section>`;
    paintBasket(); paintForm(); paintProgress(); paintEarlier(); openResult();
  }
  readHash(); render(); if (HUB.served) refresh();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  let timer = setInterval(() => { const c = C.counts || {}; if (HUB.served && (c.open || c.taken)) refresh(); }, 5000);
  window.addEventListener('pagehide', () => clearInterval(timer));
  document.addEventListener('hub:theme', () => paintResult(VIEW));
});
