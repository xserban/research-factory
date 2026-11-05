"""The `gate_policies` protocol section: hashing, floors, preset rules (slice M, M-B Task 1)."""

import pytest
from pydantic import ValidationError

from factory.model.gates import GatePolicies, GatePolicyEntry
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolSpec, protocol_version
from factory.modules.contract import PolicyKind
from factory.services.protocol_rules import other_changes
from tests.test_protocol_model import _spec as model_spec
from tests.test_protocol_rules import _check, _fields, _spec


def _entry(gate: str, policy: PolicyKind, **kw: object) -> GatePolicyEntry:
    return GatePolicyEntry.model_validate({"gate": gate, "policy": policy, **kw})


def _audit(
    gate: str = "reference.link_confirm", fraction: float = 0.1, minimum: int = 20
) -> GatePolicyEntry:
    return _entry(gate, PolicyKind.AGENT_AUDIT, fraction=fraction, minimum=minimum)


def _with(*entries: GatePolicyEntry) -> ProtocolSpec:
    return _spec(gate_policies=GatePolicies(entries=entries))


def test_p_id_unchanged_without_gate_policies() -> None:
    assert protocol_version(model_spec()) == "P@ac674dc2"
    assert protocol_version(model_spec(gate_policies=None)) == "P@ac674dc2"


def test_entry_order_does_not_change_p_id() -> None:
    a = _entry("screening.resolve", PolicyKind.HUMAN)
    b = _entry("reference.link_confirm", PolicyKind.HUMAN)
    one = model_spec(gate_policies=GatePolicies(entries=(a, b)))
    two = model_spec(gate_policies=GatePolicies(entries=(b, a)))
    assert protocol_version(one) == protocol_version(two)
    assert protocol_version(one) != "P@ac674dc2"


def test_agent_audit_needs_fraction_and_minimum() -> None:
    with pytest.raises(ValidationError):
        _entry("reference.link_confirm", PolicyKind.AGENT_AUDIT)
    with pytest.raises(ValidationError):
        _entry("reference.link_confirm", PolicyKind.AGENT_AUDIT, fraction=0.1)
    with pytest.raises(ValidationError):
        _entry("reference.link_confirm", PolicyKind.HUMAN, fraction=0.1, minimum=20)
    with pytest.raises(ValidationError):
        _entry("reference.link_confirm", PolicyKind.AGENT_AUDIT, fraction=0.0, minimum=20)
    with pytest.raises(ValidationError):
        GatePolicies(entries=(_entry("a.b", PolicyKind.HUMAN), _entry("a.b", PolicyKind.HUMAN)))


def test_unknown_gate_refused() -> None:
    check = _check(_with(_entry("nothing.here", PolicyKind.HUMAN)))
    assert "gate_policies.entries.0.gate" in _fields(check.errors)
    assert check.errors[0].reason == "unknown gate"
    # a computed gate is not a decision gate
    check = _check(_with(_entry("protocol.ready", PolicyKind.HUMAN)))
    assert "gate_policies.entries.0.gate" in _fields(check.errors)


def test_below_floor_refused() -> None:
    check = _check(_with(_entry("screening.resolve", PolicyKind.AGENT)), RigorMode.EXPLORATORY)
    assert _fields(check.errors) == ["gate_policies.entries.0.policy"]
    assert check.errors[0].reason == "below the floor of screening.resolve"
    # an agent_audit gate accepts agent_audit but not agent
    ok = _check(_with(_audit()), RigorMode.EXPLORATORY)
    assert ok.errors == []
    bad = _check(_with(_entry("reference.link_confirm", PolicyKind.AGENT)), RigorMode.EXPLORATORY)
    assert _fields(bad.errors) == ["gate_policies.entries.0.policy"]


def test_weaker_than_preset_by_mode() -> None:
    weak = _with(_audit(fraction=0.05, minimum=5))
    systematic = _check(weak, RigorMode.SYSTEMATIC)
    assert "gate_policies.entries.0.policy" in _fields(systematic.errors)
    pilot = _check(weak, RigorMode.PILOT)
    assert "gate_policies.entries.0.policy" not in _fields(pilot.errors)
    assert "gate_policies.entries.0.policy" in _fields(pilot.gaps)
    exploratory = _check(weak, RigorMode.EXPLORATORY)
    assert exploratory.errors == []
    assert "gate_policies.entries.0.policy" not in _fields(exploratory.gaps)
    # equal to the pilot preset is not weaker
    same = _check(_with(_audit()), RigorMode.PILOT)
    assert "gate_policies.entries.0.policy" not in _fields(same.gaps)
    # human is never weaker than a preset
    human = _check(_with(_entry("reference.link_confirm", PolicyKind.HUMAN)), RigorMode.PILOT)
    assert "gate_policies.entries.0.policy" not in _fields(human.gaps)


def test_amendment_reports_gate_policies_in_other_changes() -> None:
    old = _spec()
    new = _with(_entry("reference.link_confirm", PolicyKind.HUMAN))
    assert other_changes(old, new) == ["gate_policies"]
    assert other_changes(new, new) == []
