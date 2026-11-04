"""Docling converter (MIT): PDF to Markdown with layout and table models, OCR off.

Docling's layout models are fixed, non-generative weights (decision 40). To keep the platform
offline and the output reproducible, the weights must already be on disk: set
`FACTORY_DOCLING_MODELS` to the model directory; Docling is never allowed to download. The
weights' tree hash is part of the converter version. Docling is an optional extra (`docling`),
imported lazily. Inactive until decision 49: not in `default_converters`.

Pages are joined with form feeds. Warnings carry no document text.
"""

import hashlib
import importlib
import io
import os
from importlib import metadata
from pathlib import Path
from typing import Any

from factory.document.converter import ConverterUnavailable

PDF = "application/pdf"
MODELS_ENV = "FACTORY_DOCLING_MODELS"
CONVERTER_VERSION = "1.0"


def tree_hash(root: Path) -> str:
    """sha256 over the sorted (relative path, file sha256) pairs of every file under `root`."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(chunk)
        digest.update(f"{path.relative_to(root).as_posix()}\0{file_hash.hexdigest()}\n".encode())
    return digest.hexdigest()


def models_dir() -> Path | None:
    """The configured model directory if it exists, else None."""
    configured = os.environ.get(MODELS_ENV)
    if not configured:
        return None
    path = Path(configured)
    return path if path.is_dir() else None


class DoclingConverter:
    """Docling, imported lazily. `version` raises `ConverterUnavailable` when the library or the
    models are absent."""

    name = "docling"
    accepts = frozenset({PDF})

    def __init__(self) -> None:
        self._converter: Any = None

    def version(self) -> str:
        try:
            library = metadata.version("docling")
        except metadata.PackageNotFoundError as exc:
            raise ConverterUnavailable(
                "docling is not installed (install the 'docling' extra)"
            ) from exc
        models = models_dir()
        if models is None:
            raise ConverterUnavailable(f"docling models missing (set {MODELS_ENV})")
        return f"{CONVERTER_VERSION}+docling {library} weights sha256:{tree_hash(models)[:16]}"

    def _build(self, models: Path) -> Any:
        base = importlib.import_module("docling.datamodel.base_models")
        options_mod = importlib.import_module("docling.datamodel.pipeline_options")
        conv_mod = importlib.import_module("docling.document_converter")
        options = options_mod.PdfPipelineOptions(artifacts_path=str(models), do_ocr=False)
        converter = conv_mod.DocumentConverter(
            format_options={
                base.InputFormat.PDF: conv_mod.PdfFormatOption(pipeline_options=options)
            }
        )
        converter.initialize_pipeline(base.InputFormat.PDF)
        return converter

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.version()
        models = models_dir()
        assert models is not None
        if self._converter is None:
            self._converter = self._build(models)
        base = importlib.import_module("docling.datamodel.base_models")
        stream = base.DocumentStream(name="doc.pdf", stream=io.BytesIO(raw))
        result = self._converter.convert(stream)
        text = str(result.document.export_to_markdown(page_break_placeholder="\f"))
        return text, (f"docling status: {result.status.value}",)
