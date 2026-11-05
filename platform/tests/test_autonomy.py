"""Autonomy labels on read: the module hook and the weakest-of-basis rule (ruling 10)."""

# ruff: noqa: F811
from factory.events.envelope import Actor
from factory.model.references import Decision
from factory.modules.contract import Autonomy
from factory.services.context import Project
from factory.services.gates import weakest
from factory.services.modules.default import default_modules
from tests.references_service_helpers import second_agent
from tests.test_references_resolve import _decide, extraction  # noqa: F401


def test_module_hook_yields_acts_of_its_gates(
    project: Project, extraction: str, agent: Actor, human: Actor
) -> None:
    _decide(project, agent, extraction, 1, Decision.PROPOSE_CONFIRM)
    _decide(project, second_agent(agent), extraction, 1, Decision.CONFIRM)
    acts = list(default_modules().module("references").autonomy_acts(project))
    [act] = acts
    assert (act.gate_id, act.actor_kind) == ("reference.link_confirm", "agent")
    assert act.protocol_id is not None
    screening = default_modules().module("screening")
    assert {a.gate_id for a in screening.autonomy_acts(project)} <= {
        g.gate_id for g in screening.spec.gates
    }


def test_weakest_autonomy_of_a_basis() -> None:
    assert weakest([Autonomy.HUMAN, Autonomy.AGENT]) is Autonomy.AGENT
    assert weakest([Autonomy.HUMAN, Autonomy.AUDITED_AGENT]) is Autonomy.AUDITED_AGENT
    assert weakest([]) is Autonomy.HUMAN
