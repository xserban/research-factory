"""Tests for the domain pack registry and the ml-benchmark pack."""

import re

from factory.packs import ML_BENCHMARK_V1, Check, FieldKind, UnitFamily, get_pack


def test_required_and_default_keys_are_fields() -> None:
    names = {f.name for f in ML_BENCHMARK_V1.fields}
    assert set(ML_BENCHMARK_V1.required) <= names
    assert set(ML_BENCHMARK_V1.default_comparability_keys) <= names
    assert ML_BENCHMARK_V1.required == ("method_name", "task", "dataset", "metric", "value")
    assert ML_BENCHMARK_V1.default_comparability_keys == (
        "task",
        "dataset",
        "split",
        "metric",
        "input_resolution",
        "pretraining_data",
    )


def test_registry() -> None:
    assert get_pack("ml-benchmark", 1) is ML_BENCHMARK_V1
    assert get_pack("ml-benchmark", 2) is None
    assert get_pack("x", 1) is None
    assert ML_BENCHMARK_V1.name == "ml-benchmark" and ML_BENCHMARK_V1.version == 1


def test_flops_and_macs_are_separate_count_fields() -> None:
    for n in ("flops", "macs", "params"):
        f = ML_BENCHMARK_V1.field(n)
        assert f is not None and f.unit_family is UnitFamily.COUNT
        assert f.units == ("K", "M", "G", "T", "B", "")
    assert ML_BENCHMARK_V1.field("nope") is None


def test_checked_fields_have_checkable_kinds() -> None:
    for f in ML_BENCHMARK_V1.fields:
        if f.check is not Check.NONE:
            assert f.kind in (FieldKind.TEXT, FieldKind.NUMBER, FieldKind.INTEGER)


def test_names_unique_and_well_formed() -> None:
    names = [f.name for f in ML_BENCHMARK_V1.fields]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"^[a-z][a-z_]*$", n) for n in names)


def test_groups_checks_and_units() -> None:
    groups = {f.group for f in ML_BENCHMARK_V1.fields}
    assert groups == {"identity", "task", "result", "cost", "regime"}
    for n in ("method_name", "dataset", "metric"):
        f = ML_BENCHMARK_V1.field(n)
        assert f is not None and f.check is Check.TEXT_IN_QUOTE
    for n in ("value", "variance_value"):
        f = ML_BENCHMARK_V1.field(n)
        assert f is not None and f.unit_family is UnitFamily.SCORE
        assert f.units == ("%", "fraction", "") and f.check is Check.NUMBER
    for n in ("throughput", "latency", "memory"):
        f = ML_BENCHMARK_V1.field(n)
        assert f is not None and f.unit_family is UnitFamily.OTHER
    res = ML_BENCHMARK_V1.field("input_resolution")
    assert res is not None and res.normaliser == "resolution"


def test_ml_benchmark_v1_digest_is_pinned() -> None:
    import hashlib

    digest = hashlib.sha256(repr(ML_BENCHMARK_V1).encode()).hexdigest()
    assert digest == "5fdd9feebcb541f8bb73b0a7a8700a40abc86e08842d8ed7849d801582af05cc", (
        "packs are versioned: add a new version"
    )
