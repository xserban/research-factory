/* Research hub scope bar (spec slice-7-hub-scope HS-01 to HS-04, HS-11, HS-20, HS-21). The DOM part of the scope
   module: loaded after scope.js and before shell.js; it extends window.HUB_SCOPE. The pure model stays in scope.js.
   Page-facing API (all on window.HUB_SCOPE):
     current()                 {from, to, set, undated} read from the address hash now
     includeUndated()          true when the "include undated" tick is on (hash key scope.undated=1, HS-02)
     set(partial)              merge {from, to, set} into the hash (replaceState, other keys kept), fire hub:scope
     reset()                   clear from, to and set
     onChange(fn)              fn(scope) on every change (bar, hash edit, back button, tick); returns an unsubscribe
     renderLine(el, res, opts) the "n of N" line, the undated line and the tick. res is an apply() result from the
                               page's own call (N is the page's unscoped denominator); null = loading;
                               {error:'...'} = error. opts.onToggle(includeUndated) is called after the tick changes.
     label(kind)               '<span class="scope-label">whole pass, not scoped</span>' (kind 'pass', HS-21; '' while
                               no scope is active) or 'whole corpus' (kind 'corpus', HS-20): for panels the scope
                               does not change
     mountBar(el, {page, forceText})   used by shell.js: renders the bar into el, wires nav links
   The event is `hub:scope` on document, detail = the scope. */
