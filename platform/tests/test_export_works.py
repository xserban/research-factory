"""`export_works` (IDEA-87): the converted Markdown of chosen works as files for a notebook tool,
each with a traceability header, an exact manifest, skipped works with reasons, held-out works
withheld, and caps. Read-only: no event is written."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from factory.document.registry import ConverterRegistry
from factory.errors import FactoryValidationError
from factory.model.fulltext import AttemptOutcome, Route
from factory.services import export_works as ew
from factory.services import withholding, work_layers
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from factory.services.fulltext import fetch_fulltext
from factory.sources.fulltext.base import not_retrieved
from tests.document_helpers import fetched_document
from tests.route_helpers import StubRoute, always, retrieved
from tests.test_document_read import MD, _promoted


class _Both:
    name = "passthrough"
    accepts = frozenset({"text/html", "application/pdf"})

    def version(self) -> str:
        return "1.0"

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        return raw.decode("utf-8"), ()


def _convert(project: Project) -> None:
    convert_documents(project, ConverterRegistry([_Both()]))


def _fetch_pdf(project: Project, work_id: str, content: bytes) -> None:
    routes = {
        Route.OA_PDF: StubRoute(
            Route.OA_PDF,
            always(retrieved(Route.OA_PDF, content, media_type="application/pdf")),
        ),
        Route.ARXIV_HTML: StubRoute(
            Route.ARXIV_HTML, always(not_retrieved(Route.ARXIV_HTML, AttemptOutcome.FAILED, "x"))
        ),
        Route.ARXIV_SOURCE: StubRoute(
            Route.ARXIV_SOURCE,
            always(not_retrieved(Route.ARXIV_SOURCE, AttemptOutcome.NOT_AVAILABLE, "x")),
        ),
    }
    fetch_fulltext(project, routes=routes, work_ids=[work_id])


def _event_files(project: Project) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in sorted(project.paths.events_dir.rglob("*")) if p.is_file()}


@pytest.fixture
def two(project: Project, corpus: None) -> tuple[str, str]:
    """Two promoted works: the first converted from HTML, the second left unconverted."""
    works = _promoted(project)
    fetched_document(project, works[0], MD)
    _convert(project)
    return works[0], works[1]


def _manifest(out: Path) -> dict[str, Any]:
    loaded = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_exports_markdown_with_a_header_and_lists_the_skipped_work(
    project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    done, unconverted = two
    before = _event_files(project)
    out = tmp_path / "out"
    summary = ew.export_works(project, ew.Selection((done, unconverted), "ids"), out)
    assert summary.exported == 1 and summary.skipped == 1
    manifest = _manifest(out)
    [entry] = manifest["works"]
    assert entry["work_id"] == done
    body = (out / entry["file"]).read_text(encoding="utf-8")
    assert body.startswith("---\n")
    head, _, rest = body[4:].partition("\n---\n")
    for key in ("work_id", "title", "authors", "year", "doi", "conversion_id", "markdown_hash"):
        assert f"{key}:" in head
    assert f'work_id: "{done}"' in head
    assert entry["conversion_id"] in head and entry["markdown_hash"] in head
    assert "layer:" in head
    assert "Opening sentence of the study." in rest
    assert hashlib.sha256(body.encode()).hexdigest() == entry["file_sha256"]
    [skip] = manifest["skipped"]
    assert skip["work_id"] == unconverted and "no converted document" in skip["reason"]
    assert _event_files(project) == before  # read-only: no event


def test_manifest_states_selection_date_project_and_the_caveat(
    project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    ew.export_works(project, ew.Selection((two[0],), "layer core"), out, now="2026-11-17T10:00:00Z")
    manifest = _manifest(out)
    assert manifest["project"] == project.paths.slug
    assert manifest["selection"] == "layer core"
    assert manifest["exported_at"] == "2026-11-17T10:00:00Z"
    text = (out / "MANIFEST.md").read_text(encoding="utf-8")
    assert "not records" in text and "that tool's copy" in text
    assert two[0] in text and "layer core" in text


def test_filenames_are_safe_and_carry_the_work_id(
    project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    ew.export_works(project, ew.Selection((two[0],), "ids"), out)
    [entry] = _manifest(out)["works"]
    name = Path(entry["file"]).name
    assert name.endswith(".md") and "/" not in name and ":" not in name and " " not in name
    assert ew.slug_of_id(two[0]) in name


def test_pdfs_are_off_by_default_and_reported_missing_when_asked(
    project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    done = two[0]
    off = tmp_path / "off"
    ew.export_works(project, ew.Selection((done,), "ids"), off)
    assert not (off / "pdf").exists()
    assert _manifest(off)["pdfs"] == "not requested"
    on = tmp_path / "on"
    ew.export_works(project, ew.Selection((done,), "ids"), on, pdfs=True)
    manifest = _manifest(on)
    assert manifest["works"][0]["pdf"] is None
    assert manifest["works_without_pdf"] == [done]
    assert "no PDF" in (on / "MANIFEST.md").read_text(encoding="utf-8")


def test_a_stored_pdf_is_copied_when_asked(
    project: Project, corpus: None, tmp_path: Path
) -> None:
    work = _promoted(project)[0]
    pdf = b"%PDF-1.4 fake\n"
    _fetch_pdf(project, work, MD)  # converted text is the bytes; the original is the "PDF"
    _convert(project)
    out = tmp_path / "out"
    ew.export_works(project, ew.Selection((work,), "ids"), out, pdfs=True)
    [entry] = _manifest(out)["works"]
    assert entry["pdf"] is not None
    assert (out / entry["pdf"]["file"]).read_bytes() == MD
    assert entry["pdf"]["sha256"] == hashlib.sha256(MD).hexdigest()
    assert pdf  # the fixture bytes are not special


def test_a_held_out_work_is_skipped_as_withheld_and_never_named(
    project: Project, two: tuple[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    done = two[0]
    monkeypatch.setattr(withholding, "held_out_tokens", lambda p, include_work_ids=True: {done})
    out = tmp_path / "out"
    summary = ew.export_works(project, ew.Selection((done,), "ids"), out)
    assert summary.exported == 0 and summary.withheld == 1
    manifest = _manifest(out)
    assert manifest["works"] == [] and manifest["withheld"] == 1
    assert done not in json.dumps(manifest)
    assert done not in (out / "MANIFEST.md").read_text(encoding="utf-8")
    assert not list((out / "markdown").glob("*"))


def test_the_layer_selection_takes_the_works_of_that_layer(
    project: Project, two: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = work_layers.WorkLayer(layer="core", source="moved", scheme_version=1, miner_layer=None)
    monkeypatch.setattr(work_layers, "layers_of", lambda p: {two[0]: layer})
    selection = ew.select_by_layer(project, "core")
    assert selection.ids == (two[0],) and selection.how == "layer core"
    assert ew.select_by_layer(project, "applied").ids == ()


def test_unknown_ids_are_listed_as_skipped(project: Project, two: tuple[str, str], tmp_path: Path) -> None:
    out = tmp_path / "out"
    ew.export_works(project, ew.Selection((two[0], "rf:nonexistent"), "ids"), out)
    reasons = {s["work_id"]: s["reason"] for s in _manifest(out)["skipped"]}
    assert "unknown work" in reasons["rf:nonexistent"]


def test_selection_over_the_work_cap_is_refused_and_writes_nothing(
    project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    with pytest.raises(FactoryValidationError) as err:
        ew.export_works(project, ew.Selection(two, "ids"), out, max_works=1)
    assert "selection" in str(err.value.issues[0].field)
    assert not out.exists()


def test_total_bytes_over_the_cap_is_refused_and_leaves_nothing(
    project: Project, two: tuple[str, str], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    with pytest.raises(FactoryValidationError) as err:
        ew.export_works(project, ew.Selection((two[0],), "ids"), out, max_bytes=10)
    assert "bytes" in err.value.issues[0].reason
    assert not out.exists() and not list(tmp_path.glob(".export-*"))


def test_an_empty_selection_is_refused(project: Project, tmp_path: Path) -> None:
    with pytest.raises(FactoryValidationError):
        ew.export_works(project, ew.Selection((), "ids"), tmp_path / "out")


def test_an_existing_output_is_refused(project: Project, two: tuple[str, str], tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "x").write_text("keep")
    with pytest.raises(FactoryValidationError):
        ew.export_works(project, ew.Selection((two[0],), "ids"), out)
    assert (out / "x").read_text() == "keep"


def test_a_zip_output_holds_the_same_files(project: Project, two: tuple[str, str], tmp_path: Path) -> None:
    out = tmp_path / "papers.zip"
    ew.export_works(project, ew.Selection((two[0],), "ids"), out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "MANIFEST.md" in names and "manifest.json" in names
    assert any(n.startswith("markdown/") and n.endswith(".md") for n in names)


def test_ids_from_a_file_skip_blank_lines_and_comments(tmp_path: Path) -> None:
    f = tmp_path / "ids.txt"
    f.write_text("# a comment\nrf:a\n\n rf:b \nrf:a\n", encoding="utf-8")
    assert ew.read_ids_file(f) == ("rf:a", "rf:b")
