from factory.model.project import RigorMode
from factory.model.protocol import (
    CriterionExamples,
    PlannedQuery,
    SourcePlan,
    search_strategy_hash,
)
from factory.model.question import SubQuestion
from factory.model.search import QueryKind
from factory.model.seed import SeedKind
from factory.services.protocol_rules import other_changes
from factory.services.seeds import SeedRecord, SeedRole
from tests.screening_helpers import (
    QUESTION,
    QUESTION_SPEC,
    _check,
    _ex,
    _fields,
    _in,
    _reviewer,
    _screening,
    _spec,
)


def _seed(seed_id: str, role: SeedRole) -> SeedRecord:
    return SeedRecord(
        seed_id=seed_id,
        kind=SeedKind.POSITIVE,
        cite="Author 2020",
        why="",
        doi=None,
        arxiv=None,
        openalex=None,
        work_id=None,
        unresolved_reason=None,
        role=role,
    )


SEEDS = [_seed("SEED01", SeedRole.DEVELOPMENT), _seed("SEED02", SeedRole.HELD_OUT)]


def test_ready_pilot_protocol_has_no_errors_or_gaps() -> None:
    check = _check(_spec())
    assert check.errors == []
    assert check.gaps == []


def test_parentless_criterion_rejected_in_pilot_and_systematic() -> None:
    spec = _spec(criteria=(_in(parent=None), _ex()))
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        check = _check(spec, mode)
        assert ("criteria[0].parent") in _fields(check.errors)
        message = [i.reason for i in check.errors if i.field == "criteria[0].parent"]
        assert message == ["every criterion names its parent question element or non-goal (R-11)"]


def test_parentless_criterion_allowed_in_exploratory() -> None:
    check = _check(_spec(criteria=(_in(parent=None), _ex())), RigorMode.EXPLORATORY)
    assert check.errors == []


def test_parent_must_resolve_to_slot_or_non_goal() -> None:
    check = _check(_spec(criteria=(_in(parent="slot:nonexistent"), _ex())), RigorMode.EXPLORATORY)
    assert "criteria[0].parent" in _fields(check.errors)
    check = _check(_spec(criteria=(_in(parent="NG09"), _ex())), RigorMode.EXPLORATORY)
    assert "criteria[0].parent" in _fields(check.errors)
    check = _check(_spec(criteria=(_in(parent="slot:setting"), _ex())), RigorMode.EXPLORATORY)
    assert check.errors == []


def test_parent_may_name_a_sub_question_of_the_current_question() -> None:
    question = QUESTION.model_copy(
        update={
            "spec": QUESTION_SPEC.model_copy(
                update={"sub_questions": (SubQuestion(id="SQ1", text="Which metric?"),)}
            )
        }
    )
    ok = _check(
        _spec(criteria=(_in(parent="SQ1"), _ex())), RigorMode.EXPLORATORY, question=question
    )
    assert ok.errors == []
    missing = _check(
        _spec(criteria=(_in(parent="SQ2"), _ex())), RigorMode.EXPLORATORY, question=question
    )
    assert "criteria[0].parent" in _fields(missing.errors)
    absent = _check(_spec(criteria=(_in(parent="SQ1"), _ex())), RigorMode.EXPLORATORY)
    assert "criteria[0].parent" in _fields(absent.errors)


def test_held_out_seed_cannot_be_worked_example() -> None:
    held = _spec(criteria=(_in(examples=CriterionExamples(include=("SEED02",))), _ex()))
    unknown = _spec(criteria=(_in(examples=CriterionExamples(include=("SEED99",))), _ex()))
    held_check = _check(held, seeds=SEEDS)
    unknown_check = _check(unknown, seeds=SEEDS)
    held_issues = [i for i in held_check.errors if i.field == "criteria[0].examples"]
    unknown_issues = [i for i in unknown_check.errors if i.field == "criteria[0].examples"]
    assert held_issues == unknown_issues
    assert len(held_issues) == 1
    assert "SEED02" not in held_issues[0].reason
    assert "SEED02" not in str(held_check.errors)
    ok = _spec(criteria=(_in(examples=CriterionExamples(include=("SEED01",))), _ex()))
    assert _check(ok, seeds=SEEDS).errors == []


def test_question_must_be_current() -> None:
    check = _check(_spec(), current="Q@" + "b" * 8)
    assert "question_id" in _fields(check.errors)


