"""Tests for the converter contract: `convert`, its refusals, and the contract test kit."""

import hashlib

import pytest

from factory.document import converter as converter_module
from factory.document.anchorise import anchorise
from factory.document.anchors import ManifestError
from factory.document.converter import ConversionResult, ConverterUnavailable, convert
from factory.errors import FactoryValidationError
from tests.document.kit import assert_converter_contract

SOURCE_MARKDOWN = "# 1 Intro\n\nText here.\n\n## 1.2 Detail\n\nMore text.\n"


class StubConverter:
    """A converter returning fixed Markdown; it records each `to_markdown` call."""

    name = "stub"
    accepts = frozenset({"text/html"})

    def __init__(
        self,
        markdown: str = SOURCE_MARKDOWN,
        *,
        version: str = "1.0+stub",
        unavailable: bool = False,
    ) -> None:
        self._markdown = markdown
        self._version = version
        self._unavailable = unavailable
        self.calls = 0

    def version(self) -> str:
        if self._unavailable:
            raise ConverterUnavailable("stubtool is not installed")
        return self._version

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.calls += 1
        return self._markdown, ("table t3: ragged rows padded",)


class CounterConverter(StubConverter):
    """Non-deterministic on purpose: every call appends a new counter value to the body."""

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.calls += 1
        return f"# 1 Intro\n\nBody {self.calls}.\n", ()


def test_convert_anchorises_and_hashes() -> None:
    stub = StubConverter()
    result = convert(stub, b"<html></html>", "text/html")

    assert isinstance(result, ConversionResult)
    assert result.markdown == anchorise(SOURCE_MARKDOWN)
    assert '<a id="s1.p1"></a>' in result.markdown
    assert result.manifest.get("s1") is not None
    assert result.manifest.get("s1.2") is not None
    expected = "sha256:" + hashlib.sha256(result.markdown.encode("utf-8")).hexdigest()
    assert result.markdown_hash == expected
    assert result.converter == "stub"
    assert result.converter_version == "1.0+stub+anchors2"
    assert result.warnings == ("table t3: ragged rows padded",)


def test_unaccepted_media_type_refused() -> None:
    stub = StubConverter()
    with pytest.raises(FactoryValidationError) as excinfo:
        convert(stub, b"%PDF-1.4", "application/pdf")

    assert [issue.field for issue in excinfo.value.issues] == ["media_type"]
    assert stub.calls == 0


def test_unavailable_tool_raises() -> None:
    stub = StubConverter(unavailable=True)
    with pytest.raises(ConverterUnavailable, match="stubtool"):
        convert(stub, b"<html></html>", "text/html")
    assert stub.calls == 0


def test_manifest_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(markdown: str) -> None:
        raise ManifestError("broken anchor grammar")

    monkeypatch.setattr(converter_module, "parse_manifest", refuse)
    with pytest.raises(ManifestError, match="broken anchor grammar"):
        convert(StubConverter(), b"<html></html>", "text/html")


def test_kit_passes_for_deterministic_converter() -> None:
    samples = [(b"<html></html>", "text/html")]
    assert_converter_contract(StubConverter(), samples)


def test_kit_detects_nondeterminism() -> None:
    samples = [(b"<html></html>", "text/html")]
    with pytest.raises(AssertionError):
        assert_converter_contract(CounterConverter(), samples)


def test_kit_flags_empty_version() -> None:
    samples = [(b"<html></html>", "text/html")]
    with pytest.raises(AssertionError, match="version"):
        assert_converter_contract(StubConverter(version="  "), samples)
