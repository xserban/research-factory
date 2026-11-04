"""BibTeX import parser (slice 3d, plan Import-A task 1).

Every title, author and identifier here is made up; no fixture holds literature text.
"""

import hashlib
from pathlib import Path

import pytest

from factory.imports.bibtex import PARSER, PARSER_VERSION, parse_bibtex
from factory.imports.model import ImportFormat, ImportFormatError, ImportRecord, ParseOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "imports" / "zotero.bib"


def one(entry: str, base: Path | None = None) -> ImportRecord:
    parsed = parse_bibtex(entry.encode(), base)
    [record] = parsed.records
    return record


def fields(entry: str) -> ImportRecord:
    record = one(entry)
    assert record.fields is not None
    return record


def kind(entry: str) -> str:
    r = fields(entry)
    assert r.fields is not None
    return r.fields.type


def test_latex_accents_and_braces() -> None:
    r = fields(
        '@article{k, title={{\\"U}ber {BERT}}, author={M{\\"u}ller, A. and Li, B.}, year=2021}'
    )
    assert r.fields is not None
    assert r.fields.title == "Über BERT"
    assert r.fields.authors == ["Müller, A.", "Li, B."]
    assert r.fields.year == 2021
    assert r.outcome is ParseOutcome.PARSED
    assert r.ordinal == 1


def test_string_macros_and_concatenation() -> None:
    r = fields('@string{j = "J. ML"}\n@article{k, title={T}, journal = j # " Res.", year=2020}')
    assert r.fields is not None
    assert r.fields.venue == "J. ML Res."


def test_arxiv_from_eprint_and_journal_and_datacite() -> None:
    forms = [
        "@misc{a, title={T}, eprint={2101.00042v2}, archivePrefix={ArXiv}}",
        "@article{b, title={T}, journal={arXiv preprint arXiv:2101.00042}}",
        "@misc{c, title={T}, doi={10.48550/arXiv.2101.00042}}",
    ]
    ids = []
    for form in forms:
        r = fields(form)
        assert r.fields is not None
        ids.append(r.fields.arxiv)
    assert ids == ["2101.00042"] * 3


def test_eprint_without_arxiv_prefix_is_not_arxiv() -> None:
    r = fields("@misc{a, title={T}, eprint={12345}, archivePrefix={other}}")
    assert r.fields is not None
    assert r.fields.arxiv is None


def test_doi_normalised() -> None:
    r = fields("@article{k, title={T}, doi={https://doi.org/10.1000/ABC}}")
    assert r.fields is not None
    assert r.fields.doi == "10.1000/abc"


def test_keywords_become_tags() -> None:
    r = fields("@article{k, title={T}, keywords={vision, linear attention}}")
    assert r.fields is not None
    assert r.fields.tags == ["vision", "linear attention"]


def test_types_url_and_year() -> None:
    r = fields(
        "@inproceedings{k, title={T}, booktitle={Proc. Nowhere}, year={c. 2018},"
        " url={https://example.org/t}}"
    )
    assert r.fields is not None
    assert (r.fields.type, r.fields.venue, r.fields.year, r.fields.url) == (
        "inproceedings",
        "Proc. Nowhere",
        2018,
        "https://example.org/t",
    )
    assert kind("@phdthesis{k, title={T}}") == "thesis"
    assert kind("@techreport{k, title={T}}") == "report"
    assert kind("@misc{k, title={T}, eprint={2101.00042}, archiveprefix={arXiv}}") == "preprint"
    assert kind("@misc{k, title={T}}") == "other"


def test_abstract_and_authors_truncated() -> None:
    authors = " and ".join(f"Person{i}, A." for i in range(60))
    abstract = "x" * 6000
    r = fields(f"@article{{k, title={{T}}, author={{{authors}}}, abstract={{{abstract}}}}}")
    assert r.fields is not None
    assert len(r.fields.authors) == 50
    assert r.fields.abstract is not None and len(r.fields.abstract) == 5000
    assert set(r.flags) == {"abstract-truncated", "authors-truncated"}


def test_and_others_flags_authors() -> None:
    r = fields("@article{k, title={T}, author={Quill, Ada and others}}")
    assert r.fields is not None
    assert r.fields.authors == ["Quill, Ada"]
    assert r.flags == ("authors-truncated",)


