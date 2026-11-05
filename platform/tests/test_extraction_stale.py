"""Extraction staleness and re-queue (plan D, task 7; R-15, ruling 12, decision 50).

A row is stale when an amendment recorded after it stales it (all rows, or rows carrying a removed
field), or when the work's document is no longer the current one. A unit (work, pass) is current
when its latest task completed after every amendment that touches it and pins the current
document; stale units are served again under the current schema and pin, and nothing is edited."""

from collections.abc import Callable, Mapping

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import FieldInput
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractBatch,
    UnitState,
    abandoned_task_ids,
    extract_next,
    extract_record,
    in_dual_sample,
    live_rows,
    pass_config,
    stale_claims,
    stale_documents,
    stale_extractions,
    unit_pin,
    unit_states,
)
from factory.services.project import project_status
from factory.services.tasks import complete_task, get_task, release_task
from factory.sources.registry import SourceFactory
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.extraction_helpers import (
    LATENCY_FIELDS,
    SESSION_A,
    SESSION_B,
    _amend_schema,
    _claim,
    _declare_latency,
    _events,
    _extractor,
    _new_document_version,
    _row,
)
from tests.helpers import _setup
from tests.test_acceptance_fulltext_screening import _screened_full_text_world

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
LATENCY = FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1")


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