def test_duplicate_criterion_id_and_unknown_source_are_errors() -> None:
    dup = _check(_spec(criteria=(_in(), _in(), _ex())), RigorMode.EXPLORATORY)
    assert "criteria[1].id" in _fields(dup.errors)
    unknown = _check(
        _spec(sources=(SourcePlan(name="scopus", included=True, probe_id="prb_1"),), queries=()),
        RigorMode.EXPLORATORY,
    )
    assert "sources[0].name" in _fields(unknown.errors)


def test_duplicate_source_is_an_error_naming_its_index() -> None:
    spec = _spec(
        sources=(
            SourcePlan(name="openalex", included=True, probe_id="prb_1"),
            SourcePlan(name="arxiv", included=False),
            SourcePlan(name="openalex", included=False),
        )
    )
    check = _check(spec, RigorMode.EXPLORATORY)
    [issue] = [i for i in check.errors if i.field == "sources[2].name"]
    assert issue.reason == "duplicate source"
    assert "sources[1].name" not in _fields(check.errors)


def test_duplicate_planned_query_is_an_error_naming_its_index() -> None:
    query = PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="remote focus")
    padded = PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="  remote focus ")
    other = PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="other")
    check = _check(_spec(queries=(query, other, padded)), RigorMode.EXPLORATORY)
    [issue] = [i for i in check.errors if i.field.startswith("queries[")]
    assert (issue.field, issue.reason) == ("queries[2]", "duplicate planned query")


def test_queries_differing_only_in_filters_are_not_duplicates() -> None:
    plain = PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="remote focus")
    filtered = PlannedQuery(
        source="openalex", kind=QueryKind.KEYWORD, text="remote focus", filters={"year": "2020"}
    )
    check = _check(_spec(queries=(plain, filtered)), RigorMode.EXPLORATORY)
    assert not [i for i in check.errors if i.field.startswith("queries[")]


def test_query_must_use_an_included_source() -> None:
    spec = _spec(
        sources=(
            SourcePlan(name="openalex", included=True, probe_id="prb_1"),
            SourcePlan(name="arxiv", included=False),
        ),
        queries=(PlannedQuery(source="arxiv", kind=QueryKind.KEYWORD, text="remote"),),
    )
    check = _check(spec, RigorMode.EXPLORATORY)
    assert "queries[0].source" in _fields(check.errors)


def test_unreferenced_non_goal_is_a_gap_in_pilot() -> None:
    spec = _spec(criteria=(_in(), _ex("EX01", "NG01")))
    check = _check(spec)
    assert "non_goals.NG02" in _fields(check.gaps)
    assert "non_goals.NG01" not in _fields(check.gaps)
    assert _check(spec, RigorMode.EXPLORATORY).gaps == []


def test_unreferenced_filled_slot_is_a_gap_open_slots_exempt() -> None:
    # `population` is filled and no inclusion names it; `setting` is open and exempt.
    spec = _spec(criteria=(_in("IN01", "slot:setting"), _ex()))
    check = _check(spec)
    assert "slots.population" in _fields(check.gaps)
    assert "slots.setting" not in _fields(check.gaps)


def test_duplicate_exclusion_priority_is_a_gap() -> None:
    spec = _spec(criteria=(_in(), _ex("EX01", "NG01", 1), _ex("EX02", "NG02", 1)))
    check = _check(spec)
    assert _fields(check.gaps) == ["criteria[2].priority"]


def test_included_source_needs_probe_evidence_in_pilot() -> None:
    no_probe = _spec(sources=(SourcePlan(name="openalex", included=True),))
    assert "sources[0].probe_id" in _fields(_check(no_probe).gaps)
    wrong_probe = _spec(sources=(SourcePlan(name="arxiv", included=True, probe_id="prb_1"),))
    assert "sources[0].probe_id" in _fields(_check(wrong_probe).gaps)
    assert _check(no_probe, RigorMode.EXPLORATORY).gaps == []


def test_ready_needs_an_included_source_and_a_query() -> None:
    no_source = _spec(sources=(SourcePlan(name="openalex", included=False),), queries=())
    fields = _fields(_check(no_source, RigorMode.EXPLORATORY).gaps)
    assert "sources" in fields
    assert "queries" in fields


