"""Interpretation model and shape validation (slice 3c, plan G3-A, task 1)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError

from factory.intuition.labels import LAYER_CLASS, interpretation_visible, layer_label
from factory.intuition.validate import shape_issues, text_length
from factory.model.intuition import (
    ENTRY_KEY_RE,
    INTERPRETATION_ID_RE,
    InterpretationInput,
    InterpretationReviewed,
    QuoteSourceInput,
    ReviewState,
)
from factory.model.screening import Channel

ULID = "01HZX3K4M5N6P7Q8R9S0T1V2W3"
WORK = "rf:smith-2020-0a1b2c3d"
CNV = f"cnv_{ULID}"


def quote(anchor: str = "s1.p2", text: str = "positive random-feature map") -> QuoteSourceInput:
    return QuoteSourceInput(
        kind="quote", role="supports", work_id=WORK, conversion_id=CNV, anchor=anchor, quote=text
    )


def entry(**over: Any) -> InterpretationInput:
    base: dict[str, Any] = {
        "target": f"ida_{ULID}",
        "text": "It approximates the softmax kernel.",
        "sources": (quote(),),
    }
    base.update(over)
    return InterpretationInput.model_validate(base)


def fields(e: InterpretationInput) -> list[str]:
    return [i.field for i in shape_issues(e)]


def test_600_accepted_601_refused() -> None:
    assert shape_issues(entry(text="a" * 600)) == []
    assert fields(entry(text="a" * 601)) == ["text"]


def test_blank_text_refused() -> None:
    assert fields(entry(text="   ")) == ["text"]


def test_length_counts_code_points_after_nfc() -> None:
    assert text_length("é" * 600) == 600
    assert text_length("é" * 600) == 600  # decomposed accents compose to one point
    assert shape_issues(entry(text="é" * 600)) == []


def test_sources_required_and_bounded() -> None:
    assert fields(entry(sources=())) == ["sources"]
    q = [quote(anchor=f"s1.p{n}") for n in range(1, 7)]
    assert fields(entry(sources=tuple(q[:5]))) == []
    assert "sources" in fields(entry(sources=tuple(q)))


def test_duplicate_source_reported_by_index() -> None:
    assert "sources[1]" in fields(entry(sources=(quote(), quote())))


def test_same_anchor_other_quote_is_not_a_duplicate() -> None:
    assert fields(entry(sources=(quote(), quote(text="other words")))) == []


def test_citation_needs_exactly_one_locator() -> None:
    cite: dict[str, Any] = {"kind": "citation", "role": "supports"}
    for locator in (
        {"reference": None, "work_id": None},
        {"reference": f"rex_{ULID}:1", "work_id": WORK},
    ):
        with pytest.raises(ValidationError):
            InterpretationInput.model_validate(
                {"target": WORK, "text": "t", "sources": [{**cite, **locator}]}
            )
    ok = InterpretationInput.model_validate(
        {"target": WORK, "text": "t", "sources": [{**cite, "work_id": WORK}]}
    )
    assert shape_issues(ok) == []


def test_entry_key_pattern() -> None:
    assert re.fullmatch(ENTRY_KEY_RE, f"rex_{ULID}:12")
    for bad in (f"rex_{ULID}:0", "rex_x:1", f"rex_{ULID}:", f"rex_{ULID}"):
        assert re.fullmatch(ENTRY_KEY_RE, bad) is None
    with pytest.raises(ValidationError):
        InterpretationInput.model_validate(
            {
                "target": WORK,
                "text": "t",
                "sources": [{"kind": "citation", "role": "supports", "reference": "rex_x:1"}],
            }
        )


def test_unknown_source_kind_and_role_refused() -> None:
    for source in (
        {"kind": "web", "role": "supports", "url": "x"},
        {"kind": "citation", "role": "proof", "work_id": WORK},
    ):
        with pytest.raises(ValidationError):
            InterpretationInput.model_validate({"target": WORK, "text": "t", "sources": [source]})


def test_extra_fields_refused() -> None:
    with pytest.raises(ValidationError):
        InterpretationInput.model_validate(
            {"target": WORK, "text": "t", "sources": [], "review_state": "reviewed"}
        )


def test_supersedes_pattern() -> None:
    assert re.fullmatch(INTERPRETATION_ID_RE, f"int_{ULID}")
    with pytest.raises(ValidationError):
        entry(supersedes="int_short")
    assert entry(supersedes=f"int_{ULID}").supersedes == f"int_{ULID}"


def test_label_and_visibility() -> None:
    assert layer_label("unreviewed") == "interpretation · unreviewed"
    assert LAYER_CLASS == "interpretation"
    assert {s for s in ReviewState if interpretation_visible(s)} == {
        ReviewState.UNREVIEWED,
        ReviewState.REVIEWED,
    }


def test_reviewed_payload_states_limited() -> None:
    base: dict[str, Any] = {
        "interpretation_id": f"int_{ULID}",
        "note": "",
        "self_reviewed": False,
        "channel": Channel.CLI,
    }
    assert InterpretationReviewed(state="wrong", **base).state == "wrong"
    for bad in ("superseded", "unreviewed"):
        with pytest.raises(ValidationError):
            InterpretationReviewed.model_validate({**base, "state": bad})
