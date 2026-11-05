"""Optional converters: pandoc, Docling, PyMuPDF4LLM.

Decision 49 chose per format; `default_converters` is what conversion uses. This module does not
route anything: `available_converters` only reports which optional converters could run on this
machine, so the researcher can try them. Presence is checked without converting anything.
"""

from factory.document.converter import Converter, ConverterUnavailable
from factory.document.docling import DoclingConverter
from factory.document.pandoc import PandocConverter
from factory.document.pymupdf4llm import PyMuPdf4LlmConverter
from factory.document.registry import ConverterRegistry


def available_converters() -> ConverterRegistry:
    """A registry of the optional converters whose tool, library and models are present."""
    candidates: list[Converter] = [PandocConverter(), DoclingConverter(), PyMuPdf4LlmConverter()]
    present: list[Converter] = []
    for candidate in candidates:
        try:
            candidate.version()
        except ConverterUnavailable:
            continue
        present.append(candidate)
    return ConverterRegistry(present)
