"""Scope on the Findings and Landscape pages (P1-09, second half; HS-03, HS-11, HS-20, HS-21, HS-24).

A built hub (the `mined_world` fixture, whose findings and landscape payloads are empty) gets those two payloads
replaced by the unit fixtures of tests/test_hub_findings.py and tests/test_hub_landscape.py, and the shell works
replaced by ten works with dates (one undated). Each page is loaded in headless Chromium with a scope in the
address and the DOM is read with `--dump-dom`. Per page: a date range changes the counts, the page says
"n of N papers in scope", a panel the scope cannot cut carries the "whole corpus" label; an empty scope shows the
empty state, the reset button and zero counts. Skipped without chromium.
"""

# ruff: noqa: E501, F811  (fixtures)

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from factory.services import hub_build as hb
from factory.services import hub_findings as hf
from factory.services import hub_landscape as hl
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
from tests.test_hub_findings import LAYERS, RANK, W, fixture_data
from tests.test_hub_landscape import data as landscape_data
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)
from tests.test_hub_ui_scope_bar import run_chromium

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH"),
]


def _write(ui: Path, name: str, data: Any) -> None:
    (ui / f"data/{name}.json").write_text(json.dumps(data), encoding="utf-8")
    (ui / f"data/{name}.js").write_text(
        'window.HUB_DATA=window.HUB_DATA||{};HUB_DATA["' + name + '"]=' + json.dumps(data) + ";\n",
        encoding="utf-8",
    )


def _plain(dom: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dom))


def _line(dom: str, element_id: str) -> str:
    m = re.search(
        rf'<div id="{element_id}"[^>]*>(.*?)</div>\s*(?:<div|<section|<p)', dom, flags=re.S
    )
    assert m, (element_id, dom[:200])
    return _plain(m.group(1)).strip()


# ---------------------------------------------------------------- findings

FPUB: dict[str, str | None] = {
    w: None if i == 0 else f"2026-0{5 + i % 3}-10" for i, w in enumerate(W)
}
FCUT = "2026-06"
F_IN = {w for w, p in FPUB.items() if p and p[:7] >= FCUT}


def _shell_work(base: dict[str, Any], w: str) -> dict[str, Any]:
    p = FPUB[w]
    return {
        **base,
        "id": w,
        "title": f"Title {w}",
        "published": p or "",
        "year": int(p[:4]) if p else None,
        "month": int(p[5:7]) if p else None,
    }


