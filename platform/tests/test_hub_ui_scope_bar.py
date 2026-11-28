"""Scope bar in headless Chromium (HS-01, HS-02, HS-03, HS-04, HS-11, HS-20, HS-21).

Two kinds of check. (1) A small fixture page loads the real scope.js, scope-bar.js and kit.css, drives
the bar and `renderLine` with a script, and writes a JSON result into `#out` (the DOM is read with
`--dump-dom`). (2) A built hub page is loaded with a scope in its address hash, which stands for "reload
reproduces": the bar shows the scope, nav links carry it, pages with no work lists show no bar.
Not covered: real pointer and keyboard events (dump-dom has no input channel; keyboard operability rests on
native controls and the `change` and Enter handlers, driven here by dispatched events), contrast ratios
(token pairs are existing hub tokens; no measurement), Back-button behaviour. Skipped without chromium.
"""

# ruff: noqa: E501, F811  (embedded JavaScript, fixtures)

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from factory.services import hub_build as hb
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH"),
]

_UI = Path(str(resources.files("factory").joinpath("hub_ui")))

FIXTURE = """<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<link rel="stylesheet" href="file://{ui}/kit.css"></head><body>
<nav class="rail"><a href="corpus.html">Corpus</a><a href="miners.html#tab=x">Miners</a>
<a href="https://example.org/x">Ext</a></nav>
<div id="scopeBar" hidden></div><div id="line"></div><pre id="out"></pre>
<script src="file://{ui}/scope.js"></script><script src="file://{ui}/scope-bar.js"></script>
<script>
const out = {{}}, S = window.HUB_SCOPE, ev = [];
S.onChange(sc => ev.push(JSON.stringify(sc)));
S.mountBar(document.getElementById('scopeBar'), {{page: {page!r}, forceText: {text}}});
function type(id, v){{ const i = document.getElementById(id); i.value = v; i.dispatchEvent(new Event('change')); }}
{script}
document.getElementById('out').textContent = JSON.stringify(out);
</script></body></html>"""


