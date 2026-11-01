import pytest
from pydantic import JsonValue, ValidationError

from factory.model.protocol import (
    Criterion,
    CriterionExamples,
    CriterionKind,
    Limit,
    MethodProfile,
    PlannedQuery,
    ProtocolSpec,
    Reviewer,
    ScreeningPlan,
    ScreeningStage,
    SourcePlan,
    criterion_ref,
    protocol_version,
    search_strategy_hash,
    strip_prose,
)
from factory.model.search import QueryKind, QuerySpec

QID = "Q@" + "a" * 8


def _criterion(cid: str, **overrides: object) -> Criterion:
    base: dict[str, object] = {
        "id": cid,
        "parent": "slot:population",
        "statement": "adult participants",
        "rule": "include if the population is adult",
        "applies_at": ScreeningStage.TITLE_ABSTRACT,
    }
    if cid.startswith("EX"):
        base["priority"] = 1
        base["parent"] = "NG01"
    base.update(overrides)
    return Criterion.model_validate(base)


def _spec(**overrides: object) -> ProtocolSpec:
    base: dict[str, object] = {
        "question_id": QID,
        "method_profile": MethodProfile.SCOPING_REVIEW,
        "criteria": (_criterion("IN01"), _criterion("EX01", priority=1)),
        "sources": (
            SourcePlan(name="openalex", included=True, probe_id="prb_1"),
            SourcePlan(name="arxiv", included=False),
        ),
        "queries": (
            PlannedQuery(
                source="openalex", kind=QueryKind.KEYWORD, text="  remote work  ", filters={}
            ),
        ),
        "limits": (Limit(field="year", value="2015-2025", why="scope"),),
        "screening": ScreeningPlan(
            passes=1,
            reviewers=(Reviewer(role="reviewer-of-record", actor="ana", kind="human"),),
        ),
        "rationale": "first draft",
    }
    base.update(overrides)
    return ProtocolSpec.model_validate(base)


def test_prose_does_not_change_version() -> None:
    spec = _spec()
    edited = _spec(
        rationale="a completely different rationale",
        criteria=(
            _criterion("IN01", note="reworded note", examples=CriterionExamples(include=())),
            _criterion("EX01", priority=1, note="another note"),
        ),
        sources=(
            SourcePlan(name="openalex", included=True, probe_id="prb_1", why="changed why"),
            SourcePlan(name="arxiv", included=False, why="x"),
        ),
        limits=(Limit(field="year", value="2015-2025", why="rewritten"),),
    )
    assert protocol_version(edited) == protocol_version(spec)


def test_rule_change_changes_version() -> None:
    spec = _spec()
    changed = _spec(
        criteria=(
            _criterion("IN01", rule="include if the population is over 60"),
            _criterion("EX01", priority=1),
        )
    )
    assert protocol_version(changed) != protocol_version(spec)
    assert protocol_version(spec).startswith("P@")
    assert len(protocol_version(spec)) == len("P@") + 8


def test_version_is_order_independent() -> None:
    spec = _spec(
        criteria=(
            _criterion("IN01"),
            _criterion("EX01", priority=1),
            _criterion("EX02", priority=2),
        ),
    )
    reordered = _spec(
        criteria=(
            _criterion("EX02", priority=2),
            _criterion("EX01", priority=1),
            _criterion("IN01"),
        ),
        sources=(
            SourcePlan(name="arxiv", included=False),
            SourcePlan(name="openalex", included=True, probe_id="prb_1"),
        ),
    )
    assert protocol_version(reordered) == protocol_version(spec)


def test_search_strategy_hash_ignores_criteria() -> None:
    spec = _spec()
    other_criteria = _spec(
        criteria=(_criterion("IN01", rule="a different rule"), _criterion("EX01", priority=1))
    )
    assert search_strategy_hash(other_criteria) == search_strategy_hash(spec)
    assert search_strategy_hash(spec).startswith("S@")

    other_query = _spec(
        queries=(PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="gig economy"),)
    )
    assert search_strategy_hash(other_query) != search_strategy_hash(spec)


def test_criterion_kind_and_priority_rules() -> None:
    assert _criterion("IN03").kind is CriterionKind.INCLUSION
    assert _criterion("EX03", priority=2).kind is CriterionKind.EXCLUSION
    with pytest.raises(ValidationError, match="exclusion needs a priority"):
        _criterion("EX04", priority=None)
    with pytest.raises(ValidationError, match="inclusion has no priority"):
        _criterion("IN04", priority=1)
    with pytest.raises(ValidationError):
        _criterion("XX01")
    with pytest.raises(ValidationError):
        _criterion("IN1")


def test_strip_prose_removes_prose_keys_recursively() -> None:
    value: JsonValue = {
        "id": "IN01",
        "note": "drop me",
        "examples": {"include": ["SEED01"]},
        "nested": [{"why": "drop", "keep": 1}],
    }
    assert strip_prose(value) == {"id": "IN01", "nested": [{"keep": 1}]}


def test_criterion_ref_joins_protocol_and_criterion() -> None:
    assert criterion_ref("P@0a1b2c3d", "IN01") == "P@0a1b2c3d:IN01"


def test_query_matches_on_source_kind_stripped_text_and_filters() -> None:
    planned = PlannedQuery(source="openalex", kind=QueryKind.FILTER, text="x", filters={"a": "1"})
    same = QuerySpec(source="openalex", kind=QueryKind.FILTER, text="  x ", filters={"a": "1"})
    other_filter = QuerySpec(source="openalex", kind=QueryKind.FILTER, text="x", filters={"a": "2"})
    other_kind = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="x", filters={"a": "1"})
    assert planned.matches(same)
    assert not planned.matches(other_filter)
    assert not planned.matches(other_kind)


def test_models_reject_unknown_fields_and_bad_ranges() -> None:
    with pytest.raises(ValidationError):
        ScreeningPlan.model_validate({"passes": 3, "reviewers": []})
    with pytest.raises(ValidationError):
        ScreeningPlan(passes=1, dual_sample=0.0, reviewers=())
    with pytest.raises(ValidationError):
        ScreeningPlan(passes=1, kappa_floor=1.5, reviewers=())
    with pytest.raises(ValidationError):
        Reviewer.model_validate({"role": "reviewer-of-record", "actor": "a", "kind": "robot"})
