"""Meaning checks of a miner specification (the shape is `spec_from_json`'s).

Invariants:
- Pure; the issues are located (`fields[2].kind.values`) and carry fixed reasons.
- A registered miner has a name in the `m-` namespace, no `Unverified` field, a row key, at least
  one required field (the identity a disagreement shows) and, when its evidence rule asks for a
  quote, a field that can carry one. A built-in (`built_in=True`) is exempt from those that its
  pack never met.
- A registered miner's row key shares no field with its row anchor (an anchor in the key unmatches
  two passes' rows). A derived miner (`taxonomy` set) has no row anchor and its absence values are
  values of its `category` field; any absence value is a value of some enum field.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from factory.errors import ValidationIssue
from factory.extraction.numbers import normalise_text
from factory.mining.spec import (
    FIELD_NAME_RE,
    AnchorKindRef,
    CitationKind,
    EnumKind,
    MinerSpec,
    NumberKind,
    QuoteKind,
    Unverified,
    WorkRefKind,
)
from factory.model.extraction import MINER_NAME_RE
from factory.services.skills import SKILL_NAME_RE

UNVERIFIED_REFUSED = "free text is not verifiable; use a quote, enum, number or another kind"
NAME_OUTSIDE_NAMESPACE = "a registered miner's name must match ^m-[a-z0-9]+(-[a-z0-9]+)*$"


def _compiles(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def validate_miner(spec: MinerSpec, *, built_in: bool = False) -> list[ValidationIssue]:
    """Every problem of `spec`, empty when it is acceptable. `built_in` relaxes the rules that
    only registered miners must meet (name namespace, no unverified field, row key, evidence)."""
    issues: list[ValidationIssue] = []

    def bad(field: str, reason: str) -> None:
        issues.append(ValidationIssue(field, reason))

    if not built_in and re.fullmatch(MINER_NAME_RE, spec.name) is None:
        bad("name", NAME_OUTSIDE_NAMESPACE)
    if spec.version < 1:
        bad("version", "must be at least 1")
    if re.fullmatch(SKILL_NAME_RE, spec.procedure) is None:
        bad("procedure", "must be a skill name like rf-extract")
    if not spec.fields:
        bad("fields", "declare at least one field")
    names = [f.name for f in spec.fields]
    for i, f in enumerate(spec.fields):
        where = f"fields[{i}]"
        if re.fullmatch(FIELD_NAME_RE, f.name) is None:
            bad(f"{where}.name", "must be lowercase letters, digits and underscores")
        elif names.count(f.name) > 1 and names.index(f.name) != i:
            bad(f"{where}.name", "duplicate field name")
        if not f.group.strip():
            bad(f"{where}.group", "must not be blank")
        _kind_issues(f.kind, f"{where}.kind", built_in, bad)
    known = set(names)
    for label, listed in (
        ("row_key_fields", spec.row_key_fields),
        ("row_anchor_fields", spec.row_anchor_fields),
    ):
        for i, name in enumerate(listed):
            if name not in known:
                bad(f"{label}[{i}]", "not a field of the miner")
    if not built_in:
        if not spec.row_key_fields and spec.taxonomy is None:
            # a derived miner without key fields keys its row on the work (IDEA-69 (1))
            bad("row_key_fields", "declare the fields that identify a record")
        if not any(f.required for f in spec.fields):
            bad("fields", "declare at least one required field")
        for i, name in enumerate(spec.row_key_fields):
            if name in spec.row_anchor_fields:
                bad(
                    f"row_key_fields[{i}]",
                    "an anchor in the row key makes two passes' rows fail to align",
                )
    _absence_issues(spec, bad)
    for i, c in enumerate(spec.conditionals):
        where = f"conditionals[{i}]"
        if c.field not in known:
            bad(f"{where}.field", "not a field of the miner")
        when = spec.field_named(c.when)
        if when is None:
            bad(f"{where}.when", "not a field of the miner")
        elif isinstance(when.kind, EnumKind):
            outside = [v for v in c.values if v not in when.kind.values]
            if outside:
                bad(f"{where}.values", "not values of the enum field " + c.when)
        elif not built_in:
            bad(f"{where}.when", "must name an enum field")
    for i, pattern in enumerate(spec.selector.heading_patterns):
        if not _compiles(pattern):
            bad(f"selector.heading_patterns[{i}]", "does not compile")
    if spec.selector.max_units is not None and spec.selector.max_units < 1:
        bad("selector.max_units", "must be at least 1")
    for key, value in (
        ("recall_min", spec.regime.recall_min),
        ("field_agreement_min", spec.regime.field_agreement_min),
    ):
        if not 0 < value <= 1:
            bad(f"regime.{key}", "must be in (0, 1]")
    if spec.regime.calibration_size < 1:
        bad("regime.calibration_size", "must be at least 1")
    if spec.evidence.min_quotes_per_record < 0:
        bad("evidence.min_quotes_per_record", "must not be negative")
    elif spec.evidence.min_quotes_per_record >= 1 and not _can_quote(spec):
        bad("evidence.min_quotes_per_record", "needs a quote, citation or title-reference field")
    if not built_in:
        if spec.evidence.min_quotes_per_record < 1:
            bad("evidence.min_quotes_per_record", "a registered miner needs at least one quote")
        if not spec.evidence.enum_needs_quote and any(
            isinstance(f.kind, EnumKind) for f in spec.fields
        ):
            bad("evidence.enum_needs_quote", "an enum field needs an evidence quote (R-141)")
        if spec.regime.passes != 2:
            bad(
                "regime.passes", "a registered miner runs two passes; a single pass is not enforced"
            )
    for i, pattern in enumerate(spec.citation_patterns):
        if not _compiles(pattern):
            bad(f"citation_patterns[{i}]", "does not compile")
    return issues


def _absence_issues(spec: MinerSpec, bad: Callable[[str, str], None]) -> None:
    """Derived miners key rows on the category and name their absence values in it; any other
    miner's absence values must be values of some enum field."""
    if spec.taxonomy is not None:
        if spec.row_anchor_fields:
            bad(
                "row_anchor_fields", "a derived miner keys rows on the category, never on an anchor"
            )
        category = spec.field_named("category")
        allowed = (
            category.kind.values
            if category is not None and isinstance(category.kind, EnumKind)
            else ()
        )
        for i, value in enumerate(spec.evidence.absence_values):
            if value not in allowed:
                bad(f"evidence.absence_values[{i}]", "not a value of the enum field category")
        return
    enum_values = {v for f in spec.fields if isinstance(f.kind, EnumKind) for v in f.kind.values}
    for i, value in enumerate(spec.evidence.absence_values):
        if value not in enum_values:
            bad(f"evidence.absence_values[{i}]", "not a value of any enum field of the miner")


