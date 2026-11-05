"""What can convert on this machine, and the researcher's explicit choice of a converter.

Decision 49 chose per format; `default_converters` is what conversion uses. This module routes
nothing on its own: `available_converters` and `converter_infos` report what could run, and
`override_registry` is the registry of one command that names a converter (`document convert
--converter NAME`). Presence is checked without converting anything.

Invariants:
- A named converter that is unknown or cannot run is refused before anything is read or written.
  The refusal names the remedy. This is an explicit request failing; decision 49's rule that a
  missing default tool never falls through to another converter is untouched.
- `override_registry` puts the named converter first and keeps the default for every other media
  type, so naming a PDF converter changes nothing for HTML.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from factory.document.converter import Converter, ConverterUnavailable
from factory.document.docling import DoclingConverter
from factory.document.latexml_html import LatexmlHtmlConverter
from factory.document.pandoc import PandocConverter
from factory.document.pymupdf4llm import PyMuPdf4LlmConverter
from factory.document.registry import ConverterRegistry, default_converters
from factory.errors import FactoryValidationError, ValidationIssue

CONVERTERS: Mapping[str, Callable[[], Converter]] = {
    "latexml-html": LatexmlHtmlConverter,
    "docling": DoclingConverter,
    "pandoc": PandocConverter,
    "pymupdf4llm": PyMuPdf4LlmConverter,
}
"""Every converter a command may name, in listing order."""

_LICENCES: Mapping[str, str] = {
    "latexml-html": "this repository",
    "docling": "MIT",
    "pandoc": "GPL, external tool",
    "pymupdf4llm": "AGPL-3.0",
}


@dataclass(frozen=True)
class ConverterInfo:
    """One converter on this machine. `default` says that decision 49 chose it for a format;
    `reason` is why it cannot run, and `version` is None then."""

    name: str
    accepts: tuple[str, ...]
    available: bool
    version: str | None
    reason: str | None
    licence: str
    default: bool


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


def converter_infos() -> list[ConverterInfo]:
    """Every known converter and whether it can run here. Nothing is converted."""
    defaults = default_converters().names()
    infos: list[ConverterInfo] = []
    for name, build in CONVERTERS.items():
        converter = build()
        version: str | None = None
        reason: str | None = None
        try:
            version = converter.version()
        except ConverterUnavailable as exc:
            reason = str(exc)
        infos.append(
            ConverterInfo(
                name=name,
                accepts=tuple(sorted(converter.accepts)),
                available=version is not None,
                version=version,
                reason=reason,
                licence=_LICENCES[name],
                default=name in defaults,
            )
        )
    return infos


def override_registry(name: str) -> ConverterRegistry:
    """The named converter first, then the defaults.

    Raises `FactoryValidationError` on field `converter` for an unknown name, or for a converter
    that cannot run here, naming the extra or the model directory.
    """
    build = CONVERTERS.get(name)
    if build is None:
        known = ", ".join(CONVERTERS)
        raise FactoryValidationError(
            [ValidationIssue("converter", f"{name}: unknown converter; known: {known}")]
        )
    converter = build()
    try:
        converter.version()
    except ConverterUnavailable as exc:
        raise FactoryValidationError([ValidationIssue("converter", f"{name}: {exc}")]) from exc
    return default_converters().preferring(converter)