@pytest.fixture
def screened(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


@pytest.fixture
def world(project: Project, agent: Actor, screened: list[str]) -> list[str]:
    _declare_latency(project, agent, 1.0)
    return screened


@pytest.fixture
def task_a(project: Project, ext_a: Actor, world: list[str]) -> ExtractBatch:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    return batch


def _work(batch: ExtractBatch) -> str:
    return batch.records[0]["work_id"]


def _pin(batch: ExtractBatch) -> tuple[str, str]:
    record = batch.records[0]
    return record["document_id"], record["conversion_id"]


def _closed_unit(project: Project, actor: Actor, batch: ExtractBatch) -> tuple[str, str]:
    """Record a plain row and a row carrying latency, and close the unit; (plain, latency)."""
    res = extract_record(
        project,
        actor,
        batch.task_id,
        [_row(), _row("2", "t1.r3.c3", latency=LATENCY)],
        finish=True,
    )
    assert res.completed and not res.rows.rejected, res.rows.rejected
    plain, with_latency = res.rows.written
    return plain, with_latency


def _state(project: Project, work: str, label: PassLabel = PassLabel.A) -> UnitState:
    (state,) = [s for s in unit_states(project) if s.work_id == work and s.pass_label is label]
    return state


def _serve_work(project: Project, actor: Actor, label: PassLabel, work: str) -> ExtractBatch:
    """Serve tasks of the pass until the one of `work`; release every other task served."""
    for _ in range(50):
        batch = extract_next(project, actor, label).batch
        assert batch is not None, f"no task of {work} was served"
        if _work(batch) == work:
            return batch
        complete_task(project, actor, batch.task_id)
    raise AssertionError("too many tasks")


# --- Rows made stale by an amendment ---


def test_removed_field_stales_only_rows_carrying_it(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    _, with_latency = _closed_unit(project, ext_a, task_a)
    assert stale_extractions(project) == set()
    _amend_schema(project, agent, fields=tuple(f for f in LATENCY_FIELDS if f != "latency"))
    assert stale_extractions(project) == {with_latency}
    state = _state(project, _work(task_a))
    assert (state.state, state.reason) == ("stale", "schema")


def test_added_field_stales_all_rows(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    rows = set(_closed_unit(project, ext_a, task_a))
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))
    assert stale_extractions(project) == rows
    assert _state(project, _work(task_a)).state == "stale"


def test_comparability_key_and_sample_change_stale_nothing(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    _closed_unit(project, ext_a, task_a)
    _amend_schema(project, agent, comparability_keys=("task", "dataset"))
    _amend_schema(project, agent, dual_extract_sample=0.5)
    assert stale_extractions(project) == set()
    assert _state(project, _work(task_a)).state == "current"


def test_row_recorded_after_amendment_is_not_stale(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    first = extract_record(project, ext_a, task_a.task_id, [_row()], finish=True).rows.written
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))
    fresh = _serve_work(project, ext_a, PassLabel.A, _work(task_a))
    later = extract_record(project, ext_a, fresh.task_id, [_row()], finish=True).rows.written
    assert stale_extractions(project) == set(first)
    assert not set(later) & stale_extractions(project)
    assert _state(project, _work(task_a)).state == "current"


def test_reverted_amendment_keeps_order_semantics(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    plain, before = _closed_unit(project, ext_a, task_a)  # under S1; `before` carries latency
    original = task_a.protocol_id
    _amend_schema(
        project, agent, fields=tuple(f for f in LATENCY_FIELDS if f != "latency")
    )  # S1 -> S2
    middle_task = _serve_work(project, ext_a, PassLabel.A, work)
    # `plain` is still valid, so its location is taken; the stale row's location is free again.
    assert extract_record(project, ext_a, middle_task.task_id, [_row()]).rows.rejected
    (middle,) = extract_record(
        project, ext_a, middle_task.task_id, [_row("2", "t1.r3.c3")], finish=True
    ).rows.written
    assert stale_extractions(project) == {before}
    reverted = _amend_schema(project, agent, fields=LATENCY_FIELDS)  # S2 -> S1: latency added back
    assert reverted == original
    # Every row was recorded before S2 -> S1, which adds a field; `before` also stays stale by
    # S1 -> S2 although it was recorded under the version now current again.
    assert stale_extractions(project) == {plain, before, middle}
    last_task = _serve_work(project, ext_a, PassLabel.A, work)
    (after,) = extract_record(project, ext_a, last_task.task_id, [_row()], finish=True).rows.written
    assert after not in stale_extractions(project)
    assert _state(project, work).state == "current"


# --- Re-queue ---


def test_stale_unit_is_served_again_and_old_rows_stay_readable(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    old = set(_closed_unit(project, ext_a, task_a))
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    assert fresh.task_id != task_a.task_id
    assert "hardware" in [f["name"] for f in fresh.fields]
    assert _pin(fresh) == _pin(task_a)
    assert _state(project, work).state == "open"
    # The old rows are still live and readable; recording the same location again is no duplicate.
    assert old <= {r.extraction_id for r in live_rows(project, PassLabel.A, work_id=work)}
    res = extract_record(project, ext_a, fresh.task_id, [_row()], finish=True)
    assert res.completed and not res.rows.rejected
    assert _state(project, work).state == "current"
    assert stale_extractions(project) == old


def test_released_stale_task_is_replaced_by_a_fresh_one(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    _amend_schema(project, agent, fields=tuple(f for f in LATENCY_FIELDS if f != "latency"))
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, task_a.task_id, [_row()], finish=True)
    assert e.value.issues[0].field == "task_id"
    release_task(project, ext_a, task_a.task_id, "schema changed")
    fresh = extract_next(project, ext_a, PassLabel.A).batch
    assert fresh is not None and fresh.task_id != task_a.task_id
    assert "latency" not in [f["name"] for f in fresh.fields]
    served = {_work(fresh)}
    res = extract_record(project, ext_a, fresh.task_id, [_row()], finish=True)
    assert res.completed
    # The stale task is never served again, nor is any work served twice.
    while (batch := extract_next(project, ext_a, PassLabel.A).batch) is not None:
        assert batch.task_id != task_a.task_id and _work(batch) not in served
        served.add(_work(batch))
        complete_task(project, ext_a, batch.task_id)
    old = get_task(project, task_a.task_id)
    assert old is not None and old.status.value == "open"


def test_held_stale_task_is_not_served_again(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))
    again = extract_next(project, ext_a, PassLabel.A).batch
    assert again is not None and again.task_id != task_a.task_id
    assert "hardware" in [f["name"] for f in again.fields]


def test_stale_rows_excluded_from_final_rows(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    old = set(_closed_unit(project, ext_a, task_a))
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    res = extract_record(project, ext_a, fresh.task_id, [_row()], finish=True)
    done = get_task(project, fresh.task_id)
    assert done is not None
    # The closing counts and results hold only the rows of the current schema.
    (closed,) = [
        e
        for e in _events(project)
        if e.type == "extraction.closed" and e.payload["task_id"] == fresh.task_id
    ]
    assert closed.payload["rows"] == 1
    current = {r.extraction_id for r in live_rows(project, PassLabel.A)} - stale_extractions(
        project
    )
    assert current == set(res.rows.written) and not current & old


def test_unit_completed_without_a_closing_uses_its_completion_position(
    project: Project, agent: Actor, ext_a: Actor, world: list[str]
) -> None:
    work = world[0]
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))  # before the task
    first = _serve_work(project, ext_a, PassLabel.A, work)
    complete_task(project, ext_a, first.task_id)
    assert _state(project, work).state == "current"
    # Serving again creates no new task for the work: the unit stays current.
    while (batch := extract_next(project, ext_a, PassLabel.A).batch) is not None:
        assert _work(batch) != work
        complete_task(project, ext_a, batch.task_id)
    assert _state(project, work).state == "current"
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware", "memory"))  # after it
    state = _state(project, work)
    assert (state.state, state.reason) == ("stale", "schema")
    again = _serve_work(project, ext_a, PassLabel.A, work)
    complete_task(project, ext_a, again.task_id)
    assert _state(project, work).state == "current"


def test_rows_already_stale_do_not_stale_the_unit(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    _closed_unit(project, ext_a, task_a)  # on the first document; one row carries latency
    _new_document_version(project, work)
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    extract_record(project, ext_a, fresh.task_id, [], finish=True, reason="nothing reported")
    assert _state(project, work).state == "current"
    # Only the old, document-stale row carries latency: removing it stales nothing current.
    _amend_schema(project, agent, fields=tuple(f for f in LATENCY_FIELDS if f != "latency"))
    assert _state(project, work).state == "current"


def test_schema_amendments_never_stale_claims(
    project: Project, agent: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    extract_record(project, ext_a, task_a.task_id, [_row()], [_claim()], finish=True)
    _amend_schema(project, agent, fields=(*LATENCY_FIELDS, "hardware"))
    assert stale_claims(project) == set()


# --- Document versions ---


def test_claims_of_a_replaced_document_are_stale_and_not_counted(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    res = extract_record(project, ext_a, task_a.task_id, [], [_claim()], finish=True)
    assert res.completed
    (old_claim,) = res.claims.written
    assert stale_claims(project) == set()
    _new_document_version(project, work)
    assert stale_claims(project) == {old_claim}
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, fresh.task_id, [], finish=True)
    assert e.value.issues[0].field == "reason"
    done = extract_record(project, ext_a, fresh.task_id, [_row()], finish=True)
    assert done.completed
    (closed,) = [
        ev
        for ev in _events(project)
        if ev.type == "extraction.closed" and ev.payload["task_id"] == fresh.task_id
    ]
    assert (closed.payload["rows"], closed.payload["claims"]) == (1, 0)


def test_new_document_version_requeues_work_and_marks_rows_stale(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    rows = set(_closed_unit(project, ext_a, task_a))
    assert _state(project, work).state == "current"
    document = _new_document_version(project, work)
    assert document != task_a.records[0]["document_id"]
    assert stale_extractions(project) == rows
    state = _state(project, work)
    assert (state.state, state.reason) == ("stale", "document-version")
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    assert fresh.records[0]["document_id"] == document
    assert unit_pin(project, work) == _pin(fresh)


def test_held_task_of_a_replaced_document_is_refused(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    _new_document_version(project, _work(task_a))
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, task_a.task_id, [_row()], finish=True)
    assert e.value.issues[0].field == "task_id"
    assert "extract_next" in e.value.issues[0].reason
    assert stale_extractions(project) == set()


def test_new_conversion_of_same_document_only_warns(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    _closed_unit(project, ext_a, task_a)
    run_convert(project, make_registry(StubConverter(version="9.9+later")))
    current = default_conversion(project, work)
    assert current is not None and current.conversion_id != task_a.records[0]["conversion_id"]
    assert stale_documents(project) == [work]
    assert stale_extractions(project) == set()
    assert _state(project, work).state == "current"
    assert unit_pin(project, work) == _pin(task_a)


def test_pin_follows_new_document_for_both_passes(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    work = world[0]
    a = _serve_work(project, ext_a, PassLabel.A, work)
    complete_task(project, ext_a, a.task_id)
    b = _serve_work(project, ext_b, PassLabel.B, work)
    complete_task(project, ext_b, b.task_id)
    assert _pin(a) == _pin(b)
    document = _new_document_version(project, work)
    assert _state(project, work, PassLabel.B).reason == "document-version"
    b2 = _serve_work(project, ext_b, PassLabel.B, work)
    a2 = _serve_work(project, ext_a, PassLabel.A, work)
    assert _pin(a2) == _pin(b2) == unit_pin(project, work)
    assert _pin(a2)[0] == document


# --- Unit states ---


def test_unit_states_lists_every_included_work(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    excluded = {
        w for w, o in final_outcomes(project, stage=FT).items() if o is not Outcome.INCLUDED
    }
    assert excluded
    done = extract_next(project, ext_a, PassLabel.A).batch
    assert done is not None
    complete_task(project, ext_a, done.task_id)
    held = extract_next(project, ext_a, PassLabel.A).batch
    assert held is not None
    states = unit_states(project)
    # One unit per included work and pass: the declared sample (1.0) puts every work in pass B.
    assert {(s.work_id, s.pass_label) for s in states} == {
        (w, label) for w in world for label in PassLabel
    }
    assert len(states) == 2 * len(world)
    assert not excluded & {s.work_id for s in states}
    assert _state(project, _work(done)).state == "current"
    assert _state(project, _work(held)).state == "open"
    unserved = [
        s
        for s in states
        if s.pass_label is PassLabel.B or s.work_id not in {_work(done), _work(held)}
    ]
    assert {(s.state, s.reason) for s in unserved} == {("queued", None)}


def test_pass_b_units_follow_the_recorded_sample(
    project: Project, agent: Actor, ext_b: Actor, screened: list[str]
) -> None:
    _declare_latency(project, agent, 0.5)
    assert {s.pass_label for s in unit_states(project)} == {PassLabel.A}  # sample not drawn yet
    extract_next(project, ext_b, PassLabel.B)
    config = pass_config(project, PassLabel.B)
    assert config is not None
    sampled = {w for w in screened if in_dual_sample(config.seed, w, 0.5)}
    assert {s.work_id for s in unit_states(project) if s.pass_label is PassLabel.B} == sampled


def test_unserved_population_is_queued_before_any_task(project: Project, world: list[str]) -> None:
    states = unit_states(project)
    assert {s.work_id for s in states} == set(world)
    assert {(s.state, s.reason) for s in states} == {("queued", None)}


def test_unit_states_empty_without_schema_or_plan(project: Project, screened: list[str]) -> None:
    assert unit_states(project) == []


def test_unit_states_empty_without_full_text_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_latency(project, agent, 1.0)
    assert unit_states(project) == []


# --- Abandoned tasks in project status ---


def test_replaced_task_is_abandoned_not_open(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    assert project_status(project).tasks.abandoned == 0
    assert abandoned_task_ids(project) == set()
    _new_document_version(project, work)
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    assert fresh.task_id != task_a.task_id
    assert abandoned_task_ids(project) == {task_a.task_id}
    tasks = project_status(project).tasks
    assert tasks.abandoned == 1
    old = get_task(project, task_a.task_id)
    assert old is not None and old.status.value == "claimed"
    assert tasks.claimed == 1 and tasks.expired == 0


def test_completing_the_new_task_keeps_abandoned_at_one(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    work = _work(task_a)
    _new_document_version(project, work)
    fresh = _serve_work(project, ext_a, PassLabel.A, work)
    res = extract_record(project, ext_a, fresh.task_id, [_row()], finish=True)
    assert res.completed
    assert project_status(project).tasks.abandoned == 1
    assert abandoned_task_ids(project) == {task_a.task_id}
