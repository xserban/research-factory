"""The stage map at the top of the capability page: stations, counts, escaping, theme-safe CSS."""

from __future__ import annotations

import json
import re
from pathlib import Path

from factory.services.site_catalog import STAGE_IDS, Catalog, ToolSpec
from factory.services.site_catalog_page import render, stage_summary
from factory.services.site_chrome import BAR_CSS
from tests.test_site_catalog import _derive, _skill


def _tool(name: str, desc: str = "does a thing") -> ToolSpec:
    return ToolSpec(name=name, description=desc, input_schema_json="{}", params=())


def _cat(tmp_path: Path) -> Catalog:
    _skill(tmp_path, "rf-a", "frame", "1. Call `tool_one` now.\n")
    _skill(tmp_path, "rf-b", "frame", "1. Call `tool_one` and `tool_two`.\n")
    _skill(tmp_path, "rf-c", "screen", "1. Call `tool_three`.\n")
    tools = [
        _tool("tool_one"),
        _tool("tool_two"),
        _tool("tool_three", "x </script><b>y</b>\nsecond line"),
        _tool("tool_loose"),
    ]
    return _derive(tmp_path, tools)


def test_summary_counts_match_catalog(tmp_path: Path) -> None:
    cat = _cat(tmp_path)
    rows = {r["id"]: r for r in stage_summary(cat)}
    assert [r["id"] for r in stage_summary(cat) if r["id"] != "unassigned"] == list(STAGE_IDS)
    for sid in STAGE_IDS:
        assert rows[sid]["n_tools"] == sum(1 for t in cat.tools if t.stage == sid)
        assert rows[sid]["n_skills"] == sum(1 for s in cat.skills if s.stages[:1] == (sid,))
    assert rows["frame"]["n_skills"] == 2
    assert "unassigned" in rows
    assert rows["unassigned"]["n_tools"] == sum(1 for t in cat.tools if t.stage is None)
    total = sum(r["n_tools"] for r in rows.values())
    assert total == len(cat.tools)


def test_unassigned_station_only_when_needed(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "1. Call `tool_one` now.\n")
    cat = _derive(tmp_path, [_tool("tool_one")])
    assert all(r["id"] != "unassigned" for r in stage_summary(cat))
    html = render(cat, "now", "code")
    assert "id='st-unassigned'" not in html
    assert all(f"id='st-{s}'" in html for s in STAGE_IDS)


def test_page_has_stations_and_old_sections(tmp_path: Path) -> None:
    html = render(_cat(tmp_path), "now", "code")
    assert "id='st-frame'" in html and "id='st-unassigned'" in html
    assert html.index("id='st-frame'") < html.index("<h2 id='frame'>")
    assert "<h2>Flags</h2>" in html and "<h2>Marked tools</h2>" in html


def test_data_json_escapes_script_end(tmp_path: Path) -> None:
    html = render(_cat(tmp_path), "now", "code")
    m = re.search(r"<script type=application/json id=cmap-data>(.*?)</script>", html, re.S)
    assert m is not None
    assert "</" not in m.group(1)
    data = json.loads(m.group(1))
    assert any("</script>" in t["d"] for s in data["stages"] for t in s["tools"])
    assert html.count("</script>") == html.count("<script")


def test_no_hard_coded_colours_in_map(tmp_path: Path) -> None:
    html = render(_cat(tmp_path), "now", "code")
    start = html.index("/*cmap*/")
    end = html.index("/*end cmap*/")
    css = html[start:end]
    css = re.sub(r"var\(--[a-z-]+,\s*#[0-9a-fA-F]{3,8}\)", "", css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert "animation" not in css


def test_page_uses_the_kit_frame(tmp_path: Path) -> None:
    html = render(_cat(tmp_path), "now", "code")
    assert "kit.css" in html and "main-hub.css" in html
    assert html.count("class=hubbar") == 1
    own = [c for c in re.findall(r"<style>(.*?)</style>", html, re.S) if c != BAR_CSS]
    assert any(".ct-figs" in c for c in own)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", "".join(own))
    assert "Count check passed" in html or "Count check failed" in html
