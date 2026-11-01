"""Amendments: criterion changes, stale rules, the amendment service and stale decisions (R-11).

The pure tests build protocol specs and amendment records directly. The service tests amend a
ready pilot protocol on a real project.
"""

from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.protocol import (
    ChangeKind,
    Criterion,
    CriterionChange,
    CriterionEffect,
    MethodProfile,
    PlannedQuery,
    ProtocolAmended,
    ProtocolSpec,
    ProtocolStatus,
    Reviewer,
    ReviewerRole,
    ScreeningPlan,
    ScreeningStage,
    SourcePlan,
    protocol_version,
)
from factory.model.search import QueryKind, QuerySpec
from factory.services.context import Project
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
    list_amendments,
    list_deviations,
    protocol_lineage,
    record_deviation,
    record_protocol,
)
from factory.services.protocol_rules import (
    DecisionRef,
    criterion_changes,
    stale_decisions,
    stale_rules,
)
from factory.services.search import register_query
from tests.helpers import SourcesFor, ready_protocol, record_pilot_question

TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT
AMD_ID = "amd_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
QUESTION = "Q@0badcafe"
SEARCH = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")


# --- Builders for pure tests ---


def _exclusion(n: int, *, stage: ScreeningStage = TA, rule: str | None = None) -> Criterion:
    return Criterion(
        id=f"EX{n:02d}",
        parent=f"NG{n:02d}",
        statement=f"not topic {n}",
        rule=rule or f"exclude topic {n}",
        applies_at=stage,
        priority=n,
    )


def _inclusion(*, stage: ScreeningStage = TA, rule: str = "include vision") -> Criterion:
    return Criterion(
        id="IN01",
        parent="slot:population",
        statement="vision",
        rule=rule,
        applies_at=stage,
    )


def _spec(*criteria: Criterion, question_id: str = QUESTION) -> ProtocolSpec:
    reviewer = Reviewer(role=ReviewerRole.REVIEWER_OF_RECORD, actor="obd", kind="human")
    return ProtocolSpec(
        question_id=question_id,
        method_profile=MethodProfile.SCOPING_REVIEW,
        criteria=criteria,
        sources=(SourcePlan(name="openalex", included=True, probe_id="probe_x"),),
        queries=(PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="attention"),),
        screening=ScreeningPlan(passes=2, dual_sample=0.5, kappa_floor=0.7, reviewers=(reviewer,)),
    )


def _amendment(
    old: ProtocolSpec,
    new: ProtocolSpec,
    effects: dict[str, CriterionEffect],
) -> ProtocolAmended:
    changes = tuple(
        CriterionChange(
            cid=cid,
            change=kind,
            effect=effects.get(cid) if kind is ChangeKind.CHANGED else None,
        )
        for cid, kind in criterion_changes(old, new)
    )
    return ProtocolAmended(
        amendment_id=AMD_ID,
        from_version=protocol_version(old),
        to_version=protocol_version(new),
        spec=new,
        reason="test",
        semantic=True,
        changes=changes,
        stale_rules=tuple(stale_rules(changes, old, new)),
    )


def _decision(
    decision_id: str,
    verdict: str,
    criterion: str | None,
    version: str,
    stage: ScreeningStage = TA,
) -> DecisionRef:
    return DecisionRef(
        decision_id=decision_id,
        verdict=verdict,
        criterion=None if criterion is None else f"{version}:{criterion}",
        protocol_id=version,
        stage=stage,
    )


# --- Criterion changes and stale rules (pure) ---


