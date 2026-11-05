"""Registered conclusions with a verified basis (living-D, task 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.living.facts import ConclusionFacts, GroupFacts
from factory.model.conclusions import BasisRef, Predicate
from factory.model.notices import NoticeKind, NoticeObserved
from factory.services import conclusions as service
from factory.services.conclusions import (
    basis_state,
    conclusions,
    predicate_value,
    register_conclusion,
    retire_conclusion,
)
from factory.services.context import Project
from tests.helpers import SourcesFor
from tests.notice_helpers import NoticeWorld, dependent_world, numbered_records

GROUP = "grp_0123456789ab"
ROW = "rk_0123456789ab"
OTHER = "rk_ba9876543210"


def facts(**best: tuple[str, ...] | None) -> ConclusionFacts:
    return ConclusionFacts(
        included=5,
        groups=(
            GroupFacts(
                group_id=GROUP,
                independent_rows=3,
                frontier={"params|count||": (ROW,)},
                best=best.get("best", (ROW,)),
                best_reason=None,
            ),
        ),
    )


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    return dependent_world(project, agent, human, mock_sources, numbered_records(5))


def event_count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def work_basis(world: NoticeWorld, index: int = 0) -> BasisRef:
    return BasisRef(kind="work", ref=world.included[index])


def test_agent_cannot_register(world: NoticeWorld, agent: Actor) -> None:
    before = event_count(world.project)
    with pytest.raises(FactoryValidationError) as caught:
        register_conclusion(world.project, agent, "A statement.", [work_basis(world)], None)
    assert any(i.field == "actor" for i in caught.value.issues)
    assert event_count(world.project) == before
    assert conclusions(world.project) == []


def test_registers_with_resolving_work_basis(world: NoticeWorld, human: Actor) -> None:
    cid = register_conclusion(
        world.project, human, "Linear attention wins.", [work_basis(world)], None
    )
    assert cid.startswith("ccl_")
    [one] = conclusions(world.project)
    assert one.conclusion_id == cid and one.statement == "Linear attention wins."
    assert one.basis == (work_basis(world),) and one.predicate is None and not one.retired


def test_unresolvable_basis_refused(world: NoticeWorld, human: Actor) -> None:
    before = event_count(world.project)
    for bad in (
        BasisRef(kind="work", ref="rf:unknown-deadbeef"),
        BasisRef(kind="row", ref="rk_ffffffffffff"),
        BasisRef(kind="cell", ref="rk_ffffffffffff/value"),
        BasisRef(kind="group", ref=GROUP),
    ):
        with pytest.raises(FactoryValidationError) as caught:
            register_conclusion(world.project, human, "Statement.", [work_basis(world), bad], None)
        assert any(i.field == "basis" for i in caught.value.issues), bad
    assert event_count(world.project) == before


def test_relation_basis_refused_without_lineage(world: NoticeWorld, human: Actor) -> None:
    with pytest.raises(FactoryValidationError):
        register_conclusion(
            world.project,
            human,
            "Statement.",
            [BasisRef(kind="relation", ref="rel_01JZ9Q3K5M7N8P0R2S4T6V8W1A")],
            None,
        )


def test_blank_statement_and_empty_basis_refused(world: NoticeWorld, human: Actor) -> None:
    with pytest.raises(FactoryValidationError):
        register_conclusion(world.project, human, "   ", [work_basis(world)], None)
    with pytest.raises(FactoryValidationError):
        register_conclusion(world.project, human, "Statement.", [], None)


def test_basis_reference_shape_is_checked_per_kind() -> None:
    with pytest.raises(ValidationError):
        BasisRef(kind="row", ref="not-a-row")
    with pytest.raises(ValidationError):
        BasisRef(kind="cell", ref=ROW)  # a cell names a field
    BasisRef(kind="cell", ref=f"{ROW}/value")


def test_predicate_fields_per_kind() -> None:
    Predicate(kind="frontier-member", group_id=GROUP, axis_key="params|count||", row_key=ROW)
    Predicate(kind="best-in-group", group_id=GROUP, row_key=ROW)
    Predicate(kind="group-row-count-at-least", group_id=GROUP, count=2)
    Predicate(kind="path-exists", source="rf:a", target="rf:b")
    for bad in (
        {"kind": "frontier-member", "group_id": GROUP, "row_key": ROW},  # no axis key
        {"kind": "best-in-group", "group_id": GROUP},  # no row
        {"kind": "group-row-count-at-least", "group_id": GROUP},  # no count
        {"kind": "group-row-count-at-least", "group_id": GROUP, "count": 0},
        {"kind": "path-exists", "source": "rf:a"},
        {"kind": "best-in-group", "group_id": GROUP, "row_key": ROW, "count": 2},  # stray field
    ):
        with pytest.raises(ValidationError):
            Predicate.model_validate(bad)


def test_path_exists_refused_without_lineage(world: NoticeWorld, human: Actor) -> None:
    before = event_count(world.project)
    with pytest.raises(FactoryValidationError) as caught:
        register_conclusion(
            world.project,
            human,
            "Statement.",
            [work_basis(world)],
            Predicate(kind="path-exists", source="rf:a", target="rf:b"),
        )
    assert any(i.field == "predicate" for i in caught.value.issues)
    assert event_count(world.project) == before


def test_predicate_arguments_must_exist_in_the_facts(
    world: NoticeWorld, human: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "current_facts", lambda project: facts())
    ok = Predicate(kind="group-row-count-at-least", group_id=GROUP, count=2)
    register_conclusion(world.project, human, "Statement.", [work_basis(world)], ok)
    for bad in (
        Predicate(kind="group-row-count-at-least", group_id="grp_ffffffffffff", count=2),
        Predicate(kind="frontier-member", group_id=GROUP, axis_key="flops|count||", row_key=ROW),
    ):
        with pytest.raises(FactoryValidationError) as caught:
            register_conclusion(world.project, human, "Statement.", [work_basis(world)], bad)
        assert any(i.field == "predicate" for i in caught.value.issues)
    assert len(conclusions(world.project)) == 1


def test_retired_conclusion_not_evaluated(world: NoticeWorld, human: Actor, agent: Actor) -> None:
    cid = register_conclusion(world.project, human, "Statement.", [work_basis(world)], None)
    with pytest.raises(FactoryValidationError):
        retire_conclusion(world.project, agent, cid, "no")
    with pytest.raises(FactoryValidationError):
        retire_conclusion(world.project, human, cid, "  ")
    retire_conclusion(world.project, human, cid, "superseded by a better framing")
    assert conclusions(world.project) == []
    [kept] = conclusions(world.project, include_retired=True)
    assert kept.retired and kept.retire_reason == "superseded by a better framing"
    with pytest.raises(FactoryValidationError):
        retire_conclusion(world.project, human, cid, "again")
    with pytest.raises(FactoryValidationError):
        retire_conclusion(world.project, human, "ccl_01JZ9Q3K5M7N8P0R2S4T6V8W1A", "unknown")


def test_predicate_value_cases() -> None:
    f = facts()
    member = Predicate(
        kind="frontier-member", group_id=GROUP, axis_key="params|count||", row_key=ROW
    )
    assert predicate_value(f, member) is True
    assert predicate_value(f, member.model_copy(update={"row_key": OTHER})) is False
    assert predicate_value(f, member.model_copy(update={"axis_key": "flops|count||"})) is False
    assert predicate_value(f, member.model_copy(update={"group_id": "grp_ffffffffffff"})) is None
    best = Predicate(kind="best-in-group", group_id=GROUP, row_key=ROW)
    assert predicate_value(f, best) is True
    assert predicate_value(f, best.model_copy(update={"row_key": OTHER})) is False
    assert predicate_value(facts(best=None), best) is None
    count = Predicate(kind="group-row-count-at-least", group_id=GROUP, count=3)
    assert predicate_value(f, count) is True
    assert predicate_value(f, count.model_copy(update={"count": 4})) is False
    path = Predicate(kind="path-exists", source="rf:a", target="rf:b")
    assert predicate_value(f, path) is None
    with_path = f.model_copy(update={"paths": (("rf:a", "rf:b", True),)})
    assert predicate_value(with_path, path) is True


def test_basis_state_retracted_work(world: NoticeWorld) -> None:
    project = world.project
    first, second = world.included[0], world.included[1]
    basis = [BasisRef(kind="work", ref=first), BasisRef(kind="work", ref=second)]
    assert basis_state(project, basis) == ()
    payload = NoticeObserved(
        notice_id=project.ids.new("ntc"),
        work_id=first,
        kind=NoticeKind.RETRACTION,
        notice_date=None,
        notice_doi="10.2000/ret",
        source="crossref",
        run_id=project.ids.new("run"),
        raw_blob="sha256:" + "b" * 64,
    )
    project.record(
        [
            project.events.make(
                "notice.observed", payload, project.system_actor(), refs=(payload.notice_id, first)
            )
        ]
    )
    assert basis_state(project, basis) == (f"work:{first}: notice-retracted",)
