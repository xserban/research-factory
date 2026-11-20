"""Markdown export of a sheet and of an answer (spar night N8, ruling 8)."""

# ruff: noqa: F811
import re

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


# ---- review fixes -----------------------------------------------------------------------------

NASTY = "first *line* here\nsecond <script>alert(1)</script>\nthird [x](javascript:alert(1))"


def _after_label(md: str, label: str = "Source paragraph:") -> list[str]:
    block = md.split(label)[1].split("\n\n")[1]
    return block.splitlines()


def test_real_paragraph_full_text_quoted_line_by_line(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    view = sh.view_sheet(project, sheet)
    a = view.arguments[0]
    para = ex._paragraph(project, {}, a.conversion_id, a.anchor)
    assert para and QUOTE in para
    md = ex.export_sheet(project, sheet)
    lines = _after_label(md)
    assert all(ln.startswith("> ") for ln in lines)
    assert [ln[2:] for ln in lines] == [ex.escape(x) for x in para.splitlines() if x.strip()]


def test_nasty_paragraph_is_escaped(
    project: Project, agent: Actor, agent_other: Actor, world: list[str], monkeypatch
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    monkeypatch.setattr(ex, "_paragraph", lambda *a: NASTY)
    md = ex.export_sheet(project, sheet)
    lines = _after_label(md)
    assert len(lines) == 3 and all(ln.startswith("> ") for ln in lines)
    assert "\\*line\\*" in md and "\\<script\\>" in md
    assert "[x](" not in md and "\\[x\\]" in md


def test_missing_anchor_or_conversion_says_not_available(
    project: Project, agent: Actor, agent_other: Actor, world: list[str], monkeypatch
) -> None:
    sheet = _sheet(project, agent, agent_other, world)

    class Empty:
        def get(self, anchor: str) -> None:
            return None

    monkeypatch.setattr(ex, "conversion_manifest", lambda p, c: Empty())
    md = ex.export_sheet(project, sheet)
    assert md.count("> (not available)") == 3

    def boom(p: Project, c: str) -> None:
        raise FactoryValidationError([])

    monkeypatch.setattr(ex, "conversion_manifest", boom)
    assert ex.export_sheet(project, sheet).count("> (not available)") == 3


def test_balance_keeps_paragraphs_and_neutralises_markers(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    text_ = "Para one.\n\n- not a list\n+ nor this\n1. nor this\n---\n=\n\nPara three."
    sh.record_balance(project, human, sheet, text_, lean="for", note="- note item\n\nsecond")
    sh.record_balance(project, human, sheet, text_, lean="for", note="- note item\n\nsecond")
    md = ex.export_sheet(project, sheet)
    sec = md.split("## The researcher's balance")[1].split("## Case against")[0]
    assert "> Para one.\n>\n> \\- not a list" in sec and "\n>\n> Para three." in sec
    for raw in ("- not a list", "+ nor this", "1. nor this", "---", "="):
        bare = [ln.removeprefix("> ").strip() for ln in sec.splitlines()]
        assert not any(ln == raw or ln.startswith(raw + " ") for ln in bare), raw
    assert "- note item" not in sec.replace("\\- note item", "")
    assert "superseded balances: 1" in sec.lower()


def test_unresolvable_selection_prints_stale_not_failure(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(text("UPDATE sheets SET selection = :s"), {"s": '{"layers": ["nope"]}'})
        conn.commit()
    md = ex.export_sheet(project, sheet)
    assert "Stale: the selection can no longer be resolved" in md


def test_answer_unanswered_empty_and_stale(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works = sorted(world)
    spec = SelectionSpec()
    ans = an.record_answer(
        project,
        agent,
        "Q?",
        spec,
        resolve_selection_cached(project, spec).digest,
        [an.SentenceInput("It helps.", works[0], ANCHOR, QUOTE)],
        unanswered="",
    ).answer_id
    md = ex.export_answer(project, ans)
    assert "No gaps declared by the agent." in md and "Stale:" not in md
    with project.index.exclusive(), project.index.connect() as conn:
        conn.execute(text("UPDATE answers SET selection_digest = 'changed'"))
        conn.commit()
    assert "Stale: the selection has changed" in ex.export_answer(project, ans)


def test_references_numbered_in_print_order(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    md = ex.export_sheet(project, sheet)
    nums = [int(n) for n in re.findall(r"Source: \[(\d+)\]", md)]
    firsts = list(dict.fromkeys(nums))
    assert firsts == sorted(firsts) == list(range(1, len(firsts) + 1))


def test_footer_counts_events_per_pair(
    project: Project, agent: Actor, agent_other: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, agent_other, world)
    md = ex.export_sheet(project, sheet)
    line = next(ln for ln in md.splitlines() if ln.startswith("- Agent events"))
    assert re.search(r"skill rf-screen@1a2b3c4d \(\d+ events?\)", line)


def test_cli_out_refuses_overwrite_and_reports_missing_dir(
    project: Project, agent: Actor, agent_other: Actor, world: list[str], tmp_path, monkeypatch
) -> None:
    from factory.cli import main as cli_main

    sheet = _sheet(project, agent, agent_other, world)
    monkeypatch.setattr(cli_main, "_resolve_project", lambda state: project)
    runner = CliRunner()
    for cmd, ident in (("sheets", sheet), ("answers", _answer(project, agent, world))):
        out = tmp_path / f"{cmd}.md"
        out.write_text("KEEP")
        res = runner.invoke(cli_main.app, [cmd, "export", ident, "--out", str(out)])
        assert res.exit_code == 1 and out.read_text() == "KEEP"
        assert "--force" in res.output
        res = runner.invoke(cli_main.app, [cmd, "export", ident, "--out", str(out), "--force"])
        assert res.exit_code == 0 and out.read_text() != "KEEP"
        res = runner.invoke(
            cli_main.app, [cmd, "export", ident, "--out", str(tmp_path / "no" / "x.md")]
        )
        assert res.exit_code == 1 and "Traceback" not in res.output and "no" in res.output
