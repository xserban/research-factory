"""Scope on the Explore, Overview and Lenses pages (P1-09, first half; HS-03, HS-11, HS-20, HS-21, HS-24).

A built hub (the `mined_world` fixture) has its payloads rewritten so the works spread over three months
and one work is undated, then each page is loaded in headless Chromium with a scope in the address and the
DOM is read with `--dump-dom`. Per page: a date range changes the counts and the page says "n of N papers
in scope"; a panel that holds only whole-corpus aggregates carries the "whole corpus" label; an empty scope
shows the empty state and zero counts. Skipped without chromium.
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
from factory.services.context import Project
from tests.test_hub_build import mined_world, world  # noqa: F401  (fixtures)
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


def _read(ui: Path, name: str) -> Any:
    return json.loads((ui / f"data/{name}.json").read_text(encoding="utf-8"))


def spread(ui: Path) -> dict[str, str | None]:
    """Give every included work one of three months (May to July 2026), the first work none, in all
    payloads that carry `published`; month counts of the overview follow. Returns id -> published."""
    shell = _read(ui, "shell")
    pub: dict[str, str | None] = {}
    for i, w in enumerate(shell["works"]):
        pub[w["id"]] = None if i == 0 else f"2026-0{5 + i % 3}-10"

    def fix(row: dict[str, Any]) -> None:
        p = pub.get(row["id"])
        row["published"] = p or ""
        row["year"] = int(p[:4]) if p else None
        row["month"] = int(p[5:7]) if p else None

    for w in shell["works"]:
        fix(w)
    _write(ui, "shell", shell)
    ex = _read(ui, "explore")
    for w in ex["works"]:
        fix(w)
    _write(ui, "explore", ex)
    ov = _read(ui, "overview")
    for m in ov["most_cited"]:
        m["published"] = pub.get(m["id"]) or ""
    months = ["2026-05", "2026-06", "2026-07"]
    ov["papers_per_month"] = {
        "months": months,
        "counts": [sum(1 for p in pub.values() if p and p[:7] == m) for m in months],
    }
    _write(ui, "overview", ov)
    lz = _read(ui, "lenses")
    for it in lz["influence"]["items"]:
        it["published"] = pub.get(it["id"]) or ""
    _write(ui, "lenses", lz)
    return pub


def _cut(pub: dict[str, str | None]) -> tuple[str, int, int]:
    months = sorted({p[:7] for p in pub.values() if p})
    cut = months[len(months) // 2]
    inside = [p for p in pub.values() if p and p[:7] >= cut]
    assert 0 < len(inside) < len(pub)
    return cut, len(inside), len(pub)


def _text(dom: str, element_id: str) -> str:
    m = re.search(
        rf'<div id="{element_id}"[^>]*>(.*?)</div>\s*(?:<div|<section|<p)', dom, flags=re.S
    )
    assert m, (element_id, dom[:200])
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


@pytest.fixture
def built(mined_world: Project, tmp_path: Path) -> tuple[Path, dict[str, str | None]]:
    ui = tmp_path / "ui"
    report = hb.build_static(mined_world, ui)
    assert not report.errors, report.errors
    return ui, spread(ui)


def test_explore_counts_follow_the_scope_and_similar_is_labelled(
    built: tuple[Path, dict[str, str | None]], tmp_path: Path
) -> None:
    ui, pub = built
    cut, k, n = _cut(pub)
    ids = sorted(pub)
    whole = run_chromium(f"file://{ui}/explore.html", tmp_path)
    scoped = run_chromium(f"file://{ui}/explore.html#scope.from={cut}", tmp_path)
    assert _text(whole, "xscope").startswith(f"{n} of {n} papers in scope")
    assert _text(scoped, "xscope").startswith(f"{k} of {n} papers in scope")
    assert "1 paper has no date, held out of the count" in _text(scoped, "xscope")
    assert f"{k} of {k} papers in scope match this sentence" in re.sub(r"<[^>]+>", "", scoped)

    def legend_total(dom: str) -> int:
        leg = re.search(
            r'<div class="legend" id="legend">(.*?)</div>\s*</section>', dom, flags=re.S
        )
        assert leg
        return sum(int(x) for x in re.findall(r'<span class="n">(\d+)</span>', leg.group(1)))

    assert legend_total(scoped) == k  # the human-role legend counts papers in scope
    assert legend_total(whole) == n
    # the similar-papers panel is computed over the whole corpus: it says so
    pinned = run_chromium(
        f"file://{ui}/explore.html#pin={ids[1]}&sim={ids[1]}&scope.from={cut}", tmp_path
    )
    tray = re.search(r'<section class="tray" id="tray".*?</section>', pinned, flags=re.S)
    assert tray and 'data-kind="corpus"' in tray.group(0) and "whole corpus" in tray.group(0)


def test_explore_empty_scope_shows_the_empty_state_and_zero(
    built: tuple[Path, dict[str, str | None]], tmp_path: Path
) -> None:
    ui, pub = built
    dom = run_chromium(f"file://{ui}/explore.html#scope.from=2999-01", tmp_path)
    assert _text(dom, "xscope").startswith(f"0 of {len(pub)} papers in scope")
    assert 'id="xempty"' in dom and "No paper falls in this scope" in dom
    assert "data-scope-reset" in dom
    assert "0 of 0 papers in scope match this sentence" in re.sub(r"<[^>]+>", "", dom)


def test_overview_counts_follow_the_scope_and_aggregates_are_labelled(
    built: tuple[Path, dict[str, str | None]], tmp_path: Path
) -> None:
    ui, pub = built
    cut, k, n = _cut(pub)
    whole = run_chromium(f"file://{ui}/overview.html", tmp_path)
    scoped = run_chromium(f"file://{ui}/overview.html#scope.from={cut}", tmp_path)
    assert _text(whole, "ovScope").startswith(f"{n} of {n} papers in scope")
    assert _text(scoped, "ovScope").startswith(f"{k} of {n} papers in scope")

    def rows(dom: str, ident: str) -> list[int]:
        box = re.search(rf'<div class="ov-bd" id="{ident}">(.*?)</div>', dom, flags=re.S)
        assert box, ident
        return [int(x) for x in re.findall(r'<span class="ov-bd-val">(\d+) ·', box.group(1))]

    # the layer rows and the facet rows each add up to the papers in scope
    assert sum(rows(scoped, "ovS2Bd")) == k and sum(rows(whole, "ovS2Bd")) == n
    assert sum(rows(scoped, "ovS3Bd")) == k and sum(rows(whole, "ovS3Bd")) == n
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", scoped))
    assert f"n = {k} of {n} included" in flat  # the first chapter counts the papers in scope
    assert re.search(rf'id="ovBrowseN">{k}<', scoped)
    # the growth chapter: the busiest month is recomputed over the papers in scope
    months = [p[:7] for p in pub.values() if p and p[:7] >= cut]
    busiest = max(months.count(m) for m in set(months))
    assert re.search(rf'id="ovS5N"[^>]*>\s*Peak [A-Za-z]{{3}} \'\d\d: {busiest} ', scoped), busiest
    # headline, records pipeline and production line hold whole-corpus aggregates: labelled
    assert len(re.findall(r'data-kind="corpus"', scoped)) >= 3
    assert "whole corpus" in scoped


def test_overview_empty_scope_shows_the_empty_state_and_zero_rows(
    built: tuple[Path, dict[str, str | None]], tmp_path: Path
) -> None:
    ui, pub = built
    dom = run_chromium(f"file://{ui}/overview.html#scope.from=2999-01", tmp_path)
    assert _text(dom, "ovScope").startswith(f"0 of {len(pub)} papers in scope")
    assert (
        dom.count("No paper falls in this scope") >= 1
    )  # the story is replaced by the empty state
    assert "data-scope-reset" in dom
    assert re.search(r'id="ovBrowseN">0<', dom)
    vals = re.findall(r'<span class="ov-bd-val">(\d+) ·', dom)
    assert vals and set(vals) == {"0"}  # categories read 0, none missing


def test_lenses_lists_follow_the_scope_and_count_only_lenses_are_labelled(
    built: tuple[Path, dict[str, str | None]], tmp_path: Path
) -> None:
    ui, pub = built
    cut, k, n = _cut(pub)
    whole = run_chromium(f"file://{ui}/lenses.html#lens=swarm", tmp_path)
    scoped = run_chromium(f"file://{ui}/lenses.html#lens=swarm&scope.from={cut}", tmp_path)
    assert _text(whole, "lscope").startswith(f"{n} of {n} papers in scope")
    assert _text(scoped, "lscope").startswith(f"{k} of {n} papers in scope")

    def dots(dom: str) -> int:
        chart = re.search(r'<div id="chart">(.*?)</div></div>', dom, flags=re.S)
        assert chart
        return len(re.findall(r"<circle", chart.group(1)))

    assert dots(whole) == n
    assert dots(scoped) == k  # influence recomputed over the papers in scope
    # the design space is a server-side count table: whole corpus, labelled, not presented as scoped
    matrix = run_chromium(f"file://{ui}/lenses.html#lens=matrix&scope.from={cut}", tmp_path)
    assert 'class="meta lens-whole"' in matrix and "whole corpus" in matrix
    unscoped = run_chromium(f"file://{ui}/lenses.html#lens=matrix", tmp_path)
    assert "lens-whole" not in unscoped
    # the lens switcher carries the scope
    assert f'href="#lens=wall&amp;scope.from={cut}"' in matrix


def test_lenses_empty_scope_shows_the_empty_state(
    built: tuple[Path, dict[str, str | None]], tmp_path: Path
) -> None:
    ui, pub = built
    dom = run_chromium(f"file://{ui}/lenses.html#lens=swarm&scope.from=2999-01", tmp_path)
    assert _text(dom, "lscope").startswith(f"0 of {len(pub)} papers in scope")
    assert 'id="lempty"' in dom and "data-scope-reset" in dom
    chart = re.search(r'<div id="chart">(.*?)</div></div>', dom, flags=re.S)
    assert chart and "<circle" not in chart.group(
        1
    )  # the lens-switcher glyphs hold circles; the chart none