@pytest.fixture
def findings_hub(mined_world: Project, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    ui = tmp_path / "ui"
    report = hb.build_static(mined_world, ui)
    assert not report.errors, report.errors
    shell = json.loads((ui / "data/shell.json").read_text(encoding="utf-8"))
    base = shell["works"][0]
    shell["works"] = [_shell_work(base, w) for w in W]
    _write(ui, "shell", shell)
    payload = hf.findings_from(fixture_data(), layers=LAYERS, rank=RANK)
    _write(ui, "findings", payload)
    return ui, payload


def _card(dom: str, rule: str) -> str:
    m = re.search(rf'<article class="fc" data-f="{rule}">.*?</article>', dom, flags=re.S)
    assert m, rule
    return m.group(0)


def _big(dom: str, rule: str) -> int:
    m = re.search(r'<div class="big">(\d+)', _card(dom, rule))
    assert m
    return int(m.group(1))


def test_findings_counts_follow_the_scope_and_shares_are_labelled(
    findings_hub: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    ui, payload = findings_hub
    n, k = len(W), len(F_IN)
    whole = run_chromium(f"file://{ui}/findings.html", tmp_path)
    scoped = run_chromium(f"file://{ui}/findings.html#scope.from={FCUT}", tmp_path)
    assert _line(whole, "fscope").startswith(f"{n} of {n} papers in scope")
    assert _line(scoped, "fscope").startswith(f"{k} of {n} papers in scope")
    card = next(c for c in payload["cards"] if c["rule"] == "no_human")
    assert card["available"]
    behind = sum(1 for i in card["ids"] if i in F_IN)
    assert behind < len(card["ids"]), "the cut must change the card"
    # without a scope the card is a share; with one it counts the papers in scope behind it, never the share
    assert _big(whole, "no_human") == round(100 * card["numerator"] / card["denominator"])
    assert _big(scoped, "no_human") == behind
    assert f"{behind} of {len(card['ids'])} papers behind this card are in scope" in _plain(
        _card(scoped, "no_human")
    )
    # the sentence, the share and the value distribution are whole-corpus aggregates: labelled
    assert 'data-kind="corpus"' in _card(scoped, "no_human") and "whole corpus" in _card(
        scoped, "no_human"
    )
    assert 'data-kind="corpus"' not in whole
    # the research-cycle tiles count the papers in scope that automate each stage
    stage = payload["cycle"]["stages"][0]
    tile = re.search(
        rf'<button type="button" class="stg" data-s="{stage["stage"]}".*?</button>',
        scoped,
        flags=re.S,
    )
    assert tile
    assert re.search(r'<span class="pc">(\d+)<small>', tile.group(0)).group(1) == str(  # type: ignore[union-attr]
        sum(1 for i in stage["ids"] if i in F_IN)
    )


def test_findings_empty_scope_shows_the_empty_state_and_zero(
    findings_hub: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    ui, _ = findings_hub
    dom = run_chromium(f"file://{ui}/findings.html#scope.from=2999-01", tmp_path)
    assert _line(dom, "fscope").startswith(f"0 of {len(W)} papers in scope")
    assert 'id="fempty"' in dom and "No paper falls in this scope" in dom
    assert "data-scope-reset" in dom
    assert 'class="fc"' not in dom  # no card shows a number for an empty scope


# ---------------------------------------------------------------- landscape

LAND_CUT = "2022-01"


@pytest.fixture
def landscape_hub(mined_world: Project, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    ui = tmp_path / "ui"
    report = hb.build_static(mined_world, ui)
    assert not report.errors, report.errors
    payload, uses = hl.landscape_payloads(landscape_data())
    _write(ui, "landscape", payload)
    _write(ui, "landscape_uses", uses)
    return ui, payload


def _in_core(payload: dict[str, Any], cut: str | None) -> tuple[int, int]:
    """(papers, approaches) of the default lens (core layer) over the works dated from `cut` on."""
    works = {
        i
        for i, w in enumerate(payload["works"])
        if w["layer"] == "core" and (cut is None or (w["published"] and w["published"][:7] >= cut))
    }
    rows = [r for r in payload["rows"] if r[1] in works]
    return len({r[1] for r in rows}), len({r[0] for r in rows})


def _lead(dom: str) -> tuple[int, int]:
    m = re.search(
        r'<p class="lead">.*?<b>(\d+)</b> papers use <b>(\d+)</b> approaches', dom, flags=re.S
    )
    assert m, "lead sentence missing"
    return int(m.group(1)), int(m.group(2))


def test_landscape_counts_follow_the_scope_and_server_aggregates_are_labelled(
    landscape_hub: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    ui, payload = landscape_hub
    n = len(payload["works"])
    k = sum(1 for w in payload["works"] if w["published"] and w["published"][:7] >= LAND_CUT)
    assert 0 < k < n
    whole = run_chromium(f"file://{ui}/landscape.html", tmp_path)
    scoped = run_chromium(f"file://{ui}/landscape.html#scope.from={LAND_CUT}", tmp_path)
    assert _line(whole, "lscope").startswith(f"{n} of {n} papers in scope")
    assert _line(scoped, "lscope").startswith(f"{k} of {n} papers in scope")
    assert _lead(whole) == _in_core(payload, None)
    assert _lead(scoped) == _in_core(payload, LAND_CUT)
    assert _lead(scoped) != _lead(whole)
    # set-aside counts, agreement, the default-lens co-use list, candidates and the loaded-set note are the
    # server's whole-corpus aggregates: labelled
    assert len(re.findall(r'data-kind="corpus"', scoped)) >= 4 and "whole corpus" in scoped
    assert 'data-kind="corpus"' not in whole


def test_landscape_empty_scope_shows_the_empty_state_and_zero(
    landscape_hub: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    ui, payload = landscape_hub
    dom = run_chromium(f"file://{ui}/landscape.html#scope.from=2999-01", tmp_path)
    assert _line(dom, "lscope").startswith(f"0 of {len(payload['works'])} papers in scope")
    assert 'id="lsempty"' in dom and "No paper falls in this scope" in dom
    assert "data-scope-reset" in dom
    assert _lead(dom) == (0, 0)
