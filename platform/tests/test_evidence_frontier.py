"""Evidence report frontiers per group and cost axis (plan E, task 3; rulings 6 and 8)."""

from dataclasses import replace

from factory.packs import ML_BENCHMARK_V1
from factory.services.evidence_report import (
    EvidenceReport,
    FrontierAxis,
    GroupReport,
    assemble_report,
)
from factory.services.extraction_agreement import FinalField, FinalRow
from tests.evidence_helpers import ff, frow, pilot_inputs


def cost(n: str) -> FinalField:
    return ff(n, unit="count", canon=n)


def r_of(rows: list[FinalRow], **kw: object) -> EvidenceReport:
    return assemble_report(pilot_inputs(rows, **kw))  # type: ignore[arg-type]


def only_group(r: EvidenceReport) -> GroupReport:
    assert len(r.groups) == 1, [g.key for g in r.groups]
    return r.groups[0]


def axis(r: EvidenceReport, name: str) -> FrontierAxis:
    found = [a for a in only_group(r).frontiers if a.axis == name]
    assert len(found) == 1
    return found[0]


def three() -> list[FinalRow]:
    return [
        frow("rf:w1", "rk_000000000101", "A", "80.0", params=cost("20000000")),
        frow("rf:w2", "rk_000000000201", "B", "79.0", params=cost("30000000")),
        frow("rf:w3", "rk_000000000301", "C", "82.0", params=cost("40000000")),
    ]


def test_frontier_points_trace_to_their_rows() -> None:  # acceptance 12
    r = r_of(three())
    ax = axis(r, "params")
    keys = {row.row_key for row in only_group(r).rows}
    pts = [p for part in ax.partitions for p in part.points]
    assert len(pts) == 3
    assert all(p.trace_id == f"{p.row_key}/value" and p.row_key in keys for p in pts)
    by = {p.row_key: p for p in pts}
    assert by["rk_000000000101"].on_frontier and by["rk_000000000301"].on_frontier
    assert not by["rk_000000000201"].on_frontier
    assert by["rk_000000000201"].dominated_by == "rk_000000000101"
    assert by["rk_000000000101"].cost == "20000000" and by["rk_000000000101"].metric == "80"


def test_frontier_uses_only_cost_axes_of_decision_42() -> None:  # acceptance 12a
    rows = three()
    rows.append(
        frow(
            "rf:w4",
            "rk_000000000401",
            "D",
            "70.0",
            params=cost("1"),
            throughput=ff("900", unit="img/s", canon="900"),
        )
    )
    r = r_of(rows)
    assert {a.axis for g in r.groups for a in g.frontiers} <= {"params", "flops", "macs"}
    assert "throughput" not in r.model_dump_json(include={"groups": {"__all__": {"frontiers"}}})


def test_flops_and_macs_are_separate_axes() -> None:
    rows = [
        frow("rf:w1", "rk_000000000101", "A", "80.0", flops=cost("5"), macs=cost("2")),
        frow("rf:w2", "rk_000000000201", "B", "81.0", flops=cost("9")),
    ]
    r = r_of(rows)
    assert {a.axis for a in only_group(r).frontiers if a.partitions} == {"flops", "macs"}
    assert len(axis(r, "flops").partitions[0].points) == 2
    assert [p.row_key for p in axis(r, "macs").partitions[0].points] == ["rk_000000000101"]


def test_copied_rows_are_not_plotted() -> None:  # Review Focus 2
    rows = three()
    rows.append(frow("rf:w4", "rk_000000000401", "D", "90.0", cited=True, params=cost("1")))
    ax = axis(r_of(rows), "params")
    assert "rk_000000000401" not in {p.row_key for part in ax.partitions for p in part.points}
    assert "rk_000000000401" not in {k for v in ax.missing.values() for k in v}


def test_missing_and_non_positive_cost_counted_not_plotted() -> None:
    rows = three()
    rows.append(frow("rf:w4", "rk_000000000401", "D", "70.0"))
    rows.append(frow("rf:w5", "rk_000000000501", "E", "71.0", params=cost("0")))
    rows.append(frow("rf:w6", "rk_000000000601", "F", "72.0", params=cost("-3")))
    ax = axis(r_of(rows), "params")
    assert ax.missing == {
        "cost-missing": ["rk_000000000401"],
        "cost-not-positive": ["rk_000000000501", "rk_000000000601"],
    }
    assert len(ax.partitions[0].points) == 3


def test_lower_is_better_group() -> None:
    rows = [
        frow("rf:w1", "rk_000000000101", "A", "30.0", metric="Perplexity", params=cost("10")),
        frow("rf:w2", "rk_000000000201", "B", "25.0", metric="Perplexity", params=cost("20")),
        frow("rf:w3", "rk_000000000301", "C", "28.0", metric="Perplexity", params=cost("30")),
    ]
    pts = {p.row_key: p for p in axis(r_of(rows), "params").partitions[0].points}
    assert pts["rk_000000000101"].on_frontier and pts["rk_000000000201"].on_frontier
    assert not pts["rk_000000000301"].on_frontier
    assert pts["rk_000000000301"].dominated_by == "rk_000000000201"


