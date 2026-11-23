"""Tier and autonomy level types (plan 2026-11-20-tiers-autonomy-programmes)."""

from __future__ import annotations

from factory.model.levels import RIGOR_OF_TIER, AutonomyLevel, Tier
from factory.model.project import RigorMode


def test_every_tier_has_a_rigour_mode() -> None:
    assert set(RIGOR_OF_TIER) == set(Tier)
    assert RIGOR_OF_TIER[Tier.BRIEF] is RigorMode.EXPLORATORY
    assert RIGOR_OF_TIER[Tier.DEEP] is RigorMode.EXPLORATORY
    assert RIGOR_OF_TIER[Tier.PILOT] is RigorMode.PILOT
    assert RIGOR_OF_TIER[Tier.SYSTEMATIC] is RigorMode.SYSTEMATIC


def test_the_values_are_the_names_used_in_the_plan() -> None:
    assert [t.value for t in Tier] == ["brief", "deep", "pilot", "systematic"]
    assert [a.value for a in AutonomyLevel] == ["attended", "supervised", "autonomous"]