def run_chromium(url: str, tmp: Path, wait_ms: int = 5000) -> str:
    sink = tmp / "dom.html"
    with sink.open("wb") as fh:
        proc = subprocess.Popen(
            [
                "chromium",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={tmp / 'profile'}",
                f"--virtual-time-budget={wait_ms}",
                "--dump-dom",
                url,
            ],
            stdout=fh,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    return sink.read_text(encoding="utf-8", errors="replace")


def drive(
    tmp: Path, script: str, *, page: str = "corpus", text: bool = False, hash_: str = ""
) -> dict[str, Any]:
    f = tmp / "fixture.html"
    f.write_text(
        FIXTURE.format(ui=_UI, page=page, text="true" if text else "false", script=script),
        encoding="utf-8",
    )
    dom = run_chromium(f"file://{f}{hash_}", tmp)
    m = re.search(r'<pre id="out">(.*?)</pre>', dom, flags=re.S)
    assert m, dom[:500]
    import html

    return json.loads(html.unescape(m.group(1)))  # type: ignore[no-any-return]


def test_setting_dates_updates_hash_keeps_other_keys_and_fires_event(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
history.replaceState(null, '', '#tab=x');
type('scopeFrom', '2026-07'); type('scopeTo', '2026-09');
out.hash = location.hash; out.current = S.current(); out.events = ev;
out.type = document.getElementById('scopeFrom').type;
out.links = [...document.querySelectorAll('.rail a')].map(a => a.getAttribute('href'));
out.resetShown = !document.getElementById('scopeReset').hidden;
""",
    )
    assert out["hash"] == "#tab=x&scope.from=2026-07&scope.to=2026-09"
    assert out["current"] == {"from": "2026-07", "to": "2026-09", "set": None}
    assert len(out["events"]) == 2
    assert out["type"] == "month"
    assert out["links"] == [
        "corpus.html#scope.from=2026-07&scope.to=2026-09",
        "miners.html#tab=x&scope.from=2026-07&scope.to=2026-09",
        "https://example.org/x",
    ]
    assert out["links"][2] == "https://example.org/x"
    assert out["resetShown"] is True


def test_reload_reproduces_the_scope_from_the_hash(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
out.from = document.getElementById('scopeFrom').value;
out.to = document.getElementById('scopeTo').value;
out.hidden = document.getElementById('scopeBar').hidden;
out.links = [...document.querySelectorAll('.rail a')].map(a => a.getAttribute('href'));
""",
        hash_="#scope.from=2026-07&scope.to=2026-09",
    )
    assert (out["from"], out["to"], out["hidden"]) == ("2026-07", "2026-09", False)
    assert out["links"][0] == "corpus.html#scope.from=2026-07&scope.to=2026-09"


def test_reset_clears_scope_and_is_a_labelled_button(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
const r = document.getElementById('scopeReset');
out.tag = r.tagName; out.label = r.getAttribute('aria-label');
r.click();
out.hash = location.hash; out.current = S.current(); out.resetHidden = r.hidden;
out.from = document.getElementById('scopeFrom').value;
out.labels = [...document.querySelectorAll('.scope-bar label')].map(l => l.textContent);
""",
        hash_="#tab=x&scope.from=2026-07",
    )
    assert out["tag"] == "BUTTON"
    assert out["label"] == "Reset scope"
    assert out["hash"] == "#tab=x"
    assert out["current"] == {"from": None, "to": None, "set": None}
    assert out["resetHidden"] is True
    assert out["from"] == ""
    assert out["labels"] == ["from", "to"]


def test_empty_scope_states_itself_and_offers_reset(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
const m = document.getElementById('scopeMsg');
out.msg = m.textContent; out.role = m.getAttribute('role');
""",
        hash_="#scope.from=2026-09&scope.to=2026-07",
    )
    assert "2026-07" in out["msg"]
    assert "2026-09" in out["msg"]
    assert "reset" in out["msg"].lower()
    assert out["role"] == "alert"


def test_text_fallback_validates_month_format(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
out.type = document.getElementById('scopeFrom').type;
type('scopeFrom', '2026-7');
out.badHash = location.hash; out.invalid = document.getElementById('scopeFrom').getAttribute('aria-invalid');
out.msg = document.getElementById('scopeMsg').textContent;
type('scopeFrom', '2026-07');
out.okHash = location.hash;
""",
        text=True,
    )
    assert out["type"] == "text"
    assert out["badHash"] == ""
    assert out["invalid"] == "true"
    assert "YYYY-MM" in out["msg"]
    assert out["okHash"] == "#scope.from=2026-07"


def test_pages_without_work_lists_hide_the_bar_but_still_carry_links(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
out.hidden = document.getElementById('scopeBar').hidden;
out.empty = document.getElementById('scopeBar').innerHTML === '';
out.links = [...document.querySelectorAll('.rail a')].map(a => a.getAttribute('href'));
""",
        page="kit",
        hash_="#scope.from=2026-07",
    )
    assert out["hidden"] is True
    assert out["empty"] is True
    assert out["links"][0] == "corpus.html#scope.from=2026-07"


def test_line_shows_n_of_n_undated_and_tick_from_apply(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
const rows = [{d:'2026-07-15'},{d:'2026-05'},{d:'2026'},{d:''},{d:'2026-08'}];
const line = document.getElementById('line');
function draw(){
  const res = S.apply(rows, r => r.d, S.current(), {includeUndated: S.includeUndated()});
  S.renderLine(line, res, {onToggle: draw});
}
draw();
out.first = line.textContent.replace(/\\s+/g, ' ').trim();
out.tick = !!line.querySelector('[data-scope-undated]');
const t = line.querySelector('[data-scope-undated]'); t.checked = true; t.dispatchEvent(new Event('change'));
out.second = line.textContent.replace(/\\s+/g, ' ').trim();
out.checked = line.querySelector('[data-scope-undated]').checked;
""",
        hash_="#scope.from=2026-07&scope.to=2026-09",
    )
    assert out["first"].startswith("2 of 5 papers in scope")
    assert "1 paper has no date, held out of the count." in out["first"]
    assert "1 paper has only a year" in out["first"]
    assert out["tick"] is True
    assert out["second"].startswith("3 of 5 papers in scope")
    assert "held out" not in out["second"]
    assert out["checked"] is True


def test_line_states_loading_error_empty_and_unscoped(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
const line = document.getElementById('line');
S.renderLine(line, null); out.loading = line.textContent;
S.renderLine(line, {error: 'payload corpus missing'}); out.error = line.textContent;
out.errorRole = line.querySelector('[role=alert]') !== null;
S.renderLine(line, S.apply([{d:'2020-01'}], r => r.d, S.current(), {}));
out.empty = line.textContent;
S.reset();
S.renderLine(line, S.apply([{d:'2020-01'},{d:''}], r => r.d, S.current(), {}));
out.unscoped = line.textContent; out.tick = !!line.querySelector('[data-scope-undated]');
""",
        hash_="#scope.from=2026-07",
    )
    assert "Counting papers" in out["loading"]
    assert out["error"].startswith("Could not count papers in scope: payload corpus missing")
    assert out["errorRole"] is True
    assert "0 of 1 papers in scope" in out["empty"]
    assert "Widen the dates or reset" in out["empty"]
    assert out["unscoped"].startswith("2 of 2 papers in scope")
    assert out["tick"] is False  # no active scope: nothing is held out, no tick offered


def test_labels_for_unscoped_panels(tmp_path: Path) -> None:
    out = drive(
        tmp_path,
        """
out.corpus = S.label('corpus');
out.passOn = S.label('pass');
S.reset();
out.passOff = S.label('pass');
""",
        hash_="#scope.from=2026-07",
    )
    assert "whole corpus" in out["corpus"]
    assert "whole pass, not scoped" in out["passOn"]
    assert out["passOff"] == ""


def test_built_hub_page_shows_scope_and_carries_it_in_nav(
    mined_world: Project,
    tmp_path: Path,
) -> None:
    ui = tmp_path / "ui"
    report = hb.build_static(mined_world, ui)
    assert not report.errors, report.errors
    dom = run_chromium(f"file://{ui}/corpus.html#scope.from=2026-07&scope.to=2026-09", tmp_path)
    bar = re.search(r'<div id="scopeBar"[^>]*>', dom)
    assert bar and "hidden" not in bar.group(0)
    assert 'id="scopeFrom"' in dom  # the input value is a property, not in the serialized DOM
    assert 'href="overview.html#scope.from=2026-07&amp;scope.to=2026-09"' in dom
    kit = run_chromium(f"file://{ui}/kit.html", tmp_path)
    assert re.search(r'<div id="scopeBar"[^>]*hidden', kit)
