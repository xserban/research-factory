"""The converter registry: which converter handles a media type.

A registry is an ordered list of converters. `for_media_type` returns the first one that accepts a
media type, so a more specific converter registered earlier takes precedence. A media type that no
converter accepts gives None; the conversion service records that as `no-converter`.

Invariants:
- The registry is read-only after construction and never calls a converter.
- `default_converters` lists only converters whose tools are part of the platform.
"""

from collections.abc import Sequence

from factory.document.converter import Converter
from factory.document.latexml_html import LatexmlHtmlConverter


class ConverterRegistry:
    """Converters in priority order, looked up by media type."""

    def __init__(self, converters: Sequence[Converter]) -> None:
        self._converters = tuple(converters)

    def for_media_type(self, media_type: str) -> Converter | None:
        """The first registered converter that accepts `media_type`, or None if there is none."""
        return next((c for c in self._converters if media_type in c.accepts), None)


def default_converters() -> ConverterRegistry:
    """The converters shipped with the platform. Only LaTeXML HTML until later tasks add more."""
    return ConverterRegistry([LatexmlHtmlConverter()])
