"""The substring checks of a verdict (slice 7b, plan W-B, ruling 3). Pure.

The platform never judges support; it checks that what a verdict names is verbatim where it says.
The service and the projector read the same rules, so a hand-written verdict that fails them
changes nothing.

Invariants:
- `sentence_span` is compared with the sentence after whitespace collapsing only; a support
  substring with `normalise_quote` on both sides, as a quote is.
- Reasons are fixed codes; none carries text of the sentence or of a span.
- `span_length_issues` holds at write time only: the projector folds by the substring rules, so
  a verdict logged before the minimum still stands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from factory.document.quotes import normalise_quote
from factory.errors import ValidationIssue
from factory.model.drafts import SupportSpan, Verdict

MIN_SPAN_CHARS = 12
"""The shortest span a verdict may quote (plan PF ruling 2), unless that is the whole source."""


def _collapse(text: str) -> str:
    return " ".join(text.split())


def in_sentence(span: str, sentence: str) -> bool:
    needle = _collapse(span)
    return bool(needle) and needle in _collapse(sentence)


def in_spans(substring: str, spans: Sequence[str]) -> bool:
    needle = normalise_quote(substring)
    return bool(needle) and any(needle in normalise_quote(span) for span in spans)


def _too_short(span: str, sources: Sequence[str]) -> bool:
    needle = _collapse(span)
    return len(needle) < MIN_SPAN_CHARS and needle not in {_collapse(s) for s in sources}


def span_length_issues(
    sentence_span: str | None,
    support_spans: Sequence[SupportSpan],
    *,
    sentence: str,
    spans_by_ref: Mapping[str, Sequence[str]],
) -> list[ValidationIssue]:
    """Spans too short to carry a verdict's quote. Write time only (see the module docstring)."""
    issues: list[ValidationIssue] = []
    if sentence_span is not None and _too_short(sentence_span, [sentence]):
        issues.append(ValidationIssue("sentence_span", f"at least {MIN_SPAN_CHARS} characters"))
    for i, span in enumerate(support_spans):
        if _too_short(span.substring, spans_by_ref.get(span.ref, ())):
            issues.append(
                ValidationIssue(
                    f"support_spans[{i}].substring", f"at least {MIN_SPAN_CHARS} characters"
                )
            )
    return issues


def verdict_issues(
    verdict: Verdict,
    sentence_span: str | None,
    support_spans: Sequence[SupportSpan],
    *,
    sentence: str,
    spans_by_ref: Mapping[str, Sequence[str]],
) -> list[ValidationIssue]:
    """Why this verdict cannot stand against the sentence and the spans it was shown (ruling 3);
    `spans_by_ref` maps each support of the sentence to its spans."""
    issues: list[ValidationIssue] = []
    if sentence_span is None:
        if verdict is not Verdict.SUPPORTED:
            issues.append(ValidationIssue("sentence_span", "required unless supported"))
    elif not in_sentence(sentence_span, sentence):
        issues.append(ValidationIssue("sentence_span", "not a substring of the sentence"))
    if not support_spans and verdict is not Verdict.UNSUPPORTED:
        issues.append(ValidationIssue("support_spans", "at least one is required"))
    for i, span in enumerate(support_spans):
        if span.ref not in spans_by_ref:
            issues.append(ValidationIssue(f"support_spans[{i}].ref", "not a support of it"))
        elif not in_spans(span.substring, spans_by_ref[span.ref]):
            issues.append(
                ValidationIssue(f"support_spans[{i}].substring", "not a substring of the support")
            )
    return issues
