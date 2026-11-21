"""Look up a tier's plan and compute what it skips compared with `systematic`.

`skipped_steps` is computed from the plan data (never typed twice): a stage that is skipped or
capped differs from `systematic`'s uncapped stage of the same id.
"""

from __future__ import annotations

from factory.model.levels import Tier
from factory.tiers.model import StagePlan, TierPlan
from factory.tiers.plans import PLANS


def plan_for(tier: Tier) -> TierPlan:
    return PLANS[tier]


def _differences(stage: StagePlan, reference: StagePlan) -> list[str]:
    if stage.skipped and not reference.skipped:
        return [f"{stage.label}: skipped"]
    out: list[str] = []
    for key, value in stage.caps.items():
        if reference.caps.get(key) == value:
            continue
        label = key.replace("_", " ")
        if value == 0:
            out.append(f"{stage.label}: no {label}")
        elif key.endswith("_only"):
            out.append(f"{stage.label}: {label}")
        else:
            out.append(f"{stage.label}: {label} capped at {value}")
    return out


def skipped_steps(tier: Tier) -> tuple[str, ...]:
    """What `tier` leaves out or caps compared with `systematic`, one line each, in stage order.
    Empty for `systematic` and `pilot`."""
    reference = PLANS[Tier.SYSTEMATIC]
    out: list[str] = []
    for stage in PLANS[tier].stages:
        out.extend(_differences(stage, reference.stage(stage.stage_id, stage.phase)))
    return tuple(out)


def report_label(tier: Tier) -> str:
    """The label a report of `tier` carries, for example 'quick review, skipped: ...'; '' when the
    tier has none."""
    label = PLANS[tier].report_template.label
    if not label:
        return ""
    return f"{label}, skipped: {'; '.join(skipped_steps(tier))}"
