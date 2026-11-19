"""Each stage's allow-list covers the factory tools its skill tells the child to call (plan
feed-hub H8). Static: parses the real `plugin/skills/<skill>/SKILL.md`. Not run while testing is
paused."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from factory.services import runner

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
}
"""Per skill, the tool names the skill mentions that the run does not allow, with the reason."""

STAGE_NOT_ALLOWED: dict[str, dict[str, str]] = {
    "spar": {"answer_record": "an answer is written by the ask stage"},
    "ask": {},
}
"""Per stage key (a skill shared by two stages), the tools that stage does not allow."""


def _stage_specs() -> list[tuple[str, runner.StageSpec]]:
    return [*runner.STAGES.items(), (runner.MINE_PREFIX + "<id>", runner.MINE_SPEC)]


def mentioned(text: str) -> set[str]:
    """The factory tool names a skill text mentions: `mcp__factory__x`, and backticked names
    ending `_next`, `_record`, `_status`, `_list`, `_propose`, `_link`, or `document_read`."""
    names = {m for m in re.findall(PREFIX + r"([a-z_]+)", text)}
    for name in re.findall(r"`([a-z][a-z_]*)(?:\(|`)", text):
        if name == "document_read" or name.endswith(TOOL_SUFFIXES):
            names.add(name)
    return names


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
        assert any(t.endswith("_next") for t in spec.tools), key
