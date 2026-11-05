"""Tightening a gate flags earlier agent acts without staling anything (slice M, M-B Task 4)."""

# ruff: noqa: F811
import pytest

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.references import Decision
from factory.modules.contract import PolicyKind
from factory.services.check import LEVELS, _findings_as
from factory.services.context import Project
from factory.services.extraction import stale_extractions
from factory.services.gates import below_policy
from factory.services.screening import stale_screening_decisions
from tests.gate_helpers import amend_gate_policies, entry
from tests.references_service_helpers import second_agent
from tests.test_references_resolve import _decide, extraction  # noqa: F401

LINK = "reference.link_confirm"


def _confirm_as_second_agent(project: Project, rex: str, agent: Actor) -> None:
    _decide(project, agent, rex, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), rex, 1, Decision.CONFIRM)


def test_tightening_flags_without_staling(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _confirm_as_second_agent(project, extraction, agent)
    assert below_policy(project) == []
    stale_before = (stale_screening_decisions(project), stale_extractions(project))
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    flagged = below_policy(project)
    assert [(a.gate_id, a.actor_kind) for a in flagged] == [(LINK, "agent")]
    assert (stale_screening_decisions(project), stale_extractions(project)) == stale_before


def test_loosening_flags_nothing(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    amend_gate_policies(project, human, entry(LINK, PolicyKind.AGENT_AUDIT, 0.1, 20))
    assert below_policy(project) == []


def test_human_acts_are_never_below_policy(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    assert below_policy(project) == []


def test_agent_audit_gate_keeps_agent_acts_in_policy(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _confirm_as_second_agent(project, extraction, agent)
    amend_gate_policies(project, human, entry(LINK, PolicyKind.AGENT_AUDIT, 0.5, 50))
    assert below_policy(project) == []


@pytest.mark.parametrize(
    ("mode", "severity"),
    [
        (RigorMode.EXPLORATORY, "warning"),
        (RigorMode.PILOT, "warning"),
        (RigorMode.SYSTEMATIC, "error"),
    ],
)
def test_finding_severity_by_mode(
    project: Project,
    extraction: str,
    agent: Actor,
    human: Actor,
    mode: RigorMode,
    severity: str,
) -> None:
    assert LEVELS["gate-below-policy"] == ("warning", "warning", "error")
    _confirm_as_second_agent(project, extraction, agent)
    assert not [f for f in _findings_as(project, mode) if f.code == "gate-below-policy"]
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    [finding] = [f for f in _findings_as(project, mode) if f.code == "gate-below-policy"]
    assert finding.severity == severity
    assert len(finding.refs) == 1
    assert finding.message == (
        f"1 act(s) at gate {LINK} were passed by an agent before the policy became human"
    )
