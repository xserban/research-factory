"""The module contract and its registries are pure declarations (slice M rulings 1, 5)."""

import ast
import dataclasses
from collections.abc import Iterable
from pathlib import Path

import pytest

from factory.model.screening import PassLabel
from factory.modules.contract import (
    CheckHit,
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    MethodsSection,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
    QualityRegime,
    StrategySpec,
)
from factory.modules.registry import ModuleRegistry, RegistryError, TaskKindRegistry

SRC = Path(__file__).parent.parent / "src" / "factory"
REGIME = QualityRegime(1, "none", "outcome", "none", "none")


class _Stub:
    """A module with no behaviour: only its declaration."""

    def __init__(self, spec: ModuleSpec) -> None:
        self.spec = spec

    def hits(self, project: object) -> list[CheckHit]:
        return []

    def methods(self, project: object) -> MethodsSection | None:
        return None

    def autonomy_acts(self, project: object) -> Iterable[object]:
        return ()


def _core(**kw: object) -> ModuleSpec:
    return ModuleSpec(name="core", kind=ModuleKind.CORE, **kw)  # type: ignore[arg-type]


def _registry(*specs: ModuleSpec, names: Iterable[str] = ()) -> ModuleRegistry:
    return ModuleRegistry([_Stub(s) for s in specs], catalog_names=names)  # type: ignore[list-item]


def test_module_spec_is_frozen() -> None:
    spec = _core()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.events.types = ("x.y",)  # type: ignore[misc]


def test_registry_rejects_duplicate_owner() -> None:
    a = ModuleSpec("a", ModuleKind.SCOPING, events=EventFamily(("x.one",)))
    b = ModuleSpec("b", ModuleKind.RETRIEVAL, events=EventFamily(("x.one",)))
    with pytest.raises(RegistryError) as e:
        _registry(_core(), a, b, names=["x.one"])
    message = "\n".join(e.value.problems)
    assert "x.one" in message and "a" in message and "b" in message


def test_registry_rejects_unknown_event() -> None:
    a = ModuleSpec("a", ModuleKind.SCOPING, events=EventFamily(("x.ghost",)))
    with pytest.raises(RegistryError) as e:
        _registry(_core(), a, names=["x.one"])
    assert any("x.ghost" in p for p in e.value.problems)
    assert any("x.one" in p for p in e.value.problems)  # and the catalog type nobody owns


def test_unowned_event_type_fails() -> None:
    a = ModuleSpec("a", ModuleKind.SCOPING, events=EventFamily(("x.one",)))
    with pytest.raises(RegistryError) as e:
        _registry(_core(), a, names=["x.one", "x.extra"])
    assert any("x.extra" in p and "no owner" in p for p in e.value.problems)


def test_registry_rejects_duplicate_names_and_two_cores() -> None:
    with pytest.raises(RegistryError):
        _registry(_core(), ModuleSpec("core", ModuleKind.SCOPING))
    with pytest.raises(RegistryError):
        _registry(_core(), ModuleSpec("other", ModuleKind.CORE))
    with pytest.raises(RegistryError):
        _registry(ModuleSpec("a", ModuleKind.SCOPING))  # no core


def test_registry_owns_each_kind_of_thing_once() -> None:
    gate = GateSpec("a.act", GateKind.DECISION, ("x.one",), PolicyKind.HUMAN, ("R-1",))
    a = ModuleSpec(
        "a",
        ModuleKind.SCOPING,
        events=EventFamily(("x.one",), tables=("t1",)),
        task_kinds=("k1",),
        protocol_sections=("s1",),
        gates=(gate,),
        checks=(CheckRule("c1", ("warning", None, "error")),),
    )
    reg = ModuleRegistry([_Stub(_core()), _Stub(a)], catalog_names=["x.one"], table_names=["t1"])  # type: ignore[list-item]
    assert reg.owner_of_event("x.one") == "a"
    assert reg.owner_of_table("t1") == "a"
    assert reg.owner_of_task_kind("k1") == "a"
    assert reg.owner_of_section("s1") == "a"
    assert reg.owner_of_check("c1") == "a"
    assert reg.gate("a.act") is gate
    assert reg.levels() == {"c1": ("warning", None, "error")}
    assert [m.spec.name for m in reg.modules()] == ["core", "a"]
    for clash in (
        ModuleSpec("b", ModuleKind.RETRIEVAL, task_kinds=("k1",)),
        ModuleSpec("b", ModuleKind.RETRIEVAL, protocol_sections=("s1",)),
        ModuleSpec("b", ModuleKind.RETRIEVAL, checks=(CheckRule("c1", (None, None, None)),)),
        ModuleSpec("b", ModuleKind.RETRIEVAL, events=EventFamily(tables=("t1",))),
        ModuleSpec(
            "b",
            ModuleKind.RETRIEVAL,
            gates=(GateSpec("a.act", GateKind.DECISION, ("x.one",), PolicyKind.HUMAN, ()),),
        ),
    ):
        with pytest.raises(RegistryError):
            ModuleRegistry(
                [_Stub(_core()), _Stub(a), _Stub(clash)],  # type: ignore[list-item]
                catalog_names=["x.one"],
                table_names=["t1"],
            )


