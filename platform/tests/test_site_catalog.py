# ruff: noqa: E501
"""Derivation and flags of the capability catalog (plan catalog). Written per TDD; not run while
testing is paused."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def _derive(
    tmp_path: Path,
    tools: list[ToolSpec],
    registered: list[str] | None = None,
    markers: dict[str, str] | None = None,
) -> Catalog:
    return derive_catalog(
        tools,
        tmp_path / "skills",
        _decisions(tmp_path / "decisions.md"),
        registered if registered is not None else [t.name for t in tools],
        0,
        root=tmp_path,
        markers=markers if markers is not None else {},
        accepted={},
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


def test_single_word_tools_are_matched_to_skills(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "[cross]", "1. Call `check` and then `whoami`.\n")
    cat = _derive(tmp_path, [_tool("check"), _tool("whoami")])
    by = {t.name: t for t in cat.tools}
    assert by["check"].stage == "cross"
    assert by["whoami"].stage == "cross"
    assert not [f for f in cat.flags if f.code == "orphan-tool"]


def test_catalog_stamp_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from factory.services import site, site_catalog

    def boom(_settings: object) -> str:
        raise OSError("unreadable")

    monkeypatch.setattr(site_catalog, "source_hash", boom)
    project = SimpleNamespace(settings=None)
    assert site._stamp_catalog(project).startswith("unreadable:")  # type: ignore[arg-type]


# --- IDEA-61 ---

_APPRAISE = (
    "- Do not read the other pass's answers, the sheet, the agreement, the audit sample or its\n"
    "  labels, the reports, `check` or `trace`. The platform refuses them to a pass session; do not\n"
    "  work around a refusal.\n"
)
_RUN = "- Never act on a `check` finding to clear it: report it, with its code and severity.\n"
_SEARCH = (
    "6. When the last round has been screened, call `check` and report every finding to the researcher\n"
    "   as returned, with its code and severity. Do not act on a finding or alter the project to\n"
    "   clear it.\n"
)


def test_clash_needs_the_same_act_real_sentences(tmp_path: Path) -> None:
    """IDEA-61 item 1: "do not read `check`" and "never act on a `check` finding" do not oppose
    "call `check`" (rf-appraise, rf-run, rf-search)."""
    _skill(tmp_path, "rf-appraise", "extract", _APPRAISE)
    _skill(tmp_path, "rf-run", "cross", _RUN)
    _skill(tmp_path, "rf-search", "gather", _SEARCH)
    _skill(tmp_path, "rf-other", "frame", "Never call `check` before the protocol is recorded.\n")
    cat = _derive(tmp_path, [_tool("check"), _tool("trace")])
    clashes = [f for f in cat.flags if f.code == "skill-skill-clash"]
    assert len(clashes) == 1
    assert "rf-other" in clashes[0].message and clashes[0].other is not None
    assert "rf-search" in clashes[0].other


_MINE_RESOLVE_DOC = (
    "Resolve one disagreement of a miner's passes (`a`, `b` or `neither`, with a reason),\n"
    "where the project's policy for the gate `mine.resolve` lets an agent."
)


def test_backticked_values_are_not_inputs_real_sentence(tmp_path: Path) -> None:
    """IDEA-61 item 2: rf-mine line 46; `choice` is a `str` whose values the tool's description
    declares."""
    _skill(
        tmp_path,
        "rf-mine",
        "extract",
        "2. Call `mine_resolve` with `a`, `b` or `neither` and a reason, after reading the anchors yourself.\n",
    )
    spec = ToolSpec(
        name="mine_resolve",
        description=_MINE_RESOLVE_DOC,
        input_schema_json="{}",
        params=(
            "choice",
            "field",
            "miner",
            "model",
            "project",
            "reason",
            "role",
            "row_key",
            "skill",
            "work_id",
        ),
    )
    assert _derive(tmp_path, [spec]).flag_counts()["skill-unknown-arg"] == 0


def test_schema_enum_values_are_not_inputs(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "Call `tool_one` with `title` or `zz`.\n")
    spec = ToolSpec(
        name="tool_one",
        description="does it",
        input_schema_json='{"properties": {"stage": {"anyOf": [{"enum": ["title", "abstract"]}]}}}',
        params=("stage",),
    )
    args = [f.message for f in _derive(tmp_path, [spec]).flags if f.code == "skill-unknown-arg"]
    assert args == ["`tool_one` has no input `zz`"]


def test_wrapped_call_names_the_tool_real_lines(tmp_path: Path) -> None:
    """rf-reference-layers step 4 wraps the call over two lines; the tool is named, not an orphan."""
    _skill(
        tmp_path,
        "rf-reference-layers",
        "gather",
        "4. Call `reference_layer_record(project, scheme_version, stage, assignments, input_blob, role,\n"
        '   model, skill="rf-reference-layers")` with every item of the batch. Repeat until `remaining` is 0.\n',
    )
    cat = _derive(
        tmp_path,
        [
            _tool(
                "reference_layer_record",
                "project",
                "scheme_version",
                "stage",
                "assignments",
                "input_blob",
                "role",
                "model",
                "skill",
            )
        ],
    )
    assert cat.tools[0].stage == "gather"
    assert cat.flag_counts()["orphan-tool"] == 0
    assert cat.flag_counts()["skill-unknown-arg"] == 0


def test_markers_remove_orphans_and_flag_human_only_named(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "screen", "1. Call `calibration_label` for the sample.\n")
    cat = _derive(
        tmp_path,
        [_tool("whoami"), _tool("calibration_label"), _tool("audit_record"), _tool("loose_tool")],
        markers={
            "whoami": "read-only",
            "calibration_label": "human-only",
            "audit_record": "human-only",
            "gone_tool": "read-only",
        },
    )
    counts = cat.flag_counts()
    orphans = [f.message for f in cat.flags if f.code == "orphan-tool"]
    assert orphans == ["`loose_tool` is registered and no skill names it"]
    assert counts["skill-names-human-only"] == 1
    assert counts["marker-unknown-tool"] == 1
    by = {t.name: t for t in cat.tools}
    assert by["whoami"].marker == "read-only" and by["whoami"].access == "project:read"
    html_text = render(cat, "now", "code")
    assert "Marked tools" in html_text and "human-only" in html_text


def test_marker_checked_against_access_row(tmp_path: Path) -> None:
    """`grey_search_report` is an agent write (`work:run`) and `lead_decide` a gated agent act."""
    _skill(tmp_path, "rf-a", "frame", "Nothing.\n")
    cat = _derive(
        tmp_path,
        [
            _tool("grey_search_report"),
            _tool("lead_decide"),
            _tool("calibration_label"),
            _tool("whoami"),
        ],
        markers={
            "grey_search_report": "read-only",
            "lead_decide": "human-only",
            "calibration_label": "human-only",
            "whoami": "read-only",
        },
    )
    mismatched = sorted(
        f.message.split("`")[1] for f in cat.flags if f.code == "marker-access-mismatch"
    )
    assert mismatched == ["grey_search_report", "lead_decide"]


def test_declared_markers_cover_the_ruling() -> None:
    from factory.services.site_catalog import MARKER_KINDS, MARKERS

    assert sum(1 for k in MARKERS.values() if k == "read-only") == 24
    assert sum(1 for k in MARKERS.values() if k == "human-only") == 11
    assert sum(1 for k in MARKERS.values() if k == "scheduled") == 2
    assert set(MARKERS.values()) <= set(MARKER_KINDS)
    assert "grey_search_report" not in MARKERS


def test_accepted_mismatch_is_not_flagged(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "Nothing.\n")
    tools = [_tool("lead_decide"), _tool("grey_search_report")]
    markers = {"lead_decide": "human-only", "grey_search_report": "read-only"}
    cat = derive_catalog(
        tools,
        tmp_path / "skills",
        None,
        [t.name for t in tools],
        0,
        root=tmp_path,
        markers=markers,
        accepted={"lead_decide": "ruled"},
    )
    mismatched = [f.message for f in cat.flags if f.code == "marker-access-mismatch"]
    assert len(mismatched) == 1 and "grey_search_report" in mismatched[0]


def test_tools_deduplicated_when_listed_twice(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-a", "frame", "Call `tool_one`.\n")
    cat = _derive(tmp_path, [_tool("tool_one"), _tool("tool_one")])
    assert [t.name for t in cat.tools] == ["tool_one"]
    assert cat.count_check.duplicates == ("tool_one",)


def test_table_escapes_cells_and_headers() -> None:
    from factory.services.site_widgets import table

    out = table(["<h>"], [["<script>x</script>"]])
    assert "<script>" not in out and "<h>" not in out
    assert "&lt;script&gt;" in out


def test_stageless_skill_rendered_under_unassigned(tmp_path: Path) -> None:
    _skill(tmp_path, "rf-lost", "bogus", "1. Call `tool_one`.\n")
    cat = _derive(tmp_path, [_tool("tool_one")])
    html_text = render(cat, "now", "code")
    unassigned = html_text.split("<h2>Unassigned</h2>")[1].split("<h2>")[0]
    assert "rf-lost" in unassigned
    assert cat.flag_counts()["skill-no-stage"] == 1
