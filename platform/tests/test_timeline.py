"""Record timelines and yearly frontiers (plan V-B, task 3; review focus 3)."""

# ruff: noqa: F811

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.model.extraction import ReportedIn
from factory.services.context import Project
from factory.services.evidence_groups import group_index
from factory.services.horizon import timeline_view
from factory.services.trace import trace
from factory.services.views import to_json
from factory.views.timeline import DatedPoint, records, yearly_frontiers
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.views_b_helpers import (
    VbWorld,
    acc,
    declared,  # noqa: F401
    ext_b,  # noqa: F401
    run_both,
    set_year,
    vb_world,  # noqa: F401
)


def p(
    year: int | None,
    value: int,
    *,
    wid: str = "a",
    independent: bool = True,
    costs: dict[str, str] | None = None,
) -> DatedPoint:
    suffix = "" if wid == "a" else wid
    return DatedPoint(
        trace_id=f"t{year}{suffix}",
        work_id=f"w{year}{wid}",
        row_key=f"rk_{year}{wid}",
        year=year,
        value=Decimal(value),
        unit="%",
        costs={k: Decimal(v) for k, v in (costs or {}).items()},
        independent=independent,
    )


def test_record_rules() -> None:  # Review Focus 3
    pts = [
        p(2019, 70),
        p(2020, 72),
        p(2020, 72, wid="b"),
        p(2021, 71),
        p(2022, 80, independent=False),  # a copied row with a better value is never a record
        p(None, 99),  # an undated row is never a record
    ]
    assert [x.trace_id for x in records(pts, True)] == ["t2019", "t2020", "t2020b"]
    # input order does not matter
    assert [x.trace_id for x in records(list(reversed(pts)), True)] == ["t2019", "t2020", "t2020b"]


def test_equal_value_later_is_not_a_record_and_first_date_ties_all_are() -> None:
    pts = [p(2018, 60, wid="a"), p(2018, 60, wid="b"), p(2019, 60)]
    assert [x.trace_id for x in records(pts, True)] == ["t2018", "t2018b"]


def test_lower_is_better() -> None:
    pts = [p(2019, 30), p(2020, 28), p(2021, 29), p(2022, 28, wid="b")]
    assert [x.trace_id for x in records(pts, False)] == ["t2019", "t2020"]


def test_no_points_no_records() -> None:
    assert records([], True) == []
    assert yearly_frontiers([], True, ["params"]) == {}


def test_yearly_frontier_monotone_inclusion() -> None:
    pts = [
        p(2019, 70, costs={"params": "10"}),
        p(2020, 75, costs={"params": "30"}),
        p(2021, 72, costs={"params": "5"}),
        p(2022, 99, independent=False, costs={"params": "1"}),
    ]
    frontiers = yearly_frontiers(pts, True, ["params"])
    assert sorted(frontiers) == [2019, 2020, 2021]  # years with a new dated, independent row
    assert frontiers[2019] == {"params": ["t2019"]}
    assert frontiers[2020] == {"params": ["t2019", "t2020"]}
    # 2021: the 5M point at 72 dominates the 10M point at 70; the 30M point at 75 stays
    assert frontiers[2021] == {"params": ["t2021", "t2020"]}
    # a year's frontier is computed from points dated up to that year only
    assert "t2021" not in frontiers[2020]["params"]


def test_frontier_skips_rows_without_the_axis_or_a_positive_cost() -> None:
    pts = [p(2019, 70, costs={"params": "10"}), p(2020, 80), p(2021, 81, costs={"params": "0"})]
    frontiers = yearly_frontiers(pts, True, ["params", "flops"])
    assert frontiers[2021]["params"] == ["t2019"]
    assert frontiers[2021]["flops"] == []


# --- through events ---


def _group(project: Project, task: str) -> str:
    return next(g.group_id for g in group_index(project) if dict(g.key)["task"] == task)


def test_unknown_direction_no_timeline(project: Project, vb_world: VbWorld) -> None:
    view = timeline_view(project, _group(project, "detection"))
    assert view.units == {} and view.direction == "unknown" and view.higher_is_better is None
    assert "direction-unknown" in [n.code for n in view.meta.notices]


