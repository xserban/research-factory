"""The stated/inferred rule (slice 3b ruling 11; acceptance 8)."""

from __future__ import annotations

import pytest

from factory.lineage.classify import (
    CLASSIFIER_VERSION,
    BasisFacts,
    LinkFacts,
    classify,
)
from factory.model.lineage import StatusReason
from factory.model.references import LinkState

B_ = "rf:b-00000001"
C_ = "rf:c-00000002"


def basis(cited: int | None) -> BasisFacts:
    return BasisFacts(item_kind="base-idea", cited_entry=cited, reference_extraction_id="rex_X")


def link(state: str, work: str | None) -> LinkFacts:
    return LinkFacts(state=LinkState(state), work_id=work)


@pytest.mark.parametrize(
    "facts,lnk,target,idea,expected",
    [
        (None, None, B_, False, ("inferred", StatusReason.NO_BASIS)),
        (basis(None), None, B_, False, ("inferred", StatusReason.NO_CITED_ENTRY)),
        (basis(5), None, B_, False, ("inferred", StatusReason.NO_CITED_ENTRY)),
        (basis(5), link("unconfirmed", B_), B_, False, ("inferred", StatusReason.LINK_UNCONFIRMED)),
        (basis(5), link("ambiguous", None), B_, False, ("inferred", StatusReason.LINK_UNCONFIRMED)),
        (
            basis(5),
            link("unresolved", None),
            B_,
            False,
            ("inferred", StatusReason.LINK_UNCONFIRMED),
        ),
        (basis(5), link("resolved", C_), B_, False, ("inferred", StatusReason.TARGET_DIFFERS)),
        (basis(5), link("resolved", B_), "ida_X", True, ("inferred", StatusReason.TARGET_DIFFERS)),
        (basis(5), link("resolved", B_), B_, False, ("stated", None)),
    ],
)
def test_classification(
    facts: BasisFacts | None,
    lnk: LinkFacts | None,
    target: str,
    idea: bool,
    expected: tuple[str, StatusReason | None],
) -> None:
    got = classify(facts, lnk, target, target_is_idea=idea, target_cited=True)
    assert (got.status, got.reason) == expected


def test_uncited_base_flag() -> None:
    flagged = classify(None, None, B_, target_is_idea=False, target_cited=False)
    assert "uncited-base" in flagged.flags
    assert (
        "uncited-base"
        not in classify(None, None, B_, target_is_idea=False, target_cited=True).flags
    )
    assert not classify(None, None, "ida_X", target_is_idea=True, target_cited=False).flags


def test_resolved_target_reported_even_when_differs() -> None:
    got = classify(basis(5), link("resolved", C_), B_, target_is_idea=False, target_cited=True)
    assert got.resolved_target == C_
    stated = classify(basis(5), link("resolved", B_), B_, target_is_idea=False, target_cited=True)
    assert stated.resolved_target == B_


def test_resolved_target_none_when_link_not_resolved() -> None:
    got = classify(basis(5), link("unconfirmed", B_), B_, target_is_idea=False, target_cited=True)
    assert got.resolved_target is None


def test_version() -> None:
    assert CLASSIFIER_VERSION == "1"
