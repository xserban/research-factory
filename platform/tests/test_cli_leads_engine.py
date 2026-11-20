"""`factory leads candidates|queue|stats`: read-only, labelled, and the same figures as the
service (R-05)."""

# ruff: noqa: F811
import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli import render
from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.lead_engine import (
    SOURCES,
    Candidate,
    CandidateQuote,
    Candidates,
    CandidateTrigger,
    CandidateWork,
)
from factory.services.context import Project
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_queue import lead_queue
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.lead_engine_helpers import engine_world

runner = CliRunner()
KNOBS = ("--layer", "all", "--technique-min-works", "1")


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["leads", *args], env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_every_output_is_labelled_and_json_equals_the_service(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    for args in (("candidates",), ("queue",), ("stats",)):
        extra = KNOBS if args[0] != "stats" else ()
        code, out, err = _run(settings.root, *args, *extra)
        assert code == 0, (args, err)
        assert out.startswith("EXPLORATORY:"), args
    code, out, err = _run(settings.root, "candidates", "--format", "json", *KNOBS)
    assert code == 0, err
    want = lead_candidates(project, layer="all", technique_min_works=1)
    assert json.loads(out) == json.loads(want.model_dump_json(by_alias=True))
    code, out, err = _run(settings.root, "queue", "--format", "json", *KNOBS)
    assert code == 0, err
    got = json.loads(out)
    assert got["exploratory"] is True and got["parameters"]["balance"] == 1
    again = lead_queue(project, layer="all", technique_min_works=1)
    assert got == json.loads(again.model_dump_json(by_alias=True))
    code, out, err = _run(settings.root, "stats", "--format", "json")
    assert code == 0 and json.loads(out)["recorded"] == 0, err


def test_the_options_reach_the_service(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    code, out, err = _run(
        settings.root,
        "queue",
        "--format",
        "json",
        "--sources",
        "technique-gap,claims-limitation",
        "--order-by",
        "support,score",
        "--top",
        "1",
        "--no-balance",
        "--exclude-prior",
        "--per-source",
        "5",
        "--max-co-works",
        "1",
        "--no-group-claims",
        *KNOBS,
    )
    assert code == 0, err
    data = json.loads(out)
    assert data["order_by"] == ["support", "score"] and len(data["items"]) == 1
    p = data["parameters"]
    assert p["sources"] == ["technique-gap", "claims-limitation"] and p["top"] == 1
    assert p["balance"] == 0 and p["exclude_prior"] == 1 and p["per_source"] == 5
    assert p["max_co_works"] == 1 and p["technique_min_works"] == 1
    assert p["group_claims_by_work"] == 0
    code, out, err = _run(settings.root, "queue", "--format", "json", *KNOBS)
    assert code == 0, err
    assert json.loads(out)["parameters"]["group_claims_by_work"] == 1
    code, out, err = _run(
        settings.root, "queue", "--format", "json", "--per-source-top", "1", *KNOBS
    )
    assert code == 0, err
    assert (
        len(json.loads(out)["items"]) == len({i["source"] for i in json.loads(out)["items"]})
        and json.loads(out)["parameters"]["per_source_top"] == 1
    )
    assert SOURCES  # the default sources are all four


def test_bad_options_are_refused_and_there_is_no_recording_command(
    settings: Settings, project: Project
) -> None:
    for args in (
        ("queue", "--order-by", "nope"),
        ("queue", "--top", "0"),
        ("candidates", "--sources", "nope"),
        ("candidates", "--sources", ","),
        ("queue", "--format", "xml"),
        ("queue", "--no-balance", "--per-source-top", "2"),
    ):
        code, _, err = _run(settings.root, *args)
        assert code != 0, args
    for args in (
        ("queue", "--order-by", "nope"),
        ("queue", "--top", "0"),
        ("queue", "--no-balance", "--per-source-top", "2"),
    ):  # a service refusal carries the notice, as the MCP's does
        code, _, err = _run(settings.root, *args)
        assert code != 0 and "EXPLORATORY" in err, args
    code, _, _ = _run(settings.root, "record")
    assert code != 0


def test_the_table_is_compact_and_full_and_show_print_everything(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    for args in (("candidates",), ("queue",), ("stats",)):
        extra = KNOBS if args[0] != "stats" else ()
        code, out, err = _run(settings.root, *args, *extra)
        assert code == 0, err
        assert out.startswith("EXPLORATORY:")
        assert max(len(line) for line in out.splitlines()) <= render.WIDTH, args
        if args[0] != "stats":
            assert "--full" in out and "--show" in out
            assert "triggers:" not in out  # the compact view lists no trigger ids
    code, full, err = _run(settings.root, "candidates", "--full", *KNOBS)
    assert code == 0 and "triggers:" in full and "quote " in full, err
    want = lead_candidates(project, layer="all", technique_min_works=1).candidates
    assert len(want) > 1
    code, one, err = _run(settings.root, "candidates", "--top", "1", *KNOBS)
    assert code == 0, err
    rows = [ln for ln in one.splitlines() if ln.startswith(" 1 ") or ln.startswith(" 2 ")]
    assert len(rows) == 1 and rows[0].startswith(" 1 ")
    combo = next(c for c in want if c.source == "technique-combination")
    for cmd in ("candidates", "queue"):
        code, shown, err = _run(settings.root, cmd, "--show", combo.candidate_id, *KNOBS)
        assert code == 0, err
        assert shown.startswith("EXPLORATORY:") and "triggers:" in shown
        assert shown.count("  quote ") == len(combo.quotes) and "side=" in shown
        assert all(t.ref in shown for t in combo.triggers)
        code, _, err = _run(settings.root, cmd, "--show", "technique-gap:nope", *KNOBS)
        assert code != 0
        code, js, err = _run(
            settings.root, cmd, "--show", combo.candidate_id, "--format", "json", *KNOBS
        )
        assert code == 0 and combo.candidate_id in js, err
    code, rec, err = _run(settings.root, "queue", "--recorded", "hide", "--format", "json", *KNOBS)
    assert code == 0 and json.loads(rec)["parameters"]["recorded"] == "hide", err
    code, _, err = _run(settings.root, "queue", "--recorded", "nope", *KNOBS)
    assert code != 0 and "EXPLORATORY" in err


def test_a_long_quote_is_cut_at_160_characters_and_no_line_exceeds_the_width() -> None:
    long = "word " * 200
    c = Candidate(
        candidate_id="technique-combination:a+b",
        source="technique-combination",
        observation="obs " * 80,
        approaches=("a", "b"),
        works=(CandidateWork(work_id="w1", title="T"),),
        works_total=1,
        quotes=(
            CandidateQuote(
                role="a", work_id="w1", extraction_id="ext_1", quote=long, anchor="s1", side="a"
            ),
            CandidateQuote(
                role="b", work_id="w1", extraction_id="ext_2", quote="second", anchor="s1"
            ),
        ),
        triggers=(CandidateTrigger(kind="item", ref="ext_1"),),
        basis=(),
        miners=("m v1",),
        flags=("x" * 300,),
    )
    result = Candidates(
        parameters={"sources": SOURCES},
        totals={"technique-combination": 1},
        candidates=(c,),
    )
    lines = render.lead_candidates_lines(result)
    assert all(len(line) <= render.WIDTH for line in lines)
    quote_text = "".join(
        ln.strip() for ln in lines if ln.startswith("    ") or ln.startswith("      ")
    )
    assert "…" in quote_text and "second" not in quote_text  # first quote only, cut
    shown = [ln for ln in lines if "word" in ln]
    assert sum(len(ln.replace("word", "").strip()) for ln in shown) < 160 + 40
    assert "obs " * 80 not in "\n".join(lines)
    full = render.lead_candidates_lines(result, full=True)
    assert any("second" in ln for ln in full) and any(len(ln) > render.WIDTH for ln in full)