def test_systematic_needs_enforced_kappa_floor_of_at_least_0_7() -> None:
    low = _spec(screening=_screening(kappa_floor=0.6, kappa_enforced=True, dual_sample=None))
    assert "screening.kappa_floor" in _fields(_check(low, RigorMode.SYSTEMATIC).gaps)
    not_enforced = _spec(
        screening=_screening(kappa_floor=0.7, kappa_enforced=False, dual_sample=None)
    )
    assert "screening.kappa_enforced" in _fields(_check(not_enforced, RigorMode.SYSTEMATIC).gaps)
    ok = _spec(screening=_screening(kappa_floor=0.7, kappa_enforced=True, dual_sample=None))
    assert _check(ok, RigorMode.SYSTEMATIC).gaps == []


def test_systematic_dual_sample_only_none_or_full() -> None:
    partial = _spec(screening=_screening(kappa_enforced=True, dual_sample=0.5))
    assert "screening.dual_sample" in _fields(_check(partial, RigorMode.SYSTEMATIC).gaps)
    full = _spec(screening=_screening(kappa_enforced=True, dual_sample=1.0))
    assert _check(full, RigorMode.SYSTEMATIC).gaps == []


def test_pilot_kappa_is_advisory() -> None:
    advisory = _spec(screening=_screening(kappa_floor=0.5, kappa_enforced=False))
    assert _check(advisory, RigorMode.PILOT).gaps == []
    undeclared = _spec(screening=_screening(kappa_floor=None))
    assert "screening.kappa_floor" in _fields(_check(undeclared, RigorMode.PILOT).gaps)


def test_pilot_requires_two_passes_and_dual_sample() -> None:
    one_pass = _spec(screening=_screening(passes=1, dual_sample=None))
    fields = _fields(_check(one_pass, RigorMode.PILOT).gaps)
    assert "screening.passes" in fields
    assert "screening.dual_sample" in fields


def test_exactly_one_human_reviewer_of_record() -> None:
    none = _spec(screening=_screening(reviewers=()))
    assert "screening.reviewers" in _fields(_check(none, RigorMode.EXPLORATORY).gaps)
    two = _spec(screening=_screening(reviewers=(_reviewer(), _reviewer())))
    assert "screening.reviewers" in _fields(_check(two, RigorMode.EXPLORATORY).gaps)
    agent = _spec(screening=_screening(reviewers=(_reviewer(kind="agent"),)))
    assert "screening.reviewers" in _fields(_check(agent, RigorMode.EXPLORATORY).gaps)
    assistant_only = _spec(
        screening=_screening(reviewers=(_reviewer(), _reviewer(role="assisting", kind="agent")))
    )
    assert _check(assistant_only, RigorMode.EXPLORATORY).gaps == []


def test_systematic_needs_two_passes() -> None:
    one_pass = _spec(screening=_screening(passes=1, kappa_enforced=True, dual_sample=None))
    assert "screening.passes" in _fields(_check(one_pass, RigorMode.SYSTEMATIC).gaps)
    two_pass = _spec(screening=_screening(passes=2, kappa_enforced=True, dual_sample=None))
    assert _check(two_pass, RigorMode.SYSTEMATIC).gaps == []


def test_pilot_rejects_audit_minimum_below_50() -> None:
    small = _spec(screening=_screening(audit_minimum=49, kappa_enforced=False))
    fields = _fields(_check(small, RigorMode.PILOT).gaps)
    assert "screening.audit_minimum" in fields
    thin = _spec(screening=_screening(audit_fraction=0.01, kappa_enforced=False))
    assert "screening.audit_fraction" in _fields(_check(thin, RigorMode.PILOT).gaps)


def test_exploratory_allows_small_audit() -> None:
    small = _spec(screening=_screening(audit_minimum=10, audit_fraction=0.01))
    fields = _fields(_check(small, RigorMode.EXPLORATORY).gaps)
    assert "screening.audit_minimum" not in fields
    assert "screening.audit_fraction" not in fields


def test_removing_full_text_screening_is_an_other_change_not_a_search_change() -> None:
    with_plan = _spec(full_text_screening=_screening())
    without = _spec()
    assert other_changes(with_plan, without) == ["full_text_screening"]
    assert other_changes(without, with_plan) == ["full_text_screening"]
    assert search_strategy_hash(with_plan) == search_strategy_hash(without)
