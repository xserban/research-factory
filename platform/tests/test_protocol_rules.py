from collections.abc import Sequence
from datetime import UTC, datetime

from factory.errors import ValidationIssue
from factory.model.project import RigorMode
from factory.model.protocol import (
    Criterion,
    CriterionExamples,
    Limit,
    MethodProfile,
    PlannedQuery,
    ProtocolSpec,
    Reviewer,
    ScreeningPlan,
    ScreeningStage,
    SourcePlan,
)
from factory.model.question import NonGoal, QuestionSpec, Slot, question_version
from factory.model.search import QueryKind
from factory.model.seed import SeedKind
from factory.services.protocol_rules import ProtocolCheck, protocol_issues
from factory.services.question import QuestionVersion
from factory.services.seeds import SeedRecord, SeedRole

QUESTION_SPEC = QuestionSpec(
    scheme="PICO",
    primary_question="Do remote workers report higher focus?",
    slots=(
        Slot(name="population", value="knowledge workers"),
        Slot(name="setting", open="?", resolve_in="stage 2"),
    ),
    non_goals=(NonGoal(id="NG01", text="gig platforms"), NonGoal(id="NG02", text="teams")),
)
QID = question_version(QUESTION_SPEC)
QUESTION = QuestionVersion(
    question_id=QID,
    spec=QUESTION_SPEC,
    supersedes=None,
    reason=None,
    recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
)
PROBES: dict[str, set[str]] = {"prb_1": {"openalex"}}
KNOWN_SOURCES = {"openalex", "arxiv"}


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


def _in(cid: str = "IN01", parent: str | None = "slot:population", **kw: object) -> Criterion:
    base: dict[str, object] = {
        "id": cid,
        "parent": parent,
        "statement": "adults",
        "rule": "include adults",
        "applies_at": ScreeningStage.TITLE_ABSTRACT,
    }
    base.update(kw)
    return Criterion.model_validate(base)


def _ex(cid: str = "EX01", parent: str | None = "NG01", priority: int = 1) -> Criterion:
    return Criterion.model_validate(
        {
            "id": cid,
            "parent": parent,
            "statement": "gig work",
            "rule": "exclude gig work",
            "applies_at": ScreeningStage.TITLE_ABSTRACT,
            "priority": priority,
        }
    )


def _reviewer(role: str = "reviewer-of-record", kind: str = "human") -> Reviewer:
    return Reviewer.model_validate({"role": role, "actor": "ana", "kind": kind})


def _screening(**kw: object) -> ScreeningPlan:
    base: dict[str, object] = {
        "passes": 2,
        "dual_sample": 0.5,
        "kappa_floor": 0.7,
        "reviewers": (_reviewer(),),
    }
    base.update(kw)
    return ScreeningPlan.model_validate(base)


def _spec(**kw: object) -> ProtocolSpec:
    base: dict[str, object] = {
        "question_id": QID,
        "method_profile": MethodProfile.SYSTEMATIC_REVIEW,
        "criteria": (_in(), _ex(), _ex("EX02", "NG02", priority=2)),
        "sources": (SourcePlan(name="openalex", included=True, probe_id="prb_1"),),
        "queries": (PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="remote focus"),),
        "limits": (Limit(field="year", value="2015"),),
        "screening": _screening(),
    }
    base.update(kw)
    return ProtocolSpec.model_validate(base)


def _check(
    spec: ProtocolSpec,
    mode: RigorMode = RigorMode.PILOT,
    *,
    seeds: Sequence[SeedRecord] = (),
    current: str = QID,
) -> ProtocolCheck:
    return protocol_issues(
        spec,
        question=QUESTION,
        current_question_id=current,
        mode=mode,
        seeds=list(seeds),
        probes=PROBES,
        known_sources=KNOWN_SOURCES,
    )


def _fields(issues: list[ValidationIssue]) -> list[str]:
    return [issue.field for issue in issues]


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
