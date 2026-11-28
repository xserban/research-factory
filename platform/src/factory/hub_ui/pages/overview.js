/* Overview page (H03 "The 467" ported into hub v2).
   Payloads: shell (slim works, prisma headline) and overview (lead, next actions, pipeline,
   composition, most cited, papers per month, sets, line, level_statement).
   Every number comes from the payloads; every colour comes from kit tokens via H.cssv().
   Project-neutral: layers, the fourth facet (the shell's `human` slot) and their labels come from the payloads
   (shell works, `fields`, `labels`, overview composition); a panel whose data a project lacks is left out.
   Scope (HS-02, HS-03, HS-20, HS-24): the dots, the layer and facet counts, the most-cited list and the growth
   columns are recomputed over the works in scope (window.HUB_SCOPE); the screening funnel, the production line,
   the headline and the waiting list are whole-corpus aggregates and carry the label. */
HUB.load(['shell', 'overview']).then(d => {
  const H = HUB.init(d.shell);
  const O = d.overview || {};
  const main = H.mount({ page: 'overview', crumb: 'Overview' });
  const { esc, fmt, pct, LAYERS } = H;
  const SCOPE = window.HUB_SCOPE, WHOLE = SCOPE.label('corpus');
  const W = H.RF.works || [];
  const CH = O.cited_here || {};
  const cic = id => (CH[id] || [0])[0];
  const selfCic = id => (CH[id] || [0, 0])[1] || 0;
  /* The shared drawer reads w.cited_here and w.cic; fill both from the overview payload. */
  W.forEach(w => {
    const c = cic(w.id);
    w.cic = c;
    if (w.cited_here == null) w.cited_here = c;
  });

  if (!document.getElementById('ov-style')) {
    const st = document.createElement('style');
    st.id = 'ov-style';
    st.textContent = `
.ov-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.ov-hero{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:32px;align-items:start;padding:16px 0 8px}
.ov-hero .sec-head{margin:0}
.ov-hero .lead{max-width:34ch;margin-top:14px}
.ov-hero .lead .info{width:18px;height:18px}
.ov-levels{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}
.ov-levels .chip{text-decoration:none}
.ov-next{display:flex;flex-direction:column;gap:6px}
.ov-next .btn{height:38px;justify-content:space-between;width:100%;text-decoration:none}
.ov-next .btn .n{font-family:var(--f-mono);font-size:var(--t-xs);opacity:.85}

.ov-wait{margin:14px 0 24px;padding-top:12px;border-top:1px solid var(--hair)}
.ov-wait-head{font:600 var(--t-xs)/1.2 var(--f-ui);letter-spacing:.05em;text-transform:uppercase;color:var(--mut);margin-bottom:8px}
.ov-wait-grid{display:flex;flex-wrap:wrap;gap:8px}
.ov-wait-btn{display:inline-flex;align-items:center;gap:8px;min-height:32px;padding:5px 11px;border-radius:var(--r-s);border:1px solid var(--line);background:var(--surface);color:var(--fg);font:500 var(--t-xs)/1.2 var(--f-ui);cursor:pointer;text-align:left;max-width:100%;transition:border-color .15s ease,background .15s ease}
.ov-wait-btn:hover{background:var(--raised);border-color:var(--acc)}
.ov-wait-btn[data-copied="true"]{border-color:var(--inc)}
.ov-wait-count{font-family:var(--f-mono);font-weight:500;color:var(--acc);padding:2px 6px;border-radius:999px;background:var(--acc-soft)}
.ov-wait-cmd{font:400 11px/1.2 var(--f-mono);color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px}
.ov-wait-copy{font:500 11px/1 var(--f-ui);color:var(--mut);white-space:nowrap}
.ov-wait-btn[data-copied="true"] .ov-wait-copy{color:var(--inc)}
:root[data-theme="lcars"] .ov-wait-btn{border-radius:999px}

.ov-sec-bar{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin:24px 0 12px}
.ov-sec-bar .sec-head{margin:0}
.ov-link{display:inline-flex;align-items:center;gap:4px;min-height:28px;font:500 var(--t-s)/1.2 var(--f-ui);color:var(--acc);text-decoration:none;white-space:nowrap}
.ov-link:hover{text-decoration:underline;text-underline-offset:3px}

/* Preamble: honest-scale screening funnel */
.ov-preamble{margin:12px 0 8px}
.ov-funnel-card{margin:0;padding:18px 20px 16px;border:1px solid var(--hair)}
.ov-funnel-viz{width:100%;margin-bottom:14px}
.ov-funnel-viz svg{display:block;width:100%;height:auto;overflow:visible}
.ov-funnel-steps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;border-top:1px solid var(--hair);padding-top:14px}
.ov-fstep{display:flex;flex-direction:column;gap:4px;padding:10px 12px;border-radius:var(--r-s);background:var(--bg);border:1px solid var(--hair);text-decoration:none;color:inherit;transition:border-color .15s ease,background .15s ease}
.ov-fstep:hover{border-color:var(--acc);background:var(--raised)}
.ov-fstep.ov-inc{border-color:color-mix(in srgb,var(--inc) 50%,var(--hair))}
.ov-fstep-lbl{font:500 var(--t-xs)/1.2 var(--f-ui);color:var(--mut)}
.ov-fstep-num{font:600 22px/1.1 var(--f-mono);color:var(--fg);font-variant-numeric:tabular-nums}
.ov-fstep.ov-inc .ov-fstep-num{color:var(--inc)}
.ov-fstep-bar{height:5px;background:var(--raised);border-radius:3px;overflow:hidden;margin:4px 0 2px}
.ov-fstep-bar i{display:block;height:100%;background:var(--mut);border-radius:3px}
.ov-fstep.ov-inc .ov-fstep-bar i{background:var(--inc)}
.ov-fstep-of{font:400 11.5px/1.3 var(--f-ui);color:var(--dim)}
.ov-fstep-losses{margin-top:4px;display:flex;flex-direction:column;gap:2px}
.ov-floss{font:500 11.5px/1.3 var(--f-mono);color:var(--exc)}
.ov-floss.ov-none{color:var(--dim);font-family:var(--f-ui);font-weight:400}
.ov-funnel-cap{margin-top:12px;padding-top:10px;border-top:1px solid var(--hair);font-size:var(--t-xs)}
.ov-bridge{display:flex;align-items:center;gap:14px;margin:18px 0 6px}
.ov-bridge-line{flex:1;height:1px;background:var(--hair)}
.ov-bridge-tag{font-size:11px;color:var(--inc);padding:4px 10px;border-radius:999px;background:var(--surface);border:1px solid color-mix(in srgb,var(--inc) 40%,var(--line))}

/* Scrollytelling morph story */
.ov-story{padding:10px 0 32px}
.ov-story-grid{display:grid;grid-template-columns:minmax(300px,380px) minmax(0,1fr);gap:28px;align-items:start}
.ov-steps-col{grid-column:1;grid-row:1;display:flex;flex-direction:column;gap:24px;padding-bottom:14vh}
.ov-stage-col{grid-column:2;grid-row:1;height:100%}
.ov-stage-sticky{position:sticky;top:calc(var(--ov-top-h,62px) + 12px);height:calc(100vh - var(--ov-top-h,62px) - 28px);min-height:460px;max-height:740px;background:var(--surface);border:1px solid var(--hair);border-radius:var(--r);display:flex;flex-direction:column;overflow:hidden}
.ov-stage-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 12px;border-bottom:1px solid var(--hair);flex:none;flex-wrap:wrap}
.ov-stage-badge{display:flex;align-items:center;gap:8px;min-width:0}
.ov-stage-num{font-size:11.5px;font-weight:500;color:var(--acc);padding:3px 8px;border-radius:999px;background:var(--acc-soft);white-space:nowrap}
.ov-stage-scale{font-size:var(--t-xs);color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ov-stage-ctrls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.ov-pills{display:inline-flex;align-items:center;gap:2px;list-style:none;margin:0;padding:2px;background:var(--bg);border:1px solid var(--hair);border-radius:999px}
.ov-pills button{min-width:26px;min-height:24px;padding:0 7px;border:0;border-radius:999px;background:transparent;color:var(--dim);font:500 11px/1 var(--f-mono);cursor:pointer;transition:background .15s ease,color .15s ease}
.ov-pills button:hover{color:var(--fg);background:var(--raised)}
.ov-pills button[aria-current="step"]{background:var(--acc);color:var(--acc-ink)}
.ov-search{width:180px;min-height:28px;padding:4px 9px;font-size:var(--t-xs);border:1px solid var(--line)}
.ov-search-n{font-size:11px;color:var(--acc);white-space:nowrap}
.ov-mode-btn{height:28px;min-height:28px;padding:0 10px;font-size:11px;white-space:nowrap}

.ov-stage-frame{position:relative;flex:1;min-height:0;width:100%;cursor:default}
.ov-stage-frame canvas{display:block;width:100%;height:100%}
.ov-cursor{position:absolute;left:16px;top:16px;width:28px;height:28px;margin:-14px 0 0 -14px;padding:0;border:2px solid transparent;border-radius:50%;background:transparent;cursor:pointer;z-index:5;pointer-events:none}
.ov-cursor:focus-visible{outline:2px solid var(--acc);outline-offset:2px;box-shadow:0 0 0 4px var(--acc-soft)}
.ov-tip{position:absolute;pointer-events:none;z-index:10;max-width:300px;padding:9px 11px;border-radius:var(--r-s);background:var(--raised);border:1px solid var(--line);color:var(--fg);box-shadow:var(--shadow);font-size:var(--t-xs);line-height:1.4}
.ov-tip-ti{font-weight:600;color:var(--fg);margin-bottom:3px}
.ov-tip-meta{color:var(--mut);display:flex;flex-wrap:wrap;gap:3px 9px}
.ov-tip-cta{margin-top:4px;color:var(--acc);font-size:11px}

.ov-inspector{flex:none;padding:9px 12px;min-height:42px;border-top:1px solid var(--hair);background:var(--bg);display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:var(--t-xs)}
.ov-insp-act{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;min-width:0}
.ov-insp-act[hidden]{display:none}
.ov-insp-paper{display:flex;align-items:center;gap:8px;min-width:0;flex:1}
.ov-insp-ti{font-weight:600;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ov-insp-sub{color:var(--mut);white-space:nowrap;flex:none}
.ov-insp-open{min-height:26px;height:26px;padding:0 10px;font-size:11px;flex:none}

/* Narrative chapter cards */
.ov-step{min-height:62vh;display:flex;flex-direction:column;justify-content:center;padding:22px 20px;border-radius:var(--r);background:var(--surface);border:1px solid var(--hair);border-left:3px solid var(--line);transition:border-color .2s ease,opacity .2s ease;opacity:.7}
.ov-step.ov-active{opacity:1;border-color:var(--line);border-left-color:var(--acc)}
.ov-step-kicker{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);margin-bottom:8px}
.ov-step.ov-active .ov-step-kicker{color:var(--acc)}
.ov-step-title{font-family:var(--f-display);font-weight:400;font-size:25px;line-height:1.18;margin:0;color:var(--fg)}
.ov-step-cap{margin:10px 0 0;color:var(--mut);font-size:var(--t-s);line-height:1.55}
.ov-step-meta{margin-top:14px;padding-top:10px;border-top:1px solid var(--hair);display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px}
.ov-step-meta .info{width:24px;height:24px;margin-left:0;font-size:12px}
.ov-step-n{font-size:11.5px;color:var(--fg);padding:3px 7px;border-radius:4px;background:var(--raised)}
.ov-step-meta .ov-link{margin-left:auto;font-size:var(--t-xs)}
.ov-legend{margin-top:12px;display:flex;flex-wrap:wrap;gap:6px}
.ov-legend .chip{min-height:26px}
.ov-hollow{background:transparent!important;border:1.6px solid color-mix(in srgb,currentColor 55%,var(--mut))}

.ov-bd{margin-top:12px;display:flex;flex-direction:column;gap:3px}
.ov-bd-row{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px;width:100%;min-height:28px;padding:4px 8px;border:1px solid transparent;border-radius:var(--r-s);background:transparent;color:var(--fg);font:400 var(--t-xs)/1.3 var(--f-ui);text-align:left;cursor:pointer}
.ov-bd-row:hover{background:var(--raised)}
.ov-bd-row[aria-pressed="true"]{background:var(--acc-soft);border-color:var(--acc)}
.ov-bd-row.ov-half{background:var(--raised);border-color:var(--line);font-weight:600}
.ov-bd-val{font-family:var(--f-mono);color:var(--mut);white-space:nowrap}

.ov-top-list{margin-top:12px;display:flex;flex-direction:column;gap:2px}
.ov-top-btn{display:grid;grid-template-columns:22px auto 1fr auto;align-items:center;gap:7px;width:100%;min-height:30px;padding:5px 8px;border:0;border-radius:var(--r-s);background:transparent;color:var(--fg);font:400 var(--t-xs)/1.3 var(--f-ui);text-align:left;cursor:pointer}
.ov-top-btn:hover{background:var(--raised)}
.ov-top-rank{font-family:var(--f-mono);color:var(--dim)}
.ov-top-ti{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ov-top-n{font-family:var(--f-mono);color:var(--mut);white-space:nowrap}

.ov-all{margin-top:10px}
.ov-all summary{cursor:pointer;color:var(--acc);font:500 var(--t-xs)/1.4 var(--f-ui);min-height:28px;display:inline-flex;align-items:center}
.ov-tbl-scroll{overflow-x:auto;margin-top:8px;max-height:280px;border:1px solid var(--hair);border-radius:var(--r-s)}
.ov-all table.t{font-size:var(--t-xs)}
.ov-all td.ti{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.ov-callouts{margin-top:12px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.ov-callout{padding:10px 12px;border-radius:var(--r-s);background:var(--bg);border:1px solid var(--hair)}
.ov-callout-k{font-size:11px;color:var(--dim)}
.ov-callout-v{margin-top:2px;font:600 var(--t-m)/1.2 var(--f-mono);color:var(--fg)}
.ov-callout-s{margin-top:2px;font-size:11px;color:var(--mut)}

/* Static small multiples (reduced motion or manual toggle) */
.ov-mult-wrap[hidden]{display:none}
.ov-mult-bar{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.ov-mult-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.ov-mult-card{background:var(--surface);border:1px solid var(--hair);border-radius:var(--r);padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.ov-mult-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.ov-mult-cv{position:relative;width:100%;height:310px;background:var(--bg);border:1px solid var(--hair);border-radius:var(--r-s);overflow:hidden}
.ov-mult-cv canvas{display:block;width:100%;height:100%}
.ov-mult-insp{font-size:var(--t-xs);color:var(--mut);min-height:22px;display:flex;align-items:center;justify-content:space-between;gap:8px}

/* Epilogue: production line & sets reconciliation */
.ov-epilogue{padding:20px 0 12px;border-top:1px solid var(--hair)}
.ov-line-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.ov-line-card{display:flex;flex-direction:column;gap:4px;padding:16px 18px;border-radius:var(--r);background:var(--surface);border:1px solid var(--hair);text-decoration:none;color:inherit;transition:border-color .15s ease,background .15s ease}
.ov-line-card:hover{border-color:var(--acc);background:var(--raised)}
.ov-line-key{font:500 var(--t-xs)/1.2 var(--f-ui);color:var(--mut)}
.ov-line-num{font:600 28px/1.1 var(--f-mono);color:var(--fg);font-variant-numeric:tabular-nums;margin-top:2px}
.ov-line-unit{font-size:var(--t-s);color:var(--dim)}
.ov-line-go{margin-top:8px;font-size:var(--t-xs);color:var(--acc)}
.ov-foot{margin-top:20px;display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:var(--t-s);color:var(--mut)}
.ov-empty{padding:28px 20px;color:var(--dim);font-size:var(--t-s);text-align:center}

@media (max-width:1060px){
  .ov-hero{grid-template-columns:1fr;gap:18px}
  .ov-story-grid{grid-template-columns:1fr;gap:16px}
  .ov-stage-col{grid-column:1;grid-row:1;position:sticky;top:calc(var(--ov-top-h,56px) + 4px);z-index:15;height:auto}
  .ov-stage-sticky{position:static;height:44vh;min-height:280px;max-height:390px;box-shadow:var(--shadow)}
  .ov-steps-col{grid-column:1;grid-row:2;padding-bottom:6vh;gap:16px}
  .ov-step{min-height:auto;padding:18px 16px}
  .ov-funnel-steps{grid-template-columns:repeat(3,minmax(0,1fr))}
  .ov-line-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ov-mult-grid{grid-template-columns:1fr}
}
@media (max-width:760px){
  .ov-wait-cmd{display:none}
  .ov-pills{display:none}
  .ov-stage-ctrls{flex:1;min-width:0;justify-content:flex-end}
  .ov-search{flex:1;min-width:100px;max-width:170px}
  .ov-stage-scale{display:none}
  .ov-funnel-steps{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .ov-fstep-num{font-size:19px}
  .ov-stage-sticky{height:40vh;min-height:250px;max-height:330px}
  .ov-inspector{padding:7px 10px;min-height:36px}
  .ov-inspector .meta{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ov-insp-sub{display:none}
  .ov-step-title{font-size:21px}
  .ov-line-grid{grid-template-columns:1fr}
}
@media (max-width:520px){
  .ov-funnel-steps{grid-template-columns:1fr}
  .ov-search{min-width:90px}
  .ov-callouts{grid-template-columns:1fr}
}
`;
    document.head.appendChild(st);
  }

  /* ---------- vocabularies & helpers ---------- */
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  /* Layers: the project's own, from the works and the composition payload. Known layers keep their colour; others
     take the free layer tokens in order. */
  const LAYER_KNOWN = new Map(LAYERS.map(l => [l[0], l]));
  const LAYER_CNT = {};
  W.forEach(w => { const k = w.layer || 'unlayered'; LAYER_CNT[k] = (LAYER_CNT[k] || 0) + 1; });
  Object.keys((O.composition || {}).layer || {}).forEach(k => { if (!(k in LAYER_CNT)) LAYER_CNT[k] = 0; });
  const lrank = k => (k === 'unlayered' ? 1000 : (LAYERS.findIndex(l => l[0] === k) < 0 ? 100 : LAYERS.findIndex(l => l[0] === k)));
  const LAYER_KEYS = Object.keys(LAYER_CNT).sort((a, b) => lrank(a) - lrank(b) || LAYER_CNT[b] - LAYER_CNT[a] || a.localeCompare(b));
  const LAYER_TOKS = ['--l-core', '--l-benchmark', '--l-applied', '--l-adjacent', '--l-background'];
  const usedTok = new Set(LAYER_KEYS.filter(k => LAYER_KNOWN.has(k)).map(k => LAYER_KNOWN.get(k)[2]));
  const freeTok = LAYER_TOKS.filter(t => !usedTok.has(t));
  const tokPool = freeTok.length ? freeTok : LAYER_TOKS;
  let nUnknownLayer = 0;
  const LAYER_BY = new Map(LAYER_KEYS.map(k => [k, LAYER_KNOWN.get(k) || [k, H.pretty(k), tokPool[nUnknownLayer++ % tokPool.length]]]));
  const layerInfo = k => LAYER_BY.get(k) || [k, H.pretty(k), '--l-unlayered'];
  /* Bands of the timeline: the first pilot's five when every layer is one of its own, else the project's layers
     (the four largest named ones and an "other" band when there are more than five). */
  const LEGACY_LAYERS = LAYER_KEYS.every(k => LAYER_KNOWN.has(k));
  const BANDS = LEGACY_LAYERS ? ['core', 'benchmark', 'applied', 'adjacent', 'other']
    : LAYER_KEYS.length <= 5 ? LAYER_KEYS.slice()
      : [...LAYER_KEYS.filter(k => k !== 'unlayered').sort((a, b) => LAYER_CNT[b] - LAYER_CNT[a] || a.localeCompare(b)).slice(0, 4), 'other'];
  const bandOf = l => (BANDS.includes(l) ? l : 'other');
  const bandLabel = b => (b === 'other' ? 'Other' : layerInfo(b)[1]);

  /* The fourth facet slot (shell `fields`: the project's first facets stand for the pilot's four slots). Its
     values are the project's own; the pilot's "human role" reading (no human in the loop, the half) applies only
     to a project that has the pilot's own field and values. */
  const humanOf = w => (w.human && typeof w.human === 'object' ? (w.human.v || 'null') : (w.human || 'null'));
  const FACET_SLOT = H.FIELDS.find(f => f[0] === 'human') || null;
  const FACET_CNT = {};
  W.forEach(w => { const k = humanOf(w); FACET_CNT[k] = (FACET_CNT[k] || 0) + 1; });
  Object.keys((O.composition || {}).human || {}).forEach(k => { if (!(k in FACET_CNT)) FACET_CNT[k] = 0; });
  const CODED_KEYS = Object.keys(FACET_CNT).filter(k => k !== 'null' && FACET_CNT[k] > 0);
  const HUMAN_KNOWN = new Set(H.HUMAN.map(h => h[0]));
  const PIL = !H.RF.fields && CODED_KEYS.length > 0 && CODED_KEYS.every(k => HUMAN_KNOWN.has(k));
  const HAS_FACET = Boolean(FACET_SLOT) && CODED_KEYS.length > 0;
  const FACET_LABEL = FACET_SLOT ? FACET_SLOT[1] : 'Facet';
  const FACET_TOKS = ['--h-none', '--h-goal', '--h-review', '--h-feedback', '--h-collab', '--h-physical'];
  const NOT_CODED = ['null', 'Not coded', '--h-null'];
  const HUMAN_ALL = PIL ? [...H.HUMAN, NOT_CODED]
    : [...CODED_KEYS.slice().sort((a, b) => FACET_CNT[b] - FACET_CNT[a] || a.localeCompare(b)).map((k, i) => [k, H.pretty(k), FACET_TOKS[i % FACET_TOKS.length]]), NOT_CODED];
  const GATE_LABELS = { 'documents-unconverted': 'Convert documents', 'version-pairs': 'Review version pairs' };
  const STAGE_NAMES = ['The corpus', 'Papers over time', 'By layer', FACET_LABEL, 'Most cited', 'Growth per month'];
  const TOTAL_STAGES = STAGE_NAMES.length;
  /* the stages shown: the facet chapter is left out when the project has no such facet */
  const STAGES_SHOWN = STAGE_NAMES.map((_, i) => i).filter(i => i !== 3 || HAS_FACET);
  const pad2 = n => String(n).padStart(2, '0');

  const ymLabel = m => (m && m.length >= 7 ? `${MON[+m.slice(5, 7) - 1] || ''} ${m.slice(0, 4)}` : String(m || ''));
  const ymShort = m => (m && m.length >= 7 ? `${MON[+m.slice(5, 7) - 1] || ''} '${m.slice(2, 4)}` : String(m || ''));
  const mkey = w => (w.year && w.month ? `${w.year}-${String(w.month).padStart(2, '0')}` : '');
  const humanInfo = k => HUMAN_ALL.find(h => h[0] === (k == null ? 'null' : k)) || NOT_CODED;
  const sharePhrase = p => (p >= 47 && p <= 53 ? 'Half' : p >= 30 && p <= 36 ? 'About a third' : p >= 22 && p <= 28 ? 'About a quarter' : `${p}%`);

  const hashf = s => {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 10000) / 10000;
  };

  const shortTitle = (t, max = 30) => {
    let s = String(t || '').split(/[:–—]/)[0].replace(/^(The |A |An )/i, '').trim();
    if (s.length > max) {
      s = s.slice(0, max);
      const sp = s.lastIndexOf(' ');
      if (sp > 10) s = s.slice(0, sp);
      s += '…';
    }
    return s;
  };

  const easeInOutCubic = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  /* ---------- theme token reader (zero hard-coded colours) ---------- */
  const probeCanvas = document.createElement('canvas');
  probeCanvas.width = 1;
  probeCanvas.height = 1;
  const probeCtx = probeCanvas.getContext('2d', { willReadFrequently: true });

  function cssToRgb(cssColor) {
    if (!probeCtx || !cssColor) return [128, 128, 128];
    probeCtx.clearRect(0, 0, 1, 1);
    probeCtx.fillStyle = cssColor;
    probeCtx.fillRect(0, 0, 1, 1);
    const data = probeCtx.getImageData(0, 0, 1, 1).data;
    return [data[0], data[1], data[2]];
  }

  let PAL = {};
  let PAL_RGB = {};

  function readPalette() {
    const keys = [
      '--bg', '--surface', '--raised', '--line', '--hair',
      '--fg', '--mut', '--dim', '--acc', '--acc-ink', '--acc-soft',
      '--inc', '--exc', '--exc-soft',
      '--l-core', '--l-benchmark', '--l-applied', '--l-adjacent', '--l-background', '--l-off', '--l-unlayered',
      '--h-none', '--h-goal', '--h-review', '--h-feedback', '--h-collab', '--h-physical', '--h-null',
    ];
    PAL = {};
    PAL_RGB = {};
    for (const k of keys) {
      const v = H.cssv(k);
      PAL[k] = v;
      PAL_RGB[k] = cssToRgb(v);
    }
    PAL.fontUi = H.cssv('--f-ui') || 'Inter, system-ui, sans-serif';
    PAL.fontDisplay = H.cssv('--f-display') || 'Newsreader, Georgia, serif';
    PAL.fontMono = H.cssv('--f-mono') || 'JetBrains Mono, monospace';
  }

  function rgbCss(rgb, alpha = 1) {
    return `rgba(${Math.round(rgb[0])},${Math.round(rgb[1])},${Math.round(rgb[2])},${alpha})`;
  }

  /* ---------- enriched works index ---------- */
  const ppm = O.papers_per_month || { months: [], counts: [], busiest: {} };
  const months = ppm.months || [];
  let mcounts = ppm.counts || [];
  const mMap = new Map(months.map((m, i) => [m, i]));

  const ALL = W.map((w, idx) => {
    const layer = w.layer || 'unlayered';
    const humanVal = humanOf(w);
    const ym = mkey(w);
    return {
      ...w,
      _idx: idx,
      _all: idx,
      _layer: layer,
      _human: humanVal,
      _ym: ym,
      _mIdx: mMap.has(ym) ? mMap.get(ym) : Math.max(0, months.length - 1),
      _cited: cic(w.id),
      _selfCited: selfCic(w.id),
      _searchBlob: [
        w.title,
        ...(w.authors || []),
        layer,
        layerInfo(layer)[1],
        humanVal,
        humanInfo(humanVal)[1],
        ym,
      ].join(' ').toLowerCase(),
    };
  });

  const lead = O.lead || {};
  const meth = O.methods || {};
  /* Whole-corpus figures (the headline, the funnel, the production line) never change with the scope. */
  const nIncAll = lead.included ?? ALL.length;
  const hum0 = lead.human || {};
  const sharePct0 = Math.round(100 * (hum0.share_none || 0));

  /* Scope: WORKS holds the works in scope (all of them while no scope is set); every per-work view reads it.
     comp, mc, mcounts, busiest and the facet figures are recomputed over WORKS while a scope is active. */
  let SRES = null, WORKS = ALL;
  let hum = hum0, comp = O.composition || { layer: {}, human: {} }, mc = O.most_cited || [], nInc = nIncAll;
  let sharePct = sharePct0, codedN = 0, noneN = 0, busiest = ppm.busiest || { month: months[0] || '', n: 0 };
  const scopeOn = () => SCOPE.active(SCOPE.current());
  const MCM = new Map((O.most_cited || []).map(m => [m.id, m]));
  function applyScope() {
    SRES = SCOPE.apply(ALL, w => w.published, SCOPE.current(), { includeUndated: SCOPE.includeUndated() });
    WORKS = SRES.inScope;
    if (!scopeOn()) {
      hum = hum0; comp = O.composition || { layer: {}, human: {} }; mc = O.most_cited || []; nInc = nIncAll; sharePct = sharePct0;
      mcounts = ppm.counts || [];
      busiest = ppm.busiest || { month: months[0] || '', n: Math.max(0, ...mcounts) };
    } else {
      /* a category the whole corpus holds keeps its row at 0 (HS-24) */
      const zero = keys => Object.fromEntries(keys.map(k => [k, 0]));
      const cl = zero([...Object.keys(((O.composition || {}).layer) || {}), ...LAYER_KEYS]);
      const ch = zero([...Object.keys(((O.composition || {}).human) || {}), ...Object.keys(FACET_CNT)]);
      for (const w of WORKS) { cl[w._layer] = (cl[w._layer] || 0) + 1; ch[w._human] = (ch[w._human] || 0) + 1; }
      comp = { layer: cl, human: ch };
      nInc = WORKS.length;
      const notCoded = ch.null || 0, coded = Math.max(0, nInc - notCoded), none = ch.none || 0;
      hum = { coded, none, not_coded: notCoded, share_none: coded ? none / coded : 0 };
      sharePct = Math.round(100 * hum.share_none);
      mc = WORKS.filter(w => w._cited > 0)
        .map(w => ({ id: w.id, title: w.title, layer: w.layer, year: w.year, cited_here: w._cited, self_cited: w._selfCited, external: (MCM.get(w.id) || {}).external ?? null }))
        .sort((a, b) => b.cited_here - a.cited_here || a.title.localeCompare(b.title)).slice(0, 50);
      const by = {};
      for (const w of WORKS) by[w._ym] = (by[w._ym] || 0) + 1;
      mcounts = months.map(m => by[m] || 0);
      const vm = Math.max(0, ...mcounts), im = mcounts.indexOf(vm);
      busiest = { month: im >= 0 ? months[im] : (months[0] || ''), n: vm };
    }
    codedN = hum.coded || Math.max(0, WORKS.length - ((comp.human || {}).null || 0));
    noneN = (comp.human || {}).none ?? hum.none ?? 0;
  }
  applyScope();

  /* ---------- build static DOM skeleton ---------- */
  function levelBadges() {
    const ls = O.level_statement;
    if (!ls) return '';
    const tier = ls.tier || 'tier not declared';
    const unconfirmed = ls.human_confirmed ? '' : ' · not human-confirmed';
    const valLbl = ls.validation_label ? ` · ${ls.validation_label}` : '';
    return `<div class="ov-levels" aria-label="Study rigor and autonomy"><a class="chip" href="levels.html" title="How this study runs">Tier: ${esc(tier + valLbl)}</a><a class="chip" href="levels.html" title="How this study runs">Autonomy: ${esc(ls.autonomy_level || 'unknown')}${esc(unconfirmed)}</a></div>`;
  }

  const actions = O.next_actions || [];
  const waitHtml = actions.length
    ? `<section class="ov-wait" id="ovWait" aria-label="Waiting for you">
        <div class="ov-wait-head">Waiting for you ${WHOLE}</div>
        <div class="ov-wait-grid" id="ovWaitItems">
          ${actions.map((a, i) => {
            const lbl = GATE_LABELS[a.gate] || H.pretty(a.gate);
            const cmd = a.command || '';
            return `<button type="button" class="ov-wait-btn" data-cmd="${esc(cmd)}" data-idx="${i}" title="Copy command: ${esc(cmd)}">
              <span>${esc(lbl)}</span>
              <span class="ov-wait-count">${fmt(a.count)}</span>
              ${cmd ? `<code class="ov-wait-cmd">${esc(cmd)}</code><span class="ov-wait-copy">Copy</span>` : ''}
            </button>`;
          }).join('')}
        </div>
        <span class="ov-sr" id="ovCopyStatus" aria-live="polite"></span>
      </section>`
    : '';

  const leadInfoHtml = `<b>What it shows</b>The headline result of the review so far.<p><span class=k>How it's computed.</span> ${fmt(nIncAll)} is the number included in the screening flow, out of ${fmt(lead.identified)} records identified.${PIL && hum0.coded ? ` The share is the ${fmt(hum0.none || 0)} papers with human role "none" divided by the ${fmt(hum0.coded || 0)} papers with a human role coded (${fmt(hum0.not_coded || 0)} not coded are left out): ${sharePct0}%.` : ''}</p>${PIL ? `<p>${esc(meth.human_role || '')}</p>` : ''}`;

  const pipe = O.pipeline || [];
  const topPipe = (pipe[0] && pipe[0].n) || 1;
  const screenedN = pipe[1] && pipe[1].n != null ? pipe[1].n : null;
  const soughtOf = pipe[2] && pipe[2].of != null ? pipe[2].of : null;
  const taExcl = screenedN != null && soughtOf != null && screenedN > soughtOf ? screenedN - soughtOf : 0;
  const preInfoHtml = `<b>What it shows</b>How many records survive each screening step, and what each step removed.<p><span class=k>How to read it.</span> Both the narrowing ribbon height and each step's bar width are drawn linearly from zero as a share of the ${fmt(topPipe)} identified records. Losses are marked with a minus (−) glyph; included papers with a plus (+).</p><p><span class=k>How it's computed.</span> Counts come from the screening flow; the arithmetic is checked on the <a href="flow.html">flow page</a>.${taExcl ? ` Between Screened (${fmt(screenedN)}) and Full text sought (${fmt(soughtOf)} passing title and abstract), ${fmt(taExcl)} records were excluded at title and abstract.` : ''}</p>`;

  const lastM = months[months.length - 1] || '';

  const stageInfo = {
    0: H.info(`<b>What it shows</b>Every included paper rendered as one dot forming the corpus count.<p><span class=k>How to read it.</span> One dot per paper, coloured by ${H.term('layer')}. Scroll to rearrange the same dots across time, layer, ${HAS_FACET ? esc(FACET_LABEL.toLowerCase()) + ', ' : ''}citations and monthly growth.</p><p><span class=k>How it's computed.</span> ${fmt(nIncAll)} included out of ${fmt(lead.identified)} identified records.</p>`, 'About the corpus view'),
    1: H.info(`<b>What it shows</b>When each paper was published, and which layer it sits in.<p><span class=k>How to read it.</span> Across: publication month. Down: layer band (height proportional to √count). Circle area scales linearly with how often other included papers cite it here; hollow rings are unlayered.</p><p><span class=k>How it's computed.</span> ${esc(meth.papers_per_month || '')}</p>`, 'About Papers over time'),
    2: H.info(`<b>What it shows</b>How the included papers split by layer.<p><span class=k>How to read it.</span> Unit-dot bars on one shared linear scale starting from zero. Click any layer row to highlight its dots.</p><p><span class=k>How it's computed.</span> ${esc(meth.composition || '')}</p>`, 'About layer composition'),
    3: H.info(PIL
      ? `<b>What it shows</b>Where the human sits in the coded systems.<p><span class=k>How to read it.</span> Unit-dot bars on a 0–100% scale of the coded papers. The dashed meridian marks half of coded works.</p><p><span class=k>How it's computed.</span> ${esc(meth.human_role || '')}</p>`
      : `<b>What it shows</b>How the included papers split by ${esc(FACET_LABEL)}, one of this project's own facets.<p><span class=k>How to read it.</span> Unit-dot bars on a 0–100% scale of the papers that have a value. Click a row to highlight its dots.</p><p><span class=k>How it's computed.</span> Counts of the value each paper carries for this facet, from the shell payload.</p>`, `About ${FACET_LABEL}`),
    4: H.info(`<b>What it shows</b>The papers other papers in this review build on most.<p><span class=k>How to read it.</span> Circle area and horizontal bars start from zero and scale with ${H.term('cic', 'cited here')}. Click any paper to open its evidence drawer.</p><p><span class=k>How it's computed.</span> ${esc(meth.most_cited || meth.cited_here || '')}</p>`, 'About Most cited here'),
    5: H.info(`<b>What it shows</b>How many included papers appeared each month.<p><span class=k>How to read it.</span> Unit-dot columns stacked linearly from zero. The dashed frame marks the final partial month.</p><p><span class=k>How it's computed.</span> ${esc(meth.papers_per_month || '')}${lastM ? ` Latest month (${esc(ymLabel(lastM))}) is partial as of ${esc(H.RF.generated || '')}.` : ''}</p>`, 'About Growth per month'),
  };

  const lineInfoHtml = `<b>What it shows</b>The production line after screening: what has been converted, read, written up and built.<p><span class=k>How to read it.</span> Each card opens the page where that work happens.</p><p><span class=k>How it's computed.</span> ${esc(meth.line || '')}</p>`;

  const kick = idx => `${pad2(STAGES_SHOWN.indexOf(idx) + 1)} / ${pad2(STAGES_SHOWN.length)}`;
  const pillsHtml = STAGES_SHOWN.map((i, pos) =>
    `<li><button type="button" data-jump="${i}" aria-label="Jump to stage ${pos + 1}: ${esc(STAGE_NAMES[i])}" title="${pos + 1}. ${esc(STAGE_NAMES[i])}"${i === 0 ? ' aria-current="step"' : ''}>${pad2(pos + 1)}</button></li>`
  ).join('');

  main.innerHTML = `
<section class="ov-hero" id="ovHero">
  <div>
    ${H.header({ kicker: `Living review · ${H.term('protocol')}`, title: H.pretty(H.RF.slug), level: 1 })}
    <p class="lead">${fmt(nIncAll)} papers made it through ${H.term('screened', 'screening')}. ${PIL && hum0.coded ? sharePhrase(sharePct0) + ' of the systems run with no human in the loop.' : ''}${H.info(leadInfoHtml, 'How these figures are computed')} ${WHOLE}</p>
    ${levelBadges()}
  </div>
  <nav class="ov-next" aria-label="Next actions">
    <a class="btn primary" href="corpus.html">Browse papers <span class="n" id="ovBrowseN">${fmt(nIncAll)}</span></a>
    <a class="btn" href="flow.html">Open the flow <span class="n">${fmt(lead.identified)} → ${fmt(nIncAll)}</span></a>
    <a class="btn" href="explore.html">Explore papers</a>
    <a class="btn" href="lenses.html">Lenses</a>
    <p class="meta">Figures on the flow button: ${WHOLE}</p>
  </nav>
</section>
<div id="ovScope"></div>

${waitHtml}

<section class="ov-preamble" id="ovPreamble" aria-label="Where the records went">
  <div class="ov-sec-bar">
    ${H.header({ title: 'Where the records went', sub: `<span id="ovPreSub"></span> ${WHOLE}`, infoHtml: preInfoHtml })}
    <a class="ov-link" href="flow.html">Open the flow →</a>
  </div>
  <figure class="ov-funnel-card card">
    <div class="ov-funnel-viz" id="ovFunnelViz"></div>
    <div class="ov-funnel-steps" id="ovFunnelSteps" role="list" aria-label="Screening steps"></div>
    <figcaption class="ov-funnel-cap meta" id="ovFunnelCap"></figcaption>
  </figure>
  <div class="ov-bridge" aria-hidden="true">
    <span class="ov-bridge-line"></span>
    <span class="ov-bridge-tag mono" id="ovBridgeTag"></span>
    <span class="ov-bridge-line"></span>
  </div>
</section>

<section class="ov-story" id="ovStory" aria-label="Included papers across six views">
  <div id="ovScopeEmpty" hidden></div>
  <div class="ov-story-grid" id="ovStoryScroll">
    <div class="ov-stage-col">
      <div class="ov-stage-sticky" id="ovStageSticky">
        <div class="ov-stage-bar">
          <div class="ov-stage-badge">
            <span class="ov-stage-num mono" id="ovStageNum">${kick(0)}</span>
            <span class="ov-stage-scale" id="ovStageScale">1 dot = 1 paper</span>
          </div>
          <div class="ov-stage-ctrls">
            <ol class="ov-pills" id="ovStageNav" aria-label="Scroll stages">${pillsHtml}</ol>
            <label class="ov-sr" for="ovSearch">Find a paper among the dots</label>
            <input type="search" id="ovSearch" class="ov-search" placeholder="Filter papers…" autocomplete="off">
            <span class="ov-search-n mono" id="ovSearchCount" hidden></span>
            <button type="button" class="btn ov-mode-btn" id="ovModeToggle" aria-pressed="false">Small multiples</button>
          </div>
        </div>
        <div class="ov-stage-frame" id="ovStageFrame">
          <canvas id="ovCanvas" aria-hidden="true"></canvas>
          <button type="button" id="ovCursor" class="ov-cursor" aria-label="Inspect included papers. Use arrow keys to move between dots, Enter to open details."></button>
          <div class="ov-tip" id="ovTip" role="status" aria-live="polite" hidden></div>
        </div>
        <div class="ov-inspector" id="ovInspector" aria-live="polite">
          <span class="meta" id="ovInspIdle">Hover or tap a dot · Tab + Arrows, Enter opens</span>
          <div class="ov-insp-act" id="ovInspAct" hidden></div>
        </div>
      </div>
    </div>

    <div class="ov-steps-col" id="ovStepsCol">
      <article class="ov-step ov-active" data-stage="0" id="ovStep-0" aria-labelledby="ovS0Title">
        <div class="ov-step-kicker mono">${kick(0)} · The corpus</div>
        <h2 class="ov-step-title" id="ovS0Title"></h2>
        <p class="ov-step-cap" id="ovS0Cap"></p>
        <div class="ov-step-meta">
          <span class="ov-step-n mono" id="ovS0N"></span>
          ${stageInfo[0]}
          <a class="ov-link" href="corpus.html">Browse papers →</a>
        </div>
        <div class="ov-legend" id="ovS0Legend" aria-label="Filter by layer"></div>
      </article>

      <article class="ov-step" data-stage="1" id="ovStep-1" aria-labelledby="ovS1Title">
        <div class="ov-step-kicker mono">${kick(1)} · Timeline</div>
        <h2 class="ov-step-title" id="ovS1Title">Papers over time</h2>
        <p class="ov-step-cap" id="ovS1Cap"></p>
        <div class="ov-step-meta">
          <span class="ov-step-n mono" id="ovS1N"></span>
          ${stageInfo[1]}
          <a class="ov-link" href="explore.html">Explore papers →</a>
        </div>
        <div class="ov-legend" id="ovS1Legend" aria-label="Filter by layer"></div>
      </article>

      <article class="ov-step" data-stage="2" id="ovStep-2" aria-labelledby="ovS2Title">
        <div class="ov-step-kicker mono">${kick(2)} · Composition by layer</div>
        <h2 class="ov-step-title" id="ovS2Title">What the corpus is made of</h2>
        <p class="ov-step-cap" id="ovS2Cap"></p>
        <div class="ov-step-meta">
          <span class="ov-step-n mono" id="ovS2N"></span>
          ${stageInfo[2]}
          <a class="ov-link" href="corpus.html">Open corpus →</a>
        </div>
        <div class="ov-bd" id="ovS2Bd"></div>
      </article>

      <article class="ov-step" data-stage="3" id="ovStep-3" aria-labelledby="ovS3Title">
        <div class="ov-step-kicker mono">${kick(3)} · ${esc(FACET_LABEL)}</div>
        <h2 class="ov-step-title" id="ovS3Title">${esc(PIL ? 'Where the human sits' : FACET_LABEL)}</h2>
        <p class="ov-step-cap" id="ovS3Cap"></p>
        <div class="ov-step-meta">
          <span class="ov-step-n mono" id="ovS3N"></span>
          ${stageInfo[3]}
          <a class="ov-link" href="lenses.html">Open lenses →</a>
        </div>
        <div class="ov-bd" id="ovS3Bd"></div>
      </article>

      <article class="ov-step" data-stage="4" id="ovStep-4" aria-labelledby="ovS4Title">
        <div class="ov-step-kicker mono">${kick(4)} · Influence inside the review</div>
        <h2 class="ov-step-title" id="ovS4Title">Most cited here</h2>
        <p class="ov-step-cap" id="ovS4Cap"></p>
        <div class="ov-step-meta">
          <span class="ov-step-n mono" id="ovS4N"></span>
          ${stageInfo[4]}
          <a class="ov-link" href="graph.html">Citation graph →</a>
        </div>
        <div class="ov-top-list" id="ovS4List"></div>
        <details class="ov-all" id="ovAllCitedDetails">
          <summary id="ovAllCitedSummary"></summary>
          <div class="ov-tbl-scroll" id="ovAllCitedTable"></div>
        </details>
      </article>

      <article class="ov-step" data-stage="5" id="ovStep-5" aria-labelledby="ovS5Title">
        <div class="ov-step-kicker mono">${kick(5)} · Pace of publication</div>
        <h2 class="ov-step-title" id="ovS5Title">Growth per month</h2>
        <p class="ov-step-cap" id="ovS5Cap"></p>
        <div class="ov-step-meta">
          <span class="ov-step-n mono" id="ovS5N"></span>
          ${stageInfo[5]}
          <a class="ov-link" href="living.html">Living log →</a>
        </div>
        <div class="ov-callouts" id="ovS5Callouts"></div>
      </article>
    </div>
  </div>

  <div class="ov-mult-wrap" id="ovMultiples" hidden>
    <div class="ov-mult-bar">
      ${H.header({ kicker: 'Static small multiples · Reduced motion', title: 'All views side by side', sub: 'Every included paper at honest scale with no animation. Hover or focus any dot; Enter opens details.' })}
      <button type="button" class="btn" id="ovModeBack">Interactive scroll view</button>
    </div>
    <div class="ov-mult-grid" id="ovMultGrid"></div>
  </div>
</section>

<section class="ov-epilogue" id="ovEpilogue" aria-label="From papers to findings">
  ${(O.line || []).length ? `
    <div class="ov-sec-bar">
      ${H.header({ title: 'From papers to findings', sub: `What has been converted to text, read into structured rows, written up and built. ${WHOLE}`, infoHtml: lineInfoHtml })}
      <a class="ov-link" href="pipeline.html">View production line →</a>
    </div>
    <div class="ov-line-grid" id="ovLineGrid" role="list"></div>
  ` : ''}
  <p class="ov-foot" id="ovFoot"></p>
</section>
`;

  const byIdEl = id => document.getElementById(id);

  /* ---------- Waiting for you: copyable commands ---------- */
  main.querySelectorAll('.ov-wait-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      if (!cmd) return;
      const done = () => {
        btn.dataset.copied = 'true';
        const lbl = btn.querySelector('.ov-wait-copy');
        if (lbl) lbl.textContent = 'Copied';
        const status = byIdEl('ovCopyStatus');
        if (status) status.textContent = `Copied command: ${cmd}`;
        setTimeout(() => {
          btn.dataset.copied = 'false';
          if (lbl) lbl.textContent = 'Copy';
        }, 1800);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmd).then(done, () => {
          try {
            const ta = document.createElement('textarea');
            ta.value = cmd;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            done();
          } catch (_) { /* no clipboard */ }
        });
      }
    });
  });

  /* ---------- Preamble: honest-scale screening funnel ---------- */
  (function renderPreamble() {
    if (!pipe.length) {
      byIdEl('ovPreamble').hidden = true;
      return;
    }
    const top = Math.max(1, pipe[0].n || 0);
    const inc = pipe[pipe.length - 1].n ?? nIncAll;
    const incPct = ((100 * inc) / top).toFixed(1);

    byIdEl('ovPreSub').textContent = `${fmt(top)} identified records narrow linearly from zero to ${fmt(inc)} included papers (${incPct}%).`;
    byIdEl('ovBridgeTag').textContent = `+ ${fmt(inc)} included papers on stage below`;

    const STEP_LABEL = { identified: 'Identified', screened: 'Screened', sought: 'Full text sought', assessed: 'Assessed', included: 'Included' };
    const OF_LABEL = { screened: 'identified', sought: 'passing title & abstract', assessed: 'sought', included: 'assessed' };
    const LOSS_HTML = {
      duplicates: () => `${H.term('duplicates')} removed`,
      not_sought: () => `not sought (${H.term('cap', 'rapid-review cap')})`,
      not_retrieved: () => H.term('notretrieved'),
      pending: () => 'pending',
      excluded_full_text: () => 'excluded at full text',
      excluded_ta: () => 'excluded at title & abstract',
    };

    const Wv = 1000, Hv = 172, maxBandH = 108, baselineY = 126, padX = 20;
    const colW = (Wv - padX * 2) / pipe.length;
    const colInner = colW * 0.52;
    const heights = pipe.map(s => (s.n == null ? 0 : (maxBandH * s.n) / top));
    const xs = pipe.map((_, i) => padX + i * colW);

    let svg = `<svg viewBox="0 0 ${Wv} ${Hv}" role="img" aria-label="Screening flow from ${fmt(top)} identified records narrowing linearly to ${fmt(inc)} included papers">`;
    svg += `<line x1="${padX}" y1="${baselineY}" x2="${Wv - padX}" y2="${baselineY}" stroke="var(--line)" stroke-width="1"/>`;
    svg += `<line x1="${padX}" y1="${baselineY - maxBandH}" x2="${Wv - padX}" y2="${baselineY - maxBandH}" stroke="var(--hair)" stroke-dasharray="3 4" stroke-width="1"/>`;
    svg += `<text x="${Wv - padX}" y="${baselineY - maxBandH - 6}" text-anchor="end" class="axis">Linear scale from 0 to ${fmt(top)}</text>`;

    for (let i = 0; i < pipe.length - 1; i++) {
      if (pipe[i].n == null || pipe[i + 1].n == null) continue;
      const x1 = xs[i] + colInner, x2 = xs[i + 1];
      const h1 = heights[i], h2 = heights[i + 1];
      const y1Top = baselineY - h1, y2Top = baselineY - h2;
      const cx = (x1 + x2) / 2;
      const isLast = i === pipe.length - 2;
      svg += `<path d="M ${x1} ${y1Top} C ${cx} ${y1Top}, ${cx} ${y2Top}, ${x2} ${y2Top} L ${x2} ${baselineY} L ${x1} ${baselineY} Z" fill="${isLast ? 'var(--inc)' : 'var(--mut)'}" fill-opacity="${isLast ? '0.28' : '0.16'}"/>`;
      const drop = pipe[i].n - pipe[i + 1].n;
      if (drop > 0) {
        const dropMidX = (x1 + x2) / 2;
        const dropEndY = Math.min(baselineY - h2, y1Top + Math.max(10, (h1 - h2) * 0.45));
        svg += `<line x1="${dropMidX}" y1="${y1Top + 2}" x2="${dropMidX}" y2="${dropEndY}" stroke="var(--exc)" stroke-width="1.2" stroke-dasharray="2 2"/>`;
        svg += `<text x="${dropMidX}" y="${Math.max(12, y1Top - 4)}" text-anchor="middle" fill="var(--exc)" font-family="var(--f-mono)" font-size="10.5">−${fmt(drop)}</text>`;
      }
    }

    pipe.forEach((s, i) => {
      const x = xs[i], h = heights[i], y = baselineY - h;
      const isInc = s.key === 'included';
      const numText = s.n == null ? 'not run' : `${isInc ? '+ ' : ''}${fmt(s.n)}`;
      if (s.n != null) {
        svg += `<rect x="${x}" y="${y}" width="${colInner}" height="${Math.max(1.5, h)}" rx="2" fill="${isInc ? 'var(--inc)' : 'var(--mut)'}" fill-opacity="${isInc ? '0.92' : '0.55'}"/>`;
      }
      const labelY = Math.min(baselineY - h - 7, baselineY - 12);
      svg += `<text x="${x + colInner / 2}" y="${labelY}" text-anchor="middle" fill="${isInc ? 'var(--inc)' : 'var(--fg)'}" font-family="var(--f-mono)" font-weight="600" font-size="12.5">${esc(numText)}</text>`;
      svg += `<text x="${x + colInner / 2}" y="${baselineY + 17}" text-anchor="middle" class="lbl">${esc(STEP_LABEL[s.key] || H.pretty(s.key))}</text>`;
      if (s.n != null) {
        const pStr = ((100 * s.n) / top).toFixed(s.n / top < 0.1 ? 1 : 0) + '%';
        svg += `<text x="${x + colInner / 2}" y="${baselineY + 32}" text-anchor="middle" class="axis">${pStr}</text>`;
      }
    });
    svg += '</svg>';
    byIdEl('ovFunnelViz').innerHTML = svg;

    byIdEl('ovFunnelSteps').innerHTML = pipe.map((s, i) => {
      const isInc = s.key === 'included';
      const extraLosses = [];
      if (i > 0 && s.of != null && pipe[i - 1].n != null && pipe[i - 1].n > s.of) {
        extraLosses.push(['excluded_ta', pipe[i - 1].n - s.of]);
      }
      const allLosses = [...extraLosses, ...Object.entries(s.loss || {})];
      const shareBar = s.n == null ? 0 : Math.max(0.8, (100 * s.n) / top);
      return `<a class="ov-fstep${isInc ? ' ov-inc' : ''}" role="listitem" href="flow.html#node=${esc(s.key)}">
        <div class="ov-fstep-lbl">${esc(STEP_LABEL[s.key] || H.pretty(s.key))}</div>
        <div class="ov-fstep-num">${s.n == null ? '–' : `${isInc ? '+ ' : ''}${fmt(s.n)}`}</div>
        <div class="ov-fstep-bar" title="${s.n == null ? 'Stage not run' : `${fmt(s.n)} of ${fmt(top)} identified`}"><i style="width:${shareBar.toFixed(2)}%"></i></div>
        <div class="ov-fstep-of">${s.not_run ? 'not run' : (s.of != null ? `of ${fmt(s.of)} ${esc(OF_LABEL[s.key] || '')}` : 'all identified')}</div>
        <div class="ov-fstep-losses">${allLosses.length
          ? allLosses.map(([k, v]) => `<div class="ov-floss">− ${fmt(v)} ${(LOSS_HTML[k] || (() => esc(H.pretty(k))))()}</div>`).join('')
          : '<div class="ov-floss ov-none">Entry point</div>'}</div>
      </a>`;
    }).join('');

    byIdEl('ovFunnelCap').textContent = `Honest scale: each ribbon height and step bar is linear from zero to ${fmt(top)}. ${fmt(inc)} included (${incPct}%) enter the corpus below.`;
  })();

  /* ---------- Epilogue: production line & sets reconciliation ---------- */
  (function renderEpilogue() {
    const lineGrid = byIdEl('ovLineGrid');
    if (lineGrid && (O.line || []).length) {
      const LINE_LABEL = { converted: 'Converted', mined: 'Mined', synthesised: 'Synthesised', reported: 'Reported' };
      const LINE_UNIT = { documents: 'full texts as text', 'miner rows': 'rows recorded', 'pages recorded': 'pages recorded', 'products built': 'pages built' };
      lineGrid.innerHTML = O.line.map(item => `
        <a class="ov-line-card" role="listitem" href="${esc(item.href || 'pipeline.html')}">
          <div class="ov-line-key">${esc(LINE_LABEL[item.key] || H.pretty(item.key))}</div>
          <div class="ov-line-num">${item.n == null ? '–' : fmt(item.n)}</div>
          <div class="ov-line-unit">${item.n == null ? 'not available yet' : esc(LINE_UNIT[item.unit] || item.unit || '')}</div>
          <div class="ov-line-go">Open ${esc((item.href || 'pipeline.html').replace('.html', ''))} →</div>
        </a>
      `).join('');
    }

    const S = O.sets || {};
    const shS = H.RF.sets || {};
    const nRead = (S.read_in_full || []).length || shS.read_in_full || lead.read_in_full || 0;
    const nSetInc = (S.included || []).length || shS.included || nIncAll;
    const dupLen = (S.duplicate_mapped || []).length || shS.duplicate_mapped || 0;
    const minedExLen = (S.mined_but_excluded || []).length || shS.mined_but_excluded || 0;
    const notReadLen = (S.not_read_yet || []).length || shS.not_read_yet || 0;
    const parts = [];
    if (dupLen) parts.push(`${fmt(dupLen)} duplicate records were read under their own id and are shown on the canonical record`);
    if (minedExLen) parts.push(`${fmt(minedExLen)} papers were read in full but excluded at full text`);
    if (notReadLen) parts.push(`${fmt(notReadLen)} included paper${notReadLen === 1 ? '' : 's'} not yet read in full`);
    const panel = `<b>Two counts, one corpus</b><p>${parts.map(esc).join('; ')}${parts.length ? '.' : ''}</p><p><span class=k>How it's computed.</span> ${esc(S.methods || meth.sets || '')}</p>`;
    byIdEl('ovFoot').innerHTML = `${H.info(panel, 'About the paper counts')}<span>${H.term('mined', 'Papers read in full')}: <strong class="mono">${fmt(nRead)}</strong>; ${H.term('included', 'included')} by screening: <strong class="mono">${fmt(nSetInc)}</strong>. ${WHOLE}</span>`;
  })();

  /* ---------- Interactive morph state ---------- */
  let DOTS = [];
  let activeStage = 0;
  let prevStage = 0;
  let morphStart = 0;
  let morphDuration = 760;
  let isMorphing = false;
  let rafId = 0;
  let canvasW = 0;
  let canvasH = 0;
  let dpr = 1;
  const layoutCache = new Map();
  let hoveredIdx = -1;
  let focusedIdx = -1;
  let cursorHasFocus = false;
  let activeFilter = null;
  let searchQuery = '';
  const stageOrders = [[], [], [], [], [], []];
  let smallMultipleCanvases = [];
  const reduceMotionMQ = window.matchMedia('(prefers-reduced-motion: reduce)');
  let manualMultiples = false;
  const isMultiplesMode = () => reduceMotionMQ.matches || manualMultiples;

  /* ---------- Narrative chapters ---------- */
  function bindFilterButtons(container) {
    container.querySelectorAll('[data-filter-kind]').forEach(btn => {
      btn.addEventListener('click', () => {
        const kind = btn.dataset.filterKind;
        const val = btn.dataset.filterVal;
        if (activeFilter && activeFilter.kind === kind && activeFilter.value === val) activeFilter = null;
        else activeFilter = { kind, value: val };
        main.querySelectorAll('[data-filter-kind]').forEach(b => {
          const on = Boolean(activeFilter && activeFilter.kind === b.dataset.filterKind && activeFilter.value === b.dataset.filterVal);
          b.setAttribute('aria-pressed', String(on));
        });
        drawCurrentView();
      });
    });
  }

  function renderNarrative() {
    const layerCounts = comp.layer || {};
    const humanCounts = comp.human || {};

    byIdEl('ovS0Title').textContent = `${fmt(nInc)} included papers`;
    byIdEl('ovS0Cap').textContent = `Every dot forming “${fmt(nInc)}” is one included work. Scroll to rearrange these same dots across publication time, layer, ${HAS_FACET ? FACET_LABEL.toLowerCase() + ', ' : ''}citations and monthly pace.`;
    byIdEl('ovS0N').textContent = scopeOn() ? `n = ${fmt(nInc)} of ${fmt(ALL.length)} included` : `n = ${fmt(nInc)} of ${fmt(lead.identified)} identified`;

    /* a layer the whole corpus holds keeps its row at 0 under a scope (HS-24) */
    const layerRows = LAYER_KEYS.filter(k => LAYER_CNT[k] || layerCounts[k]).map(layerInfo);
    const buildLayerChips = targetEl => {
      targetEl.innerHTML = layerRows.map(([k, label, tok]) => `
        <button type="button" class="chip" data-filter-kind="layer" data-filter-val="${esc(k)}" aria-pressed="false">
          <span class="dot${k === 'unlayered' ? ' ov-hollow' : ''}" style="${k === 'unlayered' ? `color:var(${tok})` : `background:var(${tok})`}"></span>
          ${esc(label)} <span class="n">${fmt(layerCounts[k] || 0)}</span>
        </button>
      `).join('');
      bindFilterButtons(targetEl);
    };
    buildLayerChips(byIdEl('ovS0Legend'));
    buildLayerChips(byIdEl('ovS1Legend'));

    byIdEl('ovS1Cap').textContent = months.length
      ? `Each dot moves to its publication month (${ymLabel(months[0])} to ${ymLabel(lastM)}) and layer band. Circle area scales linearly with citations here${LAYER_CNT.unlayered ? '; hollow rings are unlayered' : ''}.`
      : 'Publication dates appear here once dated papers are included.';
    byIdEl('ovS1N').textContent = `n = ${fmt(WORKS.length)} · ${fmt(months.length)} months`;

    const presentLayers = layerRows;
    const topLayer = presentLayers.reduce((best, l) => ((layerCounts[l[0]] || 0) > (layerCounts[best[0]] || 0) ? l : best), presentLayers[0]);
    byIdEl('ovS2Cap').textContent = !presentLayers.length ? 'Layer counts appear once papers are assigned layers.'
      : !nInc ? 'No paper is in scope, so every layer reads 0.'
      : `The ${fmt(nInc)} dots pack into horizontal unit-dot bars starting from zero. ${topLayer[1]} is the largest layer (${fmt(layerCounts[topLayer[0]])}, ${pct(layerCounts[topLayer[0]], nInc)}%).`;
    byIdEl('ovS2N').textContent = `n = ${fmt(nInc)} across ${fmt(presentLayers.length)} layers`;
    byIdEl('ovS2Bd').innerHTML = presentLayers.map(([k, label, tok]) => `
      <button type="button" class="ov-bd-row" data-filter-kind="layer" data-filter-val="${esc(k)}" aria-pressed="false">
        <span class="dot${k === 'unlayered' ? ' ov-hollow' : ''}" style="${k === 'unlayered' ? `color:var(${tok})` : `background:var(${tok})`}"></span>
        <span>${esc(label)}</span>
        <span class="ov-bd-val">${fmt(layerCounts[k] || 0)} · ${pct(layerCounts[k] || 0, nInc)}%</span>
      </button>
    `).join('');
    bindFilterButtons(byIdEl('ovS2Bd'));

    /* The facet chapter: the project's own facet; the pilot's "no human in the loop" reading only for the pilot's field. */
    const facetOn = HAS_FACET;
    byIdEl('ovStep-3').hidden = !facetOn;
    byIdEl('ovStep-3').style.display = facetOn ? '' : 'none';
    const involvedN = Math.max(0, codedN - noneN);
    const notCodedN = humanCounts.null || 0;
    byIdEl('ovS3Cap').textContent = !facetOn ? '' : !codedN
      ? `${FACET_LABEL} counts appear once papers carry a value.`
      : PIL
        ? `Dots re-colour by human role on a 0–100% scale of ${fmt(codedN)} coded papers. No human in the loop (${fmt(noneN)}, ${sharePct}%) stands against ${fmt(involvedN)} (${100 - sharePct}%) with human involvement.`
        : `Dots re-colour by ${FACET_LABEL} on a 0–100% scale of the ${fmt(codedN)} papers that carry a value; ${fmt(notCodedN)} do not.`;
    byIdEl('ovS3N').textContent = !facetOn ? '' : PIL && codedN
      ? `${fmt(noneN)} of ${fmt(codedN)} coded (${sharePct}%) · ${fmt(notCodedN)} not coded`
      : `${fmt(codedN)} of ${fmt(nInc)} with a value · ${fmt(notCodedN)} not coded`;
    const facetRows = HUMAN_ALL.filter(([k]) => humanCounts[k] || (FACET_CNT[k] && k !== 'null'));
    byIdEl('ovS3Bd').innerHTML = facetRows.map(([k, label, tok]) => {
      const n = humanCounts[k] || 0;
      const shareStr = k === 'null' ? 'not coded' : `${pct(n, codedN)}% of coded`;
      return `<button type="button" class="ov-bd-row${PIL && k === 'none' ? ' ov-half' : ''}" data-filter-kind="human" data-filter-val="${esc(k)}" aria-pressed="false">
        <span class="dot${k === 'null' ? ' ov-hollow' : ''}" style="${k === 'null' ? `color:var(${tok})` : `background:var(${tok})`}"></span>
        <span>${esc(label)}</span>
        <span class="ov-bd-val">${fmt(n)} · ${shareStr}</span>
      </button>`;
    }).join('');
    bindFilterButtons(byIdEl('ovS3Bd'));

    const citedAny = WORKS.filter(w => w._cited > 0).length;
    const uncited = WORKS.length - citedAny;
    const top1 = mc[0];
    byIdEl('ovS4Cap').textContent = top1
      ? `Circle area grows in proportion to citations inside the review. “${shortTitle(top1.title, 34)}” leads with ${fmt(top1.cited_here)} citations here; ${fmt(uncited)} have 0.${scopeOn() ? ' Counts are those of the whole review.' : ''}`
      : 'Citation counts appear once reference lists are extracted.';
    byIdEl('ovS4N').textContent = `${fmt(citedAny)} cited ≥1× · ${fmt(uncited)} at 0×`;

    const topShow = 8;
    byIdEl('ovS4List').innerHTML = mc.slice(0, topShow).map((m, i) => {
      const tok = layerInfo(m.layer)[2];
      return `<button type="button" class="ov-top-btn" data-id="${esc(m.id)}">
        <span class="ov-top-rank">#${i + 1}</span>
        <span class="dot" style="background:var(${tok})"></span>
        <span class="ov-top-ti" title="${esc(m.title)}">${esc(m.title)}</span>
        <span class="ov-top-n">${fmt(m.cited_here)}×</span>
      </button>`;
    }).join('');
    byIdEl('ovS4List').querySelectorAll('button[data-id]').forEach(btn => {
      btn.addEventListener('click', () => H.openDrawer(btn.dataset.id));
      btn.addEventListener('mouseenter', () => {
        const idx = WORKS.findIndex(w => w.id === btn.dataset.id);
        if (idx >= 0) setHoveredDot(idx);
      });
      btn.addEventListener('mouseleave', () => setHoveredDot(-1));
    });

    const detailsEl = byIdEl('ovAllCitedDetails');
    detailsEl.hidden = false;
    if (mc.length > topShow) {
      byIdEl('ovAllCitedSummary').textContent = `Show all ${fmt(mc.length)} most cited`;
      byIdEl('ovAllCitedTable').innerHTML = `
        <table class="t">
          <thead><tr>
            <th>Paper</th><th class="r">Year</th><th class="r">${H.term('cic', 'Cited here')}</th>
            <th class="r">Same authors</th>
            <th class="r">Elsewhere ${H.info('<b>Cited elsewhere</b>The citation count stored with the paper from OpenAlex. It counts citations from the whole literature and is never added to cited here.', 'About the stored count')}</th>
          </tr></thead>
          <tbody>${mc.map(m => `
            <tr tabindex="0" data-id="${esc(m.id)}">
              <td class="ti" title="${esc(m.title)}">${esc(m.title)}</td>
              <td class="r">${m.year == null ? '–' : esc(m.year)}</td>
              <td class="r">${fmt(m.cited_here)}</td>
              <td class="r">${fmt(m.self_cited)}</td>
              <td class="r">${m.external == null ? '–' : fmt(m.external)}</td>
            </tr>`).join('')}</tbody>
        </table>`;
      byIdEl('ovAllCitedTable').querySelectorAll('tr[data-id]').forEach(tr => {
        tr.addEventListener('click', () => H.openDrawer(tr.dataset.id));
        tr.addEventListener('keydown', e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            H.openDrawer(tr.dataset.id);
          }
        });
      });
    } else {
      detailsEl.hidden = true;
    }

    const busy = busiest;
    const lastN = mcounts[months.length - 1] || 0;
    const years = [...new Set(WORKS.map(w => w.year).filter(Boolean))].sort((a, b) => a - b);
    const yrCompare = years.length >= 2
      ? (() => {
          const y1 = years[years.length - 2], y2 = years[years.length - 1];
          const c1 = WORKS.filter(w => w.year === y1).length;
          const c2 = WORKS.filter(w => w.year === y2).length;
          return ` ${fmt(c2)} appeared in ${y2} versus ${fmt(c1)} in ${y1}.`;
        })()
      : '';
    byIdEl('ovS5Cap').textContent = months.length
      ? `All ${fmt(nInc)} dots stack from zero into monthly unit-dot columns (${ymLabel(months[0])}–${ymLabel(lastM)}).${yrCompare} Peak: ${ymLabel(busy.month)} (${fmt(busy.n)}).`
      : 'Monthly growth appears once dated papers are included.';
    byIdEl('ovS5N').textContent = months.length
      ? `Peak ${ymShort(busy.month)}: ${fmt(busy.n)} · ${ymShort(lastM)}: ${fmt(lastN)} (partial)`
      : 'No monthly data yet';
    byIdEl('ovS5Callouts').innerHTML = months.length
      ? `<div class="ov-callout">
          <div class="ov-callout-k">Busiest month</div>
          <div class="ov-callout-v">${esc(ymLabel(busy.month))}</div>
          <div class="ov-callout-s">${fmt(busy.n)} (${pct(busy.n, nInc)}% of corpus)</div>
        </div>
        <div class="ov-callout">
          <div class="ov-callout-k">Latest month (partial)</div>
          <div class="ov-callout-v">${esc(ymLabel(lastM))}</div>
          <div class="ov-callout-s">${fmt(lastN)} so far · dashed frame</div>
        </div>`
      : '';
  }

  renderNarrative();

  /* ---------- Empty corpus guard ---------- */
  if (!ALL.length) {
    byIdEl('ovStory').innerHTML = '<div class="card ov-empty">Included papers appear here once screening completes.</div>';
    return;
  }

  /* ---------- Stage 0 glyph sampler: dynamically renders String(N) into exact N dots ---------- */
  const glyphPointCache = new Map();
  function sampleNumberDots(text, count) {
    const key = `${text}:${count}`;
    if (glyphPointCache.has(key)) return glyphPointCache.get(key);

    const ow = 440, oh = 210;
    const c = document.createElement('canvas');
    c.width = ow;
    c.height = oh;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.clearRect(0, 0, ow, oh);
    ctx.fillStyle = PAL['--fg'] || 'currentColor';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = `700 162px ${PAL.fontUi}`;
    ctx.fillText(text, ow / 2, oh / 2 + 6);

    const img = ctx.getImageData(0, 0, ow, oh).data;
    const isInside = (x, y) => {
      const ix = Math.round(x), iy = Math.round(y);
      if (ix < 0 || ix >= ow || iy < 0 || iy >= oh) return false;
      return img[(iy * ow + ix) * 4 + 3] > 120;
    };

    let lo = 2.0, hi = 28.0, bestPts = [];
    for (let iter = 0; iter < 18; iter++) {
      const step = (lo + hi) / 2;
      const dy = step * 0.866;
      const pts = [];
      let row = 0;
      for (let y = 4; y < oh - 4; y += dy, row++) {
        const xOff = (row % 2) * (step * 0.5);
        for (let x = 4 + xOff; x < ow - 4; x += step) {
          if (isInside(x, y)) pts.push({ x, y });
        }
      }
      if (pts.length >= count) {
        bestPts = pts;
        lo = step;
      } else {
        hi = step;
      }
    }

    if (bestPts.length < count) {
      for (let y = 2; y < oh - 2 && bestPts.length < count; y += 2) {
        for (let x = 2; x < ow - 2 && bestPts.length < count; x += 2) {
          if (isInside(x, y)) bestPts.push({ x, y });
        }
      }
    }

    bestPts.sort((a, b) => a.x - b.x || a.y - b.y);
    let chosen = [];
    if (bestPts.length === count) {
      chosen = bestPts;
    } else if (bestPts.length > count) {
      const ratio = bestPts.length / count;
      for (let i = 0; i < count; i++) {
        chosen.push(bestPts[Math.min(bestPts.length - 1, Math.floor(i * ratio))]);
      }
    } else {
      chosen = bestPts.slice();
      while (chosen.length < count) {
        const p = bestPts[chosen.length % Math.max(1, bestPts.length)] || { x: ow / 2, y: oh / 2 };
        chosen.push({ x: p.x + 1.5, y: p.y + 1.5 });
      }
    }

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of chosen) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    const bw = Math.max(1, maxX - minX);
    const bh = Math.max(1, maxY - minY);
    const result = {
      points: chosen.map(p => ({ nx: (p.x - minX) / bw, ny: (p.y - minY) / bh })),
      aspect: Math.max(0.4, bw / bh),
      stepNorm: lo / bw,
    };
    glyphPointCache.set(key, result);
    return result;
  }

  /* ---------- Layout engine (6 stages) ---------- */
  function getStageLayout(stageIdx, Wc, Hc) {
    const key = `${stageIdx}:${Math.round(Wc)}x${Math.round(Hc)}`;
    if (layoutCache.has(key)) return layoutCache.get(key);

    const N = WORKS.length;
    const narrow = Wc < 540;
    const targets = new Array(N);
    let meta = {};
    let order = [];
    const layerRank = new Map(LAYER_KEYS.map((k, i) => [k, i]));

    if (stageIdx === 0) {
      const sampled = sampleNumberDots(String(N), N);
      const padX = Wc * (narrow ? 0.08 : 0.11);
      const padTop = Hc * 0.14;
      const padBot = Hc * 0.2;
      const availW = Math.max(120, Wc - padX * 2);
      const availH = Math.max(90, Hc - padTop - padBot);
      let drawW = availW;
      let drawH = drawW / sampled.aspect;
      if (drawH > availH) {
        drawH = availH;
        drawW = drawH * sampled.aspect;
      }
      const ox = (Wc - drawW) / 2;
      const oy = padTop + (availH - drawH) / 2;
      const dotR = Math.max(2.0, Math.min(5.0, sampled.stepNorm * drawW * 0.36));
      const sorted = WORKS.map((_, i) => i).sort((a, b) =>
        (layerRank.get(WORKS[a]._layer) - layerRank.get(WORKS[b]._layer)) ||
        (WORKS[a]._mIdx - WORKS[b]._mIdx) ||
        (WORKS[b]._cited - WORKS[a]._cited)
      );
      order = sorted;
      sorted.forEach((workIdx, k) => {
        const p = sampled.points[k];
        const w = WORKS[workIdx];
        targets[workIdx] = {
          x: ox + p.nx * drawW,
          y: oy + p.ny * drawH,
          r: dotR,
          tok: layerInfo(w._layer)[2],
          hollow: w._layer === 'unlayered' ? 1 : 0,
        };
      });
      meta = { ox, oy, drawW, drawH, dotR, caption: `${fmt(N)} included · 1 dot = 1 work · colour = layer` };
    } else if (stageIdx === 1) {
      const mL = narrow ? 14 : 110;
      const mR = narrow ? 14 : 20;
      const mT = narrow ? 22 : 28;
      const mB = 34;
      const innerW = Math.max(140, Wc - mL - mR);
      const innerH = Math.max(140, Hc - mT - mB);
      const mw = innerW / Math.max(1, months.length);

      const bCounts = {};
      BANDS.forEach(b => { bCounts[b] = 0; });
      WORKS.forEach(w => { bCounts[bandOf(w._layer)]++; });

      const gapY = 6;
      const totalGap = gapY * (BANDS.length - 1);
      const sqrtSum = BANDS.reduce((a, b) => a + Math.sqrt(Math.max(1, bCounts[b])), 0) || 1;
      const rawH = BANDS.map(b => Math.max(narrow ? 26 : 32, (Math.sqrt(Math.max(1, bCounts[b])) / sqrtSum) * (innerH - totalGap)));
      const scaleH = (innerH - totalGap) / rawH.reduce((a, b) => a + b, 0);
      const finalBandH = rawH.map(h => h * scaleH);
      const bandY = [];
      let cy = mT;
      finalBandH.forEach(h => { bandY.push(cy); cy += h + gapY; });

      const r0 = narrow ? 2.1 : 2.7;
      const kArea = narrow ? 1.15 : 2.35;
      const radiusFor = c => Math.sqrt(r0 * r0 + kArea * c);

      const bandNodes = BANDS.map(() => []);
      WORKS.forEach((w, i) => {
        const bi = BANDS.indexOf(bandOf(w._layer));
        const mi = mMap.has(w._ym) ? mMap.get(w._ym) : Math.max(0, months.length - 1);
        const x0 = mL + (mi + 0.16 + 0.68 * hashf(w.id)) * mw;
        const lo = bandY[bi] + (narrow ? 14 : 4);
        const hi = bandY[bi] + finalBandH[bi] - 4;
        const y0 = lo + (hi - lo) * (0.18 + 0.64 * hashf(`${w.id}y`));
        bandNodes[bi].push({ i, r: radiusFor(w._cited), x0, x: x0, y: y0, lo, hi });
      });

      const iters = N > 120 ? 120 : 80;
      bandNodes.forEach(ns => {
        for (let it = 0; it < iters; it++) {
          for (let a = 0; a < ns.length; a++) {
            const na = ns[a];
            for (let b = a + 1; b < ns.length; b++) {
              const nb = ns[b];
              const dx = nb.x - na.x, dy = nb.y - na.y;
              const minD = na.r + nb.r + 0.9;
              const d2 = dx * dx + dy * dy;
              if (d2 < minD * minD) {
                const dd = Math.sqrt(d2) || 0.01;
                const push = ((minD - dd) / dd) * 0.5;
                na.x -= dx * push; na.y -= dy * push;
                nb.x += dx * push; nb.y += dy * push;
              }
            }
          }
          for (let a = 0; a < ns.length; a++) {
            const na = ns[a];
            na.x += (na.x0 - na.x) * 0.12;
            na.x = Math.min(Wc - mR - na.r, Math.max(mL + na.r, na.x));
            na.y = Math.min(na.hi - na.r, Math.max(na.lo + na.r, na.y));
          }
        }
        ns.forEach(na => {
          const w = WORKS[na.i];
          targets[na.i] = { x: na.x, y: na.y, r: na.r, tok: layerInfo(w._layer)[2], hollow: w._layer === 'unlayered' ? 1 : 0 };
        });
      });

      order = WORKS.map((_, i) => i).sort((a, b) =>
        (BANDS.indexOf(bandOf(WORKS[a]._layer)) - BANDS.indexOf(bandOf(WORKS[b]._layer))) || (targets[a].x - targets[b].x)
      );
      meta = { mL, mR, mT, mB, innerW, mw, bandY, bandH: finalBandH, bCounts, r0, kArea, months };
    } else if (stageIdx === 2) {
      const present = LAYER_KEYS.map(layerInfo).filter(([k]) => WORKS.some(w => w._layer === k));
      const mL = narrow ? 88 : 126;
      const mR = narrow ? 60 : 94;
      const mT = 24;
      const mB = 40;
      const innerW = Math.max(120, Wc - mL - mR);
      const innerH = Math.max(140, Hc - mT - mB);

      const groups = present.map(([k, label, tok]) => {
        const idxs = WORKS.map((_, i) => i)
          .filter(i => WORKS[i]._layer === k)
          .sort((a, b) => WORKS[b]._cited - WORKS[a]._cited || WORKS[a]._mIdx - WORKS[b]._mIdx);
        return { k, label, tok, idxs, n: idxs.length };
      });

      const maxCount = Math.max(1, ...groups.map(g => g.n));
      const stepTick = maxCount <= 20 ? 5 : maxCount <= 60 ? 10 : 50;
      const axisMax = Math.max(stepTick, Math.ceil(maxCount / stepTick) * stepTick);
      const rowH = innerH / Math.max(1, groups.length);
      const rowsPerBar = maxCount <= 12 ? 1 : (narrow ? 6 : 5);
      const maxCols = Math.max(1, Math.ceil(axisMax / rowsPerBar));
      const dx = innerW / maxCols;
      const dy = Math.min(dx, (rowH * 0.66) / rowsPerBar);
      const dotR = Math.max(1.5, Math.min(4.0, Math.min(dx, dy) * 0.39));

      const bars = [];
      groups.forEach((g, gi) => {
        const centerY = mT + (gi + 0.5) * rowH;
        const barTop = centerY - ((rowsPerBar - 1) * dy) / 2;
        const colsUsed = Math.ceil(g.n / rowsPerBar);
        g.idxs.forEach((workIdx, k) => {
          const col = Math.floor(k / rowsPerBar);
          const row = k % rowsPerBar;
          targets[workIdx] = {
            x: mL + (col + 0.5) * dx,
            y: barTop + row * dy,
            r: dotR,
            tok: g.tok,
            hollow: g.k === 'unlayered' ? 1 : 0,
          };
          order.push(workIdx);
        });
        bars.push({ ...g, y: centerY, endX: mL + Math.max(1, colsUsed) * dx });
      });

      meta = { mL, mR, mT, mB, innerW, innerH, axisMax, stepTick, bars, total: N };
    } else if (stageIdx === 3) {
      const present = HUMAN_ALL.filter(([k]) => WORKS.some(w => w._human === k));
      const cN = Math.max(1, codedN || WORKS.length);
      const axisMax = Math.max(cN, WORKS.length);
      const halfVal = cN / 2;

      const mL = narrow ? 110 : 180;
      const mR = narrow ? 54 : 92;
      const mT = 38;
      const mB = 40;
      const innerW = Math.max(120, Wc - mL - mR);
      const innerH = Math.max(140, Hc - mT - mB);

      const groups = present.map(([k, label, tok]) => {
        const idxs = WORKS.map((_, i) => i)
          .filter(i => WORKS[i]._human === k)
          .sort((a, b) => WORKS[b]._cited - WORKS[a]._cited || WORKS[a]._mIdx - WORKS[b]._mIdx);
        return { k, label, tok, idxs, n: idxs.length };
      });

      const hasNoneFirst = PIL && groups.length > 1 && groups[0].k === 'none';
      const dividerGap = hasNoneFirst ? 22 : 0;
      const rowH = (innerH - dividerGap) / Math.max(1, groups.length);
      const rowsPerBar = N <= 15 ? 1 : (narrow ? 8 : 6);
      const maxCols = Math.max(1, Math.ceil(axisMax / rowsPerBar));
      const dx = innerW / maxCols;
      const dy = Math.min(dx * 1.15, (rowH * 0.68) / rowsPerBar);
      const dotR = Math.max(1.35, Math.min(3.5, Math.min(dx, dy) * 0.4));

      const bars = [];
      groups.forEach((g, gi) => {
        const extraY = (hasNoneFirst && gi > 0) ? dividerGap : 0;
        const centerY = mT + extraY + (gi + 0.5) * rowH;
        const barTop = centerY - ((rowsPerBar - 1) * dy) / 2;
        const colsUsed = Math.ceil(g.n / rowsPerBar);
        g.idxs.forEach((workIdx, k) => {
          const col = Math.floor(k / rowsPerBar);
          const row = k % rowsPerBar;
          targets[workIdx] = {
            x: mL + (col + 0.5) * dx,
            y: barTop + row * dy,
            r: dotR,
            tok: g.tok,
            hollow: g.k === 'null' ? 1 : 0,
          };
          order.push(workIdx);
        });
        bars.push({ ...g, y: centerY, endX: mL + Math.max(1, colsUsed) * dx });
      });

      const halfX = mL + (halfVal / axisMax) * innerW;
      const dividerY = hasNoneFirst ? mT + rowH + dividerGap * 0.5 : -1;
      const involvedCount = groups.filter(g => g.k !== 'none' && g.k !== 'null').reduce((a, b) => a + b.n, 0);
      meta = { mL, mR, mT, mB, innerW, innerH, axisMax, codedN, cN, halfVal, halfX, dividerY, involvedCount, bars };
    } else if (stageIdx === 4) {
      const sorted = WORKS.map((_, i) => i).sort((a, b) =>
        (WORKS[b]._cited - WORKS[a]._cited) ||
        (WORKS[b]._selfCited - WORKS[a]._selfCited) ||
        WORKS[a].title.localeCompare(WORKS[b].title)
      );
      order = sorted;

      const topK = Math.min(sorted.length, narrow ? 6 : Math.max(3, Math.min(10, Math.floor((Hc - 130) / 38))));
      const maxCited = Math.max(1, WORKS[sorted[0]] ? WORKS[sorted[0]]._cited : 1);
      const mL = narrow ? 14 : 20;
      const mR = narrow ? 14 : 20;
      const mT = 20;
      const hasTail = sorted.length > topK;
      const tailH = hasTail ? (narrow ? 72 : 106) : 0;
      const topAreaH = Math.max(114, Hc - mT - tailH - (hasTail ? 42 : 16));
      const rowH = topAreaH / Math.max(1, topK);

      const maxR = Math.min(rowH * 0.42, narrow ? 12.5 : 17);
      const areaK = (maxR * maxR) / maxCited;
      const bigRadius = c => Math.max(2.6, Math.sqrt(areaK * c));

      const circleColX = mL + (narrow ? 28 : 42);
      const barStartX = circleColX + maxR + (narrow ? 10 : 16);
      const countColW = narrow ? 44 : 60;
      const barMaxW = Math.max(60, Wc - barStartX - mR - countColW);

      const topRows = [];
      for (let rank = 0; rank < topK; rank++) {
        const workIdx = sorted[rank];
        const w = WORKS[workIdx];
        const y = mT + (rank + 0.5) * rowH;
        const r = bigRadius(w._cited);
        targets[workIdx] = { x: circleColX, y, r, tok: layerInfo(w._layer)[2], hollow: w._layer === 'unlayered' ? 1 : 0 };
        topRows.push({ rank: rank + 1, workIdx, w, y, r, barW: (w._cited / maxCited) * barMaxW });
      }

      const tailTop = mT + topAreaH + 40;
      const tailRem = sorted.slice(topK);
      let zeroStartPos = null;
      if (tailRem.length) {
        const tailAvailW = Math.max(140, Wc - mL - mR);
        const tailAvailH = Math.max(44, Hc - tailTop - 14);
        const tailCols = Math.max(12, Math.ceil(Math.sqrt(tailRem.length * (tailAvailW / tailAvailH))));
        const tailRows = Math.ceil(tailRem.length / tailCols);
        const cellW = tailAvailW / tailCols;
        const cellH = Math.min(13, tailAvailH / Math.max(1, tailRows));
        const baseTailR = Math.max(1.5, Math.min(2.6, Math.min(cellW, cellH) * 0.36));

        tailRem.forEach((workIdx, k) => {
          const w = WORKS[workIdx];
          const col = k % tailCols;
          const row = Math.floor(k / tailCols);
          const x = mL + (col + 0.5) * cellW;
          const y = tailTop + (row + 0.5) * cellH;
          if (w._cited === 0 && zeroStartPos === null) zeroStartPos = { x: x - cellW * 0.5, y };
          const r = w._cited > 0 ? Math.min(cellH * 0.46, Math.sqrt(baseTailR * baseTailR + 0.65 * w._cited)) : baseTailR;
          targets[workIdx] = { x, y, r, tok: layerInfo(w._layer)[2], hollow: w._layer === 'unlayered' ? 1 : 0 };
        });
      }

      const tailCitedN = tailRem.filter(i => WORKS[i]._cited > 0).length;
      const tailZeroN = tailRem.length - tailCitedN;
      meta = { mL, mR, mT, circleColX, barStartX, barMaxW, maxCited, topRows, tailTop, tailRemCount: tailRem.length, tailCitedN, tailZeroN, zeroStartPos };
    } else {
      const mL = narrow ? 28 : 44;
      const mR = narrow ? 14 : 22;
      const mT = 38;
      const mB = 40;
      const innerW = Math.max(140, Wc - mL - mR);
      const innerH = Math.max(130, Hc - mT - mB);
      const nMonths = Math.max(1, months.length);
      const maxMonthN = Math.max(1, ...mcounts, Math.ceil(N / nMonths));
      const yStep = maxMonthN <= 10 ? 2 : maxMonthN <= 30 ? 5 : 10;
      const axisMax = Math.max(yStep, Math.ceil(maxMonthN / yStep) * yStep);

      const colSlotW = innerW / nMonths;
      const colsPerMonth = maxMonthN <= 6 ? 1 : 2;
      const maxRows = Math.max(1, Math.ceil(axisMax / colsPerMonth));
      const dy = innerH / maxRows;
      const dx = Math.min(dy * 1.15, (colSlotW * 0.72) / colsPerMonth);
      const dotR = Math.max(1.5, Math.min(4.0, Math.min(dx, dy) * 0.4));
      const baseY = mT + innerH;

      const byMonth = Array.from({ length: nMonths }, () => []);
      WORKS.forEach((w, i) => {
        const mi = mMap.has(w._ym) ? mMap.get(w._ym) : nMonths - 1;
        byMonth[mi].push(i);
      });

      const colCenters = [];
      byMonth.forEach((idxs, mi) => {
        idxs.sort((a, b) => (layerRank.get(WORKS[a]._layer) - layerRank.get(WORKS[b]._layer)) || (WORKS[b]._cited - WORKS[a]._cited));
        const cx = mL + (mi + 0.5) * colSlotW;
        colCenters.push(cx);
        idxs.forEach((workIdx, k) => {
          const row = Math.floor(k / colsPerMonth);
          const sub = k % colsPerMonth;
          const x = cx + (sub - (colsPerMonth - 1) / 2) * dx;
          const y = baseY - (row + 0.5) * dy;
          const w = WORKS[workIdx];
          targets[workIdx] = { x, y, r: dotR, tok: layerInfo(w._layer)[2], hollow: w._layer === 'unlayered' ? 1 : 0 };
          order.push(workIdx);
        });
      });

      const busyIdx = months.indexOf(busiest.month);
      meta = { mL, mR, mT, mB, innerW, innerH, baseY, axisMax, yStep, colSlotW, months, mcounts, colCenters, busiest, busyIdx };
    }

    const res = { targets, meta, order };
    layoutCache.set(key, res);
    return res;
  }

  function roundRect(ctx, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }

  /* ---------- Stage overlay drawing ---------- */
  function drawStageOverlay(ctx, stageIdx, layout, Wc, Hc, alpha) {
    if (alpha <= 0.01) return;
    const { meta } = layout;
    const narrow = Wc < 540;
    ctx.save();
    ctx.globalAlpha = alpha;

    if (stageIdx === 0) {
      ctx.fillStyle = PAL['--dim'];
      ctx.font = `400 ${narrow ? 11 : 12}px ${PAL.fontMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(meta.caption, Wc / 2, meta.oy + meta.drawH + 16);
    } else if (stageIdx === 1) {
      const { mL, mR, mT, innerW, mw, bandY, bandH, bCounts, r0, kArea } = meta;
      BANDS.forEach((b, i) => {
        const y = bandY[i], h = bandH[i];
        ctx.fillStyle = PAL['--bg'];
        roundRect(ctx, mL - 6, y, innerW + 12, h, 6);
        ctx.fill();
        if (!narrow) {
          ctx.fillStyle = PAL['--fg'];
          ctx.font = `500 12px ${PAL.fontUi}`;
          ctx.textAlign = 'right';
          ctx.textBaseline = 'top';
          ctx.fillText(bandLabel(b), mL - 14, y + 7);
          ctx.fillStyle = PAL['--dim'];
          ctx.font = `400 11px ${PAL.fontMono}`;
          ctx.fillText(fmt(bCounts[b]), mL - 14, y + 23);
        } else {
          ctx.fillStyle = PAL['--mut'];
          ctx.font = `600 10.5px ${PAL.fontUi}`;
          ctx.textAlign = 'left';
          ctx.textBaseline = 'top';
          ctx.fillText(`${bandLabel(b)} · ${fmt(bCounts[b])}`, mL, y + 2);
        }
      });

      const ay = bandY[BANDS.length - 1] + bandH[BANDS.length - 1] + 6;
      ctx.strokeStyle = PAL['--line'];
      ctx.fillStyle = PAL['--dim'];
      ctx.font = `400 11px ${PAL.fontMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      months.forEach((m, i) => {
        const mo = +m.slice(5);
        const show = months.length <= 6 || (narrow ? (mo === 1 || mo === 7) : (mo === 1 || mo === 4 || mo === 7 || mo === 10));
        if (!show) return;
        const x = mL + (i + 0.5) * mw;
        ctx.beginPath();
        ctx.moveTo(x, ay);
        ctx.lineTo(x, ay + 4);
        ctx.stroke();
        const tx = i === 0 && narrow ? Math.max(x, 30) : x;
        ctx.fillText(mo === 1 || months.length <= 6 ? `${MON[mo - 1]} ${m.slice(0, 4)}` : MON[mo - 1], tx, ay + 7);
      });

      if (!narrow) {
        const samples = [0, 25, 100];
        let lx = Wc - mR;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = PAL['--dim'];
        ctx.font = `400 10.5px ${PAL.fontMono}`;
        for (let s = samples.length - 1; s >= 0; s--) {
          const val = samples[s];
          const rr = Math.min(10, Math.sqrt(r0 * r0 + kArea * val) * 0.62);
          const lbl = `${val}×`;
          const tw = ctx.measureText(lbl).width;
          ctx.fillText(lbl, lx, mT * 0.5);
          lx -= tw + rr + 4;
          ctx.beginPath();
          ctx.arc(lx, mT * 0.5, rr, 0, Math.PI * 2);
          ctx.strokeStyle = PAL['--mut'];
          ctx.lineWidth = 1;
          ctx.stroke();
          lx -= rr + 10;
        }
        ctx.fillText('Area ∝ cited here:', lx, mT * 0.5);
      }
    } else if (stageIdx === 2) {
      const { mL, mT, innerW, innerH, axisMax, stepTick, bars, total } = meta;
      const baseY = mT + innerH + 6;
      ctx.font = `400 11px ${PAL.fontMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      for (let v = 0; v <= axisMax; v += stepTick) {
        const x = mL + (v / axisMax) * innerW;
        ctx.beginPath();
        ctx.strokeStyle = v === 0 ? PAL['--line'] : PAL['--hair'];
        ctx.lineWidth = 1;
        ctx.moveTo(x, mT);
        ctx.lineTo(x, baseY);
        ctx.stroke();
        ctx.fillStyle = PAL['--dim'];
        ctx.fillText(String(v), x, baseY + 6);
      }
      bars.forEach(b => {
        ctx.fillStyle = PAL['--fg'];
        ctx.font = `500 ${narrow ? 11 : 12.5}px ${PAL.fontUi}`;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(b.label, mL - 12, b.y);
        ctx.fillStyle = PAL['--mut'];
        ctx.font = `400 ${narrow ? 10.5 : 11.5}px ${PAL.fontMono}`;
        ctx.textAlign = 'left';
        ctx.fillText(`${fmt(b.n)} (${pct(b.n, total)}%)`, b.endX + 10, b.y);
      });
      ctx.fillStyle = PAL['--dim'];
      ctx.font = `400 10.5px ${PAL.fontMono}`;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'top';
      ctx.fillText('Linear from 0', mL + innerW, baseY + 21);
    } else if (stageIdx === 3) {
      const { mL, mT, innerW, innerH, axisMax, cN, halfX, dividerY, involvedCount, bars } = meta;
      const baseY = mT + innerH + 6;
      if (PIL) {
        ctx.fillStyle = rgbCss(PAL_RGB['--acc'] || [95, 212, 232], 0.1);
        ctx.fillRect(mL, mT - 4, Math.max(0, halfX - mL), baseY - mT + 4);
      }

      const pctTicks = [0, 25, 50, 75, 100];
      ctx.font = `400 10.5px ${PAL.fontMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      pctTicks.forEach(p => {
        const val = (cN * p) / 100;
        const x = mL + (val / axisMax) * innerW;
        const isHalf = PIL && p === 50;
        ctx.beginPath();
        ctx.strokeStyle = isHalf ? PAL['--acc'] : (p === 0 ? PAL['--line'] : PAL['--hair']);
        ctx.lineWidth = isHalf ? 1.6 : 1;
        if (isHalf) ctx.setLineDash([4, 3]);
        ctx.moveTo(x, mT - 6);
        ctx.lineTo(x, baseY);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = isHalf ? PAL['--acc'] : PAL['--dim'];
        ctx.fillText(`${p}%`, x, baseY + 6);
      });

      if (PIL) {
        ctx.fillStyle = PAL['--acc'];
        ctx.font = `600 ${narrow ? 10.5 : 11.5}px ${PAL.fontMono}`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(narrow ? '50% · half' : `50% meridian · half of ${fmt(codedN)} coded`, halfX, mT - 10);
      }

      if (dividerY > 0) {
        ctx.beginPath();
        ctx.strokeStyle = PAL['--line'];
        ctx.lineWidth = 1;
        ctx.moveTo(mL, dividerY);
        ctx.lineTo(mL + innerW, dividerY);
        ctx.stroke();
        ctx.fillStyle = PAL['--mut'];
        ctx.font = `500 10.5px ${PAL.fontUi}`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'bottom';
        ctx.fillText(`Human involved · ${fmt(involvedCount)} (${pct(involvedCount, cN)}% of coded)`, mL + 4, dividerY - 4);
      }

      bars.forEach(b => {
        const isNone = PIL && b.k === 'none';
        ctx.fillStyle = isNone ? PAL['--fg'] : PAL['--mut'];
        ctx.font = `${isNone ? '600' : '400'} ${narrow ? 10 : 12}px ${PAL.fontUi}`;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        const lbl = narrow && PIL ? b.label.replace('Human ', '').replace(' in the loop', '') : b.label;
        ctx.fillText(lbl, mL - 10, b.y);
        ctx.fillStyle = isNone ? PAL['--fg'] : PAL['--mut'];
        ctx.font = `${isNone ? '600' : '400'} ${narrow ? 10 : 11.5}px ${PAL.fontMono}`;
        ctx.textAlign = 'left';
        const valStr = b.k === 'null' ? fmt(b.n) : `${fmt(b.n)} (${pct(b.n, cN)}%)`;
        ctx.fillText(valStr, b.endX + 8, b.y);
      });
    } else if (stageIdx === 4) {
      const { mL, mR, barStartX, barMaxW, topRows, tailTop, tailRemCount, tailCitedN, tailZeroN, zeroStartPos } = meta;
      topRows.forEach(row => {
        ctx.fillStyle = PAL['--dim'];
        ctx.font = `500 11px ${PAL.fontMono}`;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(`#${row.rank}`, mL + (narrow ? 16 : 22), row.y);

        const barH = 5;
        ctx.fillStyle = PAL['--raised'];
        roundRect(ctx, barStartX, row.y + 5, barMaxW, barH, 2.5);
        ctx.fill();
        const tok = layerInfo(row.w._layer)[2];
        ctx.fillStyle = PAL[tok];
        roundRect(ctx, barStartX, row.y + 5, Math.max(3, row.barW), barH, 2.5);
        ctx.fill();

        ctx.fillStyle = PAL['--fg'];
        ctx.font = `500 ${narrow ? 11 : 12}px ${PAL.fontUi}`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'bottom';
        const maxChars = Math.max(16, Math.floor(barMaxW / (narrow ? 6.6 : 6.9)));
        ctx.fillText(shortTitle(row.w.title, maxChars), barStartX, row.y + 2);

        ctx.fillStyle = PAL['--fg'];
        ctx.font = `600 ${narrow ? 11 : 12}px ${PAL.fontMono}`;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(`${fmt(row.w._cited)}×`, Wc - mR, row.y);
      });

      if (tailRemCount > 0) {
        ctx.beginPath();
        ctx.strokeStyle = PAL['--line'];
        ctx.lineWidth = 1;
        ctx.moveTo(mL, tailTop - 16);
        ctx.lineTo(Wc - mR, tailTop - 16);
        ctx.stroke();

        ctx.fillStyle = PAL['--mut'];
        ctx.font = `400 ${narrow ? 10 : 11}px ${PAL.fontMono}`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'bottom';
        ctx.fillText(
          narrow
            ? `Rest (${fmt(tailRemCount)}): ${fmt(tailCitedN)} ≥1× · ${fmt(tailZeroN)} at 0×`
            : `Remaining ${fmt(tailRemCount)} · ${fmt(tailCitedN)} cited ≥1×, ${fmt(tailZeroN)} at 0× here`,
          mL,
          tailTop - 20
        );

        if (zeroStartPos) {
          ctx.beginPath();
          ctx.strokeStyle = PAL['--dim'];
          ctx.lineWidth = 1;
          ctx.setLineDash([2, 2]);
          ctx.moveTo(zeroStartPos.x, zeroStartPos.y - 6);
          ctx.lineTo(zeroStartPos.x, zeroStartPos.y + 6);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    } else if (stageIdx === 5) {
      const { mL, mT, innerW, innerH, baseY, axisMax, yStep, colSlotW, colCenters, busiest, busyIdx } = meta;
      ctx.font = `400 11px ${PAL.fontMono}`;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      for (let v = 0; v <= axisMax; v += yStep) {
        const y = baseY - (v / axisMax) * innerH;
        ctx.beginPath();
        ctx.strokeStyle = v === 0 ? PAL['--line'] : PAL['--hair'];
        ctx.lineWidth = 1;
        ctx.moveTo(mL, y);
        ctx.lineTo(mL + innerW, y);
        ctx.stroke();
        ctx.fillStyle = PAL['--dim'];
        ctx.fillText(String(v), mL - 8, y);
      }

      const lastIdx = months.length - 1;
      if (lastIdx >= 0 && colCenters[lastIdx] != null) {
        const lx = colCenters[lastIdx];
        const lCount = mcounts[lastIdx] || 0;
        const lH = Math.max(22, (lCount / axisMax) * innerH + 10);
        ctx.save();
        ctx.strokeStyle = PAL['--dim'];
        ctx.lineWidth = 1.2;
        ctx.setLineDash([3, 3]);
        roundRect(ctx, lx - colSlotW * 0.42, baseY - lH, colSlotW * 0.84, lH, 3);
        ctx.stroke();
        ctx.restore();
        ctx.fillStyle = PAL['--dim'];
        ctx.font = `500 10px ${PAL.fontMono}`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(`${fmt(lCount)}*`, lx, baseY - lH - 4);
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(`* ${ymShort(months[lastIdx])} partial (dashed)`, mL + 6, mT + 4);
      }

      if (busyIdx >= 0 && busyIdx < colCenters.length && busiest.month) {
        const bx = colCenters[busyIdx];
        const by = baseY - (busiest.n / axisMax) * innerH;
        ctx.fillStyle = PAL['--acc'];
        ctx.font = `600 ${narrow ? 10.5 : 11.5}px ${PAL.fontMono}`;
        ctx.textAlign = bx > Wc * 0.72 ? 'right' : 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(`Peak: ${ymShort(busiest.month)} · ${fmt(busiest.n)}`, bx > Wc * 0.72 ? bx + colSlotW * 0.4 : bx, Math.max(18, by - 10));
      }

      ctx.fillStyle = PAL['--dim'];
      ctx.font = `400 10.5px ${PAL.fontMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      months.forEach((m, i) => {
        const mo = +m.slice(5);
        const show = months.length <= 6 || (narrow ? (mo === 1 || mo === 7) : (mo === 1 || mo === 4 || mo === 7 || mo === 10));
        if (!show) return;
        const x = colCenters[i];
        ctx.beginPath();
        ctx.strokeStyle = PAL['--line'];
        ctx.moveTo(x, baseY);
        ctx.lineTo(x, baseY + 4);
        ctx.stroke();
        ctx.fillText(mo === 1 || months.length <= 6 ? `${MON[mo - 1]} ${m.slice(0, 4)}` : MON[mo - 1], x, baseY + 8);
      });
    }

    ctx.restore();
  }

  function drawTimelineCallouts(ctx, layout, Wc, alpha) {
    if (alpha <= 0.25) return;
    const narrow = Wc < 540;
    const top = mc.slice(0, narrow ? 3 : 5);
    const placed = [];
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.font = `500 ${narrow ? 10 : 11}px ${PAL.fontUi}`;
    ctx.textBaseline = 'middle';

    top.forEach(item => {
      const idx = WORKS.findIndex(w => w.id === item.id);
      if (idx < 0) return;
      const t = layout.targets[idx];
      if (!t) return;
      const left = t.x > Wc * 0.62;
      const label = `${shortTitle(item.title, narrow ? 16 : 22)} ${fmt(item.cited_here)}`;
      const tw = ctx.measureText(label).width + 6;
      const x = left ? t.x - t.r - 6 : t.x + t.r + 6;
      const y = t.y;
      const box = [left ? x - tw : x, y - 9, left ? x : x + tw, y + 9];
      if (placed.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) return;
      placed.push(box);
      ctx.textAlign = left ? 'end' : 'start';
      ctx.lineWidth = 3.5;
      ctx.strokeStyle = PAL['--surface'];
      ctx.lineJoin = 'round';
      ctx.strokeText(label, x, y);
      ctx.fillStyle = PAL['--fg'];
      ctx.fillText(label, x, y);
    });
    ctx.restore();
  }

  function dotMatchesQuery(w) {
    if (activeFilter) {
      if (activeFilter.kind === 'layer' && w._layer !== activeFilter.value) return false;
      if (activeFilter.kind === 'human' && w._human !== activeFilter.value) return false;
    }
    if (searchQuery && !w._searchBlob.includes(searchQuery)) return false;
    return true;
  }

  function drawSingleDot(ctx, x, y, r, rgb, hollow, alpha, strokeBg) {
    ctx.beginPath();
    ctx.arc(x, y, Math.max(1.2, r), 0, Math.PI * 2);
    if (hollow > 0.5) {
      ctx.strokeStyle = rgbCss(rgb, alpha);
      ctx.lineWidth = Math.max(1.2, Math.min(2, r * 0.45));
      ctx.stroke();
    } else {
      ctx.fillStyle = rgbCss(rgb, alpha);
      ctx.fill();
      if (r >= 2.2) {
        ctx.strokeStyle = strokeBg;
        ctx.lineWidth = 0.7;
        ctx.stroke();
      }
    }
  }

  function initDotsForStage(stageIdx) {
    const layout = getStageLayout(stageIdx, canvasW, canvasH);
    stageOrders[stageIdx] = layout.order;
    DOTS = WORKS.map((_, i) => {
      const t = layout.targets[i];
      const rgb = PAL_RGB[t.tok] || PAL_RGB['--acc'] || [95, 212, 232];
      return {
        i, x: t.x, y: t.y, r: t.r, rgb: rgb.slice(), hollow: t.hollow,
        sx: t.x, sy: t.y, sr: t.r, srgb: rgb.slice(), shollow: t.hollow,
        tx: t.x, ty: t.y, tr: t.r, trgb: rgb.slice(), thollow: t.hollow, delay: 0,
      };
    });
  }

  function setStage(nextIdx, immediate = false) {
    if (nextIdx < 0 || nextIdx >= TOTAL_STAGES || !STAGES_SHOWN.includes(nextIdx)) return;
    const changed = nextIdx !== activeStage;
    prevStage = activeStage;
    activeStage = nextIdx;

    main.querySelectorAll('.ov-step').forEach((el, i) => el.classList.toggle('ov-active', i === activeStage));
    byIdEl('ovStageNav').querySelectorAll('button').forEach(btn => {
      if (+btn.dataset.jump === activeStage) btn.setAttribute('aria-current', 'step');
      else btn.removeAttribute('aria-current');
    });

    byIdEl('ovStageNum').textContent = `${pad2(STAGES_SHOWN.indexOf(activeStage) + 1)} / ${pad2(STAGES_SHOWN.length)}`;
    const scaleNotes = [
      `${fmt(WORKS.length)} dots · 1 dot = 1 paper`,
      'x = month · y = layer · area ∝ cited here',
      'Unit-dot bars · linear from 0',
      PIL ? '0–100% of coded · 50% meridian' : '0–100% of papers with a value',
      'Area ∝ cited here · ranked largest first',
      'Monthly unit-dot columns · linear from 0',
    ];
    byIdEl('ovStageScale').textContent = scaleNotes[activeStage];

    if (isMultiplesMode() || !canvasW || !canvasH) return;
    const layout = getStageLayout(activeStage, canvasW, canvasH);
    stageOrders[activeStage] = layout.order;

    if (!DOTS.length || immediate) {
      initDotsForStage(activeStage);
      isMorphing = false;
      syncDotCursorPosition();
      drawMainCanvas(1);
      return;
    }
    if (!changed && !isMorphing) {
      drawMainCanvas(1);
      return;
    }

    morphStart = performance.now();
    morphDuration = 740;
    isMorphing = true;
    DOTS.forEach((d, i) => {
      const t = layout.targets[i];
      const rgb = PAL_RGB[t.tok] || PAL_RGB['--acc'] || [95, 212, 232];
      d.sx = d.x; d.sy = d.y; d.sr = d.r; d.srgb = d.rgb.slice(); d.shollow = d.hollow;
      d.tx = t.x; d.ty = t.y; d.tr = t.r; d.trgb = rgb.slice(); d.thollow = t.hollow;
      d.delay = (t.x / Math.max(1, canvasW)) * 130 + (i % 13) * 4;
    });
    if (!rafId) rafId = requestAnimationFrame(tick);
  }

  function tick(now) {
    rafId = 0;
    if (!isMorphing) {
      drawMainCanvas(1);
      return;
    }
    const elapsed = now - morphStart;
    let allDone = true;
    for (let i = 0; i < DOTS.length; i++) {
      const d = DOTS[i];
      const raw = (elapsed - d.delay) / morphDuration;
      if (raw < 1) allDone = false;
      const p = easeInOutCubic(Math.max(0, Math.min(1, raw)));
      d.x = d.sx + (d.tx - d.sx) * p;
      d.y = d.sy + (d.ty - d.sy) * p;
      d.r = d.sr + (d.tr - d.sr) * p;
      d.hollow = d.shollow + (d.thollow - d.shollow) * p;
      d.rgb[0] = d.srgb[0] + (d.trgb[0] - d.srgb[0]) * p;
      d.rgb[1] = d.srgb[1] + (d.trgb[1] - d.srgb[1]) * p;
      d.rgb[2] = d.srgb[2] + (d.trgb[2] - d.srgb[2]) * p;
    }
    const gProg = Math.max(0, Math.min(1, elapsed / (morphDuration + 150)));
    drawMainCanvas(gProg);
    syncDotCursorPosition();
    if (allDone) {
      isMorphing = false;
      drawMainCanvas(1);
      syncDotCursorPosition();
    } else {
      rafId = requestAnimationFrame(tick);
    }
  }

  function drawMainCanvas(progress = 1) {
    if (!WORKS.length) return;
    const canvas = byIdEl('ovCanvas');
    if (!canvas || !canvasW || !canvasH) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvasW, canvasH);

    const currLayout = getStageLayout(activeStage, canvasW, canvasH);
    if (isMorphing && prevStage !== activeStage && progress < 0.45) {
      drawStageOverlay(ctx, prevStage, getStageLayout(prevStage, canvasW, canvasH), canvasW, canvasH, Math.max(0, 1 - progress / 0.4));
    }
    const currAlpha = isMorphing ? Math.max(0, Math.min(1, (progress - 0.35) / 0.55)) : 1;
    drawStageOverlay(ctx, activeStage, currLayout, canvasW, canvasH, currAlpha);

    const hasFilter = Boolean(activeFilter || searchQuery);
    const activeIdx = hoveredIdx >= 0 ? hoveredIdx : (cursorHasFocus ? focusedIdx : -1);
    const hasFocus = activeIdx >= 0;

    const drawOrder = DOTS.map((_, i) => i);
    if (activeStage === 1) drawOrder.sort((a, b) => DOTS[b].r - DOTS[a].r);

    let matchCount = 0;
    for (let k = 0; k < drawOrder.length; k++) {
      const i = drawOrder[k];
      const d = DOTS[i];
      const matches = dotMatchesQuery(WORKS[i]);
      if (matches) matchCount++;
      let alpha = 0.94;
      if (hasFilter && !matches) alpha = 0.12;
      else if (hasFocus && i !== activeIdx) alpha = 0.3;
      drawSingleDot(ctx, d.x, d.y, d.r, d.rgb, d.hollow, alpha, PAL['--surface']);
    }

    const sc = byIdEl('ovSearchCount');
    if (searchQuery) {
      sc.hidden = false;
      sc.textContent = `${fmt(matchCount)} / ${fmt(WORKS.length)}`;
    } else {
      sc.hidden = true;
    }

    if (activeStage === 1) drawTimelineCallouts(ctx, currLayout, canvasW, currAlpha);

    if (activeIdx >= 0 && DOTS[activeIdx]) {
      const d = DOTS[activeIdx];
      drawSingleDot(ctx, d.x, d.y, Math.max(d.r, 4.5), d.rgb, d.hollow, 1, PAL['--bg']);
      ctx.beginPath();
      ctx.arc(d.x, d.y, Math.max(d.r, 4.5) + 4, 0, Math.PI * 2);
      ctx.strokeStyle = PAL['--acc'];
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawCurrentView() {
    if (!WORKS.length) return;
    if (isMultiplesMode()) renderAllSmallMultiples();
    else drawMainCanvas(1);
  }

  function resizeMainCanvas() {
    const frame = byIdEl('ovStageFrame');
    const canvas = byIdEl('ovCanvas');
    if (!frame || !canvas) return;
    const rect = frame.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvasW = Math.round(rect.width);
    canvasH = Math.round(rect.height);
    canvas.width = Math.round(canvasW * dpr);
    canvas.height = Math.round(canvasH * dpr);
    layoutCache.clear();
    setStage(activeStage, true);
  }

  function hitTestDot(px, py, dotsArr) {
    let best = -1, bestDist = Infinity;
    for (let i = 0; i < dotsArr.length; i++) {
      const d = dotsArr[i];
      const hitR = Math.max(d.r + 6, 12);
      const dist = Math.hypot(px - d.x, py - d.y);
      if (dist <= hitR && dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    }
    return best;
  }

  function setHoveredDot(idx) {
    if (hoveredIdx === idx) return;
    hoveredIdx = idx;
    const frame = byIdEl('ovStageFrame');
    if (frame) frame.style.cursor = idx >= 0 ? 'pointer' : 'default';
    updateInspectorAndTip();
    drawMainCanvas(1);
  }

  function syncDotCursorPosition() {
    const cursor = byIdEl('ovCursor');
    if (!cursor || !DOTS.length) return;
    const idx = focusedIdx >= 0 ? focusedIdx : (stageOrders[activeStage]?.[0] ?? 0);
    const d = DOTS[idx], w = WORKS[idx];
    if (!d || !w) return;
    cursor.style.left = `${d.x}px`;
    cursor.style.top = `${d.y}px`;
    cursor.setAttribute('aria-label', `${w.title}. ${ymLabel(w._ym)}, ${layerInfo(w._layer)[1]}, ${humanInfo(w._human)[1]}, cited here ${w._cited} times. Use arrow keys to move, Enter to open details.`);
  }

  function updateInspectorAndTip() {
    const idx = hoveredIdx >= 0 ? hoveredIdx : (cursorHasFocus ? focusedIdx : -1);
    const tip = byIdEl('ovTip');
    const idle = byIdEl('ovInspIdle');
    const act = byIdEl('ovInspAct');
    if (idx < 0 || !WORKS[idx] || !DOTS[idx]) {
      tip.hidden = true;
      idle.hidden = false;
      act.hidden = true;
      return;
    }

    const w = WORKS[idx], d = DOTS[idx];
    const lInfo = layerInfo(w._layer);
    const hInfo = humanInfo(w._human);
    const tok = activeStage === 3 ? hInfo[2] : lInfo[2];

    tip.hidden = false;
    tip.innerHTML = `<div class="ov-tip-ti">${esc(w.title)}</div>
      <div class="ov-tip-meta"><span>${esc(ymLabel(w._ym))}</span><span>${esc(lInfo[1])}</span><span>${esc(hInfo[1])}</span><span class="mono">cited here ${fmt(w._cited)}×</span></div>
      <div class="ov-tip-cta">Click or press Enter to open →</div>`;
    const tw = tip.offsetWidth || 250, th = tip.offsetHeight || 80;
    let left = d.x + d.r + 12;
    if (left + tw > canvasW - 10) left = d.x - d.r - tw - 12;
    if (left < 10) left = 10;
    let top = d.y - th / 2;
    if (top < 10) top = 10;
    if (top + th > canvasH - 10) top = Math.max(10, canvasH - th - 10);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;

    idle.hidden = true;
    act.hidden = false;
    act.innerHTML = `<div class="ov-insp-paper">
        <span class="dot" style="background:var(${tok})"></span>
        <span class="ov-insp-ti" title="${esc(w.title)}">${esc(w.title)}</span>
        <span class="ov-insp-sub mono">${esc(ymShort(w._ym))} · ${esc(lInfo[1])} · ${fmt(w._cited)}×</span>
      </div>
      <button type="button" class="btn ov-insp-open">Open ↵</button>`;
    act.querySelector('button').addEventListener('click', () => H.openDrawer(w.id));
  }

  /* ---------- Stage interactions & keyboard navigation ---------- */
  (function wireStage() {
    const frame = byIdEl('ovStageFrame');
    const cursor = byIdEl('ovCursor');

    frame.addEventListener('mousemove', e => {
      const rect = frame.getBoundingClientRect();
      setHoveredDot(hitTestDot(e.clientX - rect.left, e.clientY - rect.top, DOTS));
    });
    frame.addEventListener('mouseleave', () => setHoveredDot(-1));
    frame.addEventListener('click', e => {
      if (e.target.closest('button')) return;
      const rect = frame.getBoundingClientRect();
      const hit = hitTestDot(e.clientX - rect.left, e.clientY - rect.top, DOTS);
      if (hit >= 0) {
        focusedIdx = hit;
        syncDotCursorPosition();
        H.openDrawer(WORKS[hit].id);
      }
    });

    cursor.addEventListener('focus', () => {
      cursorHasFocus = true;
      if (focusedIdx < 0) focusedIdx = stageOrders[activeStage]?.[0] ?? 0;
      syncDotCursorPosition();
      updateInspectorAndTip();
      drawMainCanvas(1);
    });
    cursor.addEventListener('blur', () => {
      cursorHasFocus = false;
      updateInspectorAndTip();
      drawMainCanvas(1);
    });
    cursor.addEventListener('keydown', e => {
      const ord = stageOrders[activeStage] && stageOrders[activeStage].length ? stageOrders[activeStage] : WORKS.map((_, i) => i);
      const pos = Math.max(0, ord.indexOf(focusedIdx));
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        focusedIdx = ord[(pos + (e.shiftKey ? 10 : 1)) % ord.length];
        syncDotCursorPosition(); updateInspectorAndTip(); drawMainCanvas(1);
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        focusedIdx = ord[(pos - (e.shiftKey ? 10 : 1) + ord.length) % ord.length];
        syncDotCursorPosition(); updateInspectorAndTip(); drawMainCanvas(1);
      } else if (e.key === 'Home') {
        e.preventDefault();
        focusedIdx = ord[0];
        syncDotCursorPosition(); updateInspectorAndTip(); drawMainCanvas(1);
      } else if (e.key === 'End') {
        e.preventDefault();
        focusedIdx = ord[ord.length - 1];
        syncDotCursorPosition(); updateInspectorAndTip(); drawMainCanvas(1);
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (focusedIdx >= 0 && WORKS[focusedIdx]) H.openDrawer(WORKS[focusedIdx].id);
      }
    });

    const searchInput = byIdEl('ovSearch');
    searchInput.addEventListener('input', () => {
      searchQuery = searchInput.value.trim().toLowerCase();
      drawCurrentView();
    });
    searchInput.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        searchInput.value = '';
        searchQuery = '';
        drawCurrentView();
      } else if (e.key === 'Enter' && searchQuery) {
        const match = WORKS.findIndex(w => dotMatchesQuery(w));
        if (match >= 0) {
          focusedIdx = match;
          syncDotCursorPosition();
          cursor.focus();
        }
      }
    });

    byIdEl('ovStageNav').querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = +btn.dataset.jump;
        const step = byIdEl(`ovStep-${idx}`);
        if (step) step.scrollIntoView({ behavior: reduceMotionMQ.matches ? 'auto' : 'smooth', block: 'center' });
        setStage(idx);
      });
    });
  })();

  /* ---------- Scroll observer ---------- */
  (function setupScroll() {
    const steps = [...main.querySelectorAll('.ov-step')].filter(el => el.style.display !== 'none');
    if (!steps.length) return;
    const getFocusY = () => {
      if (window.innerWidth <= 1060) {
        const st = byIdEl('ovStageSticky');
        const bottom = st ? st.getBoundingClientRect().bottom : window.innerHeight * 0.45;
        return bottom + Math.max(70, (window.innerHeight - bottom) * 0.4);
      }
      return window.innerHeight * 0.46;
    };
    const pickActive = () => {
      const midY = getFocusY();
      let bestIdx = activeStage, bestDist = Infinity;
      steps.forEach(step => {
        const r = step.getBoundingClientRect();
        const dist = Math.abs((r.top + r.bottom) / 2 - midY);
        if (dist < bestDist) { bestDist = dist; bestIdx = +step.dataset.stage; }
      });
      if (bestIdx !== activeStage) setStage(bestIdx);
    };
    if (window.IntersectionObserver) {
      const obs = new IntersectionObserver(() => { if (!isMultiplesMode()) pickActive(); }, { threshold: [0.15, 0.45, 0.75] });
      steps.forEach(s => obs.observe(s));
    }
    let ticking = false;
    window.addEventListener('scroll', () => {
      if (isMultiplesMode() || ticking) return;
      ticking = true;
      requestAnimationFrame(() => { ticking = false; pickActive(); });
    }, { passive: true });
  })();

  /* ---------- Reduced motion: static small multiples ---------- */
  function buildSmallMultiples() {
    const grid = byIdEl('ovMultGrid');
    const specs = [
      { idx: 0, title: byIdEl('ovS0Title').textContent, cap: byIdEl('ovS0Cap').textContent, n: byIdEl('ovS0N').textContent, href: 'corpus.html', linkText: 'Browse papers →' },
      { idx: 1, title: 'Papers over time', cap: byIdEl('ovS1Cap').textContent, n: byIdEl('ovS1N').textContent, href: 'explore.html', linkText: 'Explore papers →' },
      { idx: 2, title: 'What the corpus is made of', cap: byIdEl('ovS2Cap').textContent, n: byIdEl('ovS2N').textContent, href: 'corpus.html', linkText: 'Open corpus →' },
      { idx: 3, title: PIL ? 'Where the human sits' : FACET_LABEL, cap: byIdEl('ovS3Cap').textContent, n: byIdEl('ovS3N').textContent, href: 'lenses.html', linkText: 'Open lenses →' },
      { idx: 4, title: 'Most cited here', cap: byIdEl('ovS4Cap').textContent, n: byIdEl('ovS4N').textContent, href: 'graph.html', linkText: 'Citation graph →' },
      { idx: 5, title: 'Growth per month', cap: byIdEl('ovS5Cap').textContent, n: byIdEl('ovS5N').textContent, href: 'living.html', linkText: 'Living log →' },
    ];

    grid.innerHTML = specs.filter(s => STAGES_SHOWN.includes(s.idx)).map(s => `
      <article class="ov-mult-card" data-stage="${s.idx}">
        <div class="ov-mult-head">
          <div>
            <div class="ov-step-kicker mono">${pad2(STAGES_SHOWN.indexOf(s.idx) + 1)} / ${pad2(STAGES_SHOWN.length)}</div>
            <h3 class="h3">${esc(s.title)}</h3>
          </div>
          <a class="ov-link" href="${esc(s.href)}">${esc(s.linkText)}</a>
        </div>
        <div class="ov-mult-cv" data-mult-wrap="${s.idx}">
          <canvas data-mult-canvas="${s.idx}" aria-label="${esc(s.title)} — ${fmt(WORKS.length)} included"></canvas>
          <button type="button" class="ov-cursor" data-mult-cursor="${s.idx}" aria-label="Inspect ${esc(s.title)}. Arrow keys move, Enter opens."></button>
        </div>
        <div class="ov-mult-insp" data-mult-insp="${s.idx}">
          <span>Hover or focus a dot · Enter opens details</span>
          <span class="mono">${esc(s.n)}</span>
        </div>
        <p class="meta" style="margin:0">${esc(s.cap)}</p>
      </article>
    `).join('');

    smallMultipleCanvases = specs.filter(s => STAGES_SHOWN.includes(s.idx)).map(s => {
      const wrap = grid.querySelector(`[data-mult-wrap="${s.idx}"]`);
      const canvas = grid.querySelector(`[data-mult-canvas="${s.idx}"]`);
      const cursor = grid.querySelector(`[data-mult-cursor="${s.idx}"]`);
      const insp = grid.querySelector(`[data-mult-insp="${s.idx}"]`);
      const item = { stageIdx: s.idx, wrap, canvas, cursor, insp, hoverIdx: -1, focusIdx: 0, hasFocus: false, w: 0, h: 0, layout: null };

      wrap.addEventListener('mousemove', e => {
        if (!item.layout) return;
        const rect = wrap.getBoundingClientRect();
        const hit = hitTestDot(e.clientX - rect.left, e.clientY - rect.top, item.layout.targets);
        if (hit !== item.hoverIdx) {
          item.hoverIdx = hit;
          wrap.style.cursor = hit >= 0 ? 'pointer' : 'default';
          drawSmallMultiple(item);
        }
      });
      wrap.addEventListener('mouseleave', () => {
        item.hoverIdx = -1;
        wrap.style.cursor = 'default';
        drawSmallMultiple(item);
      });
      wrap.addEventListener('click', e => {
        if (!item.layout || e.target.closest('button')) return;
        const rect = wrap.getBoundingClientRect();
        const hit = hitTestDot(e.clientX - rect.left, e.clientY - rect.top, item.layout.targets);
        if (hit >= 0) H.openDrawer(WORKS[hit].id);
      });
      cursor.addEventListener('focus', () => { item.hasFocus = true; drawSmallMultiple(item); });
      cursor.addEventListener('blur', () => { item.hasFocus = false; drawSmallMultiple(item); });
      cursor.addEventListener('keydown', e => {
        if (!item.layout) return;
        const ord = item.layout.order.length ? item.layout.order : WORKS.map((_, i) => i);
        const pos = Math.max(0, ord.indexOf(item.focusIdx));
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
          e.preventDefault(); item.focusIdx = ord[(pos + 1) % ord.length]; drawSmallMultiple(item);
        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault(); item.focusIdx = ord[(pos - 1 + ord.length) % ord.length]; drawSmallMultiple(item);
        } else if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault(); if (WORKS[item.focusIdx]) H.openDrawer(WORKS[item.focusIdx].id);
        }
      });
      return item;
    });
    renderAllSmallMultiples();
  }

  function drawSmallMultiple(item) {
    const rect = item.wrap.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    const localDpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.round(rect.width), h = Math.round(rect.height);
    if (item.w !== w || item.h !== h) {
      item.w = w; item.h = h;
      item.canvas.width = Math.round(w * localDpr);
      item.canvas.height = Math.round(h * localDpr);
    }
    const layout = getStageLayout(item.stageIdx, w, h);
    item.layout = layout;
    const ctx = item.canvas.getContext('2d');
    if (!ctx) return;
    ctx.save();
    ctx.setTransform(localDpr, 0, 0, localDpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    drawStageOverlay(ctx, item.stageIdx, layout, w, h, 1);
    const activeIdx = item.hoverIdx >= 0 ? item.hoverIdx : (item.hasFocus ? item.focusIdx : -1);
    layout.targets.forEach((t, i) => {
      const rgb = PAL_RGB[t.tok] || PAL_RGB['--acc'] || [95, 212, 232];
      const alpha = activeIdx >= 0 && activeIdx !== i ? 0.25 : 0.94;
      drawSingleDot(ctx, t.x, t.y, t.r, rgb, t.hollow, alpha, PAL['--bg']);
    });
    if (item.stageIdx === 1) drawTimelineCallouts(ctx, layout, w, 1);

    if (activeIdx >= 0 && layout.targets[activeIdx]) {
      const t = layout.targets[activeIdx];
      const rgb = PAL_RGB[t.tok] || PAL_RGB['--acc'] || [95, 212, 232];
      drawSingleDot(ctx, t.x, t.y, Math.max(t.r, 4.2), rgb, t.hollow, 1, PAL['--bg']);
      ctx.beginPath();
      ctx.arc(t.x, t.y, Math.max(t.r, 4.2) + 3.5, 0, Math.PI * 2);
      ctx.strokeStyle = PAL['--acc'];
      ctx.lineWidth = 2;
      ctx.stroke();
      const paper = WORKS[activeIdx];
      item.insp.innerHTML = `<span style="color:var(--fg);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(paper.title)}</span><span class="mono">${fmt(paper._cited)}×</span>`;
    } else {
      item.insp.innerHTML = `<span>Hover or focus a dot · Enter opens details</span><span class="mono">${fmt(WORKS.length)}</span>`;
    }

    const fTarget = layout.targets[item.focusIdx] || layout.targets[0];
    if (fTarget) {
      item.cursor.style.left = `${fTarget.x}px`;
      item.cursor.style.top = `${fTarget.y}px`;
      const fp = WORKS[item.focusIdx];
      if (fp) item.cursor.setAttribute('aria-label', `${fp.title}, cited here ${fp._cited} times. Arrow keys move, Enter opens.`);
    }
    ctx.restore();
  }

  function renderAllSmallMultiples() {
    smallMultipleCanvases.forEach(drawSmallMultiple);
  }

  function applyPresentationMode() {
    const mult = isMultiplesMode();
    byIdEl('ovStoryScroll').hidden = mult;
    byIdEl('ovMultiples').hidden = !mult;
    const toggle = byIdEl('ovModeToggle');
    if (toggle) toggle.setAttribute('aria-pressed', String(mult));
    if (mult) {
      if (!smallMultipleCanvases.length) buildSmallMultiples();
      else renderAllSmallMultiples();
    } else {
      resizeMainCanvas();
    }
  }

  byIdEl('ovModeToggle').addEventListener('click', () => {
    manualMultiples = !manualMultiples;
    applyPresentationMode();
  });
  byIdEl('ovModeBack').addEventListener('click', () => {
    manualMultiples = false;
    applyPresentationMode();
  });
  if (reduceMotionMQ.addEventListener) {
    reduceMotionMQ.addEventListener('change', applyPresentationMode);
  }

  /* ---------- Topbar height sync, theme hook, resize ---------- */
  function syncTopbarHeight() {
    const tb = document.querySelector('.topbar');
    const h = tb ? tb.offsetHeight : 62;
    document.documentElement.style.setProperty('--ov-top-h', `${h}px`);
  }
  const topbarEl = document.querySelector('.topbar');
  if (topbarEl && window.ResizeObserver) {
    new ResizeObserver(syncTopbarHeight).observe(topbarEl);
  }

  document.addEventListener('hub:theme', () => {
    readPalette();
    if (!WORKS.length) return;
    if (DOTS.length && canvasW && canvasH) {
      const layout = getStageLayout(activeStage, canvasW, canvasH);
      DOTS.forEach((d, i) => {
        const t = layout.targets[i];
        const rgb = PAL_RGB[t.tok] || PAL_RGB['--acc'] || [95, 212, 232];
        d.rgb = rgb.slice();
        d.trgb = rgb.slice();
        d.srgb = rgb.slice();
      });
    }
    drawCurrentView();
  });

  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      syncTopbarHeight();
      layoutCache.clear();
      if (!WORKS.length) return;
      if (isMultiplesMode()) renderAllSmallMultiples();
      else resizeMainCanvas();
    }, 140);
  });

  /* ---------- Scope: the story, the counts and the empty state ---------- */
  function emptyScopeHTML() {
    const f = SCOPE.format(SCOPE.current()).replace(/&/g, ', ');
    return `<p class="ov-empty scope-empty-state card">No paper falls in this scope${f ? ' (' + esc(f) + ')' : ''}. <button type="button" class="btn" data-scope-reset>Reset the scope</button></p>`;
  }
  function paintStory() {
    const empty = !WORKS.length;
    const box = byIdEl('ovScopeEmpty');
    box.hidden = !empty;
    box.innerHTML = empty ? emptyScopeHTML() : '';
    if (empty) { byIdEl('ovStoryScroll').hidden = true; byIdEl('ovMultiples').hidden = true; return; }
    applyPresentationMode();
  }
  function carryScope() {
    main.querySelectorAll('a[href]').forEach(a => { a.setAttribute('href', SCOPE.carry(a.getAttribute('href'), SCOPE.current())); });
  }
  /* Everything the scope changes, in one pass: the n of N line, the dots and their layouts, the layer and facet
     counts, the most-cited list and the growth columns. */
  function paintScoped() {
    applyScope();
    SCOPE.renderLine(byIdEl('ovScope'), SRES, {});
    layoutCache.clear();
    for (let i = 0; i < stageOrders.length; i++) stageOrders[i] = [];
    DOTS = []; hoveredIdx = -1; focusedIdx = -1; isMorphing = false; activeFilter = null;
    smallMultipleCanvases = [];
    byIdEl('ovBrowseN').textContent = fmt(scopeOn() ? WORKS.length : nIncAll);
    renderNarrative();
    byIdEl('ovSearchCount').hidden = true;
    paintStory();
    carryScope();
  }
  document.addEventListener('click', e => { if (e.target.closest('[data-scope-reset]')) SCOPE.reset(); });
  SCOPE.onChange(() => paintScoped());

  readPalette();
  syncTopbarHeight();
  SCOPE.renderLine(byIdEl('ovScope'), SRES, {});
  byIdEl('ovBrowseN').textContent = fmt(scopeOn() ? WORKS.length : nIncAll);
  paintStory();
  carryScope();
}).catch(e => {
  document.body.textContent = 'Overview failed to load: ' + e.message;
});
