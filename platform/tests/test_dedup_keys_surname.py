from __future__ import annotations

from factory.model.dedup_keys import first_surname, title_bucket_key
from tests.test_dedup_cascade import w


def test_first_surname_of_a_punctuation_only_name_is_empty() -> None:
    work = w("A title long enough", authors=["—"])
    assert first_surname(work) == ""
    assert title_bucket_key(work)[2] == ""


def test_first_surname_is_the_last_normalised_token() -> None:
    assert first_surname(w("A title long enough", authors=["Ada Zhou"])) == "zhou"
