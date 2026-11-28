"""Browser tests: the Miners and Data pages under a publication scope (P1-06).

Spec HS-03, HS-20, HS-21, HS-24. A built fixture hub (`mined_world`: miner m-test read two included
works) has the two read works re-dated in every payload, a scope is set through the address hash,
and the serialized DOM is read back. Per-work figures shrink to the in-scope works; agreement
keeps its numbers and carries "whole pass, not scoped".
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from factory.services import hub_build as hb
from factory.services import hub_payloads as hp
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)
from tests.test_hub_ui_scope_bar import run_chromium

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH"),
]

EARLY, LATE = "2024-03", "2025-06"


def _redate(node: Any, dates: dict[str, str]) -> None:
    if isinstance(node, dict):
        wid = node.get("id") if "id" in node else node.get("work")
        if "published" in node and wid in dates:
            node["published"] = dates[wid]
        for v in node.values():
            _redate(v, dates)
    elif isinstance(node, list):
        for v in node:
            _redate(v, dates)


@pytest.fixture
def hub(mined_world: Project, tmp_path: Path) -> tuple[Path, str, str]:  # noqa: F811
    """The built hub, first read work dated EARLY and second LATE; returns (ui, early, late)."""
    ui = tmp_path / "ui"
    report = hb.build_static(mined_world, ui)
    assert not report.errors, report.errors
    early, late = sorted(hp.load_flow_data(mined_world).sets.included)[:2]
    dates = {early: EARLY, late: LATE}
    for jf in sorted((ui / "data").glob("*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        _redate(data, dates)
        text = json.dumps(data, separators=(",", ":"))
        jf.write_text(text + "\n", encoding="utf-8")
        jf.with_suffix(".js").write_text(
            f"window.HUB_DATA=window.HUB_DATA||{{}};HUB_DATA[{json.dumps(jf.stem)}]={text};\n",
            encoding="utf-8",
        )
    return ui, early, late


def _dom(ui: Path, tmp: Path, page: str, hash_: str) -> str:
    tmp.mkdir(parents=True, exist_ok=True)
    return html.unescape(run_chromium(f"file://{ui}/{page}{hash_}", tmp))


def _text(dom: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dom))


def _bars(dom: str) -> dict[str, int]:
    """Value label -> count of the `stance` field card's bars."""
    card = re.search(r'aria-label="Values of Stance">(.*?)</div></div>', dom, flags=re.S)
    assert card, dom[:300]
    out: dict[str, int] = {}
    for m in re.finditer(
        r'<span class="l">(.*?)</span>.*?<span class="n">([\d,]+)</span>', card.group(1), flags=re.S
    ):
        out[m.group(1)] = int(m.group(2).replace(",", ""))
    return out


def test_miner_page_field_counts_shrink_to_the_scope_and_agreement_is_labelled(
    hub: tuple[Path, str, str], tmp_path: Path
) -> None:
    ui, _early, _late = hub
    whole = _dom(ui, tmp_path / "a", "miners.html", "#m=m-test")
    assert "2 of 2 papers in scope" in _text(whole) and "whole pass, not scoped" not in whole
    before = _bars(whole)
    assert sum(before.values()) >= 3 and before["Pro"] >= 1

    scoped = _dom(ui, tmp_path / "b", "miners.html", f"#m=m-test&scope.from={LATE}")
    text = _text(scoped)
    assert "1 of 2 papers in scope" in text
    after = _bars(scoped)
    assert set(after) == set(before)  # HS-24: a value with no paper in scope stays, as 0
    assert after["Other"] == 1 and after["Pro"] == 0 and after["Con"] == 0
    total = re.search(r'data-ftot="stance" data-n="(\d+)" data-of="(\d+)"', scoped)
    assert total and (total.group(1), total.group(2)) == ("1", "1")
    assert "0 of 1 examples in scope" in text and "No example falls in this scope" in text
    # HS-21: agreement and the other whole-pass panels keep their numbers and say so
    assert scoped.count('data-kind="pass"') >= 3
    for title in ("Two readings", "Agreement by model", "Disagreements by field"):
        a, b = _text(_section(whole, title)), _text(_section(scoped, title))
        assert "whole pass, not scoped" not in a and "whole pass, not scoped" in b
        assert re.sub(r"\s+", " ", b.replace("whole pass, not scoped", "")).strip() == a.strip(), (
            title
        )


