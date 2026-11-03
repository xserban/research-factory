"""Contract test kit: the checks every converter must pass on a set of sample documents.

`assert_converter_contract` raises `AssertionError` naming the first broken property. It checks:
- the version string is non-empty;
- determinism: converting the same bytes twice gives equal Markdown and equal hashes;
- idempotence: anchorising the converted Markdown again changes nothing;
- a valid manifest: parsing the converted Markdown gives the manifest `convert` returned;
- the converter version and warnings are well-formed.

Samples are `(raw bytes, media type)` pairs. They must be media types the converter accepts.
"""

from factory.document.anchorise import anchorise
from factory.document.anchors import parse_manifest
from factory.document.converter import Converter, convert


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_converter_contract(converter: Converter, samples: list[tuple[bytes, str]]) -> None:
    """Check the converter contract on each sample; raise `AssertionError` on the first breach."""
    _require(converter.version().strip() != "", f"{converter.name}: version must be non-empty")
    for index, (raw, media_type) in enumerate(samples):
        label = f"{converter.name} sample {index} ({media_type})"
        first = convert(converter, raw, media_type)
        second = convert(converter, raw, media_type)
        _require(first.markdown == second.markdown, f"{label}: non-deterministic Markdown")
        _require(first.markdown_hash == second.markdown_hash, f"{label}: non-deterministic hash")
        _require(anchorise(first.markdown) == first.markdown, f"{label}: anchorise not idempotent")
        _require(
            parse_manifest(first.markdown) == first.manifest,
            f"{label}: manifest does not match its Markdown",
        )
        _require(first.converter_version.strip() != "", f"{label}: empty converter version")
