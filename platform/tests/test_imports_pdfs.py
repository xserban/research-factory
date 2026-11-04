"""PDF-folder import parser and the parser registry (slice 3d, plan Import-A task 2).

PDFs are generated with `pypdf`; titles and identifiers are made up.
"""

import hashlib
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from factory.imports.bibtex import parse_bibtex
from factory.imports.model import NOT_PDF, ImportFormat, ImportFormatError, ParseOutcome
from factory.imports.pdfs import parse_pdf_folder
from factory.imports.registry import PARSERS, parse
from tests.test_fulltext_import import _pdf


def _titled(path: Path, title: str) -> Path:
    writer = PdfWriter(clone_from=PdfReader(_pdf(path, "No identifiers here")))
    writer.add_metadata({"/Title": title})
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def test_pdf_folder_identifier_from_filename(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "2101.00042v1.pdf", "Some text")
    parsed = parse_pdf_folder(tmp_path)
    assert parsed.format is ImportFormat.PDFS
    [r] = parsed.records
    assert r.outcome is ParseOutcome.PARSED and r.fields is not None
    assert r.fields.arxiv == "2101.00042" and r.fields.type == "preprint"
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert r.record_sha256 == digest
    assert r.attachment is not None and r.attachment.content_sha256 == digest
    assert r.attachment.path_sha256 == hashlib.sha256(b"2101.00042v1.pdf").hexdigest()
    assert parsed.attachment_bytes == {digest: pdf.read_bytes()}


def test_pdf_folder_doi_from_first_page(tmp_path: Path) -> None:
    _pdf(tmp_path / "paper.pdf", "doi 10.9999/fennel.3 in text")
    [r] = parse_pdf_folder(tmp_path).records
    assert r.fields is not None and r.fields.doi == "10.9999/fennel.3"


def test_pdf_folder_metadata_title_only(tmp_path: Path) -> None:
    _titled(tmp_path / "a.pdf", "A Made-Up Title About Pears")
    [r] = parse_pdf_folder(tmp_path).records
    assert r.outcome is ParseOutcome.PARSED and r.fields is not None
    assert r.fields.title == "A Made-Up Title About Pears"
    assert (r.fields.doi, r.fields.arxiv) == (None, None)


def test_pdf_folder_nothing_found(tmp_path: Path) -> None:
    _pdf(tmp_path / "plain.pdf", "Nothing to see")
    [r] = parse_pdf_folder(tmp_path).records
    assert r.outcome is ParseOutcome.NO_TITLE_NO_IDENTIFIER


def test_not_pdf_skipped_and_flagged(tmp_path: Path) -> None:
    _pdf(tmp_path / "b.pdf", "Nothing")
    (tmp_path / "a.pdf").write_bytes(b"not a pdf at all")
    (tmp_path / "notes.txt").write_text("ignored")
    records = parse_pdf_folder(tmp_path).records
    assert [(r.ordinal, r.outcome) for r in records] == [
        (1, ParseOutcome.MALFORMED),
        (2, ParseOutcome.NO_TITLE_NO_IDENTIFIER),
    ]
    assert records[0].flags == (NOT_PDF,) and records[0].fields is None


def test_pdf_folder_not_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ImportFormatError):
        parse_pdf_folder(tmp_path / "missing")


def test_registry_dispatch(tmp_path: Path) -> None:
    bib = tmp_path / "lib.bib"
    bib.write_text("@article{k, title={T}}")
    csl = tmp_path / "lib.json"
    csl.write_text('[{"title": "T"}]')
    folder = tmp_path / "pdfs"
    folder.mkdir()
    _pdf(folder / "2101.00042.pdf", "x")
    assert set(PARSERS) == set(ImportFormat)
    assert parse(ImportFormat.BIBTEX, bib) == parse_bibtex(bib.read_bytes(), tmp_path)
    assert parse(ImportFormat.CSL, csl).format is ImportFormat.CSL
    assert parse(ImportFormat.PDFS, folder).records[0].fields is not None


def test_sniff_identifiers_reexported() -> None:
    from factory.imports.pdfs import sniff_identifiers as moved
    from factory.services.fulltext_import import sniff_identifiers

    assert sniff_identifiers is moved
