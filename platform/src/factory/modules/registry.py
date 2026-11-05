"""The module registry and the task-kind registry (slice M ruling 1; decision 55).

`ModuleRegistry` validates ownership on construction: every event type of the catalog, every
index table, task kind, protocol section, check code and gate id belongs to exactly one module.
A violation raises `RegistryError` listing every problem found, not the first.

Invariants:
- Pure: the registry reads the declarations it is given and nothing else.
- Declaration order is kept; `modules()` returns it.
- `TaskKindRegistry` maps a kind string to one `(module, stage, label, scope)` and back; no two
  kinds share that tuple, so `kind_for` and `describe` are inverse.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from factory.model.screening import PassLabel
from factory.modules.contract import GateSpec, Levels, StageModule


class RegistryError(Exception):
    """The declarations do not partition what they must; `problems` lists each violation."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class ModuleRegistry:
    def __init__(
        self,
        modules: Sequence[StageModule],
        *,
        catalog_names: Iterable[str],
        table_names: Iterable[str] | None = None,
    ) -> None:
        self._modules = tuple(modules)
        catalog = set(catalog_names)
        problems: list[str] = []
        self._events = self._own(
            "event type", ((m.spec.name, m.spec.events.types) for m in self._modules), problems
        )
        self._tables = self._own(
            "table", ((m.spec.name, m.spec.events.tables) for m in self._modules), problems
        )
        self._task_kinds = self._own(
            "task kind", ((m.spec.name, m.spec.task_kinds) for m in self._modules), problems
        )
        self._sections = self._own(
            "protocol section",
            ((m.spec.name, m.spec.protocol_sections) for m in self._modules),
            problems,
        )
        self._checks = self._own(
            "check code",
            ((m.spec.name, tuple(c.code for c in m.spec.checks)) for m in self._modules),
            problems,
        )
        self._gates_owner = self._own(
            "gate id",
            ((m.spec.name, tuple(g.gate_id for g in m.spec.gates)) for m in self._modules),
            problems,
        )
        names = [m.spec.name for m in self._modules]
        for name in sorted({n for n in names if names.count(n) > 1}):
            problems.append(f"module name {name} is declared twice")
        cores = [m.spec.name for m in self._modules if m.spec.kind.value == "core"]
        if len(cores) != 1:
            problems.append(f"exactly one core module is required; found {cores or 'none'}")
        for event in sorted(set(self._events) - catalog):
            problems.append(f"{self._events[event]} owns {event}, which the catalog does not know")
        for event in sorted(catalog - set(self._events)):
            problems.append(f"event type {event} has no owner")
        if table_names is not None:
            tables = set(table_names)
            for table in sorted(set(self._tables) - tables):
                problems.append(f"{self._tables[table]} owns table {table}, which does not exist")
            for table in sorted(tables - set(self._tables)):
                problems.append(f"table {table} has no owner")
        self._gates = {g.gate_id: g for m in self._modules for g in m.spec.gates}
        for gate in self._gates.values():
            for act in gate.act_events:
                if act not in catalog:
                    problems.append(
                        f"gate {gate.gate_id} names act event {act}, not in the catalog"
                    )
        if problems:
            raise RegistryError(problems)

    @staticmethod
    def _own(
        noun: str, owned: Iterable[tuple[str, Iterable[str]]], problems: list[str]
    ) -> dict[str, str]:
        owner: dict[str, str] = {}
        for module, things in owned:
            for thing in things:
                if thing in owner and owner[thing] != module:
                    problems.append(f"{noun} {thing} is owned by both {owner[thing]} and {module}")
                elif thing in owner:
                    problems.append(f"{noun} {thing} is declared twice by {module}")
                else:
                    owner[thing] = module
        return owner

    def modules(self) -> tuple[StageModule, ...]:
        return self._modules

    def module(self, name: str) -> StageModule:
        return next(m for m in self._modules if m.spec.name == name)

    def owner_of_event(self, name: str) -> str:
        return self._events[name]

    def owner_of_table(self, name: str) -> str:
        return self._tables[name]

    def owner_of_task_kind(self, kind: str) -> str:
        return self._task_kinds[kind]

    def owner_of_section(self, section: str) -> str:
        return self._sections[section]

    def owner_of_check(self, code: str) -> str:
        return self._checks[code]

    def gate(self, gate_id: str) -> GateSpec:
        return self._gates[gate_id]

    def gates(self) -> tuple[GateSpec, ...]:
        return tuple(self._gates.values())

    def levels(self) -> dict[str, Levels]:
        """Every declared check code with its severities, in declaration order."""
        return {c.code: c.levels for m in self._modules for c in m.spec.checks}


@dataclass(frozen=True)
class TaskKindInfo:
    kind: str
    module: str
    stage: str | None
    label: PassLabel | None
    scope: str | None


class TaskKindRegistry:
    """Task kinds by `(module, stage, label, scope)`; kind strings are the persisted values."""

    def __init__(self) -> None:
        self._by_kind: dict[str, TaskKindInfo] = {}

    def register(
        self,
        kind: str,
        module: str,
        *,
        stage: str | None,
        label: PassLabel | None,
        scope: str | None,
    ) -> None:
        info = TaskKindInfo(kind, module, stage, label, scope)
        if kind in self._by_kind:
            raise ValueError(f"task kind {kind} is already registered")
        for other in self._by_kind.values():
            if (other.module, other.stage, other.label, other.scope) == (
                module,
                stage,
                label,
                scope,
            ):
                raise ValueError(f"{other.kind} already serves this pass; {kind} is a second")
        self._by_kind[kind] = info

    def kind_for(
        self,
        module: str,
        *,
        stage: str | None = None,
        label: PassLabel | None,
        scope: str | None = None,
    ) -> str:
        for info in self._by_kind.values():
            if (info.module, info.stage, info.label, info.scope) == (module, stage, label, scope):
                return info.kind
        raise KeyError((module, stage, label, scope))

    def describe(self, kind: str) -> TaskKindInfo | None:
        return self._by_kind.get(kind)

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._by_kind)

    def kinds_of(self, module: str) -> tuple[str, ...]:
        return tuple(k for k, i in self._by_kind.items() if i.module == module)