def _can_quote(spec: MinerSpec) -> bool:
    return any(
        isinstance(f.kind, QuoteKind | CitationKind)
        or (isinstance(f.kind, WorkRefKind) and f.kind.by == "title")
        for f in spec.fields
    )


def _kind_issues(kind: object, where: str, built_in: bool, bad: Callable[[str, str], None]) -> None:
    if isinstance(kind, Unverified) and not built_in:
        bad(where, UNVERIFIED_REFUSED)
    elif isinstance(kind, EnumKind):
        if not kind.values:
            bad(f"{where}.values", "an enum needs at least one value")
        if len(set(kind.values)) != len(kind.values):
            bad(f"{where}.values", "values must be unique")
        if any(v != normalise_text(v) or not v for v in kind.values):
            bad(f"{where}.values", "values must be normalised: lowercase, single spaces")
    elif isinstance(kind, CitationKind):
        if not kind.patterns:
            bad(f"{where}.patterns", "a citation needs at least one pattern")
        for i, pattern in enumerate(kind.patterns):
            if not _compiles(pattern):
                bad(f"{where}.patterns[{i}]", "does not compile")
    elif isinstance(kind, AnchorKindRef):
        if not kind.kinds:
            bad(f"{where}.kinds", "an anchor field needs at least one anchor kind")
    elif isinstance(kind, NumberKind) and len(set(kind.units)) != len(kind.units):
        bad(f"{where}.units", "units must be unique")
