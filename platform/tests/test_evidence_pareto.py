"""Pure Pareto-frontier and speed-ratio helpers (plan E, task 1)."""

import itertools
import random
from decimal import Decimal

import pytest

from factory.evidence.pareto import ParetoResult, Point, pareto, speed_ratio


def P(k: str, cost: str, metric: str, method: str = "m", work: str = "rf:w") -> Point:
    return Point(k, Decimal(cost), Decimal(metric), method, work)


def keys(points: tuple[Point, ...]) -> list[str]:
    return [p.row_key for p in points]


def test_dominated_point_is_listed_with_its_dominator() -> None:
    pts = [P("a", "22", "79.8"), P("b", "25", "78.0"), P("c", "50", "83.0")]
    r = pareto(pts, higher_is_better=True)
    assert keys(r.frontier) == ["a", "c"]
    assert [(p.row_key, q.row_key) for p, q in r.dominated] == [("b", "a")]


def test_equal_cost_better_metric_dominates() -> None:
    r = pareto([P("a", "25", "78.0"), P("b", "25", "79.0")], higher_is_better=True)
    assert keys(r.frontier) == ["b"]
    assert [(p.row_key, q.row_key) for p, q in r.dominated] == [("a", "b")]


def test_identical_points_both_on_frontier() -> None:
    r = pareto([P("a", "22", "79.8"), P("b", "22", "79.8")], higher_is_better=True)
    assert {p.row_key for p in r.frontier} == {"a", "b"}
    assert r.dominated == ()


def test_same_metric_higher_cost_is_dominated() -> None:
    r = pareto([P("a", "22", "79.8"), P("b", "30", "79.8")], higher_is_better=True)
    assert keys(r.frontier) == ["a"]
    assert [(p.row_key, q.row_key) for p, q in r.dominated] == [("b", "a")]


def test_lower_is_better_flips_metric_order() -> None:
    pts = [P("a", "10", "5.0"), P("b", "20", "6.0"), P("c", "30", "3.0")]
    r = pareto(pts, higher_is_better=False)
    assert keys(r.frontier) == ["a", "c"]
    assert [(p.row_key, q.row_key) for p, q in r.dominated] == [("b", "a")]
    r2 = pareto(pts, higher_is_better=True)
    assert keys(r2.frontier) == ["a", "b"]


def test_single_point_and_empty() -> None:
    assert keys(pareto([P("a", "1", "1")], higher_is_better=True).frontier) == ["a"]
    assert pareto([], higher_is_better=True) == ParetoResult((), ())


@pytest.mark.parametrize("cost", ["0", "-1"])
def test_non_positive_cost_raises(cost: str) -> None:
    with pytest.raises(ValueError):
        pareto([P("a", "1", "1"), P("b", cost, "2")], higher_is_better=True)


def test_output_order_is_deterministic_under_input_permutation() -> None:
    pts = [
        P("a", "22", "79.8", "x"),
        P("b", "22", "79.8", "y"),
        P("c", "25", "78.0"),
        P("d", "50", "83.0"),
        P("e", "50", "81.0"),
        P("f", "10", "70.0"),
    ]
    expected = pareto(pts, higher_is_better=True)
    for perm in itertools.permutations(pts):
        assert pareto(perm, higher_is_better=True) == expected


def test_dominator_is_first_in_sorted_order() -> None:
    # b and c both dominate d; sorted order puts b (method "a") before c (method "b").
    pts = [P("d", "30", "70"), P("c", "10", "80", "b"), P("b", "10", "80", "a")]
    r = pareto(pts, higher_is_better=True)
    assert [(p.row_key, q.row_key) for p, q in r.dominated] == [("d", "b")]


def _dominates(q: Point, p: Point, hib: bool) -> bool:
    if q.cost > p.cost:
        return False
    at_least = q.metric >= p.metric if hib else q.metric <= p.metric
    strict = q.cost < p.cost or (q.metric > p.metric if hib else q.metric < p.metric)
    return at_least and strict


