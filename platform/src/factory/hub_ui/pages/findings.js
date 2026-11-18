/* Findings page: eight finding cards, the research cycle, openness, claims by validation.
   Payloads: shell, findings (services/hub_findings.py). Every number and sentence is read from the payload. */
HUB.load(['shell', 'findings']).then(d => {
  const H = HUB.init(d.shell);
  const { esc, fmt, pretty, term, info, header, byId, layerLabel, layerColor, openDrawer } = H;
  const F = d.findings, cards = F.cards || [], cyc = F.cycle || {}, opn = F.openness || {}, clm = F.claims || {};
  const main = H.mount({ page: 'findings', crumb: 'Findings' });

  /* ---------- page styles (kit tokens only) ---------- */
  const st = document.createElement('style');
  st.textContent = `
.fp{padding-top:16px}
.fp .lead{max-width:36ch;margin:10px 0 6px}
.fp section{margin-top:52px}
.fgrid{columns:4;column-gap:16px;margin-top:22px}
.fc{background:var(--surface);border-radius:var(--r);padding:20px;display:flex;flex-direction:column;gap:10px;min-width:0;break-inside:avoid;margin:0 0 16px}
.fc .top{display:flex;justify-content:space-between;align-items:flex-start;gap:6px}
.fc .big{font:300 64px/0.95 var(--f-display);letter-spacing:-.02em;font-variant-numeric:tabular-nums;color:var(--fg)}
.fc .big small{font-size:.45em;color:var(--mut);font-weight:400;margin-left:2px}
.fc .say{font:400 var(--t-l)/1.28 var(--f-display);margin:0}
.fc .nn{font-size:var(--t-xs);color:var(--dim);line-height:1.4}
.fc .pop-line{font-size:var(--t-xs);color:var(--dim);line-height:1.4}
.fc .acts{display:flex;gap:8px;padding-top:6px;flex-wrap:wrap}
.fc .acts .btn{height:30px;padding:0 11px}
.fc[data-cur]{box-shadow:inset 0 0 0 2px var(--acc)}
.fc.na .big{color:var(--dim)}
.fc.na .say{color:var(--mut);font-size:var(--t-m)}
.waf{display:grid;grid-template-columns:repeat(10,1fr);gap:2px;width:100%;max-width:150px}
.waf i{aspect-ratio:1;border-radius:2px;background:var(--line)}
.waf i.h{background:var(--seq-4)}
.cap{font-size:var(--t-xs);color:var(--mut);margin-top:7px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.sw{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:-1px;background:var(--line)}
.sw.h{background:var(--seq-4)}
.stk{display:flex;height:26px;gap:2px;border-radius:4px;overflow:hidden}
.stk i{display:block;min-width:2px;background:var(--line)}
.stk i.h{background:var(--seq-4)}
.mb{display:grid;gap:5px}
.mb button{all:unset;cursor:pointer;display:grid;grid-template-columns:minmax(0,84px) 1fr 28px;gap:6px;align-items:center;font-size:11px;color:var(--mut);padding:1px 2px;border-radius:3px}
.mb button:hover{background:var(--raised)}
.mb button:focus-visible{outline:2px solid var(--acc)}
.mb .tr{height:9px;background:var(--raised);border-radius:3px;position:relative}
.mb .tr b{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--seq-2)}
.mb .hi .tr b{background:var(--seq-4)}
.mb .hi{color:var(--fg)}
.mb span.v{font-family:var(--f-mono);text-align:right}
.mb span.l{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cyc{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px;margin-top:6px;align-items:start}
.stg{all:unset;box-sizing:border-box;cursor:pointer;background:var(--surface);border-radius:var(--r);padding:0 14px 16px;display:flex;flex-direction:column;gap:7px;min-width:0}
.stg:hover{background:var(--raised)}
.stg:focus-visible{outline:2px solid var(--acc)}
.stg[aria-pressed=true]{box-shadow:inset 0 0 0 2px var(--acc)}
.stg .band{height:18px;margin:0 -14px 8px;clip-path:polygon(0 0,calc(100% - 12px) 0,100% 50%,calc(100% - 12px) 100%,0 100%,10px 50%)}
.stg:first-child .band{clip-path:polygon(0 0,calc(100% - 12px) 0,100% 50%,calc(100% - 12px) 100%,0 100%)}
.stg .k{font-size:var(--t-xs);color:var(--dim)}
.stg .nm{font:600 var(--t-m)/1.25 var(--f-ui);min-height:2.5em}
.stg .pc{font:300 40px/1 var(--f-display);font-variant-numeric:tabular-nums}
.stg .pc small{font-size:.4em;color:var(--mut)}
.stg .ds{font-size:var(--t-xs);color:var(--mut);line-height:1.4}
.stg .tt{margin:6px 0 0;padding:8px 0 0;border-top:1px solid var(--hair);list-style:none;display:grid;gap:5px}
.stg .tt li{display:grid;grid-template-columns:1fr auto;gap:6px;font-size:11.5px;line-height:1.3;color:var(--mut)}
.legend{display:flex;align-items:center;gap:10px;font-size:var(--t-xs);color:var(--mut);margin:14px 0 0;flex-wrap:wrap}
.legend .ramp{width:140px;height:9px;border-radius:3px;background:linear-gradient(90deg,var(--seq-1),var(--seq-4))}
.sp{margin-top:18px;background:var(--surface);border-radius:var(--r);padding:22px}
.sp .hd{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.sp .cols{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:32px;margin-top:14px}
.dp{display:grid;gap:0;max-height:640px;overflow:auto;padding-right:6px}
.dr{all:unset;cursor:pointer;display:grid;grid-template-columns:minmax(0,290px) 1fr 30px;gap:10px;align-items:center;padding:3px 6px;border-radius:4px;font-size:var(--t-xs);color:var(--mut)}
.dr:hover{background:var(--raised)}.dr:focus-visible{outline:2px solid var(--acc)}
.dr[aria-pressed=true]{background:var(--acc-soft);color:var(--fg)}
.dr .l{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dr .tr{height:14px;position:relative;background:linear-gradient(90deg,transparent calc(100% - 1px),var(--hair) 0) 0 0/25% 100%}
.dr .tr::before{content:"";position:absolute;left:0;right:calc(100% - var(--p));top:50%;height:1.5px;background:var(--seq-2)}
.dr .tr i{position:absolute;left:var(--p);top:50%;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:var(--seq-4)}
.dr.z .tr i{background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}
.dr .v{font-family:var(--f-mono);text-align:right;color:var(--fg)}
.dax{display:grid;grid-template-columns:minmax(0,290px) 1fr 30px;gap:10px;padding:0 6px 6px;font-size:11px;color:var(--dim)}
.dax .ax{display:flex;justify-content:space-between}
.tdet h3{margin:0 0 2px}
.tdet .pp{margin:10px 0 0;padding:0;list-style:none;display:grid;gap:12px}
.tdet .pp a{font-weight:500}
.tdet .quote{font-size:14px;margin:3px 0 0}
.fp .empty{color:var(--dim);font-size:var(--t-s);padding:26px 0}
.op{margin-top:8px;display:grid;grid-template-columns:minmax(0,120px) minmax(0,1fr) minmax(0,1fr);gap:10px 18px;align-items:center;background:var(--surface);border-radius:var(--r);padding:22px}
.op .ch{font-size:var(--t-s);font-weight:600;color:var(--mut)}
.op .rl{font-size:var(--t-s)}.op .rl small{display:block;color:var(--dim);font-size:var(--t-xs)}
.sbar{display:flex;height:28px;gap:2px;border-radius:4px;overflow:hidden}
.sbar button{all:unset;cursor:pointer;display:flex;align-items:center;justify-content:center;font:500 11px var(--f-mono);min-width:2px;color:var(--bg)}
.sbar button:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
.sbar button:hover{filter:brightness(1.15)}
.leg{display:flex;gap:16px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--mut);margin:12px 0 0;grid-column:1/-1}
.leg span{display:inline-flex;align-items:center;gap:6px}
.leg i{width:10px;height:10px;border-radius:2px;display:inline-block}
.mx{margin-top:8px;background:var(--surface);border-radius:var(--r);padding:22px;overflow-x:auto}
.mx table{border-collapse:separate;border-spacing:3px;min-width:640px;width:100%}
.mx th{font:500 var(--t-xs) var(--f-ui);color:var(--mut);text-align:left;padding:4px 6px;vertical-align:bottom}
.mx th.c{text-align:center}
.mx td{padding:0}
.mx td.rt,.mx th.rt{text-align:right;font-family:var(--f-mono);color:var(--mut);font-size:var(--t-xs);padding:0 6px}
.mx td button{all:unset;cursor:pointer;display:flex;align-items:center;justify-content:center;width:100%;height:42px;border-radius:5px;font:500 var(--t-s) var(--f-mono)}
.mx td button:focus-visible{outline:2px solid var(--acc)}
.mx td button:hover{box-shadow:inset 0 0 0 1.5px var(--fg)}
.mx td button.e{color:var(--dim);background:var(--bg)}
.lp{position:fixed;top:0;right:0;height:100vh;width:min(520px,100vw);background:var(--surface);box-shadow:var(--shadow);transform:translateX(100%);transition:transform .22s ease;z-index:45;overflow:auto;padding:24px 26px}
.lp[open]{transform:none}
.lp ol{list-style:none;margin:14px 0 0;padding:0}
.lp li{padding:9px 6px;border-bottom:1px solid var(--hair);cursor:pointer;border-radius:4px}
.lp li:hover,.lp li:focus-visible{background:var(--raised)}
.lp li .t1{font-weight:500;font-size:var(--t-s);line-height:1.35}
.lp li .t2{font-size:var(--t-xs);color:var(--dim);display:flex;gap:8px;align-items:center;margin-top:2px}
.lp .ev{margin:16px 0 0}
.lp .ev a{font-weight:500;font-size:var(--t-s)}
.foot{margin-top:56px;color:var(--dim);font-size:var(--t-xs);display:flex;gap:4px;align-items:center}
@media (max-width:1200px){.fgrid{columns:2}.cyc{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media (max-width:760px){.sp .cols{grid-template-columns:1fr;gap:20px}.op{grid-template-columns:1fr;gap:6px}.op .ch.sp0{display:none}.fc .big{font-size:56px}}
@media (max-width:620px){.fgrid{columns:1}.cyc{grid-template-columns:1fr}.dr,.dax{grid-template-columns:minmax(0,130px) 1fr 28px}.sp{padding:16px}}`;
  document.head.appendChild(st);

  /* ---------- small helpers ---------- */
  H.GLOSSARY.stage = ['Stage', 'One step of the research cycle: reading the literature, forming a hypothesis, designing and running experiments, analysing results, writing and checking the paper.'];
  H.GLOSSARY.automated = ['Automated', 'The system does this stage on its own. Stages where a person does the work, or that the paper only mentions, are not counted.'];
  H.GLOSSARY.core = ['Core papers', 'The papers at the centre of the review (layer: core). Technique miners were run on these only.'];
  const RULE_TITLE = {
    no_human: 'Human role', full_lifecycle: 'Full research cycle', least_automated_stage: 'Least automated stage',
    most_varied_stage: 'Most varied stage', iterative_loop: 'Iterative loops', benchmark_validation: 'Validation',
    compare_with_humans: 'Comparison with humans', data_release: 'Data release',
  };
  const RELCOL = { released: '--inc', partial: '--h-feedback', promised: '--h-none', no: '--exc', ns: '--h-null', other: '--line' };
  const pctN = (a, b) => b ? Math.round(100 * a / b) : 0;
  const cic = id => (byId.get(id) || {}).cic || 0;
  const sortIds = ids => [...new Set(ids)].filter(id => byId.has(id)).sort((a, b) => cic(b) - cic(a) || byId.get(a).title.localeCompare(byId.get(b).title));
  const stageLabel = s => ((cyc.stages || []).find(x => x.stage === s) || {}).label || pretty(s);
  const lower = s => s.charAt(0).toLowerCase() + s.slice(1);
  const quoteText = q => { q = (q || '').trim(); return /[.!?”"’)]$/.test(q) ? q : q + ' …'; };
  const evOf = (ids, quotes, k = 5) => { const out = []; for (const id of sortIds(ids)) { const q = ((quotes || {})[id] || '').trim(); if (q.length >= 40) { out.push([id, q]); if (out.length >= k) break; } } return out; };
  const fill = (tpl, p) => tpl.replace(/\{(\w+)\}/g, (_, k) => p[k] ?? '');
  const sayHtml = c => esc(fill(c.template, c.params)).replace('human in the loop', term('human', 'human in the loop'));
  const sayText = c => fill(c.template, c.params);
  const cardBy = r => cards.find(c => c.rule === r);
  const popText = p => p ? `${fmt(p.with_value)} of ${fmt(p.of_included)} included papers have this coded${p.complete ? '' : '; the rest were not read for it'}` : '';

  /* ---------- charts ---------- */
  function waffle(share, hiLabel) {
    const n = Math.round(share * 100);
    const cells = Array.from({ length: 100 }, (_, i) => `<i class="${i < n ? 'h' : ''}"></i>`).join('');
    return `<div class="waf" role="img" aria-label="Waffle chart: each square is 1% of papers">${cells}</div>` +
      `<div class="cap"><span><span class="sw h"></span>${esc(hiLabel)}</span><span><span class="sw"></span>all others</span></div>`;
  }
  function stack(segs, hiKey) {
    const tot = segs.reduce((a, s) => a + s.n, 0), hi = segs.find(s => s.key === hiKey);
    return `<div class="stk" role="img" aria-label="Stacked bar of ${tot} papers">${segs.filter(s => s.n).map(s => `<i class="${s.key === hiKey ? 'h' : ''}" style="flex:${s.n}" data-tip="${esc(s.label)}: ${fmt(s.n)} (${pctN(s.n, tot)}%)"></i>`).join('')}</div>` +
      `<div class="cap">${hi ? `<span><span class="sw h"></span>${esc(hi.label)}</span>` : ''}<span><span class="sw"></span>other values</span></div>`;
  }
  function rowsChart(rows, max) {
    return `<div class="mb">${rows.map((r, i) => `<button type="button" class="${r.hi ? 'hi' : ''}" data-row="${i}" data-tip="${esc(r.full)}: ${esc(r.txt)}"><span class="l">${esc(r.l)}</span><span class="tr"><b style="width:${max ? 100 * r.v / max : 0}%"></b></span><span class="v">${esc(r.txt)}</span></button>`).join('')}</div>`;
  }

  /* Per-card view model: big number, chart, population line, list payload. All values come from the card. */
  function model(c) {
    const ex = c.extra || {}, m = { big: pctN(c.numerator, c.denominator), unit: '%', line: `${fmt(c.numerator)} of ${fmt(c.denominator)} papers`, chart: '', rows: null };
    const ev = (c.evidence || []).map(e => [e.work, e.quote]);
    m.list = { ids: c.ids, ev, tag: () => '' };
    switch (c.rule) {
      case 'no_human': m.chart = waffle(c.share, 'No human in the loop'); m.list.tag = id => H.humanLabel(H.val(byId.get(id), 'human')); break;
      case 'full_lifecycle':
        m.chart = waffle(c.share, 'Full research cycle');
        if (ex.alternative) m.line += ` · most common alternative: ${pretty(ex.alternative.value)} (${fmt(ex.alternative.n)})`;
        m.list.tag = () => 'Full research cycle'; break;
      case 'least_automated_stage': {
        const ss = cyc.stages || [], max = Math.max(1, ...ss.map(s => s.share || 0));
        m.rows = ss.map(s => ({ l: s.label.split(/ and | /)[0], full: s.label, v: s.share || 0, txt: pctN(s.automated, s.of) + '%', hi: s.stage === ex.stage, ids: s.ids, tag: () => 'Automates it' }));
        m.max = max; m.chart = rowsChart(m.rows, max);
        if (ex.most_automated) m.line += ` · most automated: ${lower(stageLabel(ex.most_automated.stage))} (${pctN(ex.most_automated.n, c.denominator)}%)`;
        m.list.tag = () => 'Automates it'; break; }
      case 'most_varied_stage': {
        const ss = cyc.stages || [], max = Math.max(1, ...ss.map(s => s.techniques_used));
        const byTech = s => { const q = {}; (s.techniques || []).forEach(t => Object.assign(q, Object.fromEntries(Object.entries(t.quotes || {}).filter(([k]) => !(k in q))))); return q; };
        m.rows = ss.map(s => ({ l: s.label.split(/ and | /)[0], full: s.label, v: s.techniques_used, txt: String(s.techniques_used), hi: s.stage === ex.stage, ids: [...new Set((s.techniques || []).flatMap(t => t.ids))], quotes: byTech(s), tag: () => '' }));
        m.big = c.numerator; m.unit = ''; m.max = max; m.chart = rowsChart(m.rows, max);
        m.line = `Among the ${term('core', fmt(cyc.core) + ' core papers')}` + (ex.fewest ? ` · fewest: ${lower(stageLabel(ex.fewest.stage))} (${fmt(ex.fewest.n)})` : '');
        m.list.quotes = (m.rows.find(r => r.hi) || {}).quotes; break; }
      case 'iterative_loop': m.chart = waffle(c.share, 'Iterative loop'); m.list.tag = () => 'Iterative loop'; break;
      case 'benchmark_validation': {
        const segs = (clm.columns || []).map(k => ({ key: k.key, label: k.label, n: (clm.column_totals || {})[k.key] || 0 }));
        m.chart = segs.length ? stack(segs, 'simulation-or-benchmark') : waffle(c.share, 'Benchmark or simulation');
        m.line += ` · real experiment ${fmt((ex.real_experiment || {}).n || 0)}, deployment ${fmt((ex.deployment || {}).n || 0)}`;
        m.list.tag = () => 'Benchmark or simulation'; break; }
      case 'compare_with_humans': m.chart = waffle(c.share, 'Compare with humans'); m.list.tag = () => 'Compares with humans'; break;
      case 'data_release': {
        const g = (opn.groups || [])[0], segs = g ? g.data.segments : [];
        m.chart = segs.length ? stack(segs, 'released') : waffle(c.share, 'Data released');
        if (ex.code_released) m.line = `${fmt(c.numerator)} of ${fmt(c.denominator)} papers with a release record · code ${fmt(ex.code_released.n)}`;
        m.list.tag = () => 'Data released'; break; }
    }
    return m;
  }
  const M = new Map(cards.map(c => [c.rule, model(c)]));

  /* ---------- list panel: papers or evidence, then the paper drawer ---------- */
  let lp = null;
  function openList(o, view = 'papers') {
    lp = lp || document.body.appendChild(Object.assign(document.createElement('aside'), { className: 'lp', id: 'lp' }));
    lp.setAttribute('aria-label', o.title);
    const ids = sortIds(o.ids || []);
    const ev = o.ev ? o.ev.filter(([id]) => byId.has(id)) : evOf(ids, o.quotes);
    const canEv = !!(o.ev || o.quotes);
    if (view === 'evidence' && !canEv) view = 'papers';
    let body;
    if (view === 'papers') body = ids.length ? `<ol>${ids.map(id => { const w = byId.get(id); const t = o.tag && o.tag(id); return `<li tabindex="0" data-open="${esc(id)}"><div class="t1">${esc(w.title)}</div><div class="t2"><span class="dot" style="background:${layerColor(w.layer)}"></span>${esc(layerLabel(w.layer))} · ${esc(w.month || w.year)} · ${term('cic', 'cited here')} ${w.cic || 0}${t ? ' · ' + esc(t) : ''}</div></li>`; }).join('')}</ol>` : '<div class="empty">No papers in this selection.</div>';
    else body = ev.length ? `<p class="meta" style="margin-top:12px">Each quotation is the sentence the reading was based on.</p>` + ev.map(([id, q]) => `<div class="ev"><blockquote class="quote">“${esc(quoteText(q))}”</blockquote><a href="#" data-open="${esc(id)}">${esc(byId.get(id).title)}</a></div>`).join('') : '<div class="empty">No quotations recorded for these papers.</div>';
    lp.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px"><div><h2 class="h2" style="font-family:var(--f-display);font-weight:400;font-size:22px;line-height:1.25">${o.titleHtml || esc(o.title)}</h2><div class="meta" style="margin-top:4px">${fmt(ids.length)} papers</div></div><button class="btn" id="lpX">Close <span class="kbd">Esc</span></button></div>` +
      (canEv ? `<div class="seg" style="margin-top:14px" role="group" aria-label="View"><button type="button" aria-pressed="${view === 'papers'}" data-v="papers">Papers</button><button type="button" aria-pressed="${view === 'evidence'}" data-v="evidence">Evidence</button></div>` : '') + body;
    lp.setAttribute('open', '');
    lp.querySelector('#lpX').onclick = closeList;
    lp.querySelectorAll('[data-v]').forEach(b => b.onclick = () => openList(o, b.dataset.v));
    lp.querySelectorAll('[data-open]').forEach(el => { el.onclick = e => { e.preventDefault(); openDrawer(el.dataset.open); }; el.onkeydown = e => { if (e.key === 'Enter') openDrawer(el.dataset.open); }; });
    H.hash.set(o.fid ? { f: o.fid, v: view } : { f: null, v: null });
    document.querySelectorAll('.fc').forEach(c => c.dataset.f === o.fid ? c.setAttribute('data-cur', '') : c.removeAttribute('data-cur'));
  }
  function closeList() { if (lp && lp.hasAttribute('open')) { lp.removeAttribute('open'); H.hash.set({ f: null, v: null }); document.querySelectorAll('.fc').forEach(c => c.removeAttribute('data-cur')); } }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeList(); });
  const tipOn = e => { const t = e.target.closest('[data-tip]'); if (t) H.tip(t.dataset.tip, e); };
  document.addEventListener('mouseover', tipOn); document.addEventListener('mousemove', tipOn);
  document.addEventListener('mouseout', e => { if (e.target.closest('[data-tip]')) H.tip(''); });

  /* ---------- lead, from the cards ---------- */
  function leadText() {
    const a = cardBy('no_human'), b = cardBy('benchmark_validation');
    const parts = [];
    if (a && a.available) parts.push(`${esc(a.params.share_cap)} of the systems run with no ${term('human', 'human in the loop')}.`);
    if (b && b.available) parts.push(`${esc(b.params.share_cap)} are validated on benchmarks or simulation; only ${esc(b.params.real_percent)} in a real experiment.`);
    if (parts.length) return parts.join(' ');
    const f = cards.find(c => c.available);
    return f ? esc(sayText(f)) : 'Findings appear here once papers have been coded.';
  }

  /* ---------- render ---------- */
  const TOP = Math.ceil(Math.max(0, ...(cyc.stages || []).map(s => s.share || 0)) * 10) / 10 || 1;
  const stagesInfo = `<b>What it shows</b>The seven stages of a research project, and how far the systems in this review automate each.<p><span class=k>How to read it.</span> Colour is the share of papers that do the stage on their own, from pale (few) to strong (many). Select a stage for the techniques used in it.</p><p><span class=k>How it’s computed.</span> ${esc(F.methods.cycle || '')}</p>`;
  const cardHtml = c => {
    const m = M.get(c.rule);
    if (!c.available) return `<article class="fc na" data-f="${esc(c.rule)}"><div class="top"><div class="big">–</div>${info(`<b>How this is computed</b>${esc(c.how)}`, 'How this number is computed')}</div><p class="say">${esc(RULE_TITLE[c.rule] || pretty(c.rule))}</p><p class="say" style="font-size:var(--t-s)">Not enough data yet</p></article>`;
    return `<article class="fc" data-f="${esc(c.rule)}">
      <div class="top"><div class="big">${fmt(m.big)}<small>${m.unit}</small></div>${info(`<b>How this is computed</b>${esc(c.how)}<p>${esc(popText(c.population))}.</p>`, 'How this number is computed')}</div>
      <p class="say">${sayHtml(c)}</p>
      <div class="chart">${m.chart}</div>
      <div class="nn">${m.line}</div>
      <div class="acts"><button class="btn primary" data-act="papers">Show papers</button><button class="btn" data-act="evidence">Show evidence</button></div></article>`;
  };

  function render() {
    const stages = cyc.stages || [];
    main.innerHTML = `<div class="fp">
    ${header({ level: 1, title: 'Findings', infoHtml: `<b>What it shows</b>What the review has found so far, as plain statements.<p><span class=k>How to read it.</span> Each card gives one number, the papers behind it, and quotations from those papers.</p><p><span class=k>How it’s computed.</span> ${esc(F.methods.cards || '')}</p>` })}
    <p class="lead">${leadText()}</p>
    <p class="meta">${fmt((F.population || {}).included || 0)} ${term('included', 'included papers')}, as of ${esc((d.shell.generated || '').slice(0, 10))}</p>
    <div class="fgrid" id="fg">${cards.map(cardHtml).join('')}</div>

    <section id="cycle">
      ${header({ title: 'The research cycle', sub: 'How far systems automate each stage, and with which techniques.', infoHtml: stagesInfo })}
      ${stages.length ? `<div class="cyc" id="cyc">${stages.map((s, i) => { const tp = (s.techniques || []).filter(t => t.n).slice(0, 3);
        return `<button type="button" class="stg" data-s="${esc(s.stage)}" aria-pressed="false" data-tip="${esc(s.label)}: ${fmt(s.automated)} of ${fmt(s.of)} papers automate it">
          <span class="band" style="background:color-mix(in srgb,var(--seq-4) ${Math.round(Math.min(1, (s.share || 0) / TOP) * 100)}%,var(--seq-1))"></span>
          <span class="k">Stage ${i + 1}</span><span class="nm">${esc(s.label)}</span>
          <span class="pc">${pctN(s.automated, s.of)}<small>% ${term('automated', 'automate it')}</small></span>
          <span class="ds">${fmt(s.automated)} of ${fmt(s.of)} papers<br>${fmt(s.techniques_listed)} techniques listed, ${fmt(s.techniques_used)} used</span>
          <ul class="tt">${tp.map(t => `<li><span>${esc(t.label)}</span><span>${fmt(t.n)}</span></li>`).join('')}</ul></button>`; }).join('')}</div>
        <div class="legend"><span>Share of papers that automate the stage</span><span>0%</span><span class="ramp"></span><span>${Math.round(TOP * 100)}%</span><span class="meta">Technique counts: ${fmt(cyc.core)} core papers</span></div>
        <div id="sp"></div>` : '<div class="empty">The cycle appears here once the stage readings are recorded.</div>'}
    </section>

    <section id="openness">
      ${header({ title: 'Openness', sub: `Code and data release, ${fmt(opn.n || 0)} papers with a release record.`, infoHtml: `<b>What it shows</b>Whether the papers release their code and their data.<p><span class=k>How to read it.</span> One bar per layer and artefact; each segment is a status. Select a segment to list its papers.</p><p><span class=k>How it’s computed.</span> ${esc(F.methods.openness || '')}</p>` })}
      <div id="op"></div>
    </section>

    <section id="claims">
      ${header({ title: 'Claims and validation', sub: 'What papers say they contribute, against how they test it.', infoHtml: `<b>What it shows</b>The kind of contribution each paper claims, against the strongest validation it reports.<p><span class=k>How to read it.</span> Rows are contribution types, columns are validation levels, weakest to strongest. A darker cell holds more papers. Select a cell to list them.</p><p><span class=k>How it’s computed.</span> ${esc(F.methods.claims || '')} Shading is linear in the count.</p>` })}
      <div id="mx"></div>
    </section>

    <footer class="foot">Papers, counts and sets ${info(H.SETS_NOTE, 'About the paper counts')}</footer></div>`;
    wireCards(); drawOpen(); drawMx(); wireStages(); applyHash();
  }

  function wireCards() {
    document.querySelectorAll('.fc').forEach(el => {
      const c = cardBy(el.dataset.f), m = M.get(el.dataset.f);
      if (!c || !c.available) return;
      el.querySelectorAll('[data-act]').forEach(b => b.onclick = () => openList({ fid: c.rule, title: sayText(c), titleHtml: sayHtml(c), ...m.list }, b.dataset.act));
      el.querySelectorAll('[data-row]').forEach(b => b.onclick = () => { const r = m.rows[+b.dataset.row]; openList({ title: r.full, ids: r.ids, quotes: r.quotes, tag: r.tag }, 'papers'); });
    });
  }

  /* openness */
  function drawOpen() {
    const op = document.getElementById('op'), groups = opn.groups || [];
    if (!groups.length) { op.innerHTML = '<div class="empty">Release status appears here once papers have been read for it.</div>'; return; }
    op.className = 'op';
    const bar = (g, col) => { const b = g[col], tot = b.n;
      return `<div class="sbar">${b.segments.map(s => `<button type="button" data-g="${s.ids.map(esc).join(',')}" data-t="${esc(s.label + ', ' + col)}" style="flex:${s.n};background:var(${RELCOL[s.key] || '--line'})" data-tip="${esc(s.label)}: ${fmt(s.n)} of ${fmt(tot)} (${pctN(s.n, tot)}%)">${100 * s.n / tot >= 9 ? s.n : ''}</button>`).join('')}</div>`; };
    const legend = [...new Map(groups.flatMap(g => [...g.data.segments, ...g.code.segments]).map(s => [s.key, s.label]))];
    op.innerHTML = `<span class="ch sp0"></span><span class="ch">Code</span><span class="ch">Data</span>` +
      groups.map(g => `<div class="rl">${esc(g.key === 'all' ? g.label : layerLabel(g.key))}<small>${fmt(g.n)} ${g.n === 1 ? 'paper' : 'papers'}</small></div>${bar(g, 'code')}${bar(g, 'data')}`).join('') +
      `<div class="leg">${legend.map(([k, l]) => `<span><i style="background:var(${RELCOL[k] || '--line'})"></i>${esc(l)}</span>`).join('')}</div>`;
    op.querySelectorAll('.sbar button').forEach(b => b.onclick = () => { const ids = b.dataset.g.split(','); openList({ title: b.dataset.t, ids }, 'papers'); });
  }

  /* claims by validation */
  function drawMx() {
    const el = document.getElementById('mx'), cols = clm.columns || [], rows = (clm.rows || []).filter(r => r.n);
    if (!rows.length) { el.innerHTML = '<div class="empty">Not enough data yet.</div>'; return; }
    el.className = 'mx';
    const max = Math.max(1, ...rows.flatMap(r => cols.map(c => (r.cells[c.key] || {}).n || 0)));
    el.innerHTML = `<table><thead><tr><th></th>${cols.map(c => `<th class="c">${esc(c.label)}</th>`).join('')}<th class="rt">Papers</th></tr></thead><tbody>${rows.map(r => `<tr><th scope="row" style="color:var(--fg);font-size:var(--t-s);font-weight:500">${esc(r.label)}</th>${cols.map(c => { const cell = r.cells[c.key] || { n: 0, ids: [] }, f = cell.n / max;
      return `<td><button type="button" class="${cell.n ? '' : 'e'}" ${cell.n ? `data-c="${esc(r.key + '|' + c.key)}"` : 'disabled'} style="${cell.n ? `background:color-mix(in srgb,var(--seq-4) ${Math.round(f * 100)}%,var(--seq-1));color:${f > .6 ? 'var(--acc-ink)' : 'var(--fg)'}` : ''}" data-tip="${esc(r.label + ' · ' + c.label)}: ${cell.n} of ${r.n} (${pctN(cell.n, r.n)}% of the row)">${cell.n || '·'}</button></td>`; }).join('')}<td class="rt">${fmt(r.n)}</td></tr>`).join('')}
      <tr><th></th>${cols.map(c => `<th class="rt" style="text-align:center">${fmt((clm.column_totals || {})[c.key] || 0)}</th>`).join('')}<th class="rt">${fmt(clm.n)}</th></tr></tbody></table>`;
    el.querySelectorAll('[data-c]').forEach(b => b.onclick = () => { const [rk, ck] = b.dataset.c.split('|'); const r = rows.find(x => x.key === rk), c = cols.find(x => x.key === ck);
      openList({ title: `${r.label}, validated by ${c.label.toLowerCase()}`, ids: r.cells[ck].ids }, 'papers'); });
  }

  /* stage panel */
  function wireStages() { document.querySelectorAll('.stg').forEach(b => b.onclick = () => { const cur = H.hash.get().get('stage'); H.hash.set({ stage: cur === b.dataset.s ? null : b.dataset.s, tech: null }); drawStage(); }); }
  function drawStage() {
    const sp = document.getElementById('sp'); if (!sp) return;
    const p = H.hash.get(), s = (cyc.stages || []).find(x => x.stage === p.get('stage'));
    document.querySelectorAll('.stg').forEach(b => b.setAttribute('aria-pressed', String(!!s && b.dataset.s === s.stage)));
    if (!s) { sp.innerHTML = '<div class="empty">Select a stage to see every technique used for it.</div>'; return; }
    const ts = s.techniques || [], mx = Math.max(1, ...ts.map(x => x.n)), axMax = Math.ceil(mx / 5) * 5;
    const sel = ts.find(x => x.code === p.get('tech')) || ts.find(x => x.n);
    sp.innerHTML = `<div class="sp"><div class="hd"><div><h3 class="h2">${esc(s.label)} ${info(`<b>Techniques for ${esc(s.label.toLowerCase())}</b>Every technique in the codebook for this stage, ranked by how many core papers use it.<p><span class=k>How it’s computed.</span> A paper counts once per technique. ${fmt(s.not_stated)} paper readings said the technique was not stated and ${fmt(s.other)} were “other”; these are not ranked.</p>`, 'About this list')}</h3>
      <div class="meta">${fmt(s.automated)} of ${fmt(s.of)} papers automate it · ${fmt(s.techniques_listed)} techniques listed, ${fmt(s.techniques_used)} used by the ${fmt(s.core)} core papers</div></div><button class="btn" id="spX">Close</button></div>
      <div class="cols"><div><div class="dax"><span></span><span class="ax"><span>0</span><span>${Math.round(axMax / 2)}</span><span>${axMax} papers</span></span><span></span></div>
      <div class="dp" role="list">${ts.map(x => `<button type="button" class="dr ${x.n ? '' : 'z'}" role="listitem" data-code="${esc(x.code)}" aria-pressed="${!!sel && sel.code === x.code}" style="--p:${100 * x.n / axMax}%" data-tip="${esc(x.label)}"><span class="l">${esc(x.label)}</span><span class="tr"><i></i></span><span class="v">${fmt(x.n)}</span></button>`).join('')}</div></div>
      <div class="tdet">${sel ? detail(s, sel) : '<div class="empty">No technique recorded.</div>'}</div></div></div>`;
    sp.querySelector('#spX').onclick = () => { H.hash.set({ stage: null, tech: null }); drawStage(); };
    sp.querySelectorAll('.dr').forEach(b => b.onclick = () => { H.hash.set({ tech: b.dataset.code }); drawStage(); });
    const all = sp.querySelector('[data-all]'); if (all) all.onclick = () => openList({ title: sel.label, ids: sel.ids, quotes: sel.quotes }, 'evidence');
    sp.querySelectorAll('[data-open]').forEach(a => a.onclick = e => { e.preventDefault(); openDrawer(a.dataset.open); });
  }
  function detail(s, x) {
    const ids = sortIds(x.ids), ev = evOf(ids, x.quotes, 3);
    return `<h3 class="h3">${esc(x.label)}</h3><div class="meta"><span class="mono">${esc(x.code)}</span> · ${fmt(x.n)} of ${fmt(s.core)} core papers (${pctN(x.n, s.core)}%)</div>
      <ul class="pp">${(ev.length ? ev : ids.slice(0, 3).map(id => [id, ''])).map(([id, q]) => `<li><a href="#" data-open="${esc(id)}">${esc(byId.get(id).title)}</a>${q ? `<blockquote class="quote">“${esc(quoteText(q))}”</blockquote>` : ''}</li>`).join('')}</ul>
      ${x.n > 3 ? `<p style="margin-top:14px"><button class="btn" data-all>Show all ${fmt(x.n)} papers</button></p>` : ''}`;
  }

  function applyHash() {
    drawStage();
    const p = H.hash.get(), f = p.get('f'), c = f && cardBy(f);
    if (c && c.available) { const m = M.get(f); openList({ fid: f, title: sayText(c), titleHtml: sayHtml(c), ...m.list }, p.get('v') === 'evidence' ? 'evidence' : 'papers'); }
  }
  render();
  window.addEventListener('hashchange', drawStage);
}).catch(e => {
  document.body.textContent = 'Findings failed to load: ' + e.message;
});
