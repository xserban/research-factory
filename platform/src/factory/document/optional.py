"""Optional converters: pandoc, Docling, PyMuPDF4LLM.

NOT ACTIVE until decision 49 chooses a converter per format. None of these is in
`default_converters`; `available_converters` only reports which of them could run on this
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
