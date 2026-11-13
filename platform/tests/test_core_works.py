"""Core works (slice 8, IDEA-43): human marks, the guarded fold, seeds as core, forward sources."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import SnowballPlan, protocol_version
from factory.model.seed import SeedKind
from factory.services.context import Project
from factory.services.core_works import (
    core_marks,
    forward_core_sources,
    mark_core,
    seed_core_works,
    unmark_core,
)
from factory.services.search import list_works
from factory.services.seeds import SeedRole, all_seeds
from tests.document_helpers import events_of_type
from tests.extraction_helpers import PINNED_P_ID
from tests.helpers import SourcesFor, _setup, pilot_protocol_spec


def _world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> list[str]:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=3)
    return [w.id for w in list_works(project)]


def _fields(error: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in error.value.issues]


def test_plan_defaults_keep_current_behaviour_and_hash() -> None:
    plan = SnowballPlan(max_backward_rounds=2, max_forward_rounds=1)
    assert plan.forward_core_only is False
    assert plan.forward_topic_filter is None and plan.forward_max_per_work is None
    dumped = plan.model_dump(mode="json")
    assert set(dumped) == {"max_backward_rounds", "max_forward_rounds", "stop_when_no_new_included"}
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert protocol_version(spec) == PINNED_P_ID
    with_plan = spec.model_copy(update={"snowball_plan": plan})
    chosen = plan.model_copy(update={"forward_core_only": True})
    assert protocol_version(spec.model_copy(update={"snowball_plan": chosen})) != protocol_version(
        with_plan
    )
    assert chosen.model_dump(mode="json")["forward_core_only"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {"forward_max_per_work": 0},
        {"forward_topic_filter": "a,b"},
        {"forward_topic_filter": "  "},
        {"forward_topic_filter": "x" * 301},
        {"forward_topic_filter": "line\nbreak"},
    ],
)
def test_plan_forward_options_are_validated(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SnowballPlan.model_validate({"max_backward_rounds": 0, "max_forward_rounds": 1, **bad})


def test_mark_list_and_unmark(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    works = _world(project, agent, human, mock_sources)
    target = works[0]
    assert core_marks(project) == []
    event_id = mark_core(project, human, target, " central to the field ")
    [mark] = core_marks(project)
    assert (mark.work_id, mark.note, mark.event_id) == (target, "central to the field", event_id)
    with pytest.raises(FactoryValidationError) as again:
        mark_core(project, human, target)
    assert _fields(again) == [("work_id", "already-core")]
    unmark_core(project, human, target)
    assert core_marks(project) == []
    with pytest.raises(FactoryValidationError) as missing:
        unmark_core(project, human, target)
    assert _fields(missing) == [("work_id", "not-marked")]
    assert len(events_of_type(project, "work.marked_core")) == 1
    assert len(events_of_type(project, "work.unmarked_core")) == 1


def test_only_a_human_marks_and_nothing_is_written(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    works = _world(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as refused:
        mark_core(project, agent, works[0])
    assert _fields(refused) == [("actor", "human-only")]
    mark_core(project, human, works[0])
    with pytest.raises(FactoryValidationError):
        unmark_core(project, agent, works[0])
    assert events_of_type(project, "work.unmarked_core") == []
    assert len(core_marks(project)) == 1


def test_unknown_or_malformed_work_and_bad_note_are_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    works = _world(project, agent, human, mock_sources)
    with pytest.raises(FactoryValidationError) as unknown:
        mark_core(project, human, "rf:unknown-work-00000000")
    assert unknown.value.issues
    with pytest.raises(FactoryValidationError) as malformed:
        mark_core(project, human, "not a work id")
    assert _fields(malformed) == [("work_id", "not a work id")]
    with pytest.raises(FactoryValidationError):
        mark_core(project, human, works[0], "x" * 501)
    assert events_of_type(project, "work.marked_core") == []


def test_an_agent_written_event_changes_nothing_on_rebuild(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from factory.model.core_works import WorkMarkedCore

    works = _world(project, agent, human, mock_sources)
    forged = project.events.make(
        "work.marked_core",
        WorkMarkedCore(work_id=works[0]),
        agent,
        refs=(works[0],),
        input_blob=project.blobs.put_json({"forged": True}),
    )
    project.record([forged])
    assert core_marks(project) == []
    mark_core(project, human, works[1])
    project.index.rebuild()
    assert [m.work_id for m in core_marks(project)] == [works[1]]


def test_a_mark_of_an_unknown_work_written_by_hand_changes_nothing(
    project: Project, human: Actor
) -> None:
    from factory.model.core_works import WorkMarkedCore

    forged = project.events.make(
        "work.marked_core", WorkMarkedCore(work_id="rf:unknown-work-11111111"), human, refs=()
    )
    project.record([forged])
    assert core_marks(project) == []


def test_seeds_are_core_and_held_out_ones_are_not_named_to_agents(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    seeds = all_seeds(project)
    held = {s.work_id for s in seeds if s.role is SeedRole.HELD_OUT and s.work_id}
    development = {
        s.work_id
        for s in seeds
        if s.kind is SeedKind.POSITIVE and s.role is not SeedRole.HELD_OUT and s.work_id
    }
    assert held and development
    assert set(seed_core_works(project)) == held | development
    assert set(seed_core_works(project, development_only=True)) == development


def test_forward_core_sources_are_marked_included_works_and_seeds(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    works = _world(project, agent, human, mock_sources)
    seeds = set(seed_core_works(project, development_only=True))
    plain = sorted(set(works) - set(seed_core_works(project)))
    mark_core(project, human, plain[0])
    mark_core(project, human, plain[1])
    assert forward_core_sources(project, included=[plain[0]]) == sorted(seeds | {plain[0]})
    assert forward_core_sources(project, included=[]) == sorted(seeds)


def test_a_held_out_seed_work_is_a_forward_source_only_when_a_human_marks_it(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _world(project, agent, human, mock_sources)
    seeds = all_seeds(project)
    held = sorted({s.work_id for s in seeds if s.role is SeedRole.HELD_OUT and s.work_id})
    assert held
    development = set(seed_core_works(project, development_only=True))
    assert set(forward_core_sources(project, included=held)) == development
    mark_core(project, human, held[0])
    assert set(forward_core_sources(project, included=held)) == development | {held[0]}
