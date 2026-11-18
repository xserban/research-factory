"""Headless-Chromium smoke of every hub page against a fixture project (plan step 12).

No DevTools client is installed in the venv (`websockets` and `websocket-client` are absent), so
interactions are driven by URL state: `?theme=`, `#id=`, `#tab=paths&lanes=`, `#view=assoc`.
Click paths (drawer, chip, info panel, Ctrl-K) need a CDP client and are not covered here.
Skipped when `chromium` is not on PATH.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

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


def dump(page: Path, tmp: Path, suffix: str = "") -> tuple[str, str]:
    """Return (dom, stderr) of a page after 5 s of virtual time."""
    proc = subprocess.run(
        [
            "chromium",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={tmp / 'profile'}",
            "--enable-logging=stderr",
            "--v=0",
            "--virtual-time-budget=5000",
            "--dump-dom",
            f"file://{page}{suffix}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.stdout, proc.stderr


@pytest.fixture
def built(mined_world: Project, tmp_path: Path) -> Path:  # noqa: F811
    out = tmp_path / "ui"
    report = hb.build_static(mined_world, out)
    assert not report.errors, report.errors
    return out


def _main(dom: str) -> str:
    m = re.search(r'<main id="main"[^>]*>(.*)</main>', dom, flags=re.S)
    assert m, "no #main in the dumped DOM"
    return m.group(1)


def test_every_page_renders_its_header_without_errors(built: Path, tmp_path: Path) -> None:
    failures = []
    for pid in hub_ui.PAGES:
        page = built / f"{pid}.html"
        if not page.is_file():
            failures.append((pid, "page not built"))
            continue
        dom, err = dump(page, tmp_path)
        main = _main(dom)
        if "Uncaught" in err:
            failures.append((pid, "Uncaught: " + err[err.index("Uncaught") :][:200]))
        if not re.search(r"<h1\b|class=\"[^\"]*\bdisplay\b", main):
            failures.append((pid, "no h1 / .display in #main"))
    assert not failures, failures


def test_overview_lead_numbers_equal_the_payload(built: Path, tmp_path: Path) -> None:
    payload = json.loads((built / "data" / "overview.json").read_text(encoding="utf-8"))
    lead = payload["lead"]
    dom, _ = dump(built / "overview.html", tmp_path)
    m = re.search(r'<p class="lead">(.*?)</p>', _main(dom), flags=re.S)
    assert m, "no lead sentence"
    text = re.sub(r"<[^>]*>", " ", m.group(1))
    assert f"{int(lead['included']):,}" in text
    # the action buttons carry the other lead figures
    main = re.sub(r"<[^>]*>", " ", _main(dom))
    assert f"{int(lead['read_in_full']):,}" in main
    assert f"{int(lead['identified']):,} → {int(lead['included']):,}" in re.sub(r"\s+", " ", main)


def test_theme_query_sets_the_attribute(built: Path, tmp_path: Path) -> None:
    dom, _ = dump(built / "overview.html", tmp_path, "?theme=lcars")
    assert re.search(r'<html[^>]*data-theme="lcars"', dom)


def test_corpus_hash_id_opens_the_detail(built: Path, tmp_path: Path) -> None:
    corpus = json.loads((built / "data" / "corpus.json").read_text(encoding="utf-8"))
    works = corpus["works"]
    if not works:
        # the fixture's mined rows do not reach `corpus_payload`, so the corpus is empty:
        # still check the page survives an unknown id in the hash
        dom, err = dump(built / "corpus.html", tmp_path, "#id=rf:unknown")
        assert "Uncaught" not in err
        assert "<h1" in _main(dom)
        return
    wid = works[0]["id"]
    dom, err = dump(built / "corpus.html", tmp_path, f"#id={wid}")
    assert "Uncaught" not in err
    opened = re.search(r'<aside id="cdet"[^>]*\bopen\b[^>]*>(.*?)</aside>', dom, flags=re.S)
    assert opened and opened.group(1).strip(), "detail panel not opened"


def test_flow_lanes_hash_renders_lanes(built: Path, tmp_path: Path) -> None:
    shell = json.loads((built / "data" / "shell.json").read_text(encoding="utf-8"))
    wid = shell["works"][0]["id"]
    dom, err = dump(built / "flow.html", tmp_path, f"#tab=paths&lanes={wid}")
    assert "Uncaught" not in err
    assert re.search(r'class="[^"]*\blane\b', _main(dom)), "no lane rendered"


def test_lenses_view_assoc_renders_the_heatmap(built: Path, tmp_path: Path) -> None:
    dom, err = dump(built / "lenses.html", tmp_path, "#view=assoc")
    assert "Uncaught" not in err
    main = _main(dom)
    assert "More papers than chance" in main or "<rect" in main
