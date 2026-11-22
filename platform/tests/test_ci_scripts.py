"""The CI helper scripts: scripts/check_map_fresh.py and scripts/quality_trend.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

MAP = "# Map\n\nGenerated at commit `abc1234` · 3 modules.\n\nbody\n"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_map_check_passes_when_only_the_commit_differs(tmp_path: Path) -> None:
    (tmp_path / "MAP.md").write_text(MAP)
    (tmp_path / "gen.md").write_text(MAP.replace("abc1234", "def5678"))
    code = _load("check_map_fresh").main(
        ["--map", str(tmp_path / "MAP.md"), "--generated", str(tmp_path / "gen.md")]
    )
    assert code == 0


def test_map_check_fails_when_the_body_differs(tmp_path: Path) -> None:
    (tmp_path / "MAP.md").write_text(MAP)
    (tmp_path / "gen.md").write_text(MAP.replace("body", "new body"))
    code = _load("check_map_fresh").main(
        ["--map", str(tmp_path / "MAP.md"), "--generated", str(tmp_path / "gen.md")]
    )
    assert code == 1


def test_trend_line_has_the_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load("quality_trend")
    monkeypatch.setattr(module, "ruff_findings", lambda: 0)
    out = tmp_path / "trend.jsonl"
    assert module.main(["--out", str(out), "--fast"]) == 0
    assert module.main(["--out", str(out), "--fast"]) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert {
        "date",
        "commit",
        "tests_collected",
        "ruff_findings",
        "mypy_errors",
        "py_files",
        "modules",
        "test_files",
    } <= set(record)
    assert record["modules"] > 0 and record["test_files"] > 0
