"""Screening statistics: the pure quality statistics (re-exported) and screening's own constants.

Invariants:
- The statistics live in `factory.quality.stats`; every public name is re-exported unchanged.
- `quote_in` is deterministic and reads nothing but its arguments.
"""

from __future__ import annotations

from factory.model.project import RigorMode
from factory.quality.stats import (
    EXCLUSION_SHARE,
    AuditRates,
    Rates,
    audit_error_rates,
    audit_size,
    cohen_kappa,
    draw_audit,
    draw_uniform,
    kappa_by_criterion,
    sensitivity_specificity,
)

__all__ = [
    "AUDIT_ERROR_CEILING",
    "CALIBRATION_SENSITIVITY",
    "EXCLUSION_SHARE",
    "AuditRates",
    "Rates",
    "audit_error_rates",
    "audit_size",
    "cohen_kappa",
    "draw_audit",
    "draw_uniform",
    "kappa_by_criterion",
    "quote_in",
    "sensitivity_specificity",
]

AUDIT_ERROR_CEILING = 0.05
"""Audit false-exclusion rate above which `systematic` mode fails its gate (plan 5)."""

CALIBRATION_SENSITIVITY: dict[RigorMode, float | None] = {
    RigorMode.EXPLORATORY: None,
    RigorMode.PILOT: 0.9,
    RigorMode.SYSTEMATIC: 0.95,
}
"""Minimum calibration sensitivity per rigour mode; `None` means no calibration gate."""


def quote_in(quote: str, title: str, abstract: str | None) -> bool:
    """Whether `quote` occurs in the title or the abstract.

    Whitespace runs collapse to one space and ends are stripped on both sides; everything
    else, including case and punctuation, must match exactly. The quote is never matched
    across the title/abstract boundary. A quote blank after normalisation never matches.
    """
    needle = _normalise(quote)
    if not needle:
        return False
    if needle in _normalise(title):
        return True
    return abstract is not None and needle in _normalise(abstract)


def _normalise(text: str) -> str:
    return " ".join(text.split())
