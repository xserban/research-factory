"""The protocol service: recording, PRESS review, deviations and the search gate (R-11, R-19)."""

from typing import Any

import httpx
import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.protocol import (
    Criterion,
    MethodProfile,
    PlannedQuery,
    PressElement,
    PressFinding,
    ProtocolRecorded,
    ProtocolSpec,
    ProtocolStatus,
    Reviewer,
    ReviewerRole,
    ScreeningPlan,
    ScreeningStage,
    SourcePlan,
    protocol_version,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.protocol import (
    amend_protocol,
    confirm_press,
    current_protocol,
    press_review,
    record_deviation,
    record_protocol,
)
from factory.services.question import current_question, record_question
from factory.services.search import register_query, run_query
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import SourceFactory
from tests.helpers import (
    SESSION,
    SourcesFor,
    openalex_item,
    pilot_question_spec,
    ready_protocol,
    record_pilot_question,
)

SEARCH = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
FINDING = PressFinding(element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor")


def _events(project: Project, type_: str) -> list[Any]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == type_]


def _searches(project: Project) -> list[Any]:
    """The registered queries with search purpose; the helper's seed lookups and probe are not."""
    registered = _events(project, "query.registered")
    return [e for e in registered if e.payload["spec"]["purpose"] == QueryPurpose.SEARCH.value]


def _spec(question_id: str, *, probe_id: str | None = None, **overrides: Any) -> ProtocolSpec:
    """A pilot protocol that is ready only when `probe_id` names a probe that measured openalex."""
    criteria = (
        Criterion(
            id="IN01",
            parent="slot:population",
            statement="vision studies",
            rule="include vision studies",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
        ),
        *(
            Criterion(
                id=f"EX{n:02d}",
                parent=f"NG{n:02d}",
                statement=f"not topic {n}",
                rule=f"exclude topic {n}",
                applies_at=ScreeningStage.TITLE_ABSTRACT,
                priority=n,
            )
            for n in (1, 2, 3)
        ),
    )
    reviewer = Reviewer(role=ReviewerRole.REVIEWER_OF_RECORD, actor="obd", kind="human")
    base: dict[str, Any] = {
        "question_id": question_id,
        "method_profile": MethodProfile.SCOPING_REVIEW,
        "criteria": criteria,
        "sources": (SourcePlan(name="openalex", included=True, probe_id=probe_id),),
        "queries": (PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="attention"),),
        "screening": ScreeningPlan(
            passes=2, dual_sample=0.5, kappa_floor=0.7, reviewers=(reviewer,)
        ),
    }
    base.update(overrides)
    return ProtocolSpec.model_validate(base)


def _question_id(project: Project, actor: Actor) -> str:
    return record_pilot_question(project, actor)


# --- Recording (acceptance: draft, ready, replacement, identical resubmission) ---


def test_draft_with_gaps_is_written_and_gaps_returned(project: Project, agent: Actor) -> None:
    qid = _question_id(project, agent)
    result = record_protocol(project, agent, _spec(qid), ready=False)

    assert result.created is True
    assert result.status is ProtocolStatus.DRAFT
    assert "sources[0].probe_id" in [gap.field for gap in result.gaps]
    current = current_protocol(project)
    assert current is not None and current.status is ProtocolStatus.DRAFT


