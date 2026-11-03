"""Docling candidate (MIT): layout + TableFormer, OCR disabled, pages joined with form feeds."""

from __future__ import annotations

import io
from importlib import metadata

from factory.document.converter import ConverterUnavailable

from adapters._common import DOCLING_MODELS, PDF, tree_hash


class DoclingConverter:
    name = "docling"
    accepts = frozenset({PDF})

    def __init__(self) -> None:
        self._converter = None

    def version(self) -> str:
        if not DOCLING_MODELS.exists():
            raise ConverterUnavailable(f"docling models missing at {DOCLING_MODELS}")
        weights = tree_hash(DOCLING_MODELS)[:16]
        return f"docling {metadata.version('docling')} weights sha256:{weights}"

    def prepare(self) -> None:
        """Build the converter and load its models, so timing excludes the one-off load."""
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions(artifacts_path=str(DOCLING_MODELS), do_ocr=False)
        self._converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        self._converter.initialize_pipeline(InputFormat.PDF)

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        from docling.datamodel.base_models import DocumentStream

        if self._converter is None:
            self.prepare()
        assert self._converter is not None
        result = self._converter.convert(DocumentStream(name="doc.pdf", stream=io.BytesIO(raw)))
        text = result.document.export_to_markdown(page_break_placeholder="\f")
        return text, (f"docling status: {result.status.value}",)
