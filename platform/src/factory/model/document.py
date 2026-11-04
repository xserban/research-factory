"""Document conversion vocabulary and event payloads: a converted document or a failed conversion.

A conversion turns one stored document (a raw LaTeXML, HTML or PDF blob) into canonical Markdown
with an anchor manifest. Its payloads carry library hashes and counts only, never document text.

Invariants enforced here (validated at the boundary, before any event is written):
- A conversion records a count for every anchor kind and no other key; counts are non-negative.
- A conversion carries at most 50 warnings, each at most 200 characters.
- A failure names an error class exactly when its reason is a conversion error.

This module is pure. Services in `factory.services` decide when these events are written.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from factory.document.anchors import AnchorKind
from factory.model.base import StrictModel
from factory.model.fulltext import DOCUMENT_ID_RE
from factory.model.identity import BLOB_REF_RE, CONVERSION_ID_RE
from factory.model.screening import NonBlank

WARNING_MAX_CHARS = 200
WARNINGS_MAX = 50


class FailureReason(StrEnum):
    NO_CONVERTER = "no-converter"
    CONVERTER_UNAVAILABLE = "converter-unavailable"
    CONVERSION_ERROR = "conversion-error"


WarningText = Annotated[NonBlank, StringConstraints(max_length=WARNING_MAX_CHARS)]


# --- Event payloads (schema 1). Written by `factory.services.document`, folded by
# `factory.index.document`.


class Converted(StrictModel):
    """A document converted to canonical Markdown. One row per document, converter and version."""

    conversion_id: str = Field(pattern=CONVERSION_ID_RE)
    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    converter: NonBlank
    converter_version: NonBlank
    raw_hash: str = Field(pattern=BLOB_REF_RE)
    markdown_hash: str = Field(pattern=BLOB_REF_RE)
    manifest_hash: str = Field(pattern=BLOB_REF_RE)
    counts: dict[str, int]
    warnings: list[WarningText] = Field(max_length=WARNINGS_MAX)

    @field_validator("counts", mode="before")
    @classmethod
    def _legacy_counts_lack_bibliography(cls, counts: Any) -> Any:
        """Events stored before `bibliography_entry` existed read it as 0 (events are immutable)."""
        if isinstance(counts, dict) and AnchorKind.BIBLIOGRAPHY_ENTRY.value not in counts:
            return {**counts, AnchorKind.BIBLIOGRAPHY_ENTRY.value: 0}
        return counts

    @field_validator("counts")
    @classmethod
    def _counts_cover_every_kind(cls, counts: dict[str, int]) -> dict[str, int]:
        if set(counts) != {kind.value for kind in AnchorKind}:
            raise ValueError("counts name every anchor kind and no other")
        if any(count < 0 for count in counts.values()):
            raise ValueError("a count is never negative")
        return counts


class ConversionFailed(StrictModel):
    """A conversion that produced no Markdown, and why."""

    document_id: str = Field(pattern=DOCUMENT_ID_RE)
    converter: NonBlank | None
    reason: FailureReason
    error_class: NonBlank | None

    @model_validator(mode="after")
    def _error_class_follows_reason(self) -> Self:
        is_error = self.reason is FailureReason.CONVERSION_ERROR
        if (self.error_class is not None) != is_error:
            raise ValueError("an error class is recorded exactly for a conversion error")
        return self
