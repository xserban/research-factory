/* Platform page: how a project runs (the run map), what the platform can do (capabilities by
   lifecycle stage) and the backlog board. Payload: platform (services/hub_platform.py). Every number
   comes from the payload. Read-only. Tabs: How it works, Capabilities, Backlog.
   Hash keys: tab, rm, stage, q, view, area, state, slice, idea. */
/* "How it works" tab: the run map. Text is declared in the payload (`run_map`,
   services/hub_platform.py); each stage's skills and tool count come from the catalog. Read-only.
   Exposes HUB_HOWTO.render(H, P, st, go) -> html and HUB_HOWTO.wire(main, st, go). Hash key: rm (stage). */
(function () {
  const ACTOR = {
    human: ['Researcher', 'var(--h-collab)'],
    claude: ['Claude session', 'var(--h-none)'],
    platform: ['Platform', 'var(--mut)'],
  };
  const CSS = `
.rm-lead{font:400 var(--t-l)/1.4 var(--f-display);max-width:68ch;margin:4px 0 14px}
.rm-key{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:var(--t-xs);color:var(--mut);margin:0 0 14px}
.rm-key i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.rm-entry{padding:12px 16px;margin:0 0 var(--gap);font-size:var(--t-s);color:var(--mut)}
.rm-entry b{color:var(--fg);font-weight:600;margin-right:6px}
.rm-track{padding:8px 4px 4px;overflow-x:auto}
.rm-track svg{display:block;min-width:860px;width:100%;height:auto}
.rm-line{stroke:var(--line);stroke-width:3;fill:none}
.rm-flow{stroke:var(--acc);stroke-width:2;fill:none;stroke-dasharray:3 11;opacity:.7;animation:rm-run 1.4s linear infinite}
@keyframes rm-run{to{stroke-dashoffset:-14}}
.rm-loop{fill:none;stroke:var(--h-feedback);stroke-width:1.6;stroke-dasharray:5 5;opacity:.85;animation:rm-run 1.8s linear infinite reverse}
.rm-loop-t{font:500 11px var(--f-mono);fill:var(--h-feedback)}
.rm-nd{cursor:pointer}
.rm-nd .disc{fill:var(--surface);stroke:var(--line);stroke-width:2;transition:stroke .15s}
.rm-nd .fill{fill:var(--acc-soft)}
.rm-nd:hover .disc,.rm-nd:focus-visible .disc{stroke:var(--mut)}
.rm-nd.on .disc{stroke:var(--acc);stroke-width:3}
.rm-nd.on .halo{opacity:1}
.rm-nd .halo{fill:none;stroke:var(--acc);stroke-width:1;opacity:0;animation:rm-pulse 2.2s ease-out infinite}
@keyframes rm-pulse{0%{transform:scale(1);opacity:.7}100%{transform:scale(1.5);opacity:0}}
.rm-nd .num{font:500 15px var(--f-mono);fill:var(--fg);text-anchor:middle;dominant-baseline:central;pointer-events:none}
.rm-nd .lab{font:600 12.5px var(--f-ui);fill:var(--fg);text-anchor:middle;pointer-events:none}
.rm-nd .sub{font:400 11px var(--f-mono);fill:var(--mut);text-anchor:middle;pointer-events:none}
.rm-nd .dot{fill:var(--h-none)}
.rm-nd:focus{outline:none}
.rm-hint{font-size:var(--t-xs);color:var(--dim);margin:2px 4px 0}
.rm-det{margin:var(--gap) 0 0;padding:18px 20px}
.rm-det-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;margin:0 0 14px}
.rm-det-h h3{margin:0;font:400 var(--t-xl)/1.1 var(--f-display)}
.rm-det-h .n{font:500 var(--t-s) var(--f-mono);color:var(--mut)}
.rm-det-h .nav{margin-left:auto;display:flex;gap:6px}
.rm-lanes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--gap)}
.rm-lane{border-top:3px solid var(--ac);padding:10px 2px 0;min-width:0}
.rm-lane h4{margin:0 0 8px;font:600 var(--t-xs) var(--f-ui);letter-spacing:.08em;text-transform:uppercase;color:var(--ac)}
.rm-lane ul{margin:0;padding:0;list-style:none;display:grid;gap:6px;font-size:var(--t-s)}
.rm-lane li{position:relative;padding-left:14px}
.rm-lane li::before{content:"";position:absolute;left:0;top:.55em;width:6px;height:6px;border-radius:50%;background:var(--ac);opacity:.8}
.rm-cmd{display:inline-block;margin-top:10px;font:400 var(--t-xs) var(--f-mono);color:var(--ac);background:var(--raised);padding:3px 8px;border-radius:var(--r-s)}
.rm-chips{display:flex;flex-wrap:wrap;gap:5px;margin:0 0 8px}
.rm-sk{font:500 var(--t-xs) var(--f-mono);color:var(--h-none);background:color-mix(in srgb,var(--h-none) 14%,transparent);padding:2px 8px;border-radius:9px;cursor:help}
.rm-tl{font:400 var(--t-xs) var(--f-mono);color:var(--fg);background:var(--raised);padding:2px 7px;border-radius:var(--r-s);border:0;cursor:pointer}
.rm-tl:hover{background:var(--acc-soft)}
.rm-sm{font-size:var(--t-xs);color:var(--mut);margin:8px 0 0}
.rm-out{margin-top:12px;font:500 var(--t-s) var(--f-ui);color:var(--fg)}
.rm-out span{color:var(--mut);font-weight:400}
.rm-sec{margin:38px 0 0}
.rm-seq{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:var(--gap);align-items:start}
.rm-seq .card{padding:12px 10px;overflow-x:auto}
.rm-seq svg{display:block;width:100%;min-width:520px;height:auto}
.rm-life{stroke:var(--line);stroke-width:1.5;stroke-dasharray:4 4}
.rm-actor{font:600 12px var(--f-ui);text-anchor:middle}
.rm-msg{stroke:var(--dim);stroke-width:1.4;fill:none;transition:stroke .2s,opacity .2s;opacity:.55}
.rm-msg.on{stroke:var(--acc);stroke-width:2.4;opacity:1}
.rm-mt{font:500 11.5px var(--f-ui);fill:var(--mut);text-anchor:middle;transition:fill .2s}
.rm-mt.on{fill:var(--fg)}
.rm-tok{fill:var(--acc);transition:transform .7s cubic-bezier(.5,0,.3,1)}
.rm-steps{margin:0;padding:0;list-style:none;display:grid;gap:4px}
.rm-steps button{display:grid;grid-template-columns:26px minmax(0,1fr);gap:8px;width:100%;text-align:left;background:none;border:0;border-radius:var(--r-s);padding:7px 8px;color:var(--fg);font:inherit;cursor:pointer}
.rm-steps button:hover{background:var(--raised)}
.rm-steps button[aria-current=true]{background:var(--acc-soft)}
.rm-steps .i{font:500 var(--t-xs) var(--f-mono);color:var(--mut);padding-top:2px}
.rm-steps b{display:block;font-size:var(--t-s);font-weight:600}
.rm-steps b small{font:500 var(--t-xs) var(--f-ui);margin-left:6px}
.rm-steps span span{font-size:var(--t-xs);color:var(--mut)}
.rm-ctl{display:flex;gap:8px;align-items:center;margin:0 0 10px}
.rm-rules{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:var(--gap);align-items:start}
.rm-rules .card{padding:16px 18px}
.rm-rules h4{margin:0 0 4px;font:600 var(--t-s) var(--f-ui)}
.rm-rules p{margin:0 0 14px;font-size:var(--t-s);color:var(--mut);max-width:62ch}
.rm-rules p:last-child{margin-bottom:0}
.rm-ind svg{display:block;width:100%;height:auto}
.rm-ind .bx{fill:var(--raised);stroke:none}
.rm-ind text{font:500 12px var(--f-ui);fill:var(--fg);text-anchor:middle}
.rm-ind .k{font:400 11px var(--f-mono);fill:var(--mut)}
.rm-ind .ar{stroke:var(--dim);stroke-width:1.4;fill:none}
.rm-ind .wall{stroke:var(--exc);stroke-width:2;stroke-dasharray:3 4}
@media (max-width:980px){.rm-seq,.rm-rules{grid-template-columns:minmax(0,1fr)}}
@media (max-width:760px){.rm-lanes{grid-template-columns:minmax(0,1fr)}}`;

  let timer = null;
  const stop = () => { if (timer) { clearInterval(timer); timer = null; } };

  function track(H, R, rows, sel) {
    const { esc } = H;
    const W = 1000, Y = 190, X0 = 64, DX = (W - 2 * X0) / (R.stages.length - 1);
    const maxT = Math.max(1, ...rows.map(r => r.n_tools || 0));
    const pos = {}, rad = {};
    R.stages.forEach((s, i) => {
      const r = rows.find(x => x.id === s.id) || {};
      pos[s.id] = X0 + i * DX; rad[s.id] = 15 + 13 * Math.sqrt((r.n_tools || 0) / maxT);
    });
    const heights = [78, 122, 156];
    const loops = R.loops.map((l, k) => {
      const x1 = pos[l.from] + (k ? 6 : -6), x2 = pos[l.to] + (k === 2 ? -6 : 6), h = heights[k % 3];
      const y1 = Y - rad[l.from] - 4, y2 = Y - rad[l.to] - 4;
      const d = `M${x1},${y1} C${x1},${Y - h} ${x2},${Y - h} ${x2},${y2}`;
      const tx = (x1 + x2) / 2, ty = Y - 0.75 * h - 6;
      return `<path class="rm-loop" d="${d}" marker-end="url(#rm-arr)"><title>${esc(l.label)}: ${esc(l.what)}</title></path>
        <text class="rm-loop-t" x="${tx}" y="${ty}" text-anchor="middle">↺ ${esc(l.label)}</text>`;
    }).join('');
    const nodes = R.stages.map((s, i) => {
      const r = rows.find(x => x.id === s.id) || {}, x = pos[s.id], rr = rad[s.id];
      const ly = Y + 48 + (i % 2) * 22, ns = r.n_skills || 0;
      const dots = Array.from({ length: Math.min(ns, 9) }, (_, j) => `<circle class="dot" cx="${x - (Math.min(ns, 9) - 1) * 4 + j * 8}" cy="${ly + 12}" r="2.6"/>`).join('');
      const tick = `<line x1="${x}" y1="${Y + rr + 2}" x2="${x}" y2="${ly - 13}" stroke="var(--line)" stroke-width="1"/>`;
      const frac = Math.max(0.08, (r.n_tools || 0) / maxT);
      return `<g class="rm-nd${sel === s.id ? ' on' : ''}" data-rm="${esc(s.id)}" tabindex="0" role="button" aria-pressed="${sel === s.id}" aria-label="${esc(r.label || s.id)}: ${esc(String(r.n_tools || 0))} tools, ${esc(String(ns))} skills">
        <circle class="halo" cx="${x}" cy="${Y}" r="${rr}" style="transform-origin:${x}px ${Y}px"/>
${tick}<circle class="disc" cx="${x}" cy="${Y}" r="${rr}"/>
        <circle class="fill" cx="${x}" cy="${Y}" r="${(rr - 3) * Math.sqrt(frac)}"/>
        <text class="num" x="${x}" y="${Y}">${esc(String(r.n_tools || 0))}</text>
        <text class="lab" x="${x}" y="${ly}">${i + 1} · ${esc(r.label || s.id)}</text>${dots}<title>${esc(r.label || s.id)} produces ${esc(s.out)}</title></g>`;
    }).join('');
    const xa = pos[R.stages[0].id], xb = pos[R.stages[R.stages.length - 1].id];
    return `<div class="card rm-track"><svg viewBox="0 0 ${W} 300" role="group" aria-label="The run, stage by stage">
      <defs><marker id="rm-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--h-feedback)"/></marker>
      <marker id="rm-arr2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--line)"/></marker></defs>
      <path class="rm-line" d="M${xa - 40},${Y} L${xb + 44},${Y}" marker-end="url(#rm-arr2)"/>
      <path class="rm-flow" d="M${xa - 40},${Y} L${xb + 40},${Y}"/>
      ${loops}${nodes}</svg>
      <div class="rm-hint">Number in a stage: its tools. Dots under it: its skills. Size grows with the tools. Dashed arcs: loops back. Select a stage for who does what.</div></div>`;
  }

  function detail(H, R, rows, sel) {
    const { esc } = H;
    const i = Math.max(0, R.stages.findIndex(s => s.id === sel));
    const s = R.stages[i], r = rows.find(x => x.id === s.id) || { skills: [], n_tools: 0, label: s.id, covers: '' };
    const list = a => `<ul>${a.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
    const lane = (k, body) => `<div class="rm-lane" style="--ac:${ACTOR[k][1]}"><h4>${esc(ACTOR[k][0])}</h4>${body}</div>`;
    const sk = (r.skills || []).map(x => `<span class="rm-sk" title="${esc(x.d)}">${esc(x.n)}</span>`).join('');
    const tl = s.tools.map(t => `<button type="button" class="rm-tl" data-tool="${esc(t)}" data-tool-stage="${esc((rows.find(x => (x.tools || []).includes(t)) || s).id)}" title="Open in Capabilities">${esc(t)}</button>`).join('');
    const prev = R.stages[i - 1], next = R.stages[i + 1];
    return `<div class="card raised rm-det" id="rm-det"><div class="rm-det-h"><span class="n">Stage ${i + 1} of ${R.stages.length}</span><h3>${esc(r.label)}</h3><span class="meta">${esc(r.covers)}</span>
      <span class="nav"><button type="button" class="btn" data-rm="${esc(prev ? prev.id : '')}" ${prev ? '' : 'disabled'} aria-label="Previous stage">←</button><button type="button" class="btn" data-rm="${esc(next ? next.id : '')}" ${next ? '' : 'disabled'} aria-label="Next stage">→</button></span></div>
      <div class="rm-lanes">
        ${lane('human', list(s.human) + (s.cmd ? `<code class="rm-cmd">${esc(s.cmd)}</code>` : ''))}
        ${lane('claude', `<div class="rm-chips">${sk || '<span class="meta">No skill; tools only.</span>'}</div><div class="rm-chips">${tl}</div>
          <p class="rm-sm">${esc(String(r.n_skills || 0))} skills and ${esc(String(r.n_tools || 0))} tools in this stage. <a href="#" data-cap="${esc(s.id)}">See them all in Capabilities</a>.</p>${s.sessions ? `<p class="rm-sm">${esc(s.sessions)}</p>` : ''}`)}
        ${lane('platform', list(s.platform) + `<div class="rm-out"><span>Produces</span> ${esc(s.out)}</div>`)}
      </div></div>`;
  }

  function sequence(H, R, step) {
    const { esc } = H;
    const LX = { claude: 150, platform: 450, human: 750 }, top = 58, gap = 50, n = R.call.length;
    const hgt = top + n * gap + 20;
    const lines = Object.entries(LX).map(([k, x]) => `<text class="rm-actor" x="${x}" y="24" style="fill:${ACTOR[k][1]}">${esc(ACTOR[k][0])}</text>
      <line class="rm-life" x1="${x}" y1="36" x2="${x}" y2="${hgt - 6}"/>`).join('');
    const arrows = R.call.map((c, i) => {
      const to = i + 1 < n ? R.call[i + 1].who : 'platform', y = top + i * gap + 14, x1 = LX[c.who], x2 = LX[to], on = i === step ? ' on' : '';
      const d = x1 === x2 ? `M${x1},${y - 8} C${x1 + 70},${y - 8} ${x1 + 70},${y + 12} ${x1 + 4},${y + 12}` : `M${x1},${y} L${x2 + (x2 > x1 ? -6 : 6)},${y}`;
      const tx = x1 === x2 ? x1 + 80 : (x1 + x2) / 2, anchor = x1 === x2 ? 'start' : 'middle';
      return `<path class="rm-msg${on}" d="${d}" marker-end="url(#rm-a3)"/><text class="rm-mt${on}" x="${tx}" y="${x1 === x2 ? y + 6 : y - 7}" style="text-anchor:${anchor}">${i + 1}. ${esc(c.act)}</text>`;
    }).join('');
    const c = R.call[step], y0 = top + step * gap + 14;
    return `<svg viewBox="0 0 900 ${hgt}" role="img" aria-label="Sequence of one tool call">
      <defs><marker id="rm-a3" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acc)"/></marker></defs>
      ${lines}${arrows}<circle class="rm-tok" cx="0" cy="0" r="6" style="transform:translate(${LX[c.who]}px,${y0}px)"/></svg>`;
  }

  function independence(H) {
    return `<div class="rm-ind"><svg viewBox="0 0 420 210" role="img" aria-label="Two independent passes meet only in the platform">
      <rect class="bx" x="20" y="14" width="150" height="42" rx="8"/><text x="95" y="40">Session 1 · pass A</text>
      <rect class="bx" x="250" y="14" width="150" height="42" rx="8"/><text x="325" y="40">Session 2 · pass B</text>
      <line class="wall" x1="210" y1="8" x2="210" y2="66"/><text class="k" x="210" y="80">no shared view</text>
      <path class="ar" d="M95,56 C95,96 180,96 196,110" marker-end="url(#rm-a4)"/><path class="ar" d="M325,56 C325,96 240,96 224,110" marker-end="url(#rm-a4)"/>
      <rect class="bx" x="90" y="112" width="240" height="36" rx="8"/><text x="210" y="134">Platform: agreement, disagreements</text>
      <path class="ar" d="M210,148 L210,166" marker-end="url(#rm-a4)"/>
      <rect class="bx" x="110" y="168" width="200" height="34" rx="8" style="fill:color-mix(in srgb,var(--h-collab) 22%,transparent)"/><text x="210" y="189">Researcher resolves</text>
      <defs><marker id="rm-a4" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--dim)"/></marker></defs></svg></div>`;
  }

  function render(H, P, st) {
    const { esc, info } = H;
    const R = P.run_map, M = P.methods || {};
    if (!R) return '<p class="pl-empty">The run map is not in this payload.</p>';
    const rows = (P.catalog && P.catalog.stages) || [];
    const sel = R.stages.some(s => s.id === st.rm) ? st.rm : R.stages[0].id;
    const step = Math.min(Math.max(0, st.step || 0), R.call.length - 1);
    const key = Object.entries(ACTOR).map(([, v]) => `<span><i style="background:${v[1]}"></i>${esc(v[0])}</span>`).join('') + '<span><i style="background:var(--h-feedback)"></i>Loop back</span>';
    return `${H.header({ title: 'How a project runs', infoHtml: esc(M.run_map || ''), sub: 'From question to living review: who does what at each stage.' })}
      <p class="rm-lead">${esc(R.lead)}</p><div class="rm-key">${key}</div>
      <div class="card rm-entry"><b>Every session starts here</b>${esc(R.entry)}</div>
      ${P.catalog ? '' : `<p class="pl-line bad">The catalog could not be built, so skills and tool counts are missing${P.catalog_error ? ': ' + esc(P.catalog_error) : '.'}</p>`}
      ${track(H, R, rows, sel)}${detail(H, R, rows, sel)}
      <section class="rm-sec">${H.header({ title: 'One tool call', sub: 'The loop every stage repeats. Here a miner; screening, extraction and verification use their own tools.' })}
        <div class="rm-seq"><div class="card">${sequence(H, R, step)}</div>
        <div><div class="rm-ctl"><button type="button" class="btn" id="rm-play">${timer ? 'Pause' : 'Play'}</button><button type="button" class="btn" id="rm-next">Next step</button><span class="meta" role="status">Step ${step + 1} of ${R.call.length}</span></div>
        <ol class="rm-steps">${R.call.map((c, i) => `<li><button type="button" data-step="${i}" aria-current="${i === step}"><span class="i">${i + 1}</span><span><b>${esc(c.act)}<small style="color:${ACTOR[c.who][1]}">${esc(ACTOR[c.who][0])}</small></b><span>${esc(c.text)}</span></span></button></li>`).join('')}</ol></div></div>
        <p class="rm-sm">Every agent event carries the model, the skill hashed by the platform from the installed file, and the input the agent saw.</p></section>
      <section class="rm-sec">${H.header({ title: 'Rules behind it' })}
        <div class="rm-rules"><div class="card">${R.rules.map(([h, t]) => `<h4>${esc(h)}</h4><p>${esc(t)}</p>`).join('')}</div>
        <div class="card">${independence(H)}<p class="rm-sm">Pass A, pass B, a critic and a verifier each run in their own Claude Code session.</p></div></div></section>`;
  }

  function wire(main, st, go, rerender) {
    main.querySelectorAll('[data-rm]').forEach(el => {
      const f = () => { if (el.dataset.rm) { stop(); go({ rm: el.dataset.rm }); } };
      el.addEventListener('click', f);
      el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); f(); } });
    });
    main.querySelectorAll('[data-cap]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); stop(); go({ tab: 'cap', stage: el.dataset.cap, q: '' }); }));
    main.querySelectorAll('[data-tool]').forEach(el => el.addEventListener('click', () => { stop(); go({ tab: 'cap', stage: el.dataset.toolStage, q: el.dataset.tool }); }));
    const n = (main.querySelectorAll('[data-step]').length) || 1;
    const pl = main.querySelector('#rm-play');
    const setStep = k => {
      st.step = k;
      const svg = main.querySelector('.rm-seq svg'); if (!svg) { rerender(); return; }
      svg.querySelectorAll('.rm-msg').forEach((m, i) => m.classList.toggle('on', i === k));
      svg.querySelectorAll('.rm-mt').forEach((m, i) => m.classList.toggle('on', i === k));
      const tok = svg.querySelector('.rm-tok'), arr = svg.querySelectorAll('.rm-msg')[k];
      if (tok && arr) { const p = arr.getPointAtLength(0); tok.style.transform = `translate(${p.x}px,${p.y}px)`; }
      main.querySelectorAll('[data-step]').forEach((b, i) => b.setAttribute('aria-current', String(i === k)));
      const s = main.querySelector('.rm-ctl [role=status]'); if (s) s.textContent = `Step ${k + 1} of ${n}`;
    };
    const label = () => { if (pl) pl.textContent = timer ? 'Pause' : 'Play'; };
    main.querySelectorAll('[data-step]').forEach(el => el.addEventListener('click', () => { stop(); setStep(Number(el.dataset.step)); }));
    const nx = main.querySelector('#rm-next'); if (nx) nx.addEventListener('click', () => { stop(); setStep(((st.step || 0) + 1) % n); });
    if (pl) pl.addEventListener('click', () => {
      if (timer) { stop(); label(); return; }
      if ((st.step || 0) >= n - 1) setStep(0);
      timer = setInterval(() => {
        if (!pl.isConnected) { stop(); return; }
        if ((st.step || 0) >= n - 1) { stop(); label(); return; }
        setStep((st.step || 0) + 1);
      }, 1500);
      label();
    });
  }

  window.HUB_HOWTO = { CSS, render, wire, stop };
})();

