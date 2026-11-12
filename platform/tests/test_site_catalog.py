# ruff: noqa: E501
"""Derivation and flags of the capability catalog (plan catalog). Written per TDD; not run while
testing is paused."""

from __future__ import annotations

from pathlib import Path

from factory.services.site_catalog import (
    Catalog,
    ToolSpec,
    derive_catalog,
    parse_frontmatter,
    registered_names,
)
from factory.services.site_catalog_page import render


def _tool(name: str, *params: str) -> ToolSpec:
    return ToolSpec(
        name=name, description=f"{name} does a thing", input_schema_json="{}", params=params
    )


def _skill(root: Path, name: str, stage: str | None, body: str) -> None:
    d = root / "skills" / name
    d.mkdir(parents=True)
    head = f"---\nname: {name}\ndescription: Use when {name}: it runs.\n"
    if stage is not None:
        head += f"stage: {stage}\n"
    (d / "SKILL.md").write_text(head + "---\n\n" + body, encoding="utf-8")


def _decisions(path: Path) -> Path:
    path.write_text(
        "| # | Title | Status |\n|---|---|---|\n| 1 | A | Decided | x |\n| 2 | B | Proposed (maybe) | y |\n",
        encoding="utf-8",
    )
    return path


def _derive(tmp_path: Path, tools: list[ToolSpec], registered: list[str] | None = None) -> Catalog:
    return derive_catalog(
        tools,
        tmp_path / "skills",
        _decisions(tmp_path / "decisions.md"),
        registered if registered is not None else [t.name for t in tools],
        0,
        root=tmp_path,
    )


def test_frontmatter_reads_colons_and_stage_lists() -> None:
    fm, lists = parse_frontmatter(
        "---\nname: x\ndescription: a: b\nstage: [screen, acquire]\n---\n"
    )
    assert fm["description"] == "a: b"
    assert lists["stage"] == ["screen", "acquire"]


def test_primary_stage_is_earliest_and_each_tool_once(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "write", "1. Call `tool_one` now.\n")
    _skill(tmp_path, "rf-b", "[gather, screen]", "1. Call `tool_one` and `tool_two`.\n")
    cat = _derive(tmp_path, [_tool("tool_one"), _tool("tool_two"), _tool("tool_three")])
    by = {t.name: t for t in cat.tools}
    assert len(cat.tools) == 3
    assert by["tool_one"].stage == "gather"
    assert by["tool_one"].also_used_in == ("screen", "write")
    assert by["tool_three"].stage is None
    assert cat.flag_counts()["orphan-tool"] == 1
    assert cat.examples == 2


def test_missing_stage_and_orphan_skill(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", None, "Nothing here.\n")
    _skill(tmp_path, "rf-b", "bogus", "Nothing.\n")
    counts = _derive(tmp_path, [_tool("tool_one")]).flag_counts()
    assert counts["skill-no-stage"] == 2
    assert counts["orphan-skill"] == 2


def test_unknown_tool_and_unknown_arg(tmp_path: Path) -> None:
    _skill(
        tmp_path,
        "rf-a",
        "frame",
        "Call `ghost_tool` first.\n\nThen `tool_one(a=1, zz=2)` and `tool_one` with `a` and `qq`.\n",
    )
    cat = _derive(tmp_path, [_tool("tool_one", "a")])
    codes = [(f.code, f.message) for f in cat.flags]
    assert any(c == "skill-unknown-tool" and "ghost_tool" in m for c, m in codes)
    args = [m for c, m in codes if c == "skill-unknown-arg"]
    assert any("zz" in m for m in args) and any("qq" in m for m in args)
    assert not any("`a`" in m for m in args)


def test_clash_pairs_opposite_polarity_across_skills(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "Never call `tool_one` here.\n")
    _skill(tmp_path, "rf-b", "frame", "Always call `tool_one` first.\n")
    cat = _derive(tmp_path, [_tool("tool_one")])
    clashes = [f for f in cat.flags if f.code == "skill-skill-clash"]
    assert len(clashes) == 1 and clashes[0].other is not None and "rf-b" in clashes[0].other


def test_decision_checks(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "See decision 1, decisions 2 and 9 for `tool_one`.\n")
    counts = _derive(tmp_path, [_tool("tool_one")]).flag_counts()
    assert counts["skill-decision-missing"] == 1
    assert counts["skill-decision-not-decided"] == 1


def test_count_check_names_missing_and_duplicates(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "Call `tool_one`.\n")
    cat = _derive(tmp_path, [_tool("tool_one")], registered=["tool_one", "tool_two", "tool_two"])
    assert not cat.count_check.ok
    assert cat.count_check.missing == ("tool_two",)
    assert cat.count_check.duplicates == ("tool_two",)
    assert "Count check failed" in render(cat, "now", "code")


def test_registered_names_by_ast(tmp_path: Path) -> None:
    src = tmp_path / "s.py"
    src.write_text(
        "@server.tool()\ndef a(): ...\n@server.tool(name='c')\ndef b(): ...\ndef d(): ...\n",
        encoding="utf-8",
    )
    assert registered_names(src) == ["a", "c"]


def test_page_escapes(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "1. Call `tool_one` <script>.\n")
    html_text = render(_derive(tmp_path, [_tool("tool_one")]), "now", "code")
    assert "<script>." not in html_text.split("<body>")[1]
