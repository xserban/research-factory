"""Contribution item checks and the closure rule (plan G2-B, task 2).

Work 0 of the world has a document with a bibliography (entries 1-6; markers [5] at s1.p1 and
[3] at s1.p2) and a current G1 extraction; work 1 has the plain fixture document and none.
"""

# ruff: noqa: F401, F811

from collections.abc import Sequence

import pytest

from factory.errors import ValidationIssue
from factory.events.envelope import Actor
from factory.model.extraction import (
    CitedEntry,
    ExtractedRowInput,
    ExtractionRecorded,
    FieldInput,
    StoredField,
    UnitReferences,
)
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contributions import (
    contribution_check,
    contribution_close_check,
)
from factory.services.extraction import (
    ContributionBatch,
    ContributionBatchContent,
    ExtractBatchContent,
    ExtractionRow,
    ExtractResult,
    UnitPin,
    extract_next,
    extract_record,
    live_rows,
    next_unit,
    record_unit,
    unit_pin,
)
from tests.contribution_helpers import (
    P1,
    P2,
    P3,
    P4,
    P5,
    C,
    ctr_a,
    ext_a,
    field,
    item,
    not_stated,
    screened,
    with_references,
    world,
)
from tests.extraction_helpers import _row


def _hook(project: Project, base: ExtractBatchContent) -> ExtractBatchContent:
    refs = UnitReferences(status="none", extraction_id=None, entries=[])
    return ContributionBatchContent(**base.model_dump(), references=refs, item_rules=[])


def _serve(project: Project, actor: Actor, work: str) -> ContributionBatch:
    """Serve pass A units in order, closing the others with a reason, until `work`'s."""
    for _ in range(50):
        batch = next_unit(project, actor, PassLabel.A, scope=C, content=_hook).batch
        assert isinstance(batch, ContributionBatch)
        if batch.records[0]["work_id"] == work:
            return batch
        record_unit(project, actor, batch.task_id, [], finish=True, reason="not under test")
    raise AssertionError("work not served")


