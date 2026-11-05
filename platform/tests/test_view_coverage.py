"""The coverage map: methods x comparability groups, counts only (plan V-B, task 2)."""

# ruff: noqa: F811

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text

from factory.model.extraction import ReportedIn
from factory.services import view_coverage
from factory.services.context import Project
from factory.services.evidence_groups import group_index
from factory.services.view_coverage import coverage_view
from factory.services.views import to_json
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.views_b_helpers import (
    VbWorld,
    acc,
    declared,  # noqa: F401
    ext_b,  # noqa: F401
    run_both,
    vb_world,  # noqa: F401
)


def _cells(view: Any) -> dict[str, dict[str, tuple[int, int, int]]]:
    return {
        m: {g: (c.independent, c.copied, c.works) for g, c in by.items()}
        for m, by in view.cells.items()
    }


def test_fresh_project_is_empty_with_a_notice(project: Project) -> None:
    view = coverage_view(project)
    assert (view.groups, view.methods, view.cells, view.ideas, view.idea_cells) == (
        [],
        [],
        {},
        [],
        {},
    )
    assert "coverage-empty" in [n.code for n in view.meta.notices]
    assert (view.total_groups, view.total_methods, view.total_ideas) == (0, 0, 0)


def test_screened_project_without_extraction_is_empty(
    project: Project, screened: list[str]
) -> None:
    view = coverage_view(project)
    assert view.cells == {} and "coverage-empty" in [n.code for n in view.meta.notices]


def test_cells_count_rows_by_method_and_group(project: Project, vb_world: VbWorld) -> None:
    view = coverage_view(project)
    by_task = {dict(g.key)["task"]: g.group_id for g in view.groups}
    cls, det = by_task["classification"], by_task["detection"]
    assert view.methods == ["lorem", "item"]  # (works desc, name)
    assert _cells(view) == {
        "lorem": {cls: (2, 1, 3), det: (2, 0, 2)},  # variants v1 and v2 fold into one method
        "item": {cls: (1, 0, 1)},
    }
    assert [(g.works, g.rows) for g in view.groups] == [(4, 4), (2, 2)]
    assert (view.total_groups, view.total_methods) == (2, 2)
    # the totals agree with the grouping the evidence report uses
    assert sorted((s.group_id, s.rows) for s in group_index(project)) == sorted(
        (g.group_id, g.rows) for g in view.groups
    )


def test_coverage_has_no_values(project: Project, vb_world: VbWorld) -> None:  # Review Focus 2
    data = json.loads(to_json(coverage_view(project)))

    def leaves(node: Any) -> list[Any]:
        if isinstance(node, dict):
            return [x for v in node.values() for x in leaves(v)]
        return [node]

    for name in ("cells", "idea_cells"):
        found = leaves(data[name])
        assert found and all(type(x) is int for x in found), name


def test_idea_cells_only_with_result_links(project: Project, vb_world: VbWorld) -> None:
    view = coverage_view(project)
    cls = next(g.group_id for g in view.groups if dict(g.key)["task"] == "classification")
    assert view.ideas == [vb_world.idea] and view.total_ideas == 1
    assert {
        i: {g: (c.independent, c.copied, c.works) for g, c in by.items()}
        for i, by in view.idea_cells.items()
    } == {vb_world.idea: {cls: (1, 0, 1)}}
    assert "idea-links-none" not in [n.code for n in view.meta.notices]


def test_no_idea_matrix_without_links(
    project: Project, ext_a: Any, ext_b: Any, declared: list[str]
) -> None:
    run_both(project, ext_a, ext_b, lambda w: [acc("1")] if w == declared[0] else [])
    view = coverage_view(project)
    assert view.cells and view.ideas == [] and view.idea_cells == {}
    assert "idea-links-none" in [n.code for n in view.meta.notices]


def test_corpus_is_prisma_corpus_minus_absorbed(project: Project, vb_world: VbWorld) -> None:
    """A work outside the corpus (here: no provenance left) drops out of every count."""
    gone = vb_world.works[3]
    with project.index.connect() as conn:
        conn.execute(text("DELETE FROM provenance WHERE work_id = :w"), {"w": gone})
        conn.commit()
    view = coverage_view(project)
    assert "item" not in view.cells and view.total_methods == 1


def test_copied_only_cell_and_row_counts(
    project: Project, ext_a: Any, ext_b: Any, declared: list[str]
) -> None:
    run_both(
        project,
        ext_a,
        ext_b,
        lambda w: [acc("2", reported_in=ReportedIn.CITED)] if w == declared[0] else [],
    )
    view = coverage_view(project)
    assert _cells(view) == {"lorem": {view.groups[0].group_id: (0, 1, 1)}}


def test_bounds_and_truncation(
    project: Project, vb_world: VbWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(view_coverage, "VIEW_MAX_GROUPS", 1)
    monkeypatch.setattr(view_coverage, "VIEW_MAX_NODES", 1)
    view = coverage_view(project)
    assert len(view.groups) == 1 and view.methods == ["lorem"]
    assert (view.total_groups, view.total_methods) == (2, 2)  # counts are complete
    assert view.meta.truncated
    assert set(view.cells) == {"lorem"} and set(view.cells["lorem"]) == {view.groups[0].group_id}


def test_deterministic_across_rebuilds(project: Project, vb_world: VbWorld) -> None:
    before = to_json(coverage_view(project))
    assert coverage_view(project).cells  # real events produced rows
    project.index.rebuild()
    assert to_json(coverage_view(project)) == before
