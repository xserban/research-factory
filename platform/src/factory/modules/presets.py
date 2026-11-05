"""Rigor-mode presets for decision gates and enforcement of computed gates (slice M, M-B).

The presets reproduce the behaviour the services had before gate policies existed (slice-M gate
inventory). A protocol without `gate_policies` uses them; an entry in it replaces one.

Invariants:
- Pure data and comparisons; no registry, index or log is read here.
- Every decision gate not listed below is `human` in every mode: a gate gets another preset only
  by an entry in `PRESETS`.
- `weaker` is a strict order over policies: `agent` < `agent_audit` < `human`; between two
  `agent_audit` policies the smaller fraction or minimum is weaker, and incomparable
  parameters (one larger, one smaller) are not weaker either way.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from factory.model.project import RigorMode
from factory.modules.contract import GatePolicy, PolicyKind

HUMAN = GatePolicy(PolicyKind.HUMAN)
LINK_AUDIT = GatePolicy(PolicyKind.AGENT_AUDIT, 0.1, 20)
AGENT = GatePolicy(PolicyKind.AGENT)


class Enforcement(StrEnum):
    OFF = "off"
    ADVISORY = "advisory"
    ENFORCED = "enforced"


PRESETS: Mapping[RigorMode, Mapping[str, GatePolicy]] = {
    RigorMode.EXPLORATORY: {
        "hypotheses.lead_decide": AGENT,
        "hypotheses.register": AGENT,
        "experiments.freeze_unlock": AGENT,
        "mine.resolve": LINK_AUDIT,
    },
    RigorMode.PILOT: {
        "reference.link_confirm": LINK_AUDIT,
        "import.resolution_confirm": LINK_AUDIT,
    },
    RigorMode.SYSTEMATIC: {},
}
"""The gates whose preset is not `human`, per mode. Read through `preset`."""

ENFORCEMENT: Mapping[RigorMode, Mapping[str, Enforcement]] = {
    RigorMode.EXPLORATORY: {
        "protocol.ready": Enforcement.OFF,
        "screening.calibration_sensitivity": Enforcement.OFF,
        "screening.audit_ceiling": Enforcement.OFF,
        "extraction.audit_ceiling": Enforcement.OFF,
        "gate.audit_ceiling": Enforcement.OFF,
    },
    RigorMode.PILOT: {
        "protocol.ready": Enforcement.ENFORCED,
        "screening.calibration_sensitivity": Enforcement.ENFORCED,
        "screening.audit_ceiling": Enforcement.ADVISORY,
        "extraction.audit_ceiling": Enforcement.ADVISORY,
        "gate.audit_ceiling": Enforcement.ADVISORY,
    },
    RigorMode.SYSTEMATIC: {
        "protocol.ready": Enforcement.ENFORCED,
        "screening.calibration_sensitivity": Enforcement.ENFORCED,
        "screening.audit_ceiling": Enforcement.ENFORCED,
        "extraction.audit_ceiling": Enforcement.ENFORCED,
        "gate.audit_ceiling": Enforcement.ENFORCED,
    },
}
"""Enforcement of the computed gates. The thresholds stay platform constants (decision 37
item 4); only whether they bind is a function of the mode."""

_RANK = {PolicyKind.AGENT: 0, PolicyKind.AGENT_AUDIT: 1, PolicyKind.HUMAN: 2}


def preset(mode: RigorMode, gate_id: str) -> GatePolicy:
    return PRESETS[mode].get(gate_id, HUMAN)


def enforcement(mode: RigorMode, gate_id: str) -> Enforcement:
    return ENFORCEMENT[mode][gate_id]


def rank(kind: PolicyKind) -> int:
    return _RANK[kind]


def weaker(a: GatePolicy, b: GatePolicy) -> bool:
    """True when `a` lets agents do strictly more than `b` (see the module invariants)."""
    if a.kind is not b.kind:
        return rank(a.kind) < rank(b.kind)
    if a.kind is not PolicyKind.AGENT_AUDIT:
        return False
    fraction_a, fraction_b = a.fraction or 0.0, b.fraction or 0.0
    minimum_a, minimum_b = a.minimum or 0, b.minimum or 0
    return (
        fraction_a <= fraction_b
        and minimum_a <= minimum_b
        and (fraction_a, minimum_a) != (fraction_b, minimum_b)
    )