def test_zotero_file_field(tmp_path: Path) -> None:
    pdf = tmp_path / "files" / "1" / "doc.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    entry = (
        "@article{k, title={T}, file={Snapshot:files/1/page.html:text/html;"
        "Full Text PDF:files/1/doc.pdf:application/pdf}}"
    )
    parsed = parse_bibtex(entry.encode(), tmp_path)
    [r] = parsed.records
    digest = hashlib.sha256(b"%PDF-1.4 synthetic").hexdigest()
    assert r.attachment is not None
    assert r.attachment.path_sha256 == hashlib.sha256(b"files/1/doc.pdf").hexdigest()
    assert r.attachment.content_sha256 == digest
    assert parsed.attachment_bytes == {digest: b"%PDF-1.4 synthetic"}
    assert "files/1" not in r.model_dump_json()


def test_missing_attachment_file(tmp_path: Path) -> None:
    r = one("@article{k, title={T}, file={PDF:files/9/none.pdf:application/pdf}}", tmp_path)
    assert r.attachment is not None
    assert r.attachment.content_sha256 is None
    no_base = one("@article{k, title={T}, file={PDF:files/9/none.pdf:application/pdf}}")
    assert no_base.attachment is not None and no_base.attachment.content_sha256 is None


def test_no_pdf_in_file_field_means_no_attachment() -> None:
    r = one("@article{k, title={T}, file={Snapshot:files/1/page.html:text/html}}")
    assert r.attachment is None


def test_no_title_no_identifier_kept() -> None:
    r = one("@inproceedings{k, year={2020}, booktitle={Proc. Nowhere}}")
    assert r.outcome is ParseOutcome.NO_TITLE_NO_IDENTIFIER
    assert r.fields is not None
    assert r.fields.venue == "Proc. Nowhere"


def test_malformed_entry_counted_not_fatal() -> None:
    parsed = parse_bibtex(b"@article{a, title={Fine}}\n@article{b, title = {Unclosed\n", None)
    assert [r.outcome for r in parsed.records] == [ParseOutcome.PARSED, ParseOutcome.MALFORMED]
    bad = parsed.records[1]
    assert bad.fields is None and bad.attachment is None and bad.ordinal == 2
    assert len(bad.record_sha256) == 64


def test_not_bibtex_raises() -> None:
    with pytest.raises(ImportFormatError):
        parse_bibtex(b"\x00\x01", None)
    with pytest.raises(ImportFormatError):
        parse_bibtex(b"\xff\xfe not utf-8", None)


def test_record_hash_stable_under_field_order() -> None:
    a = one("@article{k, title={T}, year={2020}, doi={10.1/x}}")
    b = one("@article{k,\n  doi = {10.1/x},\n  year = 2020,\n  title = {T}\n}")
    c = one("@article{k, title={T}, year={2021}, doi={10.1/x}}")
    assert a.record_sha256 == b.record_sha256 != c.record_sha256


def test_annote_not_in_fields() -> None:
    r = one("@article{k, title={T}, annote={my private note}, note={another note}}")
    dumped = r.model_dump_json()
    assert "annote" not in dumped and "private" not in dumped and "another" not in dumped


def test_fixture_parses_in_file_order(tmp_path: Path) -> None:
    pdf = tmp_path / "files" / "1" / "quill2019.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 pear")
    parsed = parse_bibtex(FIXTURE.read_bytes(), tmp_path)
    assert parsed.format is ImportFormat.BIBTEX
    assert (parsed.parser, parsed.parser_version) == (PARSER, PARSER_VERSION)
    assert PARSER_VERSION.endswith("+rf1")
    assert [(r.ordinal, r.outcome) for r in parsed.records] == [
        (1, ParseOutcome.PARSED),
        (2, ParseOutcome.PARSED),
        (3, ParseOutcome.NO_TITLE_NO_IDENTIFIER),
        (4, ParseOutcome.MALFORMED),
    ]
    first, second = parsed.records[0].fields, parsed.records[1].fields
    assert first is not None and second is not None
    assert first.venue == "Journal of Imaginary Orchards Letters"
    assert first.title == "On the Quiet Growth of Pear Trees"
    assert first.tags == ["pears", "orchards"]
    assert second.arxiv == "2101.00042" and second.type == "preprint"
    assert parsed.records[0].attachment is not None
    assert parsed.records[0].attachment.content_sha256 is not None
    assert parsed.records[1].attachment is not None
    assert parsed.records[1].attachment.content_sha256 is None
