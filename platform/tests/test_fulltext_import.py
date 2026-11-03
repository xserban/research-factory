"""Researcher-supplied folder import (plan 2A, ruling 7).

Identifiers come from the filename first, then from page 1's text (`arXiv:` ids and DOIs). A file
matches exactly one corpus work or is listed. Only promoted works receive documents. The PDFs are
generated here with `pypdf`, so no test touches the network or a real paper.
"""

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.screening import PassLabel
from factory.model.work import Work
from factory.model.work_ids import normalize_doi
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.fulltext_import import ImportReport, import_folder, sniff_identifiers
from factory.services.screening import open_pass
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.helpers import _setup, openalex_item
from tests.test_fulltext_service import _include_all
from tests.test_screening_next import _draw

ARXIV_DOI = "10.48550/arXiv.2301.01234"
ARXIV_ID = "2301.01234"
POSITIVE_DOI = "10.1000/p4"
SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _pdf(path: Path, *lines: str) -> Path:
    """A one-page PDF whose page 1 shows each line in Helvetica (extractable text)."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    shown = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td {shown} ET".encode())
    page = writer.pages[0]
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _work_with_doi(project: Project, doi: str) -> Work:
    [work] = [w for w in list_works(project) if w.identifiers.doi == normalize_doi(doi)]
    return work


def _build(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    leave_arxiv: bool = False,
) -> None:
    """A corpus with a DataCite-DOI arXiv work and every work promoted, unless `leave_arxiv`."""
    protocol_id = _setup(
        project,
        agent,
        human,
        mock_sources,
        dual_sample=0.5,
        random_works=0,
        extra_items=[
            openalex_item(
                title="Linear attention",
                author="Ada Zhou",
                published="2023-01-05",
                openalex_id="W9001",
                doi=ARXIV_DOI,
            )
        ],
    )
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    leave = _work_with_doi(project, ARXIV_DOI).id if leave_arxiv else None
    _include_all(project, agent, human, protocol_id, leave=leave)


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> None:
    _build(project, agent, human, mock_sources)


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _of_type(project: Project, type_: str) -> list[Event]:
    return [event for event in _events(project) if event.type == type_]


def _blob_files(project: Project) -> set[Path]:
    root = project.paths.blobs_dir
    return {p for p in root.rglob("*") if p.is_file()} if root.is_dir() else set()


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "import"
    folder.mkdir(exist_ok=True)
    return folder


# --- Identifier sniffing ---


def test_sniff_filename_arxiv_and_doi(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    arxiv = _pdf(folder / "2301.01234v2.pdf")
    doi = _pdf(folder / "10.1000_p4.pdf")
    bridged = _pdf(folder / "10.48550_arXiv.2301.01234.pdf")
    assert sniff_identifiers(arxiv) == ({"arxiv:2301.01234"}, "filename")
    assert sniff_identifiers(doi) == ({"doi:10.1000/p4"}, "filename")
    assert sniff_identifiers(bridged) == ({"arxiv:2301.01234"}, "filename")


def test_sniff_no_identifier_is_none(tmp_path: Path) -> None:
    path = _pdf(_folder(tmp_path) / "scan.pdf", "Nothing identifying here")
    assert sniff_identifiers(path) == (set(), "none")


def test_sniff_unreadable_pdf_is_none(tmp_path: Path) -> None:
    path = _folder(tmp_path) / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 truncated")
    assert sniff_identifiers(path) == (set(), "none")


# --- Matching and recording ---


def test_filename_arxiv_id_matches(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "2301.01234v2.pdf", "Body text")
    report = import_folder(project, _folder(tmp_path))
    work = _work_with_doi(project, ARXIV_DOI).id
    [(name, imported_work, document)] = report.imported
    assert (name, imported_work) == ("2301.01234v2.pdf", work)
    assert document.startswith("doc_")


def test_filename_doi_with_underscore(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "10.1000_p4.pdf", "Body text")
    report = import_folder(project, _folder(tmp_path))
    [(name, work, _)] = report.imported
    assert name == "10.1000_p4.pdf"
    assert work == _work_with_doi(project, POSITIVE_DOI).id


def test_first_page_arxiv_id_matches(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "paper.pdf", "arXiv:2301.01234v2 [cs.LG]", "Linear attention")
    report = import_folder(project, _folder(tmp_path))
    [(_, work, _)] = report.imported
    assert work == _work_with_doi(project, ARXIV_DOI).id


def test_two_identifiers_in_text_is_ambiguous(
    project: Project, corpus: None, tmp_path: Path
) -> None:
    _pdf(
        _folder(tmp_path) / "paper.pdf",
        "arXiv:2301.01234v2",
        f"cites doi {POSITIVE_DOI}",
    )
    before = len(_of_type(project, "fulltext.document_added"))
    report = import_folder(project, _folder(tmp_path))
    assert report.ambiguous == ["paper.pdf"]
    assert report.imported == []
    assert len(_of_type(project, "fulltext.document_added")) == before


def test_filename_wins_over_text(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "10.1000_p4.pdf", "arXiv:2301.01234v2")
    report = import_folder(project, _folder(tmp_path))
    [(_, work, _)] = report.imported
    assert work == _work_with_doi(project, POSITIVE_DOI).id


def test_unmatched_listed(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "9999.99999.pdf", "Nothing to match")
    report = import_folder(project, _folder(tmp_path))
    assert report == ImportReport(
        imported=[],
        already_imported=[],
        unmatched=["9999.99999.pdf"],
        ambiguous=[],
        not_promoted=[],
        not_pdf=[],
    )


def test_unpromoted_work_not_imported(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, tmp_path: Path
) -> None:
    _build(project, agent, human, mock_sources, leave_arxiv=True)
    arxiv_work = _work_with_doi(project, ARXIV_DOI).id
    assert final_outcomes(project).get(arxiv_work) is not Outcome.INCLUDED
    _pdf(_folder(tmp_path) / "2301.01234v2.pdf", "Body text")
    before = len(_events(project))
    report = import_folder(project, _folder(tmp_path))
    assert report.not_promoted == ["2301.01234v2.pdf"]
    assert report.imported == []
    assert len(_events(project)) == before


def test_non_pdf_listed(project: Project, corpus: None, tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    (folder / "notes.pdf").write_bytes(b"<html>a landing page, not a PDF</html>")
    report = import_folder(project, folder)
    assert report.not_pdf == ["notes.pdf"]
    assert report.imported == []


def test_reimport_is_idempotent(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "2301.01234v2.pdf", "Body text")
    first = import_folder(project, _folder(tmp_path))
    assert len(first.imported) == 1
    before = len(_events(project))

    second = import_folder(project, _folder(tmp_path))

    assert second.already_imported == ["2301.01234v2.pdf"]
    assert second.imported == []
    assert len(_events(project)) == before


def test_import_writes_library_only(project: Project, corpus: None, tmp_path: Path) -> None:
    _pdf(_folder(tmp_path) / "2301.01234v2.pdf", "Body text")
    blobs_before = _blob_files(project)
    report = import_folder(project, _folder(tmp_path))
    assert _blob_files(project) == blobs_before
    [(_, _, document)] = report.imported
    [added] = [e for e in _of_type(project, "fulltext.document_added") if e.refs[0] == document]
    assert project.library.exists(str(added.payload["raw_hash"]))


def test_attempt_and_document_recorded_for_researcher(
    project: Project, corpus: None, tmp_path: Path
) -> None:
    path = _pdf(_folder(tmp_path) / "2301.01234v2.pdf", "Body text")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report = import_folder(project, _folder(tmp_path))
    [(_, work, document)] = report.imported

    [attempt] = _of_type(project, "fulltext.attempted")
    payload = attempt.payload
    assert payload["route"] == "researcher-supplied"
    assert payload["url"] is None
    assert payload["reason"] is None
    assert payload["outcome"] == "retrieved"
    assert payload["licence_status"] == "not-reported"
    assert payload["source_version"] == f"file:{digest[:12]}"
    assert payload["document_id"] == document
    assert attempt.actor.kind == "human"

    [added] = _of_type(project, "fulltext.document_added")
    assert added.payload["provenance"] == "researcher-supplied"
    assert added.payload["work_id"] == work
    assert added.payload["quality"] == "pdf-text"
    assert added.actor.kind == "human"


def test_missing_folder_refused(project: Project, tmp_path: Path) -> None:
    with pytest.raises(FactoryValidationError):
        import_folder(project, tmp_path / "absent")
