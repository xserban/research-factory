"""Check that the names the plugin skills mention exist (IDEA-115).

Run from the repository root:

    uv run --project platform python scripts/check_skill_tools.py

Two kinds of name are checked, by context:

* a MCP tool name is a backticked `snake_case` word with an underscore in a skill's SKILL.md; it
  must be a tool registered in `mcp/server.py` (found by AST, as `scripts/gen_map.py` does);
* a CLI command is the words after `factory` (for example `factory cards assert`); it must
  resolve in the typer app, as a command or a command group (words after the command, such as
  arguments and options, are ignored).

A backticked word that is a parameter, a field, a service function or a file is not a tool.
`NOT_TOOLS` lists the ones the skills use that way; a new name that is not a tool must be added
there with its reason, or the check fails. The script prints what it found and exits 1 when
a name is unknown. It reads files and the typer app only; it changes nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Backticked snake_case words in skills that are not tools: name -> what it is.
NOT_TOOLS: dict[str, str] = {
    "evaluate_hypothesis": "service function behind `factory hypotheses evaluate`",
    "group_claims_by_work": "parameter of the lead-candidate tools",
    "request_incomplete": "service argument (`--incomplete`)",
    "decision_rule": "a field of a hypothesis, not a tool",
    "selection_digest": "a field of a chat request, not a tool",
    "snowball_plan": "a field of the protocol, not a tool",
    "grey_sources": "a field of the protocol, not a tool",
    "source_project": "an argument of the project-copy command",
    "est_tokens": "a field of a chat request, not a tool",
    "raw_goal": "a field of the question, not a tool",
    "described_as": "a field of an item, not a tool",
    "source_work": "a field of a relation, not a tool",
    "dry_run": "a parameter of the snowball round tool",
    "technique_min_works": "a parameter of the lead-candidate tools",
}
# A name ending like this is a parameter or field (`task_id`, `work_ids`), never a tool.
PARAM_SUFFIXES = ("_id", "_ids", "_name", "_label", "_no", "_count", "_digest", "_item", "_span")
# A name is read as a tool claim when its first word begins a registered tool (`screen_...`) or
# its sentence says "tool" or "call"; this is a heuristic by context, and `NOT_TOOLS` is its
# allow-list.
_CLAIM_WORDS = re.compile(r"\b(tool|tools|call|calls|calling)\b", re.IGNORECASE)

_BACKTICKED = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")
# a command is in code: after a backtick, or at the start of a line (a fenced block)
_FACTORY_CMD = re.compile(r"(?:`|^\s*(?:\$ )?)factory((?: [a-z][a-z-]*)+)", re.MULTILINE)


def skill_files() -> list[Path]:
    return sorted((ROOT / "plugin" / "skills").glob("*/SKILL.md"))


def tool_candidates(text: str, prefixes: set[str]) -> set[str]:
    """Backticked snake_case words read as tool claims (see `_CLAIM_WORDS`)."""
    found: set[str] = set()
    for line in text.splitlines():
        claim_line = bool(_CLAIM_WORDS.search(line))
        for name in _BACKTICKED.findall(line):
            if name.endswith(PARAM_SUFFIXES):
                continue
            if claim_line or name.split("_")[0] in prefixes:
                found.add(name)
    return found


def command_candidates(text: str) -> set[tuple[str, ...]]:
    return {tuple(m.split()) for m in _FACTORY_CMD.findall(text)}


def resolves(
    words: tuple[str, ...], known: set[tuple[str, ...]], groups: set[tuple[str, ...]]
) -> bool:
    """The first word is a command or group; where it is a group the second must be one of its
    commands. Later words are arguments or prose and are not checked."""
    if not words or words[:1] not in known:
        return False
    is_group = any(len(c) > 1 and c[:1] == words[:1] for c in known)
    return len(words) == 1 or not is_group or words[:2] in known


def main() -> int:
    import gen_map

    tools = {name for name, _, _ in gen_map.mcp_tools()}
    commands = {tuple(name.split()[1:]) for name, _, _ in gen_map.cli_commands()}
    groups = {c[:i] for c in commands for i in range(1, len(c) + 1)}
    known = commands | groups
    prefixes = {t.split("_")[0] for t in tools}
    bad_tools: list[str] = []
    bad_cmds: list[str] = []
    allowed_seen: set[str] = set()
    for path in skill_files():
        text = path.read_text(encoding="utf-8")
        skill = path.parent.name
        for name in sorted(tool_candidates(text, prefixes)):
            if name in tools:
                continue
            if name in NOT_TOOLS:
                allowed_seen.add(name)
                continue
            bad_tools.append(f"{skill}: `{name}` is not a registered tool")
        for words in sorted(command_candidates(text)):
            if not resolves(words, known, groups):
                bad_cmds.append(f"{skill}: `factory {' '.join(words)}` is not a command")
    print(f"{len(tools)} tools, {len(commands)} commands, {len(skill_files())} skills")
    print(f"allow-listed non-tools used: {', '.join(sorted(allowed_seen)) or 'none'}")
    for line in bad_tools + bad_cmds:
        print("UNKNOWN", line)
    return 1 if bad_tools or bad_cmds else 0


if __name__ == "__main__":
    sys.exit(main())
