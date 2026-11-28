"""The Overview page is project-neutral (the researcher's ruling of 2026-11-28; HS-63, HS-65).

A built hub (the `mined_world` fixture) has its `shell` and `overview` payloads rewritten as a project that
has none of the first pilot's categories: its own layer names, a fourth facet slot with other values and
another label, no "human role". The page is loaded in headless Chromium; it must raise no script error
(the click driver of `test_hub_ui_clicks`), name no pilot category, show the project's own labels, and
leave out the facet chapter when the project has no such facet. Skipped without chromium.
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
from tests.test_hub_ui_clicks import _drive
from tests.test_hub_ui_scope_bar import run_chromium

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH"),
]

LAYERS = ["chest-scans", "general-models", "unlayered"]
PILOT_WORDS = [
    "Human role",
    "human in the loop",
    "Where the human sits",
    "Human involved",
    "50% meridian",
]


def _rewrite(ui: Path, name: str, data: Any) -> None:
    (ui / f"data/{name}.json").write_text(json.dumps(data), encoding="utf-8")
    (ui / f"data/{name}.js").write_text(
        'window.HUB_DATA=window.HUB_DATA||{};HUB_DATA["' + name + '"]=' + json.dumps(data) + ";\n",
        encoding="utf-8",
    )


def neutral(ui: Path, *, facet: bool) -> None:
    """Rewrite the payloads: own layers; a fourth slot labelled 'Language component' (or no such slot)."""
    shell = json.loads((ui / "data/shell.json").read_text(encoding="utf-8"))
    ov = json.loads((ui / "data/overview.json").read_text(encoding="utf-8"))
    layer_of: dict[str, str] = {}
    cl: dict[str, int] = {}
    ch: dict[str, int] = {}
    for i, w in enumerate(shell["works"]):
        w["layer"] = layer_of[w["id"]] = LAYERS[i % len(LAYERS)]
        v = ("decoder", "encoder", None)[i % 3] if facet else None
        w["human"] = {"v": v, "q": "a quote"} if v else None
        cl[w["layer"]] = cl.get(w["layer"], 0) + 1
        ch[v or "null"] = ch.get(v or "null", 0) + 1
    shell["fields"] = [["technique", "Training objective"]] + (
        [["human", "Language component"]] if facet else []
    )
    ov["composition"] = {"layer": cl, "human": ch}
    n = len(shell["works"])
    coded = n - ch.get("null", 0)
    ov["lead"]["human"] = {
        "coded": coded,
        "none": 0,
        "not_coded": ch.get("null", 0),
        "share_none": 0,
    }
    for m in ov["most_cited"]:
        m["layer"] = layer_of.get(m["id"], "unlayered")
    _rewrite(ui, "shell", shell)
    _rewrite(ui, "overview", ov)


@pytest.fixture
def built(mined_world: Project, tmp_path: Path) -> Path:
    ui = tmp_path / "ui"
    report = hb.build_static(mined_world, ui)
    assert not report.errors, report.errors
    return ui


def _text(dom: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dom))


def test_overview_names_the_projects_own_layers_and_facet(built: Path, tmp_path: Path) -> None:
    neutral(built, facet=True)
    result = _drive(built / "overview.html")
    assert result["done"] and not result["errors"], result["errors"][:5]
    dom = run_chromium(f"file://{built}/overview.html", tmp_path)
    flat = _text(dom)
    for word in PILOT_WORDS:
        assert word not in flat, word
    assert "Language component" in flat  # the facet chapter carries the project's label
    assert (
        "Chest scans" in flat and "General models" in flat
    )  # the project's layers, not the pilot's
    assert "Decoder" in flat and "Encoder" in flat  # the facet's values
    assert "of the systems run with" not in flat  # no pilot sentence about the share of one value
    assert re.search(r'id="ovStageNum"[^>]*>\s*01 / 06', dom)


def test_overview_leaves_out_the_facet_chapter_when_the_project_has_none(
    built: Path, tmp_path: Path
) -> None:
    neutral(built, facet=False)
    result = _drive(built / "overview.html")
    assert result["done"] and not result["errors"], result["errors"][:5]
    dom = run_chromium(f"file://{built}/overview.html", tmp_path)
    flat = _text(dom)
    for word in PILOT_WORDS:
        assert word not in flat, word
    assert re.search(r'id="ovStep-3"[^>]*style="display: none;"', dom) or re.search(
        r'<article[^>]*id="ovStep-3"[^>]*hidden', dom
    )
    assert re.search(r'id="ovStageNum"[^>]*>\s*01 / 05', dom)
    assert len(re.findall(r'data-jump="\d"', dom)) == 5
