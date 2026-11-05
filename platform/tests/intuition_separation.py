"""Helpers of the separation tests (slice 3c, plan G3-A task 6; reused by G3-B and G3-C).

`LAYER_MODULES` and `ALLOWED_IMPORTERS` fix which modules may import the layer; `LAYER_TABLES` the
tables only layer code (and the named readers) may name; `evidence_outputs` serialises every
evidence output; `twin_projects` builds the same world with and without a populated layer.
"""

from __future__ import annotations

import ast
import json
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import factory
from factory.config import Settings
from factory.events.reader import read_all
from factory.lineage.graph import GraphFilter
from factory.model.screening import Channel
from factory.services.context import Project, open_project
from factory.services.contributions import final_items
from factory.services.evidence_report import evidence_report
from factory.services.extraction import live_claims
from factory.services.extraction_agreement import (
    final_rows,
    grouped_rows,
    independence_counts,
)
from factory.services.ideas import list_ideas
from factory.services.interpretations import (
    intuition_next,
    record_interpretation,
    review_interpretation,
    supersede_interpretation,
)
from factory.services.lineage import graph_export, graph_query, graph_status
from factory.services.methods import methods_report
from factory.services.prisma import prisma_flow, search_report
from tests.helpers import SESSION
from tests.intuition_helpers import IWorld

SRC_ROOT = Path(factory.__file__).parent

LAYER_MODULES = frozenset(
    {
        "factory.model.intuition",
        "factory.intuition",
        "factory.intuition.validate",
        "factory.intuition.labels",
        "factory.index.intuition",
        "factory.services.intuition_sources",
        "factory.services.interpretations",
        "factory.services.concepts",  # G3-B
    }
)
ALLOWED_IMPORTERS = frozenset(
    {
        "factory.services.lineage",
        "factory.services.check",
        "factory.services.trace",
        "factory.index.default",
        "factory.events.catalog",
        "factory.mcp.server",
        "factory.cli.main",
        "factory.cli.render",
    }
)
LAYER_TABLES = (
    "interpretations",
    "interpretation_sources",
    "interpretation_reviews",
    "layer_nodes",
    "layer_edges",
    "layer_hidden",
)
G2_TABLES = ("graph_nodes", "graph_edges")
TABLE_READERS = frozenset(
    {
        "factory.services.lineage",
        "factory.services.check",
        "factory.services.trace",
        "factory.index.index",  # OMITTED_WHEN_EMPTY names tables whose emptiness is hash-neutral
    }
)


