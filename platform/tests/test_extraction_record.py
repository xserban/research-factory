"""extract_record: verified rows and claims, corrections by supersession, closing (plan D, task 6).

The pinned conversion is the synthetic LaTeXML fixture: table `t1` has the row `Lorem | 1 | 2`
under the header `Low | High`, and paragraph `s3.p1` reads "Lorem ipsum dolor sit amet."."""

from collections.abc import Callable, Mapping

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.extraction import (
    CLAIM_STATEMENT_MAX,
    VERIFIER_VERSION,
    ClaimInput,
    ClaimType,
    EvidenceType,
    ExtractedRowInput,
    FieldInput,
    Strength,
)
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.model.task import TaskStatus
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.extraction import (
    ClaimRow,
    ExtractBatch,
    ExtractionRow,
    extract_next,
    extract_record,
    live_claims,
    live_rows,
)
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.tasks import TaskSpec, claim_next, complete_task, create_tasks, get_task
from factory.sources.registry import SourceFactory
from tests.test_acceptance_fulltext_screening import _screened_full_text_world
from tests.test_extraction_next import SESSION_A, SESSION_B, _declare, _extractor

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


@pytest.fixture
def world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent, 1.0)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


@pytest.fixture
def task_a(project: Project, ext_a: Actor, world: list[str]) -> ExtractBatch:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    return batch


def _row(value: str = "1", cell: str = "t1.r3.c2", **extra: FieldInput) -> ExtractedRowInput:
    fields = {
        "method_name": FieldInput(value="Lorem", anchor="t1.r3.c1", quote="Lorem"),
        "task": FieldInput(value="classification"),
        "dataset": FieldInput(
            value="Lorem ipsum", anchor="s3.p1", quote="Lorem ipsum dolor sit amet."
        ),
        "metric": FieldInput(value="Low", anchor="t1.r2.c2", quote="Low"),
        "value": FieldInput(value=value, anchor="t1", cell=cell, quote=value),
        **extra,
    }
    return ExtractedRowInput(fields=fields)


def _claim(**over: str) -> ClaimInput:
    values = {
        "statement": "The method is described in the method section.",
        "claim_type": ClaimType.FINDING,
        "evidence_type": EvidenceType.EXPERIMENT,
        "strength": Strength.MODERATE,
        "anchor": "s3.p1",
        "quote": "Lorem ipsum dolor sit amet.",
        **over,
    }
    return ClaimInput.model_validate(values)


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _event(project: Project, ident: str) -> Event:
    (event,) = [e for e in _events(project) if ident in e.refs]
    return event


def _ids(rows: list[ExtractionRow]) -> list[str]:
    return [r.extraction_id for r in rows]


def _work(batch: ExtractBatch) -> str:
    return batch.records[0]["work_id"]


# --- Rows ---


