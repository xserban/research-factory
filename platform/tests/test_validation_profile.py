"""The validation profile per tier and autonomy level (lane L11)."""

import itertools

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.levels import RIGOR_OF_TIER, AutonomyLevel, Tier
from factory.model.rigor import RigorMode
from factory.model.screening import PassLabel
from factory.modules.presets import ENFORCEMENT, Enforcement, enforcement
from factory.services import project as project_service
from factory.services.context import Project
from factory.services.level_statement import level_statement, render_level_statement
from factory.services.mining import mine_next
from factory.services.project import ProjectLevels, init_project
from factory.services.validation_profile import (
    enforcement_for,
    miner_use_refusal,
    project_validation_profile,
)
from factory.tiers.validation import validation_profile
from tests.extraction_helpers import ext_a, screened, world  # noqa: F401
from tests.helpers import SESSION
from tests.miner_helpers import SESSION_M1, VISION_NAME, list_miner, miner_actor

CHECKS = tuple(ENFORCEMENT[RigorMode.PILOT])
LEVELS = tuple(AutonomyLevel)


def _as(monkeypatch: pytest.MonkeyPatch, tier: Tier, level: AutonomyLevel) -> None:
    levels = ProjectLevels(tier=tier, autonomy_level=level, rigor_mode=RIGOR_OF_TIER[tier])
    monkeypatch.setattr(project_service, "project_levels", lambda _project: levels)


@pytest.mark.parametrize(("tier", "level"), list(itertools.product(Tier, LEVELS)))
def test_profile_table(tier: Tier, level: AutonomyLevel) -> None:
    p = validation_profile(tier, level)
    judged = level is not AutonomyLevel.ATTENDED
    assert p.tier is tier and p.autonomy_level is level
    assert p.admission == "human"  # no autonomous admission until the researcher rules
    assert p.independent_judge is judged
    if judged:
        assert p.calibration_required
    if tier is Tier.BRIEF:
        assert set(p.checks.values()) == {Enforcement.OFF}
        assert (p.miners_allowed, p.miner_passes_allowed) == ("claims-only", 1)
        assert p.second_pass_fraction is None and p.audit_fraction is None
        assert p.label == "exploratory, unvalidated"
    elif tier is Tier.DEEP:
        assert p.checks["protocol.ready"] is Enforcement.OFF
        assert {v for k, v in p.checks.items() if k != "protocol.ready"} == {Enforcement.ADVISORY}
        assert (p.miners_allowed, p.miner_passes_allowed) == ("all", 2)
        assert p.second_pass_fraction == 0.2 and p.audit_fraction == 0.1
        assert p.label == "exploratory, sample-validated"
    else:
        assert p.checks == ENFORCEMENT[RIGOR_OF_TIER[tier]]
        assert (p.miners_allowed, p.miner_passes_allowed) == ("all", 2)
        assert p.calibration_required


@pytest.mark.parametrize("mode", list(RigorMode))
def test_legacy_profile_is_the_mode_table(mode: RigorMode) -> None:
    p = validation_profile(None, AutonomyLevel.ATTENDED, mode=mode)
    assert p.checks == ENFORCEMENT[mode]
    with pytest.raises(ValueError):
        validation_profile(None, AutonomyLevel.ATTENDED)


@pytest.mark.parametrize(("mode", "check"), list(itertools.product(RigorMode, CHECKS)))
def test_enforcement_for_equals_enforcement_without_a_tier(
    project: Project, mode: RigorMode, check: str
) -> None:
    assert enforcement_for(project, check, mode=mode) is enforcement(mode, check)
    assert miner_use_refusal(project, evidence=False, pass_label="B") is None


def test_enforcement_for_reads_the_declared_tier(
    monkeypatch: pytest.MonkeyPatch, project: Project
) -> None:
    _as(monkeypatch, Tier.DEEP, AutonomyLevel.ATTENDED)
    assert enforcement_for(project, "screening.audit_ceiling") is Enforcement.ADVISORY
    assert project_validation_profile(project).label == "exploratory, sample-validated"
    _as(monkeypatch, Tier.SYSTEMATIC, AutonomyLevel.SUPERVISED)
    assert enforcement_for(project, "gate.audit_ceiling") is Enforcement.ENFORCED


def test_miners_allowed_filters_mine_next_for_a_brief(
    monkeypatch: pytest.MonkeyPatch,
    project: Project,
    agent: Actor,
    world: list[str],  # noqa: F811
) -> None:
    list_miner(project, agent)
    miner = miner_actor(SESSION_M1, "claude-opus-5-5")
    _as(monkeypatch, Tier.BRIEF, AutonomyLevel.ATTENDED)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, miner, VISION_NAME, 1, PassLabel.A)
    assert [i.field for i in raised.value.issues] == ["miners"]
    _as(monkeypatch, Tier.DEEP, AutonomyLevel.ATTENDED)
    with pytest.raises(FactoryValidationError) as later:  # past the profile: calibration is next
        mine_next(project, miner, VISION_NAME, 1, PassLabel.A)
    assert [i.field for i in later.value.issues] == ["calibration"]


def test_a_brief_with_no_audit_is_unvalidated(settings: Settings, clock: FixedClock) -> None:
    brief = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")
    text = render_level_statement(level_statement(brief, skipped=lambda _t: ()))
    assert "validation: exploratory, unvalidated" in text
    assert "audit: no sample drawn (unvalidated)" in text
    assert "passes that ran: screening none; extraction none" in text


def test_a_legacy_project_statement_has_no_validation_lines(
    settings: Settings, clock: FixedClock
) -> None:
    legacy = init_project(settings, "old", "pilot", session=SESSION, clock=clock)
    assert "validation:" not in render_level_statement(level_statement(legacy))
