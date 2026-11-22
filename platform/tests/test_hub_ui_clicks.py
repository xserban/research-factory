"""Click-through of every hub page in headless Chromium; fails on JavaScript errors only.

For each page in `hub_ui.PAGES` a copy of the static build's page is written with two injected
scripts: an error collector at the top of `<head>` (uncaught exceptions, unhandled rejections,
`console.error`) and a click driver at the end of `<body>`. The driver exercises the page
(buttons, tabs, chips, segmented controls, first rows and drawers, selects, search boxes, the
theme picker, the hash states the page wrote) and writes a JSON result into `#rf-clicks`, which
the test reads from `--dump-dom`. Acts (`disabled`, `data-act`) are skipped. No visual judging.
The build is made once per module run (the first test builds it). Skipped without chromium.
"""

# ruff: noqa: E501  (the embedded JavaScript has long lines)

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from factory.services import hub_build as hb
from factory.services import hub_ui
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH"),
]

# Scratch root for browser profiles: FACTORY_TEST_TMP when set, else the system temp dir.
PROFILE_ROOT = (
    Path(os.environ.get("FACTORY_TEST_TMP") or tempfile.gettempdir()) / "rf-clicks-profiles"
)

COLLECTOR = """<script>
window.__rfErrors = [];
window.addEventListener('error', function (e) {
  if (e.target && e.target !== window) return;  // resource load failures are not script errors
  window.__rfErrors.push('error: ' + (e.message || String(e.error)) + ' @' + (e.filename || '') + ':' + (e.lineno || ''));
});
window.addEventListener('unhandledrejection', function (e) {
  var r = e.reason; window.__rfErrors.push('rejection: ' + (r && r.stack ? r.stack : String(r)));
});
// headless Chromium denies the clipboard permission; that is the environment, not the page
try { Object.defineProperty(navigator, 'clipboard', {value: {writeText: function () { return Promise.resolve(); }}, configurable: true}); } catch (e) {}
var __ce = console.error;
console.error = function () {
  window.__rfErrors.push('console.error: ' + Array.prototype.map.call(arguments, String).join(' '));
  return __ce.apply(console, arguments);
};
</script>
"""

DRIVER = r"""<script>
(function () {
  var counts = {buttons: 0, rows: 0, selects: 0, searches: 0, themes: 0, hashes: 0};
  var hashes = [];
  var CAP = 60;
  function tick(ms) { return new Promise(function (r) { setTimeout(r, ms || 30); }); }
  function note() { var h = location.hash; if (h && h !== '#' && hashes.indexOf(h) < 0) hashes.push(h); }
  function live(el) { return el && el.isConnected && !el.disabled && !el.hasAttribute('data-act') && !el.closest('[data-act]'); }
  function fire(el) {
    if (typeof el.click === 'function') el.click();
    else el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
  }
  function press(key) {
    document.dispatchEvent(new KeyboardEvent('keydown', {key: key, bubbles: true}));
  }
  async function closeAll() {
    press('Escape'); await tick();
    var d = document.getElementById('drawer'); if (d && d.hasAttribute('open')) { d.removeAttribute('open'); }
  }
  var BTN = 'button, [role=tab], [role=button], .chip, .seg > *, summary';
  var ROW = 'tr[data-id], [data-id], tr[tabindex], li[tabindex], [tabindex="0"], a[href^="#"]';
  // elements that leave the page (`location.href = ...`) would end the driver; they are skipped
  function skip(el) {
    return el.closest('[data-href], [data-m], a[href]:not([href^="#"])') || el.closest('#drawer') || el.closest('#palette') || el.id === 'themePick' || el.tagName === 'SELECT' || el.tagName === 'INPUT';
  }
  async function sweep(sel, key, popFirst) {
    var n = Math.min(document.querySelectorAll(sel).length, CAP);
    for (var i = 0; i < n; i++) {
      var el = document.querySelectorAll(sel)[i];
      if (!el || skip(el) || !live(el)) continue;
      fire(el); counts[key]++; note(); await tick();
      if (popFirst) await closeAll();
    }
  }
  async function run() {
    await tick(400);
    // rows first (they open drawers), then the controls
    await sweep(ROW, 'rows', true);
    await sweep(BTN, 'buttons', false);
    await closeAll();
    var sels = document.querySelectorAll('select');
    for (var s = 0; s < sels.length; s++) {
      var sel = sels[s]; if (sel.id === 'themePick' || !live(sel)) continue;
      var opts = Array.prototype.slice.call(sel.options, 0, 5);
      for (var o = 0; o < opts.length; o++) {
        sel.value = opts[o].value; sel.dispatchEvent(new Event('change', {bubbles: true}));
        sel.dispatchEvent(new Event('input', {bubbles: true})); counts.selects++; note(); await tick();
      }
      sel = document.querySelectorAll('select')[s] || sel;
    }
    var ins = document.querySelectorAll('input[type=search], input[type=text], input:not([type])');
    for (var k = 0; k < ins.length; k++) {
      var inp = ins[k]; if (!live(inp) || inp.closest('#palette')) continue;
      inp.focus(); inp.value = 'a';
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      inp.dispatchEvent(new KeyboardEvent('keyup', {key: 'a', bubbles: true}));
      counts.searches++; note(); await tick();
      inp.value = ''; inp.dispatchEvent(new Event('input', {bubbles: true})); await tick();
    }
    var tp = document.getElementById('themePick');
    if (tp) {
      var vals = Array.prototype.map.call(tp.options, function (x) { return x.value; });
      for (var t = 0; t < vals.length; t++) {
        tp.value = vals[t]; tp.dispatchEvent(new Event('change', {bubbles: true})); counts.themes++; await tick();
      }
    }
    // the hash states the page wrote, re-entered
    for (var h = 0; h < Math.min(hashes.length, 8); h++) {
      location.hash = hashes[h].slice(1);
      window.dispatchEvent(new HashChangeEvent('hashchange'));
      counts.hashes++; await tick(100); await closeAll();
    }
    await tick(100);
  }
  function finish(err) {
    if (err) window.__rfErrors.push('driver: ' + (err && err.stack ? err.stack : String(err)));
    var pre = document.createElement('pre'); pre.id = 'rf-clicks';
    pre.textContent = JSON.stringify({done: true, counts: counts, errors: window.__rfErrors});
    document.body.appendChild(pre);
  }
  window.addEventListener('load', function () { run().then(function () { finish(); }, finish); });
})();
</script>
"""

