"""CSL JSON import parser (slice 3d, plan Import-A task 2). Every item is made up."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from factory.canonical import canonical_json
from factory.imports.csl import parse_csl
from factory.imports.model import ImportFormat, ImportFormatError, ParseOutcome

ZOTERO_ITEM: dict[str, Any] = {
    "id": "http://zotero.org/users/1/items/ABCD",
    "type": "article-journal",
    "title": "Imaginary Orchards at Dusk",
    "author": [{"family": "Quill", "given": "Ada"}, {"literal": "Orchard Consortium"}],
    "issued": {"date-parts": [[2019, 4]]},
    "DOI": "https://doi.org/10.9999/ORCHARD.7",
    "URL": "https://example.org/orchards",
    "container-title": "Journal of Imaginary Orchards",
    "abstract": "A made-up abstract.",
    "keyword": "pears; orchards",
    "note": "my private note",
}


def parse(items: Any, base: Path | None = None) -> Any:
    return parse_csl(json.dumps(items).encode(), base)


def test_csl_zotero_export_fields() -> None:
    parsed = parse([ZOTERO_ITEM])
    assert parsed.format is ImportFormat.CSL
    [r] = parsed.records
    assert r.outcome is ParseOutcome.PARSED and r.ordinal == 1
    f = r.fields
    assert f is not None
    assert f.title == "Imaginary Orchards at Dusk"
    assert f.authors == ["Quill, Ada", "Orchard Consortium"]
    assert (f.year, f.doi, f.url, f.venue, f.type) == (
        2019,
        "10.9999/orchard.7",
        "https://example.org/orchards",
        "Journal of Imaginary Orchards",
        "article",
    )
    assert f.abstract == "A made-up abstract." and f.tags == ["pears", "orchards"]
    assert r.record_sha256 == hashlib.sha256(canonical_json(ZOTERO_ITEM)).hexdigest()
    assert "private" not in r.model_dump_json()


def test_csl_arxiv_preprint() -> None:
    by_number = {"type": "article", "title": "T", "publisher": "arXiv", "number": "2101.00042"}
    by_url = {"type": "manuscript", "title": "T", "URL": "http://arxiv.org/abs/2101.00042v3"}
    by_doi = {"type": "article", "title": "T", "DOI": "10.48550/arXiv.2101.00042"}
    parsed = parse([by_number, by_url, by_doi])
    assert [r.fields.arxiv for r in parsed.records if r.fields] == ["2101.00042"] * 3
    assert [r.fields.type for r in parsed.records if r.fields] == ["preprint"] * 3


def test_csl_malformed_and_unidentified_items() -> None:
    parsed = parse([{"type": "book", "issued": {"raw": "2001"}}, "not an item", {"title": 7}])
    outcomes = [r.outcome for r in parsed.records]
    assert outcomes == [
        ParseOutcome.NO_TITLE_NO_IDENTIFIER,
        ParseOutcome.MALFORMED,
        ParseOutcome.MALFORMED,
    ]
    assert parsed.records[0].fields is not None and parsed.records[0].fields.year == 2001


def test_csl_attachment(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 csl")
    item = {"title": "T", "attachments": [{"path": "a.pdf", "mimeType": "application/pdf"}]}
    parsed = parse([item], tmp_path)
    [r] = parsed.records
    digest = hashlib.sha256(b"%PDF-1.4 csl").hexdigest()
    assert r.attachment is not None and r.attachment.content_sha256 == digest
    assert parsed.attachment_bytes == {digest: b"%PDF-1.4 csl"}


def test_csl_not_json_raises() -> None:
    with pytest.raises(ImportFormatError):
        parse_csl(b"@article{k, title={T}}", None)
    with pytest.raises(ImportFormatError):
        parse_csl(b'{"title": "not a list"}', None)
