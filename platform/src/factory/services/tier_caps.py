"""Tier caps as the platform enforces them (lane L14).

`tiers/plans.py` holds the caps of the `brief` and `deep` tiers per stage as data; the skills tell
the agent to stop, and this module makes the platform stop it.

Invariants:
- Only a project that declared the tier `brief` or `deep` is capped. A legacy project (no tier),
  `pilot` and `systematic` have no cap, so their behaviour is unchanged.
- The cap is read from the plan (`StagePlan.caps`), never typed here: `SCREEN_CAP` and
  `ACQUIRE_CAP` only name the keys.
- A refusal is a `FactoryValidationError` on field `tier` whose reason starts `tier-cap-reached`
  and names the cap; nothing is written.
"""

from __future__ import annotations

from typing import Final

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.levels import Tier
from factory.services.context import Project
from factory.tiers.resolve import plan_for

SCREEN_CAP: Final = ("screen", "max_screened")
"""(stage, cap key): the works the title/abstract queue may serve."""
ACQUIRE_CAP: Final = ("acquire", "max_included")
"""(stage, cap key): the works full-text fetch may take on."""

CAPPED_TIERS: Final = frozenset({Tier.BRIEF, Tier.DEEP})


def tier_cap(project: Project, which: tuple[str, str]) -> int | None:
    """The cap `which` (stage, key) of the project's tier plan, or None when the project is
    uncapped (no tier, pilot, systematic) or its plan sets no such cap."""
    from factory.services.project import project_levels  # lazy: project imports screening

    tier = project_levels(project).tier
    if tier is None or tier not in CAPPED_TIERS:
        return None
    stage, key = which
    return plan_for(tier).stage(stage).caps.get(key)


def cap_refusal(which: tuple[str, str], cap: int, what: str) -> FactoryValidationError:
    stage, key = which
    return FactoryValidationError(
        [
            ValidationIssue(
                "tier",
                f"tier-cap-reached: the tier plan caps {what} at {cap} ({stage} cap {key})",
            )
        ]
    )
