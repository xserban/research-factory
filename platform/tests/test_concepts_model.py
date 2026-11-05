"""Concept value types and event payloads (slice 3c, plan G3-B, task 1)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.model.intuition import (
    ConceptHidden,
    ConceptInput,
    ConceptReviewed,
    ConceptSourceInput,
    HistoryEntry,
    LinkStatus,
    UseBasisInput,
)

P9 = "rf:p9-00000009"
CPT = "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WA"


def test_corpus_paper_source_needs_work_id() -> None:
    with pytest.raises(ValidationError):
        ConceptSourceInput.model_validate({"kind": "corpus-paper", "citation": "Rahimi"})
    got = ConceptSourceInput.model_validate(
        {"kind": "corpus-paper", "citation": "Rahimi", "work_id": P9}
    )
    assert got.work_id == P9
    assert ConceptSourceInput.model_validate({"kind": "textbook", "citation": "B"}).work_id is None


def test_source_citation_bounded_and_not_blank() -> None:
    with pytest.raises(ValidationError):
        ConceptSourceInput.model_validate({"kind": "textbook", "citation": " "})
    with pytest.raises(ValidationError):
        ConceptSourceInput.model_validate({"kind": "textbook", "citation": "x" * 501})


def test_basis_quote_and_reference_exclusive() -> None:
    quote: dict[str, Any] = {
        "kind": "quote",
        "role": "supports",
        "work_id": P9,
        "conversion_id": "cnv_01HZX3K4M5N6P7Q8R9S0T1V2WA",
        "anchor": "s1.p2",
        "quote": "x",
    }
    ref = "rex_01HZX3K4M5N6P7Q8R9S0T1V2WA:3"
    with pytest.raises(ValidationError):
        UseBasisInput.model_validate({"quote": quote, "reference": ref})
    assert UseBasisInput.model_validate({"reference": ref}).reference == ref
    assert UseBasisInput().quote is None


def test_concept_input_has_no_state_field() -> None:
    with pytest.raises(ValidationError):
        ConceptInput.model_validate({"name": "x", "review_state": "reviewed"})
    with pytest.raises(ValidationError):
        ConceptInput.model_validate({"name": "x", "source_state": "approved"})


def test_concept_reviewed_wrong_needs_note() -> None:
    ok = {"concept_id": CPT, "definition": "x", "self_reviewed": False}
    with pytest.raises(ValidationError):
        ConceptReviewed.model_validate({**ok, "state": "wrong", "note": " "})
    assert ConceptReviewed.model_validate({**ok, "state": "wrong", "note": "bound"}).note
    assert ConceptReviewed.model_validate({**ok, "state": "reviewed", "note": ""}).note == ""
    with pytest.raises(ValidationError):
        ConceptReviewed.model_validate({**ok, "state": "merged", "note": ""})


def test_enums_and_read_models() -> None:
    assert {s.value for s in LinkStatus} == {"stated", "inferred", "confirmed", "rejected"}
    assert ConceptHidden(unapproved=1, wrong=0, merged=0, links_inferred=2, links_rejected=0)
    assert HistoryEntry(
        event_id="e",
        kind="source-decided",
        state="approve",
        actor="a",
        note="",
        self_reviewed=False,
    )


def test_event_types_registered() -> None:
    cat = default_catalog()
    for name in (
        "concept.defined",
        "concept.source_decided",
        "concept.reviewed",
        "concept.link_proposed",
        "concept.link_decided",
        "concept.merged",
        "concept.unmerged",
    ):
        assert cat.get(name).schema == 1
