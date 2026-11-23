"""Tier and autonomy level at init (plan tiers-and-autonomy, C2)."""

import json

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.model.levels import RIGOR_OF_TIER, AutonomyLevel, Tier
from factory.model.project import ProjectCreated, RigorMode
from factory.services.project import init_project, project_levels, project_status
from tests.helpers import SESSION


def test_defaults_are_left_out_of_the_event_payload() -> None:
    payload = ProjectCreated(slug="demo", rigor_mode=RigorMode.PILOT).model_dump(mode="json")
    assert payload == {"slug": "demo", "rigor_mode": "pilot"}


def test_set_values_are_written() -> None:
    payload = ProjectCreated(
        slug="demo",
        rigor_mode=RigorMode.EXPLORATORY,
        tier=Tier.BRIEF,
        autonomy_level=AutonomyLevel.SUPERVISED,
    ).model_dump(mode="json")
    assert payload["tier"] == "brief"
    assert payload["autonomy_level"] == "supervised"


def test_legacy_project_has_no_tier_and_is_attended(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    levels = project_levels(project)
    assert (levels.tier, levels.autonomy_level, levels.rigor_mode) == (
        None,
        AutonomyLevel.ATTENDED,
        RigorMode.PILOT,
    )
    lines = [json.loads(x) for f in project.paths.events_dir.rglob("*.jsonl") for x in f.open()]
    assert lines[0]["payload"] == {"slug": "demo", "rigor_mode": "pilot"}


@pytest.mark.parametrize("tier", list(Tier))
def test_tier_fixes_the_mode(settings: Settings, clock: FixedClock, tier: Tier) -> None:
    project = init_project(
        settings,
        "demo",
        None,
        session=SESSION,
        clock=clock,
        tier=tier.value,
        autonomy_level="autonomous",
    )
    levels = project_levels(project)
    assert levels.tier is tier
    assert levels.rigor_mode is RIGOR_OF_TIER[tier]
    assert levels.autonomy_level is AutonomyLevel.AUTONOMOUS
    status = project_status(project)
    assert (status.tier, status.autonomy_level) == (tier, AutonomyLevel.AUTONOMOUS)
    assert status.rigor_mode is RIGOR_OF_TIER[tier]


def test_agreeing_mode_is_accepted(settings: Settings, clock: FixedClock) -> None:
    project = init_project(
        settings, "demo", "exploratory", session=SESSION, clock=clock, tier="deep"
    )
    assert project_levels(project).rigor_mode is RigorMode.EXPLORATORY


def test_disagreeing_mode_is_refused_and_writes_nothing(
    settings: Settings, clock: FixedClock
) -> None:
    with pytest.raises(FactoryValidationError) as err:
        init_project(settings, "demo", "pilot", session=SESSION, clock=clock, tier="brief")
    assert [i.field for i in err.value.issues] == ["rigor_mode"]
    assert not (settings.root / "projects").exists()


@pytest.mark.parametrize(
    ("tier", "level", "field"),
    [("fast", None, "tier"), (None, "free", "autonomy_level")],
)
def test_unknown_values_are_refused(
    settings: Settings, clock: FixedClock, tier: str | None, level: str | None, field: str
) -> None:
    with pytest.raises(FactoryValidationError) as err:
        init_project(
            settings,
            "demo",
            None,
            session=SESSION,
            clock=clock,
            tier=tier,
            autonomy_level=level,
        )
    assert [i.field for i in err.value.issues] == [field]
    assert not (settings.root / "projects").exists()


def test_rebuild_keeps_the_levels(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")
    first = project.index.rebuild()
    assert project.index.rebuild() == first
    assert project_levels(project).tier is Tier.BRIEF
