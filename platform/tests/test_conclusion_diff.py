"""Conclusion states against snapshots (living-D, task 3).

The facts come from the evidence report (tested in `test_living_facts`); here a stand-in supplies
them, so that a cycle's effect on a group can be scripted without an extraction world. The basis
state is the real one (a retraction notice on a basis work). Rows are resolved by a stand-in too:
the real trace of rows is covered by `test_conclusions_rows`.
"""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.living.facts import ConclusionFacts, GroupFacts
from factory.model.conclusions import BasisRef, Predicate
from factory.model.notices import NoticeKind, NoticeObserved
from factory.model.project import RigorMode
from factory.services import conclusions as service
from factory.services.check import _findings_as
from factory.services.conclusions import conclusion_diff, register_conclusion
from factory.services.context import Project
from factory.services.snapshots import snapshot, snapshot_blob, snapshots
from tests.helpers import SourcesFor
from tests.notice_helpers import NoticeWorld, dependent_world, numbered_records

GROUP = "grp_0123456789ab"
OLD, NEW = "rk_000000000101", "rk_000000000201"
AXIS = "params|count||"


def facts(best: str, *, rows: int = 2, frontier: tuple[str, ...] | None = None) -> ConclusionFacts:
    return ConclusionFacts(
        included=5,
        groups=(
            GroupFacts(
                group_id=GROUP,
                independent_rows=rows,
                frontier={AXIS: frontier or (best,)},
                best=(best,),
                best_reason=None,
            ),
        ),
    )


class Facts:
    """The facts the stand-in reports; a test changes `current` to play a cycle."""

    def __init__(self, current: ConclusionFacts) -> None:
        self.current = current


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Facts:
    script = Facts(facts(OLD))
    monkeypatch.setattr(service, "current_facts", lambda project: script.current)
    monkeypatch.setattr(service, "_resolves", lambda project, ref: True)
    return script


@pytest.fixture
def world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> NoticeWorld:
    return dependent_world(project, agent, human, mock_sources, numbered_records(4))


def register(world: NoticeWorld, human: Actor, *, index: int = 0) -> str:
    return register_conclusion(
        world.project,
        human,
        "The method is best.",
        [BasisRef(kind="work", ref=world.included[index])],
        Predicate(kind="best-in-group", group_id=GROUP, row_key=OLD),
    )


def retract(project: Project, work: str) -> None:
    payload = NoticeObserved(
        notice_id=project.ids.new("ntc"),
        work_id=work,
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
                "notice.observed", payload, project.system_actor(), refs=(payload.notice_id, work)
            )
        ]
    )


def test_conclusion_states_across_cycles(world: NoticeWorld, human: Actor, scripted: Facts) -> None:
    project = world.project
    cid = register(world, human)
    snapshot(project, human, trigger="human")

    # A cycle that adds no row to the group.
    [same] = conclusion_diff(project)
    assert (same.conclusion_id, same.state) == (cid, "unchanged")
    assert same.predicate_before is True and same.predicate_now is True and same.affected == ()

    # A cycle that adds a better row.
    scripted.current = facts(NEW, rows=3, frontier=(OLD, NEW))
    [changed] = conclusion_diff(project)
    assert changed.state == "changed"
    assert (changed.predicate_before, changed.predicate_now) == (True, False)
    assert changed.facts is not None
    [group] = changed.facts.groups
    assert group.best_changed == ((OLD,), (NEW,)) and group.rows_delta == 1

    # A retraction of the basis work.
    retract(project, world.included[0])
    [affected] = conclusion_diff(project)
    assert affected.state == "basis-affected"
    assert affected.affected == (f"work:{world.included[0]}: notice-retracted",)


def test_conclusions_new_since_the_snapshot_and_without_one(
    world: NoticeWorld, human: Actor, scripted: Facts
) -> None:
    first = register(world, human)
    [bare] = conclusion_diff(world.project)  # no snapshot yet
    assert (bare.conclusion_id, bare.state) == (first, "new")
    assert bare.predicate_before is None and bare.predicate_now is True and bare.facts is None
    snapshot(world.project, human, trigger="human")
    second = register(world, human, index=1)
    states = {d.conclusion_id: d.state for d in conclusion_diff(world.project)}
    assert states == {first: "unchanged", second: "new"}


def test_diff_against_named_snapshot(world: NoticeWorld, human: Actor, scripted: Facts) -> None:
    project = world.project
    register(world, human)
    one = snapshot(project, human, trigger="human")
    scripted.current = facts(NEW, rows=3, frontier=(OLD, NEW))
    two = snapshot(project, human, trigger="human")
    [against_last] = conclusion_diff(project)
    [against_first] = conclusion_diff(project, since=one.snapshot_id)
    assert against_last.state == "unchanged"  # the facts already moved before snapshot two
    assert against_first.state == "changed"
    assert snapshots(project)[-1].snapshot_id == two.snapshot_id
    with pytest.raises(FactoryValidationError):
        conclusion_diff(project, since="snp_01JZ9Q3K5M7N8P0R2S4T6V8W1A")


def test_snapshot_blob_holds_conclusion_states(
    world: NoticeWorld, human: Actor, scripted: Facts
) -> None:
    project = world.project
    plain = snapshot(project, human, trigger="human")
    assert snapshot_blob(project, plain.snapshot_id).conclusion_facts is None  # nothing registered
    cid = register(world, human)
    retract(project, world.included[0])
    taken = snapshot(project, human, trigger="human")
    blob = snapshot_blob(project, taken.snapshot_id)
    assert blob.conclusion_facts == facts(OLD)
    assert blob.conclusions is not None
    [state] = blob.conclusions
    assert state.conclusion_id == cid and state.predicate_value is True
    assert state.affected == (f"work:{world.included[0]}: notice-retracted",)
    assert "The method is best." not in project.blobs.get(taken.blob).decode()


def test_findings_by_mode(world: NoticeWorld, human: Actor, scripted: Facts) -> None:
    project = world.project
    cid = register(world, human)
    snapshot(project, human, trigger="human")
    assert not any(f.code.startswith("conclusion-") for f in _findings_as(project, RigorMode.PILOT))
    scripted.current = facts(NEW, rows=3, frontier=(OLD, NEW))
    retract(project, world.included[0])
    for mode, severity in (
        (RigorMode.EXPLORATORY, "warning"),
        (RigorMode.PILOT, "warning"),
        (RigorMode.SYSTEMATIC, "error"),
    ):
        found = {f.code: f for f in _findings_as(project, mode) if f.code.startswith("conclusion-")}
        assert set(found) == {"conclusion-changed", "conclusion-basis-affected"}, mode
        assert found["conclusion-basis-affected"].severity == severity
        assert found["conclusion-changed"].severity == "warning"
        assert found["conclusion-basis-affected"].refs == [cid]
        assert "The method" not in found["conclusion-changed"].message
