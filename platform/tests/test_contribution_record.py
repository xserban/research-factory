# ruff: noqa: F401, F811
"""contribution_next, contribution_record, item reads and status (plan G2-B, task 3)."""

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contributions import (
    CONTRIBUTION_INSTRUCTIONS,
    DUPLICATE_ITEM,
    contribution_item,
    contribution_next,
    contribution_record,
    contribution_status,
    final_items,
    live_items,
)
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ContributionBatch,
    ExtractResult,
    recorded_row,
    stale_extractions,
    unit_states,
)
from factory.services.references import extract_references
from tests.contribution_helpers import (
    P1,
    P2,
    P3,
    P4,
    P5,
    C,
    ctr_a,
    ctr_b,
    field,
    item,
    not_stated,
    screened,
    with_references,
    world,
)
from tests.document_helpers import StubConverter, make_registry, run_convert

A, B = PassLabel.A, PassLabel.B


def _next(project: Project, actor: Actor, label: PassLabel = A) -> ContributionBatch:
    batch = contribution_next(project, actor, label).batch
    assert isinstance(batch, ContributionBatch)
    return batch


def _reasons(result: ExtractResult) -> dict[int, dict[str, str]]:
    return {e.index: {i.field: i.reason for i in e.issues} for e in result.rows.rejected}


def _addition() -> ExtractedRowInput:
    return item("addition", P2, name="softmax attention")


def _limitation() -> ExtractedRowInput:
    return item("limitation", P4, name="long sequences", statement="very long sequences degrade")


def _result() -> ExtractedRowInput:
    return item(
        "result",
        P3,
        statement="82.4% top-1",
        metric=field("top-1", *P3),
        value=field("82.4", *P3, unit="%"),
    )


def _base(**extra: FieldInput) -> ExtractedRowInput:
    return item("base-idea", P1, name="linear attention", **extra)


# --- contribution_next ---


