"""Effective policy, `require_gate`, acts and autonomy (slice M, M-B Task 3)."""

# ruff: noqa: F811

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.references import Decision
from factory.model.screening import Channel, PassJoined, PassLabel
from factory.modules.contract import Autonomy, GateKind, PolicyKind
from factory.services.context import Project
from factory.services.gates import (
    autonomy_counts,
    autonomy_of,
    effective_policy,
    gate_acts,
    gate_issues,
    protocol_at,
    require_gate,
)
from factory.services.modules.default import default_modules
from tests.gate_helpers import amend_gate_policies, entry
from tests.references_service_helpers import second_agent
from tests.test_references_resolve import _decide, extraction  # noqa: F401

LINK = "reference.link_confirm"
HUMAN_GATES = sorted(
    g.gate_id
    for g in default_modules().gates()
    if g.kind is GateKind.DECISION and g.floor is PolicyKind.HUMAN
)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


@pytest.mark.parametrize("gate", HUMAN_GATES)
def test_require_gate_refuses_agent_at_human_gate(
    project: Project, human: Actor, agent: Actor, gate: str
) -> None:
    before = _count(project)
    with pytest.raises(FactoryValidationError) as err:
        require_gate(project, agent, gate)
    [issue] = err.value.issues
    assert issue.field == "actor"
    assert issue.reason == f"gate {gate} is human: an agent cannot pass it"
    assert _count(project) == before
    assert require_gate(project, human, gate).kind is PolicyKind.HUMAN


def test_refusal_names_neither_rate_nor_label(project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        require_gate(project, agent, "screening.resolve")
    text = str(err.value)
    assert "0." not in text and "ceiling" not in text and "fraction" not in text


def test_pilot_second_agent_link_confirm_still_allowed(project: Project, agent: Actor) -> None:
    assert require_gate(project, agent, LINK).kind is PolicyKind.AGENT_AUDIT
    assert effective_policy(project, LINK).fraction == 0.1


def test_exploratory_link_confirm_is_human(explore_project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError):
        require_gate(explore_project, agent, LINK)


def test_proposer_cannot_pass(project: Project, human: Actor, agent: Actor) -> None:
    [issue] = gate_issues(project, agent, LINK, proposer_session=agent.session)
    assert (issue.field, issue.reason) == ("session", f"the proposer cannot pass gate {LINK}")
    assert gate_issues(project, human, "screening.resolve", proposer_session="x" * 26) == []


def test_relay_from_pass_session_refused(
    project: Project, human: Actor, agent_other: Actor, extraction: str
) -> None:
    joined = PassJoined(pass_label=PassLabel.A, session=agent_other.session, model="m")
    blob = project.blobs.put_json({"pass_label": "A"})
    project.record(
        [project.events.make("screening.pass_joined", joined, agent_other, input_blob=blob)]
    )
    relayed = human.model_copy(update={"session": agent_other.session})
    [issue] = gate_issues(project, relayed, "screening.resolve", channel=Channel.MCP)
    assert issue.field == "channel"
    assert gate_issues(project, relayed, "screening.resolve", channel=Channel.CLI) == []


def test_effective_policy_follows_amendment(
    project: Project,
    extraction: str,
    agent: Actor,
    human: Actor,
) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    assert effective_policy(project, LINK).kind is PolicyKind.HUMAN
    with pytest.raises(FactoryValidationError):
        require_gate(project, second_agent(agent), LINK)
    with pytest.raises(FactoryValidationError):
        _decide(project, second_agent(agent), extraction, 1, Decision.CONFIRM)


def test_policy_of_act_is_policy_at_its_time(
    project: Project,
    extraction: str,
    agent: Actor,
    human: Actor,
) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), extraction, 1, Decision.CONFIRM)
    [before] = list(gate_acts(project, LINK))
    new = amend_gate_policies(project, human, entry(LINK, PolicyKind.HUMAN))
    [after] = list(gate_acts(project, LINK))
    assert after.event_id == before.event_id
    assert after.protocol_id == before.protocol_id != new
    assert protocol_at(project, after.event_id) == after.protocol_id
    assert effective_policy(project, LINK, protocol_id=after.protocol_id).kind is (
        PolicyKind.AGENT_AUDIT
    )
    assert effective_policy(project, LINK).kind is PolicyKind.HUMAN
    assert autonomy_of(project, after) is Autonomy.AGENT


def test_autonomy_human_after_agent_proposal(
    project: Project,
    extraction: str,
    agent: Actor,
    human: Actor,
) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    assert list(gate_acts(project, LINK)) == []  # a proposal is not a binding act
    _decide(project, human, extraction, 1, Decision.CONFIRM)
    [act] = list(gate_acts(project, LINK))
    assert (act.actor_kind, autonomy_of(project, act)) == ("human", Autonomy.HUMAN)


def test_autonomy_counts_per_gate(
    project: Project,
    extraction: str,
    agent: Actor,
    human: Actor,
) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), extraction, 1, Decision.CONFIRM)
    counts = autonomy_counts(project, LINK)
    assert counts == {Autonomy.HUMAN: 0, Autonomy.AUDITED_AGENT: 0, Autonomy.AGENT: 1}
    assert sum(autonomy_counts(project, "screening.resolve").values()) == 0
