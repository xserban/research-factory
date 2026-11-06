"""Projection of imports and import records (plan Import-A task 5)."""

from pathlib import Path

from sqlalchemy import text

from factory.imports.model import ImportFormat
from factory.index.default import PROJECTION_VERSION
from factory.model.imports import ImportRole
from factory.services.context import Project
from factory.services.imports import (
    development_ordinals,
    import_part,
    import_records,
    record_import,
)

BIB = """@article{a, title={Made-Up Pears}, author={Quill, Ada and Li, B.}, year={2019},
  doi={10.9999/x.1}, journal={J. Orchards}, url={https://example.org/a}, abstract={Long text.},
  keywords={pears}, file={PDF:files/a.pdf:application/pdf}}
@misc{b, title={Made-Up Fennel}, eprint={2101.00042}, archivePrefix={arXiv}, year={2021}}
@inproceedings{c, year={2020}}
@article{d, title={Made-Up Plums}, year={2018}}
@article{bad, title = {Unclosed
"""


def _import(project: Project, tmp_path: Path, **kwargs: object) -> str:
    path = tmp_path / "lib.bib"
    path.write_text(BIB)
    (tmp_path / "files").mkdir(exist_ok=True)
    (tmp_path / "files" / "a.pdf").write_bytes(b"%PDF-1.4 a")
    summary = record_import(
        project,
        path,
        format=ImportFormat.BIBTEX,
        role=ImportRole.REFERENCE,
        random_seed=3,
        **kwargs,  # type: ignore[arg-type]
    )
    return summary.import_id


def _rows(project: Project, sql: str, **params: object) -> list[tuple[object, ...]]:
    with project.index.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params).all()]


def test_projection_rows_match_blob(project: Project, tmp_path: Path) -> None:
    import_id = _import(project, tmp_path, collection="Pears")
    [imp] = _rows(
        project,
        "SELECT format, role, collection, parser, split_mode, split_seed FROM imports",
    )
    assert imp == ("bibtex", "reference", "Pears", "bibtexparser", "drawn", 3)
    rows = _rows(
        project,
        "SELECT ordinal, outcome, title, first_author, year, doi, arxiv, url, venue, type,"
        " record_sha256, attachment_path_sha256, attachment_content_sha256"
        " FROM import_records WHERE import_id = :i ORDER BY ordinal",
        i=import_id,
    )
    records = import_records(project, import_id)
    assert len(rows) == len(records) == 5
    for row, record in zip(rows, records, strict=True):
        f = record.fields
        attachment = record.attachment
        expected = (
            record.ordinal,
            record.outcome.value,
            f.title if f else None,
            (f.authors[0] if f.authors else None) if f else None,
            f.year if f else None,
            f.doi if f else None,
            f.arxiv if f else None,
            f.url if f else None,
            f.venue if f else None,
            f.type if f else None,
            record.record_sha256,
            attachment.path_sha256 if attachment else None,
            attachment.content_sha256 if attachment else None,
        )
        assert row == expected
    assert rows[0][3] == "Quill, Ada"


def test_part_column_from_split(project: Project, tmp_path: Path) -> None:
    import_id = _import(project, tmp_path)
    parts = dict(
        _rows(project, "SELECT ordinal, part FROM import_records WHERE import_id = :i", i=import_id)
    )
    assert parts[5] == "unsplit"
    assert {parts[o] for o in range(1, 5)} <= {"development", "held-out"}
    assert sorted(o for o, p in parts.items() if p == "development") == development_ordinals(
        project, import_id
    )
    assert all(import_part(project, import_id, o) == p for o, p in parts.items())  # type: ignore[comparison-overlap]


def test_declined_split_leaves_records_unsplit(project: Project, tmp_path: Path) -> None:
    import_id = _import(project, tmp_path, split=False)
    parts = _rows(
        project, "SELECT DISTINCT part FROM import_records WHERE import_id = :i", i=import_id
    )
    assert parts == [("unsplit",)]
    assert _rows(project, "SELECT split_mode, split_seed FROM imports") == [("declined", None)]


def test_rebuild_identical_state_hash(project: Project, tmp_path: Path) -> None:
    _import(project, tmp_path)
    _import(project, tmp_path, split=False)
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert project.index.rebuild() == before


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "59"