def test_next_serves_entries_for_current_references(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    rex = with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    assert batch.records[0]["work_id"] == world[0]
    assert batch.references.status == "current" and batch.references.extraction_id == rex
    assert [e.ordinal for e in batch.references.entries] == [1, 2, 3, 4, 5, 6]
    assert batch.references.entries[4].title == "Linear attention with kernels"
    assert batch.instructions == CONTRIBUTION_INSTRUCTIONS
    assert batch.item_rules and all(isinstance(r, str) for r in batch.item_rules)
    assert batch.schema_ref == "contribution@1" and batch.claims is False
    again = _next(project, ctr_a)  # idempotent while held
    assert again.task_id == batch.task_id


def test_next_marks_no_references_and_other_conversion(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    work = world[1]
    with_references(project, agent, work)  # before any task: its unit sees the references
    plain = _next(project, ctr_a)  # world[0] has no document with references
    assert plain.references.status == "none"
    assert plain.references.entries == [] and plain.references.extraction_id is None
    contribution_record(project, ctr_a, plain.task_id, [], finish=True, reason="no references")
    served = _next(project, ctr_a)
    assert served.records[0]["work_id"] == work
    assert served.references.status == "current"
    # Re-convert the same document and extract its references again: the new G1 extraction pins
    # the new conversion, while pass B's task shares pass A's pin (plan D ruling 5).
    run_convert(project, make_registry(StubConverter(version="9.9+other")))
    extract_references(project, agent, [work], sources={})
    contribution_record(project, ctr_a, served.task_id, [], finish=True, reason="parked")
    b_first = _next(project, ctr_b, B)
    contribution_record(project, ctr_b, b_first.task_id, [], finish=True, reason="parked")
    b_second = _next(project, ctr_b, B)
    assert b_second.records[0]["work_id"] == work
    assert b_second.records[0]["conversion_id"] == served.records[0]["conversion_id"]
    assert b_second.references.status == "other-conversion"
    assert b_second.references.entries == []


# --- contribution_record ---


def test_non_verbatim_quote_or_name_rejected_valid_written(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:  # acceptance 2
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    bad_quote = item(
        "base-idea",
        ("s1.p1", "We build on quadratic attention [5] for vision."),
        name="quadratic attention",
    )
    name_not_in_quote = item("base-idea", P1, name="softmax attention")
    res = contribution_record(
        project, ctr_a, batch.task_id, [_base(), bad_quote, name_not_in_quote, _addition()]
    )
    assert len(res.rows.written) == 2 and {e.index for e in res.rows.rejected} == {1, 2}
    reasons = [i.reason for e in res.rows.rejected for i in e.issues]
    assert "quote-not-in-anchor" in reasons and "text-not-in-quote" in reasons
    assert all("attention" not in r for r in reasons)  # no document text in an error


def test_result_value_number_check(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:  # acceptance 3
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    wrong = item(
        "result",
        P3,
        statement="82.4% top-1",
        metric=field("top-1", *P3),
        value=field("82.5", *P3, unit="%"),
    )
    res = contribution_record(project, ctr_a, batch.task_id, [wrong, _result()])
    assert len(res.rows.written) == 1
    assert _reasons(res) == {0: {"fields.value.value": "number-not-in-text"}}


def test_not_stated_accepted_for_base_and_limitation_only(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:  # acceptance 4
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    bad = [
        ExtractedRowInput(
            fields={
                "item_kind": FieldInput(value="not-stated"),
                "absent_kind": FieldInput(value=kind),
            }
        )
        for kind in ("addition", "result")
    ]
    res = contribution_record(
        project, ctr_a, batch.task_id, [*bad, not_stated("base-idea"), not_stated("limitation")]
    )
    assert len(res.rows.written) == 2
    assert {e.index for e in res.rows.rejected} == {0, 1}


def test_close_without_items_and_reason_refused(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:  # acceptance 4
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    with pytest.raises(FactoryValidationError) as e:
        contribution_record(project, ctr_a, batch.task_id, [], finish=True)
    assert e.value.issues[0].field == "reason"
    with pytest.raises(FactoryValidationError) as e:
        contribution_record(project, ctr_a, batch.task_id, [_base(), _addition()], finish=True)
    assert {(i.field, i.reason) for i in e.value.issues} == {
        ("finish", "limitation-not-covered"),
        ("reason", "no-result-needs-reason"),
    }
    assert live_items(project) == []  # nothing was written by the refused closes
    done = contribution_record(
        project, ctr_a, batch.task_id, [], finish=True, reason="the paper states no contribution"
    )
    assert done.completed


def test_close_complete_unit(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    items = [_base(cited_entry=field(5)), _addition(), _limitation(), _result()]
    done = contribution_record(project, ctr_a, batch.task_id, items, finish=True)
    assert done.completed and len(done.rows.written) == 4
    (state,) = [
        s for s in unit_states(project, scope=C) if s.work_id == world[0] and s.pass_label is A
    ]
    assert state.state == "current"


def test_correction_supersedes(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    first = contribution_record(project, ctr_a, batch.task_id, [_base(), not_stated("limitation")])
    base_id, ns_id = first.rows.written
    fixed = item("base-idea", P1, name="linear attention", cited_entry=field(5))
    again = contribution_record(project, ctr_a, batch.task_id, [fixed], supersedes={0: base_id})
    assert len(again.rows.written) == 1
    old = recorded_row(project, base_id, scope=C)
    assert old is not None and old[1] is False
    assert [i.extraction_id for i in live_items(project)] == sorted([ns_id, *again.rows.written])
    # A not-stated item is corrected by superseding it with the item it wrongly denied.
    limitation = contribution_record(
        project, ctr_a, batch.task_id, [_limitation()], supersedes={0: ns_id}
    )
    assert len(limitation.rows.written) == 1 and limitation.rows.rejected == []


def test_same_metric_twice_in_one_paragraph_refused_with_guidance(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:  # ruling 9
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    res = contribution_record(project, ctr_a, batch.task_id, [_result(), _result()])
    assert len(res.rows.written) == 1
    assert [(i.field, i.reason) for e in res.rows.rejected for i in e.issues] == [
        ("fields.value", DUPLICATE_ITEM)
    ]
    assert "finer anchor" in DUPLICATE_ITEM


def test_unit_reserved_after_g1_change(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:  # Review Focus 2
    work = world[0]
    first = with_references(project, agent, work)
    batch = _next(project, ctr_a)
    done = contribution_record(
        project,
        ctr_a,
        batch.task_id,
        [_base(cited_entry=field(5)), _addition(), _limitation()],
        finish=True,
        reason="no results",
    )
    old_ids = done.rows.written
    cited_id = old_ids[0]
    with_references(project, agent, work, version="v4")  # a new document version
    stale = stale_extractions(project, scope=C)
    assert cited_id in stale
    served = _next(project, ctr_a)
    while served.records[0]["work_id"] != work:  # the stale unit's new task is queued last
        contribution_record(project, ctr_a, served.task_id, [], finish=True, reason="parked")
        served = _next(project, ctr_a)
    assert served.task_id != batch.task_id
    assert served.references.extraction_id != first
    assert [e.ordinal for e in served.references.entries] == [1, 2, 3, 4, 5, 6]
    old = contribution_item(project, cited_id)
    assert old is not None and old.stale and old.live
    assert [i.extraction_id for i in live_items(project, work_id=work)] == sorted(
        i for i in old_ids if i not in stale
    )
    assert cited_id in {
        i.extraction_id for i in live_items(project, work_id=work, include_stale=True)
    }


def test_event_provenance_and_input_blob_include_served_entries(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    with_references(project, agent, world[0])
    batch = _next(project, ctr_a)
    contribution_record(project, ctr_a, batch.task_id, [_base(cited_entry=field(5))])
    events = read_all(project.paths.events_dir, project.catalog)
    created = [e for e in events if e.type == "task.created" and e.payload["kind"] == "contrib_a"]
    assert created and all(e.input_blob is not None for e in created)
    served = project.blobs.get_json(created[0].input_blob or "")
    assert isinstance(served, dict)
    assert len(served["references"]["entries"]) == 6  # type: ignore[index, arg-type]
    (recorded,) = [e for e in events if e.type == "extraction.recorded"]
    assert recorded.actor.model == ctr_a.model and recorded.actor.skill == ctr_a.skill
    assert recorded.input_blob is not None
    assert recorded.payload["cited"]["ordinal"] == 5  # type: ignore[index]


# --- reads and status ---


def _drive(
    project: Project, actor: Actor, label: PassLabel, items_for: dict[str, list[ExtractedRowInput]]
) -> None:
    """Serve and close every unit of the pass; `items_for` gives the items of chosen works."""
    for _ in range(50):
        batch = contribution_next(project, actor, label).batch
        if batch is None:
            return
        work = batch.records[0]["work_id"]
        contribution_record(
            project,
            actor,
            batch.task_id,
            items_for.get(work, []),
            finish=True,
            reason="no empirical result is reported",
        )
    raise AssertionError("the queue did not end")


@pytest.fixture
def finished(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> list[str]:
    """Both passes closed with the same items: world[0] has a base idea citing entry 5, an
    addition and a limitation; world[1] a not-stated base idea and limitation and an addition;
    the others no items."""
    with_references(project, agent, world[0])
    first = [_base(cited_entry=field(5)), _addition(), _limitation()]
    plain = item("addition", ("s3.p1", "Lorem ipsum dolor sit amet."), name="Lorem")
    other = [not_stated("base-idea"), plain, not_stated("limitation")]
    for actor, label in ((ctr_a, A), (ctr_b, B)):
        _drive(project, actor, label, {world[0]: first, world[1]: other})
    return world


def test_status_counts_derived(project: Project, finished: list[str]) -> None:
    status = contribution_status(project)
    finals = final_items(project)
    assert status.not_stated == {"base-idea": 1, "limitation": 1}
    assert sum(status.items_by_kind.values()) == len(finals) == 6
    assert status.items_by_kind == {
        "base-idea": 1,
        "addition": 2,
        "limitation": 1,
        "not-stated": 2,
    }
    assert status.markers == {"matched": 1}
    assert status.units == {"current": 2 * len(finished)}
    assert status.no_references == finished[1:]
    assert status.other_conversion == []


def test_final_items_one_per_final_row(project: Project, finished: list[str]) -> None:
    finals = final_items(project)
    assert len({(i.work_id, i.extraction_id) for i in finals}) == len(finals)
    cited = [i for i in finals if i.cited is not None]
    assert len(cited) == 1 and cited[0].cited_entry == 5 and cited[0].item_kind == "base-idea"
    assert cited[0].anchor == "s1.p1" and cited[0].quote == P1[1]
    assert cited[0].name == "linear attention" and cited[0].live and not cited[0].stale
    not_stated_items = [i for i in finals if i.item_kind == "not-stated"]
    assert {i.absent_kind for i in not_stated_items} == {"base-idea", "limitation"}
    assert all(i.anchor is None and i.quote is None for i in not_stated_items)
    one = contribution_item(project, cited[0].extraction_id)
    assert one is not None and one.cited == cited[0].cited
    assert contribution_item(project, "ext_01JZ9Q3K5M7N8P0R2S4T6V8W0X") is None
    assert live_items(project, kind="not-stated") == [
        i for i in live_items(project) if i.item_kind == "not-stated"
    ]


def test_status_lists_units_closed_without_items(project: Project, finished: list[str]) -> None:
    quiet = contribution_status(project).closed_without_items
    assert len(quiet) == 2 * (len(finished) - 2)
    assert {u.work_id for u in quiet} == set(finished[2:])
    assert {u.reason for u in quiet} == {"no empirical result is reported"}
    assert {u.pass_label for u in quiet} == {A, B}