_BUILT = pytest.StashKey[Path]()  # on the run's config: it ends with the run, no module state


@pytest.fixture
def built(
    request: pytest.FixtureRequest,
    pytestconfig: pytest.Config,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """The static build of the mined world, made once per run (the first test builds it and
    keeps it on the run's config; the parametrised pages then share one build)."""
    if _BUILT not in pytestconfig.stash:
        project: Project = request.getfixturevalue("mined_world")
        out = tmp_path_factory.mktemp("clicks") / "ui"
        report = hb.build_static(project, out)
        assert not report.errors, report.errors
        pytestconfig.stash[_BUILT] = out
    return pytestconfig.stash[_BUILT]


def _instrument(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8")
    assert "<head>" in text and "</body>" in text, "unexpected page skeleton"
    text = text.replace("<head>", "<head>\n" + COLLECTOR, 1)
    head, _, tail = text.rpartition("</body>")
    dst.write_text(head + DRIVER + "</body>" + tail, encoding="utf-8")


def _drive(page: Path) -> dict[str, Any]:
    """Run the click driver on `page`; return its result JSON (or an error stand-in)."""
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    marked = page.with_name(page.stem + ".clicks.html")
    _instrument(page, marked)
    profile = tempfile.mkdtemp(prefix="rf-clicks-", dir=PROFILE_ROOT)
    try:
        proc = subprocess.run(
            [
                "chromium",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=120000",
                "--dump-dom",
                f"file://{marked}",
            ],
            capture_output=True,
            text=True,
            timeout=300,  # real time: a loaded CI runner needs far more than the 120 s of virtual time
            check=False,
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
        marked.unlink(missing_ok=True)
    start = proc.stdout.find('<pre id="rf-clicks">')
    if start < 0:
        return {"done": False, "counts": {}, "errors": ["driver never finished"]}
    body = proc.stdout[start + len('<pre id="rf-clicks">') :]
    result: dict[str, Any] = json.loads(html.unescape(body[: body.index("</pre>")]))
    return result


@pytest.mark.parametrize("pid", list(hub_ui.PAGES))
def test_page_clicks_raise_no_javascript_errors(pid: str, built: Path) -> None:
    page = built / f"{pid}.html"
    assert page.is_file(), f"{pid}: page not built"
    result = _drive(page)
    counts = result["counts"]
    total = sum(counts.values())
    print(f"CLICKS {pid}: {total} {counts}")
    assert result["done"], result
    assert not result["errors"], result["errors"][:5]
    assert total >= 1, f"{pid}: nothing interactive was exercised"
