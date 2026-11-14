from factory.services.background import background_counts, background_works

CRITERIA = {"w1": "EX01", "w2": "EX02", "w3": None, "w4": "EX02"}


def test_works_under_declared_ids_only() -> None:
    assert background_works(CRITERIA, {"EX02"}) == {"w2": "EX02", "w4": "EX02"}


def test_no_declaration_gives_nothing() -> None:
    assert background_works(CRITERIA, set()) == {}
    assert background_counts({"EX01": 3}, set()) == {}


def test_counts_are_a_subset_of_excluded() -> None:
    excluded = {"EX01": 3, "EX02": 2, "unspecified": 1}
    counts = background_counts(excluded, {"EX02", "EX09"})
    assert counts == {"EX02": 2}
    assert sum(counts.values()) <= sum(excluded.values())
