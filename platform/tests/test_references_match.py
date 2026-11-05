"""The title matcher (ruling 16). Every title and name is invented."""

import pytest

from factory.model.references import Confidence, LinkState
from factory.references import match as match_module
from factory.references.match import (
    MARGIN,
    MATCHER_VERSION,
    TITLE_FLOOR,
    TITLE_FUZZY,
    YEAR_TOLERANCE,
    Candidate,
    match_title,
    title_score,
)
from factory.references.parse import RefFields


def f(title: str | None, author: str | None = None, year: int | None = None) -> RefFields:
    return RefFields(None, None, None, year, author, title, None)


def cand(
    title: str, author: str | None = None, year: int | None = None, wid: str = "rf:a-00000001"
) -> Candidate:
    return Candidate(work_id=wid, title=title, first_author=author, year=year)


def test_constants() -> None:
    assert (MATCHER_VERSION, TITLE_FUZZY, TITLE_FLOOR, MARGIN, YEAR_TOLERANCE) == (
        "1",
        0.92,
        0.85,
        0.03,
        1,
    )


def test_title_exact_and_fuzzy_and_ambiguous() -> None:
    exact = match_title(
        f("Lattice Folding Is All You Need", "Quill", 2017),
        [cand("Lattice folding is all you need", "Ada Quill", 2017)],
    )
    assert exact.state is LinkState.RESOLVED
    assert exact.confidence is Confidence.TITLE_EXACT and exact.score == 1.0
    assert exact.work_id == "rf:a-00000001"
    punct = match_title(
        f("Lattice Folding Is All You Need", "Quill", 2017),
        [cand("Lattice Folding Is All You Need.", "Quill", 2018)],
    )
    assert punct.state is LinkState.RESOLVED
    near = [
        cand("Efficient Reed Transformers", "Lee", 2021, "rf:a-00000001"),
        cand("Efficient Reed Transformer", "Lee", 2021, "rf:a-00000002"),
    ]
    amb = match_title(f("Efficient reed transformers v2", "Lee", 2021), near)
    assert amb.state is LinkState.AMBIGUOUS and amb.work_id is None
    assert [c[0] for c in amb.candidates] == ["rf:a-00000001", "rf:a-00000002"]
    none = match_title(f("Unrelated topic entirely", None, None), [cand("Lattice folding")])
    assert none.state is LinkState.UNRESOLVED and none.reason == "below-floor"
    assert none.candidates == ()


def test_fuzzy_unique_best_is_unconfirmed() -> None:
    m = match_title(
        f("Efficient reed transformers v2", "Lee", 2021),
        [cand("Efficient Reed Transformers", "Lee", 2021), cand("Moss growth", "Lee", 2021)],
    )
    assert m.state is LinkState.UNCONFIRMED
    assert m.confidence is Confidence.TITLE_FUZZY and m.work_id == "rf:a-00000001"
    assert m.score is not None and TITLE_FUZZY <= m.score < 1


def test_year_gap_blocks_exact_and_fuzzy() -> None:
    m = match_title(
        f("Lattice folding is all you need", "Quill", 2015),
        [cand("Lattice folding is all you need", "Quill", 2018)],
    )
    assert m.state is LinkState.AMBIGUOUS
    m = match_title(
        f("Efficient reed transformers v2", "Lee", 2015),
        [cand("Efficient Reed Transformers", "Lee", 2021)],
    )
    assert m.state is LinkState.AMBIGUOUS


def test_surname_mismatch_blocks_exact() -> None:
    m = match_title(
        f("Lattice folding is all you need", "Quill", 2017),
        [cand("Lattice folding is all you need", "Bram Other", 2017)],
    )
    assert m.state is not LinkState.RESOLVED


def test_checks_only_when_both_sides_present() -> None:
    m = match_title(f("Lattice folding is all you need"), [cand("Lattice folding is all you need")])
    assert m.state is LinkState.RESOLVED
    m = match_title(
        f("Lattice folding is all you need", "Quill", 2017),
        [cand("Lattice folding is all you need", None, None)],
    )
    assert m.state is LinkState.RESOLVED


def test_two_exact_candidates_are_ambiguous() -> None:
    m = match_title(
        f("Lattice folding", "Quill", 2017),
        [
            cand("Lattice folding", "Quill", 2017, "rf:b-00000002"),
            cand("Lattice Folding.", "Quill", 2017, "rf:a-00000001"),
        ],
    )
    assert m.state is LinkState.AMBIGUOUS
    assert [c[0] for c in m.candidates] == ["rf:a-00000001", "rf:b-00000002"]


def test_between_floor_and_fuzzy_is_ambiguous() -> None:
    title = "Counting reeds by echo in shallow water"
    other = "Counting reeds by sonar in shallow water"
    score = title_score(title, other)
    assert TITLE_FLOOR <= score < TITLE_FUZZY
    m = match_title(f(title, "Reyes", 2011), [cand(other, "Reyes", 2011)])
    assert m.state is LinkState.AMBIGUOUS


def test_no_title_or_no_candidates() -> None:
    assert match_title(f(None), [cand("x")]).reason == "no-title"
    assert match_title(f("..."), [cand("x")]).reason == "no-title"
    assert match_title(f("Lattice folding"), []).reason == "no-candidates"


def test_candidates_capped_at_three_sorted() -> None:
    cands = [cand("Lattice folding is all you need", wid=f"rf:a-0000000{i}") for i in range(5)]
    m = match_title(f("Lattice folding is all you need"), cands)
    assert m.state is LinkState.AMBIGUOUS
    assert [c[0] for c in m.candidates] == ["rf:a-00000000", "rf:a-00000001", "rf:a-00000002"]


def test_deterministic_regardless_of_order() -> None:
    near = [
        cand("Efficient Reed Transformers", "Lee", 2021, "rf:a-00000001"),
        cand("Efficient Reed Transformer", "Lee", 2021, "rf:a-00000002"),
    ]
    a = match_title(f("Efficient reed transformers v2", "Lee", 2021), near)
    b = match_title(f("Efficient reed transformers v2", "Lee", 2021), near[::-1])
    assert a == b


def test_a_prepared_candidate_title_is_not_normalised_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final review 7: a corpus title is normalised once, not once per entry."""
    candidates = [
        Candidate("rf:a-00000001", "Moss Growth", None, None, normalized="moss growth"),
        Candidate("rf:b-00000002", "Reed Beds", None, None, normalized="reed beds"),
    ]
    seen: list[str] = []
    real = match_module.normalize_title

    def counted(title: str) -> str:
        seen.append(title)
        return real(title)

    monkeypatch.setattr(match_module, "normalize_title", counted)
    assert match_title(f("Moss growth"), candidates).work_id == "rf:a-00000001"
    assert "Reed Beds" not in seen and "Moss Growth" not in seen


def test_a_candidate_without_a_prepared_title_is_normalised() -> None:
    assert match_title(f("Moss growth"), [cand("MOSS: Growth!")]).state is LinkState.RESOLVED
