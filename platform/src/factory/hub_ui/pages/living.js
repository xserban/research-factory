/* Living review page. Payloads: shell (as-of stamp) and living (feed river, horizon, heartbeat, methods,
   from services/hub_living.py). Every number comes from the payloads. Tabs: New papers, How current, Heartbeat. */
HUB.load(['shell', 'living']).then(d => {
  const H = HUB.init(d.shell);
  const L = d.living || {};
  const main = H.mount({ page: 'living', crumb: 'Living review' });
  const { esc, fmt } = H;
  const M = L.methods || {};
  const RIV = L.feed_river || { total: 0, days: [] };
  const HOR = L.horizon || { sources: [], years: [] };
  const HB = L.heartbeat || { total: 0, days: [], family_totals: {} };
  const FAMS = L.families || [];

  if (!document.getElementById('lv-style')) {
    const st = document.createElement('style'); st.id = 'lv-style';
    st.textContent = `
.lv-lead{max-width:44ch;margin:14px 0 0}
.lv-tabs{margin:22px 0 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.lv-card{padding:18px 18px 12px}
.lv-svg{display:block;width:100%;height:auto}
.lv-svg .bar{cursor:pointer}
.lv-svg .bar:hover rect.b,.lv-svg .bar:focus rect.b{opacity:.8}
.lv-svg .bar:focus{outline:none}
.lv-svg .sel{stroke:var(--acc);stroke-width:2;fill:none}
.lv-legend{display:flex;flex-wrap:wrap;gap:16px;margin:8px 0 4px;font:400 var(--t-xs) var(--f-ui);color:var(--mut);align-items:center}
.lv-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.lv-day{margin-top:var(--gap)}
.lv-day .stats{display:flex;flex-wrap:wrap;gap:6px 22px;margin:6px 0 12px}
.lv-day .stats b{font:500 var(--t-m) var(--f-mono);color:var(--fg)}
.lv-day .stats span{color:var(--mut);font-size:var(--t-s)}
.lv-list{list-style:none;margin:0;padding:0}
.lv-list li{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:12px;align-items:baseline;padding:9px 4px;border-top:1px solid var(--hair)}
.lv-list .rk{font:500 var(--t-s) var(--f-mono);color:var(--mut);text-align:right}
.lv-list .rk.none{color:var(--dim)}
.lv-list a{color:var(--fg);text-decoration:none}.lv-list a:hover{color:var(--acc);text-decoration:underline}
.lv-list .sc{display:block;font:400 var(--t-xs) var(--f-mono);color:var(--dim);margin-top:2px}
.lv-react{font:500 var(--t-xs) var(--f-ui);color:var(--mut);white-space:nowrap;display:inline-flex;gap:5px;align-items:center}
.lv-react svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.7}
.lv-react.like,.lv-react.save{color:var(--inc)}.lv-react.dislike{color:var(--exc)}
.lv-react.sent{color:var(--acc)}
.lv-empty{color:var(--dim);font:400 var(--t-m) var(--f-ui);padding:36px 8px;text-align:center}
.lv-src{display:grid;grid-template-columns:110px minmax(0,1fr) 150px;gap:14px;align-items:center;padding:12px 0;border-top:1px solid var(--hair)}
.lv-src:first-child{border-top:0}
.lv-src .nm{font:500 var(--t-s) var(--f-ui)}
.lv-src .bhind{font:500 var(--t-s) var(--f-mono);text-align:right;color:var(--fg)}
.lv-src .tr{position:relative;height:28px}
.lv-hb{display:grid;grid-template-columns:minmax(0,auto) minmax(260px,1fr);gap:var(--gap);align-items:start}.lv-hb .lv-day{margin-top:0}
.lv-hb-head{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.lv-hb-wrap{overflow-x:auto;padding-bottom:6px}
.lv-hb-wrap svg{display:block}
.lv-hb-wrap rect.cell{cursor:pointer}
.lv-hb-wrap rect.cell:hover,.lv-hb-wrap rect.cell.on{stroke:var(--acc);stroke-width:2}
.lv-fam{display:grid;grid-template-columns:110px minmax(0,1fr) 70px;gap:8px;align-items:center;font:400 var(--t-s) var(--f-ui);padding:2px 0}
.lv-fam .tr{height:8px;background:var(--raised);border-radius:2px;overflow:hidden}.lv-fam .tr i{display:block;height:100%;background:var(--acc)}
.lv-fam .v{text-align:right;font:400 var(--t-xs) var(--f-mono);color:var(--mut)}
@media (max-width:1000px){.lv-hb{grid-template-columns:minmax(0,1fr)}}
@media (max-width:760px){.lv-scroll{overflow-x:auto}.lv-scroll svg{min-width:640px}.lv-src{grid-template-columns:70px minmax(0,1fr);}.lv-src .bhind{grid-column:1 / -1;text-align:left}.lv-list li{grid-template-columns:30px minmax(0,1fr)}.lv-list li .lv-react{grid-column:2}}`;
    document.head.appendChild(st);
  }

  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const utc = s => { const [y, m, d] = s.slice(0, 10).split('-').map(Number); return Date.UTC(y, m - 1, d); };
  const iso = t => new Date(t).toISOString().slice(0, 10);
  const DAY = 86400000;
  const dlab = s => { const t = new Date(utc(s)); return t.getUTCDate() + ' ' + MON[t.getUTCMonth()]; };
  const dlabY = s => dlab(s) + ' ' + s.slice(0, 4);
  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
  const FAM_LABEL = { search: 'Search', screening: 'Screening', acquisition: 'Acquisition', conversion: 'Conversion', mining: 'Mining', references: 'References', feed: 'Feed', other: 'Other' };
  const SRC = { arxiv: 'arXiv', openalex: 'OpenAlex' };
  const srcName = s => SRC[s] || H.pretty(s);
  const famLabel = f => FAM_LABEL[f] || H.pretty(f);
  const ICO = {
    like: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
    dislike: '<path d="M6 6l12 12M18 6L6 18"/>',
    save: '<path d="M6 4h12v16l-6-4-6 4z"/>',
    dismiss: '<path d="M5 12h14"/>',
    sent: '<path d="M4 12l16-7-6 16-3-6z"/>',
  };
  const RWORD = { like: 'Liked', dislike: 'Disliked', save: 'Saved', dismiss: 'Dismissed' };
  const react = (k, word) => `<span class="lv-react ${k}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICO[k] || ICO.dismiss}</svg>${esc(word || RWORD[k] || H.pretty(k))}</span>`;
  const panel = (what, read, how) => `<b>What it shows</b> ${what}${read ? `<p><span class=k>How to read it.</span> ${read}</p>` : ''}${how ? `<p><span class=k>How it’s computed.</span> ${esc(how)}</p>` : ''}`;
  const empty = msg => `<div class="card lv-empty">${esc(msg)}</div>`;

  const TABS = [['river', 'New papers'], ['horizon', 'How current'], ['beat', 'Heartbeat']];
  const st = { tab: 'river', day: null, fam: 'all' };
  const readHash = () => {
    const p = H.hash.get();
    st.tab = TABS.some(t => t[0] === p.get('tab')) ? p.get('tab') : 'river';
    st.day = p.get('day') || null; st.fam = p.get('fam') || 'all';
  };
  const go = o => { H.hash.set(o); readHash(); render(); };

  /* ---------------- New papers ---------------- */
  function river() {
    const days = RIV.days || [];
    if (!days.length) return { lead: 'No feed runs yet.', info: panel('New arXiv papers per day, with the best-ranked ones and your reactions.', '', M.feed_river), body: empty('No feed runs yet. New papers appear here once the feed has fetched.') };
    const byDay = new Map(days.map(x => [x.day, x]));
    const first = utc(days[0].day), last = utc(days[days.length - 1].day);
    const all = []; for (let t = first; t <= last; t += DAY) all.push(iso(t));
    const mx = Math.max(...days.map(x => x.count));
    const sel = byDay.has(st.day) ? st.day : days[days.length - 1].day;
    const n = all.length, W = 880, Hh = 220, L0 = 44, B = 190, T = 14, step = (W - L0 - 8) / n, bw = Math.min(64, step * .7);
    const y = v => B - (B - T) * v / mx;
    const ticks = [0, .5, 1].map(f => Math.round(mx * f));
    const sx = i => L0 + step * i + (step - bw) / 2;
    const lblEvery = Math.ceil(n / 12);
    const svg = `<svg class="lv-svg" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="New papers per day">
      ${ticks.map(v => `<line class="gridline" x1="${L0}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L0 - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`).join('')}
      ${all.map((dy, i) => {
        const x = byDay.get(dy); const bx = sx(i);
        const lab = i % lblEvery === 0 || dy === sel ? `<text class="axis" x="${bx + bw / 2}" y="${B + 16}" text-anchor="middle">${dlab(dy)}</text>` : '';
        if (!x) return lab;
        const sh = x.shown, rest = x.count - sh;
        return `<g class="bar" tabindex="0" role="button" data-day="${dy}" aria-label="${dlab(dy)}: ${plural(x.count, 'new paper', 'new papers')}" aria-pressed="${dy === sel}">
          <rect class="b" x="${bx}" y="${y(x.count)}" width="${bw}" height="${B - y(x.count)}" rx="2" fill="var(--mut)" opacity=".55"/>
          ${sh ? `<rect class="b" x="${bx}" y="${y(sh)}" width="${bw}" height="${B - y(sh)}" rx="2" fill="var(--acc)"/>` : ''}
          <rect x="${bx - 2}" y="${T - 2}" width="${bw + 4}" height="${B - T + 4}" fill="transparent"/>
          ${dy === sel ? `<rect class="sel" x="${bx - 3}" y="${y(x.count) - 3}" width="${bw + 6}" height="${B - y(x.count) + 6}" rx="3"/>` : ''}
          <text class="lbl" x="${bx + bw / 2}" y="${y(x.count) - 6}" text-anchor="middle">${fmt(x.count)}</text></g>${lab}`;
      }).join('')}</svg>`;
    const cur = byDay.get(sel);
    const lastDay = days[days.length - 1], shownDays = days.filter(x => x.shown).length;
    const lead = `${fmt(RIV.total)} new papers came in over ${plural(days.length, 'day', 'days')}. ${shownDays ? `The latest ${plural(lastDay.shown, 'was ranked', 'were ranked')} for you.` : 'None have been ranked yet.'}`;
    const rx = Object.entries(cur.reactions || {});
    const list = cur.top.map(t => {
      const rk = t.rank == null ? `<span class="rk none" title="Not shown by the ranking">–</span>` : `<span class="rk">#${fmt(t.rank)}</span>`;
      const re = [t.reaction ? react(t.reaction) : '', t.sent ? react('sent', 'Sent to inbox') : ''].filter(Boolean).join(' ');
      return `<li>${rk}<span><a href="https://arxiv.org/abs/${esc(t.entry_id)}" target="_blank" rel="noopener">${esc(t.title)}</a>${t.score != null ? `<span class="sc">score ${t.score.toFixed(3)}</span>` : ''}</span><span>${re}</span></li>`;
    }).join('');
    const detail = `<section class="card lv-day">
      ${H.header({ title: dlabY(sel), sub: `<span class="meta">${plural(cur.count, 'new paper', 'new papers')}</span>` })}
      <div class="stats"><span><b>${fmt(cur.count)}</b> new</span><span><b>${fmt(cur.shown)}</b> shown</span><span><b>${fmt(cur.sent)}</b> sent to inbox</span>
        <span><b>${fmt(rx.reduce((a, r) => a + r[1], 0))}</b> reacted${rx.length ? ' (' + rx.map(([k, v]) => `${fmt(v)} ${esc((RWORD[k] || k).toLowerCase())}`).join(', ') + ')' : ''}</span></div>
      <ul class="lv-list">${list}</ul>
      ${cur.count > cur.top.length ? `<p class="meta" style="margin:10px 0 0">Best ${fmt(cur.top.length)} of ${fmt(cur.count)}</p>` : ''}</section>`;
    const body = `<div class="card lv-card"><div class="lv-scroll">${svg}</div><div class="lv-legend"><span><i style="background:var(--acc)"></i>Shown by the ranking</span><span><i style="background:var(--mut);opacity:.55"></i>Not shown</span></div></div>${detail}`;
    return { lead, info: panel('How many new arXiv papers the feed found each day, and what you did with the best-ranked ones.', 'Each bar is one day. The tinted part of a bar is the share the ranking put in front of you. Click a day to list its best-ranked papers with your reaction.', M.feed_river), body };
  }

  /* ---------------- How current ---------------- */
  function horizon() {
    const src = HOR.sources || [];
    const info = panel('How fresh each source is: when it was last searched, against today.', 'Each row runs from the date of the latest search to today. The longer the line, the further behind the source is.', M.horizon);
    if (!src.length) return { lead: 'No searches recorded yet.', info, body: empty('No searches recorded yet. Each source appears here once it has been searched.') };
    const todayT = utc((d.shell.generated || new Date().toISOString()));
    const ages = src.map(s => s.days_ago).filter(a => a != null);
    const worst = src.slice().sort((a, b) => (b.days_ago ?? -1) - (a.days_ago ?? -1))[0];
    const same = ages.length && ages.every(a => a === ages[0]);
    const lead = same ? `Every source was last searched ${plural(ages[0], 'day', 'days')} ago.` : `${esc(srcName(worst.source))} is the furthest behind, last searched ${plural(worst.days_ago, 'day', 'days')} ago.`;
    const t0 = Math.min(...src.map(s => utc(s.latest_search)), todayT - DAY * 7), span = todayT - t0 || DAY, W = 760;
    const X = t => 20 + (W - 40) * (t - t0) / span;
    const rows = src.map(s => {
      const t = utc(s.latest_search), x = X(t), x1 = X(todayT);
      const msg = s.days_ago == null ? 'date unknown' : s.days_ago === 0 ? 'searched today' : `${plural(s.days_ago, 'day', 'days')} behind`;
      return `<div class="lv-src"><span class="nm">${esc(srcName(s.source))}</span>
        <svg class="lv-svg" viewBox="0 0 ${W} 28" role="img" aria-label="${esc(srcName(s.source))}: ${esc(msg)}"><line x1="${x}" x2="${x1}" y1="14" y2="14" stroke="var(--line)" stroke-width="3" stroke-linecap="round"/>
          <circle cx="${x}" cy="14" r="6" fill="var(--acc)"/><circle cx="${x1}" cy="14" r="5" fill="none" stroke="var(--mut)" stroke-width="1.8"/></svg>
        <span class="bhind">${esc(msg)}</span></div>`;
    }).join('');
    const axis = `<div class="lv-src" style="border:0;padding-top:0"><span></span><svg class="lv-svg" viewBox="0 0 ${W} 22"><text class="axis" x="20" y="14">${dlab(iso(t0))}</text><text class="axis" x="${W - 20}" y="14" text-anchor="end">Today, ${dlab(iso(todayT))}</text></svg><span></span></div>`;
    const years = HOR.years || [];
    const pub = years.length ? `<p class="meta" style="margin:12px 0 0">Newest publications found: ${fmt(HOR.latest_year)}.</p>` : '';
    const notes = (HOR.notices || []).map(n => esc(n)).join(' ');
    const body = `<div class="card lv-card">${rows}${axis}
      <div class="lv-legend"><span><i style="background:var(--acc);border-radius:50%"></i>Latest search</span><span><i style="background:none;border:1.8px solid var(--mut);border-radius:50%;width:8px;height:8px"></i>Today</span></div>${pub}</div>
      ${notes ? `<p class="meta" style="margin:12px 4px 0">${notes}</p>` : ''}`;
    return { lead, info, body };
  }

  /* ---------------- Heartbeat ---------------- */
  function beat() {
    const days = HB.days || [];
    const info = panel('How active the project was on each day, and in which kind of work.', 'Each square is a day, weeks run in columns, Monday at the top. Darker means more events. Pick a family to see only that kind of work; hover a day for the split.', M.heartbeat);
    if (!days.length) return { lead: 'No activity yet.', info, body: empty('No activity yet. Days appear here as events are recorded.') };
    const fam = st.fam === 'all' || FAMS.includes(st.fam) ? st.fam : 'all';
    const val = x => fam === 'all' ? x.total : (x.families[fam] || 0);
    const byDay = new Map(days.map(x => [x.day, x]));
    const totals = HB.family_totals || {};
    const firstT = utc(HB.first_day), lastT = utc(HB.last_day);
    const dowOf = t => (new Date(t).getUTCDay() + 6) % 7;
    const MINW = 14;
    let endT = lastT + (6 - dowOf(lastT)) * DAY;
    let startT = firstT - dowOf(firstT) * DAY;
    const weeks = Math.max(MINW, Math.round((endT - startT) / DAY / 7) + 1);
    startT = endT - (weeks * 7 - 1) * DAY;
    const nonzero = days.map(val).filter(v => v > 0).sort((a, b) => a - b);
    const q = f => nonzero.length ? nonzero[Math.min(nonzero.length - 1, Math.floor(f * nonzero.length))] : 0;
    const cuts = [q(0), q(.25), q(.5), q(.75)];
    const level = v => v <= 0 ? 0 : v >= cuts[3] ? 4 : v >= cuts[2] ? 3 : v >= cuts[1] ? 2 : 1;
    const C = 30, G = 5, LX = 34, TY = 20, W = LX + weeks * (C + G), Hh = TY + 7 * (C + G) + 4;
    let cells = '', months = '', lastM = -1;
    for (let w = 0; w < weeks; w++) {
      const wt = startT + w * 7 * DAY, mo = new Date(wt).getUTCMonth();
      if (mo !== lastM) { months += `<text class="axis" x="${LX + w * (C + G)}" y="12">${MON[mo]}</text>`; lastM = mo; }
      for (let r = 0; r < 7; r++) {
        const t = wt + r * DAY, dy = iso(t), x = byDay.get(dy), v = x ? val(x) : 0, inRange = t >= firstT && t <= lastT;
        const f = v ? `var(--seq-${level(v)})` : (inRange ? 'var(--raised)' : 'none');
        cells += `<rect class="cell${st.day === dy ? ' on' : ''}" data-day="${dy}" x="${LX + w * (C + G)}" y="${TY + r * (C + G)}" width="${C}" height="${C}" rx="3" style="fill:${f}" ${inRange ? '' : 'stroke="var(--hair)" stroke-dasharray="2 3"'}${inRange ? ` tabindex="0" aria-label="${dlabY(dy)}: ${fmt(v)} events"` : ''}/>`;
      }
    }
    const dows = [0, 2, 4].map(r => `<text class="axis" x="0" y="${TY + r * (C + G) + C - 6}">${DOW[r]}</text>`).join('');
    const svg = `<svg width="${W}" height="${Hh}" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Events per day">${months}${dows}${cells}</svg>`;
    const busiest = days.reduce((a, x) => val(x) > val(a) ? x : a, days[0]);
    const lastActive = days.filter(x => val(x) > 0).pop();
    const what = fam === 'all' ? 'events' : famLabel(fam).toLowerCase() + ' events';
    const lead = val(busiest) ? `The busiest day was ${dlab(busiest.day)}, with ${fmt(val(busiest))} ${what}. Last activity: ${dlab(lastActive.day)}.` : `No ${what} yet.`;
    const chips = ['all', ...FAMS].map(f => {
      const n = f === 'all' ? HB.total : (totals[f] || 0);
      return `<button class="chip" data-fam="${f}" aria-pressed="${f === fam}" ${n ? '' : 'disabled'}>${f === 'all' ? 'All' : famLabel(f)} <span class="n">${fmt(n)}</span></button>`;
    }).join('');
    const sd = byDay.get(st.day) || lastActive;
    const detail = sd ? `<section class="card lv-day">${H.header({ title: dlabY(sd.day), sub: `<span class="meta">${plural(sd.total, 'event', 'events')}</span>` })}
      ${FAMS.filter(f => sd.families[f]).map(f => `<div class="lv-fam"><span>${famLabel(f)}</span><span class="tr"><i style="width:${Math.round(100 * sd.families[f] / sd.total)}%"></i></span><span class="v">${fmt(sd.families[f])}</span></div>`).join('')}</section>` : '';
    const legend = `<div class="lv-legend"><span>Fewer</span>${[0, 1, 2, 3, 4].map(i => `<span><i style="background:${i ? `var(--seq-${i})` : 'var(--raised)'};margin:0"></i></span>`).join('')}<span>More</span></div>`;
    const body = `<div class="lv-hb"><div class="card lv-card"><div class="lv-hb-head" role="group" aria-label="Family">${chips}</div><div class="lv-hb-wrap">${svg}</div>${legend}</div>${detail}</div>`;
    return { lead, info, body };
  }

  /* ---------------- render ---------------- */
  function render() {
    const V = ({ river, horizon, beat })[st.tab]();
    main.innerHTML = `<section style="padding:20px 0 0">
      ${H.header({ kicker: `Living review · ${H.term('protocol')}`, title: 'Living review', level: 1, infoHtml: V.info })}
      <p class="lead lv-lead">${V.lead}</p></section>
      <div class="lv-tabs"><div class="seg" role="tablist" aria-label="View">${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-pressed="${k === st.tab}">${l}</button>`).join('')}</div></div>
      <div id="lvBody">${V.body}</div>`;
    main.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => go({ tab: b.dataset.tab === 'river' ? null : b.dataset.tab, day: null, fam: null }));
    main.querySelectorAll('[data-fam]').forEach(b => b.onclick = () => go({ fam: b.dataset.fam === 'all' ? null : b.dataset.fam }));
    main.querySelectorAll('.bar').forEach(g => {
      const pick = () => go({ day: g.dataset.day });
      g.onclick = pick; g.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };
    });
    main.querySelectorAll('rect.cell[tabindex]').forEach(c => {
      const x = HB.days.find(z => z.day === c.dataset.day);
      const split = x ? FAMS.filter(f => x.families[f]).map(f => `${famLabel(f)} ${fmt(x.families[f])}`).join('<br>') : '';
      c.onmousemove = e => H.tipHtml(`<b>${dlabY(c.dataset.day)}</b><br>${x ? plural(x.total, 'event', 'events') + '<br>' + split : 'No events'}`, e);
      c.onmouseleave = () => H.tipHtml('');
      c.onclick = () => go({ day: c.dataset.day });
      c.onkeydown = e => { if (e.key === 'Enter') go({ day: c.dataset.day }); };
    });
  }
  readHash(); render();
  window.addEventListener('hashchange', () => { readHash(); render(); });
  document.addEventListener('hub:theme', render);
});
