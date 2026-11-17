"""The explorer selects works and exports them through the hub's route (IDEA-87): the controls,
the per-row checkbox, the request and the download, and a rebuild that carries the new page."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from factory.services import site
from factory.services.site_explorer_page import PAGE


def test_the_page_has_the_export_controls_and_a_count() -> None:
    for ident in ("exall", "exclear", "expdf", "exgo", "exmsg"):
        assert f'id="{ident}"' in PAGE
    assert "Select all in filter" in PAGE
    assert "'Export selected ('+n+')'" in PAGE
    assert "not records" in PAGE


def test_each_list_row_has_a_checkbox_that_does_not_open_the_detail() -> None:
    assert 'class="xs" data-id="${esc(w.id)}"' in PAGE
    assert "c.onclick=e=>e.stopPropagation()" in PAGE
    assert "filtered().forEach(w=>SELX.add(w.id))" in PAGE


def test_the_export_posts_the_ids_with_the_token_and_downloads_a_zip() -> None:
    assert "fetch(API+'/api/export/works'" in PAGE
    assert "'X-Factory-Token':TOKEN" in PAGE
    assert "work_ids:[...SELX],pdfs:$('#expdf').checked" in PAGE
    assert "application/zip" in PAGE and "a.download=" in PAGE
    assert "Open this page with factory site serve to export." in PAGE


def test_the_script_parses() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = re.search(r"<script>(.*?)</script>", PAGE.split("</head>", 1)[1], re.S)
    assert script is not None
    result = subprocess.run(
        [node, "--check", "-"], input=script.group(1), capture_output=True, text=True
    )
    # `const DATA=/*DATA*/null;` is valid JavaScript as it stands
    assert result.returncode == 0, result.stderr


def test_the_build_code_hash_covers_the_page_module() -> None:
    """The product fingerprint holds `code_hash`, a hash of every `site*.py`; the page is such a
    module, so a changed page makes the explorer stale and the hub's rebuilder rebuilds it."""
    here = Path(site.__file__).parent
    assert (here / "site_explorer_page.py") in set(here.glob("site*.py"))
