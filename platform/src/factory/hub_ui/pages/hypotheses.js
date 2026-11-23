/* Hypotheses page. Payload: shell, hypotheses (services/hub_hypotheses.py). Every number comes from the payload.
   Sections: stage strip, how to run it, grounding, queue, leads by state, hypotheses, statistics.
   Acts (live hub only): /ui/act/lead-decide, /ui/act/hypothesis-register, /ui/act/hypothesis-abandon.
   Everything an agent proposed is labelled a proposal and is never evidence (R-87). Hash: state. */
HUB.load(['shell', 'hypotheses']).then(d => {
  const H = HUB.init(d.shell);
  const D = d.hypotheses || {};
  const main = H.mount({ page: 'hypotheses', crumb: 'Hypotheses' });
  const { esc, fmt } = H;
  const M = D.methods || {};
  const ST = D.stages || [], G = D.grounding || { sources: [], skipped: [], miners: [], lineage: {}, total: 0 };
  const Q = D.queue || { items: [], leads_open: [], order_by: [], total_candidates: 0, shown: 0, cap: 0 };
  const L = D.leads || { by_state: {}, totals: {}, cap: 0 };
  const HY = D.hypotheses || { items: [], totals: {}, total: 0, cap: 0 };
  const S = D.stats || {};
  const RQ = D.rq || [];

  if (!document.getElementById('hy-style')) {
    const st = document.createElement('style'); st.id = 'hy-style';
    st.textContent = `
.hy-card{padding:18px 18px 14px;margin-top:var(--gap)}
.hy-strip{list-style:none;margin:18px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.hy-stage{background:var(--surface);border-radius:var(--r);padding:12px 14px;display:flex;flex-direction:column;gap:4px;min-height:132px}
.hy-stage .nm{font:500 var(--t-s) var(--f-ui);color:var(--fg)}
.hy-stage .n{font:500 var(--t-l) var(--f-mono);color:var(--fg)}
.hy-stage .u{font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.hy-stage .mk{font:500 var(--t-xs) var(--f-ui);color:var(--mut)}
.hy-stage.done .mk{color:var(--inc)}
.hy-stage.empty{box-shadow:inset 0 0 0 1px var(--hair)}
.hy-stage .miss{font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.hy-notice{margin:14px 0 0;padding:10px 14px;border-radius:var(--r);background:var(--raised);font:400 var(--t-s) var(--f-ui);color:var(--mut)}
.hy-tag{display:inline-block;font:500 var(--t-xs) var(--f-ui);padding:2px 7px;border-radius:999px;background:var(--raised);color:var(--mut);margin-right:6px;vertical-align:1px}
.hy-tag.prop{box-shadow:inset 0 0 0 1px var(--dim)}
.hy-list{list-style:none;margin:0;padding:0}
.hy-item{padding:14px 0;border-top:1px solid var(--hair)}
.hy-item:first-child{border-top:0}
.hy-item .tt{font:500 var(--t-m)/1.35 var(--f-ui);color:var(--fg);margin:0 0 6px;overflow-wrap:anywhere}
.hy-rank{font:500 var(--t-s) var(--f-mono);color:var(--mut);margin-right:8px}
.hy-why{font:400 var(--t-xs) var(--f-ui);color:var(--mut);margin:6px 0}
.hy-ev{margin:8px 0 0;padding:0 0 0 12px;border-left:2px solid var(--hair);font:400 var(--t-s)/1.45 var(--f-ui)}
.hy-ev q{color:var(--fg)}
.hy-ev .meta{display:block;margin-top:2px}
.hy-flags{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 0}
.hy-act{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
.hy-gates{display:flex;flex-wrap:wrap;gap:6px 12px;margin:8px 0 0;font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.hy-gates .pass{color:var(--inc)}.hy-gates .fail{color:var(--exc)}.hy-gates .pending{color:var(--dim)}
.hy-how ol{margin:8px 0 0 18px;padding:0;font:400 var(--t-m)/1.5 var(--f-ui)}
.hy-how li{margin:6px 0}
.hy-how code{font:400 var(--t-s) var(--f-mono);background:var(--raised);padding:1px 6px;border-radius:4px}
.hy-empty{color:var(--mut);font:400 var(--t-m)/1.5 var(--f-ui);padding:14px 4px}
.hy-sel{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 6px}
.hy-form{display:inline-flex;flex-wrap:wrap;gap:8px;align-items:center}
.hy-form select,.hy-form input{font:400 var(--t-s) var(--f-ui);background:var(--raised);color:var(--fg);border:0;border-radius:var(--r-s);padding:6px 8px}
.hy-kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin:8px 0 0}
.hy-kv div{background:var(--raised);border-radius:var(--r-s);padding:8px 10px}
.hy-kv b{display:block;font:500 var(--t-m) var(--f-mono);color:var(--fg)}
.hy-kv span{font:400 var(--t-xs) var(--f-ui);color:var(--mut)}`;
    document.head.appendChild(st);
  }

  const panel = (what, how) => `<b>What it shows</b> ${esc(what)}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const sect = (title, info, body, extra) => `<section class="card hy-card">${H.header({ title, infoHtml: info })}${extra || ''}${body}</section>`;
  const empty = msg => `<div class="hy-empty">${esc(msg)}</div>`;
  const SRC = { 'technique-challenge': 'Technique challenge', 'technique-combination': 'Technique combination', 'technique-gap': 'Technique gap', 'claims-limitation': 'Limitation in the claims', technique: 'Technique rows', claims: 'Claims rows', 'other-miner': 'Another miner', rows: 'Extracted rows', none: 'No row', mixed: 'Mixed', lead: 'Lead' };
  const srcName = s => SRC[s] || H.pretty(s);
  const workLink = (id, title) => `<a href="corpus.html#id=${encodeURIComponent(id)}">${esc(title || id)}</a>`;
  const share = v => v == null ? 'none' : Math.round(100 * v) + '%';
  const prop = '<span class="hy-tag prop">Proposal</span>';
  const MARK = { pass: '✓ ', fail: '✗ ', pending: '… ', 'n/a': '– ' };
  const served = !!HUB.served;
  const disabledNote = 'Available in the live hub';

  const st = { state: 'open', rq: '' };
  const STATES = ['open', 'promoted', 'parked', 'discarded'];
  const readHash = () => { const h = H.hash.get(), s = h.get('state'), q = h.get('rq'); st.state = STATES.includes(s) ? s : 'open'; st.rq = RQ.some(g => g.id === q) ? q : ''; };
  const inRq = x => !st.rq || (x.serves_rq || 'default') === st.rq;
  const rqTag = x => `<span class="hy-tag" title="The research question it serves">${x.serves_rq ? esc(x.serves_rq) : 'RQ4, RQ5 (default)'}</span>`;
  function rqChips() {
    if (RQ.length < 2) return '';
    return '<div class="hy-sel" role="group" aria-label="Research question"><button type="button" class="chip" data-rq="" aria-pressed="' + (st.rq === '') + '">All</button>' + RQ.map(g => `<button type="button" class="chip" data-rq="${esc(g.id)}" aria-pressed="${st.rq === g.id}">${esc(g.label)} <span class="n">${fmt(g.leads + g.hypotheses)}</span></button>`).join('') + '</div>';
  }

  /* ---------- acts: one inline form per item; the service decides and may refuse ---------- */
  function ask(host, path, base, opts) {
    const { label, fields } = opts;
    const extra = document.createElement('span'); extra.className = 'hy-form';
    const inputs = {};
    (fields || []).forEach(f => {
      let el;
      if (f.options) {
        el = document.createElement('select'); el.setAttribute('aria-label', f.label);
        el.innerHTML = `<option value="">${esc(f.label)}</option>` + f.options.map(o => `<option value="${esc(o)}">${esc(H.pretty(o))}</option>`).join('');
      } else { el = document.createElement('input'); el.type = 'text'; el.maxLength = 300; el.placeholder = f.label; el.setAttribute('aria-label', f.label); }
      inputs[f.key] = el; extra.appendChild(el);
    });
    HUB.confirm(host, label, () => {
      const body = Object.assign({}, base);
      for (const [k, el] of Object.entries(inputs)) if (el.value.trim()) body[k] = el.value.trim();
      return HUB.post(path, body).then(r => {
        host.textContent = r.ok ? 'Recorded. The page shows it after the next rebuild.' : 'Refused: ' + r.message;
      });
    }, extra);
  }
  function leadButtons(lead) {
    if (!served) return `<div class="hy-act"><button type="button" class="btn" disabled title="${disabledNote}">Decide</button><span class="meta">${disabledNote}</span></div>`;
    const btn = (k, l) => `<button type="button" class="btn" data-decide="${k}" data-lead="${esc(lead.lead_id)}">${l}</button>`;
    return `<div class="hy-act">${btn('promote', 'Promote')}${btn('park', 'Park')}${btn('discard', 'Discard')}<span data-host="${esc(lead.lead_id)}" aria-live="polite"></span></div>`;
  }
  function hypButtons(h) {
    if (!served) return '';
    const closed = ['abandoned', 'superseded', 'evaluated'].includes(h.state);
    const reg = ['draft', 'reviewed'].includes(h.state) ? `<button type="button" class="btn" data-register="${esc(h.hypothesis_id)}">Register</button>` : '';
    const ab = closed ? '' : `<button type="button" class="btn" data-abandon="${esc(h.hypothesis_id)}">Abandon</button>`;
    return reg || ab ? `<div class="hy-act">${reg}${ab}<span data-host="${esc(h.hypothesis_id)}" aria-live="polite"></span></div>` : '';
  }

  /* ---------- sections ---------- */
  function strip() {
    const mark = s => s.state === 'done' ? '● Has content' : s.state === 'session' ? '◐ In the session' : '○ Nothing yet';
    return '<ol class="hy-strip" aria-label="Engine stages">' + ST.map(s => {
      const n = s.count == null ? '' : `<span class="n">${fmt(s.count)}</span><span class="u">${esc(s.unit)}</span>`;
      const miss = s.state === 'empty' && s.missing ? `<span class="miss">Missing: ${esc(s.missing)}</span>` : '';
      return `<li class="hy-stage ${esc(s.state)}"><span class="nm">${esc(s.label)} ${H.info(esc(s.made_by), 'What makes ' + s.label)}</span>${n}<span class="mk">${mark(s)}</span>${miss}</li>`;
    }).join('') + '</ol>';
  }

  function howTo() {
    return sect('How to run it', panel('How the engine is started. The platform computes and records; a Claude session supplies the judgement.', ''),
      `<div class="hy-how"><p>Start a Claude Code session in this project and run the skill <code>${esc(D.skill || 'rf-hypothesis-engine')}</code>. Use a session that has not run a screening, extraction or mining pass.</p><ol>` +
      '<li>The skill first asks for its settings: the sources to draw from, how many candidates, the critic and the ordering measure. Say what you want or accept the defaults it states.</li>' +
      '<li>It proposes observations and leads and records them. They appear here as proposals within moments of the next rebuild.</li>' +
      '<li>You decide each lead on this page (promote, park or discard). A hypothesis is drafted only from a promoted lead, then a fresh session reviews it.</li>' +
      '<li>You register or abandon a reviewed hypothesis. The session never does.</li></ol></div>');
  }

  function grounding() {
    const rows = G.sources.length ? '<div class="hy-kv">' + G.sources.map(s => `<div><b>${fmt(s.total)}</b><span>${esc(srcName(s.id))}</span></div>`).join('') + '</div>' : '';
    const lin = G.lineage || {};
    const lineage = `<div class="hy-kv"><div><b>${fmt(lin.relations || 0)}</b><span>Relations between works</span></div><div><b>${fmt(lin.ideas || 0)}</b><span>Ideas in the lineage</span></div></div>`;
    const miners = G.miners.length ? `<p class="meta">Read from ${esc(G.miners.join(', '))}. Exploratory rows, not evidence.</p>` : '';
    const skipped = G.skipped.length ? `<p class="meta">${G.skipped.map(s => esc(s.id + ': ' + s.reason)).join('; ')}</p>` : '';
    const missing = G.missing ? `<div class="hy-empty">Missing: ${esc(G.missing)}. The technique and claims miners produce the rows the engine reads.</div>` : '';
    const absent = G.absence_only_works ? `<p class="meta">${fmt(G.absence_only_works)} works state no limitation and give no observation.</p>` : '';
    return sect('Grounding', panel('What the engine can draw observations from, and what the project holds in lineage.', M.grounding), missing + rows + miners + skipped + absent + '<p class="meta">Lineage</p>' + lineage);
  }

  function evidence(e) {
    const q = (e.quotes || []).map(x => x.quote ? `<div class="hy-ev"><q>${esc(x.quote)}</q><span class="meta">${esc(H.pretty(x.role))}${x.anchor ? ' · ' + esc(x.anchor) : ''} · ${workLink(x.work_id, x.work_id)}</span></div>` : `<div class="hy-ev"><span class="meta">${esc(H.pretty(x.role))}: no stored quote · ${workLink(x.work_id, x.work_id)}</span></div>`).join('');
    const more = e.quotes_total > (e.quotes || []).length ? `<p class="meta">${fmt(e.quotes_total - e.quotes.length)} more quotes behind it.</p>` : '';
    const works = (e.works || []).length ? `<p class="meta">Works: ${e.works.map(w => workLink(w.work_id, w.title)).join(' · ')}${e.works_total > e.works.length ? ` and ${fmt(e.works_total - e.works.length)} more` : ''}</p>` : '';
    return q + more + works;
  }
  function prior(e) {
    if (!e.prior_total) return '';
    return `<p class="meta">Shares rows with: ${e.prior.map(p => esc(p.kind + ' ' + p.id)).join(', ')}${e.prior_total > e.prior.length ? ` and ${fmt(e.prior_total - e.prior.length)} more` : ''}</p>`;
  }
  function entry(e) {
    const flags = (e.flags || []).length ? `<div class="hy-flags">${e.flags.map(f => `<span class="hy-tag">${esc(H.pretty(f))}</span>`).join('')}</div>` : '';
    const rec = e.recorded_as ? `<p class="meta">Already recorded as lead ${esc(e.recorded_as.lead_id)} (${esc(e.recorded_as.state)}).</p>` : '';
    const title = e.kind === 'candidate' ? e.observation : 'Open lead ' + e.entry_id;
    return `<li class="hy-item"><p class="tt"><span class="hy-rank">${fmt(e.rank)}</span>${prop}<span class="hy-tag">${esc(srcName(e.source))}</span> ${esc(title)}</p>` +
      `<div class="hy-why">Why here: ${(e.why || []).map(esc).join(' · ')}</div>` + evidence(e) + prior(e) + rec + flags + '</li>';
  }
  function queue() {
    const rule = `<p class="meta">${esc(Q.order_rule || '')}</p>`;
    if (!Q.items.length) return sect('Lead queue', panel('The observations and open leads, ordered by computed measures.', M.queue), empty('No observation is queued. The engine reads the technique and claims rows of the core layer; see Grounding for what is missing.'));
    const note = `<p class="meta">${fmt(Q.shown)} of ${fmt(Q.total_candidates)} observations shown. An observation becomes a lead only when a session records it. ${esc(Q.comparability || '')}</p>`;
    return sect('Lead queue', panel('Observations from the corpus, each with the evidence behind it, ordered by the printed rule.', M.queue), `<ol class="hy-list">${Q.items.map(entry).join('')}</ol>`, rule + note);
  }

  function leadItem(l) {
    const kinds = Object.entries(l.trigger_kinds || {}).map(([k, v]) => `${fmt(v)} ${esc(k)}`).join(', ');
    const dec = l.decision ? `<p class="meta">Your decision: ${esc(l.decision)}${l.reason ? ' (' + esc(H.pretty(l.reason)) + ')' : ''}${l.note ? ' · ' + esc(l.note) : ''}</p>` : '';
    const ev = l.entry ? `<div class="hy-why">Why here: ${(l.entry.why || []).map(esc).join(' · ')}</div>` : '';
    const works = (l.works || []).length ? `<p class="meta">Works: ${l.works.map(w => workLink(w, w)).join(' · ')}</p>` : '';
    const priorTxt = l.prior_total ? `<p class="meta">Shares rows with ${fmt(l.prior_total)} earlier lead, hypothesis or closed direction.</p>` : '';
    const canDecide = l.state === 'open' || l.state === 'parked';
    return `<li class="hy-item"><p class="tt">${prop}<span class="hy-tag">${esc(l.state)}</span>${rqTag(l)} ${esc(l.text)}</p><p class="meta">Cites ${kinds || 'nothing'}${l.framework ? ' · framework ' + esc(l.framework) : ''}</p>` + ev + works + priorTxt + dec + (canDecide ? leadButtons(l) : '') + '</li>';
  }
  function leads() {
    const chips = '<div class="hy-sel" role="group" aria-label="Lead state">' + STATES.map(s => `<button type="button" class="chip" data-state="${s}" aria-pressed="${st.state === s}">${esc(H.pretty(s))} <span class="n">${fmt((L.totals || {})[s] || 0)}</span></button>`).join('') + '</div>';
    const total = Object.values(L.totals || {}).reduce((a, b) => a + b, 0);
    if (!total) return sect('Leads', panel('Leads by state: proposals you promote, park or discard.', M.leads), empty('No lead is recorded yet. A lead is a short note a session writes from an observation, citing rows that resolve. Run the skill below to produce some.'));
    const list = ((L.by_state || {})[st.state] || []).filter(inRq);
    const shown = list.length, tot = (L.totals || {})[st.state] || 0;
    const body = list.length ? `<ol class="hy-list">${list.map(leadItem).join('')}</ol>` + (tot > shown ? `<p class="meta">${fmt(shown)} of ${fmt(tot)} shown, newest first.</p>` : '') : empty('No lead in this state.');
    return sect('Leads', panel('Leads by state. Every lead is a proposal; only you decide it.', M.leads), body, chips);
  }

  function hypItem(h) {
    const gates = (h.gates || []).map(g => `<span class="${esc(g.status)}" title="${esc(g.detail || '')}">${MARK[g.status] || ''}${esc(g.label)}${g.detail ? ' (' + esc(g.detail) + ')' : ''}</span>`).join('');
    const rv = h.last_review ? `<p class="meta">Latest independent review: ${esc(h.last_review.recommend)}${h.last_review.failed.length ? ' · failed ' + esc(h.last_review.failed.join(', ')) : ''}${h.last_review.critic_model ? ' · model ' + esc(h.last_review.critic_model) : ''}. ${fmt(h.reviews)} counted${h.reviews_ignored ? `, ${fmt(h.reviews_ignored)} not counted` : ''}.</p>` : '';
    const dis = h.abandon_reason ? `<p class="meta">Abandoned: ${esc(H.pretty(h.abandon_reason))}</p>` : '';
    const con = h.conclusion ? `<p class="meta">Your conclusion (interpretation): ${esc(h.conclusion)}</p>` : '';
    const flags = (h.flags || []).length ? `<div class="hy-flags">${h.flags.map(f => `<span class="hy-tag">${esc(H.pretty(f))}</span>`).join('')}</div>` : '';
    return `<li class="hy-item"><p class="tt">${prop}<span class="hy-tag">${esc(h.state)}</span><span class="hy-tag">${esc(h.kind)}</span>${rqTag(h)} ${esc(h.statement)}</p>` +
      `<p class="meta">${esc(h.treatment)} against ${esc(h.baseline)} on ${esc(h.metric)} · version ${esc(h.h_version)}${h.lead ? ' · from lead ' + esc(h.lead) : ''}</p>` +
      `<p class="hy-why">Falsifier: ${esc(h.falsifier)}</p><div class="hy-gates" aria-label="Gates">${gates}</div>` + rv + dis + con + flags + hypButtons(h) + '</li>';
  }
  function hypotheses() {
    if (!HY.total) return sect('Hypotheses', panel('Hypotheses drafted from promoted leads, with their gates and reviews.', M.hypotheses), empty('No hypothesis is drafted yet. A draft starts from a promoted lead; a fresh session then reviews it, and you register or abandon it.'));
    const tot = Object.entries(HY.totals || {}).filter(([, v]) => v).map(([k, v]) => `${fmt(v)} ${esc(k)}`).join(' · ');
    const more = HY.total > HY.items.length ? `<p class="meta">${fmt(HY.items.length)} of ${fmt(HY.total)} shown, newest first.</p>` : '';
    return sect('Hypotheses', panel('Hypotheses with their state, gates and review. A hypothesis is a proposal, not a finding.', M.hypotheses), `<ol class="hy-list">${HY.items.filter(inRq).map(hypItem).join('')}</ol>${more}`, `<p class="meta">${tot}</p>`);
  }

  function stats() {
    if (S.recorded == null) return '';
    const kv = (v, l) => `<div><b>${v}</b><span>${esc(l)}</span></div>`;
    const rate = (a, b) => a == null ? 'none' : Math.round(100 * a) + '%';
    const by = o => Object.entries(o || {}).filter(([, v]) => v).map(([k, v]) => `${esc(H.pretty(k))} ${fmt(v)}`).join(' · ') || 'none';
    const src = Object.entries(S.by_source || {}).map(([k, v]) => `${esc(srcName(k))}: ${by(v)}`).join('; ');
    return sect('Statistics', panel('Counts of recorded leads, hypotheses and reviews.', M.stats),
      `<div class="hy-kv">${kv(fmt(S.recorded), 'Leads recorded')}${kv(fmt(S.decided), 'Leads decided')}${kv(rate(S.decided_promotion_rate), 'Promoted of decided')}${kv(fmt(S.hypotheses_drafted), 'Hypotheses drafted')}${kv(fmt(S.hypotheses_registered), 'Registered')}${kv(fmt(S.reviews), 'Reviews')}</div>` +
      `<p class="meta">Discard reasons: ${by(S.discard_reasons)}. Review recommendations: ${by(S.reviews_by_recommendation)}. Outcomes: ${by(S.outcomes)}.${src ? ' By source: ' + src + '.' : ''}</p>` +
      '<p class="meta">A promotion share describes how the engine is used, not how good its leads are.</p>');
  }

  /* ---------- render ---------- */
  function render() {
    const lead = D.empty ? 'The engine has not run on this project yet.' : `${fmt(G.total)} observations to look at, ${fmt(S.recorded || 0)} leads recorded, ${fmt(HY.total)} hypotheses drafted.`;
    const sub = 'Proposals from the corpus, for you to decide.';
    main.innerHTML = H.header({ title: 'Hypotheses', sub, level: 1, infoHtml: panel('The hypothesis engine: leads, their order, and the hypotheses drafted from them.', M.page) }) +
      `<p class="lead">${esc(lead)}</p>` +
      `<p class="hy-notice">${esc(D.notice || '')} Leads and hypotheses written by an agent are proposals; exploratory outputs are never counted as evidence.</p>` +
      strip() + (D.empty ? howTo() : '') + grounding() + queue() + rqChips() + leads() + hypotheses() + stats() + (D.empty ? '' : howTo());
    wire();
  }
  function wire() {
    const on = (sel, fn) => main.querySelectorAll(sel).forEach(el => { el.onclick = e => { e.preventDefault(); fn(el); }; });
    const host = id => main.querySelector(`[data-host="${CSS.escape(id)}"]`);
    on('[data-rq]', el => { st.rq = el.dataset.rq; H.hash.set({ rq: st.rq || null }); render(); });
    on('[data-state]', el => { st.state = el.dataset.state; H.hash.set({ state: st.state === 'open' ? null : st.state }); render(); });
    on('[data-decide]', el => {
      const kind = el.dataset.decide, id = el.dataset.lead;
      const fields = kind === 'discard' ? [{ key: 'reason', label: 'Reason', options: D.discard_reasons || [] }, { key: 'note', label: 'Note (needed for other)' }] : [{ key: 'note', label: 'Note (optional)' }];
      ask(host(id), '/ui/act/lead-decide', { lead_id: id, decision: kind }, { label: kind === 'promote' ? 'Promote this lead?' : kind === 'park' ? 'Park this lead?' : 'Discard this lead?', fields });
    });
    on('[data-register]', el => ask(host(el.dataset.register), '/ui/act/hypothesis-register', { hypothesis_id: el.dataset.register }, { label: 'Register this hypothesis? Its version is then frozen.', fields: [] }));
    on('[data-abandon]', el => ask(host(el.dataset.abandon), '/ui/act/hypothesis-abandon', { hypothesis_id: el.dataset.abandon }, { label: 'Abandon this hypothesis?', fields: [{ key: 'reason', label: 'Reason', options: D.abandon_reasons || [] }, { key: 'note', label: 'Note (required)' }] }));
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
