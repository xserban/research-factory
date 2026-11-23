"""The test selector used by the Tests workflow on pull requests (scripts/affected_tests.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "affected_tests.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("affected_tests", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_suite_wide_file_selects_everything() -> None:
    mode, names = _load().select(["platform/tests/conftest.py"])
    assert mode == "all" and names == []


def test_a_docs_only_change_runs_the_always_set() -> None:
    module = _load()
    mode, names = module.select(["docs/backlog.md"])
    assert mode == "touched"
    assert set(module.ALWAYS) <= set(names)
    assert len(names) < 30


def test_a_changed_test_file_selects_itself_and_the_always_set() -> None:
    module = _load()
    mode, names = module.select(["platform/tests/test_affected_tests.py"])
    assert mode == "touched" and "test_affected_tests.py" in names
    assert set(module.ALWAYS) <= set(names)


def test_a_changed_source_module_selects_the_tests_that_import_it() -> None:
    module = _load()
    importers, files = module.build_graph()
    target = "factory.services.finders"
    assert target in files
    direct = {
        Path(files[m]).name
        for m in module._closure({target}, importers, 1, files)
        if m.startswith("tests.test_")
    }
    mode, names = module.select(["platform/src/factory/services/finders.py"])
    assert mode == "touched" and direct <= set(names)
    assert "test_finder_gaps.py" in names


def test_a_package_import_does_not_tie_its_importers_together(tmp_path: Path) -> None:
    module = _load()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("X = 1\n")
    (tmp_path / "pkg" / "b.py").write_text("Y = 2\n")
    probe = tmp_path / "t.py"
    probe.write_text("from pkg import a\n")
    found = module._imports(probe, "t", {"pkg.a", "pkg.b", "pkg"})
    assert found == {"pkg.a"}


def test_every_selected_path_exists_and_subfolders_are_kept() -> None:
    module = _load()
    tests_dir = SCRIPT.parent.parent / "platform" / "tests"
    for changed in (
        ["platform/src/factory/services/finders.py"],
        ["platform/src/factory/document/quotes.py"],
        ["docs/backlog.md"],
        ["plugin/skills/rf-run/SKILL.md"],
    ):
        mode, names = module.select(changed)
        assert mode == "touched"
        missing = [n for n in names if not (tests_dir / n).is_file()]
        assert missing == [], (changed, missing)
    nested = [n for n in module.all_test_files() if "/" in n]
    assert nested and all((tests_dir / n).is_file() for n in nested)
