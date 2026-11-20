"""The plugin skills resolve through the platform and carry the frontmatter the plugin requires."""

from pathlib import Path

import pytest

from factory.config import Settings
from factory.services.skills import skill_ref

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    "rf-acquire",
    "rf-appraise",
    "rf-brief",
    "rf-cards",
    "rf-chat",
    "rf-contributions",
    "rf-critic",
    "rf-curate",
    "rf-deep",
    "rf-develop",
    "rf-experiment",
    "rf-extract",
    "rf-frame",
    "rf-hypothesis-engine",
    "rf-ideate",
    "rf-intuition",
    "rf-lineage",
    "rf-mine",
    "rf-miner-suggest",
    "rf-probe",
    "rf-protocol",
    "rf-references",
    "rf-regions",
    "rf-run",
    "rf-screen",
    "rf-search",
    "rf-search-run",
    "rf-spar-v2",
    "rf-technique-bounce",
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
    for absent in ("draft_verify", "draft_render"):
        assert absent not in text
    # The researcher's ruling (2026-11-12, IDEA-61 group C): `draft_release` is named, only as
    # another session's step, in "Stopping and human steps", never in the procedure.
    procedure, _, stopping = text.partition("## Stopping and human steps")
    assert "draft_release" not in procedure
    assert "draft_release" in stopping.partition("## Tool arguments")[0]


def test_technique_bounce_names_its_tools_and_the_labelling_rule() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-technique-bounce" / "SKILL.md").read_text("utf-8")
    for needed in (
        "technique_landscape",
        "technique_view",
        "technique_neighbors",
        "technique_gaps",
        "technique_combinations",
        "technique_challenges",
        "interpretation_record",
        "intuition_next",
        "lead_record",
        "hypothesis_draft",
        "document_read",
        "exploratory, pass A of m-tech-",
        "Never call a `derives-from`",
    ):
        assert needed in text, needed


def test_hypothesis_engine_names_its_tools_and_gates() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-hypothesis-engine" / "SKILL.md").read_text(
        "utf-8"
    )
    text = " ".join(text.split())
    for needed in (
        "technique_gaps",
        "technique_combinations",
        "technique_challenges",
        "technique_neighbors",
        "claims_digest",
        "corpus_search",
        "selection_resolve",
        "chat_verify",
        "document_read",
        "lead_record",
        "lead_list",
        "lead_decide",
        "hypothesis_draft",
        "hypothesis_review_next",
        "hypothesis_review",
        "hypothesis_register",
        "HUMAN DECISION POINT",
        "## Runtime knobs",
        "The engine tools: lead_candidates, lead_queue, lead_stats",
        "lead_queue",
        "lead_stats",
        "balance",
        "exactly as returned",
        "Never call `lead_decide`",
        "found / not found in this corpus",
        "at most 80 characters",
        "is for discussion and review",
        "does not name the methods, the margin or the direction",
        "`cutoff-unknown`, `insufficient-evidence` and `method-unresolved`",
        "`request_incomplete`",
        "recorded_as",
        "failure-quote-not-checked",
        "broad_prior_hits",
        "--show <candidate_id>",
    ):
        assert needed in text, needed


def test_rf_chat_passes_the_digest_claim_key_to_sheet_argue() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-chat" / "SKILL.md").read_text("utf-8")
    lowered = " ".join(text.split())
    assert "pass that claim's row key as `claim_row_key`" in lowered
    assert "key=" in lowered and "copy the text after" in lowered


def test_rf_chat_has_a_contradictions_mode() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-chat" / "SKILL.md").read_text("utf-8")
    lowered = " ".join(text.split())
    assert "## Contradictions" in text
    for needed in (
        "contradiction_propose",
        "different papers",
        "row:<work_id>#<row_key>",
        "never decide",
    ):
        assert needed in lowered, needed


def test_rf_chat_has_an_unattended_run_section() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-chat" / "SKILL.md").read_text("utf-8")
    lowered = " ".join(text.split()).lower()
    assert "## Unattended run" in text
    assert "`chat_request_next`" in text and "never ask the researcher anything" in lowered
    assert "`request_id`" in text and "the researcher rates and writes the balance" in lowered
    assert "explore unless the request says `prepare`" in lowered


def test_rf_spar_v2_has_one_section_per_role_and_the_never_rules() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-spar-v2" / "SKILL.md").read_text("utf-8")
    lowered = " ".join(text.split()).lower()
    for role in ("search", "read", "against", "for", "critic", "cover"):
        assert f"\n## {role}\n" in text, role
    assert "`spar_role_next`" in text and "pass no request id" in lowered
    assert "`spar_reading_record`" in text and "`spar_coverage_record`" in text
    assert "`sheet_check`" in text and "not a rating" in lowered
    assert "never rate an argument, write the balance" in lowered
    assert "wrote no argument against" in lowered
    assert "ask nothing, wait for nothing" in lowered


