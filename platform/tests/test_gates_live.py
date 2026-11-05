"""Acts that no longer bind are not gate acts (M-B review, finding 2)."""

# ruff: noqa: F811
from factory.events.envelope import Actor
from factory.model.references import Decision
from factory.modules.contract import Autonomy, PolicyKind
from factory.services.context import Project
from factory.services.gates import autonomy_counts, below_policy, gate_acts
from tests.gate_helpers import amend_gate_policies, entry
from tests.references_service_helpers import second_agent
from tests.test_references_resolve import _decide, _reextract, extraction  # noqa: F401

LINK = "reference.link_confirm"


def test_reextracted_agent_confirmation_leaves_the_acts(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), extraction, 1, Decision.CONFIRM)
    assert len(list(gate_acts(project, LINK))) == 1
    _reextract(project, agent)
    assert list(gate_acts(project, LINK)) == []
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    assert below_policy(project) == []


def test_carried_human_decision_counts_once(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    _reextract(project, agent)
    assert autonomy_counts(project, LINK)[Autonomy.HUMAN] == 1
