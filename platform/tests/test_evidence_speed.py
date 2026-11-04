"""Evidence report within-paper speed ratios (plan E, task 4; ruling 7, acceptance 12a)."""

from factory.services.evidence_report import EvidenceReport, WithinPaperRatio, assemble_report
from factory.services.extraction_agreement import FinalField, FinalRow
from tests.evidence_helpers import ff, frow, pilot_inputs


def num(v: str, unit: str | None = "img/s") -> FinalField:
    return ff(v, unit=unit, canon=v)


def row(
    work: str,
    key: str,
    method: str,
    proposed: bool,
    *,
    thr: FinalField | None = None,
    lat: FinalField | None = None,
    hw: str | None = "A100",
    batch: str | None = "64",
    prec: str | None = None,
) -> FinalRow:
    extra: dict[str, FinalField] = {"is_proposed": ff(proposed)}
    if thr is not None:
        extra["throughput"] = thr
    if lat is not None:
        extra["latency"] = lat
    if hw is not None:
        extra["hardware"] = ff(hw)
    if batch is not None:
        extra["batch_size"] = ff(batch, canon=batch)
    if prec is not None:
        extra["precision"] = ff(prec)
    return frow(work, key, method, "80.0", **extra)


def rep(rows: list[FinalRow]) -> EvidenceReport:
    return assemble_report(pilot_inputs(rows))


def ratio(r: EvidenceReport, method: str, baseline: str) -> WithinPaperRatio:
    found = [
        x
        for x in r.speed_ratios
        if x.method.casefold() == method and x.baseline_method.casefold() == baseline
    ]
    assert len(found) == 1, r.speed_ratios
    return found[0]


def pair(**kw: str | None) -> list[FinalRow]:
    return [
        row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180"), **kw),
        row("rf:w1", "rk_000000000102", "DeiT-S", False, thr=num("100")),
    ]


def test_ratio_with_baseline_hardware_and_context() -> None:
    r = rep(pair())
    x = ratio(r, "ours", "deit-s")
    assert (x.ratio, x.hardware, x.batch_size, x.baseline_method) == (
        "1.80",
        "a100",
        "64",
        "DeiT-S",
    )
    assert x.field == "throughput" and x.unit == "img/s" and x.work_id == "rf:w1"
    assert x.proposed.trace_id == "rk_000000000101/throughput"
    assert x.baseline.trace_id == "rk_000000000102/throughput"
    assert r.speed_unpaired == {}


def test_latency_ratio_is_baseline_over_proposed() -> None:
    rows = [
        row("rf:w1", "rk_000000000101", "Ours", True, lat=num("10", "ms")),
        row("rf:w1", "rk_000000000102", "B", False, lat=num("25", "ms")),
    ]
    assert ratio(rep(rows), "ours", "b").ratio == "2.50"


def test_no_ratio_across_papers() -> None:
    rows = [
        row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
        row("rf:w2", "rk_000000000201", "B", False, thr=num("100")),
    ]
    r = rep(rows)
    assert r.speed_ratios == [] and r.speed_unpaired == {"no-baseline": 1}


def test_no_ratio_when_hardware_differs_or_missing() -> None:
    a = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100"), hw="V100"),
        ]
    )
    assert a.speed_ratios == [] and a.speed_unpaired == {"hardware-differs": 1}
    b = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180"), hw=None),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100"), hw=None),
        ]
    )
    assert b.speed_ratios == [] and b.speed_unpaired == {"hardware-missing": 1}


def test_hardware_compared_normalised() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180"), hw="A100"),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100"), hw=" a100 "),
        ]
    )
    assert len(r.speed_ratios) == 1


def test_no_ratio_when_batch_or_precision_differs() -> None:
    a = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100"), batch="128"),
        ]
    )
    assert a.speed_ratios == [] and a.speed_unpaired == {"context-differs": 1}
    b = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180"), prec="fp16"),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100")),
        ]
    )
    assert b.speed_unpaired == {"context-differs": 1}


