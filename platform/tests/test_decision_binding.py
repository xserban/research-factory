"""Binding: the records that implement a decision cite it (slice 8, plan task A7).

In `pilot` and `systematic` a question, seeds, a probe and a protocol are refused unless they cite
a selected decision at their own level; `exploratory` may skip it. A refusal writes nothing, and
the cited ids travel in the event without touching any version hash.
"""

from __future__ import annotations

from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.model.question import QuestionRecorded, question_version
from factory.model.screening import Channel
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.services import decision_binding
from factory.services import decisions as decisions_service
from factory.services.context import Project
from factory.services.probe import run_probe
from factory.services.protocol import record_protocol
from factory.services.question import record_question, state_goal
from factory.services.seeds import add_seeds
from tests.helpers import (
    SourcesFor,
    _seed_item,
    bind_ids,
    pilot_protocol_spec,
    pilot_question_spec,
)

LEVELS = DecisionLevel


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _events(project: Project, type_: str) -> list[Any]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == type_]


def _open(project: Project, agent: Actor, level: DecisionLevel = LEVELS.QUESTIONS) -> str:
    """A suggested decision no one has selected."""
    return decisions_service.suggest(
        project,
        agent,
        level,
        "test-setting",
        "Fixture decision.",
        (DecisionItem(item_id="I01", text="Fixture item", grounds=("test fixture",)),),
    )


def _fields(raised: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in raised.value.issues]


def test_pilot_question_needs_a_selected_decision(project: Project, agent: Actor) -> None:
    state_goal(project, agent, "Compare attention on vision")
    spec = pilot_question_spec()
    before = _count(project)
    with pytest.raises(FactoryValidationError) as raised:
        record_question(project, agent, spec)
    assert _fields(raised) == ["decision_ids"]
    assert _count(project) == before


def test_an_unselected_wrong_level_unknown_or_superseded_decision_is_refused(
    project: Project, agent: Actor, human: Actor
) -> None:
    state_goal(project, agent, "Compare attention on vision")
    spec = pilot_question_spec()
    open_id = _open(project, agent)
    seeds_id = bind_ids(project, agent, LEVELS.SEEDS)[0]
    old = bind_ids(project, agent, LEVELS.QUESTIONS)[0]
    decisions_service.suggest(
        project,
        agent,
        LEVELS.QUESTIONS,
        "test-setting",
        "Replaces the first.",
        (DecisionItem(item_id="I01", text="Fixture item"),),
        supersedes=old,
    )
    for ids in ([open_id], [seeds_id], ["dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X"], [old]):
        before = _count(project)
        with pytest.raises(FactoryValidationError) as raised:
            record_question(project, agent, spec, decision_ids=ids)
        assert _fields(raised) == ["decision_ids.0"]
        assert _count(project) == before
    with pytest.raises(FactoryValidationError) as raised:
        record_question(project, agent, spec, decision_ids=[old, old])
    assert _fields(raised) == ["decision_ids"]


def test_a_selected_decision_is_cited_and_leaves_the_version_unchanged(
    project: Project, agent: Actor
) -> None:
    state_goal(project, agent, "Compare attention on vision")
    spec = pilot_question_spec()
    ids = bind_ids(project, agent, LEVELS.QUESTIONS)
    result = record_question(project, agent, spec, decision_ids=ids)
    assert result.question_id == question_version(spec)
    [event] = _events(project, "question.recorded")
    assert event.payload["decision_ids"] == ids
    # An unchanged spec writes nothing and needs no decision.
    assert record_question(project, agent, spec).created is False


def test_an_event_written_before_the_slice_still_folds() -> None:
    spec = pilot_question_spec()
    old = {"question_id": question_version(spec), "spec": spec.model_dump(mode="json")}
    assert QuestionRecorded.model_validate(old).decision_ids is None


def test_exploratory_may_skip_but_never_cite_a_wrong_decision(
    explore_project: Project, agent: Actor
) -> None:
    project = explore_project
    state_goal(project, agent, "Compare attention on vision")
    spec = pilot_question_spec()
    wrong = bind_ids(project, agent, LEVELS.SEEDS)
    with pytest.raises(FactoryValidationError) as raised:
        record_question(project, agent, spec, decision_ids=wrong)
    assert _fields(raised) == ["decision_ids.0"]
    record_question(project, agent, spec)
    [event] = _events(project, "question.recorded")
    assert event.payload["decision_ids"] == []


def test_pilot_seeds_are_refused_whole_without_a_decision(
    project: Project, agent: Actor, mock_sources: SourcesFor
) -> None:
    specs = [
        SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}") for n in (1, 2)
    ]
    before = _count(project)
    with pytest.raises(FactoryValidationError) as raised:
        add_seeds(project, agent, specs, sources=mock_sources(openalex=[_seed_item(1)]))
    assert _fields(raised) == ["decision_ids"]
    assert _count(project) == before
    ids = bind_ids(project, agent, LEVELS.SEEDS)
    add_seeds(
        project, agent, specs[:1], sources=mock_sources(openalex=[_seed_item(1)]), decision_ids=ids
    )
    [event] = _events(project, "seed.added")
    assert event.payload["decision_ids"] == ids


def test_pilot_probe_and_protocol_need_their_own_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    state_goal(project, agent, "Compare attention on vision")
    question_id = record_question(
        project,
        agent,
        pilot_question_spec(),
        decision_ids=bind_ids(project, agent, LEVELS.QUESTIONS),
    ).question_id
    seed_ids = bind_ids(project, agent, LEVELS.SEEDS)
    for n in (1, 2, 3):
        seed = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
        add_seeds(
            project,
            agent,
            [seed],
            sources=mock_sources(openalex=[_seed_item(n)]),
            decision_ids=seed_ids,
        )
    probe = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    sources = mock_sources(openalex=[_seed_item(1)])

    before = _count(project)
    for wrong in (None, seed_ids):  # no decision, and a decision at the wrong level
        with pytest.raises(FactoryValidationError) as raised:
            run_probe(project, agent, [probe], sources=sources, decision_ids=wrong)
        assert _fields(raised)[0].startswith("decision_ids")
    assert _count(project) == before

    probe_ids = bind_ids(project, agent, LEVELS.PROBE)
    report = run_probe(project, agent, [probe], sources=sources, decision_ids=probe_ids)
    assert {e.payload["decision_ids"][0] for e in _events(project, "probe.measured")} == {
        probe_ids[0]
    }

    spec = pilot_protocol_spec(question_id, report.probe_id, reviewer=human.id)
    before = _count(project)
    with pytest.raises(FactoryValidationError) as raised:
        record_protocol(project, agent, spec, ready=True)
    assert _fields(raised) == ["decision_ids"]
    assert _count(project) == before
    protocol_ids = bind_ids(project, agent, LEVELS.PROTOCOL)
    record_protocol(project, agent, spec, ready=True, decision_ids=protocol_ids)
    [event] = _events(project, "protocol.recorded")
    assert event.payload["decision_ids"] == protocol_ids


def test_a_none_of_these_selection_still_counts_as_selected(
    project: Project, agent: Actor, human: Actor
) -> None:
    decision_id = _open(project, agent)
    decisions_service.select(project, human, decision_id, [], [], "none fit", Channel.CLI)
    assert decision_binding.bind(project, LEVELS.QUESTIONS, [decision_id]) == (decision_id,)
