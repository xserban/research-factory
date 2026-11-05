"""The rows of `factory modules`: each declared module, computed from its declaration.

Invariants:
- Read-only; every figure is read from the registry (R-05), nothing is typed here.
- Rows follow declaration order, so the output is stable.
"""

from factory.model.base import StrictModel
from factory.services.modules import default_modules


class GateRow(StrictModel):
    gate_id: str
    floor: str
    act_events: list[str]


class ModuleRow(StrictModel):
    name: str
    kind: str
    events: int
    tables: int
    task_kinds: list[str]
    sections: list[str]
    gates: list[GateRow]
    checks: list[str]
    strategies: list[str]
    note: str | None


def module_rows() -> list[ModuleRow]:
    """One row per declared module, in declaration order."""
    rows: list[ModuleRow] = []
    for module in default_modules().modules():
        spec = module.spec
        rows.append(
            ModuleRow(
                name=spec.name,
                kind=spec.kind.value,
                events=len(spec.events.types),
                tables=len(spec.events.tables),
                task_kinds=list(spec.task_kinds),
                sections=list(spec.protocol_sections),
                gates=[
                    GateRow(gate_id=g.gate_id, floor=g.floor.value, act_events=list(g.act_events))
                    for g in spec.gates
                ],
                checks=[c.code for c in spec.checks],
                strategies=[
                    f"{s.name} {s.version}" + ("" if s.skill is None else f" ({s.skill})")
                    for s in spec.strategies
                ],
                note=spec.events.note or None,
            )
        )
    return rows