@pytest.fixture
def unit(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> tuple[ContributionBatch, str]:
    rex = with_references(project, agent, world[0])
    return _serve(project, ctr_a, world[0]), rex


def _reasons(result: ExtractResult) -> dict[int, dict[str, str]]:
    return {e.index: {i.field: i.reason for i in e.issues} for e in result.rows.rejected}


def _base(**extra: FieldInput) -> ExtractedRowInput:
    return item("base-idea", P1, name="linear attention", **extra)


# --- cited_entry ---


def test_cited_entry_unknown_rejected(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:  # acceptance 5
    batch, _ = unit
    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [_base(cited_entry=field(9))],
        extra_check=contribution_check,
    )
    assert res.rows.written == []
    assert _reasons(res) == {0: {"fields.cited_entry.value": "entry-unknown"}}


def test_cited_entry_without_references_rejected_others_written(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:  # Review Focus 3
    batch = _serve(project, ctr_a, world[1])
    quote = "Lorem ipsum dolor sit amet."
    items = [
        item("base-idea", ("s3.p1", quote), name="Lorem", cited_entry=field(1)),
        item("addition", ("s3.p1", quote), name="ipsum"),
    ]
    res = record_unit(project, ctr_a, batch.task_id, items, extra_check=contribution_check)
    assert len(res.rows.written) == 1
    assert _reasons(res) == {0: {"fields.cited_entry.value": "no-reference-extraction"}}


def test_cited_entry_other_conversion_rejected(
    project: Project, agent: Actor, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:
    batch, _ = unit
    work = batch.records[0]["work_id"]
    document, _conversion = unit_pin(project, work, scope=C) or ("", "")
    other = UnitPin(
        task_id=batch.task_id,
        work_id=work,
        pass_label=PassLabel.A,
        scope=C,
        document_id=document,
        conversion_id="cnv_01JZ9Q3K5M7N8P0R2S4T6V8W0X",
    )
    verdict = contribution_check(project, other, _stored(_base(cited_entry=field(5))), [])
    assert verdict.cited is None
    assert [(i.field, i.reason) for i in verdict.issues] == [
        ("fields.cited_entry.value", "reference-extraction-other-conversion")
    ]


def _stored(row: ExtractedRowInput) -> dict[str, StoredField]:
    return {
        name: StoredField(**f.model_dump(), copy_marker=False) for name, f in row.fields.items()
    }


def _pin(project: Project, batch: ContributionBatch) -> UnitPin:
    work = batch.records[0]["work_id"]
    pin = unit_pin(project, work, scope=C)
    assert pin is not None
    return UnitPin(batch.task_id, work, PassLabel.A, C, pin[0], pin[1])


def test_cited_stored_with_extraction_and_marker(
    project: Project, unit: tuple[ContributionBatch, str]
) -> None:
    batch, rex = unit
    verdict = contribution_check(
        project, _pin(project, batch), _stored(_base(cited_entry=field(5))), []
    )
    assert verdict.issues == []
    assert verdict.cited == CitedEntry(reference_extraction_id=rex, ordinal=5, marker="matched")


def test_mismatch_is_flagged_not_rejected(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:  # Review Focus 1
    batch, rex = unit
    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [_base(cited_entry=field(4))],
        extra_check=contribution_check,
    )
    assert res.rows.rejected == [] and len(res.rows.written) == 1
    (row,) = live_rows(project, scope=C)
    assert row.cited == CitedEntry(reference_extraction_id=rex, ordinal=4, marker="mismatch")
    (event,) = [e for e in _recorded(project) if e.extraction_id == row.extraction_id]
    assert event.cited is not None and event.cited.marker == "mismatch"


def _recorded(project: Project) -> list[ExtractionRecorded]:
    from factory.events.reader import read_all

    return [
        ExtractionRecorded.model_validate(e.payload)
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "extraction.recorded"
    ]


def test_absent_marker_is_stored_and_flagged(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:
    batch, rex = unit
    plain = item("base-idea", P5, name="no marker", cited_entry=field(2))
    res = record_unit(project, ctr_a, batch.task_id, [plain], extra_check=contribution_check)
    assert len(res.rows.written) == 1
    (row,) = live_rows(project, scope=C)
    assert row.cited == CitedEntry(reference_extraction_id=rex, ordinal=2, marker="absent")


def test_item_without_cited_entry_has_no_cited(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:
    batch, _ = unit
    res = record_unit(project, ctr_a, batch.task_id, [_base()], extra_check=contribution_check)
    assert len(res.rows.written) == 1
    assert live_rows(project, scope=C)[0].cited is None


# --- result_row ---


def test_result_row_must_exist_for_work(
    project: Project, agent: Actor, ctr_a: Actor, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    while batch.records[0]["work_id"] != world[1]:
        extract_record(project, ext_a, batch.task_id, [], finish=True, reason="skip")
        batch = extract_next(project, ext_a, PassLabel.A).batch
        assert batch is not None
    extract_record(project, ext_a, batch.task_id, [_row()], finish=True)
    (evidence,) = live_rows(project, work_id=world[1])
    served = _serve(project, ctr_a, world[1])
    quote = "Lorem ipsum dolor sit amet."
    cell = FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1")
    metric = FieldInput(value="Low", anchor="t1.r2.c2", quote="Low")
    good = ExtractedRowInput(
        fields={
            "item_kind": FieldInput(value="result"),
            "statement": FieldInput(value="Lorem", anchor="s3.p1", quote=quote),
            "metric": metric,
            "value": cell,
            "result_row": FieldInput(value=evidence.row_key),
        }
    )
    other_work = good.model_copy(
        update={
            "fields": {
                **good.fields,
                "result_row": FieldInput(value="rk_000000000000"),
            }
        }
    )
    res = record_unit(
        project, ctr_a, served.task_id, [good, other_work], extra_check=contribution_check
    )
    assert len(res.rows.written) == 1
    assert _reasons(res) == {1: {"fields.result_row.value": "result-row-unknown"}}
    # Another work's row key is unknown for this work.
    assert evidence.work_id == world[1]


# --- not-stated ---


def test_not_stated_has_no_quote(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:  # acceptance 4
    batch, _ = unit
    quoted = ExtractedRowInput(
        fields={
            "item_kind": FieldInput(value="not-stated", anchor=P1[0], quote=P1[1]),
            "absent_kind": FieldInput(value="base-idea"),
        }
    )
    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [quoted, not_stated("limitation")],
        extra_check=contribution_check,
    )
    assert len(res.rows.written) == 1
    assert _reasons(res) == {0: {"fields.item_kind.quote": "not-stated-has-no-quote"}}


def test_not_stated_contradiction_across_calls(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:  # Review Focus 5, both orders
    batch, _ = unit
    check = {"extra_check": contribution_check}
    assert record_unit(project, ctr_a, batch.task_id, [_base()], **check).rows.written
    res = record_unit(project, ctr_a, batch.task_id, [not_stated("base-idea")], **check)
    assert res.rows.written == []
    assert _reasons(res) == {0: {"fields.item_kind.value": "contradicts-recorded-item"}}
    assert record_unit(
        project, ctr_a, batch.task_id, [not_stated("limitation")], **check
    ).rows.written
    limitation = item(
        "limitation", P4, name="long sequences", statement="very long sequences degrade"
    )
    res = record_unit(project, ctr_a, batch.task_id, [limitation], **check)
    assert _reasons(res) == {0: {"fields.item_kind.value": "contradicts-recorded-item"}}


def test_not_stated_contradiction_within_one_call(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:
    batch, _ = unit
    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [not_stated("base-idea"), _base()],
        extra_check=contribution_check,
    )
    assert len(res.rows.written) == 1
    assert _reasons(res) == {1: {"fields.item_kind.value": "contradicts-recorded-item"}}


# --- closing ---


def _stub(kind: str, absent: str | None = None) -> ExtractionRow:
    fields = {"item_kind": StoredField(value=kind, copy_marker=False)}
    if absent is not None:
        fields["absent_kind"] = StoredField(value=absent, copy_marker=False)
    return ExtractionRow(
        extraction_id="ext_01JZ9Q3K5M7N8P0R2S4T6V8W0X",
        work_id="w",
        pass_label=PassLabel.A,
        task_id="tsk_x",
        protocol_id="P@x",
        conversion_id="cnv_x",
        document_id="doc_x",
        row_key="rk_000000000000",
        fields=fields,
        event_id="",
    )


def _close(
    project: Project, rows: Sequence[ExtractionRow], reason: str | None = None
) -> list[ValidationIssue]:
    pin = UnitPin("tsk_x", "w", PassLabel.A, C, "doc_x", "cnv_x")
    return contribution_close_check(project, pin, rows, reason)


def _codes(issues: list[ValidationIssue]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in issues]


def test_close_requires_base_limitation_and_addition(project: Project) -> None:
    addition, base = _stub("addition"), _stub("base-idea")
    limitation, result = _stub("limitation"), _stub("result")
    assert _codes(_close(project, [addition, _stub("not-stated", "base-idea")])) == [
        ("finish", "limitation-not-covered"),
        ("reason", "no-result-needs-reason"),
    ]
    assert _codes(_close(project, [base, addition, limitation])) == [
        ("reason", "no-result-needs-reason")
    ]
    assert _close(project, [base, addition, limitation], "paper reports no results") == []
    assert _close(project, [base, addition, limitation, result]) == []
    assert (
        _close(
            project,
            [_stub("not-stated", "base-idea"), _stub("not-stated", "limitation"), addition, result],
        )
        == []
    )
    assert _codes(_close(project, [base, limitation, result])) == [("finish", "no-addition")]
    assert _codes(_close(project, [addition, limitation, result])) == [
        ("finish", "base-idea-not-covered")
    ]


def test_close_refuses_a_contradiction(project: Project) -> None:
    rows = [
        _stub("base-idea"),
        _stub("not-stated", "base-idea"),
        _stub("addition"),
        _stub("limitation"),
        _stub("result"),
    ]
    assert _codes(_close(project, rows)) == [("finish", "contradicts-recorded-item")]


def test_unit_with_no_items_closes_only_with_a_reason(project: Project) -> None:
    assert _close(project, [], "no contribution is stated in the text") == []


def test_close_through_record_unit(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:  # acceptance 4
    from factory.errors import FactoryValidationError

    batch, _ = unit
    kwargs = {"extra_check": contribution_check, "close_check": contribution_close_check}
    items = [
        _base(),
        item("addition", P2, name="softmax attention"),
        item("limitation", P4, name="long sequences", statement="very long sequences degrade"),
    ]
    with pytest.raises(FactoryValidationError) as e:
        record_unit(project, ctr_a, batch.task_id, items, finish=True, **kwargs)
    assert [(i.field, i.reason) for i in e.value.issues] == [("reason", "no-result-needs-reason")]
    assert live_rows(project, scope=C) == []  # nothing written
    result = item(
        "result",
        P3,
        statement="82.4% top-1",
        metric=field("top-1", *P3),
        value=field("82.4", *P3, unit="%"),
    )
    done = record_unit(project, ctr_a, batch.task_id, [*items, result], finish=True, **kwargs)
    assert done.completed


def test_messages_carry_no_document_text(
    project: Project, ctr_a: Actor, unit: tuple[ContributionBatch, str]
) -> None:
    batch, _ = unit
    bad = [_base(cited_entry=field(9)), not_stated("base-idea"), _base(cited_entry=field(9))]
    res = record_unit(project, ctr_a, batch.task_id, bad, extra_check=contribution_check)
    reasons = [i.reason for e in res.rows.rejected for i in e.issues]
    assert reasons and all(r in VOCABULARY for r in reasons)
    for text in (P1[1], "linear attention"):
        assert all(text not in r for r in reasons)


VOCABULARY = {
    "no-reference-extraction",
    "reference-extraction-other-conversion",
    "entry-unknown",
    "result-row-unknown",
    "not-stated-has-no-quote",
    "contradicts-recorded-item",
}
