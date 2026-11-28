/* Portal "The estate" (P01) — aerial fine-line isometric industrial estate.
   Reads #pt-data JSON emitted by site_portal.py. Zero literal colours, zero external URLs. */
(() => {
  'use strict';

  const COS30 = Math.cos(Math.PI / 6);
  const SIN30 = 0.5;
  const PARCEL_W = 248;
  const PARCEL_D = 162;
  const AVENUE_X = 44;
  const AVENUE_Y = 36;
  const MAX_TRACK_W = 26;
  const MAX_HALL_AREA = 6400;
  const HALL_ASPECT = 1.44;
  const DAYS_WINDOW = 30;
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  const $ = id => document.getElementById(id);
  const fmt = n => (typeof n === 'number' && Number.isFinite(n)) ? n.toLocaleString('en-US') : '—';
  const pct = (a, b) => (b > 0 ? `${(100 * a / b).toFixed(1)}%` : '0%');
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeOutCubic = t => 1 - Math.pow(1 - clamp(t, 0, 1), 3);

  function isoToScreen(wx, wy, wz = 0) {
    return { x: (wx - wy) * COS30, y: (wx + wy) * SIN30 - wz };
  }

  function parseIsoDate(str) {
    const [y, m, d] = str.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }

  function formatIsoDate(dt) {
    return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
  }

  function formatShortDate(iso) {
    if (!iso) return '—';
    const dt = parseIsoDate(iso);
    return `${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]}`;
  }

  function buildDateWindow(endIso, count) {
    const end = parseIsoDate(endIso);
    const out = [];
    for (let i = count - 1; i >= 0; i--) {
      out.push(formatIsoDate(new Date(end.getTime() - i * 86400000)));
    }
    return out;
  }

  function readToken(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function readPalette() {
    return {
      bg: readToken('--bg'),
      surface: readToken('--surface'),
      raised: readToken('--raised'),
      line: readToken('--line'),
      hair: readToken('--hair'),
      fg: readToken('--fg'),
      mut: readToken('--mut'),
      dim: readToken('--dim'),
      acc: readToken('--acc'),
      accInk: readToken('--acc-ink'),
      accSoft: readToken('--acc-soft'),
      inc: readToken('--inc'),
      exc: readToken('--exc'),
      core: readToken('--l-core') || readToken('--acc'),
      bench: readToken('--l-benchmark') || readToken('--inc'),
      seq1: readToken('--seq-1') || readToken('--acc-soft'),
      fDisplay: readToken('--f-display') || 'serif',
      fUi: readToken('--f-ui') || 'sans-serif',
      fMono: readToken('--f-mono') || 'monospace'
    };
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function pointInPoly(px, py, pts) {
    let inside = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const xi = pts[i].x, yi = pts[i].y;
      const xj = pts[j].x, yj = pts[j].y;
      const hit = ((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / ((yj - yi) || 1e-9) + xi);
      if (hit) inside = !inside;
    }
    return inside;
  }

  function rectsOverlap(a, b, pad = 4) {
    return !(
      a.x + a.w + pad <= b.x ||
      b.x + b.w + pad <= a.x ||
      a.y + a.h + pad <= b.y ||
      b.y + b.h + pad <= a.y
    );
  }

  function placeLabelBox(idealX, idealY, w, h, placed, viewW, viewH) {
    const offsets = [
      [0, 0],
      [0, 18], [0, -18],
      [0, 36], [0, -36],
      [26, 0], [-26, 0],
      [26, 20], [-26, 20],
      [26, -20], [-26, -20],
      [0, 54], [0, -54],
      [52, 0], [-52, 0]
    ];
    for (const [dx, dy] of offsets) {
      const x = clamp(idealX + dx, 8, Math.max(8, viewW - w - 8));
      const y = clamp(idealY + dy, 8, Math.max(8, viewH - h - 8));
      const cand = { x, y, w, h };
      if (!placed.some(r => rectsOverlap(cand, r))) {
        placed.push(cand);
        return cand;
      }
    }
    const fallback = {
      x: clamp(idealX, 8, Math.max(8, viewW - w - 8)),
      y: clamp(idealY, 8, Math.max(8, viewH - h - 8)),
      w,
      h
    };
    placed.push(fallback);
    return fallback;
  }

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const state = {
    palette: readPalette(),
    stillPlan: reducedMotion.matches,
    projects: [],
    days30: [],
    estateDaily30: [],
    estateMaxDaily: 1,
    globalPeakDaily: 1,
    maxIncluded: 1,
    parcels: [],
    emptyPlot: null,
    loadingDock: null,
    bounds: { minX: -200, maxX: 200, minY: -150, maxY: 150 },
    hitRegions: [],
    reservedRects: [],
    cam: { x: 0, y: 0, zoom: 1 },
    camFrom: null,
    camTo: null,
    camAnimStart: 0,
    camAnimDur: 0,
    dragging: false,
    dragStart: null,
    dragMoved: false,
    hovered: null,
    selectedId: null,
    dayFloat: 29,
    dayIndex: 29,
    playing: !reducedMotion.matches,
    lastFrameTs: 0,
    puffs: [],
    viewW: 1200,
    viewH: 560,
    dpr: Math.min(window.devicePixelRatio || 1, 2)
  };

  function loadData() {
    const el = $('pt-data');
    if (!el) return false;
    let payload;
    try {
      payload = JSON.parse(el.textContent || '{}');
    } catch (_) {
      return false;
    }
    const raw = Array.isArray(payload.projects) ? payload.projects : [];
    if (raw.length === 0) return false;

    const endDates = raw.map(r => r.activity_end).filter(Boolean).sort();
    const endIso = endDates[endDates.length - 1] || formatIsoDate(new Date());
    state.days30 = buildDateWindow(endIso, DAYS_WINDOW);

    state.projects = raw.map((r, idx) => {
      const f = r.funnel || { found: 0, screened: 0, included: 0 };
      const act = Array.isArray(r.activity) ? r.activity : [];
      const daily30 = new Array(DAYS_WINDOW).fill(0);
      if (act.length > 0 && r.activity_end) {
        const projDates = buildDateWindow(r.activity_end, act.length);
        const lookup = new Map(projDates.map((iso, i) => [iso, act[i] || 0]));
        for (let i = 0; i < DAYS_WINDOW; i++) {
          daily30[i] = lookup.get(state.days30[i]) || 0;
        }
      }
      const total30 = daily30.reduce((a, b) => a + b, 0);
      let peak30 = 0;
      let busiestIndex = DAYS_WINDOW - 1;
      for (let i = 0; i < DAYS_WINDOW; i++) {
        if (daily30[i] >= peak30 && daily30[i] > 0) {
          peak30 = daily30[i];
          busiestIndex = i;
        }
      }
      return {
        id: r.slug,
        slug: r.slug,
        title: r.title || r.slug,
        lotNumber: idx + 1,
        hubUrl: r.hub_url || `/p/${encodeURIComponent(r.slug)}/ui/`,
        classicUrl: r.classic_url || `/p/${encodeURIComponent(r.slug)}/`,
        funnel: {
          found: f.found || 0,
          screened: f.screened || 0,
          included: f.included || 0
        },
        built: r.built || 0,
        stale: typeof r.stale === 'number' ? r.stale : 0,
        hubReady: Boolean(r.hub_ready),
        building: Boolean(r.building),
        eventsTotal: r.events || 0,
        daily30,
        total30,
        peak30,
        busiestIndex,
        busiestLabel: formatShortDate(state.days30[busiestIndex]),
        accentTokenKey: idx % 2 === 0 ? 'acc' : 'bench'
      };
    });

    state.estateDaily30 = state.days30.map((_, di) =>
      state.projects.reduce((acc, p) => acc + p.daily30[di], 0)
    );
    state.estateMaxDaily = Math.max(1, ...state.estateDaily30);
    state.globalPeakDaily = Math.max(1, ...state.projects.map(p => p.peak30));
    state.maxIncluded = Math.max(1, ...state.projects.map(p => p.funnel.included));

    const firstActive = state.estateDaily30.findIndex(v => v > 0);
    if (state.stillPlan) {
      let best = DAYS_WINDOW - 1;
      for (let i = 0; i < DAYS_WINDOW; i++) {
        if (state.estateDaily30[i] >= state.estateDaily30[best]) best = i;
      }
      state.dayIndex = best;
      state.dayFloat = best;
    } else {
      const startD = firstActive >= 0 ? firstActive : DAYS_WINDOW - 1;
      state.dayIndex = startD;
      state.dayFloat = startD;
    }
    return true;
  }

  function computeMasterplan() {
    const n = state.projects.length;
    const cols = n === 1 ? 1 : (n <= 4 ? 2 : (n <= 9 ? 3 : 4));
    const rows = Math.ceil(n / cols);
    const stepX = PARCEL_W + AVENUE_X;
    const stepY = PARCEL_D + AVENUE_Y;

    state.parcels = state.projects.map((proj, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x0 = col * stepX;
      const y0 = row * stepY;

      const inc = proj.funnel.included;
      let hallW, hallD;
      if (inc > 0) {
        const area = MAX_HALL_AREA * (inc / state.maxIncluded);
        hallW = Math.sqrt(area * HALL_ASPECT);
        hallD = Math.sqrt(area / HALL_ASPECT);
      } else {
        hallW = 24;
        hallD = 18;
      }
      const hallH = inc > 0 ? clamp(24 + Math.sqrt(inc) * 0.95, 26, 48) : 12;
      const refW = Math.sqrt(MAX_HALL_AREA * HALL_ASPECT);
      const refD = Math.sqrt(MAX_HALL_AREA / HALL_ASPECT);

      const fnd = Math.max(1, proj.funnel.found);
      const wFound = MAX_TRACK_W;
      const wScreened = Math.max(3, MAX_TRACK_W * (proj.funnel.screened / fnd));
      const wIncluded = Math.max(2.2, MAX_TRACK_W * (proj.funnel.included / fnd));

      const midY = y0 + PARCEL_D * 0.5;
      const silo = { x: x0 + 30, y: midY, r: 16, h: clamp(26 + Math.log10(fnd + 1) * 7, 26, 52) };
      const shed = { x: x0 + 96, y: midY, w: 30, d: 34, h: 20 };
      const hallCenterX = x0 + 184;
      const hallCenterY = midY;
      const hall = {
        cx: hallCenterX,
        cy: hallCenterY,
        x: hallCenterX - hallW / 2,
        y: hallCenterY - hallD / 2,
        w: hallW,
        d: hallD,
        h: hallH,
        refW,
        refD
      };
      const chimney = {
        x: hall.x + hall.w - 11,
        y: hall.y + 10,
        baseZ: hall.h,
        h: 34,
        rBot: 4.8,
        rTop: 3.1
      };

      return { id: proj.id, proj, col, row, x0, y0, w: PARCEL_W, d: PARCEL_D, midY, silo, shed, hall, chimney, tracks: { wFound, wScreened, wIncluded } };
    });

    if (n === 1) {
      state.loadingDock = { id: 'loading-dock', x0: 0, y0: stepY, w: 170, d: 96 };
      state.emptyPlot = { id: 'empty-plot', x0: stepX, y0: 0, w: 176, d: 108 };
    } else if (n === 2) {
      state.loadingDock = { id: 'loading-dock', x0: 24, y0: stepY, w: 196, d: 96 };
      state.emptyPlot = { id: 'empty-plot', x0: stepX + 20, y0: stepY, w: 204, d: 100 };
    } else {
      const frontY = rows * stepY;
      state.loadingDock = { id: 'loading-dock', x0: 0, y0: frontY, w: 210, d: 96 };
      state.emptyPlot = { id: 'empty-plot', x0: stepX, y0: frontY, w: 214, d: 100 };
    }

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    const includeRect = (x0, y0, w, d, topZ = 56, padBot = 22) => {
      const corners = [
        isoToScreen(x0, y0, 0),
        isoToScreen(x0 + w, y0, 0),
        isoToScreen(x0 + w, y0 + d, 0),
        isoToScreen(x0, y0 + d, 0),
        isoToScreen(x0 + w, y0, topZ),
        isoToScreen(x0, y0, topZ)
      ];
      for (const p of corners) {
        if (p.x < minX) minX = p.x;
        if (p.x > maxX) maxX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.y + padBot > maxY) maxY = p.y + padBot;
      }
    };

    for (const p of state.parcels) {
      includeRect(p.x0, p.y0, p.w, p.d, p.hall.h + p.chimney.h + 8, 20);
    }
    includeRect(state.loadingDock.x0, state.loadingDock.y0, state.loadingDock.w, state.loadingDock.d, 24, 14);
    includeRect(state.emptyPlot.x0, state.emptyPlot.y0, state.emptyPlot.w, state.emptyPlot.d, 24, 14);
    state.bounds = { minX, maxX, minY, maxY };
  }

  function getFitCamera() {
    const bw = Math.max(100, state.bounds.maxX - state.bounds.minX);
    const bh = Math.max(100, state.bounds.maxY - state.bounds.minY);
    const zX = (state.viewW - 28) / bw;
    const zY = (state.viewH - 24) / bh;
    const zoom = clamp(Math.min(zX, zY), 0.36, 2.35);
    return {
      x: (state.bounds.minX + state.bounds.maxX) * 0.5,
      y: (state.bounds.minY + state.bounds.maxY) * 0.5,
      zoom
    };
  }

  function animateCameraTo(target, durationMs = 480) {
    if (state.stillPlan || durationMs <= 0) {
      state.cam = { ...target };
      state.camFrom = null;
      state.camTo = null;
      syncHotspots();
      renderFrame(performance.now());
      return;
    }
    state.camFrom = { ...state.cam };
    state.camTo = { ...target };
    state.camAnimStart = performance.now();
    state.camAnimDur = durationMs;
  }

  function worldToCanvas(wx, wy, wz = 0) {
    const p = isoToScreen(wx, wy, wz);
    return {
      x: state.viewW * 0.5 + (p.x - state.cam.x) * state.cam.zoom,
      y: state.viewH * 0.5 + (p.y - state.cam.y) * state.cam.zoom
    };
  }

  function drawPoly(ctx, pts, fill, stroke, lineWidth = 1, dash = null) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.closePath();
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      if (dash) ctx.setLineDash(dash);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lineWidth;
      ctx.stroke();
      if (dash) ctx.setLineDash([]);
    }
  }

  function drawIsoBox(ctx, x, y, z, w, d, h, colors, lineWidth = 1) {
    const p100 = worldToCanvas(x + w, y, z);
    const p110 = worldToCanvas(x + w, y + d, z);
    const p010 = worldToCanvas(x, y + d, z);
    const p001 = worldToCanvas(x, y, z + h);
    const p101 = worldToCanvas(x + w, y, z + h);
    const p111 = worldToCanvas(x + w, y + d, z + h);
    const p011 = worldToCanvas(x, y + d, z + h);
    drawPoly(ctx, [p010, p110, p111, p011], colors.left, colors.stroke, lineWidth);
    drawPoly(ctx, [p100, p110, p111, p101], colors.right, colors.stroke, lineWidth);
    drawPoly(ctx, [p001, p101, p111, p011], colors.top, colors.stroke, lineWidth);
  }

  function drawIsoCylinder(ctx, cx, cy, z0, r, h, colors, lineWidth = 1) {
    const segs = 16;
    const bot = [], top = [];
    for (let i = 0; i < segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      bot.push(worldToCanvas(cx + Math.cos(a) * r, cy + Math.sin(a) * r, z0));
      top.push(worldToCanvas(cx + Math.cos(a) * r, cy + Math.sin(a) * r, z0 + h));
    }
    let minIdx = 0, maxIdx = 0;
    for (let i = 1; i < segs; i++) {
      if (bot[i].x < bot[minIdx].x) minIdx = i;
      if (bot[i].x > bot[maxIdx].x) maxIdx = i;
    }
    const walk = dir => {
      const list = [];
      let cur = minIdx;
      for (let k = 0; k <= segs; k++) {
        list.push(cur);
        if (cur === maxIdx) break;
        cur = (cur + dir + segs) % segs;
      }
      return list;
    };
    const pA = walk(1), pB = walk(-1);
    const avgY = l => l.reduce((s, i) => s + bot[i].y, 0) / l.length;
    const front = avgY(pA) >= avgY(pB) ? pA : pB;
    drawPoly(ctx, [...front.map(i => bot[i]), ...front.slice().reverse().map(i => top[i])], colors.side, colors.stroke, lineWidth);
    drawPoly(ctx, top, colors.top, colors.stroke, lineWidth);
    return { topCenter: worldToCanvas(cx, cy, z0 + h) };
  }

  function drawIsoTaperedStack(ctx, cx, cy, z0, rBot, rTop, h, colors) {
    const segs = 12;
    const bot = [], top = [];
    for (let i = 0; i < segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      bot.push(worldToCanvas(cx + Math.cos(a) * rBot, cy + Math.sin(a) * rBot, z0));
      top.push(worldToCanvas(cx + Math.cos(a) * rTop, cy + Math.sin(a) * rTop, z0 + h));
    }
    let minIdx = 0, maxIdx = 0;
    for (let i = 1; i < segs; i++) {
      if (bot[i].x < bot[minIdx].x) minIdx = i;
      if (bot[i].x > bot[maxIdx].x) maxIdx = i;
    }
    const walk = dir => {
      const list = [];
      let cur = minIdx;
      for (let k = 0; k <= segs; k++) {
        list.push(cur);
        if (cur === maxIdx) break;
        cur = (cur + dir + segs) % segs;
      }
      return list;
    };
    const pA = walk(1), pB = walk(-1);
    const avgY = l => l.reduce((s, i) => s + bot[i].y, 0) / l.length;
    const front = avgY(pA) >= avgY(pB) ? pA : pB;
    drawPoly(ctx, [...front.map(i => bot[i]), ...front.slice().reverse().map(i => top[i])], colors.side, colors.stroke, 1);

    const bandZ = z0 + h * 0.82;
    const bandR = lerp(rBot, rTop, 0.82) * 1.04;
    ctx.beginPath();
    front.forEach((idx, k) => {
      const a = (idx / segs) * Math.PI * 2;
      const pt = worldToCanvas(cx + Math.cos(a) * bandR, cy + Math.sin(a) * bandR, bandZ);
      if (k === 0) ctx.moveTo(pt.x, pt.y);
      else ctx.lineTo(pt.x, pt.y);
    });
    ctx.strokeStyle = colors.band;
    ctx.lineWidth = Math.max(1.5, 2.2 * state.cam.zoom);
    ctx.stroke();

    drawPoly(ctx, top, colors.top, colors.stroke, 1);
    return worldToCanvas(cx, cy, z0 + h);
  }

  function drawGroundGrid(ctx, pal) {
    const step = 40;
    ctx.save();
    ctx.strokeStyle = pal.hair;
    ctx.lineWidth = 0.75;
    ctx.globalAlpha = 0.65;
    ctx.beginPath();
    for (let x = -420; x <= 1480; x += step) {
      const a = worldToCanvas(x, -420, 0), b = worldToCanvas(x, 1480, 0);
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    }
    for (let y = -420; y <= 1480; y += step) {
      const a = worldToCanvas(-420, y, 0), b = worldToCanvas(1480, y, 0);
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawEstateAvenues(ctx, pal) {
    const dock = state.loadingDock;
    const dockExit = { x: dock.x0 + dock.w * 0.5, y: dock.y0 };
    const spineY = dock.y0 - AVENUE_Y * 0.5;
    ctx.save();
    ctx.strokeStyle = pal.line;
    ctx.lineWidth = Math.max(1, 1.3 * state.cam.zoom);
    ctx.setLineDash([5, 4]);
    for (const p of state.parcels) {
      const pts = [
        worldToCanvas(dockExit.x, dockExit.y, 0.5),
        worldToCanvas(dockExit.x, spineY, 0.5),
        worldToCanvas(p.silo.x, spineY, 0.5),
        worldToCanvas(p.silo.x, p.y0 + p.d, 0.5)
      ];
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.restore();
  }

  function drawRailTies(ctx, xA, xB, cy, width, strokeColor) {
    ctx.save();
    ctx.strokeStyle = strokeColor;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = Math.max(0.6, 0.8 * state.cam.zoom);
    ctx.beginPath();
    for (let x = xA + 4; x < xB - 2; x += 6) {
      const a = worldToCanvas(x, cy - width / 2, 1.7);
      const b = worldToCanvas(x, cy + width / 2, 1.7);
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawHonestConveyor(ctx, parcel, pal, accent, now) {
    const { silo, shed, hall, tracks, proj } = parcel;
    const y = parcel.midY;
    const xSiloOut = silo.x + silo.r * 0.75;
    const xShedIn = shed.x - shed.w / 2;
    const xShedOut = shed.x + shed.w / 2;
    const xTaperMid = lerp(xShedOut, hall.x, 0.52);
    const xHallIn = hall.x;

    drawPoly(ctx, [
      worldToCanvas(xSiloOut, y - tracks.wFound / 2, 1.5),
      worldToCanvas(xShedIn, y - tracks.wFound / 2, 1.5),
      worldToCanvas(xShedIn, y + tracks.wFound / 2, 1.5),
      worldToCanvas(xSiloOut, y + tracks.wFound / 2, 1.5)
    ], pal.raised, pal.mut, 0.9);
    drawRailTies(ctx, xSiloOut, xShedIn, y, tracks.wFound, pal.dim);

    drawPoly(ctx, [
      worldToCanvas(xShedOut, y - tracks.wScreened / 2, 1.5),
      worldToCanvas(xTaperMid, y - tracks.wScreened / 2, 1.5),
      worldToCanvas(xTaperMid, y + tracks.wScreened / 2, 1.5),
      worldToCanvas(xShedOut, y + tracks.wScreened / 2, 1.5)
    ], pal.seq1, accent, 0.9);
    drawRailTies(ctx, xShedOut, xTaperMid, y, tracks.wScreened, accent);

    const spurPts = [
      worldToCanvas(xTaperMid - 4, y + tracks.wScreened * 0.35, 1.2),
      worldToCanvas(xTaperMid + 14, parcel.y0 + parcel.d - 16, 1.2)
    ];
    ctx.save();
    ctx.strokeStyle = pal.dim;
    ctx.lineWidth = Math.max(0.8, 1.1 * state.cam.zoom);
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(spurPts[0].x, spurPts[0].y);
    ctx.lineTo(spurPts[1].x, spurPts[1].y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    drawPoly(ctx, [
      worldToCanvas(xTaperMid, y - tracks.wIncluded / 2, 1.5),
      worldToCanvas(xHallIn, y - tracks.wIncluded / 2, 1.5),
      worldToCanvas(xHallIn, y + tracks.wIncluded / 2, 1.5),
      worldToCanvas(xTaperMid, y + tracks.wIncluded / 2, 1.5)
    ], accent, accent, 1);

    const phase = state.stillPlan ? 0.35 : ((now * 0.00018) % 1);
    const drawCar = (xA, xB, width, t, col) => {
      if (xB - xA < 8) return;
      const cx = lerp(xA + 4, xB - 4, t);
      const cw = Math.min(6, Math.max(3, (xB - xA) * 0.14));
      const cd = Math.max(2.2, Math.min(width * 0.65, 10));
      drawIsoBox(ctx, cx - cw / 2, y - cd / 2, 2, cw, cd, 3.2, {
        top: col, left: pal.raised, right: pal.surface, stroke: col
      }, 0.75);
    };
    drawCar(xSiloOut, xShedIn, tracks.wFound, phase, pal.mut);
    drawCar(xShedOut, xTaperMid, tracks.wScreened, (phase + 0.25) % 1, accent);
    drawCar(xTaperMid, xHallIn, tracks.wIncluded, (phase + 0.65) % 1, pal.acc);

    state.hitRegions.push({
      kind: 'conveyor',
      parcelId: parcel.id,
      poly: [
        worldToCanvas(xSiloOut, y - tracks.wFound * 0.65, 3),
        worldToCanvas(xHallIn, y - tracks.wFound * 0.65, 3),
        worldToCanvas(xHallIn, y + tracks.wFound * 0.65, 0),
        worldToCanvas(xSiloOut, y + tracks.wFound * 0.65, 0)
      ],
      tip: {
        kicker: 'CONVEYOR · HONEST WIDTH',
        title: `${fmt(proj.funnel.found)} → ${fmt(proj.funnel.screened)} → ${fmt(proj.funnel.included)}`,
        meta: `100% found → ${pct(proj.funnel.screened, proj.funnel.found)} screened → ${pct(proj.funnel.included, proj.funnel.found)} included`
      }
    });
  }

  function drawSortingShed(ctx, shed, pal, accent, isSelected) {
    const x = shed.x - shed.w / 2;
    const y = shed.y - shed.d / 2;
    const stroke = isSelected ? pal.acc : pal.mut;
    drawIsoBox(ctx, x, y, 0, shed.w, shed.d, shed.h, {
      top: pal.surface, left: pal.raised, right: pal.surface, stroke
    }, 0.95);
    const bayW = shed.w / 2;
    for (let b = 0; b < 2; b++) {
      const bx = x + b * bayW;
      const p0 = worldToCanvas(bx, y, shed.h);
      const p1 = worldToCanvas(bx + bayW * 0.35, y, shed.h + 7);
      const p2 = worldToCanvas(bx + bayW, y, shed.h);
      const q0 = worldToCanvas(bx, y + shed.d, shed.h);
      const q1 = worldToCanvas(bx + bayW * 0.35, y + shed.d, shed.h + 7);
      const q2 = worldToCanvas(bx + bayW, y + shed.d, shed.h);
      drawPoly(ctx, [p1, q1, q2, p2], pal.raised, stroke, 0.85);
      drawPoly(ctx, [q0, q1, q2], pal.surface, stroke, 0.85);
      drawPoly(ctx, [p0, p1, q1, q0], pal.accSoft, accent, 0.7);
    }
  }

  function drawFactoryHall(ctx, parcel, pal, accent, isSelected, isHovered) {
    const { hall, proj } = parcel;
    const stroke = isSelected ? pal.acc : (isHovered ? accent : pal.fg);

    drawIsoBox(ctx, hall.x, hall.y, 0, hall.w, hall.d, hall.h, {
      top: pal.surface, left: pal.raised, right: pal.surface, stroke
    }, isSelected ? 1.5 : 1.05);

    const bays = hall.w >= 80 ? 3 : 2;
    const bayW = hall.w / bays;
    const ridgeH = clamp(hall.h * 0.26, 7, 13);
    for (let b = 0; b < bays; b++) {
      const bx = hall.x + b * bayW;
      const p0 = worldToCanvas(bx, hall.y, hall.h);
      const p1 = worldToCanvas(bx + bayW * 0.28, hall.y, hall.h + ridgeH);
      const p2 = worldToCanvas(bx + bayW, hall.y, hall.h);
      const q0 = worldToCanvas(bx, hall.y + hall.d, hall.h);
      const q1 = worldToCanvas(bx + bayW * 0.28, hall.y + hall.d, hall.h + ridgeH);
      const q2 = worldToCanvas(bx + bayW, hall.y + hall.d, hall.h);
      drawPoly(ctx, [p1, q1, q2, p2], pal.raised, stroke, 0.9);
      drawPoly(ctx, [p0, p1, q1, q0], pal.accSoft, accent, 0.7);
      drawPoly(ctx, [q0, q1, q2], pal.raised, stroke, 0.9);
    }

    // Clerestory windows reflect real stale pages count
    const winCount = clamp(Math.round(hall.w / 14), 3, 7);
    const padX = hall.w * 0.1;
    const usableW = hall.w - padX * 2;
    const winW = (usableW / winCount) * 0.64;
    const winGap = usableW / winCount;
    const winZ0 = hall.h * 0.36;
    const winZ1 = hall.h * 0.72;
    const unlitCount = !proj.hubReady
      ? winCount
      : (proj.stale > 0 ? Math.min(winCount, Math.max(1, Math.ceil((proj.stale / Math.max(1, proj.built)) * winCount))) : 0);

    for (let i = 0; i < winCount; i++) {
      const wx0 = hall.x + padX + i * winGap;
      const wx1 = wx0 + winW;
      const wPts = [
        worldToCanvas(wx0, hall.y + hall.d + 0.2, winZ0),
        worldToCanvas(wx1, hall.y + hall.d + 0.2, winZ0),
        worldToCanvas(wx1, hall.y + hall.d + 0.2, winZ1),
        worldToCanvas(wx0, hall.y + hall.d + 0.2, winZ1)
      ];
      if (!proj.hubReady) {
        drawPoly(ctx, wPts, pal.bg, pal.dim, 0.8);
      } else if (i < unlitCount) {
        drawPoly(ctx, wPts, pal.bg, pal.exc, 0.9);
      } else {
        drawPoly(ctx, wPts, pal.accSoft, pal.inc, 0.9);
      }
    }

    const doorD = Math.min(18, hall.d * 0.34);
    const doorH = Math.min(18, hall.h * 0.55);
    const doorY0 = hall.cy - doorD / 2;
    drawPoly(ctx, [
      worldToCanvas(hall.x + hall.w + 0.2, doorY0, 0),
      worldToCanvas(hall.x + hall.w + 0.2, doorY0 + doorD, 0),
      worldToCanvas(hall.x + hall.w + 0.2, doorY0 + doorD, doorH),
      worldToCanvas(hall.x + hall.w + 0.2, doorY0, doorH)
    ], isSelected ? pal.accSoft : pal.bg, isSelected ? pal.acc : pal.mut, 1);

    const staleText = !proj.hubReady ? 'hub not built' : (proj.stale > 0 ? `${proj.stale} to rebuild` : 'up to date');
    state.hitRegions.push({
      kind: 'hall',
      parcelId: parcel.id,
      poly: [
        worldToCanvas(hall.x, hall.y, hall.h + ridgeH),
        worldToCanvas(hall.x + hall.w, hall.y, hall.h + ridgeH),
        worldToCanvas(hall.x + hall.w, hall.y + hall.d, 0),
        worldToCanvas(hall.x, hall.y + hall.d, 0)
      ],
      tip: {
        kicker: 'FACTORY HALL · CLICK TO FLY IN',
        title: `${proj.title} (${fmt(proj.funnel.included)} included)`,
        meta: `${fmt(proj.built)} pages built · ${staleText}`
      }
    });
  }

  function drawRoofSign(ctx, parcel, pal, now) {
    const { hall, proj } = parcel;
    const zoom = state.cam.zoom;
    const lit = proj.built > 0;
    const signZ0 = hall.h + 11;
    const signZ1 = signZ0 + 13;
    const sx0 = hall.x + hall.w * 0.14;
    const sx1 = hall.x + hall.w * 0.84;
    const sy = hall.y + hall.d * 0.72;

    const leg1B = worldToCanvas(sx0 + 4, sy, hall.h);
    const leg1T = worldToCanvas(sx0 + 4, sy, signZ0);
    const leg2B = worldToCanvas(sx1 - 4, sy, hall.h);
    const leg2T = worldToCanvas(sx1 - 4, sy, signZ0);
    ctx.strokeStyle = pal.mut;
    ctx.lineWidth = Math.max(0.8, 1 * zoom);
    ctx.beginPath();
    ctx.moveTo(leg1B.x, leg1B.y); ctx.lineTo(leg1T.x, leg1T.y);
    ctx.moveTo(leg2B.x, leg2B.y); ctx.lineTo(leg2T.x, leg2T.y);
    ctx.stroke();

    const pBL = worldToCanvas(sx0, sy, signZ0);
    const pBR = worldToCanvas(sx1, sy, signZ0);
    const pTR = worldToCanvas(sx1, sy, signZ1);
    const pTL = worldToCanvas(sx0, sy, signZ1);
    const pulse = (!state.stillPlan && lit) ? (0.88 + 0.12 * Math.sin(now * 0.0028)) : 1;

    ctx.save();
    if (lit) {
      ctx.globalAlpha = pulse;
      drawPoly(ctx, [pBL, pBR, pTR, pTL], pal.acc, pal.acc, 1.2);
    } else {
      drawPoly(ctx, [pBL, pBR, pTR, pTL], pal.bg, pal.dim, 1, [2, 2]);
    }
    ctx.restore();

    if (zoom >= 0.5) {
      const midX = (pBL.x + pTR.x) * 0.5;
      const midY = (pBL.y + pTR.y) * 0.5;
      const angle = Math.atan2(pBR.y - pBL.y, pBR.x - pBL.x);
      ctx.save();
      ctx.translate(midX, midY);
      ctx.rotate(angle);
      const fs = clamp(9.5 * zoom, 7.5, 13);
      ctx.font = `600 ${fs}px ${pal.fMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = lit ? pal.accInk : pal.dim;
      ctx.fillText(lit ? `+ ${fmt(proj.built)} PAGES` : `− 0 PAGES`, 0, 0.5);
      ctx.restore();
    }
  }

  function drawProjectCompound(ctx, parcel, pal, now) {
    const { proj, x0, y0, w, d, silo, shed, hall, chimney } = parcel;
    const isSelected = state.selectedId === parcel.id;
    const isHovered = state.hovered && state.hovered.parcelId === parcel.id;
    const accent = proj.accentTokenKey === 'acc' ? pal.acc : pal.bench;

    const slabPts = [
      worldToCanvas(x0, y0, 0),
      worldToCanvas(x0 + w, y0, 0),
      worldToCanvas(x0 + w, y0 + d, 0),
      worldToCanvas(x0, y0 + d, 0)
    ];
    drawPoly(ctx, slabPts, pal.surface, isSelected ? pal.acc : (isHovered ? accent : pal.line), isSelected ? 2 : (isHovered ? 1.5 : 1));

    state.hitRegions.push({
      kind: 'building',
      parcelId: parcel.id,
      poly: slabPts,
      tip: {
        kicker: `LOT ${String(proj.lotNumber).padStart(2, '0')} · ${proj.slug}`,
        title: proj.title,
        meta: `${fmt(proj.funnel.included)} included · ${fmt(proj.built)} pages built · click to fly in`
      }
    });

    if (proj.funnel.included < state.maxIncluded) {
      const refPts = [
        worldToCanvas(hall.cx - hall.refW / 2, hall.cy - hall.refD / 2, 0.4),
        worldToCanvas(hall.cx + hall.refW / 2, hall.cy - hall.refD / 2, 0.4),
        worldToCanvas(hall.cx + hall.refW / 2, hall.cy + hall.refD / 2, 0.4),
        worldToCanvas(hall.cx - hall.refW / 2, hall.cy + hall.refD / 2, 0.4)
      ];
      ctx.save();
      ctx.globalAlpha = 0.5;
      drawPoly(ctx, refPts, null, pal.dim, 0.85, [3, 3]);
      ctx.restore();
    }

    drawHonestConveyor(ctx, parcel, pal, accent, now);

    const siloTop = drawIsoCylinder(ctx, silo.x, silo.y, 0, silo.r, silo.h, {
      side: pal.raised, top: pal.surface, stroke: isSelected ? pal.acc : pal.mut
    }, 1);
    const capApex = worldToCanvas(silo.x, silo.y, silo.h + 11);
    const capL = worldToCanvas(silo.x - silo.r * 0.72, silo.y + silo.r * 0.72, silo.h);
    const capR = worldToCanvas(silo.x + silo.r * 0.72, silo.y - silo.r * 0.72, silo.h);
    drawPoly(ctx, [capL, capApex, capR], pal.raised, pal.mut, 0.9);

    drawSortingShed(ctx, shed, pal, accent, isSelected);
    drawFactoryHall(ctx, parcel, pal, accent, isSelected, isHovered);
    drawRoofSign(ctx, parcel, pal, now);

    const crownPt = drawIsoTaperedStack(ctx, chimney.x, chimney.y, chimney.baseZ, chimney.rBot, chimney.rTop, chimney.h, {
      side: pal.raised, top: pal.bg, stroke: isSelected ? pal.acc : pal.mut, band: accent
    });
    parcel._crownScreen = crownPt;
    parcel._siloTop = siloTop;
    parcel._accent = accent;
  }

  function drawEmptyPlot(ctx, plot, pal) {
    const { x0, y0, w, d } = plot;
    const isSelected = state.selectedId === 'empty-plot';
    const isHovered = state.hovered && state.hovered.kind === 'empty-plot';
    const zoom = state.cam.zoom;
    const pts = [
      worldToCanvas(x0, y0, 0),
      worldToCanvas(x0 + w, y0, 0),
      worldToCanvas(x0 + w, y0 + d, 0),
      worldToCanvas(x0, y0 + d, 0)
    ];
    drawPoly(ctx, pts, isSelected || isHovered ? pal.accSoft : pal.surface, isSelected || isHovered ? pal.acc : pal.dim, isSelected ? 1.8 : 1.1, [6, 5]);

    const sx0 = x0 + w * 0.24, sx1 = x0 + w * 0.78, sy = y0 + d * 0.56;
    const sBL = worldToCanvas(sx0, sy, 12);
    const sBR = worldToCanvas(sx1, sy, 12);
    const sTR = worldToCanvas(sx1, sy, 32);
    const sTL = worldToCanvas(sx0, sy, 32);
    drawPoly(ctx, [sBL, sBR, sTR, sTL], pal.raised, pal.acc, 1.3);

    if (zoom >= 0.45) {
      const mx = (sBL.x + sTR.x) * 0.5, my = (sBL.y + sTR.y) * 0.5;
      const angle = Math.atan2(sBR.y - sBL.y, sBR.x - sBL.x);
      ctx.save();
      ctx.translate(mx, my);
      ctx.rotate(angle);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = pal.acc;
      ctx.font = `600 ${clamp(10 * zoom, 8, 13)}px ${pal.fMono}`;
      ctx.fillText('+ BREAK GROUND', 0, -4 * zoom);
      ctx.fillStyle = pal.fg;
      ctx.font = `500 ${clamp(9 * zoom, 7.5, 11.5)}px ${pal.fUi}`;
      ctx.fillText('New project site', 0, 5.5 * zoom);
      ctx.restore();
      const rw = 120 * zoom, rh = 36 * zoom;
      state.reservedRects.push({ x: mx - rw / 2, y: my - rh / 2, w: rw, h: rh });
    }

    state.hitRegions.push({
      kind: 'empty-plot',
      parcelId: 'empty-plot',
      poly: pts,
      tip: {
        kicker: 'EMPTY PLOT · SITE SIGN',
        title: 'Break ground on a new project',
        meta: 'Click to jump to the New project form'
      }
    });
  }

  function drawLoadingDock(ctx, dock, pal, now) {
    const { x0, y0, w, d } = dock;
    const isSelected = state.selectedId === 'loading-dock';
    const isHovered = state.hovered && state.hovered.kind === 'loading-dock';
    const zoom = state.cam.zoom;
    const pts = [
      worldToCanvas(x0, y0, 0),
      worldToCanvas(x0 + w, y0, 0),
      worldToCanvas(x0 + w, y0 + d, 0),
      worldToCanvas(x0, y0 + d, 0)
    ];
    drawPoly(ctx, pts, pal.surface, isSelected || isHovered ? pal.acc : pal.line, isSelected ? 1.8 : 1.1);
    drawIsoBox(ctx, x0 + 18, y0 + 16, 0, w - 36, 48, 9, {
      top: pal.raised, left: pal.surface, right: pal.bg, stroke: pal.mut
    }, 1);

    const canZ = 28;
    const roofPts = [
      worldToCanvas(x0 + 20, y0 + 18, canZ),
      worldToCanvas(x0 + w - 20, y0 + 18, canZ),
      worldToCanvas(x0 + w - 20, y0 + 62, canZ + 3),
      worldToCanvas(x0 + 20, y0 + 62, canZ + 3)
    ];
    drawPoly(ctx, roofPts, pal.surface, isSelected || isHovered ? pal.acc : pal.fg, 1.1);

    const crateBob = state.stillPlan ? 0 : Math.sin(now * 0.003) * 0.8;
    drawIsoBox(ctx, x0 + 52, y0 + 32, 9 + crateBob, 14, 14, 10, {
      top: pal.acc, left: pal.raised, right: pal.surface, stroke: pal.acc
    }, 0.9);

    if (zoom >= 0.45) {
      const center = worldToCanvas(x0 + w * 0.5, y0 + 40, canZ + 2);
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = pal.acc;
      ctx.font = `600 ${clamp(10 * zoom, 8, 12.5)}px ${pal.fMono}`;
      ctx.fillText('↓ LOADING DOCK · INBOX', center.x, center.y - 3 * zoom);
      ctx.fillStyle = pal.mut;
      ctx.font = `400 ${clamp(8.5 * zoom, 7.5, 11)}px ${pal.fUi}`;
      ctx.fillText('Drop a DOI or click', center.x, center.y + 7 * zoom);
      ctx.restore();
      const rw = 150 * zoom, rh = 34 * zoom;
      state.reservedRects.push({ x: center.x - rw / 2, y: center.y - rh / 2, w: rw, h: rh });
    }

    state.hitRegions.push({
      kind: 'loading-dock',
      parcelId: 'loading-dock',
      poly: pts,
      tip: {
        kicker: 'RECEIVING BAY · LOADING DOCK',
        title: 'Add a paper to any project inbox',
        meta: 'Drop a DOI/arXiv URL anywhere on the estate, or click to jump to Add to inbox'
      }
    });
  }

  function drawAllAnnotations(ctx, pal, zoom) {
    if (zoom < 0.34) return;
    const compact = state.parcels.length > 4 && zoom < 0.85;
    const placed = [...state.reservedRects];

    // 1. Building nameplates (highest priority, collision-avoided)
    for (const parcel of state.parcels) {
      const { proj, x0, y0, w, d, hall } = parcel;
      const isSelected = state.selectedId === parcel.id;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';

      if (compact) {
        const anchor = worldToCanvas(hall.cx, hall.cy + hall.d * 0.62, 0);
        const fs = clamp(9.5 * zoom + 2.5, 8.5, 11);
        const shortName = proj.title.length > 16 ? `${proj.title.slice(0, 15)}…` : proj.title;
        const label = `${shortName} · n=${fmt(proj.funnel.included)}`;
        ctx.font = `500 ${fs}px ${pal.fMono}`;
        const tw = ctx.measureText(label).width + 12;
        const th = fs + 7;
        const box = placeLabelBox(anchor.x - tw / 2, anchor.y, tw, th, placed, state.viewW, state.viewH);

        ctx.fillStyle = pal.surface;
        ctx.strokeStyle = isSelected ? pal.acc : pal.line;
        ctx.lineWidth = isSelected ? 1.5 : 0.95;
        ctx.beginPath();
        ctx.roundRect(box.x, box.y, box.w, box.h, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = pal.fg;
        ctx.fillText(label, box.x + box.w / 2, box.y + 3.5);
      } else {
        const anchor = worldToCanvas(x0 + w * 0.78, y0 + d + 10, 0);
        const titleSize = clamp(13 * zoom, 10.5, 16);
        const subSize = clamp(9.5 * zoom, 8.5, 11.5);
        const staleTag = !proj.hubReady ? 'not built' : (proj.stale > 0 ? `${proj.stale} to rebuild` : 'up to date');
        const subStr = `n = ${fmt(proj.funnel.included)} included · ${fmt(proj.built)} built · ${staleTag}`;

        ctx.font = `500 ${titleSize}px ${pal.fDisplay}`;
        const tw1 = ctx.measureText(proj.title).width;
        ctx.font = `400 ${subSize}px ${pal.fMono}`;
        const tw2 = ctx.measureText(subStr).width;
        const boxW = Math.max(tw1, tw2) + 18;
        const boxH = titleSize + subSize + 13;
        const box = placeLabelBox(anchor.x - boxW / 2, anchor.y - 2, boxW, boxH, placed, state.viewW, state.viewH);

        const corner = worldToCanvas(hall.x + hall.w, hall.y + hall.d, 0);
        ctx.strokeStyle = isSelected ? pal.acc : pal.line;
        ctx.lineWidth = 0.9;
        ctx.beginPath();
        ctx.moveTo(corner.x, corner.y);
        ctx.lineTo(box.x + box.w / 2, box.y);
        ctx.stroke();

        ctx.fillStyle = pal.surface;
        ctx.strokeStyle = isSelected ? pal.acc : pal.line;
        ctx.lineWidth = isSelected ? 1.5 : 1;
        ctx.beginPath();
        ctx.roundRect(box.x, box.y, box.w, box.h, 5);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = pal.fg;
        ctx.font = `500 ${titleSize}px ${pal.fDisplay}`;
        ctx.fillText(proj.title, box.x + box.w / 2, box.y + 4);

        ctx.fillStyle = pal.mut;
        ctx.font = `400 ${subSize}px ${pal.fMono}`;
        ctx.fillText(subStr, box.x + box.w / 2, box.y + titleSize + 7);
      }
      ctx.restore();
    }

    // 2. Busiest day flags (collision-avoided)
    for (const parcel of state.parcels) {
      const { proj } = parcel;
      if (proj.peak30 > 0 && state.dayIndex === proj.busiestIndex && parcel._crownScreen && zoom >= 0.5) {
        const crownPt = parcel._crownScreen;
        const text = `★ PEAK ${proj.busiestLabel} (${fmt(proj.peak30)})`;
        const fs = clamp(9.5 * zoom, 8.5, 11.5);
        ctx.save();
        ctx.font = `600 ${fs}px ${pal.fMono}`;
        const tw = ctx.measureText(text).width + 12;
        const th = fs + 8;
        const box = placeLabelBox(crownPt.x + 12 * zoom, crownPt.y - 18 * zoom - th * 0.6, tw, th, placed, state.viewW, state.viewH);

        ctx.strokeStyle = pal.core;
        ctx.lineWidth = 1.1;
        ctx.beginPath();
        ctx.moveTo(crownPt.x, crownPt.y - 2);
        ctx.lineTo(box.x, box.y + box.h * 0.5);
        ctx.stroke();

        ctx.fillStyle = pal.surface;
        ctx.strokeStyle = pal.core;
        ctx.beginPath();
        ctx.roundRect(box.x, box.y, box.w, box.h, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = pal.core;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, box.x + 6, box.y + box.h * 0.5);
        ctx.restore();
      }
    }

    // 3. Station micro-labels (only when zoomed in enough and non-overlapping)
    if (zoom >= 0.78) {
      const fs = clamp(9.5 * zoom, 8.5, 11);
      ctx.save();
      ctx.font = `500 ${fs}px ${pal.fMono}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const parcel of state.parcels) {
        const { proj } = parcel;
        if (!parcel._siloTop) continue;
        const accent = parcel._accent || pal.acc;
        const items = [
          { pt: parcel._siloTop.topCenter, text: `${fmt(proj.funnel.found)} found`, col: pal.mut },
          { pt: worldToCanvas(parcel.shed.x, parcel.shed.y, parcel.shed.h + 10), text: `${fmt(proj.funnel.screened)} screened`, col: accent }
        ];
        for (const it of items) {
          const tw = ctx.measureText(it.text).width + 6;
          const th = fs + 4;
          const cand = { x: it.pt.x - tw / 2, y: it.pt.y - 22 * zoom - th / 2, w: tw, h: th };
          if (placed.some(r => rectsOverlap(cand, r, 3))) continue;
          placed.push(cand);
          ctx.strokeStyle = it.col;
          ctx.lineWidth = 0.75;
          ctx.beginPath();
          ctx.moveTo(it.pt.x, it.pt.y - 4);
          ctx.lineTo(it.pt.x, cand.y + cand.h);
          ctx.stroke();
          ctx.fillStyle = it.col;
          ctx.fillText(it.text, cand.x + cand.w / 2, cand.y + cand.h / 2);
        }
      }
      ctx.restore();
    }
  }

  function stepSmoke(dtSec) {
    if (state.stillPlan) return;
    if (state.playing && state.days30.length > 0) {
      state.dayFloat += dtSec * 1.15;
      if (state.dayFloat >= state.days30.length) state.dayFloat = 0;
      const nextIdx = Math.floor(state.dayFloat);
      if (nextIdx !== state.dayIndex) {
        state.dayIndex = nextIdx;
        updateReplayReadout();
      }
    }

    for (const p of state.parcels) {
      const ev = p.proj.daily30[state.dayIndex] || 0;
      if (ev <= 0) continue;
      const norm = Math.sqrt(ev / state.globalPeakDaily);
      const rate = 0.65 + norm * 6.5;
      p._smokeAcc = (p._smokeAcc || 0) + dtSec * rate;
      while (p._smokeAcc >= 1) {
        p._smokeAcc -= 1;
        state.puffs.push({
          wx: p.chimney.x + (Math.random() - 0.5) * 2,
          wy: p.chimney.y + (Math.random() - 0.5) * 2,
          wz: p.chimney.baseZ + p.chimney.h + 2,
          age: 0,
          life: 2.2 + norm * 1.4 + Math.random() * 0.4,
          r0: 2.5 + norm * 2.5,
          r1: 8 + norm * 15,
          isPeak: state.dayIndex === p.proj.busiestIndex,
          accentKey: p.proj.accentTokenKey,
          driftX: 11 + Math.random() * 4,
          driftY: -9 + (Math.random() - 0.5) * 3,
          riseZ: 25 + norm * 15
        });
      }
    }

    for (let i = state.puffs.length - 1; i >= 0; i--) {
      const pf = state.puffs[i];
      pf.age += dtSec;
      if (pf.age >= pf.life) {
        state.puffs.splice(i, 1);
      } else {
        pf.wx += pf.driftX * dtSec;
        pf.wy += pf.driftY * dtSec;
        pf.wz += pf.riseZ * dtSec;
      }
    }
    if (state.puffs.length > 360) state.puffs.splice(0, state.puffs.length - 360);
  }

  function drawAnimatedPuffs(ctx, pal) {
    const zoom = state.cam.zoom;
    ctx.save();
    for (const pf of state.puffs) {
      const u = pf.age / pf.life;
      const pt = worldToCanvas(pf.wx, pf.wy, pf.wz);
      const r = lerp(pf.r0, pf.r1, easeOutCubic(u)) * zoom;
      const alpha = (1 - u) * (u < 0.12 ? u / 0.12 : 1);
      const stroke = pf.isPeak ? pal.core : (pf.accentKey === 'acc' ? pal.acc : pal.mut);
      ctx.globalAlpha = alpha * 0.24;
      ctx.fillStyle = stroke;
      ctx.beginPath(); ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = alpha * 0.65;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = Math.max(0.75, 1.05 * zoom);
      ctx.beginPath(); ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.restore();
  }

  function drawStaticPlumes(ctx, pal) {
    const zoom = state.cam.zoom;
    ctx.save();
    for (const p of state.parcels) {
      const ev = p.proj.daily30[state.dayIndex] || 0;
      if (ev <= 0) continue;
      const norm = Math.sqrt(ev / state.globalPeakDaily);
      const rings = Math.max(2, Math.round(2 + norm * 4));
      const stroke = state.dayIndex === p.proj.busiestIndex ? pal.core : pal.acc;
      for (let k = 1; k <= rings; k++) {
        const u = k / (rings + 0.5);
        const pt = worldToCanvas(p.chimney.x + u * 28, p.chimney.y - u * 22, p.chimney.baseZ + p.chimney.h + u * (32 + norm * 24));
        const r = (3.5 + u * (7 + norm * 13)) * zoom;
        ctx.globalAlpha = (1 - u * 0.65) * 0.7;
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1;
        ctx.setLineDash(k > 2 ? [3, 2] : []);
        ctx.beginPath(); ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.setLineDash([]);
    }
    ctx.restore();
  }

  function drawPlanScaleOverlay(ctx, pal, zoom) {
    if (state.viewW < 420) return;
    const refPapers = state.maxIncluded >= 200 ? 100 : 50;
    const side = Math.sqrt(MAX_HALL_AREA * (refPapers / state.maxIncluded));
    const dx = side * COS30 * zoom * 0.5;
    const dy = side * SIN30 * zoom * 0.5;
    const label = `□ = ${refPapers} included papers (exact area)`;

    ctx.save();
    ctx.font = `500 10.5px ${pal.fMono}`;
    const tw = ctx.measureText(label).width;
    const boxW = Math.max(dx * 2 + 18, tw + 24);
    const boxH = Math.max(36, dy * 2 + 24);
    ctx.fillStyle = pal.surface;
    ctx.strokeStyle = pal.line;
    ctx.globalAlpha = 0.92;
    ctx.beginPath();
    ctx.roundRect(12, state.viewH - boxH - 12, boxW, boxH, 6);
    ctx.fill();
    ctx.stroke();

    ctx.globalAlpha = 1;
    const dcx = 26 + dx;
    const dcy = state.viewH - boxH - 12 + boxH * 0.42;
    drawPoly(ctx, [
      { x: dcx, y: dcy - dy }, { x: dcx + dx, y: dcy },
      { x: dcx, y: dcy + dy }, { x: dcx - dx, y: dcy }
    ], pal.accSoft, pal.acc, 1.1);

    ctx.fillStyle = pal.mut;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillText(label, 20, state.viewH - 17);
    ctx.restore();
  }

  function renderFrame(now) {
    const canvas = $('pt-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const pal = state.palette;
    const zoom = state.cam.zoom;

    ctx.save();
    ctx.scale(state.dpr, state.dpr);
    ctx.fillStyle = pal.bg;
    ctx.fillRect(0, 0, state.viewW, state.viewH);

    drawGroundGrid(ctx, pal);
    drawEstateAvenues(ctx, pal);
    state.hitRegions = [];
    state.reservedRects = [];

    const drawables = [
      ...state.parcels.map(p => ({ kind: 'parcel', depth: p.x0 + p.y0, data: p })),
      { kind: 'loading-dock', depth: state.loadingDock.x0 + state.loadingDock.y0, data: state.loadingDock },
      { kind: 'empty-plot', depth: state.emptyPlot.x0 + state.emptyPlot.y0, data: state.emptyPlot }
    ].sort((a, b) => a.depth - b.depth);

    for (const item of drawables) {
      if (item.kind === 'parcel') drawProjectCompound(ctx, item.data, pal, now);
      else if (item.kind === 'loading-dock') drawLoadingDock(ctx, item.data, pal, now);
      else drawEmptyPlot(ctx, item.data, pal);
    }

    if (state.stillPlan) drawStaticPlumes(ctx, pal);
    else drawAnimatedPuffs(ctx, pal);

    drawAllAnnotations(ctx, pal, zoom);
    drawPlanScaleOverlay(ctx, pal, zoom);
    ctx.restore();
  }

  function buildHotspots() {
    const layer = $('pt-hotspots');
    if (!layer) return;
    layer.innerHTML = '';
    for (const p of state.parcels) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pt-hotspot';
      btn.dataset.target = p.id;
      btn.textContent = `${p.proj.title} (${fmt(p.proj.funnel.included)})`;
      btn.setAttribute('aria-label', `${p.proj.title}: ${fmt(p.proj.funnel.included)} included, ${fmt(p.proj.built)} pages built.`);
      btn.addEventListener('click', () => focusParcel(p.id));
      layer.appendChild(btn);
    }
    syncHotspots();
  }

  function syncHotspots() {
    const layer = $('pt-hotspots');
    if (!layer) return;
    for (const btn of layer.querySelectorAll('.pt-hotspot')) {
      const p = state.parcels.find(item => item.id === btn.dataset.target);
      if (!p) continue;
      const pt = worldToCanvas(p.hall.cx, p.hall.cy, p.hall.h * 0.5);
      btn.style.left = `${clamp(pt.x, 24, state.viewW - 24)}px`;
      btn.style.top = `${clamp(pt.y, 24, state.viewH - 24)}px`;
    }
  }

  function focusParcel(parcelId) {
    const parcel = state.parcels.find(p => p.id === parcelId);
    if (!parcel) return;
    state.selectedId = parcel.id;
    const center = isoToScreen(parcel.x0 + parcel.w * 0.55, parcel.y0 + parcel.d * 0.5, 16);
    const fit = getFitCamera();
    const targetZoom = clamp(Math.max(fit.zoom * 1.55, 1.35), 1.15, 2.35);
    animateCameraTo({ x: center.x + 55 / targetZoom, y: center.y + 12 / targetZoom, zoom: targetZoom }, 500);
    openGatehouseHud(parcel);
  }

  function openGatehouseHud(parcel) {
    const { proj } = parcel;
    const hud = $('pt-gatehouse');
    if (!hud) return;
    $('pt-gh-slug').textContent = `LOT ${String(proj.lotNumber).padStart(2, '0')} · ${proj.slug}`;
    $('pt-gh-title').textContent = proj.title;
    const staleVal = !proj.hubReady ? 'Not built' : (proj.stale > 0 ? fmt(proj.stale) : '0');
    const staleLbl = !proj.hubReady ? 'hub status' : (proj.stale > 0 ? 'to rebuild' : 'up to date');
    $('pt-gh-metrics').innerHTML = `
      <div class="pt-gh-stat"><b>${fmt(proj.funnel.included)}</b><span>included / ${fmt(proj.funnel.found)} found</span></div>
      <div class="pt-gh-stat"><b>${fmt(proj.built)}</b><span>pages built</span></div>
      <div class="pt-gh-stat"><b>${staleVal}</b><span>${staleLbl}</span></div>
    `;
    const enter = $('pt-gh-enter');
    enter.href = proj.hubUrl;
    enter.onclick = ev => {
      ev.preventDefault();
      if (state.stillPlan) {
        window.location.href = proj.hubUrl;
        return;
      }
      const door = isoToScreen(parcel.hall.x + parcel.hall.w, parcel.hall.cy, parcel.hall.h * 0.35);
      animateCameraTo({ x: door.x, y: door.y, zoom: Math.max(state.cam.zoom * 2, 3.0) }, 380);
      $('pt-fly-title').textContent = proj.title;
      $('pt-fly-url').textContent = proj.hubUrl;
      $('pt-fly-veil').hidden = false;
      setTimeout(() => { window.location.href = proj.hubUrl; }, 420);
    };
    $('pt-gh-classic').href = proj.classicUrl;
    const inboxBtn = $('pt-gh-inbox');
    if (inboxBtn) {
      inboxBtn.onclick = () => jumpToInbox(proj.slug, null);
    }
    hud.hidden = false;
  }

  function closeGatehouseHud() {
    const hud = $('pt-gatehouse');
    if (hud) hud.hidden = true;
    state.selectedId = null;
  }

  function pulseElement(el) {
    if (!el) return;
    el.scrollIntoView({ behavior: state.stillPlan ? 'auto' : 'smooth', block: 'center' });
    el.classList.add('pt-pulse');
    setTimeout(() => el.classList.remove('pt-pulse'), 1400);
  }

  function jumpToCreate() {
    const form = $('create-form');
    if (!form) return;
    pulseElement(form);
    const input = form.querySelector('input[name=slug]');
    if (input) input.focus({ preventScroll: true });
  }

  function jumpToInbox(slug, value) {
    const form = $('inbox-form');
    if (!form) return;
    if (slug && form.project) form.project.value = slug;
    if (value && form.value) form.value.value = value;
    pulseElement(form);
    const input = form.querySelector('input[name=value]');
    if (input) input.focus({ preventScroll: true });
  }

  function renderReplayDeck() {
    const range = $('pt-replay-range');
    if (!range) return;
    range.max = String(state.days30.length - 1);
    range.value = String(state.dayIndex);
    const mid = Math.floor(state.days30.length / 2);
    $('pt-replay-axis').innerHTML = `
      <span>${formatShortDate(state.days30[0])}</span>
      <span>${formatShortDate(state.days30[mid])}</span>
      <span>${formatShortDate(state.days30[state.days30.length - 1])}</span>
    `;
    const peaksEl = $('pt-replay-peaks');
    peaksEl.innerHTML = '';
    for (const p of state.projects.slice(0, 4)) {
      if (p.peak30 <= 0) continue;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pt-peak-btn';
      btn.dataset.peakDay = String(p.busiestIndex);
      btn.innerHTML = `<span class="pt-peak-flag" aria-hidden="true">★</span> ${escapeHtml(p.slug)}: ${escapeHtml(p.busiestLabel)} (${fmt(p.peak30)})`;
      btn.addEventListener('click', () => {
        state.playing = false;
        state.dayIndex = p.busiestIndex;
        state.dayFloat = p.busiestIndex;
        syncPlayButton();
        updateReplayReadout();
        renderFrame(performance.now());
      });
      peaksEl.appendChild(btn);
    }
    updateReplayReadout();
    syncPlayButton();
  }

  function drawReplaySpark() {
    const svg = $('pt-replay-spark');
    if (!svg) return;
    const days = state.days30.length;
    const peakDays = new Set(state.projects.filter(p => p.peak30 > 0).map(p => p.busiestIndex));
    const w = days * 12, h = 32;
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.innerHTML = state.estateDaily30.map((val, i) => {
      const bh = val === 0 ? 1.5 : Math.max(3, (val / state.estateMaxDaily) * (h - 6));
      const y = h - bh;
      const isCur = i === state.dayIndex;
      const isPeak = peakDays.has(i);
      const fill = isCur ? 'var(--acc)' : (isPeak ? 'var(--l-core)' : (val === 0 ? 'var(--line)' : 'var(--seq-3)'));
      return `<rect x="${i * 12}" y="${y.toFixed(1)}" width="9" height="${bh.toFixed(1)}" rx="1" fill="${fill}"/>`;
    }).join('');
  }

  function updateReplayReadout() {
    const iso = state.days30[state.dayIndex];
    const total = state.estateDaily30[state.dayIndex] || 0;
    const range = $('pt-replay-range');
    if (range) range.value = String(state.dayIndex);
    $('pt-replay-day').textContent = `${formatShortDate(iso)} · Day ${state.dayIndex + 1} / ${state.days30.length}`;
    $('pt-replay-events').textContent = `${fmt(total)} events across ${state.projects.length} project${state.projects.length === 1 ? '' : 's'}`;
    for (const btn of document.querySelectorAll('.pt-peak-btn')) {
      btn.setAttribute('aria-pressed', String(Number(btn.dataset.peakDay) === state.dayIndex));
    }
    drawReplaySpark();
  }

  function syncPlayButton() {
    const btn = $('pt-replay-play');
    if (!btn) return;
    const active = state.playing && !state.stillPlan;
    btn.setAttribute('aria-pressed', String(active));
    $('pt-hud-mode').textContent = state.stillPlan
      ? 'AXONOMETRIC 30° · STILL PLAN'
      : (active ? 'AXONOMETRIC 30° · LIVE SMOKE REPLAY' : 'AXONOMETRIC 30° · PAUSED');
    $('pt-viewport').dataset.still = String(state.stillPlan);
  }

  function hitTest(px, py) {
    for (let i = state.hitRegions.length - 1; i >= 0; i--) {
      if (pointInPoly(px, py, state.hitRegions[i].poly)) return state.hitRegions[i];
    }
    return null;
  }

  function resizeCanvas() {
    const stage = $('pt-stage');
    const canvas = $('pt-canvas');
    if (!stage || !canvas) return;
    const rect = stage.getBoundingClientRect();
    state.viewW = Math.max(320, rect.width);
    state.viewH = Math.max(320, rect.height);
    state.dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(state.viewW * state.dpr);
    canvas.height = Math.round(state.viewH * state.dpr);
    state.cam = getFitCamera();
    syncHotspots();
    renderFrame(performance.now());
  }

  function bindEvents() {
    const stage = $('pt-stage');
    const tip = $('pt-tip');

    stage.addEventListener('pointerdown', ev => {
      if (ev.target.closest('.pt-gatehouse, .pt-hotspot')) return;
      state.dragging = true;
      state.dragMoved = false;
      state.dragStart = { x: ev.clientX, y: ev.clientY, camX: state.cam.x, camY: state.cam.y };
      stage.classList.add('pt-dragging');
      stage.setPointerCapture(ev.pointerId);
    });

    stage.addEventListener('pointermove', ev => {
      const rect = stage.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      if (state.dragging && state.dragStart) {
        const dx = ev.clientX - state.dragStart.x;
        const dy = ev.clientY - state.dragStart.y;
        if (Math.hypot(dx, dy) > 4) state.dragMoved = true;
        state.cam.x = state.dragStart.camX - dx / state.cam.zoom;
        state.cam.y = state.dragStart.camY - dy / state.cam.zoom;
        state.camFrom = null;
        state.camTo = null;
        syncHotspots();
        if (state.stillPlan) renderFrame(performance.now());
        return;
      }
      const hit = hitTest(px, py);
      state.hovered = hit;
      stage.classList.toggle('pt-pointer-hit', Boolean(hit));
      if (hit && hit.tip) {
        tip.innerHTML = `<span class="pt-tip-k">${escapeHtml(hit.tip.kicker)}</span><span class="pt-tip-title">${escapeHtml(hit.tip.title)}</span><span class="pt-tip-meta">${escapeHtml(hit.tip.meta)}</span>`;
        tip.hidden = false;
        tip.style.left = `${clamp(px + 14, 12, state.viewW - 312)}px`;
        tip.style.top = `${clamp(py + 14, 12, state.viewH - 90)}px`;
      } else {
        tip.hidden = true;
      }
    });

    stage.addEventListener('pointerup', ev => {
      if (!state.dragging) return;
      state.dragging = false;
      stage.classList.remove('pt-dragging');
      if (!state.dragMoved) {
        const rect = stage.getBoundingClientRect();
        const hit = hitTest(ev.clientX - rect.left, ev.clientY - rect.top);
        if (!hit) {
          closeGatehouseHud();
          animateCameraTo(getFitCamera(), 420);
        } else if (hit.kind === 'empty-plot') {
          jumpToCreate();
        } else if (hit.kind === 'loading-dock') {
          jumpToInbox(null, null);
        } else if (hit.parcelId) {
          focusParcel(hit.parcelId);
        }
      }
    });

    stage.addEventListener('wheel', ev => {
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 1.12 : 0.89;
      state.cam.zoom = clamp(state.cam.zoom * factor, 0.35, 3.0);
      syncHotspots();
      if (state.stillPlan) renderFrame(performance.now());
    }, { passive: false });

    // Drag and drop DOI onto stage -> Loading Dock
    const scrim = $('pt-drop-scrim');
    stage.addEventListener('dragover', ev => { ev.preventDefault(); if (scrim) scrim.hidden = false; });
    stage.addEventListener('dragleave', ev => { if (ev.target === stage && scrim) scrim.hidden = true; });
    stage.addEventListener('drop', ev => {
      ev.preventDefault();
      if (scrim) scrim.hidden = true;
      const text = (ev.dataTransfer.getData('text/uri-list') || ev.dataTransfer.getData('text/plain') || '').trim();
      if (text) jumpToInbox(null, text);
    });

    $('pt-cam-in')?.addEventListener('click', () => animateCameraTo({ ...state.cam, zoom: clamp(state.cam.zoom * 1.25, 0.35, 3.0) }, 260));
    $('pt-cam-out')?.addEventListener('click', () => animateCameraTo({ ...state.cam, zoom: clamp(state.cam.zoom * 0.8, 0.35, 3.0) }, 260));
    $('pt-cam-fit')?.addEventListener('click', () => { closeGatehouseHud(); animateCameraTo(getFitCamera(), 420); });
    $('pt-gh-close')?.addEventListener('click', () => { closeGatehouseHud(); animateCameraTo(getFitCamera(), 420); });
    $('pt-btn-break')?.addEventListener('click', jumpToCreate);
    $('pt-btn-dock')?.addEventListener('click', () => jumpToInbox(null, null));

    $('pt-btn-still')?.addEventListener('click', () => {
      state.stillPlan = !state.stillPlan;
      $('pt-btn-still').setAttribute('aria-pressed', String(state.stillPlan));
      if (state.stillPlan) state.puffs = [];
      syncPlayButton();
      renderFrame(performance.now());
    });

    $('pt-replay-play')?.addEventListener('click', () => {
      if (state.stillPlan) {
        state.stillPlan = false;
        $('pt-btn-still')?.setAttribute('aria-pressed', 'false');
      }
      state.playing = !state.playing;
      syncPlayButton();
      renderFrame(performance.now());
    });

    $('pt-replay-range')?.addEventListener('input', ev => {
      state.playing = false;
      state.dayIndex = Number(ev.target.value);
      state.dayFloat = state.dayIndex;
      syncPlayButton();
      updateReplayReadout();
      renderFrame(performance.now());
    });

    // Redraw on theme change
    const refreshTheme = () => {
      state.palette = readPalette();
      renderFrame(performance.now());
    };
    new MutationObserver(refreshTheme).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    });
    window.addEventListener('storage', refreshTheme);
    window.addEventListener('resize', resizeCanvas);
  }

  function loop(now) {
    const dt = state.lastFrameTs ? Math.min(0.05, (now - state.lastFrameTs) / 1000) : 0.016;
    state.lastFrameTs = now;
    if (state.camFrom && state.camTo) {
      const t = clamp((now - state.camAnimStart) / state.camAnimDur, 0, 1);
      const e = easeOutCubic(t);
      state.cam.x = lerp(state.camFrom.x, state.camTo.x, e);
      state.cam.y = lerp(state.camFrom.y, state.camTo.y, e);
      state.cam.zoom = lerp(state.camFrom.zoom, state.camTo.zoom, e);
      syncHotspots();
      if (t >= 1) { state.camFrom = null; state.camTo = null; }
    }
    if (!state.stillPlan) {
      stepSmoke(dt);
      renderFrame(now);
    }
    requestAnimationFrame(loop);
  }

  function init() {
    if (!loadData()) return;
    computeMasterplan();
    buildHotspots();
    renderReplayDeck();
    resizeCanvas();
    bindEvents();
    requestAnimationFrame(loop);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