def _section(dom: str, title: str) -> str:
    m = re.search(
        rf"<h2[^>]*>\s*{title}.*?(?=<section class=\"dsec\">|<div class=\"foot\">)", dom, flags=re.S
    )
    assert m, title
    return m.group(0)


def test_empty_scope_reads_zero_not_missing_rows(
    hub: tuple[Path, str, str], tmp_path: Path
) -> None:
    ui, _e, _l = hub
    dom = _dom(ui, tmp_path, "miners.html", "#m=m-test&scope.from=2030-01")
    assert "0 of 2 papers in scope" in _text(dom)
    after = _bars(dom)
    assert after["Pro"] == after["Con"] == after["Other"] == 0
    assert "0 of 1 examples in scope" in _text(dom)


def test_miners_gallery_scopes_the_coverage_ring(
    hub: tuple[Path, str, str], tmp_path: Path
) -> None:
    ui, _e, _l = hub
    whole = _text(_dom(ui, tmp_path / "a", "miners.html", ""))
    scoped_dom = _dom(ui, tmp_path / "b", "miners.html", f"#scope.from={LATE}")
    m = re.search(r"(\d+) of (\d+) papers in scope", whole)
    s = re.search(r"(\d+) of (\d+) papers in scope", _text(scoped_dom))
    assert m and s and m.group(1) == m.group(2) == s.group(2) and int(s.group(1)) < int(s.group(2))
    assert 'data-kind="pass"' in scoped_dom


def _grid_lead(dom: str) -> str:
    m = re.search(r'<p class="lead" id="lead"[^>]*>(.*?)</p>', dom, flags=re.S)
    assert m, dom[:300]
    return _text(m.group(1))


def test_data_grid_rows_blanks_and_totals_follow_the_scope(
    hub: tuple[Path, str, str], tmp_path: Path
) -> None:
    ui, _e, _l = hub
    base = "#miner=m-test"
    whole = _dom(ui, tmp_path / "a", "data.html", base)
    assert re.search(r"2 papers", _grid_lead(whole)) and "2 of 2 papers in scope" in _text(whole)
    scoped = _dom(ui, tmp_path / "b", "data.html", f"{base}&scope.from={LATE}")
    assert "1 of 2 papers in scope" in _text(scoped)
    assert re.search(r"\b1 papers", _grid_lead(scoped))
    assert len(re.findall(r'<tr><td class="t1">', scoped)) == 1
    assert re.search(r"Papers 1\u20131 of 1", _text(scoped))
    # the per-column blank count is recomputed from the rows in view
    assert re.search(r'<div class="em">— 0</div>', scoped)
    empty = _dom(ui, tmp_path / "c", "data.html", f"{base}&scope.from=2030-01")
    assert "0 of 2 papers in scope" in _text(empty) and "No paper matches" in _text(empty)


def test_data_coverage_recomputed_and_holes_labelled_whole_corpus(
    hub: tuple[Path, str, str], tmp_path: Path
) -> None:
    ui, _e, _l = hub
    whole = _dom(ui, tmp_path / "a", "data.html", "#view=coverage")
    scoped = _dom(ui, tmp_path / "b", "data.html", f"#view=coverage&scope.from={LATE}")

    def row(dom: str) -> list[int]:
        m = re.search(r"<td>Test</td>|<td>[^<]*[Tt]est[^<]*</td>", dom)
        assert m, dom[:200]
        cells = re.findall(r'<td class="n">([\d,]+)</td>', dom[m.end() : m.end() + 400])
        return [int(c.replace(",", "")) for c in cells[:3]]

    w, s = row(whole), row(scoped)
    assert w[0] == 2 and s[0] == 1 and s[0] + s[2] == 1
    holes = _dom(ui, tmp_path / "c", "data.html", f"#view=holes&scope.from={LATE}")
    assert 'data-kind="corpus"' in holes
