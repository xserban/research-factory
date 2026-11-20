"""Pure design check of an agent-proposed miner (lane L12; design note on-the-fly-miners.md).

Invariants:
- Pure and read-only: no event, no table, no model call. It complements `validate_miner`
  (shape and meaning of any spec) with the rules of a proposal made on the fly.
- The issues are located like `validate_miner`'s (`fields[1].description`) and the result is
  deterministic for the same spec, question and limit.
- It changes no admission, evidence count or gate: it only reports.
"""

from __future__ import annotations

import re

from factory.errors import ValidationIssue
from factory.mining.spec import EnumKind, MinerSpec, QuoteKind

MAX_PROPOSAL_FIELDS = 8
"""Default cap on the fields of a proposed miner (a brief allows fewer: pass `max_fields`)."""

RESTATEMENT_OVERLAP = 0.8
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "for",
        "to",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "by",
        "with",
        "at",
        "as",
        "from",
        "that",
        "this",
        "it",
        "its",
        "do",
        "does",
        "did",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "when",
        "where",
    }
)


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(w for w in words if w not in _STOP and len(w) > 1)


def _restates(text: str, question: frozenset[str]) -> bool:
    tokens = _tokens(text)
    if len(tokens) < 2 or not question:
        return False
    return len(tokens & question) / len(tokens) >= RESTATEMENT_OVERLAP


def check_proposal(
    spec: MinerSpec, question: str | None = None, *, max_fields: int = MAX_PROPOSAL_FIELDS
) -> tuple[ValidationIssue, ...]:
    """Every problem of a proposed miner, empty when it may go to review.

    Rules: at most `max_fields` fields; every field has a description; the selector caps the
    works read (`selector.max_units`); a miner with a required quote field, or an enum field
    under an evidence rule that asks for quotes, names at least one absence value
    (`evidence.absence_values`, the 'not stated' outcome); and, when `question` is given, no
    field whose name or description merely restates it (at least 80% of its content words are the
    question's). The last rule is a lexical screen: a reviewer still reads the schema."""
    issues: list[ValidationIssue] = []
    if len(spec.fields) > max_fields:
        issues.append(ValidationIssue("fields", f"at most {max_fields} fields in a proposal"))
    for i, f in enumerate(spec.fields):
        if not f.description.strip():
            issues.append(ValidationIssue(f"fields[{i}].description", "define the field"))
    if spec.selector.max_units is None:
        issues.append(ValidationIssue("selector.max_units", "cap the works the miner reads"))
    needs_absence = any(isinstance(f.kind, QuoteKind) and f.required for f in spec.fields) or (
        spec.evidence.enum_needs_quote and any(isinstance(f.kind, EnumKind) for f in spec.fields)
    )
    if needs_absence and not spec.evidence.absence_values:
        issues.append(
            ValidationIssue("evidence.absence_values", "name the enum value that says 'not stated'")
        )
    if question is not None:
        asked = _tokens(question)
        for i, f in enumerate(spec.fields):
            if _restates(f.description, asked) or _restates(f.name.replace("_", " "), asked):
                issues.append(
                    ValidationIssue(
                        f"fields[{i}]", "restates the question; a field records what a work says"
                    )
                )
    return tuple(issues)
