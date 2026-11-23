"""Feed ranker: synthetic vectors, no model. Ported from arXiv Miner's ranker tests."""

from __future__ import annotations

import json
import random

import pytest

from factory.errors import FactoryValidationError
from factory.services import feed_ranker as fr

pytest.importorskip("sklearn")
DIMS = 16


def _vec(rng: random.Random, shift: float) -> list[float]:
    return [rng.gauss(0, 1) + shift for _ in range(DIMS)]


def _data(
    n_like: int = 10, n_dis: int = 10, seed: int = 1
) -> tuple[dict[str, bool], dict[str, list[float]]]:
    rng = random.Random(seed)
    labels: dict[str, bool] = {}
    vecs: dict[str, list[float]] = {}
    for i in range(n_like):
        labels[f"2401.{i:05d}"] = True
        vecs[f"2401.{i:05d}"] = _vec(rng, 1)
    for i in range(n_dis):
        labels[f"2402.{i:05d}"] = False
        vecs[f"2402.{i:05d}"] = _vec(rng, -1)
    return labels, vecs


def test_threshold_reasons() -> None:
    assert fr.check_thresholds(dict.fromkeys("abcde", True)) is None
    s = fr.check_thresholds({"a": True, "b": True, "c": False, "d": False, "e": False})
    assert s is not None and s.likes == 2 and "likes" in s.reason and "reactions" not in s.reason
    s2 = fr.check_thresholds({"a": True, "b": True, "c": True})
    assert s2 is not None and "reactions" in s2.reason
    with pytest.raises(FactoryValidationError):
        fr.train({"a": True}, {"a": [0.0] * DIMS})


def test_train_scores_positive_above_negative() -> None:
    labels, vecs = _data()
    state = fr.train(labels, vecs, embedding_model="m")
    assert state.has_classifier and state.n_likes == 10 and state.n_dislikes == 10
    rng = random.Random(99)
    pos, neg = _vec(rng, 1), _vec(rng, -1)
    s = fr.score(state, {"p": pos, "n": neg})
    assert s["p"] > s["n"] and all(0 <= v <= 1 for v in s.values())


def test_no_dislikes_falls_back_to_cosine() -> None:
    labels, vecs = _data(n_like=5, n_dis=0)
    state = fr.train(labels, vecs)
    assert not state.has_classifier and state.coef is None
    near = fr.score(state, {"x": list(state.profile)})["x"]
    far = fr.score(state, {"x": [-v for v in state.profile]})["x"]
    assert near > 0.99 and far < 0.01


def test_missing_vector_and_ragged_refused() -> None:
    labels, vecs = _data()
    del vecs["2401.00000"]
    with pytest.raises(FactoryValidationError):
        fr.train(labels, vecs)
    labels, vecs = _data()
    vecs["2401.00001"] = vecs["2401.00001"][:12]
    with pytest.raises(FactoryValidationError):
        fr.train(labels, vecs)


def test_deterministic_and_round_trip() -> None:
    labels, vecs = _data()
    a = fr.train(labels, vecs, embedding_model="m")
    b = fr.train(dict(reversed(list(labels.items()))), vecs, embedding_model="m")
    assert a.to_json() == b.to_json()
    back = fr.RankerState.from_json(a.to_json())
    assert back == a and back.to_json() == a.to_json()
    probe = {"x": vecs["2401.00000"], "y": vecs["2402.00000"]}
    assert fr.score(back, probe) == fr.score(a, probe)
    assert "pickle" not in a.to_json()


def test_training_set_hash_is_order_free_and_label_sensitive() -> None:
    h = fr.training_set_hash({"a": True, "b": False})
    assert h == fr.training_set_hash({"b": False, "a": True})
    assert h != fr.training_set_hash({"a": False, "b": False})


@pytest.mark.parametrize("text", ["", "{", "[]", '{"format": 2}', '{"format": 1}'])
def test_damaged_state_refused(text: str) -> None:
    with pytest.raises(FactoryValidationError):
        fr.RankerState.from_json(text)


def test_inconsistent_state_refused() -> None:
    labels, vecs = _data()
    d = json.loads(fr.train(labels, vecs).to_json())
    d["coef"] = d["coef"][:3]
    with pytest.raises(FactoryValidationError):
        fr.RankerState.from_json(json.dumps(d))


def test_order_ties_by_id() -> None:
    assert fr.order({"b": 0.5, "a": 0.5, "c": 0.9}) == ["c", "a", "b"]


def test_dimension_mismatch_refused() -> None:
    labels, vecs = _data()
    with pytest.raises(FactoryValidationError):
        fr.score(fr.train(labels, vecs), {"x": [0.0] * 5})
