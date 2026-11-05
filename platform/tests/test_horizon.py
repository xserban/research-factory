"""The horizon activity view (plan V-B, task 4): series equal hand counts, nothing else."""

# ruff: noqa: F811

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.lineage import LineageDecision
from factory.services import horizon
from factory.services.context import Project
from factory.services.evidence_groups import group_index
from factory.services.horizon import horizon_view
from factory.services.ideas import decide_idea, merge_ideas, propose_idea
from factory.services.views import to_json
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.views_b_helpers import (
    VbWorld,
    ext_b,  # noqa: F401
    set_year,
    vb_world,  # noqa: F401
)


def _dated(project: Project, w: VbWorld) -> None:
    for work, year in ((0, "2018-03-01"), (1, "2019-06-01"), (2, "2018-01-05"), (3, "2019-02-02")):
        set_year(project, w.works[work], year)


def test_fresh_project_is_empty_with_a_horizon_notice(project: Project) -> None:
    view = horizon_view(project)
    assert (view.years, view.idea_members, view.new_ideas, view.new_edges) == ([], {}, {}, {})
    assert view.group_records == {} and view.horizon == {}
    codes = [n.code for n in view.meta.notices]
    assert "corpus-horizon" in codes and "horizon-empty" in codes


def test_series_equal_hand_counts(project: Project, vb_world: VbWorld) -> None:
    _dated(project, vb_world)
    view = horizon_view(project)
    w = vb_world
    assert view.idea_members == {w.idea: {2018: 1, 2019: 1}}
    assert view.new_ideas == {2018: [w.idea]}  # origin: work 0, published 2018
    assert view.new_edges == {2018: 1}  # confirmed work0 -> work1, by the citing work's year
    (classification,) = [
        g.group_id for g in group_index(project) if dict(g.key)["task"] == "classification"
    ]
    # work 0 (2018, value 2) is the only record: work 1 (2019, value 1) is worse, work 2 is copied
    assert view.group_records == {classification: {2018: 1}}
    assert view.years == [2018, 2019]
    assert view.undated == {"idea_members": 0, "new_ideas": 0, "new_edges": 0}


def test_undated_items_are_counted_apart(project: Project, vb_world: VbWorld) -> None:
    _dated(project, vb_world)
    set_year(project, vb_world.works[1], None)
    set_year(project, vb_world.works[0], None)
    view = horizon_view(project)
    assert view.undated == {"idea_members": 2, "new_ideas": 1, "new_edges": 1}
    assert view.years == [] or all(isinstance(y, int) for y in view.years)


def test_merged_ideas_counted_once(
    project: Project, vb_world: VbWorld, agent: Actor, other_session_human: Actor
) -> None:
    _dated(project, vb_world)
    w = vb_world
    # a second idea over works 0, 1 and 2 (overlapping the first), then merged into the first
    second = propose_idea(
        project, agent, "ipsum", w.works[0], w.name_item, [w.works[0], w.works[1], w.works[2]]
    )
    decide_idea(project, other_session_human, second, LineageDecision.CONFIRM, "named")
    before = horizon_view(project)
    assert set(before.idea_members) == {w.idea, second}
    merge_ideas(project, other_session_human, second, w.idea, "same idea")
    view = horizon_view(project)
    assert set(view.idea_members) == {w.idea}  # the merged idea is not listed
    assert view.idea_members[w.idea] == {2018: 2, 2019: 1}  # works 0, 2 (2018) and 1 (2019) once
    assert view.new_ideas == {2018: [w.idea]}


def test_inferred_edges_excluded(project: Project, vb_world: VbWorld) -> None:
    _dated(project, vb_world)  # the inferred edge's citing work is dated 2019
    assert 2019 not in horizon_view(project).new_edges


def test_corpus_horizon_notice_lists_each_source(project: Project, vb_world: VbWorld) -> None:
    view = horizon_view(project)
    assert view.horizon  # real search runs of the screened world
    (notice,) = [n for n in view.meta.notices if n.code == "corpus-horizon"]
    for source, date in view.horizon.items():
        assert f"{source}: {date}" in notice.text
    assert "orks published after these dates are not in the corpus" in notice.text


def test_horizon_ignores_probe_and_seed_runs(project: Project, vb_world: VbWorld) -> None:
    before = horizon_view(project).horizon
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO queries (query_id, source, kind, text, purpose, filters, interface, "
                "registered_at, actor_id) VALUES ('qry_p', 'zzsource', 'keyword', 'x', 'probe', "
                "'{}', 'api', '2030-01-01T00:00:00+00:00', 'a'), "
                "('qry_s', 'zzseed', 'keyword', 'x', 'seed', '{}', 'api', "
                "'2030-01-01T00:00:00+00:00', 'a')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO runs (run_id, query_id, source, status, started_at, finished_at, "
                "pages) VALUES ('run_p', 'qry_p', 'zzsource', 'complete', "
                "'2030-01-01T00:00:00+00:00', '2030-01-01T00:00:00+00:00', 0), "
                "('run_s', 'qry_s', 'zzseed', 'complete', '2030-01-01T00:00:00+00:00', "
                "'2030-01-01T00:00:00+00:00', 0)"
            )
        )
        conn.commit()
    assert horizon_view(project).horizon == before


def test_no_emerging_label_or_citation_score(project: Project, vb_world: VbWorld) -> None:
    _dated(project, vb_world)
    blob = to_json(horizon_view(project))
    assert "emerging" not in blob.lower() and "cited_by_count" not in blob


def test_bounds(project: Project, vb_world: VbWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(horizon, "HORIZON_MAX_IDEAS", 0)
    view = horizon_view(project)
    assert view.idea_members == {} and view.total_ideas == 1 and view.meta.truncated


def test_deterministic_across_rebuilds(project: Project, vb_world: VbWorld) -> None:
    before = to_json(horizon_view(project))
    assert horizon_view(project).idea_members
    project.index.rebuild()
    assert to_json(horizon_view(project)) == before
