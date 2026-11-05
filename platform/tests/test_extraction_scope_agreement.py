# ruff: noqa: F811
"""Agreement, resolution, final rows and audit by scope (plan G2-A, task 5).

The world is that of `test_extraction_scope`: both schemas declared over the screened works. A
contribution unit is dual-extracted by sessions C (pass A) and D (pass B); evidence by A and B.
"""

from collections.abc import Callable, Mapping, Sequence

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.extraction import (
    ExtractedRowInput,
    FieldInput,
    Scope,
    StoredField,
)
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.evidence_report import evidence_report
from factory.services.extraction import (
    ExtractionRow,
    ExtraVerdict,
    UnitPin,
    extract_next,
    live_claims,
    next_unit,
    record_unit,
)
from factory.services.extraction_agreement import (
    agreement_overall,
    extraction_agreement,
    final_rows,
    grouped_rows,
    independence_counts,
    resolve_extraction,
)
from factory.services.extraction_audit import (
    agreed_values,
    audit_evidence,
    extraction_audit_outstanding,
    extraction_audit_record,
    extraction_audit_report,
    extraction_audit_sample,
)
from factory.services.methods import methods_report
from tests.extraction_helpers import (  # noqa: F401
    QUOTE,
    _both,
    _item,
    add_refs,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    scope_world,
    screened,
)

C = Scope.CONTRIBUTION
CH = Channel.CLI
RowsFor = Callable[[str], list[ExtractedRowInput]]


