"""The plugin skills resolve through the platform and carry the frontmatter the plugin requires."""

from pathlib import Path

import pytest

from factory.config import Settings
from factory.services.skills import skill_ref

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    "rf-appraise",
    "rf-cards",
    "rf-contributions",
    "rf-critic",
    "rf-curate",
    "rf-develop",
    "rf-experiment",
    "rf-extract",
    "rf-frame",
    "rf-ideate",
    "rf-intuition",
    "rf-lineage",
    "rf-mine",
    "rf-probe",
    "rf-protocol",
    "rf-references",
    "rf-regions",
    "rf-run",
    "rf-screen",
    "rf-search",
    "rf-verify",
    "rf-write",
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


def test_rf_contributions_skill_text() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-contributions" / "SKILL.md").read_text("utf-8")
    for tool in ("contribution_next", "contribution_record", "document_read"):
        assert tool in text
    for phrase in (
        "cited_entry",
        "not-stated",
        "verbatim",
        "never infer",
        "finer anchor",
        "b<n>",
        "supersedes",
        "reason",
    ):
        assert phrase in text.lower(), phrase
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    for wording in ("we build on", "following", "based on", "extends", "unlike", "in contrast to"):
        assert wording in text.lower(), wording
    assert "improves" in text.lower()
    assert "human steps" in text.lower()
    # the platform never classifies: the skill must say the reading is the agent's own
    assert "the platform does not classify" in text.lower()


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


def test_rf_lineage_skill_text() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-lineage" / "SKILL.md").read_text("utf-8")
    for needed in ("relation_propose", "idea_propose", "basis_item", "note", "never confirm"):
        assert needed in text, needed
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    lowered = text.lower()
    assert "never merge" in lowered and "inferred" in lowered
    assert "the platform sets the status" in lowered


def test_rf_cards_skill_text() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-cards" / "SKILL.md").read_text("utf-8")
    for needed in (
        "vocabulary_propose",
        "card_create",
        "card_assert",
        "document_read",
        "never confirm",
        "inferred",
        "row_key",
    ):
        assert needed in text, needed
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text


def test_rf_intuition_skill_text() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-intuition" / "SKILL.md").read_text("utf-8")
    for needed in ("intuition_next", "interpretation_record", "interpretation_list", "600"):
        assert needed in text, needed
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    lowered = " ".join(text.lower().split())
    assert "not evidence" in lowered and "verbatim" in lowered
    assert "never review" in lowered and "never supersede a reviewed" in lowered
    assert "background" in lowered and "supports" in lowered


def test_rf_ideate_names_its_tools_and_never_registers() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-ideate" / "SKILL.md").read_text("utf-8")
    for tool in (
        "lead_record",
        "hypothesis_draft",
        "hypothesis_view",
        "match_query",
        "finder_contradictions",
        "finder_gaps",
    ):
        assert tool in text, tool
    lowered = text.lower()
    for phrase in (
        "never register",
        "prior",
        "framework",
        "falsifier",
        "comparability keys",
        "margin",
        "superiority",
        "non-inferiority",
        "literature-direction",
    ):
        assert phrase in lowered, phrase
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    assert "hypothesis_register" not in text and "hypothesis_review" not in text


def test_rf_critic_reads_only_the_artefact() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-critic" / "SKILL.md").read_text("utf-8")
    assert "hypothesis_review_next" in text and "hypothesis_review`" in text
    lowered = text.lower()
    for phrase in (
        "do not read the proposer's notes",
        "revise",
        "reject",
        "falsifiable",
        "conditions-in-evidence",
        "drafter",
        "lead author",
    ):
        assert phrase in lowered, phrase
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    assert "lead_record" not in text and "hypothesis_draft" not in text


def test_rf_experiment_names_its_tools_and_never_types_a_result() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-experiment" / "SKILL.md").read_text("utf-8")
    for tool in ("experiment_design", "experiment_view", "xrun_register", "xrun_list"):
        assert tool in text, tool
    lowered = " ".join(text.lower().split())
    for phrase in (
        "never type a result",
        "exploratory",
        "freeze",
        "unlock",
        "baselines",
        "ablations that each change exactly one",
        "positive and a negative control",
        "plan's minimum number of seeds",
        "primary universe",
        "budget",
    ):
        assert phrase in lowered, phrase
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    # the skill's tools cannot freeze, unlock, ingest, accept or record, and it names none
    for absent in ("experiment_freeze", "experiment_unlock", "xrun_record", "baseline_accept"):
        assert absent not in text


def test_rf_verify_names_its_tools_and_judges_only_from_the_spans() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-verify" / "SKILL.md").read_text("utf-8")
    for tool in ("draft_verify_next", "draft_verify_record"):
        assert tool in text, tool
    lowered = " ".join(text.lower().split())
    for phrase in (
        "judge only from the spans shown",
        "never use outside knowledge",
        "overstated",
        "always quote the sentence part and the span part",
        "scope, hedging or quantifier",
    ):
        assert phrase in lowered, phrase
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    for absent in ("draft_write", "draft_release"):
        assert absent not in text


def test_rf_write_names_its_tools_and_never_types_a_citation_or_number() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-write" / "SKILL.md").read_text("utf-8")
    for tool in ("writing_outline", "draft_create", "draft_next", "draft_write", "draft_status"):
        assert tool in text, tool
    lowered = " ".join(text.lower().split())
    for phrase in (
        "cite only supports shown in the slot",
        "never type a citation or a number",
        "synthesis",
        "stat",
        "disagreement",
        "the corpus does not support",
        "cross-group",
        "supersedes",
    ):
        assert phrase in lowered, phrase
    for kept in ("## Independence", "## Procedure", "## Tool arguments", "## Done when"):
        assert kept in text
    for absent in ("draft_verify", "draft_release", "draft_render"):
        assert absent not in text
