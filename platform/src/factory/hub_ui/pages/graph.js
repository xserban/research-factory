/* Graph page: six views of how the papers cite each other. Every number comes from the `graph` payload
   (services/hub_graph.graph_payload); titles, layers and dates of corpus papers come from the shell.
   The landscape layout is presentation only: a Fruchterman-Reingold pass from a seeded generator with a
   fixed iteration count, so the same data always gives the same picture. */
HUB.load(['shell', 'graph']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'graph', crumb: 'Graph' });
  const G = d.graph, esc = H.esc, fmt = H.fmt, T = H.term, cv = H.cssv, BY = H.byId;
  const M = G.methods || {}, LAND = G.landscape;

  if (!document.getElementById('graph-css')) {
    const s = document.createElement('style'); s.id = 'graph-css';
    s.textContent = `
.gtabs{margin:16px 0 18px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.gtabs .seg{flex-wrap:wrap}
.gp{padding:24px}
.gp .sec-head{margin:0}
.gp .lead{max-width:62ch;font-size:24px;margin-top:12px}
.gp .ctl{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:16px 0 8px}
.empty{color:var(--mut);padding:14px 0;font-size:var(--t-s)}
.gland{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start}
.gstage{position:relative;background:var(--bg);border-radius:var(--r);overflow:hidden}
.gstage canvas{display:block;width:100%;height:640px;cursor:grab;touch-action:none}
.gstage canvas:active{cursor:grabbing}
.gzoom{position:absolute;right:10px;top:10px;display:flex;flex-direction:column;gap:4px}
.gzoom .btn{height:30px;width:30px;padding:0;justify-content:center}
.gstat{position:absolute;left:12px;top:10px;font-size:var(--t-xs);color:var(--mut)}
.gcard{position:absolute;left:12px;bottom:12px;max-width:320px;background:var(--surface);border-radius:var(--r);padding:12px 14px;box-shadow:var(--shadow);font-size:var(--t-s)}
.gcard b{display:block;margin-bottom:4px;font-weight:600}
.gcard .x{position:absolute;right:6px;top:4px;background:none;border:0;color:var(--mut);cursor:pointer;font-size:16px}
.rank{list-style:none;margin:8px 0 0;padding:0;max-height:560px;overflow:auto;display:flex;flex-direction:column;gap:1px}
.rank button{all:unset;display:block;cursor:pointer;padding:6px 8px;border-radius:6px;font-size:13px;line-height:1.35;width:calc(100% - 16px)}
.rank button:hover{background:var(--raised)}
.rank button:focus-visible{outline:2px solid var(--acc)}
.rank .e{color:var(--mut);display:block;font-size:12px}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--mut)}
.legend span{display:inline-flex;gap:6px;align-items:center}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block;flex:none}
.frow{display:grid;grid-template-columns:28px minmax(0,1fr) 220px auto;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--hair)}
.frow .rk{color:var(--dim);font-family:var(--f-mono);font-size:12px;text-align:right}
.frow .nm{font-size:14px;line-height:1.35}
.frow .nm .meta{display:block}
.fbar{height:8px;border-radius:4px;background:var(--raised);position:relative}
.fbar i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--acc)}
.fbar+.meta{margin-top:3px}
details.cit{grid-column:2 / -1;font-size:var(--t-s)}
details.cit summary{cursor:pointer;color:var(--acc);width:max-content}
details.cit ul{list-style:none;margin:8px 0 0;padding:0;columns:2 340px;column-gap:24px}
details.cit li{break-inside:avoid;margin:0 0 4px}
button.lnk{background:none;border:0;color:var(--acc);font:inherit;text-decoration:underline;text-underline-offset:3px;cursor:pointer;padding:0;text-align:left}
.schools{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:8px}
.school{background:var(--raised);border-radius:var(--r);padding:16px;text-align:left;border:0;color:var(--fg);font:inherit;cursor:pointer;display:flex;flex-direction:column;gap:8px}
.school:hover{background:var(--line)}
.school[aria-pressed=true]{box-shadow:inset 0 0 0 2px var(--acc)}
.school.un{background:transparent;box-shadow:inset 0 0 0 1px var(--line)}
.school svg{align-self:center;margin:4px 0}
.school .ttl{font-weight:600;font-size:15px}
.school ol{margin:0;padding-left:18px;font-size:12px;color:var(--mut)}
.listpanel{margin-top:16px;padding:20px 24px}
.hbar{display:flex;height:26px;border-radius:var(--r-s);overflow:hidden;margin:14px 0 6px}
.hbar i{display:block;height:100%}
.hrow{display:grid;grid-template-columns:minmax(0,1fr) 260px 60px;gap:12px;align-items:center;padding:7px 0;border-bottom:1px solid var(--hair);cursor:pointer;font-size:13px}
.hrow:hover{background:var(--raised)}
.hrow .mini{display:flex;height:10px;border-radius:3px;overflow:hidden;background:var(--raised)}
.hrow .mini i{display:block;height:100%}
.hrow .num{text-align:right;color:var(--mut)}
.scrollx{overflow-x:auto;overflow-y:hidden}
svg text{user-select:none;font-family:var(--f-ui)}
.halo{paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
@media (max-width:1100px){.gland{grid-template-columns:minmax(0,1fr)}}
@media (max-width:760px){
  .gp{padding:16px}.gp .lead{font-size:20px}.gstage canvas{height:460px}
  .frow{grid-template-columns:24px minmax(0,1fr)}.frow .fb{grid-column:2}.frow .btn{grid-column:2;width:max-content}
  .hrow{grid-template-columns:minmax(0,1fr) 90px 44px}
}`;
    document.head.appendChild(s);
  }

  /* ---------- helpers ---------- */
  const NS = 'http://www.w3.org/2000/svg';
  const mk = (tag, a = {}, par) => { const e = document.createElementNS(NS, tag); for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]); if (par) par.appendChild(e); return e; };
  const tx = (par, x, y, t, a = {}) => { const e = mk('text', { x, y, 'font-size': 11.5, ...a }, par); e.textContent = t; return e; };
  const infoPanel = (what, read, comp) => `<b>What it shows</b> ${what}<p><span class=k>How to read it.</span> ${read}</p><p><span class=k>How it’s computed.</span> ${comp}</p>`;
  const meth = k => esc(M[k] || '');
  const short = (s, n) => s.length > n ? s.slice(0, n - 1).trim() + '…' : s;
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const wrap = (t, n) => { const out = []; let cur = ''; for (const w of t.split(' ')) { if ((cur + ' ' + w).trim().length > n && cur) { out.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); } if (cur) out.push(cur); return out; };
  const reduced = () => matchMedia('(prefers-reduced-motion:reduce)').matches;
  const pcs = (a, b) => b ? Math.round(100 * a / b) : 0;
  const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  /* a readable name for any work: the corpus title, else the person-and-words part of its id (payload carries no title for outside works) */
  function nm(id) {
    const w = BY.get(id); if (w) return w.title;
    const s = String(id).replace(/^rf:/, '').replace(/-[0-9a-f]{8}$/, '');
    const m = s.match(/^(\D*?)(\d{4})(?:\d{4})?-(.*)$/);
    return m ? cap(m[3].replace(/-/g, ' ')) + (m[1] ? ' (' + cap(m[1]) + ' ' + m[2] + ')' : ' (' + m[2] + ')') : cap(s.replace(/-/g, ' '));
  }
  const layerOf = id => (BY.get(id) || {}).layer;
  const lcol = id => H.layerColor(layerOf(id));
  const mon = w => w ? (w.year || 0) * 12 + ((w.month || 1) - 1) : null;
  const isoMon = s => s ? (+s.slice(0, 4)) * 12 + (s.length >= 7 ? +s.slice(5, 7) - 1 : 0) : null;
  const corpusN = H.RF.works.length;
  const nLabel = n => n === 1 ? '1 work' : fmt(n) + ' works';

  /* ---------- tabs ---------- */
  const TABS = [['landscape', 'Landscape'], ['foundations', 'Foundations'], ['schools', 'Schools'], ['path', 'Main path'], ['river', 'River'], ['health', 'Reference health']];
  const build = {};

  /* ================= 1. Landscape ================= */
  const LS = { nodes: null, pos: null, edges: null, done: false, running: false, view: { k: 1, x: 0, y: 0 }, fitted: false, hover: -1, selected: null };
  let cvs = null, ctx = null, stageEl = null;

  function prepLand() {
    if (LS.nodes) return;
    const idx = new Map(); LS.nodes = LAND.nodes.map((n, i) => (idx.set(n.id, i), n));
    LS.edges = LAND.edges.map(([a, b]) => [idx.get(a), idx.get(b)]).filter(([a, b]) => a != null && b != null);
    LS.idx = idx;
    LS.adj = LS.nodes.map(() => []); LS.edges.forEach(([a, b]) => { LS.adj[a].push(b); LS.adj[b].push(a); });
    LS.rad = LS.nodes.map(n => (n.in_corpus ? 4 : 2) + Math.sqrt(n.in_degree || 0) * 1.15);
    const n = LS.nodes.length; LS.pos = new Float64Array(2 * n);
    /* seeded start: clusters on a ring, jittered; mulberry32 so the picture is reproducible */
    let s = 20261118 >>> 0; const rnd = () => { s = (s + 0x6D2B79F5) >>> 0; let t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    const cl = [...new Set(LS.nodes.map(x => x.cluster).filter(Boolean))].sort();
    const R0 = Math.sqrt(n) * 30;
    LS.nodes.forEach((x, i) => {
      const ci = x.cluster ? cl.indexOf(x.cluster) : -1, a0 = ci < 0 ? rnd() * 6.283 : ci / Math.max(cl.length, 1) * 6.283;
      const r = (ci < 0 ? 1.1 : 0.45) * R0 * Math.sqrt(rnd()), a = a0 + (rnd() - .5) * (ci < 0 ? 6.283 : 1.5);
      LS.pos[2 * i] = Math.cos(a) * r; LS.pos[2 * i + 1] = Math.sin(a) * r;
    });
    LS.iter = 0; LS.ITER = n > 3000 ? 90 : 170; LS.k = Math.sqrt(n * 900 * 0.9 / n) * 3.2; LS.t0 = R0 / 6;
  }
  /* one Fruchterman-Reingold iteration; displacement buffer reused */
  function step() {
    const n = LS.nodes.length, P = LS.pos, k = LS.k, k2 = k * k, D = LS.D || (LS.D = new Float64Array(2 * n));
    D.fill(0);
    for (let i = 0; i < n; i++) {
      const xi = P[2 * i], yi = P[2 * i + 1]; let dx_ = 0, dy_ = 0;
      for (let j = i + 1; j < n; j++) {
        let dx = xi - P[2 * j], dy = yi - P[2 * j + 1], d2 = dx * dx + dy * dy;
        if (d2 > 90000) continue;
        if (d2 < 0.01) { dx = ((i * 7 + j) % 13 - 6) * .01; dy = ((i + j * 5) % 11 - 5) * .01; d2 = dx * dx + dy * dy + .01; }
        const f = k2 / d2; dx_ += dx * f; dy_ += dy * f; D[2 * j] -= dx * f; D[2 * j + 1] -= dy * f;
      }
      D[2 * i] += dx_; D[2 * i + 1] += dy_;
    }
    for (const [a, b] of LS.edges) {
      const dx = P[2 * a] - P[2 * b], dy = P[2 * a + 1] - P[2 * b + 1], d = Math.sqrt(dx * dx + dy * dy) + .01, f = d / k * .9;
      D[2 * a] -= dx * f; D[2 * a + 1] -= dy * f; D[2 * b] += dx * f; D[2 * b + 1] += dy * f;
    }
    const t = LS.t0 * (1 - LS.iter / LS.ITER) + 0.5;
    for (let i = 0; i < n; i++) {
      let dx = D[2 * i] - P[2 * i] * 0.04, dy = D[2 * i + 1] - P[2 * i + 1] * 0.04; const d = Math.sqrt(dx * dx + dy * dy) || 1, m = Math.min(d, t) / d;
      P[2 * i] += dx * m; P[2 * i + 1] += dy * m;
    }
    LS.iter++;
  }
  function runLayout() {
    if (LS.running || LS.done) return;
    LS.running = true; const t0 = performance.now();
    const finish = () => { LS.done = true; LS.running = false; LS.ms = Math.round(performance.now() - t0); console.log('graph-layout ms', LS.ms, 'nodes', LS.nodes.length, 'edges', LS.edges.length, 'iterations', LS.ITER); fit(); paintLand(); const st = document.getElementById('gstat'); if (st) st.textContent = ''; };
    if (reduced()) { while (LS.iter < LS.ITER) step(); finish(); return; }
    const chunk = () => {
      const t1 = performance.now();
      while (LS.iter < LS.ITER && performance.now() - t1 < 12) step();
      if (!LS.userView) fit();
      paintLand();
      const st = document.getElementById('gstat'); if (st) st.textContent = LS.iter < LS.ITER ? 'Arranging… ' + Math.round(100 * LS.iter / LS.ITER) + '%' : '';
      if (LS.iter < LS.ITER) requestAnimationFrame(chunk); else finish();
    };
    requestAnimationFrame(chunk);
  }
  function fit() {
    if (!cvs) return; const P = LS.pos, n = LS.nodes.length;
    /* frame the dense core: the 2nd to 98th percentile of positions, so a few far outliers do not shrink the picture */
    const xs = [], ys = []; for (let i = 0; i < n; i++) { xs.push(P[2 * i]); ys.push(P[2 * i + 1]); }
    xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
    const lo = Math.floor(n * .02), hi = Math.ceil(n * .98) - 1, x0 = xs[lo], x1 = xs[hi], y0 = ys[lo], y1 = ys[hi];
    const W = cvs.clientWidth, Hh = cvs.clientHeight, k = Math.min(W / ((x1 - x0) || 1), Hh / ((y1 - y0) || 1)) * .92;
    LS.view = { k, x: W / 2 - (x0 + x1) / 2 * k, y: Hh / 2 - (y0 + y1) / 2 * k };
  }
  function paintLand() {
    if (!cvs || !ctx) return;
    const dpr = devicePixelRatio || 1, W = cvs.clientWidth, Hh = cvs.clientHeight;
    if (cvs.width !== Math.round(W * dpr) || cvs.height !== Math.round(Hh * dpr)) { cvs.width = Math.round(W * dpr); cvs.height = Math.round(Hh * dpr); }
    const v = LS.view, P = LS.pos, N = LS.nodes, hv = LS.hover, sel = LS.selected;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, Hh);
    ctx.setTransform(dpr * v.k, 0, 0, dpr * v.k, dpr * v.x, dpr * v.y);
    const lw = 1 / v.k, mut = cv('--mut'), dim = cv('--dim');
    const focus = hv >= 0 ? hv : (sel != null ? sel : -1), nb = focus >= 0 ? new Set(LS.adj[focus]) : null;
    ctx.lineWidth = lw; ctx.strokeStyle = mut; ctx.globalAlpha = focus >= 0 ? .05 : .085; ctx.beginPath();
    for (const [a, b] of LS.edges) { ctx.moveTo(P[2 * a], P[2 * a + 1]); ctx.lineTo(P[2 * b], P[2 * b + 1]); } ctx.stroke();
    if (focus >= 0) { ctx.globalAlpha = .75; ctx.strokeStyle = cv('--acc'); ctx.lineWidth = 1.4 * lw; ctx.beginPath(); for (const j of LS.adj[focus]) { ctx.moveTo(P[2 * focus], P[2 * focus + 1]); ctx.lineTo(P[2 * j], P[2 * j + 1]); } ctx.stroke(); }
    const cache = {}; const col = n => n.in_corpus ? (cache[layerOf(n.id)] ||= H.layerColor(layerOf(n.id))) : dim;
    const draw = (corpus) => { for (let i = 0; i < N.length; i++) { const n = N[i]; if (n.in_corpus !== corpus) continue;
      ctx.globalAlpha = corpus ? (nb && i !== focus && !nb.has(i) ? .35 : .95) : (nb && !nb.has(i) && i !== focus ? .1 : .38);
      ctx.fillStyle = col(n); ctx.beginPath(); ctx.arc(P[2 * i], P[2 * i + 1], LS.rad[i], 0, 6.2832); ctx.fill(); } };
    draw(false); draw(true);
    ctx.globalAlpha = 1;
    if (focus >= 0) { ctx.strokeStyle = cv('--fg'); ctx.lineWidth = 2 * lw; ctx.beginPath(); ctx.arc(P[2 * focus], P[2 * focus + 1], LS.rad[focus] + 2 * lw, 0, 6.2832); ctx.stroke(); }
  }
  function pickNode(px, py) {
    const v = LS.view, wx = (px - v.x) / v.k, wy = (py - v.y) / v.k, P = LS.pos; let best = -1, bd = Infinity;
    for (let i = 0; i < LS.nodes.length; i++) { const dx = P[2 * i] - wx, dy = P[2 * i + 1] - wy, d = Math.sqrt(dx * dx + dy * dy) - LS.rad[i]; if (d < Math.max(3 / v.k, 0) && d < bd) { bd = d; best = i; } }
    return best;
  }
  const nodeTip = i => { const n = LS.nodes[i], w = BY.get(n.id); return `<b>${esc(nm(n.id))}</b><br>${n.in_corpus ? esc(H.layerLabel(w && w.layer)) + ' · ' : 'Outside the corpus · '}${esc(n.year ?? 'year unknown')} · cited by ${fmt(n.in_degree)} corpus ${n.in_degree === 1 ? 'work' : 'works'}`; };
  function chooseNode(i) {
    LS.selected = i; const n = LS.nodes[i], card = document.getElementById('gcard'); paintLand();
    if (n.in_corpus) { if (card) card.hidden = true; H.openDrawer(n.id); return; }
    if (!card) return;
    card.hidden = false;
    card.innerHTML = `<button class="x" aria-label="Close" type="button">×</button><b>${esc(nm(n.id))}</b><span class="meta">Outside the corpus · ${esc(n.year ?? 'year unknown')}</span><br>Cited by ${fmt(n.in_degree)} corpus ${n.in_degree === 1 ? 'work' : 'works'}.`;
    card.querySelector('.x').onclick = () => { card.hidden = true; LS.selected = null; paintLand(); };
  }
  function wireCanvas(stage) {
    let drag = null, moved = false;
    const rect = e => { const r = cvs.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    cvs.addEventListener('pointerdown', e => { cvs.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY, vx: LS.view.x, vy: LS.view.y }; moved = false; });
    cvs.addEventListener('pointermove', e => {
      if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) moved = true; if (moved) { LS.userView = true; LS.view.x = drag.vx + dx; LS.view.y = drag.vy + dy; H.tip(null); paintLand(); } return; }
      if (!LS.done && LS.running) return;
      const [px, py] = rect(e), i = pickNode(px, py);
      if (i !== LS.hover) { LS.hover = i; paintLand(); }
      if (i >= 0) H.tip(nodeTip(i), e); else H.tip(null);
    });
    cvs.addEventListener('pointerup', e => { if (drag && !moved) { const [px, py] = rect(e), i = pickNode(px, py); if (i >= 0) chooseNode(i); } drag = null; });
    cvs.addEventListener('pointerleave', () => { H.tip(null); if (LS.hover >= 0) { LS.hover = -1; paintLand(); } });
    const zoom = (f, cx, cy) => { const v = LS.view, k = Math.min(Math.max(v.k * f, .1), 30), r = k / v.k; LS.userView = true; v.x = cx - (cx - v.x) * r; v.y = cy - (cy - v.y) * r; v.k = k; paintLand(); };
    cvs.addEventListener('wheel', e => { e.preventDefault(); const [px, py] = rect(e); zoom(e.deltaY < 0 ? 1.2 : 1 / 1.2, px, py); }, { passive: false });
    stage.querySelectorAll('[data-z]').forEach(b => b.onclick = () => { if (b.dataset.z === '0') { LS.userView = false; fit(); paintLand(); } else zoom(+b.dataset.z, cvs.clientWidth / 2, cvs.clientHeight / 2); });
  }
  build.landscape = () => {
    const N = LAND.nodes, nIn = N.filter(n => n.in_corpus).length, nOut = N.length - nIn;
    const topOut = N.filter(n => !n.in_corpus).sort((a, b) => b.in_degree - a.in_degree || a.id.localeCompare(b.id))[0];
    const ranked = [...N].sort((a, b) => b.in_degree - a.in_degree || a.id.localeCompare(b.id)).slice(0, 40);
    return {
      title: 'Landscape',
      info: infoPanel('The citation network around the corpus: every paper of the review, and the outside works that several of them cite.',
        'Bright dots are corpus papers, coloured by ' + T('layer', 'layer') + '. Faint dots are outside works. A bigger dot is cited by more corpus papers. Lines are citations. Drag to pan, scroll or use + and − to zoom. Hover a dot to see its neighbours; click it to open it. The ranked list is the keyboard route to the same dots.',
        `${meth('landscape')} Position is presentation only: the layout runs in your browser from a fixed seed, so the same data gives the same picture, and distance carries no further meaning.`),
      lead: `The corpus is a dense web of <b>${fmt(nIn)}</b> papers resting on <b>${fmt(nOut)}</b> outside works${topOut ? `; the most cited one is cited by <b>${fmt(topOut.in_degree)}</b> of them` : ''}.`,
      body: `<div class="gland"><div><div class="gstage" id="gstage"><canvas id="gcv" role="img" aria-label="Citation network, ${fmt(N.length)} works"></canvas><div class="gstat" id="gstat">Arranging…</div>
        <div class="gzoom"><button class="btn" data-z="1.4" aria-label="Zoom in">+</button><button class="btn" data-z="0.714" aria-label="Zoom out">−</button><button class="btn" data-z="0" aria-label="Fit all" title="Fit all">⤢</button></div>
        <div class="gcard" id="gcard" hidden></div></div>
        <div class="legend">${H.LAYERS.slice(0, 5).map(l => `<span><i class="dot" style="background:${cv(l[2])}"></i>${esc(l[1])}</span>`).join('')}<span><i class="dot" style="background:var(--dim);opacity:.6"></i>Outside the corpus</span><span class="meta">Dot area: cited by corpus works</span></div>
        <p class="meta" style="margin-top:8px">${LAND.hidden_nodes ? `${fmt(LAND.hidden_nodes)} outside works cited by fewer than ${fmt(LAND.ring_min)} corpus works are not drawn.` : ''} <button class="btn" id="showAllRing" disabled title="${LAND.full ? 'Everything is shown' : 'Available in the live hub'}">Show all</button></p></div>
        <aside><h3 class="h3">Most cited ${H.info('The works drawn here, ranked by how many corpus papers cite them. Pick one to open it.', 'About the ranked list')}</h3>
        <ol class="rank" aria-label="Ranked works">${ranked.map(n => `<li><button type="button" data-node="${esc(n.id)}">${esc(short(nm(n.id), 80))}<span class="e">${n.in_corpus ? esc(H.layerLabel(layerOf(n.id))) : 'Outside'} · ${esc(n.year ?? '')} · cited by ${fmt(n.in_degree)}</span></button></li>`).join('')}</ol></aside></div>`,
      draw() {
        prepLand(); stageEl = document.getElementById('gstage'); cvs = document.getElementById('gcv'); ctx = cvs.getContext('2d');
        wireCanvas(stageEl);
        main.querySelectorAll('[data-node]').forEach(b => b.onclick = () => { const i = LS.idx.get(b.dataset.node); if (i != null) chooseNode(i); });
        if (!LS.userView) fit(); paintLand(); runLayout();
      },
    };
  };

  /* ================= 2. Foundations ================= */
  const openWork = id => { if (BY.has(id)) H.openDrawer(id); };
  build.foundations = () => {
    const F = G.foundations, top = F[0];
    return {
      title: 'Foundations',
      info: infoPanel('The outside works that the most corpus papers lean on.',
        'The bar is the share of corpus papers that cite the work. Open the citing papers to see who builds on it.',
        `${meth('foundations')} The list keeps the top ${fmt(F.length)}.`),
      lead: top ? `The most leaned-on outside work, “${esc(short(nm(top.id), 70))}”, is cited by <b>${fmt(top.count)}</b> corpus papers, <b>${pcs(top.count, corpusN)}%</b> of the corpus.` : '',
      body: F.length ? F.map((f, i) => `<div class="frow"><span class="rk">${i + 1}</span><div class="nm">${esc(nm(f.id))}<span class="meta">Outside the corpus</span></div>
        <div class="fb"><div class="fbar" role="img" aria-label="${pcs(f.count, corpusN)}% of the corpus"><i style="width:${(f.share * 100).toFixed(1)}%"></i></div><div class="meta">${pcs(f.count, corpusN)}% of the corpus</div></div>
        <button class="btn" disabled title="Available in the live hub">Add to snowball</button>
        <details class="cit"><summary>Citing papers (${fmt(f.citing.length)})</summary><ul>${f.citing.map(c => BY.has(c) ? `<li><button type="button" class="lnk" data-open="${esc(c)}">${esc(short(nm(c), 90))}</button></li>` : '').join('')}</ul></details></div>`).join('') : '<p class="empty">No outside works are cited yet.</p>',
    };
  };

  /* ================= 3. Schools ================= */
  const LORDER = H.LAYERS.map(l => l[0]);
  build.schools = (p) => {
    const S = G.schools.filter(s => s.id !== 'unclustered').sort((a, b) => b.size - a.size), U = G.schools.find(s => s.id === 'unclustered');
    const sel = p.get('school'), cur = G.schools.find(s => s.id === sel);
    const biggest = S[0];
    const card = (s, un) => {
      const mem = [...s.members].sort((a, b) => LORDER.indexOf(layerOf(a)) - LORDER.indexOf(layerOf(b)) || a.localeCompare(b));
      const c = 3.9, R = Math.ceil(c * Math.sqrt(mem.length) * 1.2) + 6, sz = Math.max(40, 2 * R);
      const dots = mem.map((id, i) => { const r = c * Math.sqrt(i + .5), a = i * 2.39996; return `<circle cx="${(R + Math.cos(a) * r).toFixed(1)}" cy="${(R + Math.sin(a) * r).toFixed(1)}" r="2.4" fill="${lcol(id)}"/>`; }).join('');
      const name = s.dominant_label ? H.pretty(s.dominant_label) : 'Mixed';
      return `<button type="button" class="school${un ? ' un' : ''}" data-school="${esc(s.id)}" aria-pressed="${s.id === sel}">
        <span class="ttl">${un ? 'Not grouped' : esc(name)}</span><span class="meta">${nLabel(s.size).replace('works', 'papers').replace('work', 'paper')}${s.dominant_label ? ` · ${Math.round(s.dominant_share * 100)}% ${esc(un ? 'mostly ' : '')}${esc(name.toLowerCase())}` : ''}</span>
        <svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" aria-hidden="true">${dots}</svg>
        ${s.top_refs.length ? `<span class="meta">Most shared references</span><ol>${s.top_refs.slice(0, 3).map(([id, n]) => `<li>${esc(short(nm(id), 60))} <span class="num">${fmt(n)}</span></li>`).join('')}</ol>` : '<span class="meta">No shared references with other papers.</span>'}</button>`;
    };
    let list = '';
    if (cur) {
      const ws = cur.members.map(id => BY.get(id)).filter(Boolean).sort((a, b) => b.cic - a.cic || a.title.localeCompare(b.title));
      list = `<section class="card listpanel"><div class="hd" style="display:flex;gap:12px;align-items:center;margin-bottom:10px"><h3 class="h3" style="margin:0">Papers in ${cur.id === 'unclustered' ? 'not grouped' : esc(H.pretty(cur.dominant_label))}</h3><span class="meta">${fmt(ws.length)} papers</span><button class="btn" data-school="">Clear</button></div>
        <table class="t"><thead><tr><th>Title</th><th>Layer</th><th>Year</th><th class="r">${T('cic', 'Cited here')}</th></tr></thead><tbody>${ws.map(w => `<tr data-open="${esc(w.id)}" tabindex="0"><td>${esc(w.title)}</td><td><i class="dot" style="background:${H.layerColor(w.layer)}"></i> ${esc(H.layerLabel(w.layer))}</td><td>${esc(w.year ?? '')}</td><td class="r">${w.cic}</td></tr>`).join('')}</tbody></table></section>`;
    }
    return {
      title: 'Schools',
      info: infoPanel('Groups of papers that draw on the same literature.',
        'Each cluster of dots is one school; each dot is a paper, coloured by layer. The name is the most common technique among its papers, with its share. Click a school to list its papers.',
        `${meth('schools')}`),
      lead: biggest ? `Most papers fall in one large school, mostly <b>${esc(H.pretty(biggest.dominant_label || 'mixed').toLowerCase())}</b> work: <b>${fmt(biggest.size)}</b> of ${fmt(corpusN)} papers.${S.length > 1 ? ` The other ${S.length > 2 ? 'schools are' : 'school is'} small.` : ''}` : '',
      body: `<div class="schools">${S.map(s => card(s, false)).join('')}</div>${U ? `<div class="schools" style="margin-top:14px">${card(U, true)}</div>` : ''}${list}`,
    };
  };

  /* ================= 4. Main path ================= */
  build.path = () => {
    const MP = G.main_path, path = MP.path;
    const spc = new Map(MP.spc.map(e => [e.cited + '|' + e.citing, e.spc]));
    const first = BY.get(path[0]), last = BY.get(path[path.length - 1]);
    const ys = w => w ? w.year : '';
    return {
      title: 'Main path',
      info: infoPanel('The backbone of the field: the chain of papers through which most of the knowledge flows.',
        `Read left to right along the chain: each paper cites the one before it. Each stop is a paper (its date is under it); the line between two stops is thicker the more citation paths run through that link. Faint dots above and below are the other links of each stop. ${MP.dropped.length ? `${fmt(MP.dropped.length)} ${MP.dropped.length === 1 ? 'link was' : 'links were'} dropped to break citation cycles.` : ''}`,
        meth('main_path')),
      lead: path.length ? `The backbone runs through <b>${fmt(path.length)}</b> papers, from “${esc(short(nm(path[0]), 50))}” (${esc(ys(first))}) to “${esc(short(nm(path[path.length - 1]), 50))}” (${esc(ys(last))}).` : '',
      body: path.length ? '<div class="scrollx" id="pathhost"></div><p class="meta" style="margin-top:8px">Line thickness: number of citation paths through the link.</p>' : '<p class="empty">No main path was found in this corpus.</p>',
      draw() {
        const host = document.getElementById('pathhost'); if (!host) return;
        const n = path.length, W = Math.max(host.clientWidth || 900, n * 140), Hh = 430, y0 = 215, padX = 80;
        const gap = (W - 2 * padX) / Math.max(n - 1, 1), xs = path.map((_, i) => padX + i * gap);
        const Wd = W, svg = mk('svg', { width: Wd, height: Hh, viewBox: `0 0 ${Wd} ${Hh}`, role: 'group' }); host.appendChild(svg);
        const maxS = Math.max(1, ...path.slice(1).map((id, i) => spc.get(path[i] + '|' + id) || 0));
        const onPath = new Set(path);
        path.forEach((id, i) => { /* faint branches: the heaviest other links of each stop, fanned out on the side away from its label */
          const up = i % 2 === 1, out = MP.spc.filter(e => (e.cited === id || e.citing === id) && !(onPath.has(e.cited) && onPath.has(e.citing))).sort((a, b) => b.spc - a.spc || (a.cited + a.citing).localeCompare(b.cited + b.citing)).slice(0, 16);
          out.forEach((e, j) => { const o = e.cited === id ? e.citing : e.cited, bx = xs[i] + (j - (out.length - 1) / 2) * Math.min(gap / 18, 9), by = y0 + (up ? -1 : 1) * (50 + (j % 4) * 16);
            mk('line', { x1: xs[i], y1: y0, x2: bx, y2: by, stroke: 'var(--mut)', 'stroke-width': .8, opacity: .2 }, svg);
            const c = mk('circle', { cx: bx, cy: by, r: 3, fill: lcol(o), opacity: .5 }, svg); c.style.cursor = 'pointer'; c.addEventListener('click', () => openWork(o)); c.addEventListener('mousemove', ev => H.tip(`<b>${esc(nm(o))}</b><br>${esc(BY.get(o) ? BY.get(o).year : '')}`, ev)); c.addEventListener('mouseleave', () => H.tip(null)); });
        });
        for (let i = 1; i < n; i++) { const s = spc.get(path[i - 1] + '|' + path[i]) || 0; mk('line', { x1: xs[i - 1], y1: y0, x2: xs[i], y2: y0, stroke: 'var(--acc)', 'stroke-width': 2 + 12 * s / maxS, 'stroke-linecap': 'round', opacity: .75 }, svg); if (s) tx(svg, (xs[i - 1] + xs[i]) / 2, y0 - 10 - 6 * s / maxS, fmt(s), { 'text-anchor': 'middle', fill: 'var(--mut)', 'font-size': 11, class: 'halo' }); }
        path.forEach((id, i) => {
          const w = BY.get(id), up = i % 2 === 0, g = mk('g', {}, svg);
          const c = mk('circle', { cx: xs[i], cy: y0, r: 8, fill: lcol(id), stroke: 'var(--surface)', 'stroke-width': 2 }, g);
          const lines = wrap(short(nm(id), 66), 22).slice(0, 4), ty = up ? y0 - 24 - (lines.length - 1) * 14 : y0 + 30;
          lines.forEach((l, j) => tx(g, xs[i], ty + j * 14, l, { 'text-anchor': 'middle', fill: 'var(--fg)', 'font-size': 12 }));
          tx(g, xs[i], up ? ty - 14 : ty + lines.length * 14 + 2, w ? (w.year + (w.month ? '-' + String(w.month).padStart(2, '0') : '')) : '', { 'text-anchor': 'middle', fill: 'var(--dim)', 'font-size': 11 });
          g.setAttribute('tabindex', '0'); g.setAttribute('role', 'button'); g.setAttribute('aria-label', nm(id)); g.style.cursor = 'pointer';
          g.addEventListener('click', () => openWork(id)); g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openWork(id); } });
        });
      },
    };
  };

  /* ================= 5. River ================= */
  build.river = () => {
    const R = G.river, lags = R.map(a => a.lag_months).filter(x => x != null), med = median(lags);
    const bins = []; const BW = 3; lags.forEach(l => { const b = Math.max(0, Math.floor(l / BW)); bins[b] = (bins[b] || 0) + 1; });
    return {
      title: 'River',
      info: infoPanel('When papers cite earlier work, and how far back they reach.',
        'Time runs left to right. Each arc leaves a paper and lands on an older paper it cites; wide arcs reach far back. Colour is the layer of the citing paper. Click an arc to open the citing paper. The bars beneath count citations by their lag in months.',
        meth('river')),
      lead: R.length ? `The typical citation reaches back about <b>${fmt(Math.round(med))}</b> months.` : '',
      body: R.length ? `<div class="scrollx" id="riverhost"></div><h3 class="h3" style="margin:18px 0 4px">Lag between paper and source ${H.info('How many months older the cited paper is than the citing one, in three-month steps.', 'About the lag')}</h3><div class="scrollx" id="laghost"></div>` : '<p class="empty">No citations between corpus papers.</p>',
      draw() {
        const host = document.getElementById('riverhost'), lh = document.getElementById('laghost'); if (!host) return;
        const W = Math.max(host.clientWidth || 900, 760), Hh = 400, base = Hh - 36, px = 30;
        const all = R.flatMap(a => [isoMon(a.citing_date), isoMon(a.cited_date)]).filter(x => x != null), t0 = Math.min(...all), t1 = Math.max(...all, t0 + 1);
        const x = t => px + (t - t0) / (t1 - t0) * (W - 2 * px);
        const svg = mk('svg', { width: W, height: Hh, viewBox: `0 0 ${W} ${Hh}`, role: 'group' }); host.appendChild(svg);
        mk('line', { x1: px, y1: base, x2: W - px, y2: base, stroke: 'var(--line)' }, svg);
        for (let t = Math.ceil(t0 / 6) * 6; t <= t1; t += 6) { const yr = Math.floor(t / 12), h = (t % 12) ? 'H2' : ''; mk('line', { x1: x(t), y1: base, x2: x(t), y2: base + 5, stroke: 'var(--dim)' }, svg); tx(svg, x(t), base + 20, t % 12 ? '' : String(yr), { 'text-anchor': 'middle', fill: 'var(--dim)' }); }
        const gA = mk('g', { fill: 'none' }, svg);
        R.slice().sort((a, b) => a.lag_months - b.lag_months).forEach(a => {
          const c = isoMon(a.citing_date), o = isoMon(a.cited_date); if (c == null || o == null) return;
          const x1 = x(c), x2 = x(o), h = Math.abs(x1 - x2) / (W - 2 * px) * (base - 30), d = `M${x1.toFixed(1)} ${base} Q${((x1 + x2) / 2).toFixed(1)} ${(base - h * 2).toFixed(1)} ${x2.toFixed(1)} ${base}`;
          const vis = mk('path', { d, stroke: lcol(a.citing), 'stroke-width': 1, opacity: .28 }, gA);
          const hit = mk('path', { d, stroke: 'transparent', 'stroke-width': 8, 'pointer-events': 'stroke' }, gA); hit.style.cursor = 'pointer';
          hit.addEventListener('mouseenter', () => { vis.setAttribute('opacity', 1); vis.setAttribute('stroke-width', 2); });
          hit.addEventListener('mousemove', ev => H.tip(`<b>${esc(short(nm(a.citing), 70))}</b><br>cites ${esc(short(nm(a.cited), 70))}<br>${fmt(a.lag_months)} months earlier`, ev));
          hit.addEventListener('mouseleave', () => { vis.setAttribute('opacity', .28); vis.setAttribute('stroke-width', 1); H.tip(null); });
          hit.addEventListener('click', () => openWork(a.citing));
        });
        const lw = Math.max(lh.clientWidth || 900, 520), lhH = 150, mx = Math.max(...bins.map(b => b || 0), 1), bw = (lw - 2 * px) / Math.max(bins.length, 1);
        const s2 = mk('svg', { width: lw, height: lhH + 44, viewBox: `0 0 ${lw} ${lhH + 44}`, role: 'group' }); lh.appendChild(s2);
        for (let i = 0; i < bins.length; i++) { const n = bins[i] || 0, h = n / mx * (lhH - 20); const r = mk('rect', { x: px + i * bw + 1, y: lhH - h, width: Math.max(bw - 2, 1), height: h, fill: 'var(--acc)', opacity: .8, rx: 2 }, s2);
          r.addEventListener('mousemove', ev => H.tip(`${fmt(i * BW)}–${fmt(i * BW + BW - 1)} months<br><b>${fmt(n)}</b> citations`, ev)); r.addEventListener('mouseleave', () => H.tip(null)); if (bins.length < 14 || i % 2 === 0) tx(s2, px + i * bw + bw / 2, lhH + 16, String(i * BW), { 'text-anchor': 'middle', fill: 'var(--dim)' }); }
        tx(s2, lw - px, lhH + 38, 'months between paper and cited source', { 'text-anchor': 'end', fill: 'var(--dim)', 'font-size': 11 });
      },
    };
  };

  /* ================= 6. Reference health ================= */
  const STATE = [['resolved', 'Resolved', '--inc'], ['ambiguous', 'Ambiguous', '--l-core'], ['unconfirmed', 'Unconfirmed', '--l-applied'], ['unresolved', 'Unresolved', '--exc']];
  let healthAll = false;
  build.health = () => {
    const RH = G.reference_health, tot = RH.totals, sum = STATE.reduce((a, s) => a + (tot[s[0]] || 0), 0);
    const share = w => { const t = STATE.reduce((a, s) => a + (w[s[0]] || 0), 0); return t ? (w.unresolved || 0) / t : 0; };
    const have = RH.works.filter(w => w.has_extraction), none = RH.works.filter(w => !w.has_extraction);
    const rows = have.slice().sort((a, b) => share(b) - share(a) || (b.unresolved || 0) - (a.unresolved || 0) || a.work_id.localeCompare(b.work_id));
    const shown = healthAll ? rows : rows.slice(0, 40);
    const seg = w => { const t = STATE.reduce((a, s) => a + (w[s[0]] || 0), 0) || 1; return STATE.map(s => `<i style="width:${100 * (w[s[0]] || 0) / t}%;background:var(${s[2]})" title="${s[1]}: ${w[s[0]] || 0}"></i>`).join(''); };
    return {
      title: 'Reference health',
      info: infoPanel('How well the reference lists of the corpus papers could be matched to known works.',
        'The bar at the top adds up every paper; each row beneath is one paper, with those that have the most unmatched references first. Unresolved means a reference could not be matched to a work, so a citation from it may be missing from the graph.',
        meth('reference_health')),
      lead: sum ? `About <b>${pcs(tot.resolved, sum)}%</b> of the <b>${fmt(sum)}</b> references could be matched to a known work; <b>${pcs(tot.unresolved, sum)}%</b> could not.` : '',
      body: `<div class="hbar" role="img" aria-label="Reference states">${STATE.map(s => `<i style="width:${100 * (tot[s[0]] || 0) / (sum || 1)}%;background:var(${s[2]})"></i>`).join('')}</div>
        <div class="legend" style="margin:0 0 4px">${STATE.map(s => `<span><i class="sw" style="background:var(${s[2]})"></i>${s[1]} <b class="num">${fmt(tot[s[0]] || 0)}</b></span>`).join('')}</div>
        <p class="meta">Unresolved references are not errors in the paper; they are ones the hub could not match.${tot.works_without_extraction ? ` ${fmt(tot.works_without_extraction)} papers have no extracted reference list.` : ''}</p>
        <h3 class="h3" style="margin:18px 0 4px">Paper by paper</h3>
        <div role="list">${shown.map(w => `<div class="hrow" role="listitem" tabindex="0" data-open="${esc(w.work_id)}"><span>${esc(short(nm(w.work_id), 110))}</span><span class="mini">${seg(w)}</span><span class="num">${Math.round(share(w) * 100)}%</span></div>`).join('')}</div>
        ${rows.length > shown.length ? `<p><button class="btn" id="healthMore">Show all ${fmt(rows.length)}</button></p>` : ''}
        ${none.length ? `<p class="meta" style="margin-top:12px">No reference list extracted for ${fmt(none.length)} papers.</p>` : ''}`,
    };
  };

  /* ---------- render ---------- */
  function render() {
    const sy = scrollY, p = H.hash.get(), id = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'landscape';
    const L = build[id](p);
    cvs = null; ctx = null;
    main.innerHTML = `${H.header({ level: 1, title: 'Graph', sub: 'Who cites whom, in six views.', infoHtml: `<b>What it shows</b> The citation network of the ${fmt(corpusN)} papers of the review and the works around them.<p><span class=k>How to read it.</span> Choose a view. Each has its own ⓘ with the question it answers and how it is computed.</p>` })}
      <nav class="gtabs" aria-label="Graph view"><div class="seg">${TABS.map(([k, l]) => `<button type="button" data-tab="${k}" aria-pressed="${k === id}">${l}</button>`).join('')}</div></nav>
      <section class="card gp" aria-label="${esc(L.title)}">${H.header({ title: L.title, infoHtml: L.info })}${L.lead ? `<p class="lead">${L.lead}</p>` : ''}${L.body}</section>
      <p class="meta" style="margin-top:22px">About these counts ${H.info(esc(H.SETS_NOTE), 'About these counts')}</p>`;
    if (L.draw) L.draw();
    scrollTo(0, sy);
  }
  main.addEventListener('click', e => {
    const t = e.target.closest('[data-tab],[data-school],[data-open],#healthMore'); if (!t) return;
    if (t.dataset.tab) { H.hash.set({ tab: t.dataset.tab, school: null }); render(); }
    else if (t.dataset.school !== undefined) { H.hash.set({ school: t.dataset.school || null }); render(); }
    else if (t.dataset.open) { H.openDrawer(t.dataset.open); }
    else if (t.id === 'healthMore') { healthAll = true; render(); }
  });
  main.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('tr[data-open],.hrow')) { e.preventDefault(); H.openDrawer(e.target.dataset.open); } });
  addEventListener('hashchange', render);
  document.addEventListener('hub:theme', render);
  addEventListener('resize', () => { if (cvs) { if (!LS.userView) fit(); paintLand(); } });
  render();
}).catch(e => {
  document.body.textContent = 'Graph failed to load: ' + e.message;
  console.error(e);
});
