# ruff: noqa: RUF001
"""Pure write-time checks of one sentence (slice 7b, plan W-A, task 3; spec rulings 9 and 11).

Declares: `check_sentence`, `is_single_sentence`, `QUANTIFIERS`, `COMPARATIVES`, `DraftContext`,
`CheckOutcome`. No I/O: the supports arrive already resolved.

Invariants:
- A refusal writes nothing; a flag is stored on the sentence and shown to the verifier.
- A refusal or flag names a position or a fixed code, never the sentence's or a quote's text.
- Numbers are compared as `Decimal` values, so `85.2%` and `85.2` are equal and nothing else is
  normalised. A number is supported by a number in a support span, a cited cell's canonical or
  printed value, a stored stat value or the publication year of a support work.
- Citations are not typed by the writer: any citation pattern in the text is checked against the
  first authors of the support works.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from factory.errors import ValidationIssue
from factory.extraction.numbers import normalise_text, numbers_in
from factory.model.drafts import SentenceClass, SentenceFlag, SupportKind
from factory.model.work_ids import normalize_title
from factory.packs.ml_benchmark import CITATION_PATTERNS
from factory.references.match import surname_key

if TYPE_CHECKING:
    from factory.services.supports import ResolvedSupport

QUANTIFIERS: tuple[str, ...] = (
    "outperforms all",
    "state-of-the-art",
    "consistently",
    "majority",
    "always",
    "never",
    "every",
    "most",
    "none",
    "best",
    "all",
)
COMPARATIVES: tuple[str, ...] = (
    "better",
    "worse",
    "outperform\\w*",
    "higher",
    "lower",
    "faster",
    "slower",
    "best",
    "worst",
    "highest",
    "lowest",
    "fastest",
    "slowest",
    "strongest",
    "weakest",
    "stronger",
    "weaker",
    "greatest",
    "largest",
    "smallest",
    "superior",
    "inferior",
    "beat\\w*",
    "surpass\\w*",
    "exceed\\w*",
)
_QUANTIFIER_RE = re.compile(
    r"(?<![\w-])(?:" + "|".join(re.escape(q) for q in QUANTIFIERS) + r")(?![\w-])", re.IGNORECASE
)
_COMPARATIVE_RE = re.compile(r"\b(?:" + "|".join(COMPARATIVES) + r")\b", re.IGNORECASE)
_ABBREVIATIONS = re.compile(r"\b(?:et al|e\.g|i\.e|cf|figs?|eqs?|vs)\.", re.IGNORECASE)
_INITIAL = re.compile(r"\b[A-Z]\.")
_BOUNDARY = re.compile(r"[.?!][\"')\]]*\s+[A-Z0-9]")
_NAME = re.compile(r"[A-ZÀ-ÖØ-Þ][\w'’-]*")
_CITATIONS = tuple(re.compile(p) for p in CITATION_PATTERNS)


@dataclass(frozen=True)
class DraftContext:
    """What a structural sentence may not name: the surname keys of the first authors of every
    work supporting a live sentence of the draft, and the normalised method names of its cells."""

    first_authors: frozenset[str] = frozenset()
    method_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CheckOutcome:
    refusals: tuple[ValidationIssue, ...]
    flags: tuple[SentenceFlag, ...]


def is_single_sentence(text: str) -> bool:
    """False when, after masking abbreviations and single capital initials, a `.`, `?` or `!` is
    followed by whitespace and an uppercase letter or a digit."""
    masked = _ABBREVIATIONS.sub(lambda m: m.group(0).replace(".", "·"), text)
    masked = _INITIAL.sub(lambda m: m.group(0).replace(".", "·"), masked)
    return _BOUNDARY.search(masked) is None


def citation_matches(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _CITATIONS:
        found.extend(m.group(0) for m in pattern.finditer(text))
    return found


def _cited_names(match: str) -> set[str]:
    names = {
        surname_key(w)
        for w in _NAME.findall(match)
        if w.lower() not in ("et", "al") and not w.startswith("\\")
    }
    names.discard("")
    return names


def _allowed_numbers(supports: Sequence[ResolvedSupport]) -> set[Decimal]:
    allowed: set[Decimal] = set()
    for s in supports:
        allowed.update(s.numbers)
        allowed.update(Decimal(y) for y in s.years)
        if s.stat_value is not None:
            allowed.add(Decimal(s.stat_value))
        for span in s.spans:
            allowed.update(t.value for t in numbers_in(span))
    return allowed


def _author_year(text: str, authors: Collection[str]) -> bool:
    folded = normalize_title(re.sub(r"(\d{4})", r" \1 ", text))
    return any(
        re.search(rf"\b{re.escape(a)}\b.{{0,20}}?\b\d{{4}}\b", folded) is not None
        for a in authors
        if a
    )


def _names_method(text: str, methods: Collection[str]) -> bool:
    folded = f" {normalise_text(text)} "
    return any(m and re.search(rf"(?<![\w]){re.escape(m)}(?![\w])", folded) for m in methods)


def _structural(text: str, context: DraftContext) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if numbers_in(text):
        issues.append(ValidationIssue("class", "structural-number"))
    if citation_matches(text):
        issues.append(ValidationIssue("class", "structural-citation"))
    if _author_year(text, context.first_authors):
        issues.append(ValidationIssue("class", "structural-author-year"))
    if _names_method(text, context.method_names):
        issues.append(ValidationIssue("class", "structural-method-name"))
    return issues


def _class_issues(cls: SentenceClass, supports: Sequence[ResolvedSupport]) -> list[ValidationIssue]:
    kinds = {s.ref.kind for s in supports}
    if cls is SentenceClass.CLAIM and not supports:
        return [ValidationIssue("class", "claim-needs-support")]
    if cls is SentenceClass.SYNTHESIS and not kinds & {SupportKind.STAT, SupportKind.GROUP}:
        return [ValidationIssue("class", "synthesis-needs-stat-or-group")]
    if cls is SentenceClass.STRUCTURAL and supports:
        return [ValidationIssue("class", "structural-has-support")]
    return []


def _number_issues(
    text: str, cls: SentenceClass, supports: Sequence[ResolvedSupport]
) -> list[ValidationIssue]:
    tokens = numbers_in(text)
    if cls is SentenceClass.INTERPRETIVE:
        return [ValidationIssue("class", "interpretive-has-number")] if tokens else []
    allowed = _allowed_numbers(supports)
    return [
        ValidationIssue(f"text.numbers[{i}]", "number-unsupported")
        for i, token in enumerate(tokens)
        if token.value not in allowed
    ]


def _flags(
    text: str,
    cls: SentenceClass,
    supports: Sequence[ResolvedSupport],
    outline_refs: Collection[str] | None,
) -> list[SentenceFlag]:
    flags: list[SentenceFlag] = []
    authors = {a for s in supports for a in s.first_authors}
    for match in citation_matches(text):
        if not _cited_names(match) & authors:
            flags.append(SentenceFlag.CITATION_MISMATCH)
            break
    kinds = {s.ref.kind for s in supports}
    if (
        cls is SentenceClass.CLAIM
        and _QUANTIFIER_RE.search(text)
        and not kinds & {SupportKind.STAT, SupportKind.GROUP}
    ):
        flags.append(SentenceFlag.QUANTIFIER_WITHOUT_STATISTIC)
    cell_groups = {g for s in supports if s.ref.kind is SupportKind.CELL for g in s.group_ids}
    if _COMPARATIVE_RE.search(text) and len(cell_groups) > 1:
        flags.append(SentenceFlag.CROSS_GROUP)
    works = {w for s in supports for w in s.work_ids}
    if cls is SentenceClass.SYNTHESIS and len(works) == 1:
        flags.append(SentenceFlag.SINGLE_SOURCE_GENERALISATION)
    if outline_refs is not None and any(_off_outline(s, outline_refs) for s in supports):
        flags.append(SentenceFlag.OFF_OUTLINE)
    return flags


def _off_outline(support: ResolvedSupport, outline_refs: Collection[str]) -> bool:
    if support.ref.kind in (SupportKind.STAT, SupportKind.INTERP):
        return False
    if support.ref.text in outline_refs:
        return False
    return not (
        support.ref.kind is SupportKind.CELL
        and any(f"group:{g}" in outline_refs for g in support.group_ids)
    )


def check_sentence(
    text: str,
    cls: SentenceClass,
    supports: Sequence[ResolvedSupport],
    *,
    draft_context: DraftContext,
    outline_refs: Collection[str] | None,
) -> CheckOutcome:
    """Refusals and flags of one sentence. `supports` are in the writer's order; an ineligible
    support is a refusal `supports[i]` with its reason. Refusals are complete, not first-only."""
    refusals: list[ValidationIssue] = [
        ValidationIssue(f"supports[{i}]", s.reason or "unknown")
        for i, s in enumerate(supports)
        if not s.eligible
    ]
    refusals += _class_issues(cls, supports)
    if not is_single_sentence(text):
        refusals.append(ValidationIssue("text", "more-than-one-sentence"))
    if cls is SentenceClass.STRUCTURAL:
        refusals += _structural(text, draft_context)
        return CheckOutcome(tuple(refusals), ())
    refusals += _number_issues(text, cls, [s for s in supports if s.eligible])
    flags = _flags(text, cls, [s for s in supports if s.eligible], outline_refs)
    return CheckOutcome(tuple(refusals), tuple(dict.fromkeys(flags)))
