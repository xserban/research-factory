"""The converter registry: which converter handles a media type.

A registry is an ordered list of converters. `for_media_type` returns the first one that accepts a
media type, so a more specific converter registered earlier takes precedence. A media type that no
converter accepts gives None; the conversion service records that as `no-converter`.

Invariants:
- The registry is read-only after construction and never calls a converter.
- `default_converters` holds the choice of decision 49, one converter per format. A listed
  converter whose tool is absent is not skipped: its `version` raises, and the conversion service
  records `converter-unavailable`, so a missing extra never falls through to another converter.
"""

from collections.abc import Sequence

from factory.document.converter import Converter
from factory.document.docling import DoclingConverter
from factory.document.html_generic import HtmlGenericConverter
from factory.document.latexml_html import LatexmlHtmlConverter
from factory.document.pandoc import PandocConverter


class ConverterRegistry:
    """Converters in priority order, looked up by media type."""

    def __init__(self, converters: Sequence[Converter]) -> None:
        self._converters = tuple(converters)

    def for_media_type(self, media_type: str) -> Converter | None:
        """The first registered converter that accepts `media_type`, or None if there is none."""
        return next((c for c in self._converters if media_type in c.accepts), None)

    def named(self, name: str, media_type: str) -> Converter | None:
        """The registered converter of this name, if it accepts `media_type`."""
        return next(
            (c for c in self._converters if c.name == name and media_type in c.accepts), None
        )

    def names(self) -> frozenset[str]:
        """The names of the registered converters."""
        return frozenset(c.name for c in self._converters)

    def preferring(self, converter: Converter) -> "ConverterRegistry":
        """This registry with `converter` first; one of the same name is replaced."""
        rest = [c for c in self._converters if c.name != converter.name]
        return ConverterRegistry([converter, *rest])


def default_converters() -> ConverterRegistry:
    """The converters of decision 49: HTML latexml-html, PDF Docling, LaTeX e-prints pandoc,
    PubMed Central JATS pandoc (decision 124, proposed).
    `html-generic` (captured web pages, plan SG) takes its own media type, so it competes with none.

    The order is load-bearing: pandoc also accepts HTML, so latexml-html must come before it.
    PyMuPDF4LLM is not listed; it stays an optional extra reachable only through
    `factory.document.optional`.
    """
    return ConverterRegistry(
        [LatexmlHtmlConverter(), DoclingConverter(), PandocConverter(), HtmlGenericConverter()]
    )
