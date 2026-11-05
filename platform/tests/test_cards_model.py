"""Vocabulary and card payloads: value rules (slice 6, plan H-A, task 1)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.model.cards import (
    AssertionDecided,
    BasisKind,
    CardAsserted,
    CardCreated,
    InferredBasis,
    MatchRule,
    PropertyDef,
    PropertyKind,
    PropertyProposed,
    QuoteBasis,
)
from factory.packs import UnitFamily

ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"
CNV = "cnv_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
WORK = "rf:smith-2020-a1b2c3d4"
QUOTE = {"work_id": WORK, "conversion_id": CNV, "anchor": "s1.p1", "quote": "irregularly sampled"}


def _def(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": "pr:sampling",
        "kind": "enum",
        "allowed": ["regular", "irregular"],
        "match": "equal",
        "applies_to": "both",
    }
    base.update(over)
    return base


def _asserted(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "assertion_id": f"pas_{ULID}",
        "card_id": f"mcd_{ULID}",
        "property": "pr:sampling",
        "value": "irregular",
        "basis_kind": "quote",
        "basis": QUOTE,
        "status": "stated",
        "vocabulary_version": "V@00000000",
    }
    base.update(over)
    return base


def test_property_def_kind_rules() -> None:
    PropertyDef.model_validate(_def())
    with pytest.raises(ValidationError):
        PropertyDef.model_validate(_def(allowed=[]))
    with pytest.raises(ValidationError):
        PropertyDef.model_validate(_def(kind="bool", allowed=["a"], match="equal"))
    with pytest.raises(ValidationError):  # covers on a number
        PropertyDef.model_validate(
            _def(kind="number", allowed=[], unit_family="count", match="covers")
        )
    with pytest.raises(ValidationError):  # at-most on an enum
        PropertyDef.model_validate(_def(match="at-most"))
    with pytest.raises(ValidationError):  # a number needs a unit family
        PropertyDef.model_validate(_def(kind="number", allowed=[], match="at-most"))
    with pytest.raises(ValidationError):  # value alias for a value that is not allowed
        PropertyDef.model_validate(_def(value_aliases={"gridded": ["on a grid"]}))
    ok = PropertyDef.model_validate(
        _def(kind="number", allowed=[], unit_family="count", match="at-most")
    )
    assert ok.unit_family is UnitFamily.COUNT and ok.match is MatchRule.AT_MOST
    assert ok.kind is PropertyKind.NUMBER


@pytest.mark.parametrize("key", ["sampling", "pr:S", "pr:a", "pr:Upper", "pr:" + "x" * 49])
def test_property_key_pattern(key: str) -> None:
    with pytest.raises(ValidationError):
        PropertyDef.model_validate(_def(key=key))


def test_superseding_definition_keeps_its_key() -> None:
    with pytest.raises(ValidationError):
        PropertyProposed.model_validate({"definition": _def(), "supersedes": "pr:other-key"})


def test_assertion_input_forbids_status() -> None:
    # The payload computes `status`; any extra field is refused outright (extra="forbid").
    with pytest.raises(ValidationError):
        CardAsserted.model_validate(_asserted(surprise=1))
    # and the status must follow the basis kind: a quote assertion cannot be inferred
    with pytest.raises(ValidationError):
        CardAsserted.model_validate(_asserted(status="inferred"))
    assert CardAsserted.model_validate(_asserted()).basis_kind is BasisKind.QUOTE
    assert isinstance(CardAsserted.model_validate(_asserted()).basis, QuoteBasis)


def test_inferred_basis_needs_note() -> None:
    with pytest.raises(ValidationError):
        InferredBasis.model_validate({"note": "   "})
    with pytest.raises(ValidationError):
        InferredBasis.model_validate({"note": "x" * 501})
    ok = _asserted(basis_kind="inferred", basis={"note": "reasoned"}, status="inferred")
    assert CardAsserted.model_validate(ok).status == "inferred"
    with pytest.raises(ValidationError):  # a quote basis under inferred kind
        CardAsserted.model_validate(_asserted(basis_kind="inferred", status="inferred"))


def test_researcher_basis_has_no_basis_and_imported_names_source() -> None:
    r = _asserted(basis_kind="researcher", basis=None)
    assert CardAsserted.model_validate(r).status == "stated"
    with pytest.raises(ValidationError):
        CardAsserted.model_validate(_asserted(basis_kind="researcher"))
    with pytest.raises(ValidationError):
        CardAsserted.model_validate(_asserted(basis_kind="imported", status="imported-unverified"))
    imp = _asserted(basis_kind="imported", status="imported-unverified", imported_from="a/pas_1")
    assert CardAsserted.model_validate(imp).imported_from == "a/pas_1"


def test_card_id_prefix_matches_kind() -> None:
    CardCreated.model_validate(
        {"card_id": f"mcd_{ULID}", "kind": "method", "subject": WORK, "owner": "obd"}
    )
    with pytest.raises(ValidationError):
        CardCreated.model_validate(
            {"card_id": f"mcd_{ULID}", "kind": "problem", "subject": "Q@abcdef01", "owner": "obd"}
        )


def test_decision_needs_rationale() -> None:
    with pytest.raises(ValidationError):
        AssertionDecided.model_validate(
            {"assertion_id": f"pas_{ULID}", "decision": "confirm", "rationale": " "}
        )
