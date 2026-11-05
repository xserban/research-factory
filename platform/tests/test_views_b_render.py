"""Renderers of the coverage, timeline and horizon views (plan V-B, task 5): pure formatting."""

from __future__ import annotations

import csv
import io

from factory.model.views import (
    CoverageCell,
    CoverageView,
    GroupSummary,
    HorizonView,
    RecordPoint,
    TimelineView,
    UnitTimeline,
    ViewMeta,
    ViewNotice,
)
from factory.views.render import (
    coverage_csv,
    coverage_markdown,
    horizon_csv,
    horizon_markdown,
    timeline_csv,
    timeline_markdown,
)

HORIZON = ViewNotice(
    code="corpus-horizon",
    text="Latest search or watch run per source: openalex: 2026-10-31. Works published after "
    "these dates are not in the corpus.",
)


def _meta(view: str, truncated: bool = False) -> ViewMeta:
    return ViewMeta(
        view=view,
        version=1,
        project="demo",
        as_of="evt_9",
        filter={"max_groups": 200},
        truncated=truncated,
        notices=[HORIZON],
    )


def _coverage() -> CoverageView:
    cell = CoverageCell(independent=2, copied=1, works=3)
    return CoverageView(
        meta=_meta("coverage", truncated=True),
        groups=[
            GroupSummary(
                group_id="grp_aaa",
                key=[("task", "a | b")],
                works=3,
                rows=3,
                independent=2,
                copied=1,
            )
        ],
        methods=["lorem"],
        cells={"lorem": {"grp_aaa": cell}},
        ideas=["ida_1"],
        idea_cells={"ida_1": {"grp_aaa": CoverageCell(independent=1, copied=0, works=1)}},
        total_groups=5,
        total_methods=1,
        total_ideas=1,
    )


def _timeline() -> TimelineView:
    unit = UnitTimeline(
        unit="%",
        metric=None,
        resolution=None,
        records=[
            RecordPoint(trace_id="rk_1/value", work_id="rf:w", row_key="rk_1", year=2020, value="7")
        ],
        frontiers={2020: {"params": ["rk_1/value"]}},
    )
    return TimelineView(
        meta=_meta("timeline"),
        group_id="grp_aaa",
        key=[("task", "x")],
        direction="declared",
        higher_is_better=True,
        units={"unit %": unit},
        undated=["rf:undated"],
    )


def _horizon() -> HorizonView:
    return HorizonView(
        meta=_meta("horizon"),
        years=[2019, 2020],
        idea_members={"ida_1": {2019: 1, 2020: 2}},
        new_ideas={2019: ["ida_1"]},
        new_edges={2020: 1},
        group_records={"grp_aaa": {2020: 1}},
        undated={"idea_members": 1, "new_ideas": 0, "new_edges": 0},
        horizon={"openalex": "2026-10-31"},
        total_ideas=1,
        total_groups=5,
        listed_groups=1,
    )


def test_markdown_headers_state_filter_as_of_horizon_and_activity_not_quality() -> None:
    for md in (
        coverage_markdown(_coverage()),
        timeline_markdown(_timeline()),
        horizon_markdown(_horizon()),
    ):
        assert "as_of: evt_9" in md and 'filter: {"max_groups":200}' in md
        assert "corpus-horizon" in md and "not in the corpus" in md
        assert "counts are activity, not quality" in md.lower()


def test_coverage_markdown_cells_and_truncation() -> None:
    md = coverage_markdown(_coverage())
    assert "truncated: yes" in md and "showing 1 of 5 groups" in md
    assert "| lorem | 2/1/3 |" in md  # independent / copied / works
    assert "a \\| b" in md  # table cells are escaped
    assert "| ida_1 | 1/0/1 |" in md


def test_coverage_csv_is_parseable_and_numeric() -> None:
    rows = list(csv.reader(io.StringIO(coverage_csv(_coverage()))))
    assert rows[0] == ["matrix", "row", "group_id", "independent", "copied", "works"]
    assert ["method", "lorem", "grp_aaa", "2", "1", "3"] in rows
    assert ["idea", "ida_1", "grp_aaa", "1", "0", "1"] in rows


def test_timeline_markdown_and_csv() -> None:
    md = timeline_markdown(_timeline())
    assert "rk_1/value" in md and "rf:undated" in md and "declared" in md
    rows = list(csv.reader(io.StringIO(timeline_csv(_timeline()))))
    assert rows[0] == ["unit", "kind", "year", "axis", "trace_id", "work_id", "value"]
    assert ["unit %", "record", "2020", "", "rk_1/value", "rf:w", "7"] in rows
    assert ["unit %", "frontier", "2020", "params", "rk_1/value", "", ""] in rows


def test_timeline_without_units_says_why() -> None:
    view = _timeline().model_copy(
        update={
            "units": {},
            "direction": "unknown",
            "higher_is_better": None,
            "meta": _meta("timeline").model_copy(
                update={
                    "notices": [
                        ViewNotice(code="direction-unknown", text="no timeline"),
                        HORIZON,
                    ]
                }
            ),
        }
    )
    assert "direction-unknown" in timeline_markdown(view)
    assert len(timeline_csv(view).splitlines()) == 1  # header only


def test_horizon_markdown_and_csv() -> None:
    md = horizon_markdown(_horizon())
    assert "ida_1" in md and "openalex" in md
    rows = list(csv.reader(io.StringIO(horizon_csv(_horizon()))))
    assert rows[0] == ["series", "subject", "year", "value"]
    assert ["idea_members", "ida_1", "2020", "2"] in rows
    assert ["new_ideas", "ida_1", "2019", "1"] in rows
    assert ["new_edges", "", "2020", "1"] in rows
    assert ["group_records", "grp_aaa", "2020", "1"] in rows


def test_horizon_markdown_states_a_group_cut() -> None:
    cut = _horizon().model_copy(update={"meta": _meta("horizon", truncated=True)})
    assert "1 of 5 groups" in horizon_markdown(cut)


def test_renders_are_deterministic() -> None:
    assert coverage_markdown(_coverage()) == coverage_markdown(_coverage())
    assert horizon_csv(_horizon()) == horizon_csv(_horizon())