def test_loosening_exclusion_stales_exclusions_citing_it() -> None:
    old = _spec(_inclusion(), _exclusion(2), _exclusion(3))
    new = _spec(_inclusion(), _exclusion(2), _exclusion(3, rule="exclude only severe topic 3"))
    old_version = protocol_version(old)
    decisions = [
        _decision("dec_a", "exclude", "EX03", old_version),
        _decision("dec_b", "exclude", "EX02", old_version),
        _decision("dec_c", "include", "IN01", old_version),
    ]

    changes = criterion_changes(old, new)
    assert changes == [("EX03", ChangeKind.CHANGED)]
    loosened = _amendment(old, new, {"EX03": CriterionEffect.LOOSENED})
    assert [(r.criterion, r.stales, r.stage) for r in loosened.stale_rules] == [
        ("EX03", "exclusions-citing", TA)
    ]
    assert stale_decisions([loosened], [old_version, protocol_version(new)], decisions) == ["dec_a"]


def test_tightening_stales_inclusions_only() -> None:
    old = _spec(_inclusion(), _exclusion(2))
    new = _spec(_inclusion(rule="include vision with a named benchmark"), _exclusion(2))
    old_version = protocol_version(old)
    tightened = _amendment(old, new, {"IN01": CriterionEffect.TIGHTENED})
    decisions = [
        _decision("dec_inc", "include", "IN01", old_version),
        _decision("dec_exc", "exclude", "EX02", old_version),
    ]

    assert [(r.stales, r.stage) for r in tightened.stale_rules] == [("inclusions", TA)]
    lineage = [old_version, protocol_version(new)]
    assert stale_decisions([tightened], lineage, decisions) == ["dec_inc"]


def test_added_criterion_stales_decisions_untested_at_its_stage() -> None:
    old = _spec(_inclusion(), _exclusion(2))
    new = _spec(_inclusion(), _exclusion(2), _exclusion(4, stage=FT))
    old_version = protocol_version(old)
    decisions = [
        _decision("dec_ta", "exclude", "EX02", old_version, stage=TA),
        _decision("dec_ft", "include", "IN01", old_version, stage=FT),
    ]

    added = _amendment(old, new, {})
    assert [(c.cid, c.change) for c in added.changes] == [("EX04", ChangeKind.ADDED)]
    assert [(r.criterion, r.stales, r.stage) for r in added.stale_rules] == [
        ("EX04", "untested", FT)
    ]
    assert stale_decisions([added], [old_version, protocol_version(new)], decisions) == ["dec_ft"]


def test_removed_criterion_stales_its_exclusions() -> None:
    old = _spec(_inclusion(), _exclusion(2), _exclusion(3))
    new = _spec(_inclusion(), _exclusion(2))
    old_version = protocol_version(old)
    decisions = [
        _decision("dec_ex3", "exclude", "EX03", old_version),
        _decision("dec_ex2", "exclude", "EX02", old_version),
        _decision("dec_in", "include", "IN01", old_version),
    ]

    removed = _amendment(old, new, {})
    assert [(r.criterion, r.stales, r.stage) for r in removed.stale_rules] == [
        ("EX03", "exclusions-citing", TA)
    ]
    assert stale_decisions([removed], [old_version, protocol_version(new)], decisions) == [
        "dec_ex3"
    ]


def test_renamed_criterion_is_removed_plus_added() -> None:
    old = _spec(_inclusion(), _exclusion(2), _exclusion(3))
    renamed = Criterion(
        id="EX04",
        parent="NG03",
        statement="not topic 3",
        rule="exclude topic 3",
        applies_at=TA,
        priority=3,
    )
    new = _spec(_inclusion(), _exclusion(2), renamed)
    old_version = protocol_version(old)

    assert criterion_changes(old, new) == [
        ("EX03", ChangeKind.REMOVED),
        ("EX04", ChangeKind.ADDED),
    ]
    amendment = _amendment(old, new, {})
    assert [(r.criterion, r.stales) for r in amendment.stale_rules] == [
        ("EX03", "exclusions-citing"),
        ("EX04", "untested"),
    ]
    decisions = [
        _decision("dec_ex3", "exclude", "EX03", old_version),
        _decision("dec_untested", "include", "IN01", old_version),
    ]
    assert stale_decisions([amendment], [old_version, protocol_version(new)], decisions) == [
        "dec_ex3",
        "dec_untested",
    ]


