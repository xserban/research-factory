/* Research hub scope model (spec slice-7-hub-scope HS-02, HS-10 to HS-12). Pure functions, no DOM access.
   Loaded before shell.js; exposed as window.HUB_SCOPE (and module.exports under Node, for unit tests).
     HUB_SCOPE.parse(hash)      '#scope.from=2026-07&scope.to=2026-09&scope.set=s1&scope.undated=1&x=y'
                                -> {from, to, set, undated} (strings or null; undated is a boolean, true only for
                                'scope.undated=1'; a malformed value is dropped; other keys are ignored)
     HUB_SCOPE.format(scope)    -> 'scope.from=..&scope.to=..&scope.set=..&scope.undated=1' (no '#', null/empty keys omitted)
     HUB_SCOPE.empty(scope)     true when `to` is before `from`: nothing is in range (not swapped, not an error)
     HUB_SCOPE.active(scope)    true when from or to is set
     HUB_SCOPE.classify(published, scope) -> 'in' | 'out' | 'year-only' | 'undated'
     HUB_SCOPE.inRange(published, scope)  true only for 'in'
     HUB_SCOPE.apply(rows, getDate, scope, {includeUndated}) ->
         {inScope, outOfScope, undated, yearOnly, n, N}
     HUB_SCOPE.merge(hash, scope)   hash string with the scope.* keys replaced by format(scope); other keys kept
     HUB_SCOPE.carry(href, scope)   a relative link with its hash scope.* keys replaced the same way (external,
                                    '#'-only and non-http links are returned unchanged)
     HUB_SCOPE.showsBar(page)       false for pages without work lists (HS-01)
     HUB_SCOPE.lineText(res)        {main, undated, yearOnly} sentences for an apply() result (HS-03, HS-11, HS-12)
     HUB_SCOPE.WHOLE_PASS / WHOLE_CORPUS   the labels of HS-21 / HS-20
   The DOM part (bar, lines, current(), onChange()) lives in scope-bar.js and extends this object.
   Month granularity. 'YYYY' is in range only when January to December of that year both lie in range, else
   'year-only' (excluded, counted). Empty or invalid dates are 'undated'. With no bound set every dated work
   is 'in'. apply(): outOfScope holds every excluded dated work (yearOnly rows included); undated lists all
   undated rows and they join inScope only with includeUndated; with no active bound nothing is excluded, so
   undated rows are in scope. n = inScope.length, N = rows.length. */
(function(root){
const MONTH = /^(\d{4})-(0[1-9]|1[0-2])$/;
const idx = (y, m) => y * 12 + (m - 1);

/* A month 'YYYY-MM' -> index, or null. */
function monthIndex(s){
  const m = MONTH.exec(String(s ?? '').trim());
  return m ? idx(+m[1], +m[2]) : null;
}

/* A work date -> {year, month|null}, or null when unusable. Accepts YYYY, YYYY-MM, YYYY-MM-DD, ISO timestamps. */
function parseDate(published){
  const s = String(published ?? '').trim();
  const m = /^(\d{4})(?:-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01])(?:[T ].*)?)?)?$/.exec(s);
  if (!m) return null;
  return {year: +m[1], month: m[2] ? +m[2] : null};
}