HUB.load(['shell', 'platform']).then(d => {
  const H = HUB.init(d.shell);
  const P = d.platform || {};
  const main = H.mount({ page: 'platform', crumb: 'Platform' });
  const { esc, info } = H;
  const M = P.methods || {};
  const C = P.catalog, B = P.backlog;

  if (!document.getElementById('pl-style')) {
    const st = document.createElement('style'); st.id = 'pl-style';
    st.textContent = `
.pl-tabs{margin:18px 0 20px}
.pl-kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:var(--gap);margin:0 0 14px}
.pl-kpi{padding:14px 16px}.pl-kpi .v{font:500 var(--t-xl) var(--f-mono);line-height:1.1}.pl-kpi .k{font-size:var(--t-xs);color:var(--mut);margin-top:4px}
.pl-kpi.bad .v{color:var(--exc)}
.pl-line{margin:6px 0;font-size:var(--t-s);color:var(--mut)}.pl-line.ok b{color:var(--inc)}.pl-line.bad{color:var(--exc)}
.pl-cmds{margin:10px 0 0;display:grid;gap:6px}.pl-cmds code{font:400 var(--t-s) var(--f-mono);color:var(--fg)}
.pl-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0 10px}
.pl-in{background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:7px 10px;font:inherit;font-size:var(--t-s);min-width:240px;flex:1;max-width:420px}
.pl-sel{background:var(--raised);color:var(--fg);border:1px solid var(--line);border-radius:var(--r-s);padding:6px 8px;font:inherit;font-size:var(--t-s)}
.pl-mx{width:100%;border-collapse:collapse;font-size:var(--t-s)}
.pl-mx th{font-weight:500;color:var(--mut);text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}
.pl-mx td{padding:8px;border-bottom:1px solid var(--hair);vertical-align:middle}
.pl-mx tbody tr{cursor:pointer}.pl-mx tbody tr:hover,.pl-mx tbody tr:focus-visible{background:var(--raised)}
.pl-mx tr[aria-selected=true]{background:var(--acc-soft)}.pl-mx tr.dim{opacity:.35}
.pl-mx td.n,.pl-mx th.n{text-align:right;font-family:var(--f-mono)}
.pl-st b{font-weight:600}.pl-st small{display:block;color:var(--dim);font-size:var(--t-xs)}
.pl-seg{display:flex;height:10px;min-width:120px;background:var(--raised);border-radius:3px;overflow:hidden}
.pl-seg i{display:block;height:100%;background:var(--acc)}
.pl-flag{font:600 var(--t-xs) var(--f-mono);color:var(--exc);background:var(--exc-soft);padding:2px 7px;border-radius:9px}
.pl-mk{font:500 var(--t-xs) var(--f-mono);color:var(--mut)}
.pl-panel{margin:14px 0 24px;padding:18px 20px}
.pl-panel h3{margin:0 0 2px}.pl-panel h4{margin:18px 0 6px;font:500 var(--t-xs) var(--f-ui);color:var(--mut);text-transform:uppercase;letter-spacing:.08em}
.pl-sk{padding:10px 0;border-top:1px solid var(--hair)}.pl-sk:first-of-type{border-top:0}
.pl-sk .nm{font:600 var(--t-s) var(--f-mono)}.pl-sk ol{margin:6px 0 0;padding-left:20px;color:var(--mut);font-size:var(--t-s)}
.pl-sk ol small{color:var(--dim)}
.pl-tl{padding:8px 0;border-top:1px solid var(--hair);font-size:var(--t-s)}
.pl-tl .nm{font:600 var(--t-s) var(--f-mono)}.pl-tl .meta{display:block;margin-top:2px}
.pl-tl details{margin-top:4px}.pl-tl summary{cursor:pointer;color:var(--mut);font-size:var(--t-xs)}
.pl-tl pre{margin:6px 0 0;padding:10px;background:var(--raised);border-radius:var(--r-s);overflow:auto;max-height:260px;font:400 var(--t-xs) var(--f-mono)}
.pl-tag{display:inline-block;font:500 var(--t-xs) var(--f-mono);padding:1px 7px;border-radius:9px;background:var(--raised);color:var(--mut);margin-left:6px}
.pl-sec{margin:34px 0 0}
.pl-sec table{width:100%;border-collapse:collapse;font-size:var(--t-s)}
.pl-sec th{font-weight:500;color:var(--mut);text-align:left;padding:8px;border-bottom:1px solid var(--line)}
.pl-sec td{padding:8px;border-bottom:1px solid var(--hair);vertical-align:top}
.pl-sec td.mono{font:400 var(--t-xs) var(--f-mono);word-break:break-all}
.pl-foot{margin-top:30px;font:400 var(--t-xs) var(--f-mono);color:var(--dim);overflow-wrap:anywhere}
.pl-empty{color:var(--dim);padding:24px 4px}
.pl-areas{display:grid;gap:6px;margin:6px 0 14px}
.pl-ar{display:grid;grid-template-columns:minmax(120px,220px) minmax(0,1fr) 50px;gap:12px;align-items:center;cursor:pointer;background:none;border:0;color:var(--fg);font:inherit;text-align:left;padding:3px 4px;border-radius:var(--r-s);width:100%}
.pl-ar:hover,.pl-ar[aria-pressed=true]{background:var(--raised)}.pl-ar .t{font-size:var(--t-s);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pl-ar .c{text-align:right;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.pl-stack{display:flex;height:12px;border-radius:3px;overflow:hidden;background:var(--raised)}.pl-stack i{display:block;height:100%}
.pl-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:var(--t-xs);color:var(--mut);margin:4px 0 10px}
.pl-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.pl-s-ready{--sc:var(--inc)}.pl-s-blocked{--sc:var(--exc)}.pl-s-specified{--sc:var(--acc)}.pl-s-done{--sc:var(--mut)}.pl-s-parked{--sc:var(--h-null)}
.pl-lay{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:var(--gap);align-items:start}
.pl-cols{display:grid;grid-template-columns:repeat(5,minmax(190px,1fr));gap:var(--gap);overflow-x:auto;padding-bottom:6px}
.pl-col h3{margin:0;font:600 var(--t-s) var(--f-ui);display:flex;gap:8px;align-items:center}
.pl-col h3 i{width:9px;height:9px;border-radius:50%;background:var(--sc)}.pl-col h3 span{font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.pl-col .help{font-size:var(--t-xs);color:var(--dim);margin:2px 0 8px;min-height:2.6em}
.pl-card{display:block;width:100%;text-align:left;font:inherit;color:var(--fg);background:var(--surface);border:0;border-left:3px solid var(--sc);border-radius:var(--r-s);padding:8px 10px;margin:0 0 8px;cursor:pointer}
.pl-card:hover,.pl-card[aria-current=true]{background:var(--raised)}.pl-card[aria-current=true]{box-shadow:inset 0 0 0 1px var(--acc)}
.pl-card .id{font:500 var(--t-xs) var(--f-mono);color:var(--mut)}.pl-card .ti{display:block;font-size:var(--t-s);margin-top:2px}
.pl-card .ft{display:flex;gap:8px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--dim);margin-top:4px}
.pl-more{font-size:var(--t-xs);color:var(--dim);padding:2px 4px}
.pl-det{position:sticky;top:70px;padding:16px 18px;max-height:calc(100vh - 100px);overflow:auto}
.pl-det h3{margin:2px 0 8px;font:500 var(--t-m) var(--f-ui)}.pl-det .f{margin:10px 0}.pl-det .f .k{font-size:var(--t-xs);color:var(--mut)}
.pl-det .f .v{font-size:var(--t-s);white-space:pre-wrap}.pl-det a{cursor:pointer}
.pl-tray{margin-top:var(--gap);padding:14px 18px}.pl-tray ul{margin:8px 0;padding-left:18px;font-size:var(--t-s)}
.pl-tree{overflow:auto;padding:6px}.pl-tree svg{display:block}.pl-tree .nd{cursor:pointer}
.pl-tree .nd circle{fill:var(--sc);stroke:var(--bg);stroke-width:2}.pl-tree .nd.on circle{stroke:var(--acc);stroke-width:3}
.pl-tree .nd.off{opacity:.18}.pl-tree .ed{stroke:var(--line);stroke-width:1.2;fill:none}.pl-tree .ed.on{stroke:var(--acc);stroke-width:2}.pl-tree .ed.off{opacity:.15}
.pl-tree text{font:500 10px var(--f-mono);fill:var(--mut);pointer-events:none}
@media (max-width:1100px){.pl-lay{grid-template-columns:minmax(0,1fr)}.pl-det{position:static;max-height:none}}
@media (max-width:760px){.pl-ar{grid-template-columns:90px minmax(0,1fr) 36px}}` + HUB_HOWTO.CSS;
    document.head.appendChild(st);
  }

  const TABS = [['how', 'How it works'], ['cap', 'Capabilities'], ['backlog', 'Backlog']];
  const st = { tab: 'how', rm: '', step: 0, stage: '', q: '', view: 'board', area: '', state: '', slice: '', idea: '', sel: [] };
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'how'; st.rm = p.get('rm') || '';
    st.stage = p.get('stage') || ''; st.q = p.get('q') || ''; st.view = p.get('view') === 'tree' ? 'tree' : 'board';
    st.area = p.get('area') || ''; st.state = p.get('state') || ''; st.slice = p.get('slice') || ''; st.idea = p.get('idea') || '';
  };
  const go = o => { HUB_HOWTO.stop(); H.hash.set(o); readHash(); render(); };
  const fmt = n => (n == null ? '' : String(n));
  const lc = s => String(s || '').toLowerCase();
  const empty = msg => `<p class="pl-empty">${esc(msg)}</p>`;

  /* ---------------- Capabilities ---------------- */
  const ACCESS_HELP = 'The permission row of the access table: the right a caller needs to run the tool.';
  function kpis(c) {
    const s = c.summary;
    const items = [
      [s.tools_registered, 'Tools registered'], [s.tools_listed, 'Tools listed'], [s.skills, 'Skills'],
      [s.prompts == null ? 'not derived' : s.prompts, 'Prompts'], [s.examples, 'Worked examples'],
      [s.marked, 'Marked tools'], [s.orphan_tools, 'Orphan tools', s.orphan_tools > 0], [s.flags, 'Flags', s.flags > 0],
    ];
    return `<div class="pl-kpis">${items.map(([v, k, bad]) => `<div class="card pl-kpi${bad ? ' bad' : ''}"><div class="v">${esc(fmt(v))}</div><div class="k">${esc(k)}</div></div>`).join('')}</div>`;
  }
  function countCheck(c) {
    const cc = c.count_check, s = c.summary;
    let h;
    if (cc.ok) h = `<div class="pl-line ok"><b>Count check passed.</b> ${esc(fmt(s.tools_registered))} tools in the source, all listed by the built server.</div>`;
    else {
      const parts = [['not listed', cc.missing], ['not in source', cc.extra], ['duplicate', cc.duplicates]].filter(p => p[1].length).map(p => p[0] + ': ' + p[1].join(', '));
      h = `<div class="pl-line bad">Count check failed. Registered ${esc(fmt(s.tools_registered))}, listed ${esc(fmt(s.tools_listed))}. ${esc(parts.join('; '))}</div>`;
    }
    const sk = Object.entries(c.skipped || {}).map(([k, v]) => `<div class="pl-line">Not derived: ${esc(k)} (${esc(v)}). Absent, not zero.</div>`).join('');
    return h + sk;
  }
  function matches(c) {
    const q = lc(st.q); if (!q) return null;
    const hit = new Set();
    c.tools.forEach(t => { if (lc(t.n).includes(q) || lc(t.d).includes(q)) hit.add(t.stage || 'unassigned'); });
    c.skills.forEach(s => { if (lc(s.n).includes(q) || lc(s.d).includes(q)) hit.add(s.stages[0] || 'unassigned'); });
    return hit;
  }
  function matrix(c) {
    const hit = matches(c), maxT = Math.max(1, ...c.stages.map(r => r.n_tools));
    const rows = c.stages.map(r => {
      const mk = Object.entries(r.markers).map(([k, n]) => `${k} ${n}`).join(' · ');
      const ac = Object.entries(r.access).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(' · ');
      const dim = hit && !hit.has(r.id) ? ' dim' : '';
      return `<tr tabindex="0" data-stage="${esc(r.id)}" class="${dim.trim()}" aria-selected="${st.stage === r.id}">
        <td class="pl-st"><b>${esc(r.label)}</b><small>${esc(r.covers)}</small></td>
        <td class="n">${esc(fmt(r.n_skills))}</td><td class="n">${esc(fmt(r.n_tools))}</td>
        <td style="min-width:130px"><div class="pl-seg" role="img" aria-label="${esc(r.label)}: ${esc(fmt(r.n_tools))} tools"><i style="width:${Math.round(100 * r.n_tools / maxT)}%"></i></div></td>
        <td class="pl-mk">${esc(mk || '—')}</td><td class="pl-mk">${esc(ac || '—')}</td>
        <td class="n">${r.n_flags ? `<span class="pl-flag" title="Flags in this stage">${esc(fmt(r.n_flags))}</span>` : ''}</td></tr>`;
    }).join('');
    return `<div class="card" style="overflow-x:auto"><table class="pl-mx"><thead><tr><th>Stage</th><th class="n">Skills</th><th class="n">Tools</th><th>Share of tools</th><th>Markers</th><th>Access rows ${info(esc(ACCESS_HELP), 'About access rows')}</th><th class="n">Flags</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  const toolHtml = (t, c) => {
    const tags = (t.marker ? `<span class="pl-tag">${esc(t.marker)}</span>` : '') + (t.access ? `<span class="pl-tag" title="Access row">${esc(t.access)}</span>` : '');
    const first = String(t.d || '').split('\n')[0];
    return `<div class="pl-tl" id="tool-${esc(t.n)}"><span class="nm">${esc(t.n)}</span>${tags}<span class="meta">${esc(first)}</span>
      <span class="meta">Inputs: ${esc((t.params || []).join(', ') || 'none')}${t.skills.length ? ' · named by ' + esc(t.skills.join(', ')) : ''}${t.also.length ? ' · also used in ' + esc(t.also.join(', ')) : ''}</span>
      <details><summary>Input schema</summary><pre>${esc(t.schema)}</pre></details></div>`;
  };
  const skillHtml = s => `<div class="pl-sk"><span class="nm">${esc(s.n)}</span>${s.stages.length > 1 ? `<span class="pl-tag">also ${esc(s.stages.slice(1).join(', '))}</span>` : ''}
    <div class="meta" style="color:var(--mut);font-size:var(--t-s)">${esc(s.d)}</div>
    ${s.steps.length ? `<ol>${s.steps.map(x => `<li>${esc(x.text)} <small>${esc(x.file)}:${esc(fmt(x.line))}</small></li>`).join('')}</ol>` : ''}</div>`;
  function panel(c) {
    const r = c.stages.find(x => x.id === st.stage); if (!r) return '';
    const q = lc(st.q), keep = x => !q || lc(x.n).includes(q) || lc(x.d).includes(q);
    const skills = c.skills.filter(s => (s.stages[0] || 'unassigned') === r.id).filter(keep);
    const tools = c.tools.filter(t => (t.stage || 'unassigned') === r.id).filter(keep);
    const flags = r.flags || [];
    return `<div class="card raised pl-panel" id="pl-panel"><h3>${esc(r.label)}</h3><div class="meta">${esc(r.covers)}</div>
      <h4>Skills (${esc(fmt(skills.length))})</h4>${skills.map(skillHtml).join('') || empty('No skill has this stage' + (q ? ' that matches the search.' : '.'))}
      <h4>Tools (${esc(fmt(tools.length))})</h4>${tools.map(t => toolHtml(t, c)).join('') || empty('No tool is assigned here' + (q ? ' that matches the search.' : '.'))}
      ${flags.length ? `<h4>Flags (${esc(fmt(flags.length))})</h4>${flags.map(f => `<div class="pl-tl"><span class="nm">${esc(f.c)}</span><span class="meta mono">${esc(f.w)}</span><span class="meta">${esc(f.m)}</span></div>`).join('')}` : ''}</div>`;
  }
  function unassigned(c) {
    const orph = c.tools.filter(t => c.orphans.includes(t.n)), sl = c.skills.filter(s => c.stageless.includes(s.n));
    return `<section class="pl-sec">${H.header({ title: 'Unassigned', sub: 'Tools no skill names and no marker covers, and skills with no valid stage.' })}
      ${orph.length || sl.length ? sl.map(skillHtml).join('') + orph.map(t => toolHtml(t, c)).join('') : empty('None.')}</section>`;
  }
  function marked(c) {
    const rows = c.marked.map(m => `<tr><td class="mono">${esc(m.tool)}</td><td>${esc(m.kind)}</td><td>${esc(m.why)}${m.accepted ? ' <i>Access row differs: ' + esc(m.accepted) + '</i>' : ''}</td><td class="mono">${esc(m.access || 'no access row')}</td><td>${esc(m.skills.join(', ') || 'none')}</td></tr>`).join('');
    return `<section class="pl-sec">${H.header({ title: 'Marked tools', infoHtml: esc(M.markers || ''), sub: 'A marked tool that no skill names is not an orphan.' })}
      ${rows ? `<div class="card" style="overflow-x:auto"><table><thead><tr><th>Tool</th><th>Marker</th><th>Why</th><th>Access row</th><th>Named by</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('No tool is marked.')}</section>`;
  }
  function flags(c) {
    const rows = c.flags.map(f => `<tr><td class="mono">${esc(f.code)}</td><td class="mono">${esc(f.where)}</td><td>${esc(f.msg)}${f.other ? '<br><span class="meta">' + esc(f.other) + '</span>' : ''}</td></tr>`).join('');
    return `<section class="pl-sec">${H.header({ title: 'Flags', infoHtml: esc(M.flags || ''), sub: 'Mechanical findings, listed for the researcher to judge. The platform rules on none of them.' })}
      ${rows ? `<div class="card" style="overflow-x:auto"><table><thead><tr><th>Code</th><th>Where</th><th>Finding</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('No flags.')}</section>`;
  }
  function cap() {
    if (!C) return empty('The capability catalog could not be built' + (P.catalog_error ? ': ' + P.catalog_error : '.'));
    const cmds = (P.commands || []).map(x => `<div><code>${esc(x.cmd)}</code> <span class="meta">${esc(x.what)}</span></div>`).join('');
    const f = C.footer || {};
    return `${H.header({ title: 'What the platform can do', infoHtml: esc(M.catalog || ''), sub: 'Tools, skills and flags by lifecycle stage.' })}
      ${kpis(C)}${countCheck(C)}
      <details class="pl-line"><summary>Commands that build and serve the hubs</summary><div class="pl-cmds">${cmds}</div></details>
      <div class="pl-bar"><input class="pl-in" type="search" id="pl-q" placeholder="Search tools and skills" aria-label="Search tools and skills" value="${esc(st.q)}">
        <span class="meta">Click a stage for its skills, tools and flags.</span></div>
      <section>${H.header({ title: 'Stages', infoHtml: esc(M.matrix || '') })}${matrix(C)}</section>
      ${panel(C)}${unassigned(C)}${marked(C)}${flags(C)}
      <div class="pl-foot">Code ${esc(f.code || '')} · decisions ${esc(f.decisions_sha || 'not derived')} · skills ${esc(Object.entries(f.skills || {}).map(([k, v]) => k + ' ' + v).join(', '))}</div>`;
  }
  function wireCap() {
    main.querySelectorAll('[data-stage]').forEach(el => {
      const f = () => go({ stage: st.stage === el.dataset.stage ? '' : el.dataset.stage });
      el.addEventListener('click', f); el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); f(); } });
    });
    const q = main.querySelector('#pl-q');
    if (q) q.addEventListener('input', () => { H.hash.set({ q: q.value }); readHash(); const pos = q.selectionStart; render(); const n = main.querySelector('#pl-q'); if (n) { n.focus(); n.setSelectionRange(pos, pos); } });
  }

  /* ---------------- Backlog ---------------- */
  const SL = { ready: 'Ready', blocked: 'Blocked', specified: 'Specified', done: 'Done', parked: 'Parked' };
  const SHELP = {
    ready: 'Open, with every dependency done. Sorted by how many ideas it unlocks.',
    blocked: 'Waiting on a dependency that is not done.',
    specified: 'Accepted, with a spec or plan; not built.',
    done: 'Built.',
    parked: 'Parked or rejected.',
  };
  const byId = () => Object.fromEntries(B.ideas.map(i => [i.id, i]));
  function visible() {
    const q = lc(st.q);
    return B.ideas.filter(i => (!st.area || i.area === st.area) && (!st.state || i.state === st.state) && (!st.slice || i.slice === st.slice) &&
      (!q || lc(i.id + ' ' + i.title + ' ' + i.what).includes(q)));
  }
  function areaBars() {
    const total = Math.max(1, ...B.areas.map(a => Object.values(B.by_area[a]).reduce((x, y) => x + y, 0)));
    return `<div class="pl-areas" role="group" aria-label="Ideas per area">${B.areas.map(a => {
      const row = B.by_area[a], n = Object.values(row).reduce((x, y) => x + y, 0);
      const seg = (B.states || []).map(s => row[s] ? `<i class="pl-s-${s}" style="width:${100 * row[s] / total}%;background:var(--sc)" title="${esc(SL[s])}: ${esc(fmt(row[s]))}"></i>` : '').join('');
      return `<button type="button" class="pl-ar" data-area="${esc(a)}" aria-pressed="${st.area === a}"><span class="t">${esc(a)}</span><span class="pl-stack">${seg}</span><span class="c">${esc(fmt(n))}</span></button>`;
    }).join('')}</div>
    <div class="pl-legend">${(B.states || []).map(s => `<span><i class="pl-s-${s}" style="background:var(--sc)"></i>${esc(SL[s])} ${esc(fmt(B.by_state[s]))}</span>`).join('')}</div>`;
  }
  const card = i => `<button type="button" class="pl-card pl-s-${esc(i.state)}" data-idea="${esc(i.id)}" aria-current="${st.idea === i.id}">
    <span class="id">${esc(i.id)}</span><span class="ti">${esc(i.title)}</span>
    <span class="ft"><span>${esc(i.area)}</span>${i.unmet.length ? `<span>${esc(fmt(i.unmet.length))} unmet</span>` : ''}${i.unlocks ? `<span>unlocks ${esc(fmt(i.unlocks))}</span>` : ''}</span></button>`;
  function board(list) {
    return `<div class="pl-cols">${(B.states || []).map(s => {
      const items = list.filter(i => i.state === s).sort((a, b) => (s === 'ready' ? b.unlocks - a.unlocks : 0) || a.n - b.n);
      return `<div class="pl-col pl-s-${s}"><h3><i></i>${esc(SL[s])} <span>${esc(fmt(items.length))}</span></h3><div class="help">${esc(SHELP[s])}</div>${items.map(card).join('') || '<div class="pl-more">None.</div>'}</div>`;
    }).join('')}</div>`;
  }
  function tree(list) {
    const ids = new Set(list.map(i => i.id)), all = byId();
    const nodes = list.filter(i => i.deps.some(d => ids.has(d)) || i.dependents.some(d => ids.has(d)));
    if (!nodes.length) return empty('No idea in this view has a recorded idea dependency.');
    const layers = {}; nodes.forEach(n => (layers[n.layer] = layers[n.layer] || []).push(n));
    const keys = Object.keys(layers).map(Number).sort((a, b) => a - b), W = 170, Hh = 22, pos = {};
    let maxRows = 0;
    keys.forEach((k, ci) => { layers[k].sort((a, b) => a.n - b.n).forEach((n, r) => { pos[n.id] = [30 + ci * W, 24 + r * Hh]; }); maxRows = Math.max(maxRows, layers[k].length); });
    const w = 60 + keys.length * W, h = 40 + maxRows * Hh;
    const lit = new Set(); const hov = st.idea;
    if (hov && pos[hov]) { const walk = (id, f) => { (all[id][f] || []).forEach(x => { if (pos[x] && !lit.has(x)) { lit.add(x); walk(x, f); } }); }; lit.add(hov); walk(hov, 'deps'); walk(hov, 'dependents'); }
    const edges = nodes.flatMap(n => n.deps.filter(d => pos[d]).map(d => {
      const [x1, y1] = pos[d], [x2, y2] = pos[n.id], on = lit.has(d) && lit.has(n.id), off = hov && !on;
      return `<path class="ed${on ? ' on' : ''}${off ? ' off' : ''}" d="M${x1},${y1} C${x1 + 70},${y1} ${x2 - 70},${y2} ${x2},${y2}"/>`;
    })).join('');
    const circ = nodes.map(n => `<g class="nd pl-s-${esc(n.state)}${hov && !lit.has(n.id) ? ' off' : ''}${st.idea === n.id ? ' on' : ''}" data-idea="${esc(n.id)}" transform="translate(${pos[n.id][0]},${pos[n.id][1]})"><title>${esc(n.id + ' ' + n.title + ' (' + SL[n.state] + ')')}</title><circle r="7"/><text x="12" y="3">${esc(n.id.replace('IDEA-', ''))} ${esc(n.title.slice(0, 18))}</text></g>`).join('');
    const listAlt = `<details style="margin-top:12px"><summary class="meta">The same dependencies as a list</summary><ul style="font-size:var(--t-s)">${nodes.map(n => `<li><a href="#" data-idea="${esc(n.id)}">${esc(n.id)} ${esc(n.title)}</a> (${esc(SL[n.state])})${n.deps.length ? ', depends on ' + esc(n.deps.join(', ')) : ''}</li>`).join('')}</ul></details>`;
    return `<div class="card pl-tree">${H.header({ title: 'Dependency tree', infoHtml: esc(M.tree || ''), sub: 'Dependencies on the left. Select an idea to light its chain.' })}<svg width="${w}" height="${h}" role="img" aria-label="Dependency tree of backlog ideas">${edges}${circ}</svg>${listAlt}</div>`;
  }
  function detail() {
    const i = byId()[st.idea];
    if (!i) return `<aside class="card pl-det" aria-label="Idea detail"><div class="meta">Select an idea to read its detail.</div></aside>`;
    const fld = (k, v) => v ? `<div class="f"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>` : '';
    const links = i.deps.length ? i.deps.map(d => `<a data-idea="${esc(d)}">${esc(d)}</a>`).join(', ') : '';
    const inSel = st.sel.includes(i.id);
    return `<aside class="card pl-det pl-s-${esc(i.state)}" aria-label="Idea detail"><div class="meta">${esc(i.id)} · ${esc(i.area)}</div><h3>${esc(i.title)}</h3>
      <div class="f"><span class="pl-tag" style="margin:0;color:var(--sc)">${esc(SL[i.state])}</span></div>
      ${fld('Status (as written)', i.status_raw)}${fld('Added', i.added)}${fld('Slice', i.slice)}
      ${links ? `<div class="f"><div class="k">Depends on</div><div class="v">${links}</div></div>` : fld('Depends on', i.depends_raw)}
      ${i.unmet.length ? fld('Still needs first', i.unmet.join(', ')) : ''}${fld('Unlocks', i.unlocks ? String(i.unlocks) + ' open ideas' : '')}
      ${fld('What', i.what)}${fld('Why', i.why)}${fld('Rigour notes', i.rigour)}${fld('Open questions', i.open)}
      <button type="button" class="btn" id="pl-sel">${inSel ? 'Remove from selection' : 'Add to selection'}</button></aside>`;
  }
  function brief() {
    const all = byId();
    return 'Brief for the orchestrator. Ideas selected from the backlog:\n' + st.sel.map(id => {
      const i = all[id]; if (!i) return '';
      return '- ' + i.id + ' ' + i.title + ' (' + SL[i.state] + (i.unmet.length ? '; first needs ' + i.unmet.join(', ') : '') + ')\n  What: ' + i.what;
    }).join('\n') + '\nWork on them in dependency order, one atomic task each. Nothing here is a decision.';
  }
  function tray() {
    if (!st.sel.length) return '';
    const all = byId();
    return `<div class="card pl-tray"><b>Selection (${esc(fmt(st.sel.length))})</b><ul>${st.sel.map(id => { const i = all[id]; return i ? `<li><a data-idea="${esc(id)}">${esc(id)}</a> ${esc(i.title)}${i.unmet.length ? ' <span class="meta">needs ' + esc(i.unmet.join(', ')) + ' first</span>' : ''}</li>` : ''; }).join('')}</ul>
      <button type="button" class="btn" id="pl-copy">Copy brief</button> <button type="button" class="btn" id="pl-clear">Clear</button> <span class="meta" id="pl-copied" role="status"></span>
      <div class="meta" style="margin-top:6px">Kept in this page only. Nothing is written back.</div></div>`;
  }
  function backlog() {
    if (!B) return empty('The backlog could not be read' + (P.backlog_error ? ': ' + P.backlog_error : '.'));
    if (!B.found) return empty('The backlog document was not found. Set FACTORY_BACKLOG to its path.');
    const list = visible();
    const chips = `<button class="chip" data-area="" aria-pressed="${!st.area}">All areas</button>` + B.areas.map(a => `<button class="chip" data-area="${esc(a)}" aria-pressed="${st.area === a}">${esc(a)}</button>`).join('');
    const note = st.area && B.notes[st.area] ? `<p class="note">${esc(B.notes[st.area])}</p>` : '';
    return `${H.header({ title: 'Backlog', infoHtml: esc(M.backlog || ''), sub: 'Every idea on the board, ready ones first by how many they unlock.' })}
      ${areaBars()}
      <div class="pl-bar"><div class="seg" role="group" aria-label="View"><button data-view="board" aria-pressed="${st.view === 'board'}">Board</button><button data-view="tree" aria-pressed="${st.view === 'tree'}">Dependency tree</button></div>
        <input class="pl-in" type="search" id="pl-q" placeholder="Filter ideas" aria-label="Filter ideas" value="${esc(st.q)}">
        <select class="pl-sel" id="pl-slice" aria-label="Slice"><option value="">All slices</option>${B.slices.map(s => `<option value="${esc(s)}"${st.slice === s ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select>
        <span class="meta" role="status">${esc(fmt(list.length))} of ${esc(fmt(B.ideas.length))} ideas</span></div>
      <div class="pl-bar" style="margin-top:0">${chips}</div>${note}
      <div class="pl-lay"><div>${st.view === 'tree' ? tree(list) : board(list)}</div><div>${detail()}${tray()}</div></div>
      <div class="pl-foot">Source ${esc(B.path)} · digest ${esc(B.digest)}</div>`;
  }
  function wireBacklog() {
    main.querySelectorAll('[data-area]').forEach(el => el.addEventListener('click', () => go({ area: st.area === el.dataset.area ? '' : el.dataset.area })));
    main.querySelectorAll('[data-view]').forEach(el => el.addEventListener('click', () => go({ view: el.dataset.view })));
    main.querySelectorAll('[data-idea]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); go({ idea: el.dataset.idea }); }));
    const sl = main.querySelector('#pl-slice'); if (sl) sl.addEventListener('change', () => go({ slice: sl.value }));
    const q = main.querySelector('#pl-q');
    if (q) q.addEventListener('input', () => { H.hash.set({ q: q.value }); readHash(); const pos = q.selectionStart; render(); const n = main.querySelector('#pl-q'); if (n) { n.focus(); n.setSelectionRange(pos, pos); } });
    const s = main.querySelector('#pl-sel');
    if (s) s.addEventListener('click', () => { st.sel = st.sel.includes(st.idea) ? st.sel.filter(x => x !== st.idea) : [...st.sel, st.idea]; render(); });
    const cl = main.querySelector('#pl-clear'); if (cl) cl.addEventListener('click', () => { st.sel = []; render(); });
    const cp = main.querySelector('#pl-copy');
    if (cp) cp.addEventListener('click', () => {
      const say = t => { const n = main.querySelector('#pl-copied'); if (n) n.textContent = t; };
      try { navigator.clipboard.writeText(brief()).then(() => say('Copied.'), () => say('Copy was blocked by the browser.')); } catch (e) { say('Copy was blocked by the browser.'); }
    });
  }

  function render() {
    const hdr = H.header({ title: 'Platform', sub: 'How a project runs, what the platform can do, and what is planned.', level: 1 });
    const tabs = `<div class="pl-tabs"><div class="seg" role="tablist" aria-label="View">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-pressed="${k === st.tab}">${l}</button>`).join('')}</div></div>`;
    const body = st.tab === 'how' ? HUB_HOWTO.render(H, P, st) : st.tab === 'cap' ? cap() : backlog();
    main.innerHTML = hdr + tabs + body;
    main.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => go({ tab: b.dataset.tab })));
    if (st.tab === 'how') HUB_HOWTO.wire(main, st, go, render); else if (st.tab === 'cap') wireCap(); else wireBacklog();
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
});
