"""The shared work-id resolver (IDEA-66).

A Hangul word of a work id is stored decomposed (jamo: `normalize_title` applies NFKD), while a
model or a person writes it composed. `nfc_matches` (model) compares NFC forms; `stored_spelling`
and `resolve_work_id` (services) return the stored spelling, refuse an id that matches several
stored ids, and leave an id that matches none unchanged for the caller to refuse as before.
"""

import unicodedata

import pytest

from factory.errors import FactoryValidationError
from factory.model.work_ids import nfc_matches
from factory.services.work_ref import stored_spelling

STORED = unicodedata.normalize("NFD", "rf:ahn-과학-agents-1a2b3c4d")
COMPOSED = unicodedata.normalize("NFC", STORED)
# Two distinct stored strings with one NFC form: 한 as three jamo, and as the syllable 하 plus a
# final jamo. Neither is NFC; both compose to 한.
SPLIT = "rf:\u1112\u1161\u11ab-00000000"
PARTLY = "rf:\ud558\u11ab-00000000"


def test_the_two_spellings_differ_as_strings() -> None:
    assert STORED != COMPOSED


def test_nfc_matches_finds_the_stored_spelling() -> None:
    assert nfc_matches(COMPOSED, [STORED, "rf:other-00000000"]) == [STORED]


def test_nfc_matches_an_exact_id_first() -> None:
    assert nfc_matches(STORED, [STORED, COMPOSED]) == [STORED]


def test_nfc_matches_returns_every_match_when_not_exact() -> None:
    assert sorted(nfc_matches(unicodedata.normalize("NFC", SPLIT), [SPLIT, PARTLY])) == sorted(
        [SPLIT, PARTLY]
    )


def test_stored_spelling_of_a_composed_id_is_the_stored_one() -> None:
    assert stored_spelling(COMPOSED, {STORED, "rf:other-00000000"}) == STORED


def test_stored_spelling_of_an_exact_id_is_itself() -> None:
    assert stored_spelling(STORED, {STORED}) == STORED


def test_stored_spelling_of_an_unknown_id_is_unchanged() -> None:
    assert stored_spelling("rf:nobody-00000000", {STORED}) == "rf:nobody-00000000"


def test_stored_spelling_refuses_an_id_matching_several() -> None:
    with pytest.raises(FactoryValidationError) as caught:
        stored_spelling(unicodedata.normalize("NFC", SPLIT), {SPLIT, PARTLY}, field="target")
    (issue,) = caught.value.issues
    assert issue.field == "target"
    assert "several" in issue.reason