def _events(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def _no_check(
    project: Project,
    pin: UnitPin,
    fields: Mapping[str, StoredField],
    rows: Sequence[ExtractionRow],
) -> ExtraVerdict:
    """Stand-in for G2-B's check: accepts every row and resolves no cited entry (a row whose
    `cited` names a reference list that is not the current one would be stale)."""
    return ExtraVerdict(cited=None, issues=[])


def _run_c(project: Project, actor: Actor, label: PassLabel, rows_for: RowsFor) -> None:
    """Serve every contribution unit of the pass and record `rows_for(work)`, closing the unit."""
    for _ in range(100):
        batch = next_unit(project, actor, label, scope=C, content=add_refs).batch
        if batch is None:
            return
        rows = rows_for(batch.records[0]["work_id"])
        res = record_unit(
            project,
            actor,
            batch.task_id,
            rows,
            finish=True,
            reason=None if rows else "no item",
            extra_check=_no_check,
        )
        assert res.completed, res.rows.rejected
    raise AssertionError("too many tasks")


def _both_c(
    project: Project,
    a: Actor,
    b: Actor,
    rows_a: RowsFor | None = None,
    rows_b: RowsFor | None = None,
) -> None:
    same: RowsFor = lambda work: [_item("addition", name="Lorem")]  # noqa: E731
    _run_c(project, a, PassLabel.A, rows_a or same)
    _run_c(project, b, PassLabel.B, rows_b or same)


def _statement(text: str) -> FieldInput:
    return FieldInput(value=text, anchor="s3.p1", quote=text)


# --- Review Focus 3: open tasks are counted per scope ---


def test_open_contribution_task_does_not_block_evidence_agreement(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, ctr_a: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert next_unit(project, ctr_a, PassLabel.A, scope=C, content=add_refs).batch is not None
    assert extraction_agreement(project, human).overall == 1.0
    assert agreement_overall(project).overall == 1.0
    with pytest.raises(FactoryValidationError):  # the contribution scope is not finished
        extraction_agreement(project, human, scope=C)
    assert agreement_overall(project, scope=C).overall is None


def test_open_evidence_task_does_not_block_contribution_agreement(
    project: Project, human: Actor, ext_a: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    _both_c(project, ctr_a, ctr_b)
    assert extract_next(project, ext_a, PassLabel.A).batch is not None
    agreement = extraction_agreement(project, human, scope=C)
    assert agreement.overall == 1.0 and agreement.disagreements == []
    assert agreement.dual_works == len(world) and agreement.rows_aligned == len(world)
    with pytest.raises(FactoryValidationError):
        extraction_agreement(project, human)  # evidence still has an open unit
    assert [v.sessions for v in agreement.passes] == [[ctr_a.session], [ctr_b.session]]


def test_contribution_passes_may_share_a_model_with_evidence_passes(
    project: Project,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world: list[str],
) -> None:
    # ext_a and ctr_a use one model, ext_b and ctr_b another: sharing is judged per scope.
    _both(project, ext_a, ext_b)
    _both_c(project, ctr_a, ctr_b)
    extraction_agreement(project, human)
    extraction_agreement(project, human, scope=C)


# --- Compared fields ---


def test_statement_and_quote_not_compared(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    _both_c(
        project,
        ctr_a,
        ctr_b,
        lambda w: [_item("addition", name="Lorem", statement=_statement(QUOTE))],
        lambda w: [_item("addition", name="Lorem", statement=_statement("Lorem ipsum"))],
    )
    agreement = extraction_agreement(project, human, scope=C)
    assert agreement.disagreements == [] and agreement.overall == 1.0
    assert {r.group for r in agreement.rates} == {"item", "content", "link", "result"}
    rows = final_rows(project, scope=C)
    assert len(rows) == len(world) and all(r.status == "agreed" for r in rows)
    assert all(not r.independent for r in rows)


def test_cited_entry_difference_is_a_disagreement(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    _both_c(
        project,
        ctr_a,
        ctr_b,
        lambda w: [_item("addition", name="Lorem", cited_entry=FieldInput(value=1))],
        lambda w: [_item("addition", name="Lorem", cited_entry=FieldInput(value=2))],
    )
    agreement = extraction_agreement(project, human, scope=C)
    assert {(d.field, d.kind) for d in agreement.disagreements} == {("cited_entry", "value")}
    assert len(agreement.disagreements) == len(world)
    assert final_rows(project, scope=C) == []
    d = agreement.disagreements[0]
    assert d.a is not None and d.a.anchor is None and d.a.value == "1"
    assert d.b is not None and d.b.value == "2"


def test_resolution_and_audit_events_carry_pack(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    _both_c(
        project,
        ctr_a,
        ctr_b,
        lambda w: [_item("addition", name="Lorem", cited_entry=FieldInput(value=1))],
        lambda w: [_item("addition", name="Lorem", cited_entry=FieldInput(value=2))],
    )
    for d in extraction_agreement(project, human, scope=C).disagreements:
        resolve_extraction(
            project, human, d.work_id, d.row_key, d.field, "a", "first reading", CH, scope=C
        )
    assert [e.payload["pack"] for e in _events(project, "extraction.resolved")] == [
        "contribution"
    ] * len(world)
    assert extraction_agreement(project, human, scope=C).disagreements == []
    rows = final_rows(project, scope=C)
    assert len(rows) == len(world) and all(r.status == "resolved" for r in rows)
    assert all(r.fields["cited_entry"].value == "1" for r in rows)
    # evidence has no schema rows yet: its resolution of a contribution row key is refused
    with pytest.raises(FactoryValidationError):
        resolve_extraction(project, human, rows[0].work_id, rows[0].row_key, None, "a", "x", CH)

    sampled = extraction_audit_sample(project, human, random_seed=7, scope=C)
    assert sampled.pack == "contribution"
    assert _events(project, "extraction.audit_sampled")[0].payload["pack"] == "contribution"
    item = sampled.items[0]
    extraction_audit_record(
        project, human, sampled.audit_id, item.work_id, item.row_key, item.field, True, "", CH
    )
    assert _events(project, "extraction.audit_labelled")[0].payload["pack"] == "contribution"


# --- Audit ---


def test_not_stated_items_are_audited(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    def absent(work: str) -> list[ExtractedRowInput]:
        return [
            ExtractedRowInput(
                fields={
                    "item_kind": FieldInput(value="not-stated"),
                    "absent_kind": FieldInput(value="base-idea"),
                }
            )
        ]

    _both_c(project, ctr_a, ctr_b, absent, absent)
    values = agreed_values(project, scope=C)
    assert {i.field for i in values} == {"item_kind", "absent_kind"}
    assert len(values) == 2 * len(world)
    assert agreed_values(project) == []  # evidence has no extraction yet
    sampled = extraction_audit_sample(project, human, random_seed=3, scope=C)
    evidence = audit_evidence(project, human, sampled.audit_id, CH)
    assert len(evidence) == len(sampled.items)
    assert all(e.anchor is None and e.cell is None and e.element_text == "" for e in evidence)


def test_audit_scopes_are_independent(
    project: Project,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    _both_c(project, ctr_a, ctr_b)
    assert extraction_audit_outstanding(project) and extraction_audit_outstanding(project, scope=C)
    extraction_audit_sample(project, human, random_seed=1)
    assert not extraction_audit_outstanding(project)
    assert extraction_audit_outstanding(project, scope=C)
    assert extraction_audit_report(project, scope=C) is None
    contribution = extraction_audit_sample(project, human, random_seed=1, scope=C)
    report = extraction_audit_report(project, scope=C)
    evidence = extraction_audit_report(project)
    assert report is not None and evidence is not None
    assert report.audit_id == contribution.audit_id != evidence.audit_id
    assert not extraction_audit_outstanding(project, scope=C)
    # an unscoped label of a contribution audit lands in the contribution audit
    item = contribution.items[0]
    extraction_audit_record(
        project, human, contribution.audit_id, item.work_id, item.row_key, item.field, False, "", CH
    )
    assert extraction_audit_report(project, scope=C).labelled == 1  # type: ignore[union-attr]
    assert extraction_audit_report(project).labelled == 0  # type: ignore[union-attr]


# --- Separation from the evidence table (acceptance 7, unit level) ---


def _snapshot(project: Project) -> tuple[object, ...]:
    rows = final_rows(project)
    return (
        rows,
        grouped_rows(project),
        independence_counts(rows),
        live_claims(project),
        agreement_overall(project),
        extraction_audit_report(project),
        methods_report(project),
        agreed_values(project),
    )


def test_separation_from_evidence_table(
    project: Project,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    extraction_audit_sample(project, human, random_seed=5)
    before = _snapshot(project)
    assert before[0]
    _both_c(project, ctr_a, ctr_b)
    extraction_audit_sample(project, human, random_seed=5, scope=C)
    assert _snapshot(project) == before


def test_evidence_report_unchanged_by_contribution_rows(
    project: Project, ext_a: Actor, ext_b: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    before = evidence_report(project).model_dump_json()
    _both_c(project, ctr_a, ctr_b)
    assert evidence_report(project).model_dump_json() == before