def test_ready_with_gaps_writes_nothing(project: Project, agent: Actor) -> None:
    qid = _question_id(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        record_protocol(project, agent, _spec(qid), ready=True)

    assert "sources[0].probe_id" in [issue.field for issue in raised.value.issues]
    assert _events(project, "protocol.recorded") == []
    assert current_protocol(project) is None


def test_structural_error_writes_nothing(project: Project, agent: Actor) -> None:
    qid = _question_id(project, agent)
    parentless = Criterion(
        id="IN01",
        parent=None,
        statement="vision studies",
        rule="include vision studies",
        applies_at=ScreeningStage.TITLE_ABSTRACT,
    )
    spec = _spec(qid, criteria=(parentless,))
    with pytest.raises(FactoryValidationError) as raised:
        record_protocol(project, agent, spec, ready=False)

    assert [issue.field for issue in raised.value.issues] == ["criteria[0].parent"]
    assert _events(project, "protocol.recorded") == []


def test_draft_can_be_replaced_ready_cannot(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    qid = _question_id(project, agent)
    record_protocol(project, agent, _spec(qid), ready=False)
    replaced = _spec(
        qid, queries=(PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="vision"),)
    )
    second = record_protocol(project, agent, replaced, ready=False)
    assert second.created is True
    assert len(_events(project, "protocol.recorded")) == 2

    protocol_id = ready_protocol(project, agent, project.human_actor(), mock_sources, press=False)
    with pytest.raises(FactoryValidationError) as raised:
        record_protocol(project, agent, _spec(qid), ready=False)
    [issue] = raised.value.issues
    assert issue.field == "protocol"
    assert issue.reason == "protocol is ready; change it with protocol_amend"
    current = current_protocol(project)
    assert current is not None and current.protocol_id == protocol_id


def test_record_refused_for_stale_ready_protocol(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    record_question(
        project, human, pilot_question_spec("Does linear attention match softmax?"), reason="reword"
    )
    question = current_question(project)
    assert question is not None

    stale_rebuild = old.spec.model_copy(update={"question_id": question.question_id})
    with pytest.raises(FactoryValidationError) as raised:
        record_protocol(project, agent, stale_rebuild, ready=True)

    [issue] = raised.value.issues
    assert issue.field == "protocol"
    assert issue.reason == "protocol is ready; change it with protocol_amend"
    assert len(_events(project, "protocol.recorded")) == 1
    current = current_protocol(project)
    assert current is not None and current.protocol_id == old.protocol_id


def test_identical_resubmission_writes_nothing(project: Project, agent: Actor) -> None:
    qid = _question_id(project, agent)
    first = record_protocol(project, agent, _spec(qid), ready=False)
    again = record_protocol(project, agent, _spec(qid), ready=False)

    assert first.created is True
    assert again.created is False
    assert again.protocol_id == first.protocol_id
    assert len(_events(project, "protocol.recorded")) == 1


# --- PRESS review and confirmation ---


def test_press_review_needs_agent_and_current_protocol(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = ready_protocol(project, agent, project.human_actor(), mock_sources, press=False)

    with pytest.raises(FactoryValidationError) as human_refused:
        press_review(project, project.human_actor(), protocol_id, (FINDING,))
    assert [i.field for i in human_refused.value.issues] == ["actor"]

    with pytest.raises(FactoryValidationError) as stale:
        press_review(project, agent, "P@00000000", (FINDING,))
    assert [i.field for i in stale.value.issues] == ["protocol_id"]

    review_id = press_review(project, agent, protocol_id, (FINDING,))
    assert review_id.startswith("prs_")
    assert len(_events(project, "protocol.press_reviewed")) == 1
    current = current_protocol(project)
    assert current is not None and current.press == "reviewed"


def test_press_confirmation_answers_every_finding(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    protocol_id = ready_protocol(project, agent, human, mock_sources, press=False)
    review_id = press_review(project, agent, protocol_id, (FINDING, FINDING))

    with pytest.raises(FactoryValidationError) as short:
        confirm_press(project, human, review_id, ("only one",))
    assert [i.field for i in short.value.issues] == ["responses"]

    with pytest.raises(FactoryValidationError) as blank:
        confirm_press(project, human, review_id, ("answer", "   "))
    assert [i.field for i in blank.value.issues] == ["responses"]

    confirm_press(project, human, review_id, ("answer one", "answer two"))
    [confirmed] = _events(project, "protocol.press_confirmed")
    assert confirmed.payload["responses"] == ["answer one", "answer two"]
    current = current_protocol(project)
    assert current is not None and current.press == "confirmed"


def test_press_confirmation_is_human_only(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = ready_protocol(project, agent, project.human_actor(), mock_sources, press=False)
    review_id = press_review(project, agent, protocol_id, (FINDING,))

    with pytest.raises(FactoryValidationError) as refused:
        confirm_press(project, agent, review_id, ("accepted",))
    assert [i.field for i in refused.value.issues] == ["actor"]
    assert _events(project, "protocol.press_confirmed") == []


def test_deviation_needs_a_protocol(project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        record_deviation(project, agent, description="one more query", reason="coverage")
    assert [i.field for i in raised.value.issues] == ["protocol"]


# --- The search gate (acceptance 9, R-19) ---


def test_search_refused_without_ready_protocol_in_pilot(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    _question_id(project, agent)
    with pytest.raises(FactoryValidationError) as raised:
        register_query(project, agent, SEARCH, sources=mock_sources(openalex=[]))

    assert [i.field for i in raised.value.issues] == ["protocol"]
    assert _searches(project) == []


def test_search_refused_before_press_confirmed(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    sources = mock_sources(openalex=[])
    protocol_id = ready_protocol(project, agent, human, mock_sources, press=False)

    with pytest.raises(FactoryValidationError) as none_yet:
        register_query(project, agent, SEARCH, sources=sources)
    assert [i.field for i in none_yet.value.issues] == ["press"]

    review_id = press_review(project, agent, protocol_id, (FINDING,))
    with pytest.raises(FactoryValidationError) as reviewed_only:
        register_query(project, agent, SEARCH, sources=sources)
    assert [i.field for i in reviewed_only.value.issues] == ["press"]

    confirm_press(project, human, review_id, ("accepted",))
    register_query(project, agent, SEARCH, sources=sources)
    assert len(_searches(project)) == 1


def test_search_refused_for_unplanned_query(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    unplanned = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="transformers")

    with pytest.raises(FactoryValidationError) as raised:
        register_query(project, agent, unplanned, sources=mock_sources(openalex=[]))
    assert [i.field for i in raised.value.issues] == ["query"]


def test_unplanned_query_runs_with_recorded_deviation(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, project.human_actor(), mock_sources)
    deviation_id = record_deviation(
        project,
        agent,
        description="Search transformers as well",
        reason="Synonym found in PRESS review",
        affects=("queries",),
    )
    unplanned = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="transformers")
    sources = mock_sources(openalex=[])

    query_id = register_query(project, agent, unplanned, sources=sources, deviation_id=deviation_id)
    run_query(project, query_id, sources=sources)

    [registered] = _searches(project)
    assert deviation_id in registered.refs
    assert query_id in registered.refs


def test_search_refused_when_question_changed_after_protocol(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources)
    old = current_protocol(project)
    assert old is not None

    record_question(
        project,
        human,
        pilot_question_spec("Does linear attention match softmax on speech?"),
        reason="scope changed",
    )
    with pytest.raises(FactoryValidationError) as raised:
        register_query(project, agent, SEARCH, sources=mock_sources(openalex=[]))

    [issue] = raised.value.issues
    assert issue.field == "protocol"
    assert issue.reason == (
        f"protocol is built on {old.spec.question_id}; amend it to the current question"
    )
    assert _searches(project) == []


def test_amended_protocol_restores_search(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources)
    old = current_protocol(project)
    assert old is not None
    record_question(
        project, human, pilot_question_spec("Does linear attention match softmax?"), reason="reword"
    )
    question = current_question(project)
    assert question is not None
    new_qid = question.question_id

    amended = old.spec.model_copy(update={"question_id": new_qid})
    result = amend_protocol(
        project, agent, amended, reason="question reworded", semantic=True, effects={}
    )
    assert result.from_version == old.protocol_id
    register_query(project, agent, SEARCH, sources=mock_sources(openalex=[]))
    assert len(_searches(project)) == 1


def test_probe_and_exploratory_searches_are_not_gated(
    project: Project, agent: Actor, settings: Any, clock: Any, mock_sources: SourcesFor
) -> None:
    _question_id(project, agent)
    probe = QuerySpec(
        source="openalex", kind=QueryKind.KEYWORD, text="attention", purpose=QueryPurpose.PROBE
    )
    register_query(project, agent, probe, sources=mock_sources(openalex=[]))

    explore = init_project(settings, "explore", "exploratory", session=SESSION, clock=clock)
    record_pilot_question(explore, agent)
    register_query(explore, agent, SEARCH, sources=mock_sources(openalex=[]))
    assert len(_searches(explore)) == 1


def test_query_registered_refs_protocol_version(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = ready_protocol(project, agent, project.human_actor(), mock_sources)
    register_query(project, agent, SEARCH, sources=mock_sources(openalex=[]))

    [registered] = _searches(project)
    assert protocol_id in registered.refs


def test_protocol_rebuild_equals_incremental(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources)
    before = project.index.state_hash()
    current = current_protocol(project)

    assert project.index.rebuild() == before
    assert current_protocol(project) == current


def test_duplicate_planned_query_is_refused_at_record_but_replays_from_the_log(
    project: Project, agent: Actor
) -> None:
    qid = _question_id(project, agent)
    twice = PlannedQuery(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    spec = _spec(qid, queries=(twice, twice))
    with pytest.raises(FactoryValidationError) as caught:
        record_protocol(project, agent, spec, ready=False)
    assert [i.field for i in caught.value.issues] == ["queries[1]"]
    assert _events(project, "protocol.recorded") == []

    # A log written before the rule held such a protocol; replay does not re-validate it.
    payload = ProtocolRecorded(
        protocol_id=protocol_version(spec), status=ProtocolStatus.DRAFT, spec=spec
    )
    project.record([project.events.make("protocol.recorded", payload, project.human_actor())])
    current = current_protocol(project)
    assert current is not None and current.spec == spec
    project.index.rebuild()
    assert current_protocol(project) == current


# --- Every agent purpose is gated like a search; probes stay ungated (final review, finding 1) ---


@pytest.mark.parametrize("purpose", [QueryPurpose.CHASE, QueryPurpose.SEED])
def test_chase_and_seed_queries_are_gated_like_searches_in_pilot(
    project: Project, agent: Actor, mock_sources: SourcesFor, purpose: QueryPurpose
) -> None:
    _question_id(project, agent)
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention", purpose=purpose)
    with pytest.raises(FactoryValidationError) as raised:
        register_query(project, agent, spec, sources=mock_sources(openalex=[]))

    assert [i.field for i in raised.value.issues] == ["protocol"]
    assert _events(project, "query.registered") == []


# --- Registered queries are re-gated at run time (final review, finding 3) ---


def _flaky_openalex() -> dict[str, SourceFactory]:
    """OpenAlex whose first page is good and whose second is not JSON: a PARTIAL, resumable run."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "*":
            page = {
                "meta": {"count": 2, "next_cursor": "c2"},
                "results": [
                    openalex_item(
                        title="Paper 9", author="Ada Zhou", published="2020-01-01", openalex_id="W9"
                    )
                ],
            }
            return httpx.Response(200, json=page)
        return httpx.Response(200, text="<html>not json</html>")

    polite = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )
    return {
        "openalex": SourceFactory(
            OpenAlexSource.kinds,
            lambda s, c: OpenAlexSource(polite, clock=c, mailto=s.mailto),
        )
    }


def test_registered_query_is_refused_at_run_and_resume_once_the_question_is_superseded(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    human = project.human_actor()
    ready_protocol(project, agent, human, mock_sources)
    flaky = _flaky_openalex()
    query_id = register_query(project, agent, SEARCH, sources=flaky)
    partial = run_query(project, query_id, sources=flaky)
    assert partial.status is RunStatus.PARTIAL and partial.resume_token == "c2"

    record_question(
        project,
        human,
        pilot_question_spec("Does linear attention match softmax on speech?"),
        reason="scope changed",
    )
    starts = len(_events(project, "search.run_started"))
    with pytest.raises(FactoryValidationError) as fresh:
        run_query(project, query_id, sources=flaky)
    assert [i.field for i in fresh.value.issues] == ["protocol"]
    with pytest.raises(FactoryValidationError) as resumed:
        run_query(project, query_id, sources=flaky, resume_run=partial.run_id)
    assert [i.field for i in resumed.value.issues] == ["protocol"]
    assert len(_events(project, "search.run_started")) == starts