def test_unknown_group_is_a_structured_error(project: Project, vb_world: VbWorld) -> None:
    with pytest.raises(FactoryValidationError) as err:
        timeline_view(project, "grp_000000000000")
    assert err.value.issues[0].field == "group_id"


def test_fresh_project_unknown_group(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        timeline_view(project, "grp_000000000000")


def test_records_units_and_undated_through_events(project: Project, vb_world: VbWorld) -> None:
    w = vb_world.works
    for work, year in ((w[0], "2018-03-01"), (w[1], "2019-06-01"), (w[2], "2017-01-01")):
        set_year(project, work, year)
    set_year(project, w[3], None)
    gid = _group(project, "classification")
    view = timeline_view(project, gid)
    assert view.direction == "declared" and view.higher_is_better is True
    assert view.undated == [w[3]]
    (unit,) = view.units.values()  # one value unit: never mixed with another
    assert unit.unit == "%"
    # w0 (2018, 2) is the first independent dated row; w1 (2019, 1) is worse; w2 is copied
    assert [(r.work_id, r.year) for r in unit.records] == [(w[0], 2018)]
    assert not any(r.work_id == w[2] for r in unit.records)  # copied, earlier, never a record
    assert all(r.trace_id.endswith("/value") for r in unit.records)


def test_trace_ids_resolve(project: Project, vb_world: VbWorld) -> None:
    view = timeline_view(project, _group(project, "classification"))
    (unit,) = view.units.values()
    assert unit.records
    for r in unit.records:
        assert trace(project, r.trace_id) is not None  # an unknown id would raise


def test_units_never_mixed(
    project: Project, ext_a: object, ext_b: object, declared: list[str]
) -> None:
    """A percentage and a fraction in one group are two timelines, never one record list."""
    from factory.model.extraction import FieldInput

    def rows(work: str) -> list:  # type: ignore[type-arg]
        if work == declared[0]:
            return [acc("2")]
        if work == declared[1]:
            row = acc("1")
            fields = dict(row.fields)
            fields["value"] = FieldInput(
                value="1", unit="fraction", anchor="t1", cell="t1.r3.c2", quote="1"
            )
            return [row.model_copy(update={"fields": fields})]
        return []

    run_both(project, ext_a, ext_b, rows)  # type: ignore[arg-type]
    view = timeline_view(project, _group(project, "classification"))
    assert len(view.units) == 2
    assert sorted(u.unit or "" for u in view.units.values()) == ["%", "fraction"]
    assert all(len(u.records) == 1 for u in view.units.values())


def test_corpus_and_notice_filters(project: Project, vb_world: VbWorld) -> None:
    gone = vb_world.works[0]
    with project.index.connect() as conn:
        conn.execute(text("DELETE FROM provenance WHERE work_id = :w"), {"w": gone})
        conn.commit()
    view = timeline_view(project, _group(project, "classification"))
    (unit,) = view.units.values()
    assert all(r.work_id != gone for r in unit.records)


def test_deterministic_across_rebuilds(project: Project, vb_world: VbWorld) -> None:
    gid = _group(project, "classification")
    before = to_json(timeline_view(project, gid))
    assert timeline_view(project, gid).units
    project.index.rebuild()
    assert to_json(timeline_view(project, gid)) == before


def test_frontier_axis_through_events(
    project: Project, ext_a: object, ext_b: object, declared: list[str]
) -> None:
    def rows(work: str) -> list:  # type: ignore[type-arg]
        table = {
            declared[0]: acc("1", params="2"),
            declared[1]: acc("2", params="1"),
            declared[2]: acc("2", params="2", reported_in=ReportedIn.CITED),
        }
        return [table[work]] if work in table else []

    run_both(project, ext_a, ext_b, rows)  # type: ignore[arg-type]
    set_year(project, declared[0], "2019-01-01")
    set_year(project, declared[1], "2020-01-01")
    view = timeline_view(project, _group(project, "classification"))
    (unit,) = view.units.values()
    assert sorted(unit.frontiers) == [2019, 2020]
    by_work = {r.work_id: r.trace_id for r in unit.records}
    assert unit.frontiers[2019]["params"] == [by_work[declared[0]]]
    # the 1M row with value 2 dominates the 2M row with value 1; the copied row is no point
    assert unit.frontiers[2020]["params"] == [by_work[declared[1]]]
