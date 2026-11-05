"""Attaching export-named PDFs to promoted works (Import-B task 5).

Every record, work and PDF is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.imports.model import ImportFormat
from factory.model.fulltext import Route
from factory.model.imports import ImportRole
from factory.model.references import Decision, LinkState
from factory.services.context import Project
from factory.services.import_attach import attach_import
from factory.services.import_resolve import decide_import, record_states, resolve_import
from factory.services.imports import record_import
from factory.services.search import get_work
from tests.document_helpers import events_of_type
from tests.fulltext_helpers import _pdf
from tests.import_helpers import import_bib
from tests.references_service_helpers import Lookups

MARKER = "ZEBRAXQ"


def _bib(key: str, title: str, doi: str, file: str | None) -> str:
    attached = f", file={{PDF:{file}:application/pdf}}" if file else ""
    head = f"@article{{{key}, title={{{title}}}, author={{Zhou, Ada}}, year={{2020}}"
    return f"{head}, doi={{{doi}}}{attached}}}\n"


def _doi(project: Project, work_id: str) -> str:
    work = get_work(project, work_id)
    assert work is not None and work.identifiers.doi is not None
    return work.identifiers.doi


@pytest.fixture
def attachable(project: Project, corpus_leaving: str, tmp_path: Path) -> tuple[str, str]:
    """A resolved BibTeX import: record 1 names a PDF for a promoted work, record 2 for the work
    left unpromoted, record 3 names a file that does not exist, record 4 names no file."""
    files = tmp_path / "files"
    files.mkdir()
    _pdf(files / "a.pdf", "A made-up first page", MARKER)
    _pdf(files / "b.pdf", "Another made-up first page")
    promoted = next(
        w for w in ("10.1000/p1", "10.1000/p2", "10.1000/p3") if w != _doi(project, corpus_leaving)
    )
    imp = import_bib(
        project,
        tmp_path,
        [
            _bib("a", "Promoted", promoted, "files/a.pdf"),
            _bib("b", "Left", _doi(project, corpus_leaving), "files/b.pdf"),
            _bib("c", "Missing", "10.1000/p9", "files/gone.pdf"),
            _bib("d", "Plain", "10.1000/p8", None),
        ],
    )
    resolve_import(project, imp, sources=Lookups().sources())
    return imp, corpus_leaving


def _documents(project: Project) -> list[tuple[str, str, str]]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT document_id, work_id, route FROM fulltext_documents ORDER BY document_id")
        ).all()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


def test_attach_requires_promotion(project: Project, attachable: tuple[str, str]) -> None:
    imp, left = attachable
    report = attach_import(project, imp)
    assert [o for o, _, _ in report.attached] == [1]
    assert report.not_promoted == [2]
    assert left not in {work for _, work, _ in _documents(project)}


def test_attach_records_researcher_route_document(
    project: Project, attachable: tuple[str, str]
) -> None:
    imp, _ = attachable
    report = attach_import(project, imp)
    [(ordinal, work, document)] = report.attached
    assert _documents(project) == [(document, work, Route.RESEARCHER.value)]
    [link] = events_of_type(project, "import.attachment_linked")
    assert link.payload == {
        "import_id": imp,
        "ordinal": ordinal,
        "work_id": work,
        "document_id": document,
    }
    # the link is appended with the attempt and the document: three consecutive events
    types = [e.type for e in read_all(project.paths.events_dir, project.catalog)]
    at = types.index("import.attachment_linked")
    assert types[at - 2 : at + 1] == [
        "fulltext.attempted",
        "fulltext.document_added",
        "import.attachment_linked",
    ]
    assert link.actor.kind == "human"


def test_missing_bytes_listed(project: Project, attachable: tuple[str, str]) -> None:
    imp, _ = attachable
    report = attach_import(project, imp)
    assert report.attachment_missing == [3]
    assert 4 not in {*report.not_promoted, *report.attachment_missing, *report.unresolved}


def test_attach_idempotent(project: Project, attachable: tuple[str, str]) -> None:
    imp, _ = attachable
    attach_import(project, imp)
    before = len(read_all(project.paths.events_dir, project.catalog))
    again = attach_import(project, imp)
    assert again.attached == [] and again.already_attached == [1]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_unknown_import_writes_nothing(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        attach_import(project, "imp_" + "0" * 26)


def _pdf_folder_import(project: Project, tmp_path: Path, promoted: list[str]) -> str:
    folder = tmp_path / "pdfs"
    folder.mkdir()
    # the first names its work by DOI and shows the work's title; the second shows another title
    _pdf(folder / "10.1000_p2.pdf", f"Paper 2 {MARKER}")
    _pdf(folder / "10.1000_p3.pdf", "A different first page")
    imp = record_import(
        project, folder, format=ImportFormat.PDFS, role=ImportRole.REFERENCE, split=False
    ).import_id
    resolve_import(project, imp, sources=Lookups().sources())
    return imp


def test_pdf_title_cross_check(project: Project, corpus: None, tmp_path: Path) -> None:
    imp = _pdf_folder_import(project, tmp_path, [])
    assert record_states(project, imp) == {1: LinkState.RESOLVED, 2: LinkState.RESOLVED}
    report = attach_import(project, imp)
    assert [o for o, _, _ in report.attached] == [1]
    assert report.identity_unchecked == [2]


def test_identity_unchecked_attached_after_confirmation(
    project: Project, corpus: None, tmp_path: Path, human: Actor, agent: Actor
) -> None:
    imp = _pdf_folder_import(project, tmp_path, [])
    attach_import(project, imp)
    with pytest.raises(FactoryValidationError):  # an agent cannot vouch for a file's identity
        decide_import(project, agent, imp, 2, Decision.CONFIRM, rationale="Looks right.")
    decide_import(project, human, imp, 2, Decision.CONFIRM, rationale="Checked the scan by eye.")
    assert record_states(project, imp)[2] is LinkState.RESOLVED
    report = attach_import(project, imp)
    assert [o for o, _, _ in report.attached] == [2]
    assert report.identity_unchecked == [] and report.already_attached == [1]


def test_first_page_text_not_stored(project: Project, corpus: None, tmp_path: Path) -> None:
    imp = _pdf_folder_import(project, tmp_path, [])
    attach_import(project, imp)
    for root in (project.paths.events_dir, project.paths.blobs_dir):
        for path in root.rglob("*"):
            if path.is_file():
                assert MARKER.encode() not in path.read_bytes(), path
