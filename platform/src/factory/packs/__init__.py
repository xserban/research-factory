"""Domain packs: pure data describing extractable fields.

Invariants: packs are frozen; a pack is identified by ``(name, version)``;
any change to a pack's content is a new version. No pack logic judges.
"""

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


from factory.packs.ml_benchmark import ML_BENCHMARK_V1  # noqa: E402

_PACKS: dict[tuple[str, int], Pack] = {
    (ML_BENCHMARK_V1.name, ML_BENCHMARK_V1.version): ML_BENCHMARK_V1,
}


def get_pack(name: str, version: int) -> Pack | None:
    """Return the registered pack ``(name, version)``, or None."""
    return _PACKS.get((name, version))


__all__ = [
    "ML_BENCHMARK_V1",
    "Check",
    "FieldDef",
    "FieldKind",
    "Pack",
    "UnitFamily",
    "get_pack",
]
