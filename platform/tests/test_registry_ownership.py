"""Every event type, table, task kind, protocol section, check code and gate has one owner.

The tests read what exists (the catalog, the projection's tables, `ProtocolSpec`, the task-kind
registry), so a plan that adds any of them without declaring it in `services/modules/` fails
here. When a plan adds one, it adds its declaration to the module that owns it; this file does
not change. The assertions name the offender and where to declare it."""

import pytest

from factory.events.catalog import EventCatalog, EventType, default_catalog
from factory.index.default import default_projection
from factory.model.protocol import ProtocolSpec
from factory.modules.contract import GateKind, ModuleKind, PolicyKind
from factory.modules.registry import ModuleRegistry, RegistryError
from factory.services import check
from factory.services.modules import default_modules, default_task_kinds

HOW = "declare it in the services/modules/<module>.py that owns it"


def test_every_catalog_event_has_one_owner() -> None:
    reg = default_modules()
    names = default_catalog().names()
    assert names
    unowned = []
    for name in names:
        try:
            reg.owner_of_event(name)
        except KeyError:
            unowned.append(name)
    assert not unowned, f"event types with no owner: {unowned}; {HOW}"


def test_every_table_has_one_owner() -> None:
    reg = default_modules()
    tables = sorted(default_projection().metadata.tables)
    assert len(tables) > 100
    unowned = []
    for table in tables:
        try:
            reg.owner_of_table(table)
        except KeyError:
            unowned.append(table)
    assert not unowned, f"index tables with no owner: {unowned}; {HOW}"


def test_unowned_event_type_fails() -> None:
    from pydantic import BaseModel

    class Extra(BaseModel):
        pass

    catalog = default_catalog()
    catalog.register(EventType("zzz.extra", Extra, 1))
    with pytest.raises(RegistryError) as e:
        _rebuilt(catalog_names=catalog.names())
    assert any("zzz.extra" in p and "no owner" in p for p in e.value.problems)


def test_unowned_table_fails() -> None:
    tables = [*default_projection().metadata.tables, "zzz_extra"]
    with pytest.raises(RegistryError) as e:
        _rebuilt(table_names=tables)
    assert any("zzz_extra" in p and "no owner" in p for p in e.value.problems)


def _rebuilt(
    catalog_names: list[str] | None = None, table_names: list[str] | None = None
) -> ModuleRegistry:
    return ModuleRegistry(
        default_modules().modules(),
        catalog_names=catalog_names or default_catalog().names(),
        table_names=table_names or list(default_projection().metadata.tables),
    )


def test_no_event_or_table_has_two_owners() -> None:
    claimed: dict[str, str] = {}
    for module in default_modules().modules():
        for thing in (*module.spec.events.types, *module.spec.events.tables):
            assert thing not in claimed, f"{thing}: {claimed[thing]} and {module.spec.name}"
            claimed[thing] = module.spec.name


def test_every_protocol_section_has_one_owner() -> None:
    reg = default_modules()
    for section in ProtocolSpec.model_fields:
        try:
            reg.owner_of_section(section)
        except KeyError:
            pytest.fail(f"protocol section {section} has no owner; {HOW}")
    declared = {s for m in reg.modules() for s in m.spec.protocol_sections}
    assert declared <= set(ProtocolSpec.model_fields)


def test_every_check_code_has_one_owner() -> None:
    assert default_modules().levels() == check.LEVELS
    assert check.LEVELS


def test_every_task_kind_has_one_owner() -> None:
    reg = default_modules()
    kinds = default_task_kinds()
    for kind in kinds.kinds():
        info = kinds.describe(kind)
        assert info is not None
        assert reg.owner_of_task_kind(kind) == info.module, kind
    declared = {k for m in reg.modules() for k in m.spec.task_kinds}
    assert declared == set(kinds.kinds())


def test_gate_ids_unique_and_act_events_registered() -> None:
    reg = default_modules()
    names = set(default_catalog().names())
    ids = [g.gate_id for m in reg.modules() for g in m.spec.gates]
    assert len(ids) == len(set(ids)) > 10
    for gate in reg.gates():
        assert gate.kind is GateKind.DECISION
        assert gate.act_events and set(gate.act_events) <= names, gate.gate_id
        assert reg.gate(gate.gate_id) is gate


def test_gate_floors_reproduce_the_decided_entries() -> None:
    reg = default_modules()
    agent_audit = {g.gate_id for g in reg.gates() if g.floor is PolicyKind.AGENT_AUDIT}
    assert agent_audit == {
        "reference.link_confirm",
        "import.resolution_confirm",
        "manuscript.citation_confirm",
    }
    human = {g.gate_id for g in reg.gates() if g.floor is PolicyKind.HUMAN}
    for gate_id in (
        "protocol.press_confirm",
        "screening.calibration_label",
        "screening.resolve",
        "screening.audit_label",
        "extraction.resolve",
        "extraction.audit_label",
        "lineage.relation_confirm",
        "lineage.idea_confirm",
        "intuition.review",
        "living.notice_assess",
        "living.conclusion_register",
        "inbox.withdraw",
    ):
        assert gate_id in human, gate_id


def test_module_kinds_are_the_closed_list() -> None:
    reg = default_modules()
    assert {m.spec.kind for m in reg.modules()} <= set(ModuleKind)
    assert [m.spec.name for m in reg.modules() if m.spec.kind is ModuleKind.CORE] == ["core"]
    by_name = {m.spec.name: m.spec for m in reg.modules()}
    assert by_name["screening"].kind is ModuleKind.FILTER
    assert by_name["extraction"].kind is ModuleKind.MINER
    assert by_name["extraction"].events.note.startswith("historical name")
    assert by_name["evidence"].kind is ModuleKind.BUILDER
    assert by_name["references"].kind is ModuleKind.PROPOSAL
    assert by_name["contributions"].kind is ModuleKind.MINER
    assert by_name["contributions"].task_kinds == ("contrib_a", "contrib_b")


def test_the_catalog_helper_is_not_mutated_between_tests() -> None:
    assert "zzz.extra" not in EventCatalog().names()
    assert "zzz.extra" not in default_catalog().names()


def test_every_rule_code_in_check_py_is_declared() -> None:
    """A static scan of the rule source: each code a rule can emit is declared by a module."""
    import ast
    from pathlib import Path

    from factory.services import check as check_module

    tree = ast.parse(Path(check_module.__file__).read_text())
    emitted: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "_Hit"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            emitted.add(str(node.args[0].value))
    emitted |= set(check_module._IMPORT_COUNTS)
    assert len(emitted) > 50
    declared = default_modules().levels()
    undeclared = sorted(c for c in emitted if c not in declared)
    assert not undeclared, f"rule codes with no declaring module: {undeclared}; {HOW}"


def test_sample_extended_belongs_to_screening() -> None:
    assert default_modules().owner_of_event("screening.sample_extended") == "screening"
