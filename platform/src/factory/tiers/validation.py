"""The validation profile of a tier and autonomy level (plan tiers-and-autonomy, lane L11).

The profile sets what a run may CLAIM, not only how much work it does: which computed checks bind,
how many passes a miner may run, which miners may run, whether a calibration against a
human-labelled gold set and an independent judge are required, who admits a miner.

Invariants:
- Pure data and one lookup. For `pilot`, `systematic` and a legacy project (tier None) the checks
  are exactly `modules.presets.ENFORCEMENT` of the rigour mode, so their behaviour is unchanged
  whatever the autonomy level.
- `brief` and `deep` are exploratory: the label says so and says whether anything validated the
  output. A level of `supervised` or `autonomous` adds `independent_judge` (the validating session
  differs from the proposing session and the model) and `calibration_required` (without a
  human-labelled gold set the output is labelled unvalidated). Admission of a miner stays `human`
  at every level until the researcher rules otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from factory.model.base import StrictModel
from factory.model.levels import RIGOR_OF_TIER, AutonomyLevel, Tier
from factory.model.rigor import RigorMode
from factory.modules.presets import ENFORCEMENT, Enforcement

DEFAULT_SECOND_PASS_FRACTION: Final = 0.1
"""The sampled second pass of `deep` when the tier plan names no fraction."""

DEEP_AUDIT_FRACTION: Final = 0.1

_BINARY_CHECKS: Final = frozenset({"protocol.ready"})
"""Checks the consumers read as on or off (`protocol.ready` blocks a search unless OFF), so an
advisory level would bind them: `deep` keeps them OFF, as the exploratory mode has them."""

_EXPLORATORY = "exploratory, unvalidated"
_EXPLORATORY_SAMPLED = "exploratory, sample-validated"

MinersAllowed = Literal["all", "claims-only", "none"]
Admission = Literal["human", "audited-judge-after-ruling"]


class ValidationProfile(StrictModel):
    tier: Tier | None
    autonomy_level: AutonomyLevel
    checks: Mapping[str, Enforcement]
    miner_passes_allowed: Literal[1, 2]
    miners_allowed: MinersAllowed
    second_pass_fraction: float | None
    audit_fraction: float | None
    calibration_required: bool
    independent_judge: bool
    admission: Admission
    label: str


def _second_pass_fraction() -> float:
    from factory.tiers.resolve import plan_for

    template = plan_for(Tier.DEEP).protocol_template
    if template is not None and template.dual_extract_sample is not None:
        return template.dual_extract_sample
    return DEFAULT_SECOND_PASS_FRACTION


def validation_profile(
    tier: Tier | None, level: AutonomyLevel, *, mode: RigorMode | None = None
) -> ValidationProfile:
    """The profile of `tier` at `level`. A legacy project (`tier` None) needs its rigour `mode`:
    its checks are that mode's `ENFORCEMENT`, as before tiers existed."""
    if tier is None:
        if mode is None:
            raise ValueError("a project without a tier needs its rigour mode")
        rigor = mode
    else:
        rigor = RIGOR_OF_TIER[tier]
    checks: Mapping[str, Enforcement] = dict(ENFORCEMENT[rigor])
    judged = level is not AutonomyLevel.ATTENDED
    if tier is Tier.BRIEF:
        return ValidationProfile(
            tier=tier,
            autonomy_level=level,
            checks=checks,
            miner_passes_allowed=1,
            miners_allowed="claims-only",
            second_pass_fraction=None,
            audit_fraction=None,
            calibration_required=judged,
            independent_judge=judged,
            admission="human",
            label=_EXPLORATORY,
        )
    if tier is Tier.DEEP:
        return ValidationProfile(
            tier=tier,
            autonomy_level=level,
            checks={
                gate: (Enforcement.OFF if gate in _BINARY_CHECKS else Enforcement.ADVISORY)
                for gate in checks
            },
            miner_passes_allowed=2,
            miners_allowed="all",
            second_pass_fraction=_second_pass_fraction(),
            audit_fraction=DEEP_AUDIT_FRACTION,
            calibration_required=judged,
            independent_judge=judged,
            admission="human",
            label=_EXPLORATORY_SAMPLED,
        )
    label = {RigorMode.PILOT: "pilot", RigorMode.SYSTEMATIC: "systematic"}.get(rigor)
    return ValidationProfile(
        tier=tier,
        autonomy_level=level,
        checks=checks,
        miner_passes_allowed=2,
        miners_allowed="all",
        second_pass_fraction=None,
        audit_fraction=None,
        calibration_required=True if judged else rigor is not RigorMode.EXPLORATORY,
        independent_judge=judged,
        admission="human",
        label=label or "exploratory",
    )
