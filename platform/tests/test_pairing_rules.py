"""Pairing and decision rules (slice 6, plan XP-B task 2; acceptance 15 and 18)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.hypotheses.pairing import RunFact, pair_runs
from factory.hypotheses.rules import (
    Favour,
    apply_experiment_rule,
    apply_literature_rule,
    favour_of,
)
from factory.hypotheses.stats import paired_summary
from factory.model.experiments import Cell
from factory.model.hypotheses import LiteratureDirection, NonInferiority, Superiority

UNIVERSE = {"resolution": "224"}
FACTOR = frozenset({"attention"})


def fact(
    run: str,
    arm: str,
    seed: int,
    value: str | None,
    *,
    order: int = 0,
    flags: tuple[str, ...] = (),
    split: str = "confirmatory",
    extra: dict[str, str] | None = None,
    resolution: str = "224",
) -> RunFact:
    config = {
        "attention": "linear" if arm == "treatment" else "softmax",
        "resolution": resolution,
        "seed": str(seed),
    }
    config.update(extra or {})
    return RunFact(
        run_id=run,
        cell=Cell(
            universe=(("resolution", resolution),),
            seed=seed,
            arm=arm,  # type: ignore[arg-type]
            split=split,  # type: ignore[arg-type]
        ),
        config=config,
        value=None if value is None else Decimal(value),
        flags=frozenset(flags),
        reported_order=order,
    )


def table(treatment: list[str], baseline: list[str]) -> list[RunFact]:
    out: list[RunFact] = []
    for i, (t, b) in enumerate(zip(treatment, baseline, strict=True), start=1):
        out.append(fact(f"t{i}", "treatment", i, t, order=2 * i))
        out.append(fact(f"b{i}", "baseline", i, b, order=2 * i + 1))
    return out


def pairing(facts: list[RunFact]):  # type: ignore[no-untyped-def]
    return pair_runs(
        facts, differing_keys=FACTOR, universe=UNIVERSE, split="confirmatory", direction="higher"
    )


@pytest.mark.parametrize(
    ("rule", "diffs", "outcome", "low", "high"),
    [
        (Superiority(), ["1.0", "1.2", "0.8"], "supported", "0.503167", "1.496833"),
        (Superiority(), ["-1.0", "-1.2", "-0.8"], "refuted", "-1.496833", "-0.503167"),
        (Superiority(), ["0.9", "0.1", "0.5"], "inconclusive", "-0.493666", "1.493666"),
        (NonInferiority(), ["0.1", "-0.1", "0.3"], "supported", "-0.396833", "0.596833"),
        (NonInferiority(), ["-1.0", "-1.2", "-0.8"], "refuted", "-1.496833", "-0.503167"),
        (NonInferiority(), ["-0.6", "0.4", "0.0"], "inconclusive", None, None),
    ],
)
def test_hand_computed_outcomes(
    rule: Superiority | NonInferiority,
    diffs: list[str],
    outcome: str,
    low: str | None,
    high: str | None,
) -> None:
    # hand computation: sd 0.2, se 0.2 / sqrt(3) = 0.115470, half width 4.3027 * se = 0.496833
    summary = paired_summary([Decimal(d) for d in diffs], "0.95")
    result = apply_experiment_rule(rule, Decimal("0.5"), summary, min_seeds=3)
    assert result.outcome == outcome
    if low is not None:
        assert (summary.ci_low, summary.ci_high) == (Decimal(low), Decimal(high))
    assert result.flags == frozenset()


def test_boundary_equality_is_not_support() -> None:
    summary = paired_summary([Decimal(d) for d in ("1.0", "1.0", "1.0")], "0.95")
    assert apply_experiment_rule(Superiority(), Decimal("1"), summary, min_seeds=3).outcome == (
        "inconclusive"
    )


def test_too_few_pairs_inconclusive() -> None:
    summary = paired_summary([Decimal("5")], "0.95")
    result = apply_experiment_rule(Superiority(), Decimal("0"), summary, min_seeds=3)
    assert result.outcome == "inconclusive"
    assert result.flags == frozenset({"too-few-pairs", "below-min-seeds"})


def test_below_min_seeds_flag() -> None:
    summary = paired_summary([Decimal("5"), Decimal("6")], "0.95")
    result = apply_experiment_rule(Superiority(), Decimal("0"), summary, min_seeds=3)
    assert "below-min-seeds" in result.flags and "too-few-pairs" not in result.flags


def test_pairs_oriented_for_lower_is_better() -> None:
    result = pair_runs(
        table(["10", "12"], ["13", "11"]),
        differing_keys=FACTOR,
        universe=UNIVERSE,
        split="confirmatory",
        direction="lower",
    )
    assert [d for _, _, d in result.pairs] == [Decimal(3), Decimal(-1)]
    assert result.seeds == (1, 2)


def test_confounded_pair_excluded() -> None:
    facts = table(["10", "11", "12"], ["8", "9", "10"])
    facts[2] = fact("t2", "treatment", 2, "11", order=4, extra={"lr": "0.01"})  # differs in lr too
    result = pairing(facts)
    assert [(t, b) for t, b, _ in result.pairs] == [("t1", "b1"), ("t3", "b3")]
    assert result.confounded == (("t2", "b2"),)


def test_failed_and_environment_runs_excluded_with_reason() -> None:
    facts = table(["10", "11", "12", "13"], ["8", "9", "10", "11"])
    facts[0] = fact("t1", "treatment", 1, None, order=2, flags=("failed",))
    facts[2] = fact("t2", "treatment", 2, "11", order=4, flags=("environment-differs",))
    result = pairing(facts)
    assert [(t, b) for t, b, _ in result.pairs] == [("t3", "b3"), ("t4", "b4")]
    assert result.excluded["t1"] == ("failed",)
    assert result.excluded["t2"] == ("environment-differs",)
    assert result.excluded["b1"] == ("missing-partner",)
    assert result.excluded["b2"] == ("missing-partner",)


def test_earliest_run_used_others_listed() -> None:
    facts = table(["10", "11", "12"], ["8", "9", "10"])
    facts.append(fact("t1-again", "treatment", 1, "99", order=100))
    facts.append(fact("t2-first-failed", "treatment", 2, None, order=0, flags=("failed",)))
    result = pairing(facts)
    assert result.extra_runs == ("t1-again",)
    assert [d for _, _, d in result.pairs] == [Decimal(2), Decimal(2), Decimal(2)]


def test_split_and_universe_are_respected() -> None:
    facts = table(["10", "11", "12"], ["8", "9", "10"])
    facts.append(fact("dev", "treatment", 1, "50", split="dev"))
    facts.append(fact("other", "treatment", 1, "60", resolution="384"))
    result = pairing(facts)
    assert result.extra_runs == () and len(result.pairs) == 3


def test_literature_insufficient_evidence() -> None:
    rule = LiteratureDirection(n_min=4, q="0.75")
    result = apply_literature_rule(rule, ["treatment", "treatment", "treatment"])
    assert result.outcome == "inconclusive" and result.flags == frozenset({"insufficient-evidence"})
    assert result.counts["n"] == 3


def test_literature_supported_and_refuted() -> None:
    rule = LiteratureDirection(n_min=4, q="0.75")
    supported: list[Favour] = ["treatment", "treatment", "treatment", "baseline"]
    assert apply_literature_rule(rule, supported).outcome == "supported"  # 3/4 >= 0.75
    refuted: list[Favour] = ["baseline", "baseline", "baseline", "tie"]
    assert apply_literature_rule(rule, refuted).outcome == "refuted"
    mixed: list[Favour] = ["treatment", "treatment", "baseline", "baseline"]
    assert apply_literature_rule(rule, mixed).outcome == "inconclusive"
    ties: list[Favour] = ["treatment", "treatment", "tie", "tie"]
    result = apply_literature_rule(rule, ties)
    assert result.outcome == "inconclusive" and result.counts["ties"] == 2


def test_favour_of_margin_and_direction() -> None:
    m = Decimal("1")
    assert favour_of(Decimal("5"), Decimal("3"), "higher", m) == "treatment"
    assert favour_of(Decimal("3"), Decimal("5"), "higher", m) == "baseline"
    assert favour_of(Decimal("3.5"), Decimal("3"), "higher", m) == "tie"
    assert favour_of(Decimal("3"), Decimal("5"), "lower", m) == "treatment"
