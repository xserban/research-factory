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
from factory.services.imports import import_part, import_records, list_imports, record_import
from tests.cli_helpers import _cli_env, runner
from tests.helpers import _of_type

BIB = (
    "\n".join(
        f"@article{{k{w}, title={{Made-Up Title {w}}}, year={{{2000 + i}}}, doi={{10.9999/m.{w}}}}}"
        for i, w in enumerate(["alder", "birch", "cedar", "hazel", "larch", "maple"], start=1)
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
    parts = {o: import_part(project, s.import_id, o) for o in range(1, 8)}
    held_out = {o for o, p in parts.items() if p == "held-out"}
    assert held_out

    default = _invoke(settings, "import", "show", s.import_id)
    assert default.exit_code == 0, default.stderr
    assert "held-out" not in default.stdout
    assert _row_keys(default.stdout) == _expected_keys(project, s.import_id)

    for part in ("held-out", "all"):
        refused = _invoke(settings, "import", "show", s.import_id, "--part", part)
        assert refused.exit_code == 1 and "--researcher" in refused.stderr
        assert "held-out" not in refused.stdout

    held = _invoke(settings, "import", "show", s.import_id, "--part", "held-out", "--researcher")
    assert held.exit_code == 0, held.stderr
    assert "must not be shown to agents" in held.stderr
    held_rows = [line for line in held.stdout.splitlines() if line[:1].isdigit()]
    assert {int(line.split()[0]) for line in held_rows} == held_out
    assert all(line.split()[1] == "held-out" for line in held_rows)

    everything = _invoke(settings, "import", "show", s.import_id, "--part", "all", "--researcher")
    lines = everything.stdout.splitlines()
    for ordinal, part in parts.items():
        assert any(line.split()[:2] == [str(ordinal), part] for line in lines), everything.stdout


def _rows(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("sha256:")]


def _row_keys(stdout: str) -> list[str]:
    return [line.split()[0] for line in _rows(stdout)]


def _expected_keys(project: Project, import_id: str) -> list[str]:
    """The default view as a function of the records that are not held out, and nothing else."""
    return sorted(
        f"sha256:{r.record_sha256[:16]}"
        for r in import_records(project, import_id)
        if import_part(project, import_id, r.ordinal) != "held-out"
    )


def test_cli_show_default_prints_no_ordinals(
    project: Project, settings: Settings, tmp_path: Path
) -> None:
    """Two imports of one file whose held-out parts differ: each default view is determined by
    its development records alone, carries no source ordinal, and counts the held-out part."""
    path = _bib(tmp_path)
    first = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=1
    )
    held_first = {o for o in range(1, 8) if import_part(project, first.import_id, o) == "held-out"}
    second = None
    for seed in range(2, 50):
        candidate = record_import(
            project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=seed
        )
        held = {
            o for o in range(1, 8) if import_part(project, candidate.import_id, o) == "held-out"
        }
        if held != held_first:
            second = candidate
            break
    assert second is not None
    outputs = []
    for imported in (first, second):
        result = _invoke(settings, "import", "show", imported.import_id)
        assert result.exit_code == 0 and result.stderr == ""
        rows = _rows(result.stdout)
        assert _row_keys(result.stdout) == _expected_keys(project, imported.import_id)
        tokens = {token for row in rows for token in row.split()}
        assert not tokens & {str(o) for o in range(1, 8)}
        assert "held out: 2" in result.stdout
        outputs.append(result.stdout)
    assert outputs[0] != outputs[1]


def test_cli_default_outputs_hide_held_out(
    project: Project, settings: Settings, tmp_path: Path
) -> None:
    recorded = _invoke(settings, "import", "bib", str(_bib(tmp_path)), "--role", "reference")
    assert recorded.exit_code == 0, recorded.stderr
    listed = _invoke(settings, "import", "list")
    for output in (recorded.stdout, listed.stdout):
        assert "held-out" not in output and "held_out" not in output


def test_cli_show_unsplit_import_lists_every_record(
    project: Project, settings: Settings, tmp_path: Path
) -> None:
    s = record_import(
        project, _bib(tmp_path), format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, split=False
    )
    result = _invoke(settings, "import", "show", s.import_id)
    assert len(_rows(result.stdout)) == 7 and "held out: 0" in result.stdout
    assert result.stderr == ""


def test_cli_show_unknown_import(project: Project, settings: Settings) -> None:
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
