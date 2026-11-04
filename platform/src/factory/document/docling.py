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
CONVERTER_VERSION = "1.1"


_HASH_CACHE: dict[tuple[str, tuple[tuple[str, int, int], ...]], str] = {}


def clear_hash_cache() -> None:
    """Forget cached tree hashes (tests)."""
    _HASH_CACHE.clear()


def _files(root: Path) -> list[Path]:
    """Regular files under `root`, sorted; symlinked files and directories are not followed."""
    found: list[Path] = []
    for here, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(here) / d).is_symlink()]
        found.extend(p for n in names if not (p := Path(here) / n).is_symlink() and p.is_file())
    return sorted(found)


def _cached_tree_hash(root: Path) -> str:
    """`tree_hash`, cached per process by (resolved path, sorted (relpath, size, mtime_ns))."""
    resolved = root.resolve()
    signature = tuple(
        (p.relative_to(resolved).as_posix(), (st := p.stat()).st_size, st.st_mtime_ns)
        for p in _files(resolved)
    )
    key = (str(resolved), signature)
    if key not in _HASH_CACHE:
        _HASH_CACHE[key] = tree_hash(resolved)
    return _HASH_CACHE[key]


def tree_hash(root: Path) -> str:
    """sha256 over the sorted (relative path, file sha256) pairs of every file under `root`.

    Symlinks are not followed.
    """
    digest = hashlib.sha256()
    for path in _files(root):
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
        # 16 hex digits (64 bits) identify the weights; this is a label, not an integrity proof.
        weights = _cached_tree_hash(models)[:16]
        return f"{CONVERTER_VERSION}+docling {library} weights sha256:{weights}"

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
        previous = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            if self._converter is None:
                self._converter = self._build(models)
            base = importlib.import_module("docling.datamodel.base_models")
            stream = base.DocumentStream(name="doc.pdf", stream=io.BytesIO(raw))
            result = self._converter.convert(stream)
        finally:
            if previous is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous
        text = str(result.document.export_to_markdown(page_break_placeholder="\f"))
        return text, (f"docling status: {result.status.value}",)
