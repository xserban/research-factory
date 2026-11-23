"""Gate profiles of the autonomy levels (plan 2026-11-20-tiers-and-autonomy, contract C4).

The lowest policy a decision gate may take is a function of the project's rigor mode and
autonomy level. The project-reading `effective_policy` lives in `services/gates.py` (this package
imports nothing from services) and calls `resolve_policy` below.

Invariants:
- Pure data and comparisons; no registry, index or log is read here.
- `attended` has the empty profile: the policy is the protocol entry, else the rigor preset,
  exactly as before the levels existed.
- `supervised` lowers to `agent_audit` the gates whose preset allows `agent_audit` in some mode;
  it never lowers a gate to `agent`.
- `autonomous` adds `AUTONOMOUS_FLOOR`: the lowest policy of a gate under that level. A gate
  absent from it keeps its own floor, so shipping the table empty changes nothing (decision D3 of
  the plan is the researcher's). Floors change only by editing this data; a protocol never
  lowers a gate below its profile.
- Under a non-attended level a protocol entry weaker than the profile is clamped to the profile.
"""

from __future__ import annotations

from collections.abc import Mapping

from factory.model.levels import AutonomyLevel
from factory.model.project import RigorMode
from factory.modules.contract import GatePolicy
from factory.modules.presets import LINK_AUDIT, PRESETS, preset, weaker

AUTONOMOUS_FLOOR: Mapping[str, GatePolicy] = {}
"""Gate id to the lowest policy the gate may take under `autonomous`. Empty until the researcher
rules D3 (which gates may go below `human`, with which control)."""


def _supervised_gates() -> frozenset[str]:
    """The gates whose preset is `agent_audit` in some mode, computed from `PRESETS`."""
    return frozenset(
        gate
        for table in PRESETS.values()
        for gate, policy in table.items()
        if policy.kind is LINK_AUDIT.kind
    )


SUPERVISED_AUDIT_GATES: frozenset[str] = _supervised_gates()


def profile(level: AutonomyLevel, mode: RigorMode) -> Mapping[str, GatePolicy]:
    """The policies the level sets for `mode`, by gate; a gate not listed keeps its preset."""
    if level is AutonomyLevel.ATTENDED:
        return {}
    found: dict[str, GatePolicy] = {}
    for gate in SUPERVISED_AUDIT_GATES:
        base = preset(mode, gate)
        found[gate] = base if weaker(base, LINK_AUDIT) else LINK_AUDIT
    if level is AutonomyLevel.AUTONOMOUS:
        for gate, floor in AUTONOMOUS_FLOOR.items():
            base = found.get(gate, preset(mode, gate))
            found[gate] = floor if weaker(floor, base) else base
    return found


def lower_bound(level: AutonomyLevel, mode: RigorMode, gate_id: str) -> GatePolicy:
    """The weakest policy `gate_id` may take: the profile's, else the rigor preset's."""
    return profile(level, mode).get(gate_id, preset(mode, gate_id))


def resolve_policy(
    level: AutonomyLevel, mode: RigorMode, gate_id: str, entry: GatePolicy | None
) -> GatePolicy:
    """The policy in force: the protocol `entry` if any, else the profile/preset policy.

    `attended`: `entry` unchanged (today's rule). Otherwise an entry weaker than the lower bound
    is replaced by the bound, so no protocol goes below the profile."""
    if level is AutonomyLevel.ATTENDED:
        return preset(mode, gate_id) if entry is None else entry
    bound = lower_bound(level, mode, gate_id)
    if entry is None or weaker(entry, bound):
        return bound
    return entry
