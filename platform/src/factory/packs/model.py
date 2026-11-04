"""Pack data model: field and pack dataclasses and enums (pure data)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class FieldKind(StrEnum):
    """How a field's value is typed."""

    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    BOOL = "bool"


class UnitFamily(StrEnum):
    """Which unit vocabulary and canonicalisation a field uses."""

    SCORE = "score"
    COUNT = "count"
    OTHER = "other"
    NONE = "none"


class Check(StrEnum):
    """Which verification a field's value must pass against its evidence."""

    NUMBER = "number"
    TEXT_IN_QUOTE = "text-in-quote"
    NONE = "none"


@dataclass(frozen=True)
class FieldDef:
    """One extractable field. ``normaliser`` names a text normaliser or is None."""

    name: str
    group: str
    kind: FieldKind
    unit_family: UnitFamily
    check: Check
    units: tuple[str, ...] = ()
    normaliser: str | None = None


@dataclass(frozen=True)
class ReportSpec:
    """How the evidence report reads a pack's rows (derivation only, never hashed).

    ``metric_directions`` maps a normalised metric name to ``higher_is_better``;
    ``speed_fields`` maps a speed field to whether a higher value is faster. Speed fields
    never enter a group table or a frontier; ``frontier_costs`` are the hardware-independent
    cost axes and ``display_costs`` the cost cells a group table shows.
    """

    value_field: str
    direction_field: str
    metric_directions: Mapping[str, bool]
    frontier_costs: tuple[str, ...]
    speed_fields: Mapping[str, bool]
    speed_context: tuple[str, ...]
    proposed_field: str
    display_costs: tuple[str, ...]


@dataclass(frozen=True)
class Pack:
    """A versioned set of fields with required fields and default keys."""

    name: str
    version: int
    fields: tuple[FieldDef, ...]
    required: tuple[str, ...]
    default_comparability_keys: tuple[str, ...]
    citation_patterns: tuple[str, ...]
    report: ReportSpec | None = field(default=None, repr=False, compare=False, hash=False)
    """Derivation-only report spec (plan E ruling 15): outside repr, equality and the digest."""

    def field(self, name: str) -> FieldDef | None:
        """Return the field called ``name``, or None."""
        for f in self.fields:
            if f.name == name:
                return f
        return None
