"""`factory report evidence` (plan E, task 8)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli import main as cli_main
from factory.cli.evidence_render import POINTS_COLUMNS
from factory.cli.main import app
from factory.config import Settings
from factory.services.context import Project
from factory.services.evidence_report import EvidenceReport, assemble_report
from tests.cli_helpers import _env
from tests.evidence_helpers import pilot_inputs

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["report", "evidence", *args], env=_env(root))
    return result.exit_code, result.stdout, result.stderr


@pytest.fixture
def report(monkeypatch: pytest.MonkeyPatch) -> EvidenceReport:
    full = assemble_report(pilot_inputs())
    monkeypatch.setattr(
        cli_main.evidence_report_service,
        "evidence_report",
        lambda _p, expect=(), include_notice_affected=False, without_grey=False: full,
    )
    return full


def test_md_is_default_and_has_group_sections(
    settings: Settings, project: Project, report: EvidenceReport
) -> None:
    code, out, err = _run(settings.root)
    assert code == 0, err
    assert report.groups
    for g in report.groups:
        assert g.group_id in out


def test_json_equals_model_dump(
    settings: Settings, project: Project, report: EvidenceReport
) -> None:
    code, out, err = _run(settings.root, "--format", "json")
    assert code == 0, err
    assert out.strip() == report.model_dump_json()


def test_csv_points_header_exact(
    settings: Settings, project: Project, report: EvidenceReport
) -> None:
    code, out, err = _run(settings.root, "--format", "csv-points")
    assert code == 0, err
    assert out.splitlines()[0] == POINTS_COLUMNS


def test_expect_without_match_yields_expectation_empty(
    settings: Settings, project: Project
) -> None:
    code, out, err = _run(settings.root, "--expect", "dataset=coco", "--format", "json")
    assert code == 0, err
    assert "expectation-empty" in out


def test_output_writes_file(
    settings: Settings, project: Project, report: EvidenceReport, tmp_path: Path
) -> None:
    target = tmp_path / "out.csv"
    code, out, err = _run(settings.root, "--format", "csv-rows", "--output", str(target))
    assert code == 0, err
    assert out == ""
    assert target.read_text(encoding="utf-8").startswith("group_id,")


@pytest.mark.parametrize("bad", ["dataset", "=coco", "dataset=", "a=1,a=2", "a=1,b"])
def test_bad_expect_is_refused(settings: Settings, project: Project, bad: str) -> None:
    code, _out, err = _run(settings.root, "--expect", bad)
    assert code == 2
    assert "bad --expect" in err


def test_output_into_missing_directory_fails_cleanly(
    settings: Settings, project: Project, report: EvidenceReport, tmp_path: Path
) -> None:
    target = tmp_path / "missing" / "out.md"
    code, _out, err = _run(settings.root, "--output", str(target))
    assert code == 1
    assert str(target) in err
