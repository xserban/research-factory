"""Each stage's allow-list covers the factory tools its skill tells the child to call (plan
feed-hub H8). Static: parses the real `plugin/skills/<skill>/SKILL.md`. Not run while testing is
paused."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from factory.services import runner
from factory.services.access import TOOL_PERMISSIONS

SKILLS_DIR = Path(__file__).resolve().parents[2] / "plugin" / "skills"
PREFIX = "mcp__factory__"
TOOL_SUFFIXES = ("_next", "_record", "_status", "_list", "_propose", "_link")

NOT_ALLOWED: dict[str, dict[str, str]] = {
    "rf-intuition": {
        "concept_propose": "proposing concepts is out of scope for a headless run",
        "concept_link": "linking concepts is out of scope for a headless run",
    },
    "rf-chat": {
        "contradiction_propose": "the Contradictions mode is attended; no runner stage serves it",
        "lead_record": "a lead needs the researcher's balance; no headless run records one",
    },
    "rf-spar-v2": {
        "lead_record": "a lead needs the researcher's balance; no role run records one",
        "answer_record": "an answer is the ask stage's; no spar role writes one",
    },
}
"""Per skill, the tool names the skill mentions that the run does not allow, with the reason."""

STAGE_NOT_ALLOWED: dict[str, dict[str, str]] = {
    "spar": {"answer_record": "an answer is written by the ask stage"},
    "ask": {},
    "spar2-search": {
        "spar_reading_record": "a reader records readings",
        "spar_coverage_record": "the coverage role records the sweep",
    },
    "spar2-read": {"spar_coverage_record": "the coverage role records the sweep"},
    "spar2-against": {
        "spar_reading_record": "a reader records readings",
        "spar_coverage_record": "the coverage role records the sweep",
    },
    "spar2-for": {
        "spar_reading_record": "a reader records readings",
        "spar_coverage_record": "the coverage role records the sweep",
    },
    "spar2-critic": {
        "spar_reading_record": "a reader records readings",
        "spar_coverage_record": "the coverage role records the sweep",
    },
    "spar2-cover": {"spar_reading_record": "a reader records readings"},
    "develop-lead": {
        "hypothesis_review_next": "the independent review is the critic's own run",
        "hypothesis_review": "the independent review is the critic's own run",
        "hypothesis_draft": "drafting is the drafter's own run",
        "hypothesis_view": "the drafter and the critic read drafts; the lead author writes none",
        "hypothesis_register": "registering is the researcher's act (human-only gate)",
        "lead_decide": "promoting a lead is the researcher's act (human-only gate)",
        "check": "named in prose only; the conductor's verifier runs the check",
    },
    "develop-draft": {
        "lead_record": "a lead is the lead author's; the drafter works from promoted leads",
        "lead_candidates": "candidates are the lead author's input",
        "lead_queue": "the queue is the lead author's input",
        "lead_stats": "statistics are the lead author's input",
        "hypothesis_review_next": "the independent review is the critic's own run",
        "hypothesis_review": "the independent review is the critic's own run",
        "hypothesis_register": "registering is the researcher's act (human-only gate)",
        "lead_decide": "promoting a lead is the researcher's act (human-only gate)",
        "check": "named in prose only; the conductor's verifier runs the check",
    },
    "acquire": {
        "screen_next": "screening is the screen stage's; the conductor's acquire step fetches",
        "screen_record": "screening is the screen stage's; the conductor's acquire step fetches",
        "protocol_amend": "an amendment is the researcher's act",
        "protocol_deviation": "a deviation is the researcher's act",
        "inbox_add": "a manual link is the researcher's; the step fetches what the plan names",
        "inbox_resolve": "a manual link is the researcher's; the step fetches what the plan names",
        "library_adopt": "adopting a library document is the researcher's act",
        "chat_verify": "quote verification belongs to the chat and write stages",
    },
    "extract": {
        "check": "the skill forbids a pass session the reports, `check` and `trace`",
        "trace": "the skill forbids a pass session the reports, `check` and `trace`",
    },
    "extract-b": {
        "check": "the skill forbids a pass session the reports, `check` and `trace`",
        "trace": "the skill forbids a pass session the reports, `check` and `trace`",
    },
    "frame": {"develop_render": "a develop page is not part of framing"},
    "gather": {
        "probe_run": "the probe is the frame step's",
        "seed_add": "seeds are the researcher's, recorded in the frame step",
        "protocol_amend": "an amendment is the researcher's act",
        "protocol_deviation": "a deviation is the researcher's act",
        "merge_revert": "reverting a merge is the researcher's call",
    },
    "write": {"draft_release": "a release is the researcher's act (human-only gate)"},
    "screen": {
        "screen_agreement": "agreement is read by the researcher once both passes are done",
        "screen_check_draw": "the screening check is the researcher's calibration act",
        "screen_check_example": "the screening check is the researcher's calibration act",
        "screen_check_label": "the screening check is the researcher's calibration act",
        "screen_check_report": "the screening check is the researcher's calibration act",
    },
    "screen-ft": {
        "screen_agreement": "agreement is read by the researcher once both passes are done",
        "screen_check_draw": "the screening check is the researcher's calibration act",
        "screen_check_example": "the screening check is the researcher's calibration act",
        "screen_check_label": "the screening check is the researcher's calibration act",
        "screen_check_report": "the screening check is the researcher's calibration act",
    },
    "conduct-verify": {"audit_sample": "the audit draw is the auditor's own run"},
}
"""Per stage key (a skill shared by two stages), the tools that stage does not allow."""

CONDUCTOR_STAGES = runner.CONDUCT_STAGES
"""The conductor's stages serve no queue (their unit is the conductor's step), so they need no
`_next` tool."""


def _stage_specs() -> list[tuple[str, runner.StageSpec]]:
    return [*runner.STAGES.items(), (runner.MINE_PREFIX + "<id>", runner.MINE_SPEC)]


def mentioned(text: str) -> set[str]:
    """The factory tool names a skill text mentions: `mcp__factory__x`, and backticked names
    ending `_next`, `_record`, `_status`, `_list`, `_propose`, `_link`, or `document_read`."""
    names = {m for m in re.findall(PREFIX + r"([a-z_]+)", text)}
    for name in re.findall(r"`([a-z][a-z_]*)(?:\(|`)", text):
        if name in ("document_read", "digest_get") or name.endswith(TOOL_SUFFIXES):
            names.add(name)
    return names


def registered_tools() -> set[str]:
    """The MCP tool names the platform registers (`TOOL_PERMISSIONS` keys without `cli:` rows)."""
    return {k for k in TOOL_PERMISSIONS if not k.startswith("cli:")}


def mentioned_all(text: str) -> set[str]:
    """Every registered tool name a skill text mentions: `mcp__factory__x`, and any snake_case
    identifier inside a backticked span or before a `(`, kept when it is a registered tool."""
    candidates = set(re.findall(PREFIX + r"([a-z][a-z0-9_]*)", text))
    for span in re.findall(r"`([^`\n]+)`", text):
        for word in re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", span):
            # a one-word name (`check`, `trace`) is ambiguous with the CLI command of that name:
            # it counts only when it is the whole span or is called
            if "_" in word or span.strip() in (word, f"{word}()") or f"{word}(" in span:
                candidates.add(word)
    candidates.update(re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(", text))
    return candidates & registered_tools()


WIDE_STAGES = (
    "frame", "gather", "screen", "screen-ft", "acquire", "extract", "extract-b", "write",
    "understand", "develop-lead", "develop-draft", "develop-critic", "maintain",
    "conduct-verify", "conduct-audit",
)  # fmt: skip
"""The conductor's stages: every registered tool their skill text names is allowed or excluded
with a reason (the other stages are held to the narrower `mentioned`)."""


@pytest.mark.parametrize("key", WIDE_STAGES)
def test_every_registered_tool_a_conductor_skill_names_is_allowed_or_excluded(key: str) -> None:
    spec = runner.STAGES[key]
    text = (SKILLS_DIR / spec.skill / "SKILL.md").read_text(encoding="utf-8")
    allowed = {t.removeprefix(PREFIX) for t in spec.tools}
    excluded = {**NOT_ALLOWED.get(spec.skill, {}), **STAGE_NOT_ALLOWED.get(key, {})}
    missing = sorted(mentioned_all(text) - allowed - set(excluded))
    assert not missing, (
        f"{key}: {spec.skill} names registered tools the run may not call: {missing}"
    )
    assert not (allowed & set(excluded)), f"{key}: a tool is both allowed and excluded"
    registered = registered_tools()
    assert allowed <= registered, f"{key}: allow-list names unregistered {allowed - registered}"


def test_no_conductor_stage_allows_a_human_only_act() -> None:
    human_only = {
        "lead_decide", "hypothesis_register", "draft_release", "protocol_amend",
        "protocol_deviation", "mine_resolve", "miner_register", "audit_sample",
    }  # fmt: skip
    for key in WIDE_STAGES:
        allowed = {t.removeprefix(PREFIX) for t in runner.STAGES[key].tools}
        banned = human_only - ({"audit_sample"} if key == "conduct-audit" else set())
        assert not (allowed & banned), (key, sorted(allowed & banned))


@pytest.mark.parametrize(("key", "spec"), _stage_specs(), ids=[k for k, _ in _stage_specs()])
def test_every_tool_a_skill_names_is_allowed_or_excluded_with_a_reason(
    key: str, spec: runner.StageSpec
) -> None:
    text = (SKILLS_DIR / spec.skill / "SKILL.md").read_text(encoding="utf-8")
    allowed = {t.removeprefix(PREFIX) for t in spec.tools}
    excluded = {**NOT_ALLOWED.get(spec.skill, {}), **STAGE_NOT_ALLOWED.get(key, {})}
    found = mentioned(text)
    assert found, f"{spec.skill}: the parser found no tool name"
    missing = sorted(found - allowed - set(excluded))
    assert not missing, f"{key}: {spec.skill} names tools the run may not call: {missing}"
    assert not (allowed & set(excluded)), f"{key}: a tool is both allowed and excluded"
    assert all(excluded.values())


def test_the_next_tool_of_each_stage_is_allowed() -> None:
    for key, spec in _stage_specs():
        if key in CONDUCTOR_STAGES:
            continue
        assert any(t.endswith("_next") for t in spec.tools), key
