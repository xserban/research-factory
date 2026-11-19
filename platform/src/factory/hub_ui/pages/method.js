/* Method page: Lifecycle, Steps and Taxonomy. Payload: method (services/hub_method.py). Every number comes
   from the payload; the nine stages, the name map and the sequence counts are computed there. The only counts
   made here are the filtered ones (layer, mode, text), taken over rows the payload carries.
   Hash state: tab, layer, mode, stage (an arc joins two stages with "|"), seq (t:a>b, l:a>b, o:<n>, s:<stage>),
   sstage, actor, chk, lim, q (steps), tax, v, cat (taxonomy). */
HUB.load(['shell', 'method']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'method', crumb: 'Method' });
  const { esc, fmt, info } = H;
  const M = d.method, L = M.lifecycle, SQ = L.sequences, ST = M.steps, TX = M.taxonomy, ME = M.methods || {};
  const STAGES = L.stages, NAME = Object.fromEntries(STAGES.map(s => [s.id, s.name]));
  const ids = STAGES.map(s => s.id), N = ids.length, IDX = Object.fromEntries(ids.map((s, i) => [s, i]));
  const TABS = [['lifecycle', 'Lifecycle'], ['steps', 'Steps'], ['taxonomy', 'Taxonomy']];
  const ACTOR_LABEL = { automated: 'automated', 'human-assisted': 'human-assisted', human: 'human', 'not-stated': 'not stated', '': 'not stated' };
  const ACTOR_COLOR = { automated: 'var(--acc)', 'human-assisted': 'var(--h-feedback)', human: 'var(--h-collab)' };
  const actorColor = a => ACTOR_COLOR[a] || 'var(--h-null)';
  const MODE_LABEL = { any: 'any mode', automated: 'automated', 'human-assisted': 'human-assisted', 'mentioned-only': 'mentioned only' };

  if (!document.getElementById('method-css')) {
    const s = document.createElement('style'); s.id = 'method-css';
    s.textContent = `
.mt-tabs{margin:16px 0 18px}
.mt-sec{background:var(--surface);border-radius:var(--r);padding:24px;margin:0 0 var(--gap)}
.mt-sec .sec-head{margin:0 0 6px}
.mt-sec .lead{max-width:64ch;font-size:22px;margin:10px 0 14px}
.mt-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}
.mt-bar .lbl{margin-right:4px}
.mt-warn{border-left:3px solid var(--h-feedback);background:var(--raised);padding:10px 14px;border-radius:var(--r-s);margin:12px 0;font-size:var(--t-s);color:var(--fg)}
.mt-diag{width:100%;display:block}
.mt-cols{display:grid;grid-template-columns:repeat(${N},1fr);text-align:center;font-size:var(--t-xs);color:var(--mut);margin-top:4px}
.mt-cols button{background:none;border:0;color:inherit;font:inherit;cursor:pointer;padding:4px 2px;border-radius:var(--r-s)}
.mt-cols button:hover,.mt-cols button[aria-pressed=true]{background:var(--acc-soft);color:var(--fg)}
.mt-cols b{display:block;color:var(--fg);font-weight:600}
.mt-arc{fill:none;cursor:pointer}
.mt-arc:hover,.mt-arc[aria-pressed=true]{stroke:var(--acc)!important;opacity:1!important}
.mt-node{fill:var(--acc);cursor:pointer}
.mt-line{stroke:var(--line);stroke-width:1}
.mt-list{list-style:none;margin:8px 0 0;padding:0}
.mt-list li{padding:10px 0;border-bottom:1px solid var(--hair)}
.mt-list .q{font-family:var(--f-display);color:var(--mut);margin:4px 0 0;font-size:var(--t-m)}
.mt-badge{display:inline-block;font:500 var(--t-xs)/1 var(--f-ui);padding:3px 7px;border-radius:999px;background:var(--raised);color:var(--mut);margin-left:6px}
.mt-seq{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.mt-step{border-radius:var(--r-s);padding:5px 8px;font-size:var(--t-xs);background:var(--raised);border-left:3px solid var(--h-null);color:var(--fg)}
.mt-arrow{color:var(--dim);font-size:var(--t-xs)}
.mt-heat td.c{text-align:center;font-family:var(--f-mono);min-width:44px}
.mt-bars{display:grid;grid-template-columns:70px 1fr 50px;gap:6px 10px;align-items:center;font-size:var(--t-s)}
.mt-bars i{display:block;height:12px;background:var(--acc);border-radius:3px;min-width:1px}
.mt-two{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px}
.mt-st-sec{margin:20px 0}
.mt-st-sec h3{margin:0 0 6px}
.mt-step-row{padding:8px 0;border-bottom:1px solid var(--hair)}
.mt-step-row summary{cursor:pointer;list-style:none}
.mt-step-row .det{margin:8px 0 0 22px;color:var(--mut);font-size:var(--t-s)}
.mt-step-row .det .quote{margin:2px 0 8px}
.mt-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.mt-strip button{background:var(--raised);border:0;border-radius:var(--r-s);padding:10px;text-align:left;color:var(--fg);cursor:pointer;font:inherit}
.mt-strip button[aria-pressed=true]{box-shadow:inset 0 0 0 1px var(--acc);background:var(--acc-soft)}
.mt-strip .n{font:600 var(--t-l)/1.2 var(--f-mono);display:block}
.mt-input{background:var(--raised);color:var(--fg);border:0;border-radius:var(--r-s);padding:7px 10px;font:inherit;min-width:220px}
.mt-cat{padding:12px 0;border-bottom:1px solid var(--hair)}
.mt-cat:target,.mt-cat.sel{background:var(--acc-soft);border-radius:var(--r-s);padding:12px}
.mt-cat dl{display:grid;grid-template-columns:130px 1fr;gap:4px 12px;margin:8px 0 0;font-size:var(--t-s)}
.mt-cat dt{color:var(--mut)}.mt-cat dd{margin:0}
.mt-rules code{font-family:var(--f-mono);font-size:var(--t-xs);color:var(--mut)}
.mt-empty{color:var(--mut);padding:14px 0;font-size:var(--t-s)}
@media(max-width:700px){.mt-cols{font-size:10px}.mt-cat dl{grid-template-columns:1fr}}
`;
    document.head.appendChild(s);
  }

  const S = { tab: 'lifecycle' };
  const readHash = () => {
    const p = H.hash.get();
    S.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'lifecycle';
    S.layer = p.get('layer') || 'all'; S.mode = p.get('mode') || 'any'; S.stage = p.get('stage') || '';
    S.seq = p.get('seq') || ''; S.sstage = p.get('sstage') || 'all';
    S.actor = p.get('actor') || 'any'; S.chk = p.get('chk') === '1'; S.lim = p.get('lim') === '1'; S.q = p.get('q') || '';
    S.tax = p.get('tax') || ''; S.v = +p.get('v') || 0; S.cat = p.get('cat') || '';
  };
  const go = obj => { H.hash.set(obj); readHash(); render(); };
  const paperLink = (id, title) => H.byId && H.byId.has(id)
    ? `<a href="#" data-open="${esc(id)}">${esc(title)}</a>` : `<span>${esc(title)}</span>`;
  const sn = id => NAME[id] || id;

  /* ---------- shared diagram: nine stages on a line, arcs above (forward) and below (back) ---------- */
  function arcDiagram({ nodes, arcs, below, selected, kind, label }) {
    const W = 960, UP = 230, DN = below ? 230 : 40, Y = UP, colW = W / N;
    const x = i => (i + 0.5) * colW;
    const maxN = Math.max(1, ...arcs.map(a => a.n), ...nodes.map(n => n.n));
    const path = (a, b) => {
      const xa = x(IDX[a]), xb = x(IDX[b]), dist = Math.abs(xb - xa);
      if (!dist) return `M${xa - 8},${Y} C${xa - 30},${Y - 60} ${xa + 30},${Y - 60} ${xa + 8},${Y}`;
      return `M${xa},${Y} A${dist / 2},${Math.min(10 + dist * 0.26, 225)} 0 0 1 ${xb},${Y}`;
    };
    let svg = `<svg class="mt-diag" viewBox="0 0 ${W} ${UP + DN}" role="img" aria-label="${esc(label)}">
      <defs><marker id="mt-ar" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--mut)"/></marker></defs>
      <line class="mt-line" x1="0" x2="${W}" y1="${Y}" y2="${Y}"/>`;
    for (const a of arcs) {
      const sel = selected === a.key, dash = a.loop ? ' stroke-dasharray="5 4"' : '';
      svg += `<path class="mt-arc" data-${kind}="${esc(a.key)}" d="${path(a.from, a.to)}" stroke="${a.loop ? 'var(--h-feedback)' : 'var(--mut)'}"${dash}
        stroke-width="${(1.5 + 13 * a.n / maxN).toFixed(1)}" opacity="${sel ? 1 : 0.45}" ${sel ? 'aria-pressed="true"' : ''}${kind === 'seq' && !a.loop ? ' marker-end="url(#mt-ar)"' : ''}><title>${esc(a.tip)}</title></path>`;
    }
    for (const n of nodes) {
      const r = 6 + 16 * Math.sqrt(n.n / maxN);
      svg += `<circle class="mt-node" data-node="${esc(n.id)}" cx="${x(IDX[n.id])}" cy="${Y}" r="${r.toFixed(1)}"${n.sel ? ' stroke="var(--fg)" stroke-width="2"' : ''}><title>${esc(sn(n.id) + ': ' + fmt(n.n))}</title></circle>`;
    }
    return svg + '</svg>';
  }
  const colRow = (cells, sel) => `<div class="mt-cols">${ids.map((s, i) =>
    `<button type="button" data-node="${esc(s)}" aria-pressed="${sel === s}">${esc(sn(s))}${cells[i]}</button>`).join('')}</div>`;

  /* ---------- lifecycle: stage coverage (m-stages) ---------- */
  const covers = (w, s) => (w.stages[s] || []).some(r => S.mode === 'any' || r.mode === S.mode);
  const fworks = () => L.works.filter(w => S.layer === 'all' || w.layer === S.layer);
  function coverage() {
    const ws = fworks(), nodes = ids.map(s => ({ id: s, n: ws.filter(w => covers(w, s)).length, sel: S.stage.split('|').includes(s) }));
    const arcs = [];
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const n = ws.filter(w => covers(w, ids[i]) && covers(w, ids[j])).length;
      if (n) arcs.push({ key: ids[i] + '|' + ids[j], from: ids[i], to: ids[j], n, tip: `${sn(ids[i])} and ${sn(ids[j])}: ${fmt(n)} papers` });
    }
    return { ws, nodes, arcs };
  }
  function selectedList(ws) {
    if (!S.stage) return '<p class="mt-empty">Click a stage or an arc to list its papers with the quote behind each row.</p>';
    const sel = S.stage.split('|').filter(s => NAME[s]);
    const hit = ws.filter(w => sel.every(s => covers(w, s)));
    const rows = hit.map(w => {
      const r = (w.stages[sel[0]] || []).find(r => S.mode === 'any' || r.mode === S.mode) || {};
      return `<li>${paperLink(w.id, w.title)} <span class="meta">${esc(w.year)}</span>
        <span class="mt-badge"><span class="dot" style="background:${H.layerColor(w.layer)}"></span> ${esc(H.layerLabel(w.layer))}</span>
        ${r.mode ? `<span class="mt-badge">${esc(MODE_LABEL[r.mode] || r.mode)}</span>` : ''}
        ${r.quote ? `<p class="q">“${esc(r.quote)}”${r.anchor ? ` <span class="meta">${esc(r.anchor)}</span>` : ''}</p>` : ''}</li>`;
    }).join('');
    return `<p class="meta"><b class="num">${fmt(hit.length)}</b> papers cover ${esc(sel.map(sn).join(' and '))}${S.layer !== 'all' ? ', layer ' + esc(H.layerLabel(S.layer)) : ''}.
      <button type="button" class="btn" data-clear="stage">Clear</button></p><ul class="mt-list">${rows}</ul>`;
  }
  function chips(items, cur, key) {
    return items.map(([v, label, n]) => `<button type="button" class="chip" data-f="${key}" data-v="${esc(v)}" aria-pressed="${cur === v}">${esc(label)}${n != null ? ` <span class="n">${fmt(n)}</span>` : ''}</button>`).join('');
  }
  function lifecycleFlow() {
    const { ws, nodes, arcs } = coverage();
    const layers = [['all', 'All layers', L.works.length], ...L.layers.map(l => [l.id, H.layerLabel(l.id), l.n])];
    const modes = [['any', 'Any mode'], ...L.modes.map(m => [m, MODE_LABEL[m] || m])];
    return `<section class="mt-sec" id="lc-flow">
      ${H.header({ title: 'Stage coverage', sub: 'Which stages papers cover, and which they cover together. Left to right is a layout, not a finding.', infoHtml: ME.lifecycle_flow || '' })}
      <div class="mt-bar"><span class="lbl">Layer</span>${chips(layers, S.layer, 'layer')}</div>
      <div class="mt-bar"><span class="lbl">Mode</span>${chips(modes, S.mode, 'mode')}</div>
      ${L.works.length ? arcDiagram({ nodes, arcs, below: false, selected: S.stage, kind: 'arc', label: 'Stages of AI research systems and how often papers cover them' }) +
        colRow(nodes.map(n => `<b class="num">${fmt(n.n)}</b>`), S.stage) + selectedList(ws)
        : '<p class="mt-empty">No paper has stage rows yet.</p>'}
    </section>`;
  }
  function matrix() {
    const lay = L.layers.map(l => l.id);
    const cell = (n, layer, stage) => n ? `<a href="#" data-f="cell" data-layer="${esc(layer)}" data-stage="${esc(stage)}">${fmt(n)}</a>` : '0';
    return `<section class="mt-sec" id="lc-matrix">
      ${H.header({ title: 'Papers per stage and layer', infoHtml: ME.stage_matrix || '' })}
      <div style="overflow-x:auto"><table class="t"><thead><tr><th>Stage</th>${lay.map(l => `<th class="r">${esc(H.layerLabel(l))}</th>`).join('')}<th class="r">All</th></tr></thead><tbody>
      ${L.matrix.map(r => `<tr><td>${esc(sn(r.stage))} <a class="meta" href="#" data-tab-go="steps" data-stage="${esc(r.stage)}">Steps →</a></td>
        ${lay.map(l => `<td class="r">${cell(r.layers[l], l, r.stage)}</td>`).join('')}<td class="r">${cell(r.n, 'all', r.stage)}</td></tr>`).join('')}
      </tbody></table></div></section>`;
  }
  const heat = (v, max) => v ? `style="background:color-mix(in srgb,var(--acc) ${Math.round(12 + 60 * v / max)}%,transparent)"` : '';
  function coverageGrids() {
    const mm = Math.max(1, ...L.stage_mode.flatMap(r => Object.values(r.modes)));
    const modeGrid = `<table class="t mt-heat"><thead><tr><th>Stage</th>${L.modes.map(m => `<th class="r">${esc(MODE_LABEL[m])}</th>`).join('')}</tr></thead><tbody>
      ${L.stage_mode.map(r => `<tr><td>${esc(sn(r.stage))}</td>${L.modes.map(m => `<td class="c" ${heat(r.modes[m], mm)}>${r.modes[m] ? `<a href="#" data-f="cell2" data-stage="${esc(r.stage)}" data-mode="${esc(m)}">${fmt(r.modes[m])}</a>` : '0'}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    const mx = Math.max(1, ...L.distinct_stages.map(d => d.n));
    const bars = L.distinct_stages.length ? `<div class="mt-bars">${L.distinct_stages.map(d => `<span>${fmt(d.k)} ${d.k === 1 ? 'stage' : 'stages'}</span><i style="width:${(100 * d.n / mx).toFixed(1)}%"></i><span class="num">${fmt(d.n)}</span>`).join('')}</div>` : '<p class="mt-empty">No data yet.</p>';
    const tx = L.stage_technique, tm = Math.max(1, ...tx.rows.flatMap(r => Object.values(r.n)));
    const techGrid = tx.techniques.length ? `<div style="overflow-x:auto"><table class="t mt-heat"><thead><tr><th>Stage</th>${tx.techniques.map(t => `<th class="r">${esc(H.pretty(t))}</th>`).join('')}</tr></thead><tbody>
      ${tx.rows.map(r => `<tr><td>${esc(sn(r.stage))}</td>${tx.techniques.map(t => `<td class="c" ${heat(r.n[t], tm)}>${r.n[t] ? fmt(r.n[t]) : ''}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '<p class="mt-empty">No automated stage has a technique yet.</p>';
    return `<section class="mt-sec" id="lc-grids">
      ${H.header({ title: 'How stages are covered', infoHtml: ME.stage_mode || '' })}
      <div class="mt-two"><div><h3 class="h3">By mode ${info(ME.stage_mode || '', 'About stage by mode')}</h3>${modeGrid}</div>
      <div><h3 class="h3">Stages per paper ${info(ME.stage_count || '', 'About stages per paper')}</h3>${bars}</div></div>
      <h3 class="h3" style="margin-top:22px">By technique ${info(ME.stage_technique || '', 'About stage by technique')}</h3>${techGrid}</section>`;
  }

  /* ---------- lifecycle: overall sequences (LC-10) and each paper's own sequence (LC-8) ---------- */
  const parseSeq = () => { const m = /^([tlos]):(.*)$/.exec(S.seq || ''); return m ? { k: m[1], v: m[2] } : null; };
  function seqFilter() {
    const f = parseSeq(); if (!f) return () => true;
    if (f.k === 't' || f.k === 'l') {
      const [a, b] = f.v.split('>');
      return f.k === 't' ? p => p.path.some((s, i) => s === a && p.path[i + 1] === b) : p => p.stages.some(e => e.stage === a && e.loops_to === b);
    }
    if (f.k === 'o') { const o = SQ.orders[+f.v]; return p => !!o && p.path.join('>') === o.path.join('>'); }
    return p => p.path.includes(f.v);
  }
  const seqLabel = () => {
    const f = parseSeq(); if (!f) return '';
    if (f.k === 't') return 'taking ' + f.v.split('>').map(sn).join(' → ');
    if (f.k === 'l') return 'looping back ' + f.v.split('>').map(sn).join(' → ');
    if (f.k === 'o') return 'with the order selected';
    return 'passing through ' + sn(f.v);
  };
  const stepChip = e => `<span class="mt-step" style="border-left-color:${actorColor(e.actor)}" title="${esc((e.how || '') + (e.actor ? ' (' + (ACTOR_LABEL[e.actor] || e.actor) + ')' : ''))}">${esc(e.order)} ${esc(e.name)}${e.next ? ` <span class="mt-arrow">→ ${esc(e.next)}</span>` : ''}${e.loops && !/^(none|no)$/i.test(e.loops.trim()) ? ` <span class="mt-arrow">loop ${esc(e.loops)}</span>` : ''}</span>`;
  function sequences() {
    if (!SQ.n_papers) return `<section class="mt-sec" id="lc-seq">${H.header({ title: 'Stage sequences', infoHtml: ME.sequences || '' })}
      <p class="mt-empty">No paper has stage rows from the lifecycle miner yet. It is registered and listed for core papers; calibration comes before the production run.</p></section>`;
    const arcs = [
      ...SQ.transitions.map(t => ({ key: 't:' + t.from + '>' + t.to, from: t.from, to: t.to, n: t.n, tip: `${sn(t.from)} → ${sn(t.to)}: ${fmt(t.n)} papers` })),
      ...SQ.loops.map(t => ({ key: 'l:' + t.from + '>' + t.to, from: t.from, to: t.to, n: t.n, loop: true, tip: `Loop back ${sn(t.from)} → ${sn(t.to)}: ${fmt(t.n)} papers` })),
    ];
    const f = parseSeq(), cur = f ? f.k + ':' + f.v : '';
    const nodes = ids.map(s => ({ id: s, n: SQ.papers.filter(p => p.path.includes(s)).length, sel: f && f.k === 's' && f.v === s }));
    const cells = ids.map(s => `<span class="meta">in <b class="num" style="display:inline">${fmt(SQ.entry[s])}</b> · out <b class="num" style="display:inline">${fmt(SQ.exit[s])}</b></span>`);
    const orders = SQ.orders.map((o, i) => `<li><a href="#" data-seq="o:${i}"${cur === 'o:' + i ? ' aria-current="true"' : ''}>${o.path.map(sn).map(esc).join(' → ')}</a> <b class="num">${fmt(o.n)}</b></li>`).join('');
    const ok = seqFilter();
    const papers = SQ.papers.filter(ok);
    return `<section class="mt-sec" id="lc-seq">
      ${H.header({ title: 'Stage sequences', sub: 'The order in which papers run the stages, over all papers.', infoHtml: ME.sequences || '' })}
      <div class="mt-warn">From pass A of the lifecycle miner, for <b class="num">${fmt(SQ.n_papers)}</b> papers with rows (<b class="num">${fmt(SQ.n_rows)}</b> stage rows). Until the production run these are the calibration sample only, not yet checked against the gold labels.</div>
      ${arcDiagram({ nodes, arcs, below: true, selected: cur, kind: 'seq', label: 'Transitions between stages over all papers' })}
      ${colRow(cells, f && f.k === 's' ? f.v : '')}
      <p class="meta">Arcs above go forward, arcs below go back; dashed arcs are loops the papers state. Thickness is papers. ${arcs.length ? 'Click an arc or a stage to filter the papers below.' : ''}</p>
      <div class="mt-two" style="margin-top:18px"><div><h3 class="h3">Most common orders</h3><ol class="mt-list" style="list-style:decimal inside">${orders}</ol></div>
      <div><h3 class="h3">Loops back</h3>${SQ.loops.length ? `<ul class="mt-list">${SQ.loops.map(l => `<li><a href="#" data-seq="l:${esc(l.from)}>${esc(l.to)}">${esc(sn(l.from))} → ${esc(sn(l.to))}</a> <b class="num">${fmt(l.n)}</b></li>`).join('')}</ul>` : '<p class="mt-empty">No paper states a loop back.</p>'}
      ${SQ.unresolved_loops ? `<p class="meta">${fmt(SQ.unresolved_loops)} loop statements could not be matched to a stage of the same paper.</p>` : ''}</div></div>
      <h3 class="h3" style="margin-top:22px">Each paper's own sequence</h3>
      <p class="meta"><b class="num">${fmt(papers.length)}</b> of ${fmt(SQ.n_papers)} papers${f ? ' ' + esc(seqLabel()) : ''}. ${f ? '<button type="button" class="btn" data-clear="seq">Show all</button>' : ''}</p>
      <ul class="mt-list">${papers.map(p => `<li>${paperLink(p.id, p.title)} <span class="meta">${esc(p.year)}</span><div class="mt-seq" style="margin-top:6px">${p.stages.map(stepChip).join('<span class="mt-arrow">→</span>')}</div></li>`).join('')}</ul>
    </section>`;
  }
  function stageMap() {
    const rows = SQ.stage_map.map(r => `<tr><td>${esc(r.name || '(no name)')}</td><td>${r.mapped ? esc(sn(r.stage)) : `<b>${esc(sn(r.stage))}</b> <span class="meta">unmapped</span>`}</td><td class="r">${fmt(r.papers)}</td><td class="r">${fmt(r.rows)}</td></tr>`).join('');
    return `<section class="mt-sec mt-rules" id="lc-map">
      ${H.header({ title: 'How stage names were grouped', sub: SQ.unmapped.length ? 'Names the rules do not know sit in other.' : 'Every name matched a rule.', infoHtml: ME.stage_map || '' })}
      ${SQ.stage_map.length ? `<div style="overflow-x:auto"><table class="t"><thead><tr><th>Name in the paper</th><th>Stage</th><th class="r">Papers</th><th class="r">Rows</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="mt-empty">No stage names yet.</p>'}
      <details style="margin-top:14px"><summary class="meta" style="cursor:pointer">The rules, in the order they are tried</summary>
      <table class="t"><tbody>${L.stage_rules.map(r => `<tr><td>${esc(sn(r.stage))}</td><td><code>${r.keywords.map(esc).join(' · ')}</code></td></tr>`).join('')}</tbody></table></details>
    </section>`;
  }
  const lifecycleLinks = () => `<p class="meta">See also <a href="miners.html">Miners</a> for the state of the stage miners, <a href="lenses.html">Lenses</a>, and <a href="platform.html">Platform</a> for what is planned.</p>`;
  const lifecycle = () => lifecycleFlow() + matrix() + coverageGrids() + sequences() + stageMap() + lifecycleLinks();

  /* ---------- steps ---------- */
  function stepsView() {
    const q = S.q.toLowerCase(), cur = S.sstage;
    const keep = s => (S.actor === 'any' || (s.actor || 'not-stated') === S.actor) && (!S.chk || s.check) && (!S.lim || s.limits)
      && (!q || (s.text + ' ' + (s.method?.text || '') + ' ' + (s.inputs?.text || '') + ' ' + (s.outputs?.text || '')).toLowerCase().includes(q));
    const filt = ST.stages.map(st => ({ ...st, works: st.works.map(w => ({ ...w, steps: w.steps.filter(keep) })).filter(w => w.steps.length) }));
    const shown = filt.filter(s => cur === 'all' || s.id === cur);
    const nShown = shown.reduce((a, s) => a + s.works.reduce((b, w) => b + w.steps.length, 0), 0);
    const strip = `<div class="mt-strip">${ST.stages.map(s => `<button type="button" data-sstage="${esc(s.id)}" aria-pressed="${cur === s.id}">${esc(s.name)}<span class="n">${fmt(s.n_steps)}</span><span class="meta">${fmt(s.n_works)} papers</span></button>`).join('')}</div>`;
    const detail = (label, c) => c ? `<div><b>${label}</b><blockquote class="quote">“${esc(c.text)}”${c.anchor ? ` <span class="meta">${esc(c.anchor)}</span>` : ''}</blockquote></div>` : '';
    const sect = st => `<div class="mt-st-sec" id="stage-${esc(st.id)}"><h3 class="h3">${esc(st.name)} <span class="meta">${fmt(st.works.length)} papers, ${fmt(st.works.reduce((a, w) => a + w.steps.length, 0))} steps</span></h3>
      ${st.works.length ? st.works.map(w => `<div style="margin:10px 0"><div>${paperLink(w.id, w.title)} <span class="meta">${esc(w.year)}</span></div>
        ${w.steps.map(s => `<details class="mt-step-row"><summary><span class="meta">${s.order === 99 ? '' : fmt(s.order)}</span> ${esc(s.text)} ${s.anchor ? `<span class="meta">${esc(s.anchor)}</span>` : ''}
          <span class="mt-badge" style="border-left:3px solid ${actorColor(s.actor)}">${esc(ACTOR_LABEL[s.actor] || s.actor)}</span></summary>
          <div class="det">${ST.fields.map(f => detail(f, s[f])).join('') || '<span class="meta">No inputs, outputs, method, check or limits stated.</span>'}</div></details>`).join('')}</div>`).join('')
        : '<p class="mt-empty">No steps in this stage: the miner found none in any paper.</p>'}</div>`;
    return `<section class="mt-sec" id="steps">
      ${H.header({ title: 'Steps', sub: 'What a system does in each stage, paper by paper.', infoHtml: ME.steps || '' })}
      <div class="mt-warn"><b>Exploratory.</b> The ${esc(ST.miner)} miner has no calibration. These rows are for reading, not evidence: no count from them goes into a report, a claim or a hypothesis, and some steps may sit in the wrong stage.</div>
      ${ST.n_rows ? `${strip}
      <div class="mt-bar" style="margin-top:14px"><span class="lbl">Actor</span>${chips([['any', 'Any'], ...ST.actors.map(a => [a, ACTOR_LABEL[a]])], S.actor, 'actor')}
        <button type="button" class="chip" data-f="chk" aria-pressed="${S.chk}">Has a check</button><button type="button" class="chip" data-f="lim" aria-pressed="${S.lim}">Has limits</button>
        <input class="mt-input" id="mt-q" type="search" placeholder="Search steps" value="${esc(S.q)}" aria-label="Search steps"><button type="button" class="chip" data-f="all" aria-pressed="${cur === 'all'}">All stages</button></div>
      <p class="meta"><b class="num">${fmt(nShown)}</b> steps shown of ${fmt(ST.n_rows)}, from ${fmt(ST.n_works)} papers.</p>
      ${shown.map(sect).join('')}` : '<p class="mt-empty">No step rows yet. The steps miner has not been run.</p>'}
    </section>`;
  }

  /* ---------- taxonomy ---------- */
  function taxView() {
    const reg = TX.registered;
    const cur = reg.find(t => t.name === S.tax) || reg[0];
    const ver = cur && (cur.versions.find(v => v.version === S.v) || cur.versions[0]);
    const index = reg.length ? `<div style="overflow-x:auto"><table class="t"><thead><tr><th>Name</th><th>Versions, latest first</th><th class="r">Open proposals</th></tr></thead><tbody>
      ${reg.map(t => `<tr><td>${esc(t.name)}</td><td>${t.versions.map(v => `<a href="#" data-tax="${esc(t.name)}" data-v="${v.version}">v${fmt(v.version)}</a> <code class="meta">${esc((v.digest || '').slice(0, 12))}</code> <span class="meta">${esc(v.date)}, ${fmt(v.n_dimensions)} dimensions, ${fmt(v.n_categories)} categories</span>`).join('<br>')}</td><td class="r">${fmt(t.open_proposals)}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="mt-empty">No taxonomy is registered yet. The researcher registers them.</p>';
    return `<section class="mt-sec" id="tax">${H.header({ title: 'Taxonomies', sub: 'The project’s own categories, by version.', infoHtml: ME.taxonomy || '' })}${index}</section>`
      + (ver ? taxVersion(cur, ver) : '') + legacy() +
      `<p class="meta">The codebook of technique codes is on the <a href="miners.html">Miners</a> page.</p>`;
  }
  function diffTable(v) {
    if (!v.diff) return '';
    return `<h3 class="h3" style="margin-top:18px">Changes from version ${fmt(v.against)}</h3><table class="t"><tbody>${v.diff.map(r => `<tr><td style="width:130px">${esc(r.label)}</td><td>${esc(r.text) || '<span class="meta">none</span>'}</td></tr>`).join('')}</tbody></table>`;
  }
  function taxVersion(t, v) {
    const m = v.miner;
    const mx = Math.max(1, ...v.dimensions.flatMap(dm => dm.categories.map(c => c.count || 0)));
    const dim = dm => `<h3 class="h3" style="margin-top:24px">${esc(dm.title)} <span class="meta">${esc(dm.id)}</span></h3>
      <table class="t"><tbody><tr><td style="width:130px">Question</td><td>${esc(dm.question)}</td></tr><tr><td>Cardinality</td><td>${esc(dm.cardinality)}</td></tr>
      <tr><td>Read scope</td><td>${esc(dm.read_scope) || 'none'}</td></tr>
      <tr><td>Residuals</td><td>${dm.residuals.map(r => esc(r.id) + (r.count != null ? ' ' + fmt(r.count) : '')).join(', ') || 'none'}</td></tr></tbody></table>
      ${!dm.categories.length && dm.layer_scheme != null ? `<p class="meta">Categories come from layer scheme version ${fmt(dm.layer_scheme)}.</p>` : ''}
      ${dm.categories.map(c => cat(c)).join('')}`;
    const list = a => a.length ? `<ul style="margin:0;padding-left:18px">${a.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : 'none';
    const cat = c => `<div class="mt-cat${S.cat === c.full_id ? ' sel' : ''}" id="${esc(c.full_id)}"><b>${esc(c.id)}</b> — ${esc(c.name)}
      ${c.count != null ? `<span class="num" style="float:right">${fmt(c.count)}</span>` : c.mined ? '' : '<span class="meta" style="float:right">not mined</span>'}
      ${c.count != null ? `<div style="height:6px;background:var(--acc);border-radius:3px;width:${(100 * c.count / mx).toFixed(1)}%;min-width:1px;margin:6px 0"></div>` : ''}
      <dl><dt>Definition</dt><dd>${esc(c.definition)}</dd><dt>Works with a current row</dt><dd>${c.count != null ? fmt(c.count) : c.mined ? '' : 'not mined'}</dd>
      <dt>Include cues</dt><dd>${list(c.include)}</dd><dt>Exclude cues</dt><dd>${list(c.exclude)}</dd>
      ${c.examples.length ? `<dt>Examples</dt><dd>${c.examples.map(e => `<blockquote class="quote">“${esc(e.quote)}” ${H.byId && H.byId.has(e.work) ? `<a href="#" data-open="${esc(e.work)}">${esc(e.work)}</a>` : esc(e.work)}, ${esc(e.anchor)}</blockquote>`).join('')}</dd>` : ''}</dl></div>`;
    return `<section class="mt-sec" id="tax-v">
      ${H.header({ title: `${t.name}, version ${v.version}`, sub: 'Versions: ' + t.versions.map(x => x.version === v.version ? `<b>${fmt(x.version)}</b>` : `<a href="#" data-tax="${esc(t.name)}" data-v="${x.version}">${fmt(x.version)}</a>`).join(', ') })}
      ${v.rationale ? `<p class="lead" style="font-size:var(--t-m)">${esc(v.rationale)}</p>` : ''}
      <p class="meta">${m ? `Derived miner: <a href="miners.html#m=${encodeURIComponent(m.name)}">${esc(m.name)}</a> version ${fmt(m.version)}. Counts are papers with a current row.` : 'No derived miner yet.'}</p>
      ${diffTable(v)}${v.dimensions.map(dim).join('')}</section>`;
  }
  function legacy() {
    const g = TX.legacy; if (!g) return '';
    return `<details class="mt-sec"><summary class="h2" style="cursor:pointer">Earlier unregistered list: ${esc(g.name)}</summary>
      <p class="meta">Kept as it was. Status: ${esc(g.status)}. ${esc(g.source)}</p>
      ${g.dimensions.map(dm => `<h3 class="h3">${esc(dm.title)}</h3><table class="t"><thead><tr><th>Category</th><th>Keyword pattern</th></tr></thead><tbody>${dm.categories.map(c => `<tr><td>${esc(c.name)}</td><td><code>${esc(c.pattern || '(matches none)')}</code></td></tr>`).join('')}</tbody></table>`).join('')}</details>`;
  }

  /* ---------- page ---------- */
  function render() {
    const body = { lifecycle, steps: stepsView, taxonomy: taxView }[S.tab]();
    main.innerHTML = H.header({ title: 'Method', sub: 'Lifecycle, steps and taxonomy.', level: 1 }) +
      `<div class="mt-tabs"><div class="seg" role="tablist" aria-label="Method view">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-pressed="${k === S.tab}">${l}</button>`).join('')}</div></div>` + body;
    const q = main.querySelector('#mt-q');
    if (q) q.oninput = () => { const pos = q.selectionStart; H.hash.set({ q: q.value || null }); readHash(); render(); const n = main.querySelector('#mt-q'); n.focus(); n.setSelectionRange(pos, pos); };
    const target = S.tab === 'taxonomy' && S.cat ? document.getElementById(S.cat) : null;
    if (target) target.scrollIntoView({ block: 'center' });
  }
  main.addEventListener('click', e => {
    const a = e.target.closest('[data-open],[data-tab],[data-f],[data-node],[data-arc],[data-seq],[data-clear],[data-tab-go],[data-sstage],[data-tax]');
    if (!a) return;
    e.preventDefault();
    const D = a.dataset;
    if (D.open) return H.openDrawer(D.open);
    if (D.tab) return go({ tab: D.tab === 'lifecycle' ? null : D.tab });
    if (D.tabGo) return go({ tab: D.tabGo, sstage: D.stage, stage: null });
    if (D.sstage) return go({ sstage: D.sstage === S.sstage ? 'all' : D.sstage });
    if (D.tax) return go({ tab: 'taxonomy', tax: D.tax, v: D.v, cat: null });
    if (D.clear) return go({ [D.clear]: null });
    if (D.arc) return go({ stage: S.stage === D.arc ? null : D.arc });
    if (D.seq) return go({ seq: S.seq === D.seq ? null : D.seq });
    if (D.node) {
      const inSeq = !!a.closest('#lc-seq');
      if (inSeq) return go({ seq: S.seq === 's:' + D.node ? null : 's:' + D.node });
      return go({ stage: S.stage === D.node ? null : D.node });
    }
    if (D.f === 'layer') return go({ layer: D.v === 'all' ? null : D.v });
    if (D.f === 'mode') return go({ mode: D.v === 'any' ? null : D.v });
    if (D.f === 'cell') return go({ layer: D.layer === 'all' ? null : D.layer, mode: null, stage: D.stage, tab: null });
    if (D.f === 'cell2') return go({ mode: D.mode, layer: null, stage: D.stage, tab: null });
    if (D.f === 'actor') return go({ actor: D.v === 'any' ? null : D.v });
    if (D.f === 'chk') return go({ chk: S.chk ? null : '1' });
    if (D.f === 'lim') return go({ lim: S.lim ? null : '1' });
    if (D.f === 'all') return go({ sstage: null, stage: null });
  });
  document.addEventListener('hub:theme', render);
  window.addEventListener('hashchange', () => { readHash(); render(); });
  readHash(); render();
});
