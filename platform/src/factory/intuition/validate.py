"""Pure shape checks of an interpretation (spec rulings 4 and 5).

Invariants: length counts Unicode code points after NFC, never bytes; every problem is reported
together, located at `text`, `sources` or `sources[i]`; reasons come from a fixed vocabulary and
never carry text of the interpretation or of a source.
"""

from __future__ import annotations

import unicodedata

from factory.errors import ValidationIssue
from factory.model.intuition import (
    INTERPRETATION_MAX_CHARS,
    INTERPRETATION_MAX_SOURCES,
    CitationSourceInput,
    InterpretationInput,
    QuoteSourceInput,
)


def text_length(text: str) -> int:
    """The length of `text` in code points after NFC normalisation."""
    return len(unicodedata.normalize("NFC", text))


def shape_issues(entry: InterpretationInput) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not entry.text.strip():
        issues.append(ValidationIssue("text", "must not be blank"))
    elif text_length(entry.text) > INTERPRETATION_MAX_CHARS:
        issues.append(ValidationIssue("text", f"at most {INTERPRETATION_MAX_CHARS} characters"))
    if not entry.sources:
        issues.append(ValidationIssue("sources", "at least one source is required"))
    elif len(entry.sources) > INTERPRETATION_MAX_SOURCES:
        issues.append(ValidationIssue("sources", f"at most {INTERPRETATION_MAX_SOURCES} sources"))
    seen: set[tuple[str | None, ...]] = set()
    for index, source in enumerate(entry.sources):
        key = _locator(source)
        if key in seen:
            issues.append(ValidationIssue(f"sources[{index}]", "duplicate source"))
        seen.add(key)
    return issues


def _locator(source: QuoteSourceInput | CitationSourceInput) -> tuple[str | None, ...]:
    if isinstance(source, QuoteSourceInput):
        return ("quote", source.conversion_id, source.anchor, " ".join(source.quote.split()))
    return ("citation", source.reference, source.work_id)
