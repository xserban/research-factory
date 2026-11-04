"""`stage_facts` on a project whose extraction schema is declared and not yet extracted."""

from dataclasses import replace

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.portfolio import Stage, derive_stage, stage_facts
from tests import test_extraction_agreement as ea
from tests.portfolio_helpers import fresh

# Re-export the fixtures under their own names so pytest finds them in this module.
ext_a = ea.ext_a
ext_b = ea.ext_b
screened = ea.screened
world = ea.world


def test_declared_schema_with_open_units_is_extraction(
    project: Project, world: list[str], settings: Settings, clock: FixedClock
) -> None:
    facts = stage_facts(fresh(settings, "demo", clock))
    # The fixture leaves one promoted work without a document, so full text is still open; with
    # that cleared the extraction row is the first to match.
    assert facts.extraction_schema and facts.extraction_open > 0 and facts.ft_open == 1
    assert derive_stage(facts) is Stage.FULL_TEXT
    assert derive_stage(replace(facts, ft_open=0)) is Stage.EXTRACTION


def test_agreed_extraction_leaves_no_open_unit(
    project: Project,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
    settings: Settings,
    clock: FixedClock,
) -> None:
    ea._both(project, ext_a, ext_b)
    facts = stage_facts(fresh(settings, "demo", clock))
    assert facts.extraction_open == 0
    assert derive_stage(replace(facts, ft_open=0)) is Stage.REPORTING