def test_conflicting_or_unknown_direction_gives_no_frontier_and_a_statement() -> None:
    unknown = [
        frow("rf:w1", "rk_000000000101", "A", "1", metric="Weirdness", params=cost("1")),
        frow("rf:w2", "rk_000000000201", "B", "2", metric="Weirdness", params=cost("2")),
    ]
    g = only_group(r_of(unknown))
    assert g.direction_status == "unknown" and g.frontiers == []
    assert "direction-unknown" in {s.code for s in g.statements}
    conflict = [
        frow(
            "rf:w1",
            "rk_000000000101",
            "A",
            "1",
            params=cost("1"),
            higher_is_better=ff(False),
        ),
        frow("rf:w2", "rk_000000000201", "B", "2", params=cost("2")),
    ]
    g = only_group(r_of(conflict))
    assert g.direction_status == "conflict" and g.frontiers == []


def test_percent_and_fraction_are_separate_partitions() -> None:  # never converted
    rows = three()
    rows.append(frow("rf:w4", "rk_000000000401", "D", "0.9", params=cost("10000000")))
    rows[-1].fields["value"] = ff("0.9", unit="fraction", canon="0.9")
    parts = axis(r_of(rows), "params").partitions
    assert [(p.unit, len(p.points)) for p in parts] == [("%", 3), ("fraction", 1)]


def test_resolution_partitions_when_not_a_key() -> None:
    keys = ("task", "dataset", "split", "metric", "pretraining_data")
    rows = [
        frow("rf:w1", "rk_000000000101", "A", "80", resolution="224", params=cost("10")),
        frow("rf:w2", "rk_000000000201", "B", "81", resolution="384", params=cost("20")),
        frow("rf:w3", "rk_000000000301", "C", "82", resolution="384", params=cost("30")),
    ]
    parts = axis(r_of(rows, keys=keys), "params").partitions
    assert [(p.resolution, len(p.points)) for p in parts] == [("224x224", 1), ("384x384", 2)]
    # resolution a key: no resolution partition
    r2 = r_of([frow("rf:w1", "rk_000000000101", "A", "80", params=cost("10"))])
    assert all(p.resolution is None for a in only_group(r2).frontiers for p in a.partitions)


def test_single_point_partition_states_no_frontier() -> None:
    r = r_of([frow("rf:w1", "rk_000000000101", "A", "80", params=cost("10"))])
    (part,) = axis(r, "params").partitions
    assert part.statement is not None and "no frontier" in part.statement
    assert len(part.points) == 1
    assert "frontier-single-point" in {s.code for s in only_group(r).statements}
    assert axis(r_of(three()), "params").partitions[0].statement is None


def test_frontiers_identical_for_permuted_event_order() -> None:
    rows = [*three(), frow("rf:w4", "rk_000000000401", "D", "81.0", params=cost("25000000"))]
    assert r_of(rows).model_dump_json() == r_of(list(reversed(rows))).model_dump_json()


def test_no_speed_value_in_any_frontier_structure() -> None:
    rows = [
        frow(
            "rf:w1",
            "rk_000000000101",
            "A",
            "80",
            params=cost("10"),
            throughput=ff("123456", unit="img/s", canon="123456"),
            latency=ff("7.5", unit="ms", canon="7.5"),
        )
    ]
    dump = r_of(rows).model_dump_json(include={"groups": {"__all__": {"frontiers"}}})
    assert "throughput" not in dump and "123456" not in dump and "latency" not in dump


def test_rows_without_cost_keep_the_axis_with_missing_counts() -> None:
    rows = [
        frow("rf:w1", "rk_000000000101", "A", "80"),
        frow("rf:w2", "rk_000000000201", "B", "81"),
    ]
    ax = axis(r_of(rows), "params")
    assert ax.partitions == []
    assert ax.missing == {"cost-missing": ["rk_000000000101", "rk_000000000201"]}
    assert ax.statement is not None and "No independent row reports params" in ax.statement


def test_axis_not_declared_by_the_schema_gives_no_axis() -> None:
    inputs = pilot_inputs(three())
    declared = tuple(f for f in [d.name for d in ML_BENCHMARK_V1.fields] if f != "params")
    r = assemble_report(replace(inputs, declared_fields=declared))
    assert "params" not in {a.axis for a in only_group(r).frontiers}
    r2 = assemble_report(replace(inputs, declared_fields=(*declared, "params")))
    assert "params" in {a.axis for a in only_group(r2).frontiers}
