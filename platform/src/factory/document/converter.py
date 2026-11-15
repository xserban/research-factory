"""The converter contract: raw source bytes in, canonical anchorised Markdown and manifest out.

A converter turns one accepted media type into plain Markdown and reports its own warnings. It
never writes anchors; `convert` applies `anchorise`, so one scheme holds across formats. For a
fixed converter version and fixed input bytes, `convert` returns byte-identical Markdown and the
same hash. `convert` refuses a media type the converter does not accept, before any work is done.
"""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from factory.document.anchorise import ANCHOR_VERSION, anchorise, stamp_version
from factory.document.anchors import Manifest, parse_manifest
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue


class ConverterUnavailable(FactoryError):
    """The conversion tool is not installed; the message names the tool."""


@dataclass(frozen=True)
class ConversionResult:
    """One converted document.

    `markdown` is canonical (anchorised). `markdown_hash` is `sha256:<hex>` of its UTF-8 bytes.
    `converter_version` is the converter's own version joined with its tool version, then the
    anchoring version (`stamp_version`): a change of anchoring rules is a new version.
    `warnings` are the converter's non-fatal findings, in the order it reported them.
    """

    markdown: str
    manifest: Manifest
    markdown_hash: str
    converter: str
    converter_version: str
    warnings: tuple[str, ...]


class Converter(Protocol):
    """A format-specific converter.

    `accepts` lists the media types `to_markdown` handles. `version` raises `ConverterUnavailable`
    when the tool is absent. `to_markdown` returns plain Markdown and its warnings; it must be
    deterministic for fixed input bytes.
    """

    name: str
    accepts: frozenset[str]

    def version(self) -> str: ...

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]: ...


def convert(
    converter: Converter, raw: bytes, media_type: str, *, anchor_version: int = ANCHOR_VERSION
) -> ConversionResult:
    """Convert `raw` with `converter` and return the canonical result.

    Raises `FactoryValidationError` on field `media_type` if the converter does not accept it, and
    `ConverterUnavailable` if the tool is absent. A `ManifestError` from the anchored output
    propagates unchanged.
    """
    if media_type not in converter.accepts:
        raise FactoryValidationError(
            [ValidationIssue("media_type", f"{converter.name} does not accept {media_type!r}")]
        )
    version = converter.version()
    markdown, warnings = converter.to_markdown(raw, media_type)
    canonical = anchorise(markdown, version=anchor_version)
    manifest = parse_manifest(canonical)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ConversionResult(
        markdown=canonical,
        manifest=manifest,
        markdown_hash=f"sha256:{digest}",
        converter=converter.name,
        converter_version=stamp_version(version, anchor_version),
        warnings=tuple(warnings),
    )
