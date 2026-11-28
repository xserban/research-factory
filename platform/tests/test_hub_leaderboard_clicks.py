"""Leaderboard page in headless Chromium on a built hub (HS-20, HS-22): the page is built by the
real build, its `leaderboard` payload is replaced by one made from a fixture (the world has no
results miner), and a driver sets scopes and clicks. The page's ranking is compared with
`hub_leaderboard.rank` over the same rows. Skipped without chromium."""

# ruff: noqa: E501, F811  (embedded JavaScript, fixtures)

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from factory.services import hub_build as hb
from factory.services import hub_leaderboard as lb
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_leaderboard import baseline_world, res
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)
from tests.test_hub_ui_scope_bar import run_chromium

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH"),
]

DRIVER = r"""<script>
(async function () {
  const out = {};
  const tick = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 80 && !document.getElementById('lbLead'); i++) await tick(100);
  const S = window.HUB_SCOPE, txt = id => { const e = document.getElementById(id); return e ? e.textContent.trim() : null; };
  out.lead = txt('lbLead'); out.hidden0 = txt('lbHidden');
  out.base0 = [...document.querySelectorAll('#lbBase tbody tr')].map(r => [...r.children].map(c => c.textContent.trim()));
  out.tables0 = document.querySelectorAll('.lb-card h3').length;
  out.line0 = txt('lbLine');
  S.set({from: '2026-01'}); await tick(300);
  out.hidden1 = txt('lbHidden'); out.line1 = txt('lbLine');
  out.base1 = [...document.querySelectorAll('#lbBase tbody tr')].map(r => [...r.children].map(c => c.textContent.trim()));
  S.reset(); await tick(300);
  const b = document.querySelector('.lb-val'); out.valueButtons = document.querySelectorAll('.lb-val').length;
  if (b) { b.click(); await tick(200); const q = document.querySelector('.lb-q blockquote'); out.quote = q ? q.textContent : null; }
  out.merged = [...document.querySelectorAll('.lb-dot')].map(e => e.getAttribute('title'));
  out.errors = window.__errs || [];
  const pre = document.createElement('pre'); pre.id = 'lbout'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
</script>"""


def fixture_payload() -> dict[str, Any]:
    data = baseline_world()
    extra = [
        res("o3", "w2", "Mine3", "0.7", dataset="CT RATE"),
        res("o4", "w3", "Mine4", "0.6"),
    ]
    from tests.test_hub_leaderboard import vocab
    from tests.test_hub_leaderboard import world as mkworld

    rows = [r for rs in data.rows.values() for r in rs] + extra
    works = list(data.sets.included)
    v = vocab("dataset", {"ct-rate": ("CT RATE",)})
    return lb.payload_from(mkworld(rows, works, published=dict(data.published)), v)


def test_scope_hides_baseline_rows_in_the_page_and_ranking_matches_the_service(
    world: Project, tmp_path: Path
) -> None:
    out = tmp_path / "ui"
    assert not hb.build_static(world, out).errors
    payload = fixture_payload()
    text = json.dumps(payload, sort_keys=True)
    (out / "data" / "leaderboard.json").write_text(text, encoding="utf-8")
    (out / "data" / "leaderboard.js").write_text(
        f'window.HUB_DATA=window.HUB_DATA||{{}};HUB_DATA["leaderboard"]={text};\n', encoding="utf-8"
    )
    page = out / "leaderboard.html"
    src = page.read_text(encoding="utf-8")
    head, _, tail = src.rpartition("</body>")
    page.write_text(head + DRIVER + "</body>" + tail, encoding="utf-8")
    dom = run_chromium(f"file://{page}", tmp_path, wait_ms=20000)
    start = dom.find('<pre id="lbout">')
    assert start >= 0, dom[:800]
    body = dom[start + len('<pre id="lbout">') :]
    got = json.loads(html.unescape(body[: body.index("</pre>")]))

    whole = lb.rank(payload["rows"])
    in_scope = {w["id"] for w in payload["works"] if w["published"] >= "2026-01"}
    scoped = lb.rank(payload["rows"], in_scope)
    assert got["hidden0"] is None  # no scope: nothing hidden, nothing said
    assert got["tables0"] == len(whole["tables"]) >= 1
    assert [int(r[2]) for r in got["base0"]] == [b["papers"] for b in whole["baselines"]]
    assert scoped["hidden_baseline_rows"] == 2
    assert got["hidden1"].startswith("2 baseline rows hidden (source paper out of scope)")
    assert [int(r[2]) for r in got["base1"]] == [b["papers"] for b in scoped["baselines"]] == [4]
    assert [r[3] for r in got["base1"]] == [f"{b['median']:.3f}" for b in scoped["baselines"]]
    assert got["line1"] and got["line0"]  # the n-of-N line is rendered
    assert got["valueButtons"] >= 1 and got["quote"] and "Table 2 says" in got["quote"]
    assert any(t and "as extracted: " in t and "as merged: ct-rate" in t for t in got["merged"])
