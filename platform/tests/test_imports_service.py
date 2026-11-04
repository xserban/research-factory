"""Recording an import: archive, allow-listed records blob, one `import.recorded` event (task 3).

Fixtures are synthetic: made-up titles, authors and identifiers.
"""

import hashlib
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Event
from factory.imports.model import ImportFormat, ParseOutcome
from factory.model.imports import ImportRecorded, ImportRole
from factory.services.context import Project
from factory.services.imports import import_records, record_import, record_key
from tests.helpers import _of_type

BIB = """@article{quill2019,
  title = {On the Quiet Growth of Pear Trees},
  author = {Quill, Ada and Bramble, Tobias},
  year = {2019},
  doi = {10.9999/orchard.0001},
  annote = {my private note about pears},
  note = {another personal remark},
  file = {Full Text PDF:/Users/someone/Zotero/storage/AB12/quill.pdf:application/pdf},
}

@misc{fennel2021,
  title = {A Preprint on Imaginary Fennel},
  author = {Fennel, Rosa},
  eprint = {2101.00042},
  archivePrefix = {arXiv},
  file = {PDF:files/2/fennel.pdf:application/pdf},
}

@article{broken, title = {Unclosed
"""


@pytest.fixture
def bib_path(tmp_path: Path) -> Path:
    folder = tmp_path / "export"
    folder.mkdir()
    path = folder / "library.bib"
    path.write_text(BIB)
    return path


@pytest.fixture
def bib_with_pdf(bib_path: Path) -> Path:
    pdf = bib_path.parent / "files" / "2" / "fennel.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 synthetic fennel")
    return bib_path


def only_event(project: Project, type_: str) -> Event:
    [event] = _of_type(project, type_)
    return event


def tracked_files(project: Project) -> list[Path]:
    """Every file a project would commit: all but the git-ignored library and index."""
    root = project.paths.dir
    ignored = (project.paths.library_dir, project.paths.index_path.parent)
    return [
        p for p in root.rglob("*") if p.is_file() and not any(p.is_relative_to(i) for i in ignored)
    ]


def grep_git_tracked(project: Project, needles: list[str]) -> list[tuple[Path, str]]:
    hits = []
    for path in tracked_files(project):
        data = path.read_bytes().decode("utf-8", "replace")
        hits.extend((path, n) for n in needles if n in data)
    return hits