def test_clarification_stales_nothing() -> None:
    old = _spec(_inclusion(), _exclusion(2))
    new = _spec(_inclusion(), _exclusion(2, rule="exclude topic two, explicitly"))
    old_version = protocol_version(old)
    clarified = _amendment(old, new, {"EX02": CriterionEffect.CLARIFIED})

    assert clarified.stale_rules == ()
    decisions = [_decision("dec_ex2", "exclude", "EX02", old_version)]
    assert stale_decisions([clarified], [old_version, protocol_version(new)], decisions) == []


def test_decisions_after_the_amendment_are_not_stale() -> None:
    old = _spec(_inclusion(), _exclusion(3))
    new = _spec(_inclusion(), _exclusion(3, rule="exclude only severe topic 3"))
    loosened = _amendment(old, new, {"EX03": CriterionEffect.LOOSENED})
    new_version = protocol_version(new)
    decisions = [_decision("dec_after", "exclude", "EX03", new_version)]

    lineage = [protocol_version(old), new_version]
    assert stale_decisions([loosened], lineage, decisions) == []


# --- The amendment service ---


def _with_criteria(spec: ProtocolSpec, *criteria: Criterion) -> ProtocolSpec:
    return spec.model_copy(update={"criteria": criteria})


def _replace(spec: ProtocolSpec, new: Criterion) -> ProtocolSpec:
    return _with_criteria(spec, *(new if c.id == new.id else c for c in spec.criteria))


def _amended_events(project: Project) -> list[Any]:
    events = read_all(project.paths.events_dir, project.catalog)
    return [e for e in events if e.type == "protocol.amended"]


