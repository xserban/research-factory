/* Ideas page: the lineage of ideas. Payload: shell, ideas (services/hub_ideas.py). Every number is computed in the
   payload; this script only draws and lists. EXPLORATORY: items and relations were read and proposed by agents and are
   proposals until you confirm them. Tabs: Graph, Lineage path, Needs your decision. Hash: tab, sel, path, rej, cit.
   Acts (served hub only): confirm or reject a relation or an idea, with a written reason; the service refuses a
   decision from the session that proposed it. */
HUB.load(['shell', 'ideas']).then(d => {
  const H = HUB.init(d.shell);
  const I = d.ideas || {};
  const main = H.mount({ page: 'ideas', crumb: 'Ideas' });
  const { esc, fmt } = H;
  const M = I.methods || {}, C = I.counts || {}, REL = C.relations || {}, IDEAS = C.ideas || {};
  const NODES = I.nodes || [], EDGES = I.edges || [], NEEDS = I.needs || [], PATHS = I.paths || {}, OMIT = I.omitted || {};
  const BYID = new Map(NODES.map(n => [n.id, n])), EBYID = new Map(EDGES.map(e => [e.id, e]));
  const local = {}; /* decisions made on this page, shown at once; the payload catches up when the hub rebuilds */
  main.classList.add('id');

  if (!document.getElementById('id-style')) {
    const st = document.createElement('style'); st.id = 'id-style';
    st.textContent = `
.id{padding-top:16px}
.id .lead{max-width:62ch;margin:10px 0 14px}
.id .id-kpis{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0 6px}
.id .id-kpi{background:var(--surface);border-radius:var(--r);padding:10px 14px;min-width:120px}
.id .id-kpi b{display:block;font:500 var(--t-l) var(--f-mono);color:var(--fg)}
.id .id-kpi span{font:400 var(--t-xs) var(--f-ui);color:var(--mut)}
.id .id-prop{border-left:4px solid var(--h-feedback);background:var(--surface);border-radius:var(--r-s);padding:10px 14px;margin:12px 0;font-size:var(--t-s);color:var(--mut);max-width:80ch}
.id .id-prop b{color:var(--fg);letter-spacing:.06em;text-transform:uppercase;font-size:var(--t-xs)}
.id .id-tabs{margin:18px 0 14px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.id .id-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.id .id-empty{padding:26px 22px;margin-top:var(--gap)}
.id .id-empty h3{margin:0 0 8px}
.id .id-empty ol{margin:10px 0 0;padding-left:20px;max-width:70ch}
.id .id-empty li{margin:8px 0}
.id .id-empty code{font-family:var(--f-mono);background:var(--raised);padding:1px 5px;border-radius:3px}
.id .id-wrap{overflow:auto;background:var(--surface);border-radius:var(--r);padding:8px}
.id svg{display:block}
.id svg text{fill:var(--mut);font:400 11px var(--f-ui)}
.id svg .yr{fill:var(--dim);font-family:var(--f-mono)}
.id svg .nl{fill:var(--fg);paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.id svg .nl.idea{font-weight:600}
.id svg g[data-node]{cursor:pointer}
.id svg g[data-node]:focus-visible,.id svg path[data-edge]:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.id svg .dim{opacity:.25}
.id .id-legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin:10px 0 2px;font-size:var(--t-xs);color:var(--mut)}
.id .id-legend span{display:inline-flex;align-items:center;gap:6px}
.id .id-chip{display:inline-block;padding:2px 8px;border-radius:999px;font:500 var(--t-xs) var(--f-ui);background:var(--raised);color:var(--mut)}
.id .id-chip.proposal{background:var(--surface);box-shadow:inset 0 0 0 1px var(--h-feedback);color:var(--fg)}
.id .id-chip.ok{box-shadow:inset 0 0 0 1px var(--inc);color:var(--fg)}
.id .id-chip.no{box-shadow:inset 0 0 0 1px var(--exc);color:var(--fg)}
.id .id-row{background:var(--surface);border-radius:var(--r);padding:14px 16px;margin:0 0 12px}
.id .id-row .top{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.id .id-decide{margin-top:10px}
.id .id-decide input[type=text],.drawer .id-decide input[type=text]{min-width:min(340px,100%);padding:6px 8px}
.id .id-chain{list-style:none;margin:8px 0 0;padding:0}
.id .id-chain li{padding:6px 0;border-bottom:1px solid var(--hair)}
.id .lnk,.drawer .lnk{all:unset;cursor:pointer;color:var(--acc);text-decoration:underline;text-underline-offset:3px}
.id .lnk:focus-visible,.drawer .lnk:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.drawer .id-chip{display:inline-block;padding:2px 8px;border-radius:999px;font:500 var(--t-xs) var(--f-ui);background:var(--raised);color:var(--mut)}
.drawer .id-chip.proposal{box-shadow:inset 0 0 0 1px var(--h-feedback);color:var(--fg)}
.drawer .id-chip.ok{box-shadow:inset 0 0 0 1px var(--inc);color:var(--fg)}
.drawer .id-chip.no{box-shadow:inset 0 0 0 1px var(--exc);color:var(--fg)}
.drawer .id-item{margin:12px 0}
.drawer .id-decide{margin-top:12px;display:grid;gap:8px}`;
    document.head.appendChild(st);
  }

  /* ---------- vocabulary ---------- */
  const STATUS = { stated: 'Stated in the paper', confirmed: 'Confirmed by you', inferred: 'Proposed', stale: 'Needs re-checking', rejected: 'Rejected', derived: 'Derived between ideas' };
  const KIND = { 'builds-on': 'builds on', 'improves-on': 'improves on', cites: 'cites' };
  const ITEM = { 'base-idea': 'Base idea', addition: 'Addition', limitation: 'Limitation', 'not-stated': 'Not stated' };
  const DASH = { inferred: '7 4', stale: '2 3', derived: '1 4', rejected: '3 5' };
  const eff = e => local[e.id] || e.status;
  const chipClass = s => s === 'inferred' || s === 'stale' ? 'proposal' : s === 'confirmed' ? 'ok' : s === 'rejected' ? 'no' : '';
  const statusChip = s => `<span class="id-chip ${chipClass(s)}">${esc(STATUS[s] || s)}</span>`;
  const label = id => (BYID.get(id) || {}).label || id;
  const short = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  const who = p => !p || !p.kind ? 'unknown' : p.kind === 'agent' ? 'agent' + (p.model ? ' ' + p.model : '') : p.kind === 'human' ? 'a person' : p.kind;
  const day = t => t ? String(t).slice(0, 10) : '';
  const plain = e => `${short(label(e.source), 60)} ${KIND[e.kind] || e.kind} ${short(label(e.target), 60)}`;
  const phrase = e => esc(plain(e));
  const panel = (what, read, how) => `<b>What it shows</b> ${what}${read ? `<p><span class=k>How to read it.</span> ${read}</p>` : ''}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const SRC = '<span class="meta">Read and proposed by an agent; a proposal, not a finding.</span>';
  const quoteBlock = it => it && it.quote ? `<blockquote class="quote">“${esc(it.quote)}”</blockquote><div class="meta">${it.anchor ? 'at ' + esc(it.anchor) : 'No anchor recorded'}</div>` : '<div class="meta">No quote recorded.</div>';

  const TABS = [['graph', 'Graph'], ['path', 'Lineage path'], ['needs', 'Needs your decision']];
  const st = { tab: 'graph', sel: null, path: null, rej: false, cit: false };
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'graph';
    st.sel = p.get('sel') || null; st.path = p.get('path') || null;
    st.rej = p.get('rej') === '1'; st.cit = p.get('cit') === '1';
  };
  const writeHash = () => H.hash.set({ tab: st.tab === 'graph' ? null : st.tab, sel: st.sel, path: st.path, rej: st.rej ? '1' : null, cit: st.cit ? '1' : null });

  /* ---------- decisions ---------- */
  const ROUTE = { 'relation:confirm': '/ui/act/ideas-relation-confirm', 'relation:reject': '/ui/act/ideas-relation-reject', 'idea:confirm': '/ui/act/ideas-idea-confirm', 'idea:reject': '/ui/act/ideas-idea-reject' };
  function decideBox(type, id, status, item) {
    const can = type === 'relation' ? [status === 'inferred', status !== 'rejected'] : [status === 'proposed', status !== 'rejected'];
    if (!can[0] && !can[1]) return '';
    const off = HUB.served ? '' : ' disabled title="Decisions are recorded from the live hub"';
    return `<div class="id-decide" data-type="${esc(type)}" data-id="${esc(id)}">
      ${item ? quoteBlock(item) : '<div class="meta">No basis item: the proposer gave only a note.</div>'}
      <label class="meta">Your reason <input type="text" data-why maxlength="1000" placeholder="Why it holds, or why not"${off}></label>
      <span>${can[0] ? `<button type="button" class="btn primary" data-do="confirm"${off}>Confirm</button> ` : ''}${can[1] ? `<button type="button" class="btn" data-do="reject"${off}>Reject</button>` : ''}</span>
      <span class="meta" data-msg aria-live="polite">${HUB.served ? 'Recorded as your decision; correct it later by deciding again.' : 'Decisions are recorded from the live hub.'}</span></div>`;
  }
  function wireDecide(root) {
    root.querySelectorAll('.id-decide').forEach(box => {
      const type = box.dataset.type, id = box.dataset.id, msg = box.querySelector('[data-msg]');
      box.querySelectorAll('[data-do]').forEach(b => {
        b.onclick = () => {
          const why = box.querySelector('[data-why]').value.trim();
          if (!why) { msg.textContent = 'Write your reason first; it is recorded with the decision.'; return; }
          const decision = b.dataset.do;
          HUB.confirm(msg, decision === 'confirm' ? 'Record this as confirmed?' : 'Record this as rejected?', () =>
            HUB.post(ROUTE[type + ':' + decision], { [type === 'relation' ? 'relation_id' : 'idea_id']: id, rationale: why }).then(r => {
              if (!r.ok) { msg.textContent = 'Refused: ' + r.message; return; }
              local[id] = decision === 'confirm' ? 'confirmed' : 'rejected';
              msg.textContent = 'Recorded.';
              H.closeDrawer(); render();
            }));
        };
      });
    });
  }

  /* ---------- drawer ---------- */
  const relsOf = id => EDGES.filter(e => e.kind !== 'cites' && (e.source === id || e.target === id));
  function relList(id) {
    const out = relsOf(id).filter(e => e.source === id), inn = relsOf(id).filter(e => e.target === id);
    const li = (e, other) => `<li><button type="button" class="lnk" data-edge="${esc(e.id)}">${esc(KIND[e.kind])} ${esc(short(label(other), 60))}</button> ${statusChip(eff(e))}</li>`;
    return (out.length ? `<h3 class="h3">Builds on or improves on</h3><ul>${out.map(e => li(e, e.target)).join('')}</ul>` : '') +
      (inn.length ? `<h3 class="h3">Built on or improved by</h3><ul>${inn.map(e => `<li><button type="button" class="lnk" data-edge="${esc(e.id)}">${esc(short(label(e.source), 60))}</button> ${esc(KIND[e.kind])} this ${statusChip(eff(e))}</li>`).join('')}</ul>` : '') ||
      '<p class="meta">No relation is recorded for this one yet.</p>';
  }
  function showDrawer(html) {
    const dr = document.getElementById('drawer');
    dr.innerHTML = `<div style="display:flex;justify-content:flex-end"><button type="button" class="btn" id="dClose">Close <span class="kbd">Esc</span></button></div>${html}`;
    dr.setAttribute('aria-label', 'Idea lineage detail');
    dr.setAttribute('open', ''); dr.focus();
    document.getElementById('dClose').onclick = H.closeDrawer;
    dr.querySelectorAll('[data-edge]').forEach(b => { b.onclick = () => openEdge(b.dataset.edge); });
    dr.querySelectorAll('[data-node]').forEach(b => { b.onclick = () => openNode(b.dataset.node); });
    dr.querySelectorAll('[data-paper]').forEach(b => { b.onclick = () => H.openDrawer(b.dataset.paper); });
    wireDecide(dr);
  }
  function openNode(id) {
    const n = BYID.get(id); if (!n) return;
    st.sel = id; writeHash(); paintSel();
    if (n.kind === 'idea') {
      const state = local[id] || n.state;
      const members = (n.members || []).map(m => `<li><button type="button" class="lnk" ${BYID.has(m) ? `data-node="${esc(m)}"` : `data-paper="${esc(m)}"`}>${esc(short(label(m), 80))}</button></li>`).join('');
      showDrawer(`<span class="meta">Idea · ${state === 'confirmed' ? '<span class="id-chip ok">Confirmed by you</span>' : state === 'rejected' ? '<span class="id-chip no">Rejected</span>' : '<span class="id-chip proposal">Proposal</span>'}</span>
        <h2 class="display" style="font-size:28px;margin-top:12px">${esc(n.label)}</h2>
        <p class="meta">Named by ${esc(who(n.proposer))}${n.proposed_at ? ' on ' + esc(day(n.proposed_at)) : ''}. ${state === 'confirmed' ? '' : 'Until you confirm it, this name is a suggestion.'}</p>
        <h3 class="h3">Where the name comes from</h3>${n.name_item ? `<div class="id-item"><b>${esc(ITEM[n.name_item.kind] || n.name_item.kind)}</b>${n.name_item.name ? ': ' + esc(n.name_item.name) : ''}${quoteBlock(n.name_item)}</div>` : '<p class="meta">Its name item is no longer final.</p>'}
        <h3 class="h3">Papers that carry it</h3><ul>${members || '<li class="meta">None recorded.</li>'}</ul>
        ${relList(id)}
        ${state === 'proposed' ? `<h3 class="h3">Your decision</h3>${decideBox('idea', id, 'proposed', n.name_item)}` : ''}`);
      return;
    }
    const items = (n.items || []).map(it => `<div class="id-item"><b>${esc(ITEM[it.kind] || it.kind)}</b>${it.name ? ': ' + esc(it.name) : ''}${it.stale ? ' <span class="id-chip proposal">Needs re-checking</span>' : ''}${it.statement ? `<div class="meta">${esc(it.statement)}</div>` : ''}${quoteBlock(it)}</div>`).join('');
    showDrawer(`<span class="meta">Paper${n.year ? ' · ' + esc(n.year) : ''}${n.in_corpus ? '' : ' · outside the corpus'}</span>
      <h2 class="display" style="font-size:26px;margin-top:12px">${esc(n.label)}</h2>
      ${n.in_corpus ? `<p class="meta"><button type="button" class="lnk" data-paper="${esc(n.id)}">Paper details</button></p>` : ''}
      <h3 class="h3">What it builds on and adds</h3>${n.items.length ? SRC + items : '<p class="meta">No contribution item is recorded for this paper.</p>'}
      ${n.items_total > n.items.length ? `<p class="meta">${esc(fmt(n.items.length))} of ${esc(fmt(n.items_total))} items shown.</p>` : ''}
      ${relList(id)}`);
  }
  function openEdge(id) {
    const e = EBYID.get(id); if (!e) return;
    const s = eff(e);
    const reasons = (e.stale_reasons || []).map(r => esc(r)).join(', ');
    showDrawer(`<span class="meta">${esc(KIND[e.kind] || e.kind)} · ${statusChip(s)}${e.proposal && s !== 'confirmed' && s !== 'rejected' ? ' <span class="id-chip proposal">Proposal</span>' : ''}</span>
      <h2 class="display" style="font-size:24px;margin-top:12px">${phrase(e)}</h2>
      <p class="meta"><button type="button" class="lnk" data-node="${esc(e.source)}">Open the later one</button> · <button type="button" class="lnk" data-node="${esc(e.target)}">Open the earlier one</button></p>
      ${e.derived ? '<p class="meta">Derived: the platform computes this edge between ideas from the relations of their member papers. It is not a separate claim.</p>' : `
      <p class="meta">Proposed by ${esc(who(e.proposer))}${e.proposed_at ? ' on ' + esc(day(e.proposed_at)) : ''}${e.reason ? '. Why it is only proposed: ' + esc(e.reason) : ''}.${reasons ? ' Needs re-checking because: ' + reasons + '.' : ''}</p>
      ${e.note ? `<p class="meta">Agent note (not evidence): ${esc(e.note)}</p>` : ''}
      <h3 class="h3">Evidence</h3>${e.basis_item ? `<div class="id-item"><b>${esc(ITEM[e.basis_item.kind] || e.basis_item.kind)}</b>${e.basis_item.name ? ': ' + esc(e.basis_item.name) : ''}${quoteBlock(e.basis_item)}</div>` : '<p class="meta">No basis item; the relation rests on the proposer’s note alone.</p>'}
      ${e.kind === 'cites' ? '' : `<h3 class="h3">Your decision</h3>${decideBox('relation', id, s, e.basis_item) || '<p class="meta">Nothing to decide here.</p>'}`}`}`);
  }

  /* ---------- graph ---------- */
  const COLW = 210, ROWH = 26, TOP = 38, LEFT = 24;
  function layout() {
    const years = [...new Set(NODES.map(n => n.year || ''))].sort((a, b) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)));
    const col = new Map(years.map((y, i) => [y, i])), rows = years.map(() => 0), pos = new Map();
    const order = [...NODES].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === 'idea' ? -1 : 1) || String(a.label).localeCompare(String(b.label)) || a.id.localeCompare(b.id));
    for (const n of order) { const c = col.get(n.year || ''); pos.set(n.id, { x: LEFT + c * COLW, y: TOP + rows[c] * ROWH }); rows[c] += 1; }
    return { years, pos, w: LEFT * 2 + years.length * COLW, h: TOP + Math.max(1, ...rows) * ROWH + 12 };
  }
  const edgeStyle = e => {
    const s = eff(e), k = e.kind;
    const colour = k === 'improves-on' ? 'var(--inc)' : k === 'cites' ? 'var(--line)' : 'var(--h-review)';
    const colourRej = s === 'rejected' ? 'var(--exc)' : colour;
    return { colour: colourRej, width: k === 'improves-on' ? 2.4 : k === 'cites' ? 1 : 1.6, dash: DASH[s] || '' };
  };
  function graphSvg() {
    const L = layout(), edges = EDGES.filter(e => (st.cit || e.kind !== 'cites') && (st.rej || eff(e) !== 'rejected') && L.pos.has(e.source) && L.pos.has(e.target));
    const path = e => {
      const a = L.pos.get(e.source), b = L.pos.get(e.target), sx = a.x, sy = a.y, tx = b.x, ty = b.y;
      if (sx === tx) { const bulge = 40 + Math.min(60, Math.abs(ty - sy) / 3); return `M${sx} ${sy} C${sx + bulge} ${sy} ${tx + bulge} ${ty} ${tx} ${ty}`; }
      const dx = (tx - sx) / 2; return `M${sx} ${sy} C${sx + dx} ${sy} ${tx - dx} ${ty} ${tx} ${ty}`;
    };
    const mk = (id, colour) => `<marker id="id-ar-${id}" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" style="fill:${colour}"/></marker>`;
    const defs = `<defs>${mk('b', 'var(--h-review)')}${mk('i', 'var(--inc)')}${mk('c', 'var(--line)')}${mk('r', 'var(--exc)')}</defs>`;
    const arrow = (e, s) => 'url(#id-ar-' + (s === 'rejected' ? 'r' : e.kind === 'improves-on' ? 'i' : e.kind === 'cites' ? 'c' : 'b') + ')';
    const edgeSvg = edges.map(e => {
      const s = eff(e), y = edgeStyle(e);
      return `<g data-e="${esc(e.id)}" data-src="${esc(e.source)}" data-tgt="${esc(e.target)}"><path d="${path(e)}" fill="none" style="stroke:${y.colour}" stroke-width="${y.width}" ${y.dash ? `stroke-dasharray="${y.dash}"` : ''} marker-end="${arrow(e, s)}"/><path data-edge="${esc(e.id)}" d="${path(e)}" fill="none" stroke="transparent" stroke-width="12" tabindex="0" role="button" aria-label="${esc(plain(e))}, ${esc(STATUS[s] || s)}"/></g>`;
    }).join('');
    const nodeSvg = NODES.map(n => {
      const p = L.pos.get(n.id), idea = n.kind === 'idea', sel = st.sel === n.id;
      const shape = idea ? `<rect x="-6" y="-6" width="12" height="12" rx="2" transform="rotate(45)" style="fill:${n.state === 'confirmed' || local[n.id] === 'confirmed' ? 'var(--acc)' : 'var(--surface)'};stroke:var(--acc)" stroke-width="1.6"/>` : `<circle r="5" style="fill:${n.read ? 'var(--fg)' : 'var(--dim)'}"/>`;
      return `<g data-node="${esc(n.id)}" transform="translate(${p.x} ${p.y})" tabindex="0" role="button" aria-label="${esc((idea ? 'Idea ' : 'Paper ') + n.label)}"><title>${esc(n.label)}</title>${sel ? '<circle r="10" fill="none" style="stroke:var(--acc)" stroke-width="2"/>' : ''}${shape}<text class="nl ${idea ? 'idea' : ''}" x="11" y="4">${esc(short(n.label, 28))}</text></g>`;
    }).join('');
    const heads = L.years.map((y, i) => `<text class="yr" x="${LEFT + i * COLW}" y="16">${esc(y || 'No date')}</text>`).join('');
    const finding = `${fmt(NODES.length)} nodes and ${fmt(edges.length)} edges are drawn.`;
    return `<div class="id-wrap"><svg width="${L.w}" height="${L.h}" viewBox="0 0 ${L.w} ${L.h}" role="img" aria-label="${esc(finding)}">${defs}${heads}${edgeSvg}${nodeSvg}</svg></div>`;
  }
  function paintSel() { /* dim what is not next to the selected node */
    const svg = main.querySelector('.id-wrap svg'); if (!svg) return;
    svg.querySelectorAll('g[data-e]').forEach(g => g.classList.toggle('dim', !!st.sel && g.dataset.src !== st.sel && g.dataset.tgt !== st.sel));
    svg.querySelectorAll('g[data-node]').forEach(g => { g.querySelector('circle[r="10"]')?.remove(); if (g.dataset.node === st.sel) { const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); c.setAttribute('r', '10'); c.setAttribute('fill', 'none'); c.style.stroke = 'var(--acc)'; c.setAttribute('stroke-width', '2'); g.prepend(c); } });
  }
  const legend = () => `<div class="id-legend" aria-label="Legend">
    <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" style="stroke:var(--h-review)" stroke-width="1.6"/></svg>builds on</span>
    <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" style="stroke:var(--inc)" stroke-width="2.4"/></svg>improves on</span>
    <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" style="stroke:var(--line)" stroke-width="1"/></svg>cites</span>
    <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" style="stroke:var(--fg)" stroke-width="1.6"/></svg>solid: stated or confirmed</span>
    <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" style="stroke:var(--fg)" stroke-width="1.6" stroke-dasharray="7 4"/></svg>dashed: proposed</span>
    <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" style="stroke:var(--fg)" stroke-width="1.6" stroke-dasharray="1 4"/></svg>dotted: derived</span>
    <span><svg width="12" height="12"><circle cx="6" cy="6" r="5" style="fill:var(--fg)"/></svg>paper</span>
    <span><svg width="14" height="14"><rect x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" style="fill:none;stroke:var(--acc)" stroke-width="1.6"/></svg>idea</span></div>`;
  function graphTab() {
    const rejN = REL.rejected || 0;
    const cut = (OMIT.nodes || OMIT.edges || OMIT.cites || OMIT.items) ? `<p class="meta">Left out to keep the picture readable: ${fmt(OMIT.nodes || 0)} nodes, ${fmt(OMIT.edges || 0)} relations, ${fmt(OMIT.cites || 0)} citations, ${fmt(OMIT.items || 0)} items.</p>` : '';
    return `<div class="id-bar"><button type="button" class="chip" data-cit aria-pressed="${st.cit}">Citations</button><button type="button" class="chip" data-rej aria-pressed="${st.rej}">Rejected <span class="n">${fmt(rejN)}</span></button><span class="meta">Select a node or a line for the evidence behind it.</span></div>${graphSvg()}${legend()}${cut}`;
  }

  /* ---------- lineage path ---------- */
  function pathTab() {
    const ids = Object.keys(PATHS).sort((a, b) => label(a).localeCompare(label(b)) || a.localeCompare(b));
    if (!ids.length) return `<div class="card id-empty"><h3 class="h3">No chain yet</h3><p class="meta">A chain appears once a paper or an idea has a recorded relation to an earlier one.</p></div>`;
    const pick = ids.includes(st.path) ? st.path : (ids.includes(st.sel) ? st.sel : ids[0]);
    const P = PATHS[pick], inP = new Set(P.edges), out = new Map();
    for (const eid of P.edges) { const e = EBYID.get(eid); if (e) { if (!out.has(e.source)) out.set(e.source, []); out.get(e.source).push(e); } }
    const lines = [];
    const walk = (id, depth, seen) => {
      for (const e of out.get(id) || []) {
        if (!inP.has(e.id) || seen.has(e.target)) continue;
        const root = (P.roots || []).includes(e.target);
        lines.push(`<li style="padding-left:${depth * 22}px">${esc(KIND[e.kind])} <button type="button" class="lnk" data-node="${esc(e.target)}">${esc(short(label(e.target), 80))}</button> ${statusChip(eff(e))} ${root ? '<span class="id-chip">start of the chain</span>' : ''} <button type="button" class="lnk" data-edge="${esc(e.id)}">evidence</button></li>`);
        walk(e.target, depth + 1, new Set([...seen, e.target]));
      }
    };
    walk(pick, 0, new Set([pick]));
    const opts = ids.map(i => `<option value="${esc(i)}"${i === pick ? ' selected' : ''}>${esc((BYID.get(i).kind === 'idea' ? 'Idea: ' : '') + short(label(i), 70))}</option>`).join('');
    return `<div class="id-bar"><label class="meta">From <select id="id-pick" aria-label="Start from a paper or an idea">${opts}</select></label></div>
      <div class="card id-row"><div class="top"><b>${esc(label(pick))}</b><span class="meta">${fmt(P.nodes.length)} earlier, ${fmt((P.roots || []).length)} at the start${P.truncated ? ', cut at the depth limit' : ''}</span></div>
      <ul class="id-chain">${lines.join('') || '<li class="meta">Nothing further back.</li>'}</ul></div>`;
  }

  /* ---------- needs your decision ---------- */
  function needsTab() {
    const rows = NEEDS.map(n => {
      if (n.type === 'relation') {
        const e = EBYID.get(n.id); if (!e || eff(e) !== 'inferred') return '';
        return `<div class="id-row"><div class="top">${statusChip('inferred')}<b>${phrase(e)}</b></div>
          <div class="meta">${esc(KIND[e.kind])} · proposed by ${esc(who(e.proposer))}${e.proposed_at ? ' on ' + esc(day(e.proposed_at)) : ''}${e.reason ? ' · ' + esc(e.reason) : ''} · <button type="button" class="lnk" data-edge="${esc(e.id)}">Open</button></div>${decideBox('relation', e.id, 'inferred', e.basis_item)}</div>`;
      }
      const nd = BYID.get(n.id); if (!nd || (local[nd.id] || nd.state) !== 'proposed') return '';
      return `<div class="id-row"><div class="top"><span class="id-chip proposal">Idea proposal</span><b>${esc(nd.label)}</b></div>
        <div class="meta">Named by ${esc(who(nd.proposer))}${nd.proposed_at ? ' on ' + esc(day(nd.proposed_at)) : ''} · <button type="button" class="lnk" data-node="${esc(nd.id)}">Open</button></div>${decideBox('idea', nd.id, 'proposed', nd.name_item)}</div>`;
    }).join('');
    return rows || `<div class="card id-empty"><h3 class="h3">Nothing waits for you</h3><p class="meta">${I.empty ? 'Proposals appear here once the lineage skill has recorded some.' : 'Every proposed relation and idea has a decision.'}</p></div>`;
  }

  /* ---------- empty state ---------- */
  function emptyBlock() {
    const steps = (I.missing || []).map(s => `<li><b>${esc(s.what)}</b> ${esc(s.step)}</li>`).join('');
    return `<section class="card id-empty"><h3 class="h3">${I.empty ? 'Nothing is here yet' : 'Relations are still missing'}</h3>
      <p class="meta">${I.empty ? 'This is not an error: the page fills in as the steps below run. They run as agent sessions outside the hub, each in its own Claude Code session.' : 'Papers have been read, but no relation or idea has been proposed.'}</p>
      <ol>${steps}</ol>
      <p class="meta">${C.population ? `${fmt(C.population)} included papers are waiting to be read.` : 'No included paper is waiting yet; screening comes first.'}</p></section>`;
  }

  /* ---------- render ---------- */
  function render() {
    const nProp = NEEDS.filter(n => n.type === 'relation' ? (EBYID.get(n.id) && eff(EBYID.get(n.id)) === 'inferred') : (BYID.get(n.id) && (local[n.id] || BYID.get(n.id).state) === 'proposed')).length;
    const lead = I.empty ? 'No lineage has been recorded yet, so there is nothing to draw.' :
      `${fmt(C.works_read || 0)} papers were read for what they build on. ${fmt(nProp)} proposals wait for your decision.`;
    const kpi = (v, l, info) => `<div class="id-kpi"><b>${fmt(v)}</b><span>${esc(l)}${info ? ' ' + H.info(info) : ''}</span></div>`;
    const rel = REL;
    const kpis = `<div class="id-kpis">${kpi(C.works_read || 0, 'papers read', panel('How many included papers have a final contribution item.', '', M.overview))}${kpi(C.items || 0, 'items')}${kpi((IDEAS.confirmed || 0) + (IDEAS.proposed || 0), 'ideas')}
      ${kpi(rel.confirmed || 0, 'relations confirmed')}${kpi(rel.stated || 0, 'stated in papers', panel('A relation the paper’s own reference list backs.', '', M.status))}${kpi(rel.inferred || 0, 'proposed')}${kpi(rel.stale || 0, 'need re-checking')}${kpi(rel.rejected || 0, 'rejected')}</div>`;
    const tabs = '<div class="seg" role="group" aria-label="Ideas views">' + TABS.map(([k, l]) => `<button type="button" data-tab="${k}" aria-pressed="${st.tab === k}">${esc(l)}${k === 'needs' ? ` (${fmt(nProp)})` : ''}</button>`).join('') + '</div>';
    const body = st.tab === 'graph' ? (NODES.length ? graphTab() : '') : st.tab === 'path' ? pathTab() : needsTab();
    main.innerHTML = H.header({ kicker: 'Lineage', title: 'Ideas', sub: 'Which paper builds on which, and the ideas between them.', level: 1,
      infoHtml: panel('The lineage of ideas across the papers read for their contributions.', 'Columns are years. A solid line is stated or confirmed; a dashed line is a proposal waiting for you.', M.graph) }) +
      `<p class="lead">${esc(lead)}</p>` + kpis +
      `<div class="id-prop"><b>Exploratory</b> Items and relations were read and proposed by agents. Each is a proposal until you confirm it; the quote is the evidence. ${H.info(esc(M.page || ''))}</div>` +
      ((I.empty || (I.missing || []).length) ? emptyBlock() : '') +
      `<div class="id-tabs">${tabs}</div>` + body;
    wire();
    paintSel();
  }
  function wire() {
    const on = (sel, fn) => main.querySelectorAll(sel).forEach(el => { el.onclick = e => { e.preventDefault(); fn(el); }; });
    on('[data-tab]', el => { st.tab = el.dataset.tab; writeHash(); render(); });
    on('[data-cit]', () => { st.cit = !st.cit; writeHash(); render(); });
    on('[data-rej]', () => { st.rej = !st.rej; writeHash(); render(); });
    main.querySelectorAll('svg g[data-node]').forEach(g => {
      g.onclick = () => openNode(g.dataset.node);
      g.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openNode(g.dataset.node); } };
    });
    main.querySelectorAll('svg path[data-edge]').forEach(p => {
      p.onclick = () => openEdge(p.dataset.edge);
      p.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openEdge(p.dataset.edge); } };
    });
    main.querySelectorAll('.id-chain [data-node], .id-row [data-node]').forEach(b => { b.onclick = () => openNode(b.dataset.node); });
    main.querySelectorAll('.id-chain [data-edge], .id-row [data-edge]').forEach(b => { b.onclick = () => openEdge(b.dataset.edge); });
    const pk = main.querySelector('#id-pick'); if (pk) pk.onchange = () => { st.path = pk.value; writeHash(); render(); };
    wireDecide(main);
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