(function(root){
const S = root.HUB_SCOPE;
if (!S || typeof document === 'undefined') return;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const EVENT = 'hub:scope';
const listeners = new Set();

const current = () => S.parse(location.hash);
const includeUndated = () => current().undated;

function emit(){
  const sc = current();
  document.dispatchEvent(new CustomEvent(EVENT, {detail: sc}));
}

function set(partial){
  const next = Object.assign({}, current(), partial || {});
  const h = S.merge(location.hash, next);
  history.replaceState(null, '', location.pathname + location.search + (h ? '#' + h : ''));
  emit();
}
const reset = () => set({from: null, to: null, set: null, undated: false});

function onChange(fn){
  const h = e => fn(e.detail);
  document.addEventListener(EVENT, h);
  return () => document.removeEventListener(EVENT, h);
}

/* ---------- nav links carry the scope ---------- */
function carryLinks(){
  const sc = current();
  document.querySelectorAll('.rail a[href], .sec-tabs a[href], .menu-grid a[href]').forEach(a => {
    if (a.dataset.href0 === undefined) a.dataset.href0 = a.getAttribute('href');
    a.setAttribute('href', S.carry(a.dataset.href0, sc));
  });
}

/* ---------- the bar ---------- */
function monthSupported(){
  const i = document.createElement('input');
  i.setAttribute('type', 'month');
  return i.type === 'month';
}

function mountBar(el, opts){
  const o = opts || {};
  carryLinks();
  onChange(carryLinks);
  addEventListener('hashchange', emit);
  if (!el) return;
  if (!S.showsBar(o.page)){ el.hidden = true; return; }
  const native = !o.forceText && monthSupported();
  const type = native ? 'month' : 'text';
  const extra = native ? '' : ' placeholder="YYYY-MM" pattern="\\d{4}-(0[1-9]|1[0-2])" inputmode="numeric" maxlength="7" size="8"';
  el.hidden = false;
  el.className = 'scope-bar';
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', 'Publication scope');
  el.innerHTML =
    '<span class="scope-title">Published</span>' +
    '<label class="scope-f"><span>from</span><input type="' + type + '" id="scopeFrom" data-scope="from"' + extra + '></label>' +
    '<label class="scope-f"><span>to</span><input type="' + type + '" id="scopeTo" data-scope="to"' + extra + '></label>' +
    '<span class="scope-set" id="scopeSet" hidden></span>' +
    '<button type="button" class="btn scope-reset" id="scopeReset" aria-label="Reset scope" title="Reset scope">✕</button>' +
    '<span class="scope-msg" id="scopeMsg" role="status" aria-live="polite"></span>';
  const from = el.querySelector('#scopeFrom'), to = el.querySelector('#scopeTo');
  const setEl = el.querySelector('#scopeSet'), rst = el.querySelector('#scopeReset'), msg = el.querySelector('#scopeMsg');

  function paint(){
    const sc = current();
    if (document.activeElement !== from) from.value = sc.from || '';
    if (document.activeElement !== to) to.value = sc.to || '';
    from.removeAttribute('aria-invalid'); to.removeAttribute('aria-invalid');
    setEl.hidden = !sc.set;
    setEl.textContent = sc.set ? 'Paper set: ' + sc.set : '';
    rst.hidden = !S.active(sc) && !sc.set;
    el.classList.toggle('is-empty', S.empty(sc));
    msg.className = 'scope-msg' + (S.empty(sc) ? ' bad' : '');
    msg.textContent = S.empty(sc)
      ? 'No papers in scope: the end (' + sc.to + ') is before the start (' + sc.from + '). Change a date or reset.'
      : '';
    if (S.empty(sc)) msg.setAttribute('role', 'alert'); else msg.setAttribute('role', 'status');
  }

  function commit(input, key){
    const v = input.value.trim();
    if (v === '' ){ set({[key]: null}); return; }
    if (S.parse('#scope.' + key + '=' + v)[key] === null){
      input.setAttribute('aria-invalid', 'true');
      msg.className = 'scope-msg bad'; msg.setAttribute('role', 'alert');
      msg.textContent = 'Use a month as YYYY-MM, for example 2026-07.';
      return;
    }
    set({[key]: v});
  }
  [[from, 'from'], [to, 'to']].forEach(([i, k]) => {
    i.addEventListener('change', () => commit(i, k));
    i.addEventListener('keydown', e => { if (e.key === 'Enter') commit(i, k); });
  });
  rst.addEventListener('click', () => { reset(); from.focus(); });
  onChange(paint);
  paint();
}

/* ---------- the "n of N" lines (HS-03, HS-11, HS-12) ---------- */
function renderLine(el, res, opts){
  if (!el) return;
  const o = opts || {};
  el.classList.add('scope-line');
  el.setAttribute('aria-live', 'polite');
  if (res === null || res === undefined){          /* loading */
    el.innerHTML = '<span class="scope-n loading">Counting papers in scope…</span>';
    return;
  }
  if (res.error){                                  /* error: never shown as empty */
    el.innerHTML = '<span class="scope-n bad" role="alert">Could not count papers in scope: ' + esc(res.error) +
      '. Reload the page; if it persists, rebuild the hub.</span>';
    return;
  }
  const sc = current(), t = S.lineText(res), k = (res.undated || []).length;
  let h = '<span class="scope-n"><b>' + esc(t.main) + '</b></span>';
  if (res.n === 0 && res.N > 0){                   /* empty: say why and what to do */
    const f = S.format(sc).replace(/&/g, ', ');
    h += '<span class="scope-empty">No paper falls in this scope' + (f ? ' (' + esc(f) + ')' : '') +
      '. Widen the dates or reset the scope.</span>';
  }
  if (t.yearOnly) h += '<span class="scope-year">' + esc(t.yearOnly) + '.</span>';
  if (k){                                          /* partial: held out undated works are always named */
    h += '<span class="scope-undated">' + esc(t.undated) + (S.active(sc) && !sc.undated ? ', held out of the count' : '') + '.</span>' +
      (S.active(sc) ? '<label class="scope-tick"><input type="checkbox" data-scope-undated' + (sc.undated ? ' checked' : '') +
        '> include undated</label>' : '');
  }
  el.innerHTML = h;
  const tick = el.querySelector('[data-scope-undated]');
  if (tick) tick.addEventListener('change', () => {
    set({undated: tick.checked});
    if (o.onToggle) o.onToggle(tick.checked);
  });
}

/* Labels for panels the scope does not change. */
function label(kind){
  if (kind === 'pass' && !S.active(current())) return '';   /* HS-21: only while a scope is active */
  const text = kind === 'pass' ? S.WHOLE_PASS : S.WHOLE_CORPUS;
  return '<span class="scope-label" data-kind="' + (kind === 'pass' ? 'pass' : 'corpus') + '" title="The scope does not change this figure">' + esc(text) + '</span>';
}

Object.assign(S, {current, includeUndated, set, reset, onChange, renderLine, label, mountBar, EVENT});
})(typeof window !== 'undefined' ? window : globalThis);