def test_unowned_table_fails() -> None:
    with pytest.raises(RegistryError) as e:
        ModuleRegistry([_Stub(_core())], catalog_names=[], table_names=["orphan"])  # type: ignore[list-item]
    assert any("orphan" in p and "no owner" in p for p in e.value.problems)


def test_decision_gate_needs_act_events() -> None:
    with pytest.raises(ValueError, match="names no act event"):
        ModuleSpec(
            "a",
            ModuleKind.SCOPING,
            gates=(GateSpec("a.act", GateKind.DECISION, (), PolicyKind.HUMAN, ()),),
        )
    with pytest.raises(RegistryError):  # an act event the catalog does not know
        _registry(
            _core(),
            ModuleSpec(
                "a",
                ModuleKind.SCOPING,
                gates=(GateSpec("a.act", GateKind.DECISION, ("x.none",), PolicyKind.HUMAN, ()),),
            ),
        )


def test_builder_has_no_events_or_gates() -> None:
    gate = GateSpec("b.act", GateKind.DECISION, ("x.one",), PolicyKind.HUMAN, ())
    with pytest.raises(ValueError, match="no gate"):
        ModuleSpec("b", ModuleKind.BUILDER, gates=(gate,))
    with pytest.raises(ValueError, match="agent-written"):
        ModuleSpec("b", ModuleKind.BUILDER, events=EventFamily(("x.one",)))
    ModuleSpec("b", ModuleKind.BUILDER, events=EventFamily(("x.one",), system_only=True))


def test_miner_needs_regime() -> None:
    with pytest.raises(ValueError, match="regime"):
        ModuleSpec("m", ModuleKind.MINER)
    ModuleSpec("m", ModuleKind.MINER, regime=REGIME)


def test_strategy_spec_round_trips() -> None:
    assert StrategySpec("probe", "1", "rf-probe").skill == "rf-probe"


def test_task_kind_registry_round_trip() -> None:
    reg = TaskKindRegistry()
    reg.register("screen_a", "screening", stage="title-abstract", label=PassLabel.A, scope=None)
    reg.register("screen_b", "screening", stage="title-abstract", label=PassLabel.B, scope=None)
    reg.register("extract_a", "extraction", stage=None, label=PassLabel.A, scope="evidence")
    reg.register("intuition", "intuition", stage=None, label=None, scope=None)
    assert reg.kind_for("screening", stage="title-abstract", label=PassLabel.B) == "screen_b"
    assert reg.kind_for("extraction", label=PassLabel.A, scope="evidence") == "extract_a"
    info = reg.describe("screen_a")
    assert info is not None
    assert (info.module, info.stage, info.label, info.scope) == (
        "screening",
        "title-abstract",
        PassLabel.A,
        None,
    )
    assert reg.describe("nope") is None
    assert reg.kinds() == ("screen_a", "screen_b", "extract_a", "intuition")
    assert reg.kinds_of("screening") == ("screen_a", "screen_b")
    with pytest.raises(ValueError):
        reg.register("screen_a", "screening", stage="full-text", label=PassLabel.A, scope=None)
    with pytest.raises(ValueError):  # the same (module, stage, label, scope) under a second kind
        reg.register("screen_c", "screening", stage="title-abstract", label=PassLabel.A, scope=None)
    with pytest.raises(KeyError):
        reg.kind_for("screening", stage="full-text", label=PassLabel.A)


def _imports(path: Path) -> set[str]:
    """The modules `path` imports at run time (an `if TYPE_CHECKING:` block is not run)."""
    found: set[str] = set()
    tree = ast.parse(path.read_text())
    guarded = {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and getattr(node.test, "id", "") == "TYPE_CHECKING"
        for stmt in node.body
        for inner in ast.walk(stmt)
    }
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def test_modules_package_is_pure() -> None:
    forbidden = ("factory.services", "factory.index", "factory.mcp", "factory.cli")
    checked = 0
    for package in ("modules", "quality"):
        for path in (SRC / package).glob("*.py"):
            checked += 1
            for name in _imports(path):
                assert not name.startswith(forbidden), (path.name, name)
    assert checked >= 5
