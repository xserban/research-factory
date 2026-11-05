"""`factory modules`: the declared modules with their gates, task kinds, checks and strategies."""

import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.services.modules import default_modules
from factory.services.modules.listing import ModuleRow, module_rows

runner = CliRunner()


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def test_rows_are_computed_from_the_declarations() -> None:
    rows = {row.name: row for row in module_rows()}
    assert list(rows) == [m.spec.name for m in default_modules().modules()]
    screening = rows["screening"]
    assert screening.kind == "filter"
    assert screening.task_kinds == ["screen_a", "screen_b", "screen_ft_a", "screen_ft_b"]
    assert {g.gate_id: g.floor for g in screening.gates} == {
        "screening.calibration_label": "human",
        "screening.resolve": "human",
        "screening.audit_label": "human",
    }
    assert "kappa-below-floor" in screening.checks
    assert screening.events == len(default_modules().module("screening").spec.events.types)
    extraction = rows["extraction"]
    assert extraction.note is not None and extraction.note.startswith("historical name")
    assert rows["references"].gates[0].floor == "agent_audit"
    assert rows["scoping"].strategies == ["interview 1 (rf-frame)", "probe 1 (rf-probe)"]


def test_cli_lists_every_module(tmp_path: Path) -> None:
    result = runner.invoke(app, ["modules"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    for module in default_modules().modules():
        assert module.spec.name in result.stdout
    assert "screening.calibration_label (human)" in result.stdout
    assert "historical name" in result.stdout


def test_cli_json_parses_into_the_rows(tmp_path: Path) -> None:
    result = runner.invoke(app, ["modules", "--json"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    rows = [ModuleRow.model_validate(item) for item in json.loads(result.stdout)]
    assert rows == module_rows()
    again = runner.invoke(app, ["modules", "--json"], env=_env(tmp_path))
    assert again.stdout == result.stdout
