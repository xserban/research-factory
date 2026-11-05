"""Coverage rests on import resolutions, so it carries the autonomy counts (M-B review, 5)."""

# ruff: noqa: F811
from factory.events.envelope import Actor
from factory.model.references import Decision
from factory.services.context import Project
from factory.services.coverage import agent_coverage, coverage_report
from factory.services.import_resolve import decide_import
from tests.references_service_helpers import second_agent
from tests.test_import_confirm import WHY, imported  # noqa: F401


def test_no_counts_while_every_decision_is_human(
    project: Project, imported: str, human: Actor
) -> None:
    assert coverage_report(project, imported).autonomy == {}
    decide_import(project, human, imported, 1, Decision.CONFIRM, rationale=WHY)
    assert coverage_report(project, imported).autonomy == {}


def test_counts_per_level_once_an_agent_passed_a_gate(
    project: Project, imported: str, agent: Actor, human: Actor
) -> None:
    decide_import(project, agent, imported, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    decide_import(project, second_agent(agent), imported, 1, Decision.CONFIRM, rationale=WHY)
    expected = {"human": 0, "audited-agent": 0, "agent": 1}
    assert coverage_report(project, imported).autonomy == expected
    assert agent_coverage(project, imported).autonomy == expected