def test_record_import_writes_one_event_and_archives(project: Project, bib_path: Path) -> None:
    s = record_import(project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    ev = only_event(project, "import.recorded")
    payload = ImportRecorded.model_validate(ev.payload)
    assert payload.import_id == s.import_id and ev.refs == (s.import_id,)
    assert project.library.get(payload.file_hash) == bib_path.read_bytes()
    assert payload.counts == {
        ParseOutcome.PARSED: 2,
        ParseOutcome.NO_TITLE_NO_IDENTIFIER: 0,
        ParseOutcome.MALFORMED: 1,
    }
    assert (payload.attachments, payload.attachments_missing) == (2, 2)
    assert s.counts == payload.counts
    assert payload.parser == "bibtexparser" and payload.format is ImportFormat.BIBTEX
    records = import_records(project, s.import_id)
    assert [r.ordinal for r in records] == [1, 2, 3]
    assert records[0].fields is not None
    assert records[0].fields.title == "On the Quiet Growth of Pear Trees"
    assert record_key(s.import_id, 2) == f"{s.import_id}:2"


def test_no_private_text_outside_library(project: Project, bib_with_pdf: Path) -> None:
    record_import(project, bib_with_pdf, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    needles = ["my private note", "personal remark", "/Users/", "annote", "files/2", "fennel.pdf"]
    assert tracked_files(project)
    assert grep_git_tracked(project, needles) == []


def test_reimport_is_deterministic(project: Project, bib_path: Path) -> None:
    first = record_import(project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    second = record_import(project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    assert first.import_id != second.import_id
    a, b = (ImportRecorded.model_validate(e.payload) for e in _of_type(project, "import.recorded"))
    assert a.file_hash == b.file_hash and a.records_blob == b.records_blob


def test_attachment_bytes_in_library(project: Project, bib_with_pdf: Path) -> None:
    s = record_import(project, bib_with_pdf, format=ImportFormat.BIBTEX, role=ImportRole.CORPUS)
    assert (s.attachments, s.attachments_missing) == (2, 1)
    digest = hashlib.sha256(b"%PDF-1.4 synthetic fennel").hexdigest()
    assert project.library.get(f"sha256:{digest}") == b"%PDF-1.4 synthetic fennel"
    assert not project.blobs.exists(f"sha256:{digest}")


def test_pdf_folder_import_archives_manifest(project: Project, tmp_path: Path) -> None:
    folder = tmp_path / "pdfs"
    folder.mkdir()
    (folder / "2101.00042.pdf").write_bytes(b"%PDF-1.4 tiny")
    s = record_import(project, folder, format=ImportFormat.PDFS, role=ImportRole.REFERENCE)
    payload = ImportRecorded.model_validate(only_event(project, "import.recorded").payload)
    assert project.library.exists(payload.file_hash)
    assert project.library.get(f"sha256:{hashlib.sha256(b'%PDF-1.4 tiny').hexdigest()}")
    assert s.attachments == 1 and s.attachments_missing == 0


def test_unreadable_file_writes_nothing(project: Project, tmp_path: Path) -> None:
    before = sorted(p.name for p in tracked_files(project))
    with pytest.raises(FactoryValidationError) as caught:
        record_import(
            project, tmp_path / "absent.bib", format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE
        )
    assert [i.field for i in caught.value.issues] == ["path"]
    binary = tmp_path / "binary.bib"
    binary.write_bytes(b"\x00\x01")
    with pytest.raises(FactoryValidationError) as caught:
        record_import(project, binary, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    assert [i.field for i in caught.value.issues] == ["path"]
    assert sorted(p.name for p in tracked_files(project)) == before
    assert not project.paths.library_dir.exists()
    assert _of_type(project, "import.recorded") == []


def test_actor_is_human(project: Project, bib_path: Path) -> None:
    record_import(project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    assert only_event(project, "import.recorded").actor.kind == "human"


def test_collection_length_validated(project: Project, bib_path: Path) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        record_import(
            project,
            bib_path,
            format=ImportFormat.BIBTEX,
            role=ImportRole.REFERENCE,
            collection="x" * 121,
        )
    assert [i.field for i in caught.value.issues] == ["collection"]
    s = record_import(
        project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, collection="Pears"
    )
    payload = ImportRecorded.model_validate(only_event(project, "import.recorded").payload)
    assert payload.collection == "Pears" and payload.import_id == s.import_id


def test_unknown_import_has_no_records(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        import_records(project, "imp_01ARZ3NDEKTSV4RRFFQ69G5FAV")


def test_export_read_once_archive_matches_parsed_bytes(
    project: Project, bib_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The archived bytes are the parsed bytes, even if the file changes after the read."""
    from factory.imports import registry

    original = bib_path.read_bytes()
    real = registry.parse_bytes

    def mutate_then_parse(format: ImportFormat, data: bytes, base: Path | None):  # type: ignore[no-untyped-def]
        bib_path.write_text("@article{other, title={Changed After Read}}\n")
        return real(format, data, base)

    monkeypatch.setattr("factory.services.imports.parse_bytes", mutate_then_parse)
    s = record_import(project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    payload = ImportRecorded.model_validate(only_event(project, "import.recorded").payload)
    assert project.library.get(payload.file_hash) == original
    titles = [r.fields.title for r in import_records(project, s.import_id) if r.fields]
    assert "Changed After Read" not in titles


def test_pdf_folder_files_read_once(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every PDF is read from disk once; sniffing and metadata read the same bytes."""
    import io

    from factory.imports import pdfs

    folder = tmp_path / "pdfs"
    folder.mkdir()
    (folder / "2101.00042.pdf").write_bytes(b"%PDF-1.4 tiny")
    (folder / "plain.pdf").write_bytes(b"%PDF-1.4 other")
    sources: list[object] = []
    real_reader = pdfs.PdfReader

    def reader(stream: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        sources.append(stream)
        return real_reader(stream, *args, **kwargs)  # type: ignore[arg-type]

    reads: list[Path] = []
    real_read = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        reads.append(self)
        return real_read(self)

    monkeypatch.setattr(pdfs, "PdfReader", reader)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    record_import(project, folder, format=ImportFormat.PDFS, role=ImportRole.REFERENCE)
    pdf_reads = [p for p in reads if p.suffix == ".pdf"]
    assert sorted(p.name for p in pdf_reads) == ["2101.00042.pdf", "plain.pdf"]
    assert sources and all(isinstance(s, io.BytesIO) for s in sources)
