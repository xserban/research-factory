/* Miners page: a gallery of miner cards and a detail view per miner (#m=<name>).
   Payloads: shell, mining (services/hub_mining.mining_payload_from). Every figure is read from the payload. */
HUB.load(['shell', 'mining']).then(d => {
  const H = HUB.init(d.shell);
  const { esc, fmt } = H;
  const MP = d.mining, MX = MP.methods || {};
  const M = (MP.miners && MP.miners.miners) || [];
  const PAIRS = (MP.miners && MP.miners.by_model_pair) || [];
  const NINC = ((MP.miners && MP.miners.corpus) || {}).included || 0;
  const CB = MP.codebook || {};
  const main = H.mount({ page: 'miners', crumb: 'Miners' });
  main.classList.add('mp');

  if (!document.getElementById('mp-style')) {
    const st = document.createElement('style'); st.id = 'mp-style';
    st.textContent = `
.mp{padding-top:16px}
.mp .lead{max-width:46ch;margin:10px 0 22px}
.mp .grp{margin:30px 0 0}
.mp .gh{display:flex;align-items:baseline;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.mp .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.mc{display:flex;flex-direction:column;gap:10px;background:var(--surface);border-radius:var(--r);padding:16px;color:var(--fg);position:relative;min-width:0}
.mc:hover{background:var(--raised)}
.mc .nm{font:600 var(--t-m)/1.25 var(--f-ui);display:flex;align-items:center;gap:2px;margin:0}
.mc .why{font-size:var(--t-s);color:var(--mut);line-height:1.4;min-height:2.8em;margin:0}
.mc .cov{display:flex;align-items:center;gap:12px}
.mc .t1{font:600 var(--t-m)/1.1 var(--f-mono)}
.mc .t2{font-size:var(--t-xs);color:var(--mut)}
.mc .row{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:22px;font-size:var(--t-xs)}
.mc .ib{position:relative;z-index:2}
.mc a.cover{position:absolute;inset:0;border-radius:var(--r);z-index:1}
.mc a.cover:focus-visible{outline:2px solid var(--acc)}
.chk{display:inline-flex;align-items:center;gap:6px;font-size:var(--t-xs);color:var(--fg)}
.chk.no{color:var(--dim)}
.chk i{width:8px;height:8px;border-radius:50%;background:var(--seq-4);display:inline-block}
.chk.no i{background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}
.strip{display:flex;gap:3px;align-items:flex-end}
.strip i{display:block;width:9px;height:16px;border-radius:2px;background:var(--line);position:relative;overflow:hidden}
.strip i b{position:absolute;left:0;right:0;bottom:0;background:var(--seq-4)}
.strip.none{font-size:var(--t-xs);color:var(--dim)}
.sub-tag{font-size:var(--t-xs);color:var(--mut)}
.pairs{display:grid;gap:10px;max-width:760px}
.pair{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr) 230px;gap:6px 14px;align-items:center}
.pair .nn{font:400 var(--t-xs) var(--f-mono);color:var(--mut);text-align:right}
.ptr{height:8px;background:var(--hair);border-radius:2px;overflow:hidden}.ptr i{display:block;height:100%;background:var(--seq-3)}
.foot{margin-top:36px;color:var(--dim);font-size:var(--t-xs);display:flex;gap:4px;align-items:center}
.crumbs{font-size:var(--t-s);margin-bottom:10px}
.dsec{margin-top:34px}
.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:0 0 6px}
.anat{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin-top:6px}
.an{background:var(--surface);border-radius:var(--r);padding:16px;position:relative;min-width:0}
.an+.an{margin-left:28px}
.an+.an::before{content:"";position:absolute;left:-28px;top:34px;width:28px;height:2px;background:var(--line)}
.an .st{font-size:var(--t-xs);color:var(--dim);letter-spacing:.04em}
.an h3{margin:2px 0 8px}
.an .quote{font-size:13px;margin:4px 0}
.an p{margin:6px 0 0;font-size:var(--t-s);color:var(--mut);line-height:1.45}
.an p b{color:var(--fg);font-weight:600}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.tag{font-size:var(--t-xs);padding:3px 8px;border-radius:999px;background:var(--raised);color:var(--mut)}
.tchip{font:500 11px/1 var(--f-ui);padding:3px 7px;border-radius:4px;background:var(--raised);color:var(--mut)}
.fgroup{margin-top:20px}
.fgroup>.gname{font:500 var(--t-s) var(--f-ui);color:var(--mut);margin-bottom:8px;display:flex;gap:8px;align-items:baseline}
.fgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:16px}
.fc{background:var(--surface);border-radius:var(--r);padding:14px 16px;min-width:0}
.fc .fh{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.fc .fh b{font-weight:600;font-size:var(--t-s)}
.fc .rq{font-size:var(--t-xs);color:var(--dim)}
.bars{display:flex;flex-direction:column;gap:3px}
.bar{display:grid;grid-template-columns:minmax(0,150px) 1fr 44px;gap:8px;align-items:center;padding:2px 4px;font-size:var(--t-xs)}
.bar .l{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--fg)}
.bar .tr{height:8px;background:var(--hair);border-radius:2px;overflow:hidden}
.bar .tr i{display:block;height:100%;background:var(--seq-3)}
.bar .n{font-family:var(--f-mono);color:var(--mut);text-align:right}
.bar[data-vals]{cursor:pointer;border-radius:4px}.bar[data-vals]:hover{background:var(--raised)}.bar[data-vals]:focus-visible{outline:2px solid var(--acc)}
.vl{display:grid;gap:2px;max-height:220px;overflow:auto}.vl .ttl{all:unset;cursor:pointer;font-size:var(--t-xs);padding:3px 4px;border-radius:4px}.vl .ttl:hover{background:var(--raised)}
.more{all:unset;cursor:pointer;font-size:var(--t-xs);color:var(--acc);padding:3px 4px;text-decoration:underline;text-underline-offset:3px}
.more:focus-visible{outline:2px solid var(--acc)}
.agr{display:grid;grid-template-columns:minmax(120px,190px) minmax(0,1fr) 100px;gap:4px 14px;align-items:center}
.agr .fl{font-size:var(--t-s)}
.agr .ml{font-size:var(--t-xs);color:var(--mut);text-align:right}
.agr .nn{font:400 var(--t-xs) var(--f-mono);color:var(--mut);text-align:right;white-space:nowrap}
.agr .gap{grid-column:1/-1;height:8px}
.trk{position:relative;height:18px}.trk i{position:absolute;display:block}
.trk .base{left:0;right:0;top:7px;height:4px;background:var(--hair)}
.trk .fill{left:0;top:7px;height:4px;opacity:.55}
.trk .wh{top:8px;height:2px;background:var(--mut)}
.trk .dt{top:3px;width:12px;height:12px;border-radius:50%;margin-left:-6px}
.trk .thr{top:0;height:18px;width:0;border-left:1.5px dashed var(--fg)}
.trk.alt{height:14px}.trk.alt .dt{top:2px;width:10px;height:10px;margin-left:-5px;opacity:.7}
.trk.alt .base,.trk.alt .fill{top:5px}.trk.alt .wh{top:6px}.trk.alt .thr{height:14px}
.axl{display:flex;justify-content:space-between;font-size:10px;color:var(--dim);font-family:var(--f-mono)}
.legend2{display:flex;gap:16px;flex-wrap:wrap;font-size:var(--t-xs);color:var(--mut);margin-top:10px}
.legend2 span{display:inline-flex;gap:6px;align-items:center}
.legend2 .sw{width:0;height:10px;border-left:1.5px dashed var(--fg)}
.sums{display:flex;gap:28px;flex-wrap:wrap;margin:0 0 16px}
.sums .big{font:600 var(--t-l,22px)/1.1 var(--f-mono)}
.sums .lb{font-size:var(--t-xs);color:var(--mut);display:flex;align-items:center;gap:2px}
.sums .def{outline:0}
.ex{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}
.exc{background:var(--surface);border-radius:var(--r);padding:16px;min-width:0}
.exc .ttl{all:unset;display:block;font:600 var(--t-s)/1.35 var(--f-ui);cursor:pointer;margin-bottom:8px}
.exc .ttl:hover{color:var(--acc);text-decoration:underline}
.exc .ttl:focus-visible{outline:2px solid var(--acc)}
.exc .ef{margin-top:10px}
.exc .ef .k{font-size:var(--t-xs);color:var(--mut);display:flex;gap:8px;align-items:center}
.exc .ef .v{font-weight:600;font-size:var(--t-s);margin-top:2px}
.exc .quote{font-size:14px;margin:4px 0 0}
.empty{color:var(--mut);font-size:var(--t-s);padding:10px 0}
@media (max-width:1100px){.anat{grid-template-columns:minmax(0,1fr);gap:26px}.an+.an{margin-left:0}.an+.an::before{display:none}}
@media (max-width:760px){.axl span:nth-child(2),.axl span:nth-child(4){display:none}.mp .lead{font-size:22px}.agr{grid-template-columns:minmax(0,1fr) 90px}.agr .fl{grid-column:1/-1}.ex,.fgrid{grid-template-columns:minmax(0,1fr)}.bar{grid-template-columns:minmax(0,100px) 1fr 48px}.pair{grid-template-columns:minmax(0,1fr)}.pair .nn{text-align:left}}`;
    document.head.appendChild(st);
  }

  /* ---------- labels: generated from the registered specs (payload `labels`) ---------- */
  const LB = MP.labels || {}, LBM = LB.miners || {}, LBF = LB.fields || {}, LBV = LB.values || {};
  const GROUPS = ['Describe the paper', 'Trace the process', 'Technique per stage', 'Claims', 'Other miners'];
  const meta = m => { const x = LBM[m.name] || {}; return [x.title || m.name, x.group || 'Other miners', x.blurb || '']; };
  const hname = m => meta(m)[0];
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const flab = f => LBF[f] || cap(f.replace(/_/g, ' '));
  function lab(v) {
    if (v == null) return 'Not recorded';
    v = String(v); if (LBV[v]) return LBV[v];
    if (H.HUMAN.some(h => h[0] === v)) return H.humanLabel(v);
    const k = v.replace(/^[a-z]+\//, '');
    if (CB[k] && CB[k].label) return CB[k].label.replace(/^(.{70}).+$/, '$1…');
    if (/^[a-z]{1,3}-\d+$/.test(k)) return k.toUpperCase();
    return LBV[k] || H.pretty(k);
  }
  function model(list) {
    if (!list || !list.length) return null;
    return list.map(x => { const m = String(x).match(/claude-(\w+)-(\d+)-(\d+)/); return m ? cap(m[1]) + ' ' + m[2] + '.' + m[3] : x; }).join(' + ');
  }
  const pl = (n, one, many) => fmt(n) + ' ' + (n === 1 ? one : many);
  const pc = x => Math.round(100 * x);
  const checked = m => m.pass_b.works > 0;
  const subset = m => NINC > 0 && m.pass_a.works < 0.5 * NINC;

  /* The measure shown by default: the fairer (semantic) one where it has figures, else the exact one. */
  const hasM = (m, k) => { const a = m.agreement && m.agreement[k]; return !!(a && a.by_field && Object.values(a.by_field).some(v => v.total > 0)); };
  const defMeasure = m => hasM(m, 'fairer') ? 'fairer' : (hasM(m, 'exact') ? 'exact' : null);
  const MNAME = { fairer: 'Fairer match', exact: 'Exact match', platform: 'Platform rate' };
  const MDEF = k => HUB.info('<b>' + esc(MNAME[k]) + '</b><p>' + esc(MX[k] || '') + '</p>', 'About ' + MNAME[k]);
  function wilson(a, n) { const z = 1.96, p = a / n, dd = 1 + z * z / n, c = p + z * z / (2 * n), r = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return [Math.max(0, (c - r) / dd), Math.min(1, (c + r) / dd)]; }
  function fieldRates(m, k) {
    const a = m.agreement && m.agreement[k]; if (!a || !a.by_field) return [];
    return Object.entries(a.by_field).filter(([, v]) => v.total > 0).map(([f, v]) => ({ f, a: v.agreed, c: v.total, s: v.rate, d: v.disagreements, o: v.one_sided }));
  }
  const infoPop = (title, body) => HUB.info('<b>' + esc(title) + '</b>' + body, 'About ' + title);

  function ring(frac) {
    const r = 15, C = 2 * Math.PI * r;
    return `<svg width=40 height=40 viewBox="0 0 40 40" role=img aria-label="${pc(frac)}% covered"><circle cx=20 cy=20 r=${r} fill=none stroke="var(--line)" stroke-width=5 /><circle cx=20 cy=20 r=${r} fill=none stroke="var(--seq-4)" stroke-width=5 stroke-dasharray="${(C * Math.min(1, frac)).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 20 20)"/></svg>`;
  }
  function strip(m) {
    const k = defMeasure(m); if (!k) return `<span class="strip none">${checked(m) ? 'Free text, not compared' : 'No agreement yet'}</span>`;
    const r = fieldRates(m, k);
    return `<span class=strip role=img aria-label="Agreement per compared field">${r.map(x => `<i><b style="height:${pc(x.s)}%"></b></i>`).join('')}</span>`;
  }

  /* ---------- gallery ---------- */
  function card(m) {
    const [nm, , why] = meta(m), A = m.pass_a.works, frac = NINC ? A / NINC : 0, k = defMeasure(m);
    const ov = k && m.agreement[k].overall && m.agreement[k].overall.total ? m.agreement[k].overall : null;
    const info = infoPop(nm, `<p>${esc(why)}</p><p><span class=k>Coverage.</span> ${esc(HUB.fmt(A))} of ${esc(fmt(NINC))} included papers read in the first reading.${subset(m) ? ' This miner ran on a subset of the papers.' : ''}</p><p><span class=k>Miner name.</span> <span class=mono>${esc(m.name)}</span>, version ${esc(m.version)}.</p>`);
    const sInfo = k ? infoPop(MNAME[k] + ', field by field', `<p>One tick per compared field; the taller the fill, the more often the two readings recorded the same value.</p><p><span class=k>How it's computed.</span> ${esc(MX[k] || '')}</p>`) : infoPop('Agreement', '<p>This miner records quotations or free text, which cannot be compared value by value, or has no second reading yet.</p>');
    return `<article class=mc>
      <a class=cover href="#m=${esc(m.name)}" aria-label="Open ${esc(nm)}"></a>
      <h3 class=nm>${esc(nm)}<span class=ib>${info}</span></h3>
      <p class=why>${esc(why)}</p>
      <div class=cov>${ring(frac)}<div><div class=t1>${fmt(A)}<span class=meta> / ${fmt(NINC)}</span></div><div class=t2>papers read${subset(m) ? ' · a subset' : ''}</div></div></div>
      <div class=row>${checked(m) ? `<span class=chk><i></i>Checked on ${fmt(m.pass_b.works)} · ${esc(model(m.pass_b.models) || '')}</span>` : `<span class="chk no"><i></i>Not checked yet</span>`}</div>
      <div class=row>${strip(m)}<span class="sub-tag">${ov ? pc(ov.rate) + '% ' + (k === 'fairer' ? 'fairer' : 'exact') : ''}</span><span class=ib>${sInfo}</span></div>
    </article>`;
  }
  function pairsSection(pairs) {
    if (!pairs.length) return `<div class=empty>Model pairs appear here once checked papers are recorded.</div>`;
    return `<div class=pairs>${pairs.map(p => `<div class=pair><div>${esc(model([p.a]))} <span class=meta>read first</span><br>${esc(model([p.b]))} <span class=meta>checked</span></div><div class=ptr role=img aria-label="${pc(p.rate)}% agreement"><i style="width:${pc(p.rate)}%"></i></div><div class=nn>${pc(p.rate)}% · ${fmt(p.agreed)} of ${fmt(p.total)}<br>${fmt(p.works_both)} papers · ${pl(p.miners.length, 'miner', 'miners')}</div></div>`).join('')}</div>`;
  }
  function overview() {
    const cov = (MP.coverage && MP.coverage.miners) || [], union = new Set();
    cov.forEach(c => (c.a || []).forEach(i => union.add(i)));
    const nChk = M.filter(checked).length;
    const lead = `${fmt(M.length)} miners have read ${fmt(union.size)} papers. ${fmt(nChk)} have a second reading to check them.`;
    main.innerHTML = H.header({
      level: 1, title: 'Miners',
      infoHtml: `<b>What it shows</b>The ${HUB.term('miner', 'miners')} in the review: what each reads and records, how many papers it has covered, and whether a second reading agrees.<p><span class=k>How to read it.</span> The ring is the share of included papers the first reading covered. The ticks give agreement per compared field; the percentage beside them is the overall rate under the fairer match where it exists, else the exact match.</p><p><span class=k>How it's computed.</span> ${esc(MX.miners || '')}</p>`
    }) + `<p class=lead>${esc(lead)}</p>`
      + GROUPS.map(g => {
        const ms = M.filter(m => meta(m)[1] === g); if (!ms.length) return '';
        const keys = Object.keys(LBM);
        ms.sort((a, b) => keys.indexOf(a.name) - keys.indexOf(b.name));
        return `<section class=grp><div class=gh>${H.header({ title: g })}<span class=meta>${fmt(ms.length)} ${ms.length > 1 ? 'miners' : 'miner'}${ms.every(subset) ? ' · ran on a subset of the papers' : ''}</span></div><div class=cards>${ms.map(card).join('')}</div></section>`;
      }).join('')
      + `<section class=grp>${H.header({ title: 'All miners at a glance', infoHtml: `<b>What it shows</b>One line per miner: its unit counts from the platform, the share of works read twice, and the three named agreement measures.<p><span class=k>How it's computed.</span> Units, closed, open, rows and stale are the platform's own counts (<span class=mono>mine status</span>); agreement is as defined under Two readings.</p>` })}${glanceTable()}<details style="margin-top:10px"><summary>What the columns mean</summary>${glossary()}</details></section>`
      + `<section class=grp>${H.header({ title: 'Two readings, per miner', infoHtml: `<b>What it shows</b>For each miner, the works both passes read, the rows each pass wrote, how many rows matched, and the agreement under each named measure.<p><span class=k>How it's computed.</span> ${esc(MX.fairer || '')}</p>` })}${pairsTable()}</section>`
      + `<section class=grp>${H.header({ title: 'Agreement by model', infoHtml: `<b>What it shows</b>For each pair of models that read the same papers, how often they recorded the same value.<p><span class=k>How it's computed.</span> ${esc(MX.by_model || '')}</p>` })}${pairsSection(PAIRS)}</section>`
      + `<div class=foot>${HUB.info(esc(HUB.SETS_NOTE), 'About the paper counts')} <span>Paper counts</span></div>`;
  }

  /* ---------- detail ---------- */
  function anatomy(m) {
    const nf = m.fields.length, grs = [...new Set(m.fields.map(f => f.group))];
    const nq = m.fields.filter(f => f.type === 'quote').length, ne = m.fields.filter(f => f.type === 'enum').length;
    let q = null;
    for (const ex of m.examples || []) {
      for (const [f, c] of Object.entries(ex.cells || {})) { if (c.quote && c.quote.length < 170) { q = [f, c.value, c.quote]; break; } }
      if (q) break;
    }
    const A = model(m.pass_a.models), B = model(m.pass_b.models), thr = pc(m.regime.field_agreement_min);
    return `<div class=anat>
      <div class=an><div class=st>1 · READS</div><h3 class=h3>The paper</h3><div class=tags><span class="tag">Full text</span></div><p>${fmt(m.pass_a.works)} of ${fmt(NINC)} included papers${subset(m) ? ', a subset' : ''}. Scope: ${esc(m.scope.text)}.</p></div>
      <div class=an><div class=st>2 · RECORDS</div><h3 class=h3>${pl(nf, 'field', 'fields')}</h3><div class=tags>${grs.map(g => `<span class=tag>${esc(cap(g))} · ${fmt(m.fields.filter(f => f.group === g).length)}</span>`).join('')}</div><p>${pl(ne, 'choice', 'choices')}, ${pl(nq, 'quote', 'quotes')}. ${m.multi_row ? '<b>Several rows per paper</b>' + (m.rows_per_work ? ', ' + esc(m.rows_per_work) + ' on average.' : '.') : 'One row per paper.'}</p></div>
      <div class=an><div class=st>3 · EVIDENCE</div><h3 class=h3>A quote for every value</h3>${q ? `<div class=quote>“${esc(q[2])}”</div><p>Sets <b>${esc(flab(q[0]))}</b>${q[1] != null && q[1] !== q[2] ? ' = <b>' + esc(lab(q[1])) + '</b>' : ''}.</p>` : '<p>Every value is stored with the sentence it was based on.</p>'}</div>
      <div class=an><div class=st>4 · CHECK</div><h3 class=h3>${checked(m) ? 'Read again by ' + esc(B) : 'Not checked yet'}</h3><p>${checked(m) ? `The second reading covered <b>${fmt(m.pass_b.works)}</b> of ${fmt(m.pass_a.works)} papers. First reading: ${esc(A)}${A === B ? ' (the same model, so a weaker check)' : ''}.` : `No second reading exists.`} A field passes at ${thr}% agreement; calibration set of ${fmt(m.regime.calibration_size)} papers.</p></div>
    </div>`;
  }
  let open = {};
  function fieldCard(m, f) {
    const dist = m.distributions && m.distributions[f.name];
    let body = '';
    if (f.type === 'enum' && dist && Object.keys(dist).length) {
      const unit = m.multi_row ? 'rows' : 'works';
      const ent = Object.entries(dist).map(([v, o]) => [v, o[unit]]).sort((a, b) => b[1] - a[1]);
      const tot = ent.reduce((s, x) => s + x[1], 0) || 1, lim = open[m.name + f.name] ? ent.length : 8;
      body = `<div class=bars role=group aria-label="Values of ${esc(flab(f.name))}">${ent.slice(0, lim).map(([v, n]) => `<div class=bar tabindex=0 role=button data-vals="${esc(m.name + '|' + f.name + '|' + v)}" title="${esc(lab(v))}"><span class=l>${esc(lab(v))}</span><span class=tr><i style="width:${(100 * n / tot).toFixed(1)}%"></i></span><span class=n>${fmt(n)}</span></div>`).join('')}</div>`
        + (ent.length > 8 ? `<button class=more data-more="${esc(m.name + f.name)}">${open[m.name + f.name] ? 'Show fewer' : 'Show all ' + fmt(ent.length)}</button>` : '')
        + `<div class=meta style="margin-top:6px">${m.multi_row ? 'rows' : 'papers'}. Select a value to list its papers.</div><div class=vl data-vl="${esc(m.name + '|' + f.name)}"></div>`;
    } else if (f.type === 'enum') body = `<div class=empty>No values recorded yet.</div>`;
    else body = `<div class=meta>${f.type === 'quote' ? 'Records a sentence from the paper.' : 'Records a figure as printed.'}</div>`;
    const allowed = (f.values || []).length || f.desc ? infoPop(flab(f.name), (f.desc ? `<p>${esc(f.desc)}</p>` : '') + ((f.values || []).length ? `<p><span class=k>Allowed values.</span> ${f.values.map(v => esc(lab(v))).join(', ')}</p>` : '')) : '';
    const bf = ((m.agreement || {}).fairer || {}).by_field || {}, nd = (bf[f.name] || {}).disagreements || 0;
    const dlink = nd ? `<div class=meta style="margin-top:8px"><a href="#m=${esc(m.name)}&d=${esc(f.name)}">${fmt(nd)} ${nd === 1 ? 'disagreement' : 'disagreements'} between the two readings</a></div>` : '';
    return `<div class=fc><div class=fh><b>${esc(flab(f.name))}</b><span class=tchip>${esc(cap(f.type))}</span><span class=rq>${esc(cap(f.group))}</span>${f.required ? '<span class=rq>required</span>' : ''}${f.compared ? '' : '<span class=rq>not compared</span>'}${allowed}</div>${body}${dlink}</div>`;
  }
  function track(r, thr, alt, col) {
    const [lo, hi] = wilson(r.a, r.c), L = p => (100 * p).toFixed(2) + '%';
    return `<div class="trk${alt ? ' alt' : ''}" tabindex=0 role=img aria-label="${esc(flab(r.f))}: ${pc(r.s)}% agreement, ${r.a} of ${r.c}" data-tip="${esc(flab(r.f) + '\n' + r.a + ' of ' + r.c + ' match (' + pc(r.s) + '%)\n95% range ' + pc(lo) + '–' + pc(hi) + '%')}"><i class=base></i><i class=fill style="width:${L(r.s)};background:${col}"></i><i class=wh style="left:${L(lo)};width:${L(hi - lo)}"></i><i class=dt style="left:${L(r.s)};background:${col}"></i><i class=thr style="left:${L(thr)}"></i></div>`;
  }
  function agreementSection(m) {
    const thr = m.regime.field_agreement_min, dk = defMeasure(m);
    if (!dk) return `<div class=empty>${checked(m) ? 'This miner’s fields are quotations or free text, which cannot be compared value by value.' : 'No second reading yet, so there is nothing to compare.'}</div>`;
    const R = { fairer: fieldRates(m, 'fairer'), exact: fieldRates(m, 'exact') };
    const order = []; for (const k of ['fairer', 'exact']) for (const r of R[k]) if (!order.includes(r.f)) order.push(r.f);
    const ok = s => s >= thr ? 'var(--inc)' : 'var(--exc)';
    const pf = m.agreement.platform || {}, pl = [['all_rows', 'All rows'], ['aligned_rows', 'Aligned rows only']].filter(([k]) => pf[k] != null);
    const sums = ['fairer', 'exact'].filter(k => m.agreement[k] && m.agreement[k].overall && m.agreement[k].overall.total > 0).map(k => { const o = m.agreement[k].overall; return `<div><div class=big>${pc(o.rate)}%</div><div class=lb>${MNAME[k]}${k === dk ? ' (shown first)' : ''} ${MDEF(k)}</div><div class=meta>${fmt(o.agreed)} of ${fmt(o.total)}</div></div>`; })
      .concat(pl.map(([k, l]) => `<div><div class=big>${pc(pf[k])}%</div><div class=lb>Platform rate · ${l} ${MDEF('platform')}</div></div>`));
    const rows = order.map(f => {
      const a = R.fairer.find(x => x.f === f), b = R.exact.find(x => x.f === f), first = dk === 'fairer' ? a : b, second = dk === 'fairer' ? b : a;
      const line = (x, k, alt) => x ? `<div class=fl>${alt ? '<span class=meta>' + MNAME[k] + '</span>' : esc(flab(f)) + '<br><span class=meta>' + MNAME[k] + '</span>'}</div>${track(x, thr, alt, ok(x.s))}<div class=nn>${pc(x.s)}% \u00b7 n=${fmt(x.c)}${x.d != null ? ' \u00b7 ' + fmt(x.d) + ' differ' : ''}${x.o ? ' \u00b7 ' + fmt(x.o) + ' one-sided' : ''}</div>` : '';
      const fk = dk, sk = dk === 'fairer' ? 'exact' : 'fairer';
      const top = first ? line(first, fk, false) : (second ? `<div class=fl>${esc(flab(f))}</div><div></div><div class=nn></div>` : '');
      return top + (first && second ? line(second, sk, true) : (!first && second ? line(second, sk, true) : '')) + '<div class=gap></div>';
    }).join('');
    return `<div class=sums>${sums.join('')}</div><div class=agr>${rows}<div></div><div class=axl>${[0, 25, 50, 75, 100].map(t => `<span>${t}%</span>`).join('')}</div><div></div></div>
    <div class=legend2><span><span class=sw></span>Bar to clear: ${pc(thr)}%</span><span><span class=dot style="background:var(--inc)"></span>meets it</span><span><span class=dot style="background:var(--exc)"></span>below it</span><span>Thin line: 95% range at this n</span><span>Large dot: ${MNAME[dk].toLowerCase()}; small dot: the other measure</span></div>`;
  }
  function modelSection(m) {
    const bm = m.agreement.by_model, mine = bm ? [bm] : [];
    return `<div class=meta style="margin-bottom:10px">First reading: ${esc(model(m.pass_a.models) || 'not recorded')}. Second reading: ${esc(model(m.pass_b.models) || 'none yet')}.</div>`
      + (mine.length ? pairsSection(mine) + `<div class=meta style="margin-top:8px">This rate covers this miner only: ${fmt(bm.agreed)} of ${fmt(bm.total)} field comparisons.</div>` : `<div class=empty>${checked(m) ? 'No model pair is recorded for this miner.' : 'Appears once a second reading exists.'}</div>`);
  }
  function examples(m) {
    if (!(m.examples || []).length) return `<div class=empty>No example rows yet.</div>`;
    const ftype = n => (m.fields.find(x => x.name === n) || {}).type;
    return `<div class=ex>${m.examples.map(ex => {
      const ents = Object.entries(ex.cells || {}).filter(([, c]) => c.quote || c.value != null), first = ents.slice(0, 3), rest = ents.length - first.length;
      const known = H.byId.has(ex.work);
      return `<article class=exc>${known ? `<button class=ttl data-w="${esc(ex.work)}">${esc(ex.title)}</button>` : `<div class=h3 style="margin-bottom:8px">${esc(ex.title)}</div>`}${first.map(([f, c]) => {
        const isq = ftype(f) === 'quote';
        return `<div class=ef><div class=k>${esc(flab(f))}${isq ? ' <span class=tchip>Quote</span>' : ''}</div>${isq ? '' : `<div class=v>${esc(lab(c.value))}</div>`}${c.quote ? `<blockquote class=quote>“${esc(c.quote)}”</blockquote>` : ''}</div>`;
      }).join('')}${rest > 0 ? `<div class=meta style="margin-top:10px">+ ${fmt(rest)} more fields recorded for this paper</div>` : ''}</article>`;
    }).join('')}</div>`;
  }
  function detail(m) {
    const nm = hname(m), gname = meta(m)[1], thr = m.regime.field_agreement_min, dk = defMeasure(m);
    const r = dk ? fieldRates(m, dk) : [], meet = r.filter(x => x.s >= thr).length;
    const grs = []; for (const f of m.fields) { let g = grs.find(x => x.g === f.group); if (!g) grs.push(g = { g: f.group, fs: [] }); g.fs.push(f); }
    const lead = checked(m)
      ? `Read ${fmt(m.pass_a.works)} papers and checked ${fmt(m.pass_b.works)}. ` + (r.length ? (meet ? `${fmt(meet)} of ${pl(r.length, 'compared field', 'compared fields')} reach the ${pc(thr)}% bar.` : `No compared field reaches the ${pc(thr)}% bar.`) + ` (${MNAME[dk].toLowerCase()})` : 'Its fields are free text, so they are not compared.')
      : `Read ${fmt(m.pass_a.works)} papers. No second reading yet.`;
    const popLine = subset(m) ? `Ran on a subset: ${fmt(m.pass_a.works)} of ${fmt(NINC)} included papers (${esc(m.scope.text)}).` : `${fmt(m.pass_a.works)} of ${fmt(NINC)} included papers (${esc(m.scope.text)}).`;
    main.innerHTML = `<div class=crumbs><a href="#">← All miners</a></div>`
      + H.header({ level: 1, kicker: esc(gname) + ' · ' + HUB.term('miner', 'miner') + ' <span class=mono>' + esc(m.name) + '</span> · version ' + esc(m.version) + (m.digest ? ' · digest <span class=mono>' + esc(String(m.digest).slice(0, 12)) + '</span>' : ''), title: nm, infoHtml: `<b>${esc(nm)}</b><p>${esc(m.rationale || '')}</p><p><span class=k>Regime.</span> ${fmt(m.regime.passes)} passes. A field must agree on at least ${pc(thr)}% of checked papers; recall at least ${pc(m.regime.recall_min)}%.</p>` })
      + `<p class=lead>${esc(lead)}</p><div class=actions><span class=meta>${popLine}</span><a class=btn href="data.html#miner=${encodeURIComponent(m.name)}">See the data</a></div>`
      + `<section class=dsec>${H.header({ title: 'Status', infoHtml: `<b>What it shows</b>The platform's own counts for this miner.<p><span class=k>How it's computed.</span> Units are reading tasks, one per work and pass; closed ones are finished, open ones are waiting; stale rows were made outdated by a protocol change. These come from <span class=mono>mine status</span>.</p>` })}${statusSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'How it reads', infoHtml: `<b>What it shows</b>The works, paragraphs and sections the miner is given, and the skill that reads them. Recorded in the registered spec.` })}${readsSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'Anatomy', infoHtml: `<b>What it shows</b>What the miner looks at, what it writes down, how each value is backed, and how it is checked.<p><span class=k>How it's computed.</span> ${esc(MX.anatomy || '')}</p>` })}${anatomy(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'What it records', infoHtml: `<b>What it shows</b>The ${fmt(m.fields.length)} fields, grouped as the miner defines them.<p><span class=k>How to read it.</span> Each bar is the number of ${m.multi_row ? 'rows' : 'papers'} with that value in the first reading.</p><p><span class=k>How it's computed.</span> ${esc(MX.miners || '')}</p>` })}`
      + `<div class=fgrid>${m.fields.map(f => fieldCard(m, f)).join('')}</div></section>`
      + `<section class=dsec>${H.header({ title: 'Two readings', infoHtml: `<b>What it shows</b>For each compared field, how often the second reading recorded the same value as the first, under each named measure.<p><span class=k>How to read it.</span> The dot is the share that match, the thin line is the 95% range given the papers checked, the dashed line is the bar the regime sets.</p><p><b>Fairer match.</b> ${esc(MX.fairer || '')}</p><p><b>Exact match.</b> ${esc(MX.exact || '')}</p><p><b>Platform rate.</b> ${esc(MX.platform || '')}</p>` })}${agreementSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'Quality and use', infoHtml: `<b>What it shows</b>How the protocol uses this miner and the quality checks that apply to it.` })}${useSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'Disagreements by field', infoHtml: `<b>What it shows</b>Every field where the two readings differ, largest first, with both values and the quote behind each. It shows consistency, not which reading is right: that needs gold labels.<p><span class=k>What to do.</span> Many disagreements on a field with overlapping categories mean the definitions need tightening in a new version; a field one pass left empty may need to be required.</p><p><span class=k>How it's computed.</span> ${esc(MX.fairer || '')}</p>` })}${disSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'Agreement by model', infoHtml: `<b>What it shows</b>Which models made the two readings, and how often each pair agreed.<p><span class=k>How it's computed.</span> ${esc(MX.by_model || '')}</p>` })}${modelSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'Examples', infoHtml: `<b>What it shows</b>Real rows from the first reading, each with the sentence the miner used.` })}${examples(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'Versions', infoHtml: `<b>What it shows</b>Every registered version of this miner. Only a version the protocol lists produces rows that count.` })}${versionsSection(m)}</section>`
      + `<section class=dsec>${H.header({ title: 'What you can do' })}${commandsSection(m)}</section>`
      + `<div class=foot>${HUB.info(esc(HUB.SETS_NOTE), 'About the paper counts')} <span>Paper counts</span></div>`;
    wireDis(m);
    main.querySelectorAll('[data-copy]').forEach(b => b.onclick = () => { try { navigator.clipboard.writeText(b.dataset.copy); b.textContent = 'Copied'; } catch (e) { b.textContent = 'Select and copy'; } });
    main.querySelectorAll('[data-more]').forEach(b => b.onclick = () => { open[b.dataset.more] = !open[b.dataset.more]; render(); });
    main.querySelectorAll('[data-w]').forEach(b => b.onclick = () => HUB.openDrawer(b.dataset.w));
    main.querySelectorAll('[data-vals]').forEach(el => {
      const show = () => {
        const [mn, fn, v] = el.dataset.vals.split('|'), mm = M.find(x => x.name === mn), box = main.querySelector(`[data-vl="${mn}|${fn}"]`);
        const ids = (((mm.distributions || {})[fn] || {})[v] || {}).ids || [];
        const known = ids.filter(i => H.byId.has(i));
        box.innerHTML = `<div class=meta style="margin:8px 0 4px">${fmt(known.length)} ${known.length === 1 ? 'paper' : 'papers'} with “${esc(lab(v))}”</div>` + known.map(i => `<button class=ttl data-w="${esc(i)}">${esc(H.byId.get(i).title)}</button>`).join('');
        box.querySelectorAll('[data-w]').forEach(b => b.onclick = () => HUB.openDrawer(b.dataset.w));
      };
      el.onclick = show; el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(); } };
    });
    main.querySelectorAll('[data-tip]').forEach(s => { s.onmousemove = e => HUB.tip(s.dataset.tip, e); s.onmouseleave = () => HUB.tipHtml(''); });
  }

  /* ---------- parity additions: status, how it reads, use, versions, commands, disagreements ---------- */
  const COLS = (MP.miners && MP.miners.columns) || [];
  const dash = v => v == null ? '–' : v;
  const rate = x => x == null ? '–' : pc(x) + '%';
  const st = m => m.status || {};
  const ovr = (m, k) => { const a = m.agreement && m.agreement[k]; return a && a.overall && a.overall.total ? a.overall.rate : null; };
  const firstSentence = t => { const s = String(t || '').trim(), i = s.search(/[.!?](\s|$)/); return i < 0 ? s : s.slice(0, i + 1); };
  function glossary() {
    if (!COLS.length) return '';
    return `<table class=t><thead><tr><th>Column</th><th>Meaning</th></tr></thead><tbody>${COLS.map(c => `<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.meaning)}</td></tr>`).join('')}</tbody></table>`;
  }
  function glanceTable() {
    const rows = M.map(m => {
      const s = st(m), u = m.use || {}, f = (m.agreement && m.agreement.fairer) || {};
      return `<tr><td><a href="#m=${esc(m.name)}">${esc(hname(m))}</a><br><span class="mono meta">${esc(m.name)}</span></td><td class=r>${esc(m.version)}${m.listed ? '' : ' <span class=meta>(not listed)</span>'}</td><td>${esc(firstSentence(m.rationale))}</td><td class=r>${esc(dash(s.units))}</td><td class=r>${esc(dash(s.closed))}</td><td class=r>${esc(dash(s.open))}</td><td class=r>${esc(dash(s.rows))}</td><td class=r>${esc(dash(s.stale))}</td><td class=r>${u.dual_extract_sample == null ? (m.listed ? 'every work' : '–') : pc(u.dual_extract_sample) + '%'}</td><td class=r>${rate(ovr(m, 'fairer'))}</td><td class=r>${rate(m.agreement && m.agreement.platform ? m.agreement.platform.all_rows : null)}</td><td class=r>${f.disagreements == null ? '–' : fmt(f.disagreements)}</td></tr>`;
    }).join('');
    return `<div class=scroll style="overflow-x:auto"><table class=t><thead><tr><th>Miner</th><th class=r>Version</th><th>What it records</th><th class=r>Units</th><th class=r>Closed</th><th class=r>Open</th><th class=r>Rows</th><th class=r>Stale</th><th class=r>Second pass</th><th class=r>Fairer</th><th class=r>Platform</th><th class=r>Disagreements</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function pairsTable() {
    const rows = M.filter(m => m.agreement && m.agreement.fairer && m.agreement.fairer.works_both != null).map(m => {
      const f = m.agreement.fairer, p = f.primary || {};
      return `<tr><td><a href="#m=${esc(m.name)}">${esc(hname(m))}</a></td><td class=r>${fmt(f.works_both)}</td><td class=r>${fmt(f.rows_a || 0)}</td><td class=r>${fmt(f.rows_b || 0)}</td><td class=r>${fmt(f.matched || 0)}</td><td class=r>${rate(f.overall && f.overall.total ? f.overall.rate : null)}</td><td class=r>${rate(p.total ? p.rate : null)}</td><td class=r>${rate(m.agreement.platform && m.agreement.platform.all_rows)}</td><td class=r>${rate(m.agreement.platform && m.agreement.platform.aligned_rows)}</td><td class=r>${fmt(f.disagreements || 0)}</td><td class=r>${fmt(f.one_sided || 0)}</td></tr>`;
    }).join('');
    return `<div class=scroll style="overflow-x:auto"><table class=t><thead><tr><th>Miner</th><th class=r>Works in both passes</th><th class=r>Rows A</th><th class=r>Rows B</th><th class=r>Matched</th><th class=r>Fairer (all enum values)</th><th class=r>Fairer (primary fields)</th><th class=r>Platform (all rows)</th><th class=r>Platform (aligned)</th><th class=r>Disagreements</th><th class=r>One-sided labels</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  const kv = rows => `<table class=t><tbody>${rows.map(([k, v, tip]) => `<tr><th scope=row style="text-align:left;font-weight:500;width:34%">${esc(k)}${tip ? ' ' + HUB.info(esc(tip), 'About ' + k) : ''}</th><td>${v}</td></tr>`).join('')}</tbody></table>`;
  const tf = b => b ? 'yes' : 'no';
  function statusSection(m) {
    const s = st(m), f = (m.agreement && m.agreement.fairer) || {}, pf = (m.agreement && m.agreement.platform) || {};
    if (s.units == null) return `<div class=empty>This version is registered but the protocol does not list it, so no unit counts exist.</div>`;
    return `<div class=kpis style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px">${[['Units', s.units], ['Closed', s.closed], ['Open', s.open], ['Rows', s.rows], ['Stale', s.stale]].map(([l, v]) => `<div class=exc><div class=big>${fmt(v)}</div><div class=meta>${esc(l)}</div></div>`).join('')}<div class=exc><div class=big>${rate(ovr(m, 'fairer'))}</div><div class=meta>Agreement, fairer</div></div><div class=exc><div class=big>${rate(pf.all_rows)}</div><div class=meta>Agreement, platform</div></div></div>${s.imported_dual || s.imported_single ? `<div class=meta style="margin-top:8px">Imported rows in use: ${fmt(s.imported_dual)} from a source with two agreeing passes, ${fmt(s.imported_single)} from a single pass.</div>` : ''}`;
  }
  function readsSection(m) {
    const h = m.how_reads || {};
    return kv([
      ['Works read (population)', esc(h.population || '–') + ` <span class=meta>· read ${fmt(m.pass_a.works)} of ${fmt(NINC)} included</span>`],
      ['Paragraph kinds', (h.elements || []).length ? (h.elements).map(e => `<span class=tag>${esc(e)}</span>`).join(' ') : 'all kinds'],
      ['Sections searched', (h.heading_patterns || []).length ? (h.heading_patterns).map(e => `<span class="tag mono">${esc(e)}</span>`).join(' ') : 'every section'],
      ['Most works read', h.max_works == null ? 'no cap' : fmt(h.max_works)],
      ['Procedure (skill)', h.procedure ? `<span class=mono>${esc(h.procedure)}</span>` : '–'],
      ['One row per', (h.row_key || []).length ? (h.row_key).map(e => `<span class=tag>${esc(flab(e))}</span>`).join(' ') + ' of a work' : 'work'],
    ]);
  }
  function useSection(m) {
    const u = m.use, r = m.regime, h = m.how_reads || {};
    const rows = [
      ['Passes', fmt(r.passes)],
      ['Second-pass sample', u ? (u.dual_extract_sample == null ? 'every work' : pc(u.dual_extract_sample) + '% of works') : 'not listed'],
      ['Audit', u ? pc(u.audit_fraction) + '% of rows, at least ' + fmt(u.audit_minimum) : 'not listed'],
      ['Rows enter the evidence report', u ? tf(u.evidence) : 'not listed', 'Refused by the platform until the miner is calibrated.'],
      ['Imported rows', u ? esc(u.imports) : 'not listed', 'allow, deny or audit: whether rows imported from another project are accepted.'],
      ['Exploratory', u ? tf(u.exploratory) : 'not listed', 'An exploratory use carries no quality claim and never reaches the evidence report.'],
      ['Quote rule', `at least ${fmt(h.min_quotes_per_record || 0)} quote${h.min_quotes_per_record === 1 ? '' : 's'} per record; ${h.enum_needs_quote ? 'every choice needs a quote' : 'choices need no quote'}${(h.absence_values || []).length ? '; exempt when a field says ' + h.absence_values.map(esc).join(', ') : ''}`],
      ['Calibration', `${fmt(r.calibration_size)} papers; field agreement at least ${pc(r.field_agreement_min)}%, recall at least ${pc(r.recall_min)}%`],
    ];
    if (u && ((u.layers || []).length || u.on_demand)) rows.push(['Mined automatically in', (u.layers || []).map(esc).join(', ') + (u.on_demand ? ' (and on request)' : '')]);
    return kv(rows);
  }
  function versionsSection(m) {
    const v = m.versions || [];
    if (!v.length) return `<div class=empty>No versions recorded.</div>`;
    return `<table class=t><thead><tr><th class=r>Version</th><th>Digest</th><th>Listed in the protocol</th><th>Proposed by</th></tr></thead><tbody>${v.map(x => `<tr><td class=r>${esc(x.version)}${x.version === m.version ? ' <span class=meta>(shown)</span>' : ''}</td><td class=mono>${esc(String(x.digest || '').slice(0, 16))}</td><td>${tf(x.listed)}</td><td>${esc(x.proposer || '–')}</td></tr>`).join('')}</tbody></table>`;
  }
  function commandsSection(m) {
    const cmds = (m.commands || []).map(c => `<div style="display:flex;gap:10px;align-items:center;margin:6px 0"><code class=mono>${esc(c)}</code><button class=btn type=button data-copy="${esc(c)}">Copy</button></div>`).join('');
    return cmds + `<p class=meta>To change this miner, register a new version and list it with a protocol amendment; the version above is never edited in place.</p>`;
  }
  /* Disagreements load from the grid payload (grid-<miner>), the lazy per-miner family. */
  const disCache = new Map();
  function loadDis(name) {
    if (disCache.has(name)) return Promise.resolve(disCache.get(name));
    return HUB.load(['grid-' + name]).then(x => { const g = x['grid-' + name]; disCache.set(name, (g && g.disagreements) || { fields: [], count: 0 }); return disCache.get(name); });
  }
  const side = (lbl, v, q, a) => `<div class=exc style="padding:8px"><div class=k>${esc(lbl)}</div><div class=v>${v ? esc(lab(v)) : '<span class=meta>no value</span>'}</div>${q ? `<blockquote class=quote>“${esc(q)}”</blockquote>` : ''}${a ? `<div class="meta mono">${esc(a)}</div>` : ''}</div>`;
  function disBlocks(m, d) {
    if (!d.count) return `<div class=empty>No disagreements: ${checked(m) ? 'the two readings agree on every compared value.' : 'no second reading to compare.'}</div>`;
    return `<div class=meta style="margin-bottom:8px">${fmt(d.count)} disagreements over ${fmt(d.works_both)} works read by both passes, per field below. At most ${fmt(d.per_field_cap)} pairs are listed per field; the count is exact.</div>`
      + d.fields.map(f => `<details id="dis-${esc(f.field)}" class=dsec ${H.hash.get().get('d') === f.field ? 'open' : ''}><summary><b>${esc(flab(f.field))}</b> <span class=meta>· ${fmt(f.count)} disagreements of ${fmt(f.total)} compared${f.shown < f.count ? ' · ' + fmt(f.shown) + ' listed' : ''}</span></summary>${f.desc ? `<p class=meta>${esc(f.desc)}</p>` : ''}${(f.values || []).length ? `<p class=meta>Allowed values: ${f.values.map(v => esc(lab(v))).join(', ')}</p>` : ''}${f.items.map(x => `<div style="margin:10px 0"><div>${H.byId.has(x.work) ? `<button class=ttl data-w="${esc(x.work)}">${esc(H.byId.get(x.work).title)}</button>` : '<span class=mono>' + esc(x.work) + '</span>'} <span class=chip style="cursor:default">${esc(x.why)}</span>${x.row ? ` <span class="meta mono">${esc(x.row)}</span>` : ''}</div><div class=ex style="margin-top:6px">${side('First reading', x.a, x.qa, x.aa)}${side('Second reading', x.b, x.qb, x.ab)}</div></div>`).join('')}</details>`).join('');
  }
  function disSection(m) {
    return `<div data-dis="${esc(m.name)}"><div class=meta>Loading the disagreements…</div></div>`;
  }
  function wireDis(m) {
    const box = main.querySelector('[data-dis]'); if (!box) return;
    if (!checked(m)) { box.innerHTML = `<div class=empty>No second reading yet, so there is nothing to compare.</div>`; return; }
    loadDis(m.name).then(d => {
      if (H.hash.get().get('m') !== m.name) return;
      box.innerHTML = disBlocks(m, d);
      box.querySelectorAll('[data-w]').forEach(b => b.onclick = () => HUB.openDrawer(b.dataset.w));
      const t = H.hash.get().get('d'); if (t) { const el = document.getElementById('dis-' + t); if (el) el.scrollIntoView(); }
    }).catch(e => { box.innerHTML = `<div class=empty>The disagreements could not be loaded: ${esc(e.message || e)}</div>`; });
  }
  function render() {
    const name = H.hash.get().get('m'), m = M.find(x => x.name === name);
    if (m) detail(m); else overview();
    document.title = (m ? hname(m) + ' · ' : '') + 'Miners';
  }
  addEventListener('hashchange', () => { render(); scrollTo(0, 0); });
  document.addEventListener('hub:theme', render);
  render();
}).catch(e => {
  document.body.textContent = 'Miners failed to load: ' + e.message;
});
