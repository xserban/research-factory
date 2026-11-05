"""The intuition layer never reaches an evidence output (slice 3c, plan G3-A, task 6).

An AST scan fails on any import of a layer module outside the allowed importers, on a layer table
named outside the layer and its named readers, and on a layer module naming a G2 graph table. A
differential test builds the same world with and without a populated layer and requires every
evidence output to be byte-identical (acceptance 8; R-xx(h)).
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory.services import contributions as contributions_service
from factory.services.context import Project
from factory.services.contributions import ItemView
from tests.intuition_helpers import (
    IWorld,
    ctr_a,
    ctr_b,
    evidenced,
    ext_a,
    ext_b,
    iw,
    iwe,
    lin,
    screened,
    world,
)
from tests.intuition_separation import (
    ALLOWED_IMPORTERS,
    G2_TABLES,
    LAYER_MODULES,
    LAYER_TABLES,
    TABLE_READERS,
    evidence_outputs,
    imports_of,
    layer_event_count,
    modules_with_string_literals,
    package_dirs,
    package_modules,
    twin_projects,
)

TRACE_IDEAS_ARE_NODES = False
"""True once `trace` resolves idea ids (commit 422b0c0, not on this branch's base)."""


def test_no_evidence_module_imports_the_layer() -> None:
    """Acceptance 8."""
    modules = package_modules()
    offenders = sorted(
        (importer, imported)
        for importer, imported in imports_of(modules, packages=package_dirs())
        if imported in LAYER_MODULES and importer not in ALLOWED_IMPORTERS | LAYER_MODULES
    )
    assert offenders == []


def test_the_layer_modules_exist_where_the_scan_looks() -> None:
    modules = package_modules()
    present = LAYER_MODULES & set(modules)
    assert {
        "factory.model.intuition",
        "factory.intuition.validate",
        "factory.intuition.labels",
        "factory.index.intuition",
        "factory.services.intuition_sources",
        "factory.services.interpretations",
    } <= present


def test_no_sql_outside_layer_names_layer_tables() -> None:
    named = modules_with_string_literals(package_modules(), LAYER_TABLES)
    assert sorted(named - LAYER_MODULES - TABLE_READERS) == []


def test_layer_modules_never_name_g2_graph_tables() -> None:
    """Ruling A1: no layer row in graph_nodes / graph_edges, and no layer code that reads them."""
    modules = package_modules()
    assert sorted(modules_with_string_literals(modules, G2_TABLES) & LAYER_MODULES) == []
    imports = imports_of(modules, packages=package_dirs())
    assert sorted(m for m, i in imports if m in LAYER_MODULES and i == "factory.index.graph") == []


def test_scanner_catches_a_planted_import(tmp_path: Path) -> None:
    pkg = tmp_path / "factory"
    (pkg / "services").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "services" / "__init__.py").write_text("")
    (pkg / "services" / "evidence_plant.py").write_text(
        "from factory.services import interpretations\n"
        "from . import intuition_sources\n"
        "import factory.model.intuition\n"
        "SQL = 'SELECT * FROM layer_nodes'\n"
    )
    modules = package_modules(pkg, "factory")
    imports = imports_of(modules, packages=package_dirs(pkg, "factory"))
    planted = {i for m, i in imports if m == "factory.services.evidence_plant"}
    assert LAYER_MODULES & planted == {
        "factory.services.interpretations",
        "factory.services.intuition_sources",
        "factory.model.intuition",
    }
    assert modules_with_string_literals(modules, LAYER_TABLES) == {
        "factory.services.evidence_plant"
    }


def test_scanner_ignores_docstrings(tmp_path: Path) -> None:
    pkg = tmp_path / "factory"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "doc.py").write_text('"""Mentions layer_nodes and interpretations."""\nX = 1\n')
    assert modules_with_string_literals(package_modules(pkg, "factory"), LAYER_TABLES) == set()


def test_evidence_outputs_byte_identical_with_and_without_layer(
    tmp_path: Path, project: Project, iwe: IWorld
) -> None:
    """Every output a researcher reads, data and rendered, is the same with a populated layer."""
    iw = iwe
    plain, layered = twin_projects(tmp_path, project, iw)
    nodes = [iw.source, iw.other, iw.idea1]
    assert layer_event_count(plain) == 0 and layer_event_count(layered) > 0
    expected = evidence_outputs(plain, nodes)
    # the comparison is not vacuous: real final rows, claims, groups and independent rows
    assert expected["final_rows"] not in ("[]", "")
    assert expected["live_claims"] not in ("[]", "")
    assert '"groups": []' not in expected["evidence_report"]
    assert "No rows" not in expected["evidence_markdown"]
    assert expected["independence"] != "IndependenceCounts(independent=0, copied=0)"
    assert iw.idea1 in expected["ideas"] and expected["contribution_items"] != "[]"
    assert "claude-intuition-only" not in expected["methods_text"]
    # trace must compare real nodes, not two identical errors
    for node in (iw.source, iw.other):
        for direction in ("back", "forward"):
            assert not expected[f"trace:{node}:{direction}"].startswith("error:"), (node, direction)
    for direction in ("back", "forward"):
        is_error = expected[f"trace:{iw.idea1}:{direction}"].startswith("error:")
        # g3a's base cannot trace an idea id (422b0c0 adds it): flip when the branch is merged
        assert is_error == (not TRACE_IDEAS_ARE_NODES), "flip TRACE_IDEAS_ARE_NODES"
    got = evidence_outputs(layered, nodes)
    assert [k for k in expected if expected[k] != got[k]] == []
    assert expected == got


def test_differential_detects_a_leak(
    tmp_path: Path, project: Project, iwe: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patch the real read path (`final_items`, which every contribution reader uses) so the
    layered project's items carry a layer id; the outputs must then differ."""
    plain, layered = twin_projects(tmp_path, project, iwe)
    nodes = [iwe.source]
    original = contributions_service.final_items

    def leaking(p: Project) -> list[ItemView]:
        found = original(p)
        if p is layered and found:
            return [found[0].model_copy(update={"name": "int_LEAKED"}), *found[1:]]
        return found

    monkeypatch.setattr(contributions_service, "final_items", leaking)
    assert evidence_outputs(plain, nodes) != evidence_outputs(layered, nodes)