function parse(hash){
  const out = {from: null, to: null, set: null, undated: false};
  const q = String(hash ?? '').replace(/^#/, '');
  for (const part of q.split('&')){
    const eq = part.indexOf('=');
    if (eq < 0) continue;
    let k = part.slice(0, eq), v = part.slice(eq + 1);
    try { v = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) { continue; }
    if (k === 'scope.from' || k === 'scope.to'){
      if (monthIndex(v) !== null) out[k.slice(6)] = v.trim();
    } else if (k === 'scope.set' && v.trim()) out.set = v.trim();
    else if (k === 'scope.undated' && v.trim() === '1') out.undated = true;
  }
  return out;
}

function format(scope){
  const s = scope || {}, parts = [];
  if (s.from && monthIndex(s.from) !== null) parts.push('scope.from=' + s.from);
  if (s.to && monthIndex(s.to) !== null) parts.push('scope.to=' + s.to);
  if (s.set) parts.push('scope.set=' + encodeURIComponent(s.set));
  if (s.undated) parts.push('scope.undated=1');
  return parts.join('&');
}

const bounds = scope => {
  const s = scope || {};
  return [s.from ? monthIndex(s.from) : null, s.to ? monthIndex(s.to) : null];
};
const active = scope => { const [a, b] = bounds(scope); return a !== null || b !== null; };
const empty = scope => { const [a, b] = bounds(scope); return a !== null && b !== null && b < a; };

function classify(published, scope){
  const d = parseDate(published);
  if (!d) return 'undated';
  const [a, b] = bounds(scope);
  if (a !== null && b !== null && b < a) return 'out';
  const lo = idx(d.year, d.month ?? 1), hi = idx(d.year, d.month ?? 12);
  const within = (a === null || lo >= a) && (b === null || hi <= b);
  if (within) return 'in';
  return d.month === null ? 'year-only' : 'out';
}

const inRange = (published, scope) => classify(published, scope) === 'in';

function apply(rows, getDate, scope, opts){
  const includeUndated = !!(opts && opts.includeUndated);
  const list = Array.from(rows || []);
  const on = active(scope);
  const inScope = [], outOfScope = [], undated = [], yearOnly = [];
  for (const row of list){
    const c = classify(getDate(row), scope);
    if (c === 'undated'){
      undated.push(row);
      if (includeUndated || !on) inScope.push(row);
    } else if (c === 'in') inScope.push(row);
    else {
      outOfScope.push(row);
      if (c === 'year-only') yearOnly.push(row);
    }
  }
  return {inScope, outOfScope, undated, yearOnly, n: inScope.length, N: list.length};
}

const isScopeKey = part => /^scope\.(from|to|set|undated)(=|$)/.test(part);

/* Replace the scope.* keys of a hash string ('#a=1&scope.from=..' or without '#') by format(scope); keep the rest. */
function merge(hash, scope){
  const keep = String(hash ?? '').replace(/^#/, '').split('&').filter(p => p && !isScopeKey(p));
  const f = format(scope);
  return keep.concat(f ? [f] : []).join('&');
}

/* A link with the scope carried in its hash. Only relative page links are rewritten. */
function carry(href, scope){
  const h = String(href ?? '');
  if (!h || h[0] === '#' || /^[a-z][a-z0-9+.-]*:/i.test(h) || h.startsWith('//')) return h;
  const i = h.indexOf('#');
  const base = i < 0 ? h : h.slice(0, i);
  const m = merge(i < 0 ? '' : h.slice(i + 1), scope);
  return m ? base + '#' + m : base;
}

/* Pages with no work lists (HS-01) show no bar. */
const NO_BAR = ['kit', 'platform', 'costs', 'learn', 'protocol', 'levels', 'method'];
const showsBar = page => NO_BAR.indexOf(page) < 0;

const WHOLE_PASS = 'whole pass, not scoped';
const WHOLE_CORPUS = 'whole corpus';

const plural = (k, one, many) => k + ' ' + (k === 1 ? one : many);

/* Sentences for an apply() result. n and N come from the result; the caller supplies N. */
function lineText(res){
  const r = res || {};
  const k = (r.undated || []).length, y = (r.yearOnly || []).length;
  return {
    main: r.n + ' of ' + r.N + ' papers in scope',
    undated: k ? plural(k, 'paper has', 'papers have') + ' no date' : '',
    yearOnly: y ? plural(y, 'paper has', 'papers have') + ' only a year, too coarse for this range' : '',
  };
}

const api = {parse, format, empty, active, classify, inRange, apply, merge, carry, showsBar, lineText,
  NO_BAR, WHOLE_PASS, WHOLE_CORPUS};
root.HUB_SCOPE = api;
if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
