"""The default `StageModule` binding: a declaration and the check rules it owns.

A module's `hits` are the findings of the rules that carry its codes. The rules themselves stay
in `services/check.py`, grouped in the order `check` reports them; this class selects the hits
whose code the module declares. `autonomy_acts` lists the acts at the module's decision gates
(services/gates.py); `methods` is empty until the methods plan gives a module something to say.

Invariants:
- `hits` never invents a hit: it returns exactly the rule results whose code is in `spec.checks`,
  in report order (`CheckHit.seq`).
- A module that declares no check code returns no hit without running a rule.
"""

from collections.abc import Iterable

from factory.modules.contract import (
    AutonomyAct,
    CheckHit,
    GateKind,
    MethodsSection,
    ModuleSpec,
)
from factory.services.context import Project


class RuleModule:
    def __init__(self, spec: ModuleSpec) -> None:
        self.spec = spec
        self._codes = frozenset(rule.code for rule in spec.checks)

    def hits(self, project: Project) -> list[CheckHit]:
        if not self._codes:
            return []
        from factory.services.check import segment_hits  # check imports the registry

        return [hit for hit in segment_hits(project) if hit.code in self._codes]

    def methods(self, project: Project) -> MethodsSection | None:
        return None

    def autonomy_acts(self, project: Project) -> Iterable[AutonomyAct]:
        from factory.services.gates import as_autonomy_acts  # gates imports the registry

        decision = tuple(g.gate_id for g in self.spec.gates if g.kind is GateKind.DECISION)
        return as_autonomy_acts(project, decision)