def test_rf_search_run_names_its_tools_and_gates() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-search-run" / "SKILL.md").read_text("utf-8")
    for needed in (
        "search_run",
        "search_slice",
        "report_search",
        "dedup_run",
        "resume_run",
        "esearch-cap",
        "deviation_id",
        "factory dedup pairs",
        "factory calibrate draw",
        "notice",
        "## Never",
        "## Done when",
    ):
        assert needed in text, needed
    never = text.split("## Never", 1)[1].split("\n## ", 1)[0]
    assert "held-out" in never and "Never decide a human gate" in never
    run = (REPO_ROOT / "plugin" / "skills" / "rf-run" / "SKILL.md").read_text("utf-8")
    assert "rf-search-run" in run


def test_rf_acquire_names_its_tools_and_gates() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-acquire" / "SKILL.md").read_text("utf-8")
    assert _frontmatter("rf-acquire")["stage"] == "[acquire]"
    for needed in (
        "library_adoptable",
        "library_adopt",
        "fulltext_fetch",
        "fulltext_status",
        "inbox_add",
        "inbox_resolve",
        "document_read",
        "chat_verify",
        "factory document convert",
        "factory fulltext import",
        "full-text screening is not planned in the protocol",
        "## Human-only acts",
        "## Never",
        "## Done when",
    ):
        assert needed in text, needed
    never = text.split("## Never", 1)[1].split("\n## ", 1)[0]
    assert "held-out" in never and "executable" in never
    run = (REPO_ROOT / "plugin" / "skills" / "rf-run" / "SKILL.md").read_text("utf-8")
    assert "rf-acquire" in run


BRIEF_TOOLS = (
    "project_status",
    "question_record",
    "seed_add",
    "protocol_record",
    "search_run",
    "report_search",
    "dedup_run",
    "ranking_compute",
    "screen_next",
    "screen_record",
    "fulltext_fetch",
    "fulltext_status",
    "extract_next",
    "extract_record",
    "extraction_status",
    "report_evidence",
    "chat_verify",
    "claims_digest",
    "page_brief",
    "page_record",
)


def test_rf_brief_names_existing_tools_labels_the_note_and_marks_human_gates() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-brief" / "SKILL.md").read_text("utf-8")
    assert _frontmatter("rf-brief")["stage"] == "[frame, gather, screen, acquire, extract, write]"
    server = (REPO_ROOT / "platform" / "src" / "factory" / "mcp" / "server.py").read_text("utf-8")
    for tool in BRIEF_TOOLS:
        assert f"`{tool}`" in text, tool
        assert f"    def {tool}(" in server, tool
    for needed in (
        "quick review, skipped:",
        "factory brief plan",
        "rf-deep",
        "## Human gates",
        "## Done when",
    ):
        assert needed in text, needed
    assert "report_evidence" in text and "none typed from memory" in text


DEEP_TOOLS = (
    "project_status",
    "protocol_record",
    "protocol_press_review",
    "search_run",
    "report_search",
    "dedup_run",
    "snowball_round",
    "ranking_compute",
    "screen_next",
    "screen_record",
    "screen_agreement",
    "audit_sample",
    "extract_agreement",
    "extract_audit_sample",
    "finder_contradictions",
    "report_evidence",
    "chat_verify",
    "claims_digest",
)


def test_rf_deep_names_existing_tools_labels_the_note_and_marks_human_gates() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-deep" / "SKILL.md").read_text("utf-8")
    server = (REPO_ROOT / "platform" / "src" / "factory" / "mcp" / "server.py").read_text("utf-8")
    for tool in DEEP_TOOLS:
        assert f"`{tool}`" in text, tool
        assert f"    def {tool}(" in server, tool
    for needed in (
        "deep review, skipped:",
        "factory brief plan",
        "factory protocol confirm-press",
        "factory audit label",
        "factory extract audit-label",
        "does NOT enforce",
        "Decision 158",
        "`dry_run` true",
        "## Human gates",
        "## Done when",
    ):
        assert needed in text, needed
    human = text.split("## Human gates", 1)[1].split("\n## ", 1)[0]
    assert "PRESS confirmation" in human and "audit label" in human


def test_rf_miner_suggest_names_existing_tools_and_marks_human_gates() -> None:
    text = (REPO_ROOT / "plugin" / "skills" / "rf-miner-suggest" / "SKILL.md").read_text("utf-8")
    server = (REPO_ROOT / "platform" / "src" / "factory" / "mcp" / "server.py").read_text("utf-8")
    for tool in (
        "project_status",
        "question_view",
        "miner_list",
        "mine_status",
        "decision_suggest",
        "miner_register",
        "protocol_record",
        "protocol_amend",
        "miner_calibration_label",
    ):
        assert f"`{tool}`" in text, tool
        assert f"    def {tool}(" in server, tool
    for needed in (
        "exploratory, unvalidated, agent-proposed",
        "agent-proposed schema",
        "factory mine request",
        "factory miner admit",
        "not-stated",
        "## Human gates",
        "## Done when",
    ):
        assert needed in text, needed
    human = text.split("## Human gates", 1)[1].split("\n## ", 1)[0]
    assert "admission" in human and "ticking" in human
