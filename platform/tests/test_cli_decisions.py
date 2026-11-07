"""The `factory decide` commands (slice 8, plan A5)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.services import decisions as decisions_service
from factory.services.context import Project
from tests.cli_helpers import _env

runner = CliRunner()
MISSING = "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X"


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _suggest(project: Project, agent: Actor, **over: object) -> str:
    args: dict[str, object] = {
        "level": DecisionLevel.PROTOCOL,
        "subject": "exclusions",
        "explanation": "The exclusions set what leaves the corpus.",
        "items": (
            DecisionItem(item_id="I01", text="Exclude preprints", grounds=("prb_1",)),
            DecisionItem(item_id="I02", text="Keep preprints"),
            DecisionItem(item_id="I03", text="Exclude non-English"),
        ),
    }
    args.update(over)
    return decisions_service.suggest(project, agent, **args)  # type: ignore[arg-type]


def test_list_and_show(settings: Settings, project: Project, agent: Actor) -> None:
    assert _run(settings.root, "decide", "list")[1].strip() == "no decisions"
    first = _suggest(project, agent)
    _suggest(project, agent, level=DecisionLevel.GOAL, subject="objective")
    code, out, _ = _run(settings.root, "decide", "list", "--level", "protocol")
    assert code == 0 and first in out and "objective" not in out and "0/3 selected" in out
    code, out, _ = _run(settings.root, "decide", "list", "--open")
    assert code == 0 and out.count("open") == 2
    assert _run(settings.root, "decide", "list", "--level", "nonsense")[0] == 1
    code, out, _ = _run(settings.root, "decide", "show", first)
    assert code == 0
    assert "[ ] I01  Exclude preprints" in out and "grounds: prb_1" in out
    assert _run(settings.root, "decide", "show", MISSING)[0] == 1


def test_select_ticks_adds_and_records_the_cli_channel(
    settings: Settings, project: Project, agent: Actor
) -> None:
    decision_id = _suggest(project, agent)
    code, out, _ = _run(
        settings.root,
        "decide",
        "select",
        decision_id,
        "--item",
        "I01",
        "--item",
        "I03",
        "--add",
        "Exclude theses",
        "--note",
        "keep it narrow",
    )
    assert code == 0 and out.strip() == f"selected {decision_id}: kept I01, I03; added 1"
    [event] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "decision.selected"
    ]
    assert event.actor.kind == "human" and event.input_blob is None
    assert event.payload["channel"] == "cli" and event.payload["reconstructed"] is False
    code, out, _ = _run(settings.root, "decide", "show", decision_id)
    assert "[x] I01" in out and "[-] I02" in out and "[+] A01  Exclude theses" in out
    assert "note: keep it narrow" in out
    assert _run(settings.root, "decide", "list", "--open")[1].strip() == "no decisions"


def test_select_refusals_write_nothing(settings: Settings, project: Project, agent: Actor) -> None:
    decision_id = _suggest(project, agent)
    code, _, err = _run(settings.root, "decide", "select", decision_id)
    assert code == 1 and "note" in err
    code, _, err = _run(settings.root, "decide", "select", decision_id, "--item", "I09")
    assert code == 1 and "selected.0" in err
    code, _, err = _run(settings.root, "decide", "select", MISSING, "--item", "I01")
    assert code == 1 and "decision_id" in err
    types = [e.type for e in read_all(project.paths.events_dir, project.catalog)]
    assert "decision.selected" not in types
    code, out, _ = _run(settings.root, "decide", "select", decision_id, "--note", "none fits")
    assert code == 0 and "kept none" in out


def test_reconstructed_flag(settings: Settings, project: Project, agent: Actor) -> None:
    decision_id = _suggest(project, agent)
    code, _, _ = _run(
        settings.root, "decide", "select", decision_id, "--item", "I02", "--reconstructed"
    )
    assert code == 0
    code, out, _ = _run(settings.root, "decide", "show", decision_id)
    assert "(reconstructed)" in out and "via cli" in out
