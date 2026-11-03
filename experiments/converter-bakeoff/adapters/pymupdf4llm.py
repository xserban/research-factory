"""PyMuPDF4LLM candidate (AGPL-3.0 via PyMuPDF): per-page Markdown joined with form feeds."""

from __future__ import annotations

from importlib import metadata

from adapters._common import PDF


class PyMuPdf4LlmConverter:
    name = "pymupdf4llm"
    accepts = frozenset({PDF})

    def version(self) -> str:
        return (
            f"pymupdf4llm {metadata.version('pymupdf4llm')} pymupdf {metadata.version('pymupdf')}"
        )

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        import pymupdf
        import pymupdf4llm

        doc = pymupdf.open(stream=raw, filetype="pdf")
        chunks = pymupdf4llm.to_markdown(doc, page_chunks=True)
        return "\f".join(chunk["text"] for chunk in chunks), ()
