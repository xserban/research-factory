"""Depth, name match, kernel, helper, coverage map and sharding rules of scripts/affected_tests.py,
on a small synthetic repo (the module's REPO, SRC and TESTS are pointed at it)."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "affected_tests.py"
S = "platform/src/factory/"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("affected_tests_depth", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Any:
    """Src chain leaf <- mid <- top; kernel events/k <- mid2 <- top2; a helper; various tests."""
    _write(tmp_path, S + "__init__.py")
    for pkg in ("services", "events"):
        _write(tmp_path, f"{S}{pkg}/__init__.py")
    _write(tmp_path, S + "services/leaf.py", "X = 1\n")
    _write(tmp_path, S + "services/mid.py", "from factory.services import leaf\n")
    _write(tmp_path, S + "services/top.py", "from factory.services import mid\n")
    _write(tmp_path, S + "services/solo.py", "Y = 1\n")
    _write(tmp_path, S + "events/kcore.py", "K = 1\n")
    _write(tmp_path, S + "events/mid2.py", "from factory.events import kcore\n")
    _write(tmp_path, S + "events/top2.py", "from factory.events import mid2\n")
    t = "platform/tests/"
    _write(tmp_path, t + "helpers.py", "from factory.services import leaf\n")
    _write(tmp_path, t + "test_direct_leaf.py", "from factory.services.leaf import X\n")
    _write(tmp_path, t + "test_via_mid.py", "import factory.services.mid\n")
    _write(tmp_path, t + "test_via_top.py", "from factory.services import top\n")
    _write(tmp_path, t + "test_uses_helper.py", "from tests import helpers\n")
    _write(tmp_path, t + "test_solo_extra.py", "pass\n")
    _write(tmp_path, t + "test_services_solo_more.py", "pass\n")
    _write(tmp_path, t + "test_kernel_user.py", "from factory.events import kcore\n")
    _write(tmp_path, t + "test_kernel_two.py", "from factory.events import mid2\n")
    _write(tmp_path, t + "test_kernel_three.py", "from factory.events import top2\n")
    module = _load()
    module.REPO = tmp_path
    module.SRC = tmp_path / "platform" / "src"
    module.TESTS = tmp_path / "platform" / "tests"
    module.ALWAYS = ()
    return module


def _sel(m: Any, changed: list[str], **kw: object) -> set[str]:
    mode, names = m.select(changed, **kw)
    assert mode == "touched"
    return set(names)


def test_depth_one_selects_direct_importers_only(tree: Any) -> None:
    got = _sel(tree, [S + "services/leaf.py"])
    assert "test_direct_leaf.py" in got  # a direct importer is always selected
    assert "test_via_mid.py" not in got and "test_via_top.py" not in got


def test_depth_two_and_the_old_closure_reach_further(tree: Any) -> None:
    got2 = _sel(tree, [S + "services/leaf.py"], closure=2)
    assert {"test_direct_leaf.py", "test_via_mid.py"} <= got2 and "test_via_top.py" not in got2
    assert "test_via_top.py" in _sel(tree, [S + "services/leaf.py"], closure=99)


def test_name_match_selects_test_files_named_after_the_module(tree: Any) -> None:
    assert _sel(tree, [S + "services/solo.py"]) == {
        "test_solo_extra.py",
        "test_services_solo_more.py",
    }


def test_kernel_changes_use_depth_two_unless_closure_is_given(tree: Any) -> None:
    got = _sel(tree, [S + "events/kcore.py"])
    assert {"test_kernel_user.py", "test_kernel_two.py"} <= got
    assert "test_kernel_three.py" not in got
    assert "test_kernel_two.py" not in _sel(tree, [S + "events/kcore.py"], closure=1)
    assert tree.depth_for([S + "services/leaf.py"], None) == 1
    assert tree.depth_for([S + "events/kcore.py"], None) == 2


def test_a_changed_helper_selects_its_importers_and_a_changed_test_itself(tree: Any) -> None:
    assert "test_uses_helper.py" in _sel(tree, ["platform/tests/helpers.py"])
    assert "test_solo_extra.py" in _sel(tree, ["platform/tests/test_solo_extra.py"])


def test_a_package_reexport_resolves_to_the_defining_module(tree: Any) -> None:
    _write(tree.REPO, S + "services/__init__.py", "from .leaf import X\n")
    _write(tree.REPO, "platform/tests/test_reexport.py", "from factory.services import X\n")
    assert "test_reexport.py" in _sel(tree, [S + "services/leaf.py"])


def _map(tree: Any, tests: dict[str, list[str]], generated: str = "2026-11-23") -> Path:
    path: Path = tree.REPO / "map.json"
    path.write_text(json.dumps({"generated": generated, "tests": tests, "durations": {"a": 1}}))
    return path


def test_suite_wide_files_select_all_even_with_a_map(tree: Any) -> None:
    cover = tree.CoverageMap("2026-11-23", {"test_solo_extra.py": frozenset()}, {})
    assert tree.select([".github/workflows/tests.yml"], None, cover) == ("all", [])


def test_the_map_selects_tests_whose_recorded_files_overlap(tree: Any) -> None:
    path = _map(
        tree,
        {
            "test_via_top.py": ["src/factory/services/leaf.py"],
            "test_solo_extra.py": ["src/factory/services/solo.py"],
        },
    )
    cover, why = tree.load_map(path, 7, date(2026, 11, 24))
    assert cover is not None and "2026-11-23" in why
    got = _sel(tree, [S + "services/leaf.py"], cover=cover)
    # recorded overlap selects test_via_top; the import rules are not used for a known file
    assert "test_via_top.py" in got and "test_direct_leaf.py" not in got


def test_a_file_absent_from_the_map_falls_back_to_the_import_rules(tree: Any) -> None:
    path = _map(tree, {"test_solo_extra.py": ["src/factory/services/solo.py"]})
    cover, _ = tree.load_map(path, 7, date(2026, 11, 24))
    got = _sel(tree, [S + "services/leaf.py"], cover=cover)
    assert "test_direct_leaf.py" in got and "test_via_top.py" not in got


def test_a_stale_or_missing_or_broken_map_is_ignored(tree: Any) -> None:
    path = _map(tree, {"test_solo_extra.py": ["src/factory/services/leaf.py"]}, "2026-11-01")
    cover, why = tree.load_map(path, 7, date(2026, 11, 24))
    assert cover is None and "23 days old" in why
    assert tree.load_map(tree.REPO / "nope.json")[0] is None
    (tree.REPO / "bad.json").write_text("{")
    assert tree.load_map(tree.REPO / "bad.json")[0] is None
    assert "test_direct_leaf.py" in _sel(tree, [S + "services/leaf.py"], cover=cover)


def test_shards_are_balanced_by_duration_and_deterministic(tree: Any) -> None:
    files = [f"test_{i}.py" for i in range(8)]
    durations = {"test_0.py": 100.0, "test_1.py": 50.0, "test_2.py": 50.0}
    shards = tree.split_shards(files, 2, durations)
    assert sum(len(s) for s in shards) == 8 and shards == tree.split_shards(files, 2, durations)
    assert "test_0.py" in shards[0] and {"test_1.py", "test_2.py"} <= set(shards[1])


def test_browser_files_are_recognised(tree: Any) -> None:
    assert tree.is_browser("test_hub_ui_clicks.py") and not tree.is_browser("test_other.py")
