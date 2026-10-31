import pytest

from factory.canonical import canonical_json


def test_canonical_json_sorts_keys_and_is_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, "é"]}) == '{"a":[1,"é"],"b":1}'.encode()


def test_canonical_json_is_utf8_without_ascii_escapes() -> None:
    assert canonical_json("é") == '"é"'.encode()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json(value)
