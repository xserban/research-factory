"""Domain packs: pure data describing extractable fields.

Invariants: packs are frozen; a pack is identified by ``(name, version)``;
any change to a pack's content is a new version. No pack logic judges.
"""

from __future__ import annotations

from factory.packs.contribution import CONTRIBUTION_V1
from factory.packs.ml_benchmark import ML_BENCHMARK_V1
from factory.packs.model import (
    Check,
    Conditional,
    FieldDef,
    FieldKind,
    Pack,
    ReportSpec,
    UnitFamily,
)

_PACKS: dict[tuple[str, int], Pack] = {
    (p.name, p.version): p for p in (ML_BENCHMARK_V1, CONTRIBUTION_V1)
}


NON_COMPARABLE_KEYS = frozenset({"throughput", "latency", "memory"})
"""Fields that are never comparability keys: speed and memory are compared only within a paper
(decision 42 item 3, acceptance 12a)."""


def get_pack(name: str, version: int) -> Pack | None:
    """Return the registered pack ``(name, version)``, or None."""
    return _PACKS.get((name, version))


__all__ = [
    "CONTRIBUTION_V1",
    "ML_BENCHMARK_V1",
    "NON_COMPARABLE_KEYS",
    "Check",
    "Conditional",
    "FieldDef",
    "FieldKind",
    "Pack",
    "ReportSpec",
    "UnitFamily",
    "get_pack",
]
