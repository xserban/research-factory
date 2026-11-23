"""The registry of count sources (R-87, IDEA-109): enumeration, import scan and the check rule."""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from pathlib import Path

import pytest

from factory.model.project import RigorMode
from factory.services import check as check_module
from factory.services import count_sources
from factory.services.context import Project
from factory.services.count_sources import (
    COUNT_SOURCES,
    EXPLORATORY_MODULES,
    NOT_COUNT_SOURCES,
    CountSource,
    Layer,
    exploratory_sources,
)
from factory.services.modules import default_modules

SERVICES = Path(check_module.__file__).parent
_REPORT_STEM = re.compile(
    r"^(prisma.*|.*_prisma|.*_report|methods|.*_methods|discovery|briefing.*|"
    r".*digest|trace|.*_trace)$"
)

# (count source module, exploratory module) -> why the import is not an exploratory count input.
ALLOWED_IMPORTS: dict[tuple[str, str], str] = {
    ("evidence_report", "evidence_miners"): "admitted miner rows are added beside the counts",
    ("methods", "mining"): "the statement lists registered miners; it counts none of their rows",
}


def _stem(module: str) -> str:
    return module.rsplit(".", 1)[-1]


def _imported_services(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "factory.services":
                found |= {a.name for a in node.names}
            elif node.module.startswith("factory.services."):
                found.add(node.module.split(".")[2])
        elif isinstance(node, ast.Import):
            found |= {
                a.name.split(".")[2] for a in node.names if a.name.startswith("factory.services.")
            }
    return found


def test_every_report_or_count_service_is_declared() -> None:
    declared = {_stem(s.module) for s in COUNT_SOURCES} | set(NOT_COUNT_SOURCES)
    candidates = {p.stem for p in SERVICES.glob("*.py") if _REPORT_STEM.match(p.stem)}
    missing = sorted(candidates - declared)
    assert not missing, (
        f"report or count services not declared in services/count_sources.py: {missing}; add a "
        "CountSource with the layers it reads, or a NOT_COUNT_SOURCES entry with a reason"
    )


def test_declarations_name_real_modules_once() -> None:
    stems = [_stem(s.module) for s in COUNT_SOURCES]
    assert len(stems) == len(set(stems)), "a module is declared twice"
    names = [s.name for s in COUNT_SOURCES]
    assert len(names) == len(set(names))
    for stem in [*stems, *NOT_COUNT_SOURCES, *EXPLORATORY_MODULES]:
        assert (SERVICES / f"{stem}.py").is_file(), stem
    assert not set(stems) & set(NOT_COUNT_SOURCES)
    assert not set(stems) & EXPLORATORY_MODULES


def test_no_declared_source_reads_the_exploratory_layer_today() -> None:
    assert exploratory_sources() == []


def test_declared_sources_import_no_exploratory_module() -> None:
    """The declaration is honest: a source declared without `exploratory` imports none of the
    exploratory services, but for the named exceptions."""
    offenders = [
        (_stem(s.module), imported)
        for s in COUNT_SOURCES
        if Layer.EXPLORATORY not in s.reads
        for imported in sorted(_imported_services(SERVICES / f"{_stem(s.module)}.py"))
        if imported in EXPLORATORY_MODULES and (_stem(s.module), imported) not in ALLOWED_IMPORTS
    ]
    assert not offenders, f"declare `exploratory` or justify in ALLOWED_IMPORTS: {offenders}"


def test_a_source_must_declare_a_layer() -> None:
    with pytest.raises(ValueError):
        CountSource("x", "factory.services.x", "nothing", frozenset())


def test_the_rule_is_declared_with_levels() -> None:
    assert default_modules().levels()["count-source-exploratory"] == ("warning", "error", "error")


def test_the_rule_flags_an_exploratory_source(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = check_module._findings_as(project, RigorMode.SYSTEMATIC)
    assert "count-source-exploratory" not in {f.code for f in clean}
    tainted = replace(COUNT_SOURCES[0], reads=frozenset({Layer.EVIDENCE, Layer.EXPLORATORY}))
    monkeypatch.setattr(count_sources, "COUNT_SOURCES", (tainted, *COUNT_SOURCES[1:]))
    for mode, severity in (
        (RigorMode.EXPLORATORY, "warning"),
        (RigorMode.PILOT, "error"),
        (RigorMode.SYSTEMATIC, "error"),
    ):
        hits = [
            f
            for f in check_module._findings_as(project, mode)
            if f.code == "count-source-exploratory"
        ]
        assert [(f.severity, f.refs) for f in hits] == [(severity, [tainted.name])], mode
