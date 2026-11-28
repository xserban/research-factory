/* Research hub scope model (spec slice-7-hub-scope HS-02, HS-10 to HS-12). Pure functions, no DOM access.
   Loaded before shell.js; exposed as window.HUB_SCOPE (and module.exports under Node, for unit tests).
     HUB_SCOPE.parse(hash)      '#scope.from=2026-07&scope.to=2026-09&scope.set=s1&x=y' -> {from, to, set}
                                (strings or null; a malformed value is dropped to null; other keys are ignored)
     HUB_SCOPE.format(scope)    -> 'scope.from=..&scope.to=..&scope.set=..' (no '#', null/empty keys omitted)
     HUB_SCOPE.empty(scope)     true when `to` is before `from`: nothing is in range (not swapped, not an error)
     HUB_SCOPE.active(scope)    true when from or to is set
     HUB_SCOPE.classify(published, scope) -> 'in' | 'out' | 'year-only' | 'undated'
     HUB_SCOPE.inRange(published, scope)  true only for 'in'
     HUB_SCOPE.apply(rows, getDate, scope, {includeUndated}) ->
         {inScope, outOfScope, undated, yearOnly, n, N}
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
  const out = {from: null, to: null, set: null};
  const q = String(hash ?? '').replace(/^#/, '');
  for (const part of q.split('&')){
    const eq = part.indexOf('=');
    if (eq < 0) continue;
    let k = part.slice(0, eq), v = part.slice(eq + 1);
    try { v = decodeURIComponent(v); } catch (e) { continue; }
    if (k === 'scope.from' || k === 'scope.to'){
      if (monthIndex(v) !== null) out[k.slice(6)] = v.trim();
    } else if (k === 'scope.set' && v.trim()) out.set = v.trim();
  }
  return out;
}

function format(scope){
  const s = scope || {}, parts = [];
  if (s.from && monthIndex(s.from) !== null) parts.push('scope.from=' + s.from);
  if (s.to && monthIndex(s.to) !== null) parts.push('scope.to=' + s.to);
  if (s.set) parts.push('scope.set=' + encodeURIComponent(s.set));
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

const api = {parse, format, empty, active, classify, inRange, apply};
root.HUB_SCOPE = api;
if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
