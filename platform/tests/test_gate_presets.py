"""Presets reproduce the behaviour recorded at base (slice M, M-B Task 2)."""

import pytest

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.references import LinkState
from factory.modules.contract import GateKind, GatePolicy, PolicyKind
from factory.modules.presets import Enforcement, enforcement, preset, weaker
from factory.services.modules.default import default_modules
from factory.services.reference_resolve import confirmer_ruling

SESSION = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
MODES = tuple(RigorMode)
HUMAN = GatePolicy(PolicyKind.HUMAN)
AUDIT = GatePolicy(PolicyKind.AGENT_AUDIT, 0.1, 20)

# Recorded from the code at base: only the second-agent link confirmation of slice-3a ruling 3
# lets an agent pass a decision gate, and only in pilot.
AGENT = GatePolicy(PolicyKind.AGENT)
EXPECTED: dict[tuple[str, RigorMode], GatePolicy] = {
    ("hypotheses.lead_decide", RigorMode.EXPLORATORY): AGENT,
    ("hypotheses.register", RigorMode.EXPLORATORY): AGENT,
    ("experiments.freeze_unlock", RigorMode.EXPLORATORY): AGENT,
    ("reference.link_confirm", RigorMode.PILOT): AUDIT,
    ("import.resolution_confirm", RigorMode.PILOT): AUDIT,
    ("manuscript.citation_confirm", RigorMode.PILOT): AUDIT,
    # slice M, M-D: the one gate whose floor lets an exploratory project loosen it
    ("mine.resolve", RigorMode.EXPLORATORY): AUDIT,
    # slice 7b: the release gate (reconciliation table; the audit condition is the service's)
    ("writing.release", RigorMode.EXPLORATORY): AGENT,
    ("writing.release", RigorMode.PILOT): AGENT,
}
DECISION_GATES = sorted(g.gate_id for g in default_modules().gates() if g.kind is GateKind.DECISION)


@pytest.mark.parametrize("gate", DECISION_GATES)
@pytest.mark.parametrize("mode", MODES)
def test_preset_table_is_recorded_behaviour(gate: str, mode: RigorMode) -> None:
    assert preset(mode, gate) == EXPECTED.get((gate, mode), HUMAN)


@pytest.mark.parametrize("gate", DECISION_GATES)
@pytest.mark.parametrize("mode", MODES)
def test_no_preset_is_below_its_floor(gate: str, mode: RigorMode) -> None:
    floor = default_modules().gate(gate).floor
    assert not weaker(preset(mode, gate), GatePolicy(floor))


@pytest.mark.parametrize("gate", ["reference.link_confirm", "import.resolution_confirm"])
@pytest.mark.parametrize("kind", ["human", "agent"])
@pytest.mark.parametrize("mode", MODES)
def test_presets_reproduce_behaviour(gate: str, kind: str, mode: RigorMode) -> None:
    """The shared confirmer ruling (the one service that lets an agent pass a binding gate)
    accepts a seconding agent exactly where the preset says `agent_audit`."""
    actor = (
        Actor(kind="human", id="ana", user="ana", session=SESSION)
        if kind == "human"
        else Actor(
            kind="agent", id="a", user="ana", session=SESSION, model="m", skill="rf-x@1a2b3c4d"
        )
    )
    confirmed, issues = confirmer_ruling(
        actor,
        gate_id=gate,
        policy=preset(mode, gate),
        base_state=LinkState.UNCONFIRMED,
        confirmed_by=None,
        has_proposal=True,
        deciding_sessions=set(),
    )
    accepted = not issues
    expected = kind == "human" or mode is RigorMode.PILOT
    assert accepted is expected
    if accepted:
        assert confirmed == ("human" if kind == "human" else "second-agent")


def test_enforcement_matches_base() -> None:
    audit_gates = ("screening.audit_ceiling", "extraction.audit_ceiling", "gate.audit_ceiling")
    for gate in audit_gates:
        assert enforcement(RigorMode.EXPLORATORY, gate) is Enforcement.OFF
        assert enforcement(RigorMode.PILOT, gate) is Enforcement.ADVISORY
        assert enforcement(RigorMode.SYSTEMATIC, gate) is Enforcement.ENFORCED
    assert enforcement(RigorMode.EXPLORATORY, "protocol.ready") is Enforcement.OFF
    assert enforcement(RigorMode.PILOT, "protocol.ready") is Enforcement.ENFORCED
    assert enforcement(RigorMode.SYSTEMATIC, "protocol.ready") is Enforcement.ENFORCED
    sensitivity = "screening.calibration_sensitivity"
    assert enforcement(RigorMode.EXPLORATORY, sensitivity) is Enforcement.OFF
    assert enforcement(RigorMode.SYSTEMATIC, sensitivity) is Enforcement.ENFORCED


def test_weaker_order() -> None:
    agent = GatePolicy(PolicyKind.AGENT)
    assert weaker(agent, AUDIT) and weaker(AUDIT, HUMAN) and weaker(agent, HUMAN)
    assert not weaker(HUMAN, AUDIT) and not weaker(AUDIT, agent) and not weaker(agent, agent)
    assert not weaker(AUDIT, AUDIT)
    assert weaker(GatePolicy(PolicyKind.AGENT_AUDIT, 0.05, 20), AUDIT)
    assert weaker(GatePolicy(PolicyKind.AGENT_AUDIT, 0.1, 5), AUDIT)
    assert not weaker(GatePolicy(PolicyKind.AGENT_AUDIT, 0.2, 20), AUDIT)
    # incomparable parameters are not weaker either way
    mixed = GatePolicy(PolicyKind.AGENT_AUDIT, 0.05, 50)
    assert not weaker(mixed, AUDIT) and not weaker(AUDIT, mixed)


def test_tightened_gate_refusal_names_gate_and_policy_only() -> None:
    actor = Actor(
        kind="agent", id="a", user="ana", session=SESSION, model="m", skill="rf-x@1a2b3c4d"
    )
    _, issues = confirmer_ruling(
        actor,
        gate_id="reference.link_confirm",
        policy=HUMAN,
        base_state=LinkState.UNCONFIRMED,
        confirmed_by=None,
        has_proposal=True,
        deciding_sessions=set(),
    )
    assert [i.reason for i in issues] == [
        "gate reference.link_confirm is human: an agent may only propose"
    ]
