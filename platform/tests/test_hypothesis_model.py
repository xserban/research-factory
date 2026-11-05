"""The hypothesis spec, the decision-rule menu and the `H@` hash (slice 6, plan H-C task 3)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from factory.model.hypotheses import (
    HypothesisSpec,
    MethodRef,
    falsifier_text,
    hypothesis_version,
)

CARD_A = "mcd_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
CARD_B = "mcd_01JZ9Q3K5M7N8P0R2S4T6V8W0Y"


def spec_dict(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "experiment",
        "statement": "Linear attention matches softmax attention on top-1 accuracy.",
        "treatment": {"card": CARD_A},
        "baseline": {"card": CARD_B},
        "metric": {
            "name": "top-1 accuracy",
            "direction": "higher",
            "unit_family": "score",
            "unit": "points",
        },
        "conditions": {"dataset": "ImageNet-1k", "resolution": "224"},
        "prediction": {"direction": "treatment-better", "margin": "0.5", "unit": "points"},
        "decision_rule": {"rule": "superiority"},
        "test": {"kind": "experiment"},
        "rationale": "because",
    }
    base.update(over)
    return base


def build(**over: Any) -> HypothesisSpec:
    return HypothesisSpec.model_validate(spec_dict(**over))


def literature(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "literature",
        "decision_rule": {"rule": "literature-direction", "n_min": 5, "q": "0.8"},
        "test": {"kind": "literature", "window_start": "2026-01-01", "sources": ["run_b", "run_a"]},
    }
    base.update(over)
    return base


def test_statement_change_keeps_h_version() -> None:  # acceptance 9
    one = build()
    two = build(statement="A different sentence.", rationale="other", alternatives=[], lead=None)
    three = build(lead="led_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    assert hypothesis_version(one) == hypothesis_version(two) == hypothesis_version(three)
    assert hypothesis_version(one).startswith("H@") and len(hypothesis_version(one)) == 10


@pytest.mark.parametrize(
    "change",
    [
        {"prediction": {"direction": "treatment-better", "margin": "1.0", "unit": "points"}},
        {"conditions": {"dataset": "ImageNet-1k", "resolution": "384"}},
        {"conditions": {"dataset": "ImageNet-1k"}},
        {"treatment": {"card": CARD_B}, "baseline": {"card": CARD_A}},
        {"metric": {"name": "top-5", "direction": "higher", "unit_family": "score"}},
        {
            "prediction": {"direction": "no-worse", "margin": "0.5", "unit": "points"},
            "decision_rule": {"rule": "non-inferiority"},
        },
        {"treatment": {"card": CARD_A, "row_key": "rk_0123456789ab"}},
    ],
)
def test_margin_rule_conditions_change_h_version(change: dict[str, Any]) -> None:  # acceptance 9
    assert hypothesis_version(build(**change)) != hypothesis_version(build())


def test_literature_hash_ignores_source_order_and_follows_window() -> None:
    base = build(**literature())
    swapped = build(
        **literature(
            test={"kind": "literature", "window_start": "2026-01-01", "sources": ["run_a", "run_b"]}
        )
    )
    later = build(
        **literature(test={"kind": "literature", "window_start": "2026-02-01", "sources": []})
    )
    assert hypothesis_version(base) == hypothesis_version(swapped)
    assert hypothesis_version(base) != hypothesis_version(later)


def test_h_version_independent_of_dict_order() -> None:
    forward = build(conditions={"a": "1", "b": "2"})
    backward = build(conditions={"b": "2", "a": "1"})
    assert hypothesis_version(forward) == hypothesis_version(backward)
    dump = json.loads(forward.model_dump_json())
    assert hypothesis_version(HypothesisSpec.model_validate(dump)) == hypothesis_version(forward)


def test_rule_kind_compatibility() -> None:
    with pytest.raises(ValidationError):  # an experiment cannot use the literature rule
        build(decision_rule={"rule": "literature-direction", "n_min": 3, "q": "0.8"})
    with pytest.raises(ValidationError):  # a literature hypothesis needs it
        build(kind="literature", test={"kind": "literature", "window_start": "2026-01-01"})
    with pytest.raises(ValidationError):  # kind and test must agree
        build(test={"kind": "literature", "window_start": "2026-01-01"})
    with pytest.raises(ValidationError):  # `no-worse` goes with non-inferiority only
        build(prediction={"direction": "no-worse", "margin": "0.5"})
    with pytest.raises(ValidationError):
        build(decision_rule={"rule": "non-inferiority"})
    assert build(**literature())
    for q in ("0.5", "1.5", "x"):
        with pytest.raises(ValidationError):
            build(**literature(decision_rule={"rule": "literature-direction", "n_min": 5, "q": q}))
    with pytest.raises(ValidationError):
        build(**literature(decision_rule={"rule": "literature-direction", "n_min": 0, "q": "0.8"}))
    with pytest.raises(ValidationError):
        build(decision_rule={"rule": "bootstrap"})


def test_method_ref_exactly_one() -> None:
    assert MethodRef(name="softmax attention", row_key="rk_0123456789ab")
    with pytest.raises(ValidationError):
        MethodRef()
    with pytest.raises(ValidationError):
        MethodRef(card=CARD_A, name="both")
    with pytest.raises(ValidationError):
        MethodRef(idea="ida_01JZ9Q3K5M7N8P0R2S4T6V8W0X", card=CARD_A)
    with pytest.raises(ValidationError):
        MethodRef(card="nope")
    with pytest.raises(ValidationError):
        MethodRef(name="x", row_key="rk_short")


def test_margin_is_a_non_negative_decimal() -> None:
    for margin in ("-1", "abc", "1e3", ""):
        with pytest.raises(ValidationError):
            build(prediction={"direction": "treatment-better", "margin": margin})


def test_falsifier_text_fixed_sentences() -> None:
    assert falsifier_text(build()) == (
        "Refuted if the 95% CI upper bound of (treatment \N{MINUS SIGN} baseline) on top-1 "
        "accuracy (dataset=ImageNet-1k, resolution=224) is below 0.5 points."
    )
    assert falsifier_text(build(), confidence="0.99").startswith("Refuted if the 99% CI")
    lower = build(
        metric={"name": "latency", "direction": "lower", "unit_family": "other"},
        prediction={"direction": "no-worse", "margin": "2", "unit": "ms"},
        decision_rule={"rule": "non-inferiority"},
        conditions={},
    )
    assert falsifier_text(lower) == (
        "Refuted if the 95% CI upper bound of (baseline \N{MINUS SIGN} treatment) on latency "
        "is below \N{MINUS SIGN}2 ms."
    )
    assert falsifier_text(build(**literature())) == (
        "Refuted if at least 80% of at least 5 later-literature comparisons of treatment and "
        "baseline on top-1 accuracy (dataset=ImageNet-1k, resolution=224) favour the baseline."
    )


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        build(state="registered")
