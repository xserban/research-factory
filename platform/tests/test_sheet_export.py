"""Markdown export of a sheet and of an answer (spar night N8, ruling 8)."""

# ruff: noqa: F811
import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.services import answers as an
from factory.services import sheet_export as ex
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.selection import SelectionSpec, resolve_selection_cached
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"


def _arg(work: str, stance: str, claim: str = "it fails") -> sh.ArgumentInput:
    return sh.ArgumentInput(stance, work, ANCHOR, QUOTE, claim, "moderate")


def _sheet(project: Project, agent: Actor, other: Actor, world: list[str], claim: str = "x") -> str:
    works = sorted(world)
    sheet = sh.open_sheet(
        project,
        agent,
        "Reflection helps",
        SelectionSpec(),
        [
            C(works[0], "claims", "against", ANCHOR, QUOTE),
            C(works[1], "keyword", "for", ANCHOR, QUOTE),
        ],
        mode="prepare",
    ).sheet_id
    sh.record_arguments(project, agent, sheet, [_arg(works[0], "against", claim)])
    sh.close_section(project, agent, sheet, "against")
    sh.record_arguments(project, other, sheet, [_arg(works[1], "for"), _arg(works[0], "for")])
    sh.close_section(project, other, sheet, "for")
    return sheet


def test_no_balance_states_it_and_never_invents_one(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    md = ex.export_sheet(project, sheet)
    assert "No balance written by the researcher yet." in md
    assert "Reflection helps" in md and "prepare" in md
    assert "unrated" in md and "proposed by agent" in md
    assert QUOTE in md  # the verified quote and its paragraph
    assert "Provenance" in md and sheet in md and "claude-opus-5-5" in md
    assert "rf-screen@1a2b3c4d" in md


def test_balance_comes_first_then_against_then_for(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    sh.record_balance(project, human, sheet, "Mostly for.", lean="for", note="replicate")
    md = ex.export_sheet(project, sheet)
    assert "No balance written" not in md
    pos = [md.index(s) for s in ("Mostly for.", "Case against", "Case for", "## References")]
    assert pos == sorted(pos)
    assert "replicate" in md and "obd" in md


def test_ratings_shown_and_unrated_marked(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    view = sh.view_sheet(project, sheet)
    sh.rate_argument(project, human, view.arguments[0].argument_id, "weak", "thin sample")
    md = ex.export_sheet(project, sheet)
    assert "Rating (researcher): weak" in md and "thin sample" in md
    assert md.count("Not rated by the researcher") == len(view.arguments) - 1


def test_references_list_each_cited_work_once(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)  # work 0 cited twice
    md = ex.export_sheet(project, sheet)
    refs = md.split("## References")[1].split("## Provenance")[0]
    lines = [ln for ln in refs.splitlines() if ln[:1].isdigit()]
    assert len(lines) == 2
    assert lines[0].startswith("1. ")


def test_stale_line_when_selection_changed(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    assert "stale" not in ex.export_sheet(project, sheet).lower()
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(text("UPDATE sheets SET selection_digest = 'changed'"))
        conn.commit()
    assert "Stale:" in ex.export_sheet(project, sheet)


def test_escape_keeps_the_document_intact() -> None:
    raw = "a * b _c_ # d | e [f] <g> `h` \\i"
    out = ex.escape(raw)
    for ch in "*_#|[]<>`":
        assert out.count(ch) == out.count("\\" + ch) == raw.count(ch)
    assert "\n" not in ex.escape("x\ny")


def test_special_characters_in_claim_do_not_break_structure(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world, claim="# Heading | cell *bold* _it_")
    md = ex.export_sheet(project, sheet)
    assert "\n# Heading" not in md and "\\# Heading" in md
    assert "*bold*" not in md.replace("\\*bold\\*", "")


def test_unknown_ids_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        ex.export_sheet(project, "sht_NOPE")
    with pytest.raises(FactoryValidationError):
        ex.export_answer(project, "ans_NOPE")


def _answer(project: Project, agent: Actor, world: list[str]) -> str:
    works = sorted(world)
    spec = SelectionSpec()
    return an.record_answer(
        project,
        agent,
        "Does reflection help?",
        spec,
        resolve_selection_cached(project, spec).digest,
        [
            an.SentenceInput("It helps.", works[0], ANCHOR, QUOTE),
            an.SentenceInput("It also fails.", works[1], ANCHOR, QUOTE),
        ],
        unanswered="Long-term effects.",
    ).answer_id


def test_answer_export(project: Project, agent: Actor, human: Actor, world: list[str]) -> None:
    ans = _answer(project, agent, world)
    an.rate_answer(project, human, ans, "sound", "ok", sentence=1)
    md = ex.export_answer(project, ans)
    assert "Does reflection help?" in md and "It helps." in md and QUOTE in md
    assert "Rating (researcher): sound" in md and "Not rated by the researcher" in md
    assert "Long-term effects." in md and "## References" in md
    assert "proposed by agent" in md and ans in md and "rf-screen@1a2b3c4d" in md


def test_cli_export_to_stdout_and_file(
    project: Project, agent: Actor, agent_other: Actor, world: list[str], tmp_path, monkeypatch
) -> None:
    from factory.cli import main as cli_main

    sheet = _sheet(project, agent, agent_other, world)
    monkeypatch.setattr(cli_main, "_resolve_project", lambda state: project)
    runner = CliRunner()
    res = runner.invoke(cli_main.app, ["sheets", "export", sheet])
    assert res.exit_code == 0, res.output
    assert "No balance written by the researcher yet." in res.output
    out = tmp_path / "brief.md"
    res = runner.invoke(cli_main.app, ["sheets", "export", sheet, "--out", str(out)])
    assert res.exit_code == 0 and "No balance written" in out.read_text()
    ans = _answer(project, agent, world)
    res = runner.invoke(cli_main.app, ["answers", "export", ans])
    assert res.exit_code == 0 and "Does reflection help?" in res.output
