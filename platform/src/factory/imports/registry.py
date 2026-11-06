"""The parser for each import format, by path (one file, or one folder for `pdfs`).

A file format's relative attachment paths are read against the file's own folder.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from factory.imports.bibtex import parse_bibtex
from factory.imports.csl import parse_csl
from factory.imports.model import ImportFormat, ParsedImport
from factory.imports.pdfs import parse_pdf_folder
from factory.imports.ris import parse_ris


def _bibtex(path: Path) -> ParsedImport:
    return parse_bibtex(path.read_bytes(), path.parent)


def _csl(path: Path) -> ParsedImport:
    return parse_csl(path.read_bytes(), path.parent)


def _ris(path: Path) -> ParsedImport:
    return parse_ris(path.read_bytes(), path.parent)


PARSERS: Mapping[ImportFormat, Callable[[Path], ParsedImport]] = MappingProxyType(
    {
        ImportFormat.BIBTEX: _bibtex,
        ImportFormat.CSL: _csl,
        ImportFormat.RIS: _ris,
        ImportFormat.PDFS: parse_pdf_folder,
    }
)


BYTE_PARSERS: Mapping[ImportFormat, Callable[[bytes, Path | None], ParsedImport]] = (
    MappingProxyType(
        {
            ImportFormat.BIBTEX: parse_bibtex,
            ImportFormat.CSL: parse_csl,
            ImportFormat.RIS: parse_ris,
        }
    )
)


def parse(format: ImportFormat, path: Path) -> ParsedImport:
    """Parse `path` as `format`. Raises `ImportFormatError`, or `OSError` if unreadable."""
    return PARSERS[format](path)


def parse_bytes(format: ImportFormat, data: bytes, base: Path | None) -> ParsedImport:
    """Parse an export already read into memory, so the caller can archive the same bytes.

    Only single-file formats have a byte form; a PDF folder raises `ValueError`.
    """
    if format not in BYTE_PARSERS:
        raise ValueError(f"{format.value} has no single-file form")
    return BYTE_PARSERS[format](data, base)
