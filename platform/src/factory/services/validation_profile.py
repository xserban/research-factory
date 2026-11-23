"""The project's validation profile and the entry points that consult it (lane L11).

Invariants:
- A project that declared no tier (a legacy project) gets `modules.presets.enforcement(mode, check)`
  unchanged; so does a `pilot` or `systematic` project, whose profile is that mode's table. Only
  `brief` and `deep` differ.
- Read-only: nothing is written; the tier and level come from the first `project.created` event.
- `project.py`, `audit.py` and the other consumers import this module, so it imports
  `project_levels` inside the functions, never at the top.
"""

from __future__ import annotations

from factory.model.rigor import RigorMode
from factory.modules.presets import Enforcement, enforcement
from factory.services.context import Project
from factory.tiers.validation import ValidationProfile, validation_profile


def project_validation_profile(
    project: Project, *, mode: RigorMode | None = None
) -> ValidationProfile:
    """The profile of `project`. `mode` is its rigour mode when the caller holds it; otherwise the
    index is read (only a legacy project needs it)."""
    from factory.services.project import project_levels  # services.project imports the consumers

    levels = project_levels(project)
    return validation_profile(levels.tier, levels.autonomy_level, mode=mode or levels.rigor_mode)


def enforcement_for(project: Project, check: str, *, mode: RigorMode | None = None) -> Enforcement:
    """Whether the computed gate `check` binds for `project`: the tier's profile when a tier is
    declared, else `enforcement(mode, check)` (the mode is read from the index when not given)."""
    from factory.services.project import project_levels

    levels = project_levels(project)
    if levels.tier is None:
        if mode is None:
            from factory.services.gates import indexed_rigor_mode

            mode = indexed_rigor_mode(project)
        return enforcement(mode, check)
    return validation_profile(levels.tier, levels.autonomy_level).checks[check]


def miner_use_refusal(
    project: Project, *, evidence: bool, pass_label: str | None = None
) -> str | None:
    """The reason the profile refuses a production pass of a miner use (`evidence`: the use is
    admitted as evidence), or None. `claims-only` admits only a use admitted as evidence; a profile
    of one pass refuses pass B."""
    from factory.services.project import project_levels

    levels = project_levels(project)
    if levels.tier is None:
        return None
    profile = validation_profile(levels.tier, levels.autonomy_level)
    if profile.miners_allowed == "none" or (
        profile.miners_allowed == "claims-only" and not evidence
    ):
        return (
            f"the {levels.tier.value} tier runs {profile.miners_allowed} miners only "
            f"(validation profile: {profile.label}); use a deeper tier for this miner"
        )
    if pass_label == "B" and profile.miner_passes_allowed < 2:
        return (
            f"the {levels.tier.value} tier runs one miner pass "
            f"(validation profile: {profile.label})"
        )
    return None
