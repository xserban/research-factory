"""Bake-off adapters and the (candidate, format) registry.

Formats: `html` (arXiv LaTeXML HTML), `latex` (arXiv e-print), `pdf`. Each registry value is a
class implementing `factory.document.converter.Converter`.
"""

from __future__ import annotations

from factory.document.converter import Converter
from factory.document.latexml_html import LatexmlHtmlConverter

from adapters._common import EPRINT, HTML, PDF
from adapters.docling import DoclingConverter
from adapters.grobid import GrobidConverter
from adapters.pandoc import PandocConverter
from adapters.pymupdf4llm import PyMuPdf4LlmConverter

REFERENCE = ("latexml-html", "html")

#: (candidate, format) -> converter class
REGISTRY: dict[tuple[str, str], type] = {
    ("latexml-html", "html"): LatexmlHtmlConverter,
    ("pandoc", "html"): PandocConverter,
    ("pandoc", "latex"): PandocConverter,
    ("docling", "pdf"): DoclingConverter,
    ("pymupdf4llm", "pdf"): PyMuPdf4LlmConverter,
    ("grobid", "pdf"): GrobidConverter,
}

#: format -> (raw file name under data/raw/<id>/, media type)
FORMATS: dict[str, tuple[str, str]] = {
    "html": ("html", HTML),
    "latex": ("eprint", EPRINT),
    "pdf": ("pdf", PDF),
}


def make(candidate: str, fmt: str) -> Converter:
    return REGISTRY[(candidate, fmt)]()
