"""Tier and autonomy level of a study (plan 2026-11-20-tiers-autonomy-programmes).

A *study* is a project; a *programme* groups studies (naming ruling 2026-11-14). Two independent
settings describe how a study is run:

- `Tier`: speed and depth, from a quick brief to a systematic review. It fixes the rigour mode
  (`RIGOR_OF_TIER`) and, in `factory.tiers`, the plan of stages, caps and templates.
- `AutonomyLevel`: who closes the decision gates. `attended`: a human, as today. `supervised`: an
  independent agent session closes the gates that allow it, and a sampled audit follows.
  `autonomous`: an orchestrated multi-agent run closes them, with independent verification, and the
  human reviews afterwards from a deferred queue. It is a project-level setting; the per-act
  `modules.contract.Autonomy` (human, audited-agent, agent) records who passed one act.

Invariants:
- Pure data. Neither setting changes what the platform may do on its own: the platform never calls a
  model, provenance and the held-out rule hold at every tier and level.
- A project without a tier is a legacy project: its tier is unknown and its autonomy level is
  `attended`. Neither value is written to an old log or hashed into its state.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from factory.model.project import RigorMode


class Tier(StrEnum):
    BRIEF = "brief"
    DEEP = "deep"
    PILOT = "pilot"
    SYSTEMATIC = "systematic"


class AutonomyLevel(StrEnum):
    ATTENDED = "attended"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


RIGOR_OF_TIER: Final[Mapping[Tier, RigorMode]] = {
    Tier.BRIEF: RigorMode.EXPLORATORY,
    Tier.DEEP: RigorMode.EXPLORATORY,
    Tier.PILOT: RigorMode.PILOT,
    Tier.SYSTEMATIC: RigorMode.SYSTEMATIC,
}
"""The rigour mode a tier runs under (decision 24 modes are unchanged)."""

__all__ = ["RIGOR_OF_TIER", "AutonomyLevel", "Tier"]