def test_both_absent_batch_and_precision_pair() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180"), batch=None),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100"), batch=None),
        ]
    )
    x = r.speed_ratios[0]
    assert x.batch_size is None and x.precision is None


def test_no_ratio_when_baseline_is_cited_or_copy_marked() -> None:
    cited = ff("100", unit="img/s", canon="100", cited=True)
    marked = ff("100", unit="img/s", canon="100", marker=True)
    for base in (cited, marked):
        r = rep(
            [
                row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
                row("rf:w1", "rk_000000000102", "B", False, thr=base),
            ]
        )
        assert r.speed_ratios == [] and r.speed_unpaired == {"not-own": 1}


def test_unit_mismatch_not_paired() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180", "img/s")),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100", "ms")),
        ]
    )
    assert r.speed_ratios == [] and r.speed_unpaired == {"unit-differs": 1}


def test_printed_fallback_without_canonical_is_used() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=ff("180", unit="img/s")),
            row("rf:w1", "rk_000000000102", "B", False, thr=ff("90", unit="img/s")),
        ]
    )
    assert r.speed_ratios[0].ratio == "2.00"


def test_unusable_value_is_counted() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("0")),
        ]
    )
    assert r.speed_ratios == [] and r.speed_unpaired == {"value-unusable": 1}


def test_speed_values_absent_from_group_tables_and_points() -> None:  # acceptance 12a
    r = rep(pair())
    assert r.groups
    assert all(
        f not in row_.costs
        for g in r.groups
        for row_ in g.rows
        for f in ("throughput", "latency", "memory")
    )


def test_ratios_are_computed_with_decimal_and_rounded_half_even() -> None:
    def one(p: str, b: str) -> str:
        r = rep(
            [
                row("rf:w1", "rk_000000000101", "Ours", True, thr=num(p)),
                row("rf:w1", "rk_000000000102", "B", False, thr=num(b)),
            ]
        )
        return r.speed_ratios[0].ratio

    assert one("1.005", "1") == "1.00"
    assert one("1.015", "1") == "1.02"
    assert one("1", "3") == "0.33"


def test_duplicates_collapse_and_order_is_stable() -> None:
    rows = [
        row("rf:w2", "rk_000000000201", "Z", True, thr=num("200")),
        row("rf:w2", "rk_000000000202", "B", False, thr=num("100")),
        row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
        row("rf:w1", "rk_000000000102", "DeiT-S", False, thr=num("100")),
        row("rf:w1", "rk_000000000103", "DeiT-S", False, thr=num("100")),
        row("rf:w1", "rk_000000000104", "Aaa", False, thr=num("90")),
    ]
    r = rep(rows)
    got = [(x.work_id, x.method, x.baseline_method) for x in r.speed_ratios]
    assert got == [("rf:w1", "Ours", "Aaa"), ("rf:w1", "Ours", "DeiT-S"), ("rf:w2", "Z", "B")]
    assert r.speed_unpaired == {}


def test_no_speed_rows_gives_empty() -> None:
    r = assemble_report(pilot_inputs())
    assert r.speed_ratios == [] and r.speed_unpaired == {}


def test_printed_fallback_with_scaled_unit_text() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=ff("3", unit="k img/s")),
            row("rf:w1", "rk_000000000102", "B", False, thr=ff("2", unit="k img/s")),
        ]
    )
    assert r.speed_ratios[0].ratio == "1.50" and r.speed_unpaired == {}


def test_conflicting_duplicates_are_ambiguous_not_silently_dropped() -> None:
    r = rep(
        [
            row("rf:w1", "rk_000000000101", "Ours", True, thr=num("180")),
            row("rf:w1", "rk_000000000102", "B", False, thr=num("100")),
            row("rf:w1", "rk_000000000103", "B", False, thr=num("50")),
        ]
    )
    assert r.speed_ratios == [] and r.speed_unpaired == {"ambiguous": 1}
