/* Chat page (night feature N5). Payload: shell, chat (services/hub_chat.py); served mode also reads `ui/chat?...` live.
   An agent proposes; you rate each argument or sentence and write the balance yourself. Every quote is shown with its
   FULL paragraph. Writes (served only): the four allow-listed acts, each as you (the local human).
   Hash: layers, include, exclude, only (the basket), kind, mode, hyp, parent (the form), sheet or answer (the open result).
   Conversations are derived from the parent links (no event of their own); every exchange is already recorded, the page says so. */
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
.ch-stale{background:var(--raised);border-radius:var(--r);padding:12px 16px;margin:12px 0;border-left:3px solid var(--exc)}
.ch-stale h3,.ch-diff h3{margin:0 0 6px;font:500 var(--t-m) var(--f-ui)}
.ch-diff{background:var(--raised);border-radius:var(--r);padding:12px 16px;margin:12px 0}
.ch-diff ul{margin:6px 0;padding-left:18px}.ch-diff li{margin:6px 0;overflow-wrap:anywhere}
.ch-sugg{margin-top:4px;padding:6px 8px;border-radius:var(--r-s);background:var(--surface);font:400 var(--t-s) var(--f-ui)}
.ch-prec{border-collapse:collapse;font:400 var(--t-s) var(--f-ui);width:100%}.ch-prec th,.ch-prec td{text-align:left;padding:3px 8px;border-bottom:1px solid var(--hair)}
.ch-saved{font:500 var(--t-xs) var(--f-ui);padding:2px 8px;border-radius:var(--r);background:var(--acc-soft);color:var(--acc)}
.ch-follow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.ch-queued{margin:8px 0 0;padding-left:18px;font:400 var(--t-s) var(--f-ui)}.ch-queued li{margin:2px 0;overflow-wrap:anywhere}
.ch-thread{padding:10px 0;border-bottom:1px solid var(--hair);list-style:none}
.ch-thead{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}.ch-thead b{overflow-wrap:anywhere}
.ch-nodes{list-style:none;margin:8px 0 0;padding:0}.ch-nodes li{display:flex;flex-wrap:wrap;gap:6px;align-items:baseline;padding:4px 0;border-left:2px solid var(--hair);overflow-wrap:anywhere}
.ch-wait{color:var(--mut);font-style:italic}
.ch-empty{color:var(--dim);font:400 var(--t-s) var(--f-ui);padding:8px 0}`;
    document.head.appendChild(st);
  }

  /* ---------- state: the address holds the basket, the form and the open result ---------- */
  const st = { layers: [], include: [], exclude: [], only: false, kind: 'spar', mode: 'explore', hyp: '', parent: '', sheet: '', answer: '', same: true, ctx: null, queued: [], openT: {} };
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
  const maxBatch = () => C.batch_max || 10;
  /* one order per non-empty line, or per paragraph when blank lines separate them */
  const itemsOf = t => {
    const raw = (t || '').replace(/\r/g, '').trim();
    if (!raw) return [];
    const paras = raw.split(/\n\s*\n/);
    const parts = paras.length > 1 ? paras.map(p => p.split('\n').map(x => x.trim()).filter(Boolean).join(' ')) : raw.split('\n').map(x => x.trim());
    return parts.filter(Boolean);
  };
  const nodeOf = id => { for (const t of (C.threads || [])) for (const n of t.nodes) if (n.id === id) return n; return null; };
  const shortOf = id => { const n = nodeOf(id); return n ? n.text.slice(0, 70) : id; };
  const countLine = () => {
    const n = itemsOf(st.hyp).length, kind = st.kind === 'spar' ? 'spars' : 'asks';
    if (n > maxBatch()) return `At most ${maxBatch()} at once; you have ${n}.`;
    return n > 1 ? `${n} ${kind} will be queued, one per line or paragraph.` : '';
  };
  const ctxLine = () => {
    if (!st.parent || !st.same) return '';
    if (!HUB.served) return 'The live hub passes the parent’s papers along.';
    if (!st.ctx || st.ctx.id !== st.parent) return 'Reading the parent’s papers…';
    return `Uses the parent’s papers; ${fmt(st.ctx.works.length)} it cites are passed along as already read.`;
  };
  function formHtml() {
    const spar = st.kind === 'spar';
    const followRow = st.parent ? `<div class="ch-follow"><span class="chip" id="ch-follow">Following up on: ${esc(shortOf(st.parent))}</span><button type="button" class="btn" id="ch-unfollow">Clear</button>
        <label class="meta"><input type="checkbox" id="ch-same" ${st.same ? 'checked' : ''}> Same papers as the parent</label>${H.info('A follow-up reads the parent’s papers by default and is told which of them the parent already cited, so the session can skip re-reading them. Untick it to use the basket above instead.', 'About the parent’s papers')}
        <span class="meta" id="ch-ctx" aria-live="polite">${esc(ctxLine())}</span></div>` : '';
    const queued = st.queued.length ? `<div class="meta">Queued ${fmt(st.queued.length)}:</div><ol class="ch-queued">${st.queued.map(q => `<li>${esc(q)}</li>`).join('')}</ol>` : '';
    return `<div class="ch-form"><div class="ch-row"><span class="seg" role="group" aria-label="Kind"><button type="button" data-kind="spar" aria-pressed="${spar}">Spar</button><button type="button" data-kind="ask" aria-pressed="${!spar}">Ask</button></span>
      ${H.info(spar ? 'A spar puts a hypothesis against the papers: the case against and the case for, each argument with an exact quote. You rate each one and write the balance yourself.' : 'An ask answers a question from the papers, sentence by sentence, each with an exact quote. You rate each sentence.', 'About the kind')}</div>
      ${followRow}
      <label class="meta" for="ch-text">${spar ? 'Hypothesis' : 'Question'} ${H.info('Write several at once: each line, or each paragraph when blank lines separate them, becomes its own order, in order, over the same papers and parent. Up to ' + maxBatch() + ' at a time.', 'About several at once')}</label>
      <textarea id="ch-text" rows="3" maxlength="${2000 * maxBatch()}">${esc(st.hyp)}</textarea>
      <div class="meta" id="ch-count" aria-live="polite">${esc(countLine())}</div>
      ${spar ? `<div class="ch-row"><span class="meta">Mode</span><span class="seg" role="group" aria-label="Mode"><button type="button" data-mode="explore" aria-pressed="${st.mode === 'explore'}">Explore</button><button type="button" data-mode="prepare" aria-pressed="${st.mode === 'prepare'}">Prepare</button></span>
        ${H.info('Explore: one session writes both cases. Prepare: separate sessions write the case against and the case for, so the case for is a second order. Only a Prepare sheet may feed a lead.', 'About the mode')}</div>` : ''}
      <label class="meta" for="ch-parent">Follow up on an earlier result</label><select id="ch-parent">${parentOptions()}</select>
      <label class="meta" for="ch-note">Note (optional)</label><input type="text" id="ch-note" maxlength="600">
      <div class="ch-row">${HUB.served ? '<button type="button" class="btn primary" id="ch-go">Order it</button>' : '<button type="button" class="btn" disabled title="Available in the live hub">Order it</button>'}<span class="meta" id="ch-msg" aria-live="polite"></span></div>${queued}</div>`;
  }
  function order(body, host, route) {
    say(host, 'Recording…');
    return HUB.post(route || '/ui/act/chat-request', body).then(r => {
      if (!r.ok) { say(host, 'Refused: ' + r.message); return false; }
      const j = r.json || {}, many = Array.isArray(j.request_ids) ? j.request_ids.length : 0;
      const run = j.run_id ? (many > 1 ? 'one run has started; the others wait for the next run.' : 'the run has started.') : 'no run started' + (j.run_error ? ' (' + j.run_error + ')' : '') + (j.command ? '. Start it with: ' + j.command : '') + '.';
      say(host, (many > 1 ? 'Ordered ' + many + '; ' : 'Ordered; ') + run + ' Saved.');
      refresh();
      return true;
    });
  }
  /* the parent's selection and cited works, read when a follow-up is set */
  function loadCtx() {
    st.ctx = null;
    if (!st.parent || !HUB.served) return Promise.resolve(null);
    const id = st.parent;
    return getLive('context=' + encodeURIComponent(id)).then(({ ok, j }) => { if (ok && id === st.parent) st.ctx = j; return st.ctx; }).catch(() => null)
      .then(c => { const el = main.querySelector('#ch-ctx'); if (el) say(el, ctxLine()); return c; });
  }
  function focusForm() {
    const t = main.querySelector('#ch-text'); if (!t) return;
    if (t.scrollIntoView) t.scrollIntoView({ block: 'center' });
    t.focus();
  }
  /* pre-fill only: the researcher presses Order it */
  function prefill(p) {
    if (p.kind) st.kind = p.kind;
    if (p.mode) st.mode = p.mode;
    if (p.text != null) st.hyp = String(p.text).slice(0, 2000);
    st.parent = p.parent || ''; st.same = true; st.queued = [];
    writeHash(); paintForm(); loadCtx(); focusForm();
  }
  const follow = id => prefill({ parent: id, text: st.hyp });
  function wireFollow(host) {
    host.querySelectorAll('[data-follow]').forEach(b => { b.onclick = () => follow(b.dataset.follow); });
  }
  /* the note carries the parent's cited works as plain text, within the 600-character limit */
  function noteWith(user) {
    const c = st.ctx;
    if (!(st.parent && st.same && c && c.id === st.parent && c.works.length)) return user;
    const pre = 'Already read in the parent: ', ids = c.works;
    const build = k => pre + ids.slice(0, k).join(', ') + (k < ids.length ? ' and ' + (ids.length - k) + ' more' : '') + '.' + (user ? ' ' + user : '');
    let k = ids.length;
    while (k > 0 && build(k).length > 600) k--;
    return k > 0 ? build(k) : user;
  }
  function wireForm() {
    main.querySelectorAll('[data-kind]').forEach(b => { b.onclick = () => { st.kind = b.dataset.kind; writeHash(); paintForm(); }; });
    main.querySelectorAll('[data-mode]').forEach(b => { b.onclick = () => { st.mode = b.dataset.mode; writeHash(); paintForm(); }; });
    const text = main.querySelector('#ch-text'), parent = main.querySelector('#ch-parent');
    text.oninput = () => { st.hyp = text.value; say(main.querySelector('#ch-count'), countLine()); };
    text.onchange = writeHash;
    parent.onchange = () => { st.parent = parent.value; st.same = true; writeHash(); paintForm(); loadCtx(); };
    const un = main.querySelector('#ch-unfollow'); if (un) un.onclick = () => { st.parent = ''; st.ctx = null; writeHash(); paintForm(); };
    const same = main.querySelector('#ch-same'); if (same) same.onchange = () => { st.same = same.checked; say(main.querySelector('#ch-ctx'), ctxLine()); };
    const go = main.querySelector('#ch-go'); if (!go) return;
    go.onclick = () => {
      const host = main.querySelector('#ch-msg'), user = main.querySelector('#ch-note').value.trim(), items = itemsOf(text.value);
      if (!items.length) { say(host, 'Write the ' + (st.kind === 'spar' ? 'hypothesis' : 'question') + ' first.'); return; }
      if (items.length > maxBatch()) { say(host, countLine()); return; }
      const inherit = !!(st.parent && st.same);
      const ready = inherit && !(st.ctx && st.ctx.id === st.parent) ? loadCtx() : Promise.resolve(st.ctx);
      ready.then(ctx => {
        if (inherit && !ctx) { say(host, 'The parent’s papers could not be read; untick “Same papers as the parent” to use the basket.'); return; }
        const body = { kind: st.kind, selection: inherit ? { ...ctx.selection } : { ...spec(), only: st.only } };
        if (items.length > 1) body.lines = items; else body[st.kind === 'spar' ? 'hypothesis' : 'question'] = items[0];
        if (st.kind === 'spar') body.mode = st.mode;
        if (st.parent) body.parent = st.parent;
        const note = noteWith(user); if (note) body.note = note;
        const what = items.length > 1 ? items.length + ' ' + (st.kind === 'spar' ? 'spars' : 'asks') : 'this ' + (st.kind === 'spar' ? 'spar' : 'ask');
        const over = inherit ? 'the parent’s papers' : st.size == null ? 'the basket' : fmt(st.size) + ' papers';
        HUB.confirm(host, 'Order ' + what + ' over ' + over + '?', () => { go.disabled = true; return order(body, host, items.length > 1 ? '/ui/act/chat-batch' : null).then(ok => { if (ok) { const m = host.textContent; st.queued = items; st.hyp = ''; writeHash(); paintForm(); say(main.querySelector('#ch-msg'), m); } }).finally(() => { go.disabled = false; }); });
      });
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
  /* ---------- living sheet: what changed since it opened, and what a re-spar changed ---------- */
  function stalePanel(v) {
    const s = v.staleness || {};
    if (s.stale === null) return `<div class="ch-stale"><h3>Changed since</h3><p class="meta">${esc((s.reasons || []).join('; ') || 'The selection cannot be checked.')}</p></div>`;
    if (!s.stale) return '';
    const names = list => (list || []).slice(0, 12).map(w => esc(w.title || w.work_id)).join('; ') + ((list || []).length > 12 ? ` and ${fmt(list.length - 12)} more` : '');
    return `<div class="ch-stale"><h3>Changed since this sheet opened ${H.info('Computed now from today’s papers and claims. The sheet itself is unchanged: this is a prompt to spar again, not a verdict.', 'About staleness')}</h3>
      <ul>${(s.reasons || []).map(r => `<li>${esc(r)}</li>`).join('')}</ul>
      ${(s.works_added || []).length ? `<div class="meta">Papers added: ${names(s.works_added)}</div>` : ''}
      ${(s.works_removed || []).length ? `<div class="meta">Papers removed: ${names(s.works_removed)}</div>` : ''}
      ${(s.rows_changed || []).length ? `<div class="meta">Claims rows changed for: ${names(s.rows_changed)}</div>` : ''}
      ${s.claims_checked ? '' : '<div class="meta">This sheet predates claims tracking; only the selection was checked.</div>'}</div>`;
  }
  function diffHtml(d) {
    if (!d) return '';
    const item = x => `<li><b>${esc(x.stance)}</b> ${esc(x.title || x.work_id)} <span class="meta mono">${esc(x.anchor)}</span><div>${esc(x.claim)}</div><blockquote class="ch-quote">${esc(x.quote)}</blockquote></li>`;
    const keptItem = k => {
      let sugg = '';
      if (k.rating) sugg = `<div class="ch-sugg">You already rated this one: ${esc(k.rating)}.</div>`;
      else if (k.changed) sugg = `<div class="ch-sugg">Changed at the same place: the quote is not the earlier one, so no rating is suggested.${k.old_rating ? ' Earlier rating, for context only: ' + esc(k.old_rating) + (k.old_note ? ' · ' + esc(k.old_note) : '') + '.' : ''}</div>`;
      else if (k.suggested_rating) sugg = `<div class="ch-sugg">Rating suggested from the earlier sheet (same quote): <b>${esc(k.suggested_rating)}</b>${k.suggested_note ? ' · ' + esc(k.suggested_note) : ''}. It is not your rating until you accept it. <button type="button" class="btn" data-accept="${esc(k.new_argument_id)}" data-rating="${esc(k.suggested_rating)}" data-note="${esc(k.suggested_note || '')}" ${HUB.served ? '' : 'disabled'}>Accept this rating</button><span class="meta" data-amsg aria-live="polite"></span></div>`;
      else sugg = '<div class="ch-sugg">The earlier sheet had no rating for this argument.</div>';
      const before = `<div class="ch-before meta">Earlier sheet: ${esc(k.old_claim)}<blockquote class="ch-quote">${esc(k.old_quote)}</blockquote></div>`;
      return `<li><b>${esc(k.stance)}</b> ${esc(k.title || k.work_id)} <span class="meta mono">${esc(k.anchor)}</span><div>${esc(k.claim)}</div><blockquote class="ch-quote">${esc(k.quote)}</blockquote>${before}${sugg}</li>`;
    };
    const c = d.counts || {};
    return `<div class="ch-diff"><h3>Compared with the earlier sheet ${H.info('Arguments are matched by paper, anchor and stance; a rating is suggested only when the quote is the same. A rating you gave the earlier argument is only suggested here; nothing is rated until you accept it.', 'About the comparison')}</h3>
      <div class="meta"><b class="num">${fmt(c.added || 0)}</b> added · <b class="num">${fmt(c.dropped || 0)}</b> dropped · <b class="num">${fmt(c.kept || 0)}</b> kept · earlier sheet <a href="#sheet=${encodeURIComponent(d.old)}" data-result="${esc(d.old)}">${esc(d.old)}</a></div>
      <p class="note">${esc(d.label || '')}</p>
      <div class="h3">Added</div><ul>${(d.added || []).map(item).join('') || '<li class="meta">None.</li>'}</ul>
      <div class="h3">Dropped</div><ul>${(d.dropped || []).map(item).join('') || '<li class="meta">None.</li>'}</ul>
      <div class="h3">Kept</div><ul>${(d.kept || []).map(keptItem).join('') || '<li class="meta">None.</li>'}</ul></div>`;
  }
  function sheetHtml(v) {
    const c = v.counts, entry = (C.sheets || []).find(s => s.sheet_id === v.sheet_id) || {};
    const caseFor = entry.case_for_available ? `<div class="ch-row"><button type="button" class="btn" id="ch-casefor" ${HUB.served ? '' : 'disabled'}>Order the case for</button><span class="meta">The case against is closed. A different session writes the case for.</span><span class="meta" id="ch-cf-msg" aria-live="polite"></span></div>` : '';
    const items = v.arguments.map((a, i) => `<article class="ch-item ${esc(a.stance)}"><div class="meta"><b>${esc(a.stance)}</b> · strength ${esc(a.strength)} (the writer’s judgement)</div><p>${esc(a.claim)}</p><div class="ch-row"><button type="button" class="btn" data-ask-i="${i}">Ask about this</button></div>${where(a)}${quoteBlock(a)}${a.linked_claim ? `<div class="meta">Linked claim: ${a.linked_claim.missing ? '' : `${esc(a.linked_claim.claim_type)} · ${esc(a.linked_claim.about)}`}${a.linked_claim.note ? ` <em class="ch-claim-note">(${esc(a.linked_claim.note)})</em>` : ''}${a.linked_claim.missing ? '' : `<blockquote class="ch-quote">${esc(a.linked_claim.quote)}</blockquote>`}</div>` : ''}${rateRow('argument', a.argument_id, i, a.rating, a.rating_note)}</article>`).join('');
    const respar = v.can_respar ? `<div class="ch-row"><button type="button" class="btn" id="ch-respar" ${HUB.served ? '' : 'disabled'}>Re-spar with today’s papers</button><span class="meta">Spars the same hypothesis again over the papers as they are now; the new sheet is compared with this one.</span><span class="meta" id="ch-rs-msg" aria-live="polite"></span></div>` : '';
    return `<h3>Sheet: ${esc(v.hypothesis)} <span class="meta">${esc(v.mode)}</span></h3>${savedRow(v.sheet_id)}${stalePanel(v)}${balanceBox(v)}${caseFor}${respar}${diffHtml(v.diff)}
      <div class="meta"><b class="num">${fmt(c.arguments)}</b> arguments (${fmt(c.against)} against, ${fmt(c.for)} for) · rated sound ${fmt(c.ratings.sound || 0)}, weak ${fmt(c.ratings.weak || 0)}, wrong ${fmt(c.ratings.wrong || 0)} · <b class="num">${fmt(c.unrated)}</b> not rated by you</div>
      ${items || '<div class="ch-empty">No argument has been written yet.</div>'}`;
  }
  /* every exchange is already recorded as events: say so, and offer the next step */
  const savedRow = id => `<div class="ch-row"><span class="ch-saved">Saved</span>${H.info('Every answer and sheet is recorded as it is written and kept. Find it again under Conversations.', 'About saving')}<button type="button" class="btn" data-follow="${esc(id)}">Follow up</button>${id.startsWith('ans_') ? '<button type="button" class="btn" data-spar-i="-1">Spar this claim</button>' : ''}</div>`;
  function answerHtml(v) {
    const c = v.counts;
    const items = v.sentences.map((s, i) => `<article class="ch-item"><p>${esc(s.text)}</p><div class="ch-row"><button type="button" class="btn" data-spar-i="${i}">Spar this claim</button></div>${where(s)}${quoteBlock(s)}${rateRow('sentence', v.answer_id, s.index, s.rating, s.rating_note)}</article>`).join('');
    return `<h3>Answer: ${esc(v.question)}</h3>${savedRow(v.answer_id)}
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
    wireFollow(host);
    host.querySelectorAll('[data-spar-i]').forEach(b => { b.onclick = () => { const i = Number(b.dataset.sparI); prefill({ kind: 'spar', mode: 'explore', text: i < 0 ? v['question'] : v.sentences[i]['text'], parent: v.answer_id }); }; });
    host.querySelectorAll('[data-ask-i]').forEach(b => { b.onclick = () => prefill({ kind: 'ask', text: v.arguments[Number(b.dataset.askI)].claim, parent: v.sheet_id }); });
    const bs = host.querySelector('#ch-bal-save');
    if (bs) bs.onclick = () => {
      const msg = host.querySelector('#ch-bal-msg'), lean = host.querySelector('#ch-bal-lean').value, note = host.querySelector('#ch-bal-note').value.trim();
      const body = { sheet_id: v.sheet_id, text: host.querySelector('#ch-bal-text').value };
      if (lean) body.lean = lean;
      if (note) body.note = note;
      HUB.confirm(msg, 'Record this as your balance?', () => HUB.post('/ui/act/chat-balance', body).then(r => { say(msg, r.ok ? 'Recorded.' : 'Refused: ' + r.message); if (r.ok) openResult(); }));
    };
    const rs = host.querySelector('#ch-respar');
    if (rs) rs.onclick = () => {
      const msg = host.querySelector('#ch-rs-msg');
      HUB.confirm(msg, 'Spar this hypothesis again over today’s papers?', () => order({ respar: v.sheet_id }, msg));
    };
    host.querySelectorAll('[data-accept]').forEach(b => {
      b.onclick = () => {
        const msg = b.parentNode.querySelector('[data-amsg]');
        HUB.confirm(msg, 'Record this as your rating?', () => HUB.post('/ui/act/chat-rate-argument', { argument_id: b.dataset.accept, rating: b.dataset.rating, note: b.dataset.note || '' }).then(r => { say(msg, r.ok ? 'Saved as your rating.' : 'Refused: ' + r.message); if (r.ok) refresh(); }));
      };
    });
    wireResults(host);
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

  /* ---------- 5. conversations: the parent links, nested; every exchange is already saved ---------- */
  const STATE = { open: 'waiting', taken: 'running', answered: 'answered', done: 'answered', failed: 'failed' };
  const stateClass = x => (x === 'answered' ? 'done' : x);
  function nodeLine(n) {
    const label = n.type === 'answer' ? 'Answer' : n.type === 'sheet' ? 'Spar · ' + (n.mode || 'explore') : (n.kind === 'spar' ? 'Spar' : 'Ask');
    const shown = esc(n.text.slice(0, 110));
    const link = n.type === 'request' ? shown : `<a href="#${n.type === 'answer' ? 'answer' : 'sheet'}=${encodeURIComponent(n.id)}" data-result="${esc(n.id)}">${shown}</a>`;
    const status = n.type === 'request'
      ? (n.state === 'failed' ? 'the run ended without a complete result' : n.state === 'taken' ? 'a session is working on it' : 'waiting for a session')
      : (n.state === 'taken' ? 'a session is working on it' : n.state === 'failed' ? 'the run ended without a complete result' : '');
    const saved = n.type !== 'request' && n.state === 'done' ? '<span class="ch-saved">Saved</span>' : `<span class="ch-wait">${esc(status)}</span>`;
    const fu = n.type === 'request' ? '' : `<button type="button" class="btn" data-follow="${esc(n.id)}">Follow up</button>`;
    return `<li style="margin-left:${Math.min(n.depth, 6) * 18}px;padding-left:8px"><span class="meta">${esc(label)}</span> ${link} ${saved} ${fu}</li>`;
  }
  function threadHtml(t) {
    const open = t.root in st.openT ? st.openT[t.root] : t.state !== 'answered';
    const rootNode = t.nodes[0], canFollow = rootNode && rootNode.type !== 'request';
    const head = `<div class="ch-thead"><b>${esc(t.text.slice(0, 110))}</b> <span class="ch-state ${esc(stateClass(t.state))}">${esc(STATE[t.state] || t.state)}</span>
      <span class="meta">${fmt(t.count)} ${t.count === 1 ? 'exchange' : 'exchanges'} · latest ${esc(t.latest.slice(0, 10))} · Saved</span>
      <button type="button" class="btn" data-tog="${esc(t.root)}" aria-expanded="${open}">${open ? 'Hide thread' : 'Show thread'}</button>${canFollow ? `<button type="button" class="btn" data-follow="${esc(t.root)}">Follow up</button>` : ''}</div>`;
    return `<li class="ch-thread">${head}${open ? `<ul class="ch-nodes">${t.nodes.map(nodeLine).join('')}</ul>` : ''}</li>`;
  }
  function paintThreads() {
    const ts = C.threads || [], host = main.querySelector('#ch-earlier');
    host.innerHTML = ts.length ? `<div class="meta"><b class="num">${fmt(ts.length)}</b> conversations</div><ul class="ch-list" style="padding:0">${ts.slice(0, 50).map(threadHtml).join('')}</ul>${ts.length > 50 ? `<div class="meta">The latest 50 of ${fmt(ts.length)} are listed.</div>` : ''}` : '<div class="ch-empty">No conversation yet.</div>';
    host.querySelectorAll('[data-tog]').forEach(b => { b.onclick = () => { const t = ts.find(x => x.root === b.dataset.tog); const was = t.root in st.openT ? st.openT[t.root] : t.state !== 'answered'; st.openT[t.root] = !was; paintThreads(); }; });
    wireFollow(host);
    wireResults(host);
  }

  /* ---------- 6. precision: your ratings summarised; every figure is computed, never typed ---------- */
  function paintPrecision() {
    const P = C.precision || {}, A = P.arguments || {}, ms = P.measures || {};
    const tbl = (title, rows, tip) => `<div class="h3" style="margin-top:12px">${esc(title)} ${tip ? H.info(esc(tip), 'About ' + title) : ''}</div>` + (rows && rows.length
      ? `<table class="ch-prec"><thead><tr><th>Group</th><th>Sound share</th><th>Sound</th><th>Weak</th><th>Wrong</th><th>Not rated</th></tr></thead><tbody>${rows.map(x => `<tr><td>${esc(x.key)}</td><td class="num">${esc(x.precision_text)}</td><td class="num">${fmt(x.sound)}</td><td class="num">${fmt(x.weak)}</td><td class="num">${fmt(x.wrong)}</td><td class="num">${fmt(x.unrated)}</td></tr>`).join('')}</tbody></table>`
      : '<div class="ch-empty">Nothing yet.</div>');
    const g = P.agreement || { table: {}, n: 0 };
    const rows = Object.keys(g.table || {}).sort().map(v => `<tr><td>${esc(v)}</td>${['sound', 'weak', 'wrong'].map(k => `<td class="num">${fmt((g.table[v] || {})[k] || 0)}</td>`).join('')}</tr>`).join('');
    const agree = `<div class="h3" style="margin-top:12px">Critic against you ${H.info(esc(ms.agreement || ''), 'About critic agreement')}</div>` +
      (g.n ? `<table class="ch-prec"><thead><tr><th>Critic said</th><th>You: sound</th><th>weak</th><th>wrong</th></tr></thead><tbody>${rows}</tbody></table>` : '') +
      `<div class="meta">${fmt(g.n)} compared · agreement ${g.raw === null || g.raw === undefined ? '—' : esc(String(g.raw)) + '%'} · kappa ${g.kappa === null || g.kappa === undefined ? '—' : esc(String(g.kappa))}</div>`;
    main.querySelector('#ch-precision').innerHTML =
      tbl('All arguments', A.all, (ms.precision || '') + ' ' + (ms.since || '')) + tbl('By stance', A.stance) + tbl('By source', A.source, ms.source) +
      tbl('By strength', A.strength) + tbl('By model', A.model) + tbl('By engine', A.engine) + tbl('By role', A.role, ms.role) +
      agree + tbl('Answer sentences by model', (P.answers || {}).model, ms.answers);
  }

  /* ---------- the whole page, and the poll while an order is waiting or running ---------- */
  function refresh() {
    if (!HUB.served) { paintProgress(); paintThreads(); return Promise.resolve(); }
    return getLive('').then(({ ok, j }) => { if (ok) { C = j; paintProgress(); paintThreads(); paintPrecision(); const sel = main.querySelector('#ch-parent'); if (sel && document.activeElement !== sel) sel.innerHTML = parentOptions(); } })
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
       <section class="card ch-card"><h3>5. Conversations ${H.info('A conversation is a question or hypothesis with its follow-ups beneath it, built from the follow-up links. Every answer and sheet is recorded when it is written; nothing here needs saving.', 'About conversations')}</h3><div id="ch-earlier"></div></section>
       <section class="card ch-card"><h3>6. Precision ${H.info(esc((M.precision || 'Your ratings summarised; every figure is computed from them.')), 'About precision')}</h3><div id="ch-precision"></div></section>`;
    paintBasket(); paintForm(); paintProgress(); paintThreads(); paintPrecision(); openResult(); loadCtx();
  }
  readHash(); render(); if (HUB.served) refresh();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  let timer = setInterval(() => { const c = C.counts || {}; if (HUB.served && (c.open || c.taken)) refresh(); }, 5000);
  window.addEventListener('pagehide', () => clearInterval(timer));
  document.addEventListener('hub:theme', () => paintResult(VIEW));
});