@pytest.mark.parametrize("hib", [True, False])
def test_properties_on_random_inputs(hib: bool) -> None:
    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(0, 12)
        pts = [P(f"r{i}", str(rng.randint(1, 6)), str(rng.randint(1, 6))) for i in range(n)]
        r = pareto(pts, higher_is_better=hib)
        assert len(r.frontier) + len(r.dominated) == n
        for p, q in itertools.product(r.frontier, r.frontier):
            assert not _dominates(q, p, hib)
        for p, q in r.dominated:
            assert q in r.frontier and _dominates(q, p, hib)
        shuffled = pts[:]
        rng.shuffle(shuffled)
        assert pareto(shuffled, higher_is_better=hib) == r


def test_speed_ratio() -> None:
    assert speed_ratio(Decimal("1800"), Decimal("1000"), higher_is_faster=True) == Decimal("1.80")
    assert speed_ratio(Decimal("10"), Decimal("18"), higher_is_faster=False) == Decimal("1.80")
    assert speed_ratio(Decimal("0"), Decimal("1"), higher_is_faster=True) is None
    assert speed_ratio(Decimal("1"), Decimal("-1"), higher_is_faster=False) is None


def test_speed_ratio_rounds_half_even_to_two_places() -> None:
    assert speed_ratio(Decimal("1.005"), Decimal("1"), higher_is_faster=True) == Decimal("1.00")
    assert speed_ratio(Decimal("1.015"), Decimal("1"), higher_is_faster=True) == Decimal("1.02")
    assert str(speed_ratio(Decimal("2"), Decimal("1"), higher_is_faster=True)) == "2.00"


_NON_FINITE = ["NaN", "sNaN", "Infinity", "-Infinity"]


@pytest.mark.parametrize("value", _NON_FINITE)
def test_non_finite_cost_raises_value_error(value: str) -> None:
    with pytest.raises(ValueError):
        pareto([P("a", "1", "1"), P("b", value, "2")], higher_is_better=True)


@pytest.mark.parametrize("value", _NON_FINITE)
def test_non_finite_metric_raises_value_error(value: str) -> None:
    for hib in (True, False):
        with pytest.raises(ValueError):
            pareto([P("a", "1", "1"), P("b", "2", value)], higher_is_better=hib)


def test_non_finite_error_names_only_the_row_identity() -> None:
    with pytest.raises(ValueError) as info:
        pareto([P("row-7", "NaN", "1", "meth", "rf:w9")], higher_is_better=True)
    assert str(info.value) == "non-finite cost or metric: meth/rf:w9/row-7"


def test_infinite_cost_is_rejected_before_sorting() -> None:
    # +inf is positive, so the non-positive check alone would let it through.
    with pytest.raises(ValueError):
        pareto([P("a", "Infinity", "1")], higher_is_better=True)


@pytest.mark.parametrize(
    ("proposed", "baseline"),
    [
        ("NaN", "1"),
        ("1", "NaN"),
        ("sNaN", "1"),
        ("1", "sNaN"),
        ("Infinity", "1"),
        ("1", "Infinity"),
        ("-Infinity", "1"),
        ("1", "-Infinity"),
    ],
)
@pytest.mark.parametrize("higher_is_faster", [True, False])
def test_speed_ratio_non_finite_input_is_none(
    proposed: str, baseline: str, higher_is_faster: bool
) -> None:
    result = speed_ratio(Decimal(proposed), Decimal(baseline), higher_is_faster=higher_is_faster)
    assert result is None


def test_speed_ratio_huge_and_tiny_values_do_not_raise() -> None:
    result = speed_ratio(Decimal("1E30"), Decimal("1E-30"), higher_is_faster=True)
    assert isinstance(result, Decimal)
    assert result == Decimal("1E60")


def test_speed_ratio_tiny_result_displays_as_zero() -> None:
    # Below the two-decimal resolution: a displayed 0.00 means "less than 0.005".
    assert speed_ratio(Decimal("1"), Decimal("1E30"), higher_is_faster=True) == Decimal("0.00")
