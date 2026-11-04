"""Pack data model: field and pack dataclasses and enums (pure data)."""

from __future__ import annotations

from dataclasses import dataclass
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
class Pack:
    """A versioned set of fields with required fields and default keys."""

    name: str
    version: int
    fields: tuple[FieldDef, ...]
    required: tuple[str, ...]
    default_comparability_keys: tuple[str, ...]
    citation_patterns: tuple[str, ...]

    def field(self, name: str) -> FieldDef | None:
        """Return the field called ``name``, or None."""
        for f in self.fields:
            if f.name == name:
                return f
        return None
