import pytest

from factory.exports.keys import assign_keys, bib_key


def test_key_drops_prefix_and_hash() -> None:
    assert (
        bib_key("rf:katharopoulos2020-transformers-are-rnns-1a2b3c4d")
        == "katharopoulos2020-transformers-are-rnns"
    )


def test_assign_is_order_independent() -> None:
    ids = ["rf:b2020-x-11111111", "rf:a2019-y-22222222"]
    assert assign_keys(ids) == assign_keys(reversed(ids))


def test_collision_uses_full_suffix() -> None:
    k = assign_keys(["rf:smith2020-attention-11111111", "rf:smith2020-attention-22222222"])
    assert set(k.values()) == {"smith2020-attention-11111111", "smith2020-attention-22222222"}


def test_collision_changes_only_colliding_keys() -> None:
    before = assign_keys(["rf:smith2020-attention-11111111", "rf:a2019-y-22222222"])
    after = assign_keys(
        [
            "rf:smith2020-attention-11111111",
            "rf:a2019-y-22222222",
            "rf:smith2020-attention-33333333",
        ]
    )
    assert before["rf:a2019-y-22222222"] == after["rf:a2019-y-22222222"] == "a2019-y"
    assert before["rf:smith2020-attention-11111111"] == "smith2020-attention"
    assert after["rf:smith2020-attention-11111111"] == "smith2020-attention-11111111"


def test_keys_are_ascii() -> None:
    key = bib_key("rf:müller2020-übung-11111111")
    assert key == "muller2020-ubung"
    assert key.isascii()


def test_invalid_work_id_raises() -> None:
    with pytest.raises(ValueError):
        bib_key("not-a-work-id")
    with pytest.raises(ValueError):
        assign_keys(["rf:nohash"])
