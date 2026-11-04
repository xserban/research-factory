"""The plugin skills resolve through the platform and carry the frontmatter the plugin requires."""

from pathlib import Path

import pytest

from factory.config import Settings
from factory.services.skills import skill_ref

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    "rf-extract",
    "rf-frame",
    "rf-probe",
    "rf-protocol",
    "rf-references",
    "rf-screen",
    "rf-search",
)


def _frontmatter(name: str) -> dict[str, str]:
    lines = (REPO_ROOT / "plugin" / "skills" / name / "SKILL.md").read_text("utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(": ")
        assert sep, f"frontmatter line without key: {line!r}"
        fields[key] = value
    return fields


@pytest.mark.parametrize("name", SKILLS)
def test_plugin_skills_resolve_and_have_frontmatter(name: str) -> None:
    s = Settings.load(root=REPO_ROOT, user="obd")  # plugin_dir defaults to <repo>/plugin
    assert skill_ref(s, name).startswith(f"{name}@")
    assert _frontmatter(name)["name"] == name
    assert _frontmatter(name)["description"].startswith("Use when")


def test_rf_screen_full_text_mode_section() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-screen" / "SKILL.md").read_text("utf-8")
    assert "## Full-text mode" in text
    section = text.split("## Full-text mode", 1)[1].split("\n## ", 1)[0]
    assert "document_read(work_id=" in section and "conversion_id" in section
    assert 'stage="full-text"' in section
    assert "pinned" in section and "ONE `anchor`" in section
    assert "character for character" in section and "single paragraph or table cell" in section
    assert "outside knowledge" in section
    assert "needs a fresh Claude Code session" in section
    assert "may screen both stages" not in section
    assert "`after` set to the page's `next_after`" in section
    assert "screen_agreement" in section  # named only to forbid it
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text


def test_rf_references_skill_text() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-references" / "SKILL.md").read_text("utf-8")
    for needed in (
        "references_extract",
        "references_list",
        "reference_decide",
        "propose-confirm",
        "snowball_round",
        "snowball_compare",
        "exactly two strings",
        "character for character",
        "Never confirm or reject a link",
        "dry_run",
        "go ahead",
        "## Never",
        "## Tool arguments",
        "## Done when",
    ):
        assert needed in text, needed
    never = text.split("## Never", 1)[1].split("\n## ", 1)[0]
    assert "by hand" in never and "held-out" in never.lower()
    assert "seed_check" not in text and "found_by" not in text


def test_rf_extract_skill_text() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-extract" / "SKILL.md").read_text("utf-8")
    for needed in (
        "extract_next",
        "document_read",
        "finish",
        "verbatim",
        "never compute",
        "## Independence",
        "## Procedure",
        "## Tool arguments",
        "## Done when",
        "`supersedes`",
        "row indices",
        "the cell text",
    ):
        assert needed in text, needed
    independence = " ".join(text.split("## Independence", 1)[1].split("\n## ", 1)[0].split())
    assert "different model" in independence
    assert "Do not read the other pass's rows" in independence
    assert "human labels" in independence and "audit" in independence