def _module_name(root: Path, prefix: str, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([prefix, *parts]) if parts else prefix


def package_modules(root: Path = SRC_ROOT, prefix: str = "factory") -> dict[str, ast.Module]:
    return {
        _module_name(root, prefix, path): ast.parse(path.read_text("utf-8"))
        for path in sorted(root.rglob("*.py"))
    }


def imports_of(
    modules: dict[str, ast.Module], *, packages: Iterable[str] = ()
) -> set[tuple[str, str]]:
    """(importer, imported) pairs, with relative imports resolved. `from a import b` yields both
    `a` and `a.b`, so a submodule imported by name is seen."""
    package_names = set(packages)
    found: set[tuple[str, str]] = set()
    for name, tree in modules.items():
        is_package = name in package_names
        base = name.split(".") if is_package else name.split(".")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update((name, a.name) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    anchor = base[: len(base) - node.level + 1]
                    module = ".".join([*anchor, *(node.module.split(".") if node.module else [])])
                else:
                    module = node.module or ""
                found.add((name, module))
                found.update((name, f"{module}.{a.name}") for a in node.names)
    return found


def package_dirs(root: Path = SRC_ROOT, prefix: str = "factory") -> set[str]:
    return {_module_name(root, prefix, p) for p in root.rglob("__init__.py")}


def string_literals(tree: ast.Module) -> list[str]:
    """String constants outside docstrings."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


def modules_with_string_literals(modules: dict[str, ast.Module], names: Iterable[str]) -> set[str]:
    """Modules with a string literal that contains one of `names` as a whole word."""
    import re

    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    return {
        m for m, tree in modules.items() if any(pattern.search(s) for s in string_literals(tree))
    }


def populate_layer(project: Project, iw: IWorld) -> int:
    """A fixed set of layer events through the services: an agent-written interpretation reviewed
    and superseded by a human, a second agent-written one left unreviewed, a human-written one on
    a paper and a rejected one. Returns the number of layer events written."""
    batch = intuition_next(project, iw.writer, targets=[iw.idea1]).batch
    assert batch is not None
    first = record_interpretation(project, iw.writer, iw.entry(iw.idea1), task_id=batch.task_id)
    review_interpretation(project, iw.human, first, "reviewed", "ok", Channel.CLI)
    supersede_interpretation(project, iw.human, first, "A human replacement.", [iw.quote()])
    batch2 = intuition_next(project, iw.writer, targets=[iw.idea2]).batch
    assert batch2 is not None
    second = record_interpretation(project, iw.writer, iw.entry(iw.idea2), task_id=batch2.task_id)
    review_interpretation(project, iw.human, second, "wrong", "misreads", Channel.CLI)
    record_interpretation(project, iw.human, iw.entry(iw.third))
    return layer_event_count(project)


def layer_event_count(project: Project) -> int:
    events = read_all(project.paths.events_dir, project.catalog)
    return len([e for e in events if e.type.startswith("interpretation.")])


def _run(fn: Callable[[], Any]) -> str:
    try:
        result = fn()
    except Exception as exc:  # an output that raises must raise the same in both projects
        return f"error:{type(exc).__name__}:{exc}"
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(mode="json"), sort_keys=True, default=str)
    if isinstance(result, list):
        return json.dumps(
            [r.model_dump(mode="json") if hasattr(r, "model_dump") else repr(r) for r in result],
            sort_keys=True,
            default=str,
        )
    return result if isinstance(result, str) else repr(result)


def methods_without_agent_provenance(project: Project) -> str:
    """The methods report without `models` and `skills`: those list every agent that acted in the
    project, so they name the intuition writer's skill once a layer exists. They are provenance,
    not a count or a result; `agent_provenance` compares them separately."""
    report = methods_report(project).model_dump(mode="json")
    report.pop("models")
    report.pop("skills")
    return json.dumps(report, sort_keys=True, default=str)


def agent_provenance(project: Project) -> tuple[list[str], list[str]]:
    report = methods_report(project)
    return report.models, report.skills


def evidence_outputs(project: Project, nodes: Iterable[str] = ()) -> dict[str, str]:
    """Each evidence output of the project, serialised."""
    out: dict[str, str] = {
        "final_rows": _run(lambda: final_rows(project)),
        "grouped_rows": _run(lambda: repr(grouped_rows(project))),
        "independence": _run(lambda: independence_counts(final_rows(project))),
        "live_claims": _run(lambda: live_claims(project)),
        "evidence_report": _run(lambda: evidence_report(project)),
        "prisma": _run(lambda: prisma_flow(project)),
        "search_report": _run(lambda: search_report(project)),
        "methods": _run(lambda: methods_without_agent_provenance(project)),
        "contribution_items": _run(lambda: final_items(project)),
        "ideas": _run(lambda: list_ideas(project, include_unconfirmed=True)),
        "graph_status": _run(lambda: graph_status(project)),
    }
    filters = {
        "default": GraphFilter(),
        "all": GraphFilter(include_inferred=True, include_stale=True),
    }
    for label, flt in filters.items():
        out[f"cited_by:{label}"] = _run(
            lambda f=flt: graph_query(project, "cited_by_at_least", k=1, flt=f)
        )
        out[f"no_stated_base:{label}"] = _run(
            lambda f=flt: graph_query(project, "no_stated_base", flt=f)
        )
        for node in nodes:
            for kind in ("ancestors", "descendants"):
                out[f"{kind}:{node}:{label}"] = _run(
                    lambda k=kind, n=node, f=flt: graph_query(project, k, node=n, flt=f)
                )
        for fmt in ("json", "dot"):
            out[f"export:{fmt}:{label}"] = _run(
                lambda m=fmt, f=flt: graph_export(project, m, flt=f)  # type: ignore[arg-type]
            )
    return out


def twin_projects(root: Path, project: Project, iw: IWorld) -> tuple[Project, Project]:
    """The built world twice: `plain` as built, `layered` a copy of its whole root with a layer
    populated through the services. Both indexes are rebuilt from their logs."""
    copy_root = root / "twin"
    shutil.copytree(project.settings.root, copy_root, ignore=shutil.ignore_patterns(".index"))
    settings = Settings(root=copy_root, user=project.settings.user)
    layered = open_project(settings, project.paths.slug, session=SESSION, clock=project.clock)
    twin_iw = IWorld(**{**iw.__dict__})
    populate_layer(layered, twin_iw)
    project.index.rebuild()
    layered.index.rebuild()
    return project, layered