def test_valid_rows_written_invalid_reported(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    res = extract_record(
        project, ext_a, task_a.task_id, [_row(), _row("abc"), _row("2", "t1.r3.c3")]
    )
    assert len(res.rows.written) == 2
    assert [e.index for e in res.rows.rejected] == [1]
    assert res.rows.rejected[0].issues[0].field == "fields.value.value"
    assert sorted(_ids(live_rows(project, PassLabel.A))) == sorted(res.rows.written)
    assert res.completed is False
    # all valid rows were written in one append
    assert len({_event(project, i).ts for i in res.rows.written}) == 1


def test_undeclared_field_rejects_row_only(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    extra = {"hardware": FieldInput(value="GPU")}  # a pack field the schema does not declare
    res = extract_record(project, ext_a, task_a.task_id, [_row(**extra), _row("2", "t1.r3.c3")])
    assert [e.index for e in res.rows.rejected] == [0]
    assert res.rows.rejected[0].issues[0].field == "fields.hardware"
    assert len(res.rows.written) == 1


def test_recorded_row_stores_computed_fields(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    (written,) = extract_record(project, ext_a, task_a.task_id, [_row()]).rows.written
    payload = _event(project, written).payload
    assert payload["verifier"] == VERIFIER_VERSION == 1
    assert payload["fields"]["value"]["canonical"] is not None
    assert payload["fields"]["value"]["copy_marker"] is False
    assert payload["conversion_id"] == task_a.records[0]["conversion_id"]
    assert payload["document_id"] == task_a.records[0]["document_id"]
    assert payload["schema_ref"] == task_a.schema_ref
    assert payload["supersedes"] is None
    (row,) = live_rows(project, PassLabel.A, work_id=_work(task_a))
    assert row.extraction_id == written and row.task_id == task_a.task_id
    assert row.fields["value"].canonical == payload["fields"]["value"]["canonical"]
    assert row.fields["value"].cell == "t1.r3.c2"
    assert row.row_key == payload["row_key"]
    assert live_rows(project, PassLabel.B) == []
    assert live_rows(project, PassLabel.A, work_id="nope") == []


def test_event_carries_provenance(project: Project, ext_a: Actor, task_a: ExtractBatch) -> None:
    res = extract_record(project, ext_a, task_a.task_id, [_row()], [_claim()])
    for ident in [*res.rows.written, *res.claims.written]:
        event = _event(project, ident)
        assert event.actor.model == ext_a.model and event.actor.skill == ext_a.skill
        assert event.input_blob is not None
        blob = project.blobs.get_json(event.input_blob)
        assert isinstance(blob, dict)
        assert blob["task_id"] == task_a.task_id
        assert blob["rows"] == [_row().model_dump(mode="json")]
        assert blob["claims"] == [_claim().model_dump(mode="json")]


# --- Corrections ---


def test_correction_supersedes_and_both_remain(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    (old_id,) = extract_record(project, ext_a, task_a.task_id, [_row()]).rows.written
    res = extract_record(
        project, ext_a, task_a.task_id, [_row("2", "t1.r3.c3")], supersedes={0: old_id}
    )
    (new,) = res.rows.written
    assert _ids(live_rows(project, PassLabel.A)) == [new]
    assert _event(project, old_id) is not None
    assert _event(project, new).payload["supersedes"] == old_id


def test_cannot_supersede_other_pass_or_work_or_dead_row(
    project: Project, ext_a: Actor, ext_b: Actor, task_a: ExtractBatch
) -> None:
    (old_id,) = extract_record(project, ext_a, task_a.task_id, [_row()]).rows.written
    (newer,) = extract_record(
        project, ext_a, task_a.task_id, [_row()], supersedes={0: old_id}
    ).rows.written
    # an already-superseded row and an unknown id
    for target in (old_id, "ext_01JZ9Q3K5M7N8P0R2S4T6V8W1X"):
        res = extract_record(project, ext_a, task_a.task_id, [_row()], supersedes={0: target})
        assert res.rows.written == [] and res.rows.rejected[0].issues[0].field == "supersedes"
    # a row of the same work in pass B
    batch_b = extract_next(project, ext_b, PassLabel.B).batch
    assert batch_b is not None
    while _work(batch_b) != _work(task_a):
        complete_task(project, ext_b, batch_b.task_id)
        batch_b = extract_next(project, ext_b, PassLabel.B).batch
        assert batch_b is not None
    (b_row,) = extract_record(project, ext_b, batch_b.task_id, [_row()]).rows.written
    res = extract_record(project, ext_a, task_a.task_id, [_row()], supersedes={0: b_row})
    assert res.rows.rejected[0].issues[0].field == "supersedes"
    # a row of another work in pass A
    extract_record(project, ext_a, task_a.task_id, [], finish=True)
    other = extract_next(project, ext_a, PassLabel.A).batch
    assert other is not None and _work(other) != _work(task_a)
    res = extract_record(project, ext_a, other.task_id, [_row()], supersedes={0: newer})
    assert res.rows.rejected[0].issues[0].field == "supersedes"
    assert _ids(live_rows(project, PassLabel.A, work_id=_work(task_a))) == [newer]


def test_two_rows_cannot_supersede_one_target(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    (old_id,) = extract_record(project, ext_a, task_a.task_id, [_row()]).rows.written
    res = extract_record(
        project, ext_a, task_a.task_id, [_row(), _row()], supersedes={0: old_id, 1: old_id}
    )
    assert len(res.rows.written) == 1
    assert [e.index for e in res.rows.rejected] == [1]


def test_supersedes_index_out_of_range_refused(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, task_a.task_id, [_row()], supersedes={3: "ext_x"})
    assert e.value.issues[0].field == "supersedes"
    assert len(_events(project)) == before


# --- Closing ---


def test_finish_completes_task_with_results(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    first = extract_record(project, ext_a, task_a.task_id, [_row()]).rows.written
    res = extract_record(
        project, ext_a, task_a.task_id, [_row("2", "t1.r3.c3")], [_claim()], finish=True
    )
    assert res.completed is True
    task = get_task(project, task_a.task_id)
    assert task is not None and task.status is TaskStatus.COMPLETED
    (closed,) = [e for e in _events(project) if e.type == "extraction.closed"]
    assert closed.payload["rows"] == 2 and closed.payload["claims"] == 1
    assert closed.payload["reason"] is None
    (completed,) = [
        e for e in _events(project) if e.type == "task.completed" and task_a.task_id in e.refs
    ]
    expected = sorted([*first, *res.rows.written]) + res.claims.written
    assert list(completed.payload["result_refs"]) == expected
    with pytest.raises(FactoryValidationError):  # the task is no longer held
        extract_record(project, ext_a, task_a.task_id, [_row()])


def test_finish_refused_while_items_rejected(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    res = extract_record(project, ext_a, task_a.task_id, [_row(), _row("abc")], finish=True)
    assert res.completed is False and len(res.rows.written) == 1
    task = get_task(project, task_a.task_id)
    assert task is not None and task.status is TaskStatus.CLAIMED
    assert not [e for e in _events(project) if e.type == "extraction.closed"]


def test_zero_result_paper_closes_only_with_reason(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    before = len(_events(project))
    for reason in (None, "  "):
        with pytest.raises(FactoryValidationError) as e:
            extract_record(project, ext_a, task_a.task_id, [], finish=True, reason=reason)
        assert e.value.issues[0].field == "reason"
    assert len(_events(project)) == before
    res = extract_record(
        project, ext_a, task_a.task_id, [], finish=True, reason="theory paper; no benchmark results"
    )
    assert res.completed
    (closed,) = [e for e in _events(project) if e.type == "extraction.closed"]
    assert closed.payload["rows"] == 0 and closed.payload["claims"] == 0
    assert closed.payload["reason"] == "theory paper; no benchmark results"


# --- Claims ---


def test_claims_pass_a_only_and_quote_verified(
    project: Project, ext_a: Actor, ext_b: Actor, task_a: ExtractBatch
) -> None:
    res = extract_record(
        project,
        ext_a,
        task_a.task_id,
        [],
        [_claim(), _claim(quote="not in the paragraph"), _claim(anchor="s9.p9")],
    )
    assert len(res.claims.written) == 1
    assert [(e.index, e.issues[0].field) for e in res.claims.rejected] == [
        (1, "quote"),
        (2, "anchor"),
    ]
    assert res.claims.written[0].startswith("clm_")
    batch_b = extract_next(project, ext_b, PassLabel.B).batch
    assert batch_b is not None
    before = len(_events(project))
    res_b = extract_record(project, ext_b, batch_b.task_id, [], [_claim()])
    assert res_b.claims.written == []
    assert res_b.claims.rejected[0].issues[0].field == "claims"
    assert "pass A only" in res_b.claims.rejected[0].issues[0].reason
    assert len(_events(project)) == before


def test_claim_statement_is_bounded(project: Project, ext_a: Actor, task_a: ExtractBatch) -> None:
    long = "x" * (CLAIM_STATEMENT_MAX + 1)
    with pytest.raises(ValidationError):
        _claim(statement=long)
    unchecked = ClaimInput.model_construct(**{**_claim().model_dump(), "statement": long})
    res = extract_record(project, ext_a, task_a.task_id, [], [unchecked])
    assert res.claims.rejected[0].issues[0].field == "statement"


def test_claims_refused_when_schema_disables_them(
    project: Project, agent: Actor, ext_a: Actor, world: list[str]
) -> None:
    current = current_protocol(project)
    assert current is not None and current.spec.extraction_schema is not None
    schema = current.spec.extraction_schema.model_copy(update={"claims": False})
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"extraction_schema": schema}),
        reason="no claims",
        semantic=True,
        effects={},
    )
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None and batch.claims is False
    res = extract_record(project, ext_a, batch.task_id, [_row()], [_claim()])
    assert res.claims.rejected[0].issues[0].field == "claims"
    assert len(res.rows.written) == 1


def test_live_claims_returns_claim_rows(
    project: Project, ext_a: Actor, task_a: ExtractBatch
) -> None:
    w = _work(task_a)
    cnv = task_a.records[0]["conversion_id"]
    (first,) = extract_record(project, ext_a, task_a.task_id, [], [_claim()]).claims.written
    c = live_claims(project, PassLabel.A, work_id=w)[0]
    assert isinstance(c, ClaimRow) and c.claim_type == "finding" and c.conversion_id == cnv
    assert c.claim_id.startswith("clm_") and c.claim_id == first
    assert set(ClaimRow.model_fields) == {
        "claim_id",
        "work_id",
        "pass_label",
        "claim_type",
        "evidence_type",
        "strength",
        "statement",
        "anchor",
        "quote",
        "conversion_id",
        "event_id",
    }
    # a superseded claim is absent from live_claims
    (second,) = extract_record(
        project,
        ext_a,
        task_a.task_id,
        [],
        [_claim(claim_type=ClaimType.LIMITATION)],
        claim_supersedes={0: first},
    ).claims.written
    assert [c.claim_id for c in live_claims(project)] == [second]
    assert _event(project, second).payload["supersedes"] == first
    assert live_claims(project, PassLabel.B) == []


# --- Refusals ---


def test_pass_b_session_cannot_record_on_pass_a_task(
    project: Project, ext_a: Actor, ext_b: Actor, task_a: ExtractBatch
) -> None:
    extract_next(project, ext_b, PassLabel.B)  # joins pass B
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:  # not held by this session
        extract_record(project, ext_b, task_a.task_id, [_row()])
    assert e.value.issues[0].field == "task_id"
    other_a = claim_next(project, ext_b, "extract_a")  # held, but of the other pass
    assert other_a is not None
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_b, other_a.task_id, [_row()])
    assert e.value.issues[0].field == "pass"
    assert len(_events(project)) == before + 1  # only the claim


def test_nothing_written_on_refusal(
    project: Project, agent: Actor, human: Actor, ext_a: Actor, task_a: ExtractBatch
) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, human, task_a.task_id, [_row()])
    assert e.value.issues[0].field == "actor"
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, "tsk_01JZ9Q3K5M7N8P0R2S4T6V8W1X", [_row()])
    assert e.value.issues[0].field == "task_id"
    # a task of another kind
    (other,) = create_tasks(project, agent, [TaskSpec(kind="misc", content={"x": 1})]).written
    held = claim_next(project, ext_a, "misc")
    assert held is not None and held.task_id == other
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, other, [_row()])
    assert e.value.issues[0].field == "task_id"
    after_setup = len(_events(project))
    # a stale task: the protocol changed after the task was served
    _declare(project, agent, 0.5)
    amended = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ext_a, task_a.task_id, [_row()], finish=True)
    assert e.value.issues[0].field == "task_id"
    assert len(_events(project)) == amended
    assert after_setup - before == 2  # the misc task and its claim
