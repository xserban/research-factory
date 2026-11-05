"""PyMuPDF4LLM converter: PDF to Markdown, pages joined with form feeds.

Licence: PyMuPDF and PyMuPDF4LLM are AGPL-3.0; they are an optional extra (`pymupdf`), imported
lazily, never a core dependency. Not chosen by decision 49 (Docling is the PDF converter), so
not in `default_converters`; reachable through `document convert --converter pymupdf4llm`.

Warnings carry no document text. Deterministic for fixed library versions and input bytes.
"""

import importlib
from importlib import metadata
from typing import Any

from factory.document.converter import ConverterUnavailable

PDF = "application/pdf"
CONVERTER_VERSION = "1.1"


def _dist_version(dist: str) -> str:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError as exc:
        raise ConverterUnavailable(
            f"{dist} is not installed (install the 'pymupdf' extra)"
        ) from exc


class PyMuPdf4LlmConverter:
    """PyMuPDF4LLM, imported lazily. `version` raises `ConverterUnavailable` when absent."""

    name = "pymupdf4llm"
    accepts = frozenset({PDF})

    def version(self) -> str:
        return (
            f"{CONVERTER_VERSION}+pymupdf4llm {_dist_version('pymupdf4llm')} "
            f"pymupdf {_dist_version('pymupdf')}"
        )

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.version()
        pymupdf: Any = importlib.import_module("pymupdf")
        pymupdf4llm: Any = importlib.import_module("pymupdf4llm")
        doc = pymupdf.open(stream=raw, filetype="pdf")
        try:
            chunks = pymupdf4llm.to_markdown(doc, page_chunks=True)
        finally:
            doc.close()
        return "\f".join(str(chunk["text"]) for chunk in chunks), ()
