"""The skills name only tools and commands that exist (scripts/check_skill_tools.py, IDEA-115)."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sys.modules.pop("check_skill_tools", None)
    import check_skill_tools

    return check_skill_tools


def test_every_skill_name_is_a_tool_or_command(
    check: object, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check.main() == 0, capsys.readouterr().out  # type: ignore[attr-defined]


def test_unknown_tool_and_command_are_found(check: object) -> None:
    prefixes = {"screen"}
    text = "Call `screen_nonexistent`, then `factory nosuchgroup run`; `task_id` is a field."
    assert check.tool_candidates(text, prefixes) == {"screen_nonexistent"}  # type: ignore[attr-defined]
    words = next(iter(check.command_candidates(text)))  # type: ignore[attr-defined]
    assert not check.resolves(words, {("cards",), ("cards", "assert")}, {("cards",)})  # type: ignore[attr-defined]


def test_a_group_needs_a_known_second_word(check: object) -> None:
    known = {("cards",), ("cards", "assert")}
    assert check.resolves(("cards", "assert", "x"), known, {("cards",)})  # type: ignore[attr-defined]
    assert not check.resolves(("cards", "bogus"), known, {("cards",)})  # type: ignore[attr-defined]
