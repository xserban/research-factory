"""The tier modules import each other directly: a guarded `importlib` import with a silent
fallback would mask a rename and quietly drop a stop rule (`trust-pause`), a level or a skipped
list. Source scan; a lazy `from ... import` inside a function (an import cycle) is allowed."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "factory"
MODULES = (
    "services/conductor.py",
    "services/level_statement.py",
    "services/gates.py",
    "services/tier_caps.py",
    "services/hub_levels.py",
    "cli/conductor.py",
)


@pytest.mark.parametrize("module", MODULES)
def test_no_guarded_import_and_no_stale_merge_note(module: str) -> None:
    text = (SRC / module).read_text(encoding="utf-8")
    assert "importlib" not in text, module
    assert "ModuleNotFoundError" not in text, module
    assert not re.search(r"lane L\d+ (is )?not merged|while .* does not exist", text), module
