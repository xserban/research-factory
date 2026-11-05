"""Works absorbed by a real dedup merge are read as their primary (plan V-B review, I2)."""

# ruff: noqa: F811

from __future__ import annotations

from factory.services.context import Project
from factory.services.evidence_groups import group_index
from factory.services.evidence_report import evidence_report
from factory.services.horizon import horizon_view, timeline_view
from factory.services.view_coverage import coverage_view
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.views_b_helpers import VbWorld, ext_b, real_merge, set_year, vb_world  # noqa: F401


def _merged(project: Project, w: VbWorld) -> tuple[str, str]:
    """Work 2 (the copied row) absorbs work 0 (idea origin and member, edge source, result row)."""
    for work, year in ((0, "2018-03-01"), (1, "2019-06-01"), (2, "2017-01-01")):
        set_year(project, w.works[work], year)
    real_merge(project, w.works[2], w.works[0])
    return w.works[2], w.works[0]


def test_views_keep_the_rows_the_report_keeps_and_read_the_primary(
    project: Project, vb_world: VbWorld
) -> None:
    primary, _ = _merged(project, vb_world)
    report = evidence_report(project)
    report_rows = sum(len(g.rows) for g in report.groups)  # the report ignores merges
    view = coverage_view(project)
    assert sum(g.rows for g in view.groups) == report_rows == 6
    classification = next(g for g in view.groups if dict(g.key)["task"] == "classification")
    assert classification.works == 3  # works 0 and 2 are one paper; the report counts records
    assert [s.works for s in group_index(project) if s.group_id == classification.group_id] == [4]
    # the result item of the absorbed work still links its row, now under the primary
    assert view.ideas == [vb_world.idea]
    assert primary in vb_world.works


def test_horizon_follows_merges_for_members_origin_and_edge_source(
    project: Project, vb_world: VbWorld
) -> None:
    _merged(project, vb_world)
    view = horizon_view(project)
    assert view.idea_members == {vb_world.idea: {2017: 1, 2019: 1}}
    assert view.new_ideas == {2017: [vb_world.idea]}
    assert view.new_edges == {2017: 1}
    assert view.undated == {"idea_members": 0, "new_ideas": 0, "new_edges": 0}


def test_timeline_reads_the_absorbed_row_under_the_primary(
    project: Project, vb_world: VbWorld
) -> None:
    primary, _ = _merged(project, vb_world)
    gid = next(g.group_id for g in group_index(project) if dict(g.key)["task"] == "classification")
    (unit,) = timeline_view(project, gid).units.values()
    assert [(r.work_id, r.year) for r in unit.records] == [(primary, 2017)]
