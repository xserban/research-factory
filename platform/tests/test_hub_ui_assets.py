"""Hub UI asset registry: every entry loads, versions are content hashes, and the
assets stay offline (no Google Fonts, no remote scripts) with GLOSSARY and LABELS
keys shared between shell.js and Python.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import pytest

from factory.services import hub_ui
from factory.services.hub_ui import ASSETS, GLOSSARY, LABELS, asset_bytes, asset_version

_HUB_DIR = Path(str(resources.files("factory").joinpath("hub_ui")))


def _read(name: str) -> str:
    return _HUB_DIR.joinpath(name).read_text(encoding="utf-8")


def _js_block_keys(source: str, start: str, key_pattern: str) -> set[str]:
    """Keys of the object literal that begins at `start` and ends at the next line '};'."""
    begin = source.index(start)
    end = source.index("\n};", begin)
    body = source[begin:end]
    return set(re.findall(key_pattern, body, flags=re.MULTILINE))


@pytest.mark.parametrize("name", sorted(ASSETS))
def test_every_asset_loads(name: str) -> None:
    data = asset_bytes(name)
    assert isinstance(data, bytes)
    assert len(data) > 0


@pytest.mark.parametrize("name", sorted(ASSETS))
def test_every_asset_file_is_in_package(name: str) -> None:
    rel, content_type = ASSETS[name]
    assert rel.startswith("hub_ui/")
    assert _HUB_DIR.joinpath(*rel.split("/")[1:]).is_file()
    assert content_type


def test_unknown_asset_raises_key_error() -> None:
    with pytest.raises(KeyError):
        asset_bytes("no-such-asset.css")


def test_asset_version_is_stable_and_short() -> None:
    first = asset_version()
    assert first == asset_version()
    assert re.fullmatch(r"[0-9a-f]{12}", first)


def test_asset_version_changes_when_bytes_change(monkeypatch: pytest.MonkeyPatch) -> None:
    before = asset_version()
    real = asset_bytes

    def changed(name: str) -> bytes:
        data = real(name)
        return data + b"/* changed */" if name == "kit.css" else data

    monkeypatch.setattr(hub_ui, "asset_bytes", changed)
    assert asset_version() != before


def test_kit_css_references_only_registered_fonts() -> None:
    css = _read("kit.css")
    assert "@font-face" in css
    urls = re.findall(r"url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)", css)
    assert urls, "kit.css should reference its vendored fonts"
    for url in urls:
        assert url in ASSETS, f"kit.css references unregistered asset {url}"
        assert url.startswith("fonts/") and url.endswith(".woff2")


def test_no_remote_font_or_script_in_hub_ui() -> None:
    for path in _HUB_DIR.rglob("*"):
        if path.suffix not in {".css", ".js", ".html", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "fonts.googleapis" not in text, path.name
        assert not re.search(r"<script\s+src=['\"]?https?:", text, flags=re.IGNORECASE), path.name
        assert "@import" not in text or "fonts.googleapis" not in text, path.name


def test_shell_glossary_keys_match_python() -> None:
    shell = _read("shell.js")
    js_keys = _js_block_keys(shell, "const GLOSSARY = {", r"^  ([A-Za-z]+):\[")
    assert js_keys == set(GLOSSARY)


def test_shell_labels_keys_match_python() -> None:
    shell = _read("shell.js")
    js_keys = _js_block_keys(shell, "const LABELS = {", r"'([a-z0-9-]+)'\s*:")
    assert js_keys == set(LABELS)


def test_shell_exports_init_and_never_reads_window_rf() -> None:
    shell = _read("shell.js")
    assert "function init(payload)" in shell
    assert "window.RF" not in shell


def test_shell_palette_points_at_hub_pages() -> None:
    shell = _read("shell.js")
    for page in (
        "overview",
        "corpus",
        "flow",
        "lenses",
        "explore",
        "graph",
        "miners",
        "data",
        "findings",
        "living",
        "kit",
    ):
        assert f"'{page}.html'" in shell, page
    assert "explorer/index.html" not in shell
    assert "results.html" not in shell


def test_rail_and_palette_list_exactly_the_registered_pages() -> None:
    shell = _read("shell.js")
    ids = list(hub_ui.PAGES)
    rail = re.search(r"const nav = \[(.*?)\];", shell, re.S)
    assert rail is not None
    rail_ids = re.findall(r"\['(\w+)','[^']*','(\w+)\.html'\]", rail.group(1))
    assert all(a == b for a, b in rail_ids)
    assert [a for a, _ in rail_ids] == [i for i in ids if i != "kit"]  # kit is design, off the rail
    pal = re.search(r"const PAGES = \[(.*?)\n\];", shell, re.S)
    assert pal is not None
    assert sorted(re.findall(r"'(\w+)\.html'", pal.group(1))) == sorted(ids)


def test_every_page_script_calls_load_init_and_mount() -> None:
    for spec in hub_ui.PAGES.values():
        src = _read(spec.script)
        assert "HUB.load([" in src and "HUB.init(d.shell)" in src and ".mount(" in src, spec.id
        for name in spec.payloads:
            assert f"'{name}'" in src, (spec.id, name)
