/* Overview page. Payloads: shell (slim works, prisma headline) and overview (lead, next actions,
   pipeline, composition, most cited, papers per month, sets). Every number comes from the payloads. */
HUB.load(['shell', 'overview']).then(d => {
  const H = HUB.init(d.shell);
  const O = d.overview;
  const main = H.mount({ page: 'overview', crumb: 'Overview' });
  const { esc, fmt, pct, LAYERS } = H;
  const W = H.RF.works;
  const CH = O.cited_here || {};
  const cic = id => (CH[id] || [0])[0];
  /* The drawer reads w.cic; the slim payload has none, so fill it from the overview payload. */
  W.forEach(w => { w.cic = cic(w.id); });

  if (!document.getElementById('ov-style')) {
    const st = document.createElement('style'); st.id = 'ov-style';
    st.textContent = `
.ov-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:40px;align-items:start;padding:20px 0 8px}
.ov-hero .lead{max-width:34ch;margin-top:18px}
.ov-hero .sec-head,.ov-panels .sec-head{margin:0}.ov-hero .lead .info{width:16px;height:16px}
.ov-next{display:flex;flex-direction:column;gap:6px}
.ov-next .btn{height:40px;justify-content:space-between;width:100%;text-decoration:none}
.ov-next .btn .n{font-family:var(--f-mono);font-size:var(--t-xs);opacity:.8}
.ov-todo{display:block;text-align:left;border:1px solid var(--hair);border-radius:var(--r,6px);padding:8px 12px;color:var(--fg);background:none;font:inherit;cursor:pointer}
.ov-wait{margin:8px 0 32px}.ov-waitgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-top:6px}
.ov-todo:hover{background:var(--raised)}
.ov-todo .row{display:flex;justify-content:space-between;gap:8px;font:400 var(--t-s) var(--f-ui)}
.ov-todo .cmd{display:block;margin-top:2px;color:var(--dim);font:400 var(--t-xs) var(--f-mono);overflow-wrap:anywhere}
.ov-strip{display:grid;grid-template-columns:repeat(5,1fr);margin:28px 0 8px}
.ov-step{padding:4px 18px 4px 0;margin-right:18px;border-right:1px solid var(--hair);color:inherit;text-decoration:none;display:block}
.ov-step:last-child{border-right:0;margin-right:0}
.ov-step:hover .big{color:var(--acc)}
.ov-step .big{font:500 28px/1.1 var(--f-ui);font-variant-numeric:tabular-nums}
.ov-step .bar{height:4px;background:var(--raised);border-radius:2px;margin:10px 0 8px;overflow:hidden}
.ov-step .bar i{display:block;height:100%;background:var(--mut)}
.ov-step.inc .bar i{background:var(--inc)}
.ov-step .loss{color:var(--exc);font:500 var(--t-s) var(--f-mono)}
.ov-step .loss.none{color:var(--dim)}
.ov-maphead{margin:36px 0 12px}.ov-maphead .sec-head{margin:0}
svg.ov-map{display:block;width:100%;height:auto}
svg.ov-map .pt{cursor:pointer;transition:opacity .12s}
svg.ov-map.dim .pt{opacity:.14}
svg.ov-map.dim .pt.nb{opacity:1}
svg.ov-map .halo{paint-order:stroke;stroke:var(--bg);stroke-width:3px;stroke-linejoin:round}
.ov-legend{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.ov-legend .chip{cursor:default}
.ov-panels{display:grid;grid-template-columns:1.1fr 1.25fr 1fr;gap:var(--gap);margin-top:36px}
.ov-panels .card{display:flex;flex-direction:column;gap:12px}
.ov-hb{display:grid;grid-template-columns:172px 1fr 72px;align-items:center;gap:8px;width:100%;background:none;border:0;color:var(--fg);font:400 var(--t-s) var(--f-ui);padding:3px 4px;border-radius:4px;cursor:pointer;text-align:left}
.ov-hb:hover{background:var(--raised)}
.ov-hb .tr{height:8px}.ov-hb .tr i{display:block;height:100%;border-radius:1px}
.ov-hb .v{text-align:right;font-family:var(--f-mono);font-size:var(--t-xs);color:var(--mut)}
.ov-grp{font:600 var(--t-xs) var(--f-ui);color:var(--mut);margin:6px 0 2px}
.ov-top td.ti{max-width:0;width:100%}
.ov-top .bar{display:inline-block;height:6px;background:var(--mut);border-radius:1px;vertical-align:middle;margin-right:8px}
.ov-top td:last-child{white-space:nowrap}
.ov-foot{margin-top:40px}
.ov-empty{color:var(--dim);font:400 var(--t-s) var(--f-ui)}
@media (max-width:1100px){.ov-hero{grid-template-columns:1fr}.ov-panels{grid-template-columns:1fr}.ov-strip{grid-template-columns:repeat(2,1fr);row-gap:20px}.ov-step:nth-child(2n){border-right:0}}
@media (max-width:760px){.ov-hb{grid-template-columns:112px 1fr 84px}.ov-hb .v{white-space:nowrap}.ov-hero .lead{font-size:22px}}`;
    document.head.appendChild(st);
  }

  const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const ym = m => MON[+m.slice(5) - 1] + ' ' + m.slice(0, 4);
  const mkey = w => w.year + '-' + String(w.month).padStart(2, '0');
  const months = (O.papers_per_month || {}).months || [];
  const mcounts = (O.papers_per_month || {}).counts || [];
  const comp = O.composition || { human: {}, layer: {} };
  const lead = O.lead || {};
  const hum = lead.human || {};
  const hTok = k => (H.HUMAN.find(h => h[0] === k) || [,, '--h-null'])[2];
  const hLab = k => k === 'null' ? 'Not coded' : H.humanLabel(k);
  const HORDER = [...H.HUMAN.map(h => h[0]), 'null'];
  const lTok = l => (LAYERS.find(x => x[0] === l) || [,, '--l-unlayered'])[2];
  const share = p => p >= 47 && p <= 53 ? 'Half' : p >= 30 && p <= 36 ? 'About a third' : p >= 22 && p <= 28 ? 'About a quarter' : p + '%';
  const sharePct = Math.round(100 * (hum.share_none || 0));

  /* ---- lead and next actions ---- */
  const GATE = {
    'documents-unconverted': 'Convert documents', 'version-pairs': 'Review version pairs',
  };
  const nextHtml = (O.next_actions || []).map(a =>
    `<button type="button" class="ov-todo" data-cmd="${esc(a.command || '')}" title="Click to copy the command">
      <span class="row"><span>${esc(GATE[a.gate] || H.pretty(a.gate))}</span><span class="n mono">${fmt(a.count)}</span></span>
      ${a.command ? `<span class="cmd">${esc(a.command)}</span>` : ''}</button>`).join('');

  main.innerHTML = `
<section class="ov-hero">
  <div>
    ${H.header({ kicker: `Living review · ${H.term('protocol')}`, title: H.pretty(H.RF.slug), level: 1 })}
    <p class="lead">${fmt(lead.included)} papers made it through ${H.term('screened', 'screening')}. ${hum.coded ? share(sharePct) + ' of the systems run with no human in the loop.' : ''}${H.info(`<b>What it shows</b>The headline result of the review so far.<p><span class=k>How it's computed.</span> ${fmt(lead.included)} is the number included in the screening flow, out of ${fmt(lead.identified)} records identified. The share is the ${fmt(hum.none)} papers with human role "none" divided by the ${fmt(hum.coded)} papers that have a human role coded (${fmt(hum.not_coded)} not coded are left out): ${sharePct}%.</p><p>${esc((O.methods || {}).human_role || '')}</p>`, 'How these figures are computed')}</p>
  </div>
  <nav class="ov-next" aria-label="Next actions">
    <a class="btn primary" href="corpus.html">Browse papers <span class="n">${fmt(lead.included)}</span></a>
    <a class="btn" href="flow.html">Open the flow <span class="n">${fmt(lead.identified)} → ${fmt(lead.included)}</span></a>
    <a class="btn" href="explore.html">Explore papers</a>
    <a class="btn" href="lenses.html">Lenses</a>
  </nav>
</section>
${nextHtml ? `<section class="ov-wait" aria-label="Waiting for you"><div class="ov-grp">Waiting for you</div><div class="ov-waitgrid">${nextHtml}</div></section>` : ''}

${H.header({ title: 'Where the records went', infoHtml: `<b>What it shows</b>How many records survive each screening step, and what each step removed.<p><span class=k>How to read it.</span> Each bar is the step's count as a share of the ${fmt(lead.identified)} records identified, drawn from zero. A red line is what that step removed.</p><p><span class=k>How it's computed.</span> Counts come from the screening flow; the arithmetic is checked on the <a href="flow.html">flow page</a>.</p>` })}
<section class="ov-strip" id="ovStrip" aria-label="Where the records went"></section>

<section>
  <div class="ov-maphead">
    ${H.header({ title: 'Papers over time', sub: '<span id="ovMapSub"></span>', infoHtml: `<b>What it shows</b>When each paper was published, and where it sits in the corpus.<p><span class=k>How to read it.</span> One dot per paper. Across: publication month. Down: layer band. Dot size: how often other papers here cite it. Hover a dot to see its title; click to open it.</p><p><span class=k>How it's computed.</span> ${esc((O.methods || {}).papers_per_month || '')} Dots are offset slightly within a month so they do not overlap. Band height is proportional to the square root of its count. An outlined dot is a paper with no layer.</p>` })}
  </div>
  <div class="card" style="padding:16px 12px 12px"><svg class="ov-map" id="ovMap" role="img" aria-label="Papers by month and layer"></svg></div>
  <div class="ov-legend" id="ovLegend" aria-label="Legend"></div>
</section>

<section class="ov-panels">
  <div class="card">${H.header({ title: 'What the corpus is made of', sub: `<span class="meta">${fmt(lead.included)} papers</span>`, infoHtml: `<b>What it shows</b>How the papers split by layer and by human role.<p><span class=k>How to read it.</span> All bars share one scale from zero. Click a bar to see its papers.</p><p><span class=k>How it's computed.</span> ${esc((O.methods || {}).composition || '')}</p>` })}<div id="ovComp"></div></div>
  <div class="card">${H.header({ title: 'Most cited', sub: `<span class="meta">${H.term('cic', 'Cited here')}, largest first</span>`, infoHtml: `<b>What it shows</b>The papers other papers in the corpus build on most.<p><span class=k>How it's computed.</span> ${esc((O.methods || {}).cited_here || '')}</p>` })}<div id="ovTop"></div></div>
  <div class="card">${H.header({ title: 'Growth', sub: '<span class="meta" id="ovGsub"></span>', infoHtml: `<b>What it shows</b>How many papers appeared each month.<p><span class=k>How it's computed.</span> ${esc((O.methods || {}).papers_per_month || '')} The last month is partial: data as of ${esc(H.RF.generated || '')}.</p>` })}<div id="ovGrowth"></div></div>
</section>
<p class="meta ov-foot" id="ovFoot"></p>`;

  /* click-to-copy for command hints */
  main.querySelectorAll('.ov-todo').forEach(b => b.onclick = () => { try { navigator.clipboard.writeText(b.dataset.cmd); } catch (e) { /* no clipboard */ } });

  /* ---- sets note, once, behind an info button ---- */
  (function () {
    const S = O.sets || {};
    const nRead = (S.read_in_full || []).length, nInc = (S.included || []).length;
    const parts = [];
    if ((S.duplicate_mapped || []).length) parts.push(`${fmt(S.duplicate_mapped.length)} duplicate records were read under their own id and are shown on the canonical record`);
    if ((S.mined_but_excluded || []).length) parts.push(`${fmt(S.mined_but_excluded.length)} papers were read but excluded at full text`);
    if ((S.not_read_yet || []).length) parts.push(`${fmt(S.not_read_yet.length)} included papers have not been read yet`);
    const panel = `<b>Two counts, one corpus</b><p>${parts.map(esc).join('; ')}${parts.length ? '.' : ''}</p><p><span class=k>How it's computed.</span> ${esc(S.methods || (O.methods || {}).sets || '')}</p>`;
    document.getElementById('ovFoot').innerHTML = `${H.info(panel, 'About the paper counts')} ${H.term('mined', 'Papers read in full')}: ${fmt(nRead)}; ${H.term('included', 'included')} by screening: ${fmt(nInc)}.`;
  })();

  /* ---- pipeline strip ---- */
  (function () {
    const LABEL = { identified: 'Identified', screened: 'Screened', sought: 'Full text sought', assessed: 'Assessed', included: 'Included' };
    const OF = { screened: 'identified', sought: 'passing title and abstract', assessed: 'sought', included: 'assessed' };
    const LOSS = {
      duplicates: () => H.term('duplicates') + ' removed', not_sought: () => 'not sought, ' + H.term('cap', 'rapid-review cap'),
      not_retrieved: () => H.term('notretrieved'), pending: () => 'pending', excluded_full_text: () => 'excluded at full text',
    };
    const pipe = O.pipeline || [];
    const top = (pipe[0] || {}).n || 1;
    document.getElementById('ovStrip').innerHTML = pipe.map(s => {
      const loss = Object.entries(s.loss || {});
      return `<a class="ov-step ${s.key === 'included' ? 'inc' : ''}" href="flow.html#node=${esc(s.key)}">
      <div class="meta">${esc(LABEL[s.key] || H.pretty(s.key))}</div><div class="big">${s.key === 'included' ? '+ ' : ''}${fmt(s.n)}</div>
      <div class="bar" title="${fmt(s.n)} of ${fmt(top)} identified"><i style="width:${Math.max(1.5, 100 * s.n / top)}%"></i></div>
      <div class="meta" style="margin-bottom:4px">${s.of != null ? 'of ' + fmt(s.of) + ' ' + OF[s.key] : '&nbsp;'}</div>
      ${loss.length ? loss.map(([k, v]) => `<div class="loss">− ${fmt(v)} ${(LOSS[k] || (() => esc(H.pretty(k))))()}</div>`).join('') : '<div class="loss none">no loss at this step</div>'}
    </a>`; }).join('');
  })();

  /* ---- map ---- */
  const BANDS = ['core', 'benchmark', 'applied', 'adjacent', 'other'];
  const bandOf = l => BANDS.includes(l) ? l : 'other';
  const BLAB = { core: 'Core', benchmark: 'Benchmark', applied: 'Applied', adjacent: 'Adjacent', other: 'Other' };
  const count = f => { const o = {}; W.forEach(w => { const k = f(w); o[k] = (o[k] || 0) + 1; }); return o; };
  const topW = (O.most_cited || []).map(m => W.find(w => w.id === m.id)).filter(Boolean);
  const hashf = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 10000) / 10000; };
  const svg = document.getElementById('ovMap');
  let L = null, LW = 0;
  const mIndex = new Map(months.map((m, i) => [m, i]));
  function layout(width, narrow) {
    const mL = narrow ? 8 : 112, mR = narrow ? 8 : 16, top = 4, axisH = 26, innerW = width - mL - mR, mw = innerW / Math.max(1, months.length);
    const cnt = count(w => bandOf(w.layer)); BANDS.forEach(b => cnt[b] = cnt[b] || 0);
    const tot = BANDS.reduce((a, b) => a + Math.sqrt(cnt[b]), 0) || 1, budget = narrow ? 1000 : 600;
    const Hh = BANDS.map(b => Math.max(narrow ? 46 : 52, Math.sqrt(cnt[b]) / tot * budget));
    const y0 = []; let acc = top; Hh.forEach(h => { y0.push(acc); acc += h + 6; });
    const R = w => (narrow ? 2.6 : 3.2) + (narrow ? 1.3 : 1.9) * Math.sqrt(cic(w.id));
    const nodes = [];
    BANDS.forEach((b, bi) => {
      const ns = W.filter(w => bandOf(w.layer) === b && mIndex.has(mkey(w))).map(w => {
        const x0 = mL + (mIndex.get(mkey(w)) + .15 + .7 * hashf(w.id)) * mw;
        return { w, r: R(w), x0, x: x0, y: y0[bi] + Hh[bi] * (.2 + .6 * hashf(w.id + 'y')), lo: y0[bi], hi: y0[bi] + Hh[bi] };
      });
      for (let it = 0; it < 260; it++) {
        for (let i = 0; i < ns.length; i++) {
          const a = ns[i];
          for (let j = i + 1; j < ns.length; j++) {
            const c = ns[j], dx = c.x - a.x, dy = c.y - a.y, dd = Math.hypot(dx, dy) || .01, m = a.r + c.r + .9;
            if (dd < m) { const k = (m - dd) / dd * .5; a.x -= dx * k; a.y -= dy * k; c.x += dx * k; c.y += dy * k; }
          }
        }
        ns.forEach(a => { a.x += (a.x0 - a.x) * .08; a.y = Math.min(a.hi - a.r, Math.max(a.lo + a.r, a.y)); a.x = Math.min(width - mR, Math.max(mL, a.x)); });
      }
      nodes.push(...ns);
    });
    return { nodes, y0, H: Hh, mL, mR, mw, totalH: acc + axisH, cnt, axisH };
  }
  const colorOf = w => `var(${lTok(w.layer)})`;
  const isHollow = w => w.layer === 'unlayered' || !LAYERS.some(l => l[0] === w.layer);
  function tipFor(id, e) {
    const w = H.byId.get(id); if (!w || !e) return;
    H.tipHtml(`<b>${esc(w.title)}</b><div class="meta">${ym(mkey(w))} · ${esc(H.layerLabel(w.layer))}<br>cited here ${fmt(cic(id))}×</div>`, e);
  }
  const unfocus = () => { svg.classList.remove('dim'); svg.querySelectorAll('.pt.nb').forEach(d => d.classList.remove('nb')); };
  function focus(id, e) {
    svg.classList.add('dim'); svg.querySelectorAll('.pt').forEach(d => d.classList.toggle('nb', d.dataset.id === id));
    tipFor(id, e);
  }
  function drawMap() {
    if (!months.length) { svg.parentElement.innerHTML = '<div class="ov-empty">The map appears once papers are included.</div>'; return; }
    const width = Math.max(320, Math.round(svg.parentElement.clientWidth - 24)), narrow = width < 640;
    if (!L || LW !== width) { L = layout(width, narrow); LW = width; }
    svg.setAttribute('viewBox', `0 0 ${width} ${L.totalH}`);
    let s = '';
    BANDS.forEach((b, i) => {
      const y = L.y0[i], h = L.H[i];
      s += `<rect x="${L.mL - 6}" y="${y}" width="${width - L.mL - L.mR + 12}" height="${h}" fill="var(--bg)" rx="6"/>`;
      if (!narrow) s += `<text x="${L.mL - 16}" y="${y + 16}" text-anchor="end" class="lbl">${BLAB[b]}</text><text x="${L.mL - 16}" y="${y + 31}" text-anchor="end" class="lbl-m">${fmt(L.cnt[b])} papers</text>`;
      else s += `<text x="${L.mL + 4}" y="${y + 14}" class="lbl-m"><tspan class="lbl" style="font-weight:600">${BLAB[b]}</tspan> ${fmt(L.cnt[b])}</text>`;
    });
    const ay = L.totalH - L.axisH;
    months.forEach((m, i) => {
      const mo = +m.slice(5), x = L.mL + (i + .5) * L.mw;
      if (narrow ? (mo === 1 || mo === 7) : (mo === 1 || mo === 4 || mo === 7 || mo === 10))
        s += `<line x1="${x}" x2="${x}" y1="${ay - 2}" y2="${ay + 3}" stroke="var(--dim)"/><text class="axis" x="${x}" y="${ay + 17}" text-anchor="middle" style="font-size:12px">${MON[mo - 1]}${mo === 1 ? ' ' + m.slice(0, 4) : ''}</text>`;
    });
    const pos = new Map(L.nodes.map(n => [n.w.id, n]));
    s += '<g id="ovDots">' + [...L.nodes].sort((a, b) => b.r - a.r).map(n => {
      const w = n.w, c = colorOf(w), hol = isHollow(w);
      return `<circle class="pt" data-id="${esc(w.id)}" data-c="${esc(w.layer)}" cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${n.r.toFixed(1)}" fill="${hol ? 'none' : c}" stroke="${hol ? c : 'var(--bg)'}" stroke-width="${hol ? 1.4 : .6}" ${topW.includes(w) ? 'tabindex="0" role="button" aria-label="' + esc(w.title) + '"' : ''}/>`;
    }).join('') + '</g>';
    const placed = []; let lb = '';
    topW.slice(0, narrow ? 3 : 6).forEach(w => {
      const n = pos.get(w.id); if (!n) return;
      const left = n.x > width * .6;
      let short = w.title.split(/[:–—]/)[0].replace(/^(The |A |An )/, ''); if (short.length > 26) { short = short.slice(0, 26); short = short.slice(0, short.lastIndexOf(' ')) + '…'; }
      const tw = short.length * 6.6 + 28, x = left ? n.x - n.r - 6 : n.x + n.r + 6, y = n.y + 4, box = [left ? x - tw : x, y - 13, left ? x : x + tw, y + 5];
      if (placed.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) return; placed.push(box);
      lb += `<text class="lbl halo" x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${left ? 'end' : 'start'}">${esc(short)} <tspan class="lbl-m">${fmt(cic(w.id))}</tspan></text>`;
    });
    s += `<g pointer-events="none">${lb}</g>`;
    svg.innerHTML = s;
    svg.querySelectorAll('.pt').forEach(dd => {
      dd.addEventListener('mouseenter', e => focus(dd.dataset.id, e)); dd.addEventListener('mousemove', e => tipFor(dd.dataset.id, e));
      dd.addEventListener('mouseleave', () => { unfocus(); H.tipHtml(null); });
      dd.addEventListener('focus', () => focus(dd.dataset.id)); dd.addEventListener('blur', unfocus);
      dd.addEventListener('click', () => H.openDrawer(dd.dataset.id));
      dd.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); H.openDrawer(dd.dataset.id); } });
    });
  }
  function drawLegend() {
    const lg = document.getElementById('ovLegend'), dl = count(w => w.layer);
    lg.innerHTML = LAYERS.filter(l => dl[l[0]]).map(([k, l, t]) => `<span class="chip" data-c="${k}"><span class="dot" style="${k === 'unlayered' ? 'border:1.5px solid var(--l-unlayered)' : `background:var(${t})`}"></span>${l} <span class="n">${fmt(dl[k])}</span></span>`).join('');
    lg.querySelectorAll('.chip').forEach(c => {
      c.addEventListener('mouseenter', () => { svg.classList.add('dim'); svg.querySelectorAll('.pt').forEach(dd => dd.classList.toggle('nb', dd.dataset.c === c.dataset.c)); });
      c.addEventListener('mouseleave', unfocus);
    });
  }
  document.getElementById('ovMapSub').textContent = `${fmt(W.length)} papers, coloured by layer; size shows how often each is cited here.`;
  drawMap(); drawLegend();
  document.addEventListener('hub:theme', () => { drawMap(); drawLegend(); });
  let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(() => { LW = 0; drawMap(); }, 150); });

  /* ---- panels ---- */
  (function () {
    const dh = comp.human || {}, dl = comp.layer || {};
    const mx = Math.max(1, ...Object.values(dh), ...Object.values(dl));
    const tot = lead.included || W.length;
    const row = (lab, n, tok, hol, href) => `<button class="ov-hb" data-href="${esc(href)}"><span>${esc(lab)}</span><span class="tr"><i style="width:${100 * n / mx}%;${hol ? `box-shadow:inset 0 0 0 1.5px var(${tok})` : `background:var(${tok})`}"></i></span><span class="v">${fmt(n)} · ${pct(n, tot)}%</span></button>`;
    document.getElementById('ovComp').innerHTML =
      `<div class="ov-grp">Layer</div>` + LAYERS.filter(l => dl[l[0]]).map(([k, l, t]) => row(l, dl[k], t, k === 'unlayered', `corpus.html#layer=${k}`)).join('') +
      `<div class="ov-grp" style="margin-top:12px">Human role</div>` + HORDER.filter(k => dh[k]).map(k => row(hLab(k), dh[k], hTok(k), k === 'null', `corpus.html#human=${k}`)).join('');
    document.querySelectorAll('#ovComp .ov-hb').forEach(b => b.onclick = () => { location.href = b.dataset.href; });

    const mc = Math.max(1, ...(O.most_cited || []).map(m => m.cited_here));
    document.getElementById('ovTop').innerHTML = (O.most_cited || []).length
      ? `<table class="t ov-top"><tbody>${O.most_cited.map(m => `<tr tabindex="0" data-id="${esc(m.id)}"><td class="ti"><span class="dot" style="background:var(${lTok(m.layer)});margin-right:6px"></span>${esc(m.title.length > 74 ? m.title.slice(0, 72) + '…' : m.title)}</td><td class="r"><span class="bar" style="width:${Math.round(70 * m.cited_here / mc)}px"></span>${fmt(m.cited_here)}</td></tr>`).join('')}</tbody></table>`
      : '<div class="ov-empty">Citation counts appear once reference lists are extracted.</div>';
    document.querySelectorAll('#ovTop tr').forEach(r => { r.onclick = () => H.openDrawer(r.dataset.id); r.onkeydown = e => { if (e.key === 'Enter') H.openDrawer(r.dataset.id); }; });

    const g = document.getElementById('ovGrowth');
    if (!months.length) { g.innerHTML = '<div class="ov-empty">Growth appears once papers are included.</div>'; return; }
    const vm = Math.max(1, ...mcounts), iM = mcounts.indexOf(vm), busy = O.papers_per_month.busiest || { month: months[iM], n: vm };
    const W2 = 420, H2 = 230, bw = W2 / mcounts.length;
    document.getElementById('ovGsub').textContent = `Busiest ${ym(busy.month)} (${fmt(busy.n)} papers); ${ym(months[months.length - 1])} is partial.`;
    g.innerHTML = `<svg viewBox="0 0 ${W2} ${H2 + 24}" style="width:100%;display:block" role="img" aria-label="Papers by publication month">` +
      [0, vm / 2, vm].map(v => `<line class="gridline" x1="0" x2="${W2}" y1="${H2 - H2 * v / vm}" y2="${H2 - H2 * v / vm}"/>`).join('') +
      mcounts.map((v, i) => `<rect class="gb" data-m="${months[i]}" data-n="${v}" x="${(i * bw + 1).toFixed(1)}" y="${(H2 - H2 * v / vm).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(H2 * v / vm).toFixed(1)}" fill="var(--mut)" ${i === mcounts.length - 1 ? 'fill-opacity=".45"' : ''}/>`).join('') +
      `<text class="axis" x="0" y="${H2 + 16}">${ym(months[0])}</text><text class="axis" x="${W2}" y="${H2 + 16}" text-anchor="end">${ym(months[months.length - 1])}</text><text class="lbl" x="${(iM * bw + bw / 2).toFixed(1)}" y="${(H2 - H2 * vm / vm - 4).toFixed(1)}" text-anchor="middle">${fmt(vm)}</text></svg>`;
    g.querySelectorAll('.gb').forEach(r => {
      r.addEventListener('mousemove', e => H.tipHtml(`<b>${ym(r.dataset.m)}</b><br>${fmt(+r.dataset.n)} papers`, e)); r.addEventListener('mouseleave', () => H.tipHtml(null));
      r.style.cursor = 'pointer'; r.onclick = () => { location.href = 'corpus.html#year=' + r.dataset.m.slice(0, 4); };
    });
  })();
}).catch(e => {
  document.body.textContent = 'Overview failed to load: ' + e.message;
});
