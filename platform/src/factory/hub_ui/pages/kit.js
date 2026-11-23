/* Brand kit page. Payload: shell. Tokens, the themes and contrast ratios are read live from the
   CSS in each theme (the theme attribute is switched synchronously and the colours resolved by the
   browser); nothing about colour is typed here. */
HUB.load(['shell']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'kit', crumb: 'Brand kit' });
  const { esc, fmt, HUMAN, LAYERS } = H;
  const RF = H.RF, W = RF.works || [];

  if (!document.getElementById('kit-style')) {
    const st = document.createElement('style'); st.id = 'kit-style';
    st.textContent = `
section.k{margin-top:44px}
.kit-sw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px;margin-top:10px}
.kit-sw{background:var(--surface);border-radius:var(--r);overflow:hidden}
.kit-sw .c{height:40px}
.kit-sw .m{padding:8px 10px;font-size:var(--t-xs);color:var(--mut);line-height:1.5}
.kit-sw .m b{color:var(--fg);font:500 var(--t-s) var(--f-mono)}
.kit-grp{margin-top:20px;font:600 var(--t-s) var(--f-ui);color:var(--mut)}
.kit-themes{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:var(--gap);margin-top:14px}
.kit-th{border-radius:var(--r);overflow:hidden;border:2px solid transparent;text-align:left;padding:0;cursor:pointer;font:inherit;display:block;width:100%}
.kit-th[aria-pressed=true]{border-color:var(--acc)}
.kit-th .top{padding:14px 14px 10px}
.kit-th .nm{font:600 var(--t-m) var(--f-ui)}
.kit-th .strip{display:flex;height:14px;margin-top:10px;border-radius:3px;overflow:hidden}.kit-th .strip i{flex:1}
.kit-th .samp{font-size:var(--t-s);margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.kit-th .samp span{padding:3px 8px;border-radius:4px}
.kit-th .rat{padding:10px 14px 12px;display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:3px 12px;font-size:var(--t-xs);background:var(--surface);color:var(--mut)}
.kit-th .rat .v{font-family:var(--f-mono);text-align:right}
.kit-th .rat .ok{color:var(--inc)}.kit-th .rat .no{color:var(--exc)}
.pass{color:var(--inc)}.fail{color:var(--exc)}
.kit-role{display:grid;grid-template-columns:200px minmax(0,1fr);gap:6px 24px;align-items:baseline;border-bottom:1px solid var(--hair);padding:12px 0}
.kit-role .k{font:var(--t-xs) var(--f-mono);color:var(--mut)}
.kit-states{display:grid;grid-template-columns:90px repeat(5,auto);gap:12px 18px;align-items:center;justify-content:start;margin-top:4px;overflow-x:auto}
.kit-states .k{font-size:var(--t-xs);color:var(--mut)}
.sim-hover.btn{background:var(--line)}.sim-hover.btn.primary{filter:brightness(1.08);background:var(--acc)}
.sim-focus{outline:2px solid var(--acc);outline-offset:2px}
.kit-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:var(--gap);margin-top:14px}
.kit-seq{display:flex;border-radius:6px;overflow:hidden;margin-top:10px}.kit-seq i{flex:1;height:28px}
.kit-rules{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:10px;max-width:80ch}
.kit-rules li{padding-left:18px;position:relative}.kit-rules li:before{content:'';position:absolute;left:0;top:.65em;width:8px;height:2px;background:var(--mut)}
.kit-works{list-style:none;margin:0;padding:0}
.kit-works li{display:flex;gap:10px;align-items:baseline;padding:8px 6px;border-top:1px solid var(--hair);cursor:pointer;border-radius:4px}
.kit-works li:first-child{border-top:0}.kit-works li:hover{background:var(--raised)}
.kit-works .y{margin-left:auto;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
.kit-works .dot{align-self:center}
@media (max-width:760px){.kit-role{grid-template-columns:1fr}.kit-themes{grid-template-columns:minmax(0,1fr)}}`;
    document.head.appendChild(st);
  }

  /* ---- colour reading: resolve each token through the browser, per theme ---- */
  const TOK = ['--bg', '--surface', '--raised', '--line', '--hair', '--fg', '--mut', '--dim', '--acc', '--acc-ink', '--inc', '--exc',
    ...HUMAN.map(h => h[2]), '--h-null', ...LAYERS.map(l => l[2]), '--seq-0', '--seq-1', '--seq-2', '--seq-3', '--seq-4'];
  const parse = s => {
    const n = (s.match(/-?\d*\.?\d+(?:e-?\d+)?/g) || []).map(Number);
    if (/^color\(/.test(s)) return n.slice(0, 3).map(v => v * 255);
    return n.slice(0, 3);
  };
  const hex = c => '#' + c.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }); return .2126 * r + .7152 * g + .0722 * b; };
  const cr = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  function readTheme(t) {
    const el = document.documentElement, prev = el.dataset.theme;
    el.dataset.theme = t;
    const probe = document.createElement('i'); probe.style.cssText = 'position:absolute;visibility:hidden'; document.body.appendChild(probe);
    const o = {};
    TOK.forEach(k => { probe.style.color = ''; probe.style.color = `var(${k})`; o[k] = parse(getComputedStyle(probe).color); });
    probe.remove();
    if (prev) el.dataset.theme = prev; else delete el.dataset.theme;
    return o;
  }
  const THEMES = H.THEMES;
  const TH = Object.fromEntries(THEMES.map(([k]) => [k, readTheme(k)]));
  const PAIRS = [
    ['Body text', '--fg', '--bg', 4.5], ['Body text on card', '--fg', '--surface', 4.5], ['Secondary text', '--mut', '--bg', 4.5], ['Secondary text on card', '--mut', '--surface', 4.5],
    ['Secondary text on raised', '--mut', '--raised', 4.5], ['Tertiary (notes, axes)', '--dim', '--bg', 4.5], ['Tertiary on card', '--dim', '--surface', 4.5],
    ['Link and accent text', '--acc', '--bg', 4.5], ['Primary button', '--acc-ink', '--acc', 4.5], ['Included (+)', '--inc', '--bg', 4.5], ['Excluded (−)', '--exc', '--bg', 4.5],
    ...HUMAN.slice(0, 6).map(h => ['Human: ' + h[1].toLowerCase() + ' (graphic)', h[2], '--bg', 3]),
    ['Layer: core (graphic)', '--l-core', '--bg', 3], ['Layer: adjacent (graphic)', '--l-adjacent', '--bg', 3],
  ];
  const KEY = [['Body text', '--fg', '--bg', 4.5], ['Secondary text', '--mut', '--bg', 4.5], ['Tertiary text', '--dim', '--bg', 4.5], ['Accent text', '--acc', '--bg', 4.5], ['Primary button', '--acc-ink', '--acc', 4.5]];
  const ratio = (t, f, b) => cr(TH[t][f], TH[t][b]);
  const fails = t => PAIRS.filter(([, f, b, m]) => ratio(t, f, b) < m);
  const cssvar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const SW = [
    ['Ground and surfaces', ['--bg', '--surface', '--raised', '--line', '--hair']], ['Text', ['--fg', '--mut', '--dim']],
    ['Accent: one job', ['--acc', '--acc-ink']], ['Outcome pair, with + and −', ['--inc', '--exc']],
    ['Human role (ordered)', [...HUMAN.map(h => h[2]), '--h-null']], ['Layer', LAYERS.slice(0, 6).map(l => l[2])], ['Sequential', ['--seq-0', '--seq-1', '--seq-2', '--seq-3', '--seq-4']],
  ];
  const NAMES = Object.fromEntries([...HUMAN.map(h => [h[2], h[1]]), ['--h-null', 'Not coded']]);
  const panel = (what, read, how) => `<b>What it shows</b> ${what}${read ? `<p><span class=k>How to read it.</span> ${read}</p>` : ''}${how ? `<p><span class=k>How it’s computed.</span> ${how}</p>` : ''}`;

  const cur = () => document.documentElement.dataset.theme || 'dark';
  const curName = () => (THEMES.find(t => t[0] === cur()) || [, cur()])[1];
  const inc = H.stats.included, nCore = W.filter(w => w.layer === 'core').length;
  const topWorks = W.slice().sort((a, b) => (b.cic || 0) - (a.cic || 0)).slice(0, 5);
  const allOk = THEMES.filter(([k]) => !fails(k).length).length;

  function render() {
    const t = cur(), T = TH[t] || TH.dark;
    const themeCards = THEMES.map(([k, name]) => {
      const c = TH[k], hx = x => hex(x), nf = fails(k).length;
      return `<button class="kit-th" data-theme-pick="${k}" aria-pressed="${k === t}" style="background:${hx(c['--bg'])};color:${hx(c['--fg'])}">
        <div class="top"><div class="nm">${esc(name)}</div>
          <div class="strip">${['--bg', '--surface', '--raised', '--line', '--acc', '--inc', '--exc', '--h-none', '--h-goal', '--h-review', '--h-feedback', '--h-collab'].map(x => `<i style="background:${hx(c[x])}"></i>`).join('')}</div>
          <div class="samp"><span style="background:${hx(c['--surface'])};color:${hx(c['--mut'])}">Secondary</span><span style="background:${hx(c['--acc'])};color:${hx(c['--acc-ink'])}">Primary</span><span style="color:${hx(c['--acc'])}">Link</span></div></div>
        <div class="rat" style="background:${hx(c['--surface'])};color:${hx(c['--mut'])}">${KEY.map(([n, f, b, m]) => { const r = ratio(k, f, b); return `<span>${n}</span><span class="v">${r.toFixed(2)}</span><span class="${r >= m ? 'ok' : 'no'}" style="color:${hx(c[r >= m ? '--inc' : '--exc'])}">${r >= m ? '✓' : '✗'}</span>`; }).join('')}
          <span style="grid-column:1/-1;margin-top:4px">${nf ? `${fmt(nf)} of ${fmt(PAIRS.length)} pairs fall short` : `All ${fmt(PAIRS.length)} pairs pass`}</span></div></button>`;
    }).join('');
    const rows = PAIRS.map(([n, f, b, min]) => {
      const r = ratio(t, f, b);
      return `<tr><td>${n}</td><td class="mono">${f} on ${b}</td><td class="r">${min}</td><td class="r ${r >= min ? 'pass' : 'fail'}">${r.toFixed(2)} ${r >= min ? '✓' : '✗'}</td></tr>`;
    }).join('');
    const tt = n => cssvar(n);
    main.innerHTML = `
<header style="padding:20px 0 0;max-width:72ch">
  ${H.header({ kicker: 'Design system · tokens live in the shared stylesheet', title: 'Brand kit', level: 1 })}
  <p class="lead" style="margin-top:14px">Quiet ground, one accent, hue that means one thing. ${fmt(allOk)} of ${fmt(THEMES.length)} themes pass every colour check.${H.info(panel('The colours, type and components every page uses, in every theme.', 'Click a theme card to switch to it. Ticks and crosses are measured, not declared.', 'Every colour is read from the live stylesheet: the theme attribute is switched, and the browser resolves each token. Contrast uses the WCAG 2.x relative-luminance formula; the thresholds are 4.5 for text and 3 for graphics and large text.'), 'How the kit is measured')}</p>
</header>

<section class="k">${H.header({ title: 'Themes', sub: `Showing: ${esc(curName())}`, infoHtml: panel('Each theme as it looks, with the contrast of its five most important pairs.', 'Left of each tick is the measured ratio; ✓ means it meets its threshold (4.5 for text).', 'Per theme, from the resolved token colours.') })}
  <div class="kit-themes">${themeCards}</div></section>

<section class="k">${H.header({ title: 'Colour', sub: `Tokens of the current theme, ${esc(curName())}`, infoHtml: panel('The colour tokens of the theme you are viewing.', 'Each swatch shows the token and the colour it resolves to.', 'Read from the stylesheet for the current theme.') })}
  ${SW.map(([g, ks]) => `<div class="kit-grp">${g}</div><div class="kit-sw-grid">${ks.map(k => `<div class="kit-sw"><div class="c" style="background:var(${k})"></div><div class="m"><b>${k}</b>${NAMES[k] ? ' · ' + esc(NAMES[k]) : ''}<br><span class="mono">${hex(T[k])}</span></div></div>`).join('')}</div>`).join('')}
</section>

<section class="k">${H.header({ title: 'Contrast', sub: `${esc(curName())}`, infoHtml: panel('Whether text and graphics are readable on their ground.', '', 'Thresholds are 4.5 for text and 3 for graphics and large text. The tick or cross is computed from the ratio.') })}
  <div class="card" style="margin-top:12px;overflow-x:auto"><table class="t" style="cursor:default"><thead><tr><th>Pair</th><th>Tokens</th><th class="r">Min</th><th class="r">Ratio</th></tr></thead><tbody>${rows}</tbody></table></div></section>

<section class="k">${H.header({ title: 'Type' })}
  <div class="card" style="margin-top:12px;padding:8px 24px">
    <div class="kit-role"><span class="k">.display · Newsreader ${tt('--t-xxl')}</span><span class="display">${esc(H.pretty(RF.slug))}</span></div>
    <div class="kit-role"><span class="k">.lead · Newsreader ${tt('--t-xl')}</span><span class="lead">${fmt(inc)} papers made it through screening.</span></div>
    <div class="kit-role"><span class="k">.h2 · Inter 600 ${tt('--t-l')}</span><span class="h2">Where the records went</span></div>
    <div class="kit-role"><span class="k">body · Inter ${tt('--t-m')}</span><span>Body text carries explanation. Tabular figures: ${fmt(inc)}.</span></div>
    <div class="kit-role"><span class="k">.meta · Inter ${tt('--t-s')}</span><span class="meta">Secondary information, counts, denominators.</span></div>
    <div class="kit-role"><span class="k">ⓘ panel · Inter ${tt('--t-s')}</span><span>Method and reading notes live behind an ⓘ button, not in the page body.</span></div>
    <div class="kit-role"><span class="k">.mono · JetBrains Mono</span><span class="mono">${esc((RF.generated || '').replace('T', ' ').slice(0, 16))} · ${fmt(inc)} papers</span></div>
    <div class="kit-role" style="border:0"><span class="k">.quote · Newsreader italic</span><blockquote class="quote" style="margin:0">“Evidence quotes are set as quotations, in the serif.”</blockquote></div>
  </div></section>

<section class="k">${H.header({ title: 'Components', sub: 'Hover and focus are simulated so they show at rest.' })}
  <div class="card" style="margin-top:12px"><div class="kit-states">
    <span></span><span class="k">Rest</span><span class="k">Hover</span><span class="k">Selected</span><span class="k">Disabled</span><span class="k">Focus</span>
    <span class="k">Button</span><button class="btn">Open</button><button class="btn sim-hover">Open</button><span class="meta">not used</span><button class="btn" disabled>Open</button><button class="btn sim-focus">Open</button>
    <span class="k">Primary</span><button class="btn primary">Browse papers</button><button class="btn primary sim-hover">Browse papers</button><span class="meta">not used</span><button class="btn primary" disabled>Browse papers</button><button class="btn primary sim-focus">Browse papers</button>
    <span class="k">Chip</span><button class="chip">Core <span class="n">${fmt(nCore)}</span></button><button class="chip" style="background:var(--line);color:var(--fg)">Core <span class="n">${fmt(nCore)}</span></button><button class="chip" aria-pressed="true">Core <span class="n">${fmt(nCore)}</span></button><button class="chip" disabled>Core <span class="n">${fmt(nCore)}</span></button><button class="chip sim-focus">Core <span class="n">${fmt(nCore)}</span></button>
    <span class="k">Segment</span><div class="seg"><button aria-pressed="true">Flow</button><button>Every record</button></div><span></span><span></span><span></span><span></span>
  </div></div>
  <div class="kit-cols">
    <div class="card"><h3 class="h3">Section header</h3><p class="meta" style="margin:2px 0 14px">A title of one to four words, in sentence case, never a question. Optional kicker above, one-line subtitle below, ⓘ beside the title.</p>
      ${H.header({ kicker: `Living review · ${H.term('protocol')}`, title: 'Most cited', sub: 'Cited here, largest first', infoHtml: panel('The papers other papers in the corpus build on most.', 'Longer bar, more citations.', 'Citation links between papers in the corpus, counted per cited paper.') })}</div>
    <div class="card"><h3 class="h3">Info panel and term</h3><p class="meta" style="margin:2px 0 14px">ⓘ opens on hover or focus; click pins it, Esc closes. A dotted word carries a plain definition.</p>
      <p style="margin:0">Hover this number ${H.info(panel('The papers that passed every screening step.', '', 'The included count from the screening flow.'), 'About this number')} <b class="num">${fmt(inc)}</b></p>
      <p style="margin:12px 0 0">Papers passed ${H.term('screened', 'screening')} and are grouped by ${H.term('layer')} and ${H.term('human', 'human role')}.</p></div>
    <div class="card"><h3 class="h3">Drawer and works list</h3><p class="meta" style="margin:2px 0 10px">Every paper opens in the same side drawer, with each value beside its quotation.</p>
      <ul class="kit-works">${topWorks.map(w => `<li data-open="${esc(w.id)}" tabindex="0" role="button"><span class="dot" style="background:var(${(LAYERS.find(l => l[0] === w.layer) || [, , '--l-unlayered'])[2]})"></span><span>${esc(w.title)}</span><span class="y">${esc(w.year || '')}</span></li>`).join('')}</ul>
      ${topWorks.length ? `<p style="margin:12px 0 0"><button class="btn" data-open="${esc(topWorks[0].id)}">Open a paper</button></p>` : '<p class="meta">Papers appear here once the corpus is built.</p>'}</div>
  </div></section>

<section class="k">${H.header({ title: 'Data scales' })}
  <div class="kit-cols">
    <div class="card"><h3 class="h3">Human role</h3><p class="meta" style="margin:2px 0 10px">Ordinal: least to most human.</p>
      <div style="display:grid;gap:6px">${HUMAN.map(h => `<div style="display:flex;gap:8px;align-items:center"><span class="dot" style="background:var(${h[2]})"></span><span class="meta" style="color:var(--fg)">${esc(h[1])}</span></div>`).join('')}<div style="display:flex;gap:8px;align-items:center"><span class="dot" style="border:1.5px solid var(--h-null)"></span><span class="meta" style="color:var(--fg)">Not coded (ring only)</span></div></div></div>
    <div class="card"><h3 class="h3">Layer</h3><p class="meta" style="margin:2px 0 10px">Categorical, one hue per layer.</p>
      <div style="display:grid;gap:6px">${LAYERS.slice(0, 5).map(h => `<div style="display:flex;gap:8px;align-items:center"><span class="dot" style="background:var(${h[2]})"></span><span class="meta" style="color:var(--fg)">${h[1]}</span></div>`).join('')}</div></div>
    <div class="card"><h3 class="h3">Sequential</h3><p class="meta" style="margin:2px 0 10px">One hue, dark to light, for density.</p>
      <div class="kit-seq">${[0, 1, 2, 3, 4].map(i => `<i style="background:var(--seq-${i})"></i>`).join('')}</div>
      <div style="display:flex;justify-content:space-between" class="meta"><span>Fewer</span><span>More</span></div></div>
  </div></section>

<section class="k">${H.header({ title: 'Copy rules' })}
  <div class="card" style="margin-top:12px"><ul class="kit-rules">
    <li><b>Short human titles.</b> One to four words, sentence case, no questions and no counts.</li>
    <li><b>The question goes behind ⓘ.</b> What it shows, how to read it and how it is computed sit in the panel, not the page body.</li>
    <li><b>Lead sentences sound like a colleague.</b> One idea, about 25 words at most, computed from the data.</li>
    <li><b>Words for people.</b> “Papers” rather than “mined works”, “human role” rather than “human position”, “not coded” rather than “not classified”.</li>
    <li><b>Jargon is a dotted term.</b> Wrap it once per page so a definition is one hover away.</li>
    <li><b>Buttons are verbs.</b> Browse papers, Open the flow, Show all, Clear.</li>
    <li><b>Numbers are computed.</b> Every figure comes from the data with its denominator; none is typed.</li>
    <li><b>Colour is never the only signal,</b> and the accent has one job: selection, the primary action and focus.</li>
    <li><b>The as-of stamp is always visible:</b> ${esc(RF.generated || '')}.</li>
  </ul></div></section>`;
    main.querySelectorAll('[data-theme-pick]').forEach(b => b.onclick = () => { H.setTheme(b.dataset.themePick); const p = document.getElementById('themePick'); if (p) p.value = b.dataset.themePick; });
    main.querySelectorAll('[data-open]').forEach(b => { b.onclick = () => H.openDrawer(b.dataset.open); b.onkeydown = e => { if (e.key === 'Enter') H.openDrawer(b.dataset.open); }; });
  }
  render();
  document.addEventListener('hub:theme', render);
});
