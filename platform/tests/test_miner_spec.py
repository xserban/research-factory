"""Miner specification: JSON round trip, shape errors and validation (M-C, task 1)."""

from dataclasses import replace
from typing import Any

import pytest

from factory.document.anchors import AnchorKind
from factory.errors import FactoryValidationError
from factory.mining.spec import (
    AnchorKindRef,
    CitationKind,
    EnumKind,
    IntegerKind,
    MinerField,
    NumberKind,
    QuoteKind,
    Unverified,
    WorkRefKind,
    spec_from_json,
    spec_to_json,
)
from factory.mining.validate import validate_miner
from factory.packs.model import Conditional, UnitFamily
from tests.miner_helpers import vision_result


def _fields(issues: list[Any]) -> set[str]:
    return {i.field for i in issues}


def test_json_round_trip() -> None:
    spec = replace(
        vision_result(),
        fields=(
            *vision_result().fields,
            MinerField("cite", "c", CitationKind((r"\[\d+\]",))),
            MinerField("where", "c", AnchorKindRef((AnchorKind.TABLE, AnchorKind.PARAGRAPH))),
            MinerField("ref", "c", WorkRefKind("entry")),
            MinerField("title", "c", WorkRefKind("title")),
            MinerField("n", "c", IntegerKind()),
            MinerField("cnt", "c", NumberKind(UnitFamily.COUNT, ("K", ""))),
        ),
        conditionals=(Conditional("evidence", "direction", ("lower",), "required"),),
    )
    assert spec_from_json(spec_to_json(spec)) == spec


def test_shape_errors_are_dotted_and_collected() -> None:
    body = spec_to_json(vision_result())
    body["fields"][1]["kind"] = {"type": "tensor"}  # type: ignore[index]
    body["selector"]["population"] = "everything"  # type: ignore[index]
    body["bogus"] = 1
    with pytest.raises(FactoryValidationError) as raised:
        spec_from_json(body)
    assert {"fields[1].kind.type", "selector.population", "bogus"} <= _fields(raised.value.issues)


def test_a_valid_spec_has_no_issues() -> None:
    assert validate_miner(vision_result()) == []


def test_free_text_refused_for_registered() -> None:
    spec = replace(
        vision_result(), fields=(*vision_result().fields, MinerField("note", "x", Unverified()))
    )
    assert "fields[4].kind" in _fields(validate_miner(spec))
    assert validate_miner(spec, built_in=True) == []


@pytest.mark.parametrize("name", ["vision-result", "ml-benchmark", "m-", "m-Vision", "m--a"])
def test_name_outside_namespace_refused(name: str) -> None:
    assert "name" in _fields(validate_miner(vision_result(name=name)))


def test_bad_heading_pattern_refused() -> None:
    spec = vision_result(selector=replace(vision_result().selector, heading_patterns=("(",)))
    assert "selector.heading_patterns[0]" in _fields(validate_miner(spec))


def test_enum_needs_values() -> None:
    empty = replace(
        vision_result(), fields=(*vision_result().fields, MinerField("kind", "x", EnumKind(())))
    )
    assert "fields[4].kind.values" in _fields(validate_miner(empty))
    unnormalised = replace(
        vision_result(),
        fields=(*vision_result().fields, MinerField("kind", "x", EnumKind(("Yes", "no")))),
    )
    assert "fields[4].kind.values" in _fields(validate_miner(unnormalised))


def test_quote_field_required_by_evidence_rule() -> None:
    no_quote = replace(
        vision_result(),
        fields=(
            MinerField("value", "r", NumberKind(UnitFamily.SCORE), required=True),
            MinerField("direction", "r", EnumKind(("higher", "lower"))),
        ),
        row_key_fields=("value",),
        row_anchor_fields=(),
    )
    assert "evidence.min_quotes_per_record" in _fields(validate_miner(no_quote))


def test_conditional_names_unknown_field() -> None:
    spec = replace(
        vision_result(), conditionals=(Conditional("ghost", "direction", ("higher",), "required"),)
    )
    assert "conditionals[0].field" in _fields(validate_miner(spec))
    spec = replace(
        vision_result(),
        conditionals=(Conditional("evidence", "direction", ("sideways",), "required"),),
    )
    assert "conditionals[0].values" in _fields(validate_miner(spec))


def test_row_key_and_required_field_needed() -> None:
    spec = vision_result(row_key_fields=())
    assert "row_key_fields" in _fields(validate_miner(spec))
    spec = vision_result(row_key_fields=("ghost",))
    assert "row_key_fields[0]" in _fields(validate_miner(spec))


def test_regime_and_selector_bounds() -> None:
    spec = vision_result(
        selector=replace(vision_result().selector, max_units=0),
        regime=replace(vision_result().regime, recall_min=0.0, calibration_size=0),
    )
    assert {"selector.max_units", "regime.recall_min", "regime.calibration_size"} <= _fields(
        validate_miner(spec)
    )


def test_citation_and_anchor_kinds_checked() -> None:
    spec = replace(
        vision_result(),
        fields=(
            *vision_result().fields,
            MinerField("cite", "c", CitationKind(("(",))),
            MinerField("where", "c", AnchorKindRef(())),
        ),
    )
    assert {"fields[4].kind.patterns[0]", "fields[5].kind.kinds"} <= _fields(validate_miner(spec))
    assert QuoteKind() == QuoteKind()
