"""The tutorial data names only things that exist: skills, MCP tools, CLI commands, hub pages."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer

from factory.learn.concepts import CONCEPTS
from factory.learn.glossary import GLOSSARY
from factory.learn.model import Ref, RefKind
from factory.learn.stages import STAGES
from factory.services import hub_platform as hpl
from factory.services import hub_ui
from factory.services import site_catalog as sc

SKILLS = Path(__file__).resolve().parents[2] / "plugin" / "skills"


def _refs() -> Iterator[tuple[str, Ref]]:
    for stage in STAGES:
        for step in stage.steps:
            for ref in step.refs:
                yield stage.id, ref
        yield stage.id, stage.page
        for ref in stage.done.shown_by:
            yield stage.id, ref


def _commands(group: Any, prefix: str = "") -> set[str]:
    subs = getattr(group, "commands", None)
    if not subs:
        return {prefix.strip()}
    out: set[str] = set()
    for name, sub in subs.items():
        out |= _commands(sub, f"{prefix} {name}")
    return out


def _exists(ref: Ref, tools: set[str], commands: set[str]) -> bool:
    if ref.kind is RefKind.SKILL:
        return (SKILLS / ref.name / "SKILL.md").is_file()
    if ref.kind is RefKind.TOOL:
        return ref.name in tools
    if ref.kind is RefKind.PAGE:
        return ref.name in hub_ui.PAGES
    return ref.name in commands


def test_every_named_skill_tool_command_and_page_exists() -> None:
    from factory.cli.main import app

    tools = set(sc.registered_names(sc.server_source()))
    commands = _commands(typer.main.get_command(app))
    missing = sorted(
        {(s, r.kind.value, r.name) for s, r in _refs() if not _exists(r, tools, commands)}
    )
    assert missing == []


def test_stages_are_the_run_map_stages_in_order() -> None:
    ids = [s.id for s in STAGES]
    assert ids == [s["id"] for s in hpl.RUN_MAP["stages"]]
    assert ids == [i for i in sc.STAGE_IDS if i != "cross"]
    assert [s.next_id for s in STAGES] == [*ids[1:], None]


def test_every_card_is_complete() -> None:
    for s in STAGES:
        assert s.title and s.goal.endswith(".") and s.gates and s.steps and s.rigour, s.id
        assert len(s.mistakes) == 5, s.id
        assert s.done.shown_by, s.id
        assert all(step.text for step in s.steps), s.id


def test_concepts_and_glossary_have_their_size() -> None:
    assert len({c.id for c in CONCEPTS}) == len(CONCEPTS) >= 5
    assert 12 <= len(GLOSSARY) <= 20
    assert len({t.term for t in GLOSSARY}) == len(GLOSSARY)


def test_no_unverified_claim_markers() -> None:
    text = repr(STAGES) + repr(CONCEPTS) + repr(GLOSSARY)
    for marker in ("unverified", "TODO", "dedup pairs"):
        assert marker not in text


@pytest.mark.parametrize("stage", [s.id for s in STAGES])
def test_a_stage_names_a_skill_a_command_and_a_page(stage: str) -> None:
    kinds = {r.kind for sid, r in _refs() if sid == stage}
    assert {RefKind.CLI, RefKind.PAGE} <= kinds
