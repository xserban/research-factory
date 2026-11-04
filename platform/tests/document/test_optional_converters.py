"""Optional converters: ConverterUnavailable with the tool absent (always on), and the contract
kit when the tool or library is present (skipped otherwise). Not registered by default."""

import gzip
import io
import shutil
import tarfile
from importlib import metadata
from pathlib import Path

import pytest

from factory.document import docling as docling_module
from factory.document import pandoc as pandoc_module
from factory.document.converter import ConverterUnavailable, convert
from factory.document.docling import DoclingConverter
from factory.document.optional import available_converters
from factory.document.pandoc import PandocConverter
from factory.document.pymupdf4llm import PyMuPdf4LlmConverter
from factory.document.registry import default_converters
from tests.document.kit import assert_converter_contract

HTML_SAMPLE = (
    b"<html><body><h1>1 Intro</h1><p>Some text &amp; more.</p>"
    b"<h2>1.1 Detail</h2><p>Other text.</p>"
    b"<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>"
)
LATEX_SAMPLE = (
    b"\\documentclass{article}\\begin{document}\\section{Intro}Hello world.\n\n"
    b"\\subsection{Detail}More text.\\end{document}\n"
)


def _eprint(tex: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("paper.tex")
        info.size = len(tex)
        archive.addfile(info, io.BytesIO(tex))
    return gzip.compress(buffer.getvalue(), mtime=0)


# --- absent tools (always on) -------------------------------------------------------------


def test_pandoc_absent_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FACTORY_PANDOC", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(ConverterUnavailable, match="pandoc"):
        PandocConverter().version()
    with pytest.raises(ConverterUnavailable):
        convert(PandocConverter(), b"<p>x</p>", "text/html")


def test_pandoc_env_var_to_missing_file_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FACTORY_PANDOC", str(tmp_path / "nope"))
    with pytest.raises(ConverterUnavailable):
        PandocConverter().version()


def test_pandoc_unrunnable_binary_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "pandoc"
    fake.write_text("not executable")
    monkeypatch.setenv("FACTORY_PANDOC", str(fake))
    with pytest.raises(ConverterUnavailable):
        PandocConverter().version()


def test_pymupdf_absent_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:

    def missing(_dist: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", missing)
    with pytest.raises(ConverterUnavailable, match="pymupdf"):
        PyMuPdf4LlmConverter().version()


def test_docling_absent_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_dist: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", missing)
    with pytest.raises(ConverterUnavailable, match="docling"):
        DoclingConverter().version()


def test_docling_without_models_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "version", lambda _dist: "2.0")
    monkeypatch.delenv("FACTORY_DOCLING_MODELS", raising=False)
    with pytest.raises(ConverterUnavailable, match="models"):
        DoclingConverter().version()


def test_docling_version_includes_weights_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "w.bin").write_bytes(b"weights")
    monkeypatch.setattr(metadata, "version", lambda _dist: "2.0")
    monkeypatch.setenv("FACTORY_DOCLING_MODELS", str(tmp_path))
    first = DoclingConverter().version()
    assert "docling 2.0 weights sha256:" in first
    (tmp_path / "w.bin").write_bytes(b"other")
    assert DoclingConverter().version() != first


def test_available_converters_skips_absent_and_default_stays_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FACTORY_PANDOC", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        metadata,
        "version",
        lambda _d: (_ for _ in ()).throw(metadata.PackageNotFoundError()),
    )
    registry = available_converters()
    assert registry.for_media_type("text/html") is None
    assert registry.for_media_type("application/x-eprint-tar") is None
    default = default_converters()
    for media_type in ("application/pdf", "application/x-eprint-tar"):
        assert default.for_media_type(media_type) is None


def test_available_converters_lists_present_pandoc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "pandoc"
    fake.write_text("#!/bin/sh\necho 'pandoc 9.9'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("FACTORY_PANDOC", str(fake))
    found = available_converters().for_media_type("application/x-eprint-tar")
    assert found is not None
    assert found.name == "pandoc"
    assert found.version() == "1.0+pandoc 9.9"


def test_pandoc_eprint_without_main_tex_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "pandoc"
    fake.write_text("#!/bin/sh\necho 'pandoc 9.9'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("FACTORY_PANDOC", str(fake))
    with pytest.raises(ValueError, match="document class"):
        PandocConverter().to_markdown(_eprint(b"no class here"), "application/x-eprint-tar")


# --- contract tests (skipped when the tool is absent) --------------------------------------


def test_pandoc_contract() -> None:
    if pandoc_module.pandoc_path() is None:
        pytest.skip("pandoc not installed")
    assert_converter_contract(
        PandocConverter(),
        [
            (HTML_SAMPLE, "text/html"),
            (_eprint(LATEX_SAMPLE), "application/x-eprint-tar"),
            (gzip.compress(LATEX_SAMPLE, mtime=0), "application/x-eprint"),
        ],
    )


def _sample_pdf() -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "1 Introduction", fontsize=18)
    page.insert_text((72, 120), "Some body text of the paper.", fontsize=11)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def test_pymupdf4llm_contract() -> None:
    pytest.importorskip("pymupdf4llm")
    assert_converter_contract(PyMuPdf4LlmConverter(), [(_sample_pdf(), "application/pdf")])


def test_docling_contract() -> None:
    pytest.importorskip("docling")
    pytest.importorskip("pymupdf")
    if docling_module.models_dir() is None:
        pytest.skip("FACTORY_DOCLING_MODELS not set")
    assert_converter_contract(DoclingConverter(), [(_sample_pdf(), "application/pdf")])
