"""`factory import bib|csl|pdfs|list|show` (plan Import-A task 6). Synthetic fixtures only."""

import json
from datetime import timedelta
from pathlib import Path

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.services.context import Project
from factory.services.imports import import_part, list_imports, record_import
from tests.helpers import _of_type
from tests.test_cli import _cli_env, runner

BIB = (
    "\n".join(
        f"@article{{k{i}, title={{Made-Up Title {i}}}, year={{{2000 + i}}}, doi={{10.9999/m.{i}}}}}"
        for i in range(1, 7)
    )
    + "\n@article{bad, title = {Unclosed\n"
)


def _bib(tmp_path: Path) -> Path:
    path = tmp_path / "library.bib"
    path.write_text(BIB)
    return path


def _invoke(settings: Settings, *args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, list(args), env=_cli_env(settings.root))


def test_cli_bib_prints_counts_and_id(project: Project, settings: Settings, tmp_path: Path) -> None:
    result = _invoke(
        settings, "import", "bib", str(_bib(tmp_path)), "--role", "reference", "--seed", "4"
    )
    assert result.exit_code == 0, result.stderr
    [listed] = [i.row for i in list_imports(project)]
    out = result.stdout
    assert listed.import_id in out
    assert "parsed: 6" in out and "malformed: 1" in out and "no-title-no-identifier: 0" in out
    assert "split: drawn" in out
    assert listed.split_seed == 4 and listed.role is ImportRole.REFERENCE


def test_cli_csl_and_pdfs_and_options(project: Project, settings: Settings, tmp_path: Path) -> None:
    csl = tmp_path / "lib.json"
    csl.write_text(json.dumps([{"title": "Made-Up"}]))
    folder = tmp_path / "pdfs"
    folder.mkdir()
    (folder / "2101.00042.pdf").write_bytes(b"%PDF-1.4 x")
    first = _invoke(
        settings,
        "import",
        "csl",
        str(csl),
        "--role",
        "corpus",
        "--collection",
        "Pears",
        "--no-split",
    )
    assert first.exit_code == 0, first.stderr
    assert "split: declined" in first.stdout
    second = _invoke(settings, "import", "pdfs", str(folder), "--role", "reference")
    assert second.exit_code == 0, second.stderr
    rows = [i.row for i in list_imports(project)]
    assert [(r.format, r.collection) for r in rows] == [
        (ImportFormat.CSL, "Pears"),
        (ImportFormat.PDFS, None),
    ]


def test_cli_refuses_missing_file_writes_nothing(
    project: Project, settings: Settings, tmp_path: Path
) -> None:
    result = _invoke(settings, "import", "bib", str(tmp_path / "absent.bib"), "--role", "reference")
    assert result.exit_code == 1
    assert "path:" in result.stderr
    assert _of_type(project, "import.recorded") == []


def test_cli_show_lists_parts(project: Project, settings: Settings, tmp_path: Path) -> None:
    s = record_import(
        project,
        _bib(tmp_path),
        format=ImportFormat.BIBTEX,
        role=ImportRole.REFERENCE,
        random_seed=1,
    )
    result = _invoke(settings, "import", "show", s.import_id)
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    for ordinal in range(1, 8):
        part = import_part(project, s.import_id, ordinal)
        assert any(line.split()[:2] == [str(ordinal), part] for line in lines), result.stdout
    held = _invoke(settings, "import", "show", s.import_id, "--part", "held-out")
    held_rows = [line for line in held.stdout.splitlines() if line[:1].isdigit()]
    assert held_rows and all(line.split()[1] == "held-out" for line in held_rows)
    dev = _invoke(settings, "import", "show", s.import_id, "--part", "development")
    dev_rows = [line for line in dev.stdout.splitlines() if line[:1].isdigit()]
    assert len(dev_rows) + len(held_rows) == 6
    missing = _invoke(settings, "import", "show", "imp_01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert missing.exit_code == 1 and "import_id" in missing.stderr


def test_cli_list_orders_by_time(
    project: Project, settings: Settings, tmp_path: Path, clock: FixedClock
) -> None:
    path = _bib(tmp_path)
    first = record_import(project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    clock.advance(timedelta(seconds=5))
    second = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.CORPUS, collection="Plums"
    )
    result = _invoke(settings, "import", "list")
    assert result.exit_code == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("imp_")]
    assert [line.split()[0] for line in lines] == [first.import_id, second.import_id]
    assert "Plums" in lines[1] and "corpus" in lines[1]
