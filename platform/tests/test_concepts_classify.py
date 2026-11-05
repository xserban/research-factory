"""Pure rules of the `uses` classification and the cycle test (slice 3c, plan G3-B, task 1)."""

from __future__ import annotations

from typing import Any

import pytest

from factory.intuition.classify import classify_use, fold, name_in_text, source_digest, would_cycle
from factory.model.intuition import ConceptSourceInput

P8 = "rf:p8-00000008"
P9 = "rf:p9-00000009"


def base(over: dict[str, Any]) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "from_kind": "paper",
        "names": ["random features"],
        "quote": None,
        "cited_work": None,
        "link_resolved": None,
        "source_work": None,
        "source_approved": False,
    }
    kw.update(over)
    return kw


def test_fold_nfkc_casefold_whitespace() -> None:
    assert fold("  Random" + chr(0xA0) + " FEATURES ") == "random features"


def test_name_in_quote_whole_word_folded() -> None:  # Review Focus 2
    assert name_in_text(["Random Features"], "we use random  features to approximate")
    assert not name_in_text(["kernel"], "positive kernels only")
    assert not name_in_text(["kernel"], "a nonkernel method")
    assert name_in_text(["kernel trick", "RFF"], "via RFF.")
    assert not name_in_text([], "anything")
    assert not name_in_text([" "], "anything")


def test_classify_quote_and_citation() -> None:
    assert classify_use(**base({"quote": "…random features…"})) == ("stated", "name-in-quote")
    kw = base(
        {
            "names": ["x"],
            "cited_work": P9,
            "link_resolved": True,
            "source_work": P9,
            "source_approved": True,
        }
    )
    assert classify_use(**kw) == ("stated", "cites-approved-source")


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"quote": "no name here"}, "name-not-in-quote"),
        ({"cited_work": None, "link_resolved": False}, "citation-unresolved"),
        (
            {"cited_work": P9, "link_resolved": False, "source_work": P9, "source_approved": True},
            "citation-unresolved",
        ),
        (
            {"cited_work": P8, "link_resolved": True, "source_work": P9, "source_approved": True},
            "citation-not-approved-source",
        ),
        (
            {"cited_work": P9, "link_resolved": True, "source_work": P9, "source_approved": False},
            "source-unapproved",
        ),
        (
            {"cited_work": P9, "link_resolved": True, "source_work": None, "source_approved": True},
            "source-not-in-corpus",
        ),
        ({}, "no-basis"),
    ],
)
def test_inferred_reasons(kw: dict[str, Any], reason: str) -> None:
    assert classify_use(**base(kw)) == ("inferred", reason)


def test_concept_to_concept_always_inferred() -> None:
    got = classify_use(**base({"from_kind": "concept", "quote": "random features"}))
    assert got == ("inferred", "concept-to-concept")


def test_quote_wins_over_citation_when_both_given() -> None:
    kw = base({"quote": "random features", "cited_work": P8})
    assert classify_use(**kw) == ("stated", "name-in-quote")


def test_would_cycle() -> None:
    assert would_cycle({("a", "b"), ("b", "c")}, ("c", "a"))
    assert would_cycle(set(), ("a", "a"))
    assert not would_cycle({("a", "b")}, ("a", "c"))
    assert not would_cycle({("a", "b"), ("c", "b")}, ("a", "c"))


def test_digest_stable_and_kind_sensitive() -> None:
    a = ConceptSourceInput(kind="textbook", citation="Book, ch. 3")  # type: ignore[arg-type]
    b = ConceptSourceInput(kind="textbook", citation="Book, ch. 3")  # type: ignore[arg-type]
    c = ConceptSourceInput(kind="survey", citation="Book, ch. 3")  # type: ignore[arg-type]
    d = ConceptSourceInput(kind="corpus-paper", citation="Book, ch. 3", work_id=P9)  # type: ignore[arg-type]
    assert source_digest(a) == source_digest(b)
    assert len({source_digest(x) for x in (a, c, d)}) == 3
    assert source_digest(a).startswith("src_") and len(source_digest(a)) == 4 + 16
