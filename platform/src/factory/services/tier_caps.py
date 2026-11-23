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

from typing import Final, Literal

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.levels import Tier
from factory.services.context import Project
from factory.tiers.resolve import plan_for

SCREEN_CAP: Final = ("screen", "max_screened")
"""(stage, cap key): the works the title/abstract queue may serve."""
ACQUIRE_CAP: Final = ("acquire", "max_included")
"""(stage, cap key): the works full-text fetch may take on."""

ENFORCED_CAPS: Final = frozenset({SCREEN_CAP, ACQUIRE_CAP})
"""The (stage, key) caps the platform refuses past (the two above). Every other cap of a plan is
advisory: the stage's skill tells the agent to stay within it and nothing checks (finding I4)."""

CapEnforcement = Literal["enforced", "advisory"]


def cap_enforcement(stage: str, key: str) -> CapEnforcement:
    """`enforced` for a cap the platform refuses past, else `advisory`."""
    return "enforced" if (stage, key) in ENFORCED_CAPS else "advisory"


def cap_lines(tier: Tier | None) -> tuple[str, ...]:
    """One line per stage cap of the tier's plan, each marked enforced or advisory; empty for a
    tier with no caps (and for none)."""
    if tier is None or tier not in CAPPED_TIERS:
        return ()
    return tuple(
        f"cap {stage.stage_id} {key}: {value} ({cap_enforcement(stage.stage_id, key)})"
        for stage in plan_for(tier).stages
        if not stage.skipped
        for key, value in stage.caps.items()
    )


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