def test_prose_only_amendment_keeps_version(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    prose = old.spec.model_copy(update={"rationale": "Reworded for the protocol record."})

    result = amend_protocol(project, agent, prose, reason="prose", semantic=False, effects={})

    assert result.prose_only is True
    assert result.from_version == result.to_version == old.protocol_id
    assert result.stale_rules == []
    [event] = _amended_events(project)
    assert event.payload["from_version"] == event.payload["to_version"] == old.protocol_id
    current = current_protocol(project)
    assert current is not None and current.protocol_id == old.protocol_id
    assert current.spec.rationale == "Reworded for the protocol record."


def test_amendment_on_draft_refused(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    question_id = record_pilot_question(project, agent)
    draft = _spec(_inclusion(), _exclusion(1), question_id=question_id)
    record_protocol(project, agent, draft, ready=False)

    with pytest.raises(FactoryValidationError) as raised:
        amend_protocol(
            project,
            agent,
            draft.model_copy(update={"rationale": "x"}),
            reason="why",
            semantic=False,
            effects={},
        )
    assert [issue.field for issue in raised.value.issues] == ["protocol"]
    assert _amended_events(project) == []


def test_effects_must_cover_exactly_the_changed_criteria(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    changed = _replace(old.spec, _exclusion(2, rule="exclude a narrower topic two"))

    with pytest.raises(FactoryValidationError) as missing:
        amend_protocol(project, agent, changed, reason="narrow", semantic=True, effects={})
    assert [issue.field for issue in missing.value.issues] == ["effects"]
    assert "missing: EX02" in missing.value.issues[0].reason

    with pytest.raises(FactoryValidationError) as unexpected:
        amend_protocol(
            project,
            agent,
            changed,
            reason="narrow",
            semantic=True,
            effects={"EX02": CriterionEffect.TIGHTENED, "EX03": CriterionEffect.LOOSENED},
        )
    assert [issue.field for issue in unexpected.value.issues] == ["effects"]
    assert "unexpected: EX03" in unexpected.value.issues[0].reason
    assert _amended_events(project) == []


def test_semantic_flag_must_match_changes(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    loosened = _replace(old.spec, _exclusion(2, rule="exclude a narrower topic two"))

    with pytest.raises(FactoryValidationError) as wrong:
        amend_protocol(
            project,
            agent,
            loosened,
            reason="narrow",
            semantic=False,
            effects={"EX02": CriterionEffect.LOOSENED},
        )
    assert [issue.field for issue in wrong.value.issues] == ["semantic"]

    clarified = _replace(old.spec, _exclusion(2, rule="exclude topic two, explicitly"))
    result = amend_protocol(
        project,
        agent,
        clarified,
        reason="clarify",
        semantic=False,
        effects={"EX02": CriterionEffect.CLARIFIED},
    )
    assert result.prose_only is False
    assert result.stale_rules == []


def test_amended_protocol_must_stay_ready(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    without_ex1 = _with_criteria(old.spec, *(c for c in old.spec.criteria if c.id != "EX01"))

    with pytest.raises(FactoryValidationError) as raised:
        amend_protocol(project, agent, without_ex1, reason="drop", semantic=True, effects={})
    assert "non_goals.NG01" in [issue.field for issue in raised.value.issues]
    assert _amended_events(project) == []
    current = current_protocol(project)
    assert current is not None and current.protocol_id == old.protocol_id


def test_press_carries_over_when_search_strategy_unchanged(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    protocol_id = ready_protocol(project, agent, human, mock_sources)
    old = current_protocol(project)
    assert old is not None and old.press == "confirmed"
    clarified = _replace(old.spec, _exclusion(2, rule="exclude topic two, explicitly"))

    result = amend_protocol(
        project,
        agent,
        clarified,
        reason="clarify",
        semantic=False,
        effects={"EX02": CriterionEffect.CLARIFIED},
    )

    assert result.from_version == protocol_id
    assert result.to_version != protocol_id
    current = current_protocol(project)
    assert current is not None
    assert current.protocol_id == result.to_version
    assert current.press == "confirmed"
    register_query(project, agent, SEARCH, sources=mock_sources(openalex=[]))


def test_query_change_needs_new_press(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources)
    old = current_protocol(project)
    assert old is not None
    retargeted = old.spec.model_copy(
        update={
            "queries": (PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="vision"),)
        }
    )

    result = amend_protocol(
        project, agent, retargeted, reason="new query", semantic=True, effects={}
    )

    assert result.to_version != result.from_version
    current = current_protocol(project)
    assert current is not None and current.press == "none"
    vision = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="vision")
    with pytest.raises(FactoryValidationError) as raised:
        register_query(project, agent, vision, sources=mock_sources(openalex=[]))
    assert [issue.field for issue in raised.value.issues] == ["press"]


def test_amendments_and_deviations_listed_separately(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    deviation_id = record_deviation(project, agent, description="extra", reason="coverage")
    clarified = _replace(old.spec, _exclusion(2, rule="exclude topic two, explicitly"))
    amend_protocol(
        project,
        agent,
        clarified,
        reason="clarify",
        semantic=False,
        effects={"EX02": CriterionEffect.CLARIFIED},
    )

    amendments = list_amendments(project)
    deviations = list_deviations(project)
    assert [a.from_version for a in amendments] == [old.protocol_id]
    assert [d.deviation_id for d in deviations] == [deviation_id]
    assert protocol_lineage(project) == [old.protocol_id, protocol_version(clarified)]


def test_amendment_rebuild_equals_incremental(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    loosened = _replace(old.spec, _exclusion(2, rule="exclude only severe topic two"))
    amend_protocol(
        project,
        agent,
        loosened,
        reason="loosen",
        semantic=True,
        effects={"EX02": CriterionEffect.LOOSENED},
    )
    before = project.index.state_hash()
    amendments = list_amendments(project)
    current = current_protocol(project)

    assert project.index.rebuild() == before
    assert list_amendments(project) == amendments
    assert current_protocol(project) == current
    assert current is not None and current.status is ProtocolStatus.READY
