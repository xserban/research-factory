"""`check_proposal`: the design rules of an agent-proposed miner."""

from __future__ import annotations

from dataclasses import replace

from factory.errors import ValidationIssue
from factory.mining.spec import EvidenceRule, MinerField, MinerSpec, QuoteKind, Selector
from factory.services.miner_proposal import check_proposal
from tests.miner_helpers import vision_result


def _fields(issues: tuple[ValidationIssue, ...]) -> set[str]:
    return {i.field for i in issues}


def _good() -> MinerSpec:
    spec = vision_result()
    return replace(spec, evidence=EvidenceRule(absence_values=("direction/not-stated",)))


def test_a_described_capped_miner_with_an_absence_value_passes() -> None:
    spec = _good()
    spec = replace(
        spec,
        fields=tuple(replace(f, description="what the work states") for f in spec.fields),
    )
    assert check_proposal(spec) == ()


def test_missing_description_cap_and_absence_value_are_reported() -> None:
    spec = vision_result()
    spec = replace(
        spec,
        selector=Selector(spec.selector.population, max_units=None),
        evidence=EvidenceRule(),
    )
    got = _fields(check_proposal(spec))
    assert {"fields[0].description", "selector.max_units", "evidence.absence_values"} <= got


def test_too_many_fields_are_reported() -> None:
    spec = vision_result()
    extra = tuple(MinerField(f"f{i}", "g", QuoteKind(), description="d") for i in range(9))
    assert "fields" in _fields(check_proposal(replace(spec, fields=spec.fields + extra)))
    assert "fields" not in _fields(
        check_proposal(replace(spec, fields=spec.fields + extra), max_fields=20)
    )


def test_a_field_restating_the_question_is_reported() -> None:
    spec = vision_result()
    f = MinerField(
        "answer", "g", QuoteKind(), description="does retrieval augmentation improve accuracy"
    )
    spec = replace(spec, fields=(f,))
    q = "Does retrieval augmentation improve accuracy?"
    assert "fields[0]" in _fields(check_proposal(spec, q))
    assert "fields[0]" not in _fields(check_proposal(spec))
