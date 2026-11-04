from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.document.anchors import AnchorKind
from factory.events.catalog import default_catalog
from factory.model.document import ConversionFailed, Converted, FailureReason

CNV = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def counts() -> dict[str, int]:
    return {kind.value: 1 for kind in AnchorKind}


def converted_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "conversion_id": CNV,
        "document_id": DOC,
        "converter": "latexml",
        "converter_version": "0.8.7",
        "raw_hash": HASH_A,
        "markdown_hash": HASH_B,
        "manifest_hash": HASH_C,
        "counts": counts(),
        "warnings": [],
    }
    base.update(overrides)
    return base


def failed_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "document_id": DOC,
        "converter": "latexml",
        "reason": FailureReason.CONVERSION_ERROR,
        "error_class": "ValueError",
    }
    base.update(overrides)
    return base


def test_converted_requires_every_kind_count() -> None:
    Converted(**converted_kwargs())
    partial = counts()
    del partial[AnchorKind.TABLE.value]
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(counts=partial))
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(counts={**counts(), "unknown_kind": 0}))


def test_converted_rejects_negative_count() -> None:
    bad = {**counts(), AnchorKind.PARAGRAPH.value: -1}
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(counts=bad))


def test_converted_requires_blob_refs_and_names() -> None:
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(raw_hash="md5:x"))
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(conversion_id=DOC))
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(converter="   "))


def test_failed_error_class_only_for_conversion_error() -> None:
    ConversionFailed(**failed_kwargs())
    ConversionFailed(**failed_kwargs(reason=FailureReason.NO_CONVERTER, error_class=None))
    ConversionFailed(**failed_kwargs(reason=FailureReason.CONVERTER_UNAVAILABLE, error_class=None))
    with pytest.raises(ValidationError):
        ConversionFailed(**failed_kwargs(error_class=None))
    with pytest.raises(ValidationError):
        ConversionFailed(**failed_kwargs(reason=FailureReason.NO_CONVERTER))


def test_warning_cap() -> None:
    Converted(**converted_kwargs(warnings=["x" * 200]))
    Converted(**converted_kwargs(warnings=["w"] * 50))
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(warnings=["w"] * 51))
    with pytest.raises(ValidationError):
        Converted(**converted_kwargs(warnings=["x" * 201]))


def test_catalog_registers_document_events() -> None:
    catalog = default_catalog()
    expected = {
        "document.converted": Converted,
        "document.conversion_failed": ConversionFailed,
    }
    for name, payload in expected.items():
        assert name in catalog
        assert catalog.get(name).schema == 1
        assert catalog.get(name).payload is payload
