"""The `ai-research-system` extraction pack, version 1: shape, registry and enumerations (slice 8).

Pure-data checks only; the pack declares no conditionals and no verification logic of its own.
"""

import re

from factory.packs import AI_RESEARCH_SYSTEM_V1, Check, FieldKind, UnitFamily, get_pack
from factory.packs.ai_research_system import (
    AI_RESEARCH_SYSTEM_PACK,
    EVIDENCE_GRADES,
    HUMAN_ROLES,
    PROCESS_SHAPES,
    RELEASED_VALUES,
    SELF_REPORTED_VALUES,
)
from factory.packs.ml_benchmark import CITATION_PATTERNS

ENUM_FIELDS = {
    "process_shape": PROCESS_SHAPES,
    "evidence_grade": EVIDENCE_GRADES,
    "human_role": HUMAN_ROLES,
    "released": RELEASED_VALUES,
    "self_reported": SELF_REPORTED_VALUES,
}
TEXT_FIELDS = {
    "system",
    "stage",
    "automated_span",
    "stage_inputs",
    "stage_outputs",
    "approach",
    "compared_to",
    "metric",
    "result",
    "ablation",
    "human_adds",
    "human_vs_automated",
    "components_models",
    "idea_assessment_method",
    "assessment_reliability",
}


def test_registry_and_identity() -> None:
    p = get_pack("ai-research-system", 1)
    assert p is AI_RESEARCH_SYSTEM_V1
    assert p.name == AI_RESEARCH_SYSTEM_PACK == "ai-research-system"
    assert p.version == 1
    assert get_pack("ai-research-system", 2) is None


def test_field_names_in_order() -> None:
    assert [f.name for f in AI_RESEARCH_SYSTEM_V1.fields] == [
        "system",
        "stage",
        "process_shape",
        "automated_span",
        "stage_inputs",
        "stage_outputs",
        "approach",
        "compared_to",
        "metric",
        "result",
        "evidence_grade",
        "ablation",
        "human_role",
        "human_adds",
        "human_vs_automated",
        "components_models",
        "released",
        "idea_assessment_method",
        "assessment_reliability",
        "self_reported",
    ]


def test_names_unique_and_well_formed() -> None:
    names = [f.name for f in AI_RESEARCH_SYSTEM_V1.fields]
    assert len(names) == len(set(names))
    for n in names:
        assert re.fullmatch(r"[a-z][a-z_]*", n), n


def test_enumerated_fields_have_closed_values() -> None:
    assert PROCESS_SHAPES == (
        "linear",
        "iterative-loop",
        "tree-search",
        "parallel-branches",
        "other",
    )
    assert EVIDENCE_GRADES == ("A", "B", "C", "D", "E", "F")
    assert HUMAN_ROLES == ("none", "validates", "directs", "contributes")
    assert RELEASED_VALUES == ("code-and-system", "code-only", "none", "unclear")
    assert SELF_REPORTED_VALUES == ("yes", "no")
    for name, values in ENUM_FIELDS.items():
        f = AI_RESEARCH_SYSTEM_V1.field(name)
        assert f is not None, name
        assert f.kind is FieldKind.TEXT
        assert f.allowed == values
        assert f.check is Check.NONE
        assert f.unit_family is UnitFamily.NONE


def test_free_text_fields_are_quote_checked() -> None:
    for name in TEXT_FIELDS:
        f = AI_RESEARCH_SYSTEM_V1.field(name)
        assert f is not None, name
        assert f.kind is FieldKind.TEXT
        assert f.check is Check.TEXT_IN_QUOTE
        assert f.allowed == ()
    declared = {f.name for f in AI_RESEARCH_SYSTEM_V1.fields}
    assert declared == TEXT_FIELDS | set(ENUM_FIELDS)


def test_required_and_row_key() -> None:
    p = AI_RESEARCH_SYSTEM_V1
    assert p.required == ("system", "stage", "evidence_grade", "self_reported")
    assert p.row_key_fields == ("system", "stage")
    assert p.row_anchor_fields == ("system", "stage")
    assert p.default_comparability_keys == ()
    assert p.conditionals == ()
    assert p.report is None
    names = {f.name for f in p.fields}
    assert set(p.required) <= names
    assert set(p.row_key_fields) <= names


def test_compared_fields_are_declared_and_keyed() -> None:
    p = AI_RESEARCH_SYSTEM_V1
    assert p.compared_fields == (
        "system",
        "stage",
        "evidence_grade",
        "human_role",
        "released",
        "self_reported",
    )
    names = {f.name for f in p.fields}
    assert p.compared_fields is not None
    assert set(p.compared_fields) <= names
    assert set(p.row_key_fields) <= set(p.compared_fields)


def test_citation_patterns_shared_with_pack_family() -> None:
    assert AI_RESEARCH_SYSTEM_V1.citation_patterns == CITATION_PATTERNS
