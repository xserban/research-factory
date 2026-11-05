"""Dual extraction, agreement, resolution and audit for contributions (plan G2-B, task 4).

World 0 has a document with references (markers [5] at s1.p1 and [3] at s1.p2); world 1 the plain
fixture. Pass A is session C (opus), pass B session D (sonnet).
"""

# ruff: noqa: F401, F811

from collections.abc import Callable

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.contributions import (
    contribution_agreement,
    contribution_audit_record,
    contribution_audit_report,
    contribution_audit_sample,
    contribution_next,
    contribution_record,
    final_items,
    resolve_contribution,
)
from factory.services.extraction import pass_config
from factory.services.extraction_audit import EXTRACTION_ERROR_CEILING, agreed_values
from tests.contribution_helpers import (
    P1,
    P2,
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

A, B = PassLabel.A, PassLabel.B
CH = Channel.CLI
RowsFor = Callable[[str], list[ExtractedRowInput]]


def _drive(project: Project, actor: Actor, label: PassLabel, rows_for: RowsFor) -> None:
    """Serve and close every unit of the pass with `rows_for(work)`; the reason covers the units
    that report no result."""
    for _ in range(50):
        batch = contribution_next(project, actor, label).batch
        if batch is None:
            return
        rows = rows_for(batch.records[0]["work_id"])
        done = contribution_record(
            project, actor, batch.task_id, rows, finish=True, reason="no empirical result"
        )
        assert done.completed and done.rows.rejected == [], done.rows.rejected
    raise AssertionError("the queue did not end")


def _lorem() -> ExtractedRowInput:
    return item("addition", ("s3.p1", "Lorem ipsum dolor sit amet."), name="Lorem")


def _reading(world_zero: str, cited: int = 5) -> RowsFor:
    """A full reading: work 0 cites entry `cited`; the others state no base idea."""

    def rows(work: str) -> list[ExtractedRowInput]:
        if work == world_zero:
            return [
                item("base-idea", P1, name="linear attention", cited_entry=field(cited)),
                item("addition", P2, name="softmax attention"),
                item("limitation", P2, name="softmax attention", statement="our module is linear"),
            ]
        return [not_stated("base-idea"), _lorem(), not_stated("limitation")]

    return rows


@pytest.fixture
def refs(project: Project, agent: Actor, world: list[str]) -> list[str]:
    with_references(project, agent, world[0])
    return world


def test_pass_independence_as_plan_d(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    assert contribution_next(project, ctr_a, A).batch is not None
    same_model = ctr_b.model_copy(update={"model": ctr_a.model})
    with pytest.raises(FactoryValidationError) as e:
        contribution_next(project, same_model, B)
    assert e.value.issues[0].field == "model"
    with pytest.raises(FactoryValidationError) as e:
        contribution_next(project, ctr_a, B)  # the same session cannot serve both passes
    assert e.value.issues[0].field == "pass"
    first_b = contribution_next(project, ctr_b, B).batch
    assert first_b is not None
    config_a, config_b = pass_config(project, A, scope=C), pass_config(project, B, scope=C)
    assert config_a is not None and config_b is not None
    assert (config_a.field_order, config_b.field_order) == ("schema", "reversed")
    a_fields = [f["name"] for f in contribution_next(project, ctr_a, A).batch.fields]  # type: ignore[union-attr]
    b_fields = [f["name"] for f in first_b.fields]
    assert b_fields == list(reversed(a_fields))
    with pytest.raises(FactoryValidationError) as e:  # a session that extracts cannot read
        contribution_agreement(project, ctr_a)
    assert e.value.issues[0].field == "session"


def test_rows_align_on_row_key_across_passes(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    for actor, label in ((ctr_a, A), (ctr_b, B)):
        _drive(project, actor, label, _reading(refs[0]))
    agreement = contribution_agreement(project, human)
    assert agreement.disagreements == [] and agreement.overall == 1.0
    assert agreement.dual_works == len(refs)
    assert agreement.rows_aligned == 3 * len(refs) and agreement.rows_unmatched == 0
    finals = final_items(project)
    assert len(finals) == 3 * len(refs)


def test_different_anchor_is_row_disagreement(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:  # Review Focus 4
    def reading(anchor: tuple[str, str]) -> RowsFor:
        def rows(work: str) -> list[ExtractedRowInput]:
            if work != refs[0]:
                return []
            return [
                item("base-idea", anchor, name="attention"),
                item("addition", P2, name="softmax attention"),
                item("limitation", P2, name="softmax attention", statement="our module is linear"),
            ]

        return rows

    _drive(project, ctr_a, A, reading(P1))
    _drive(project, ctr_b, B, reading(P2))
    agreement = contribution_agreement(project, human)
    assert agreement.rows_aligned == 2 and agreement.rows_unmatched == 2
    assert {d.kind for d in agreement.disagreements} == {"row"}
    shown = {v.value for d in agreement.disagreements for v in (d.a, d.b) if v is not None}
    assert shown == {"base-idea"}  # item_kind stands where plan D shows the value
    # The aligned rows are final; the base idea, quoted at two anchors, is never auto-aligned.
    assert sorted(i.item_kind for i in final_items(project)) == ["addition", "limitation"]


def test_cited_entry_and_value_compared_statement_not(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    def rows_b(work: str) -> list[ExtractedRowInput]:
        rows = _reading(refs[0], cited=4)(work)
        if work == refs[0]:  # another statement, another quote, the same anchor
            rows[1] = item(
                "addition", P2, name="softmax attention", statement="Unlike softmax attention"
            )
        return rows

    _drive(project, ctr_a, A, _reading(refs[0]))
    _drive(project, ctr_b, B, rows_b)
    agreement = contribution_agreement(project, human)
    assert [(d.field, d.kind) for d in agreement.disagreements] == [("cited_entry", "value")]
    assert agreement.rows_aligned == 3 * len(refs)


def test_human_resolution_chooses_a_b_or_neither(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    def rows_a(work: str) -> list[ExtractedRowInput]:
        rows = _reading(refs[0])(work)
        if work == refs[0]:
            rows[1] = item("addition", P2, name="softmax attention", cited_entry=field(3))
        return rows

    def rows_b(work: str) -> list[ExtractedRowInput]:
        rows = _reading(refs[0], cited=4)(work)
        if work == refs[0]:
            rows[1] = item("addition", P2, name="softmax attention", cited_entry=field(2))
        return rows

    _drive(project, ctr_a, A, rows_a)
    _drive(project, ctr_b, B, rows_b)
    open_ = contribution_agreement(project, human).disagreements
    assert {d.field for d in open_} == {"cited_entry"} and len(open_) == 2
    base, addition = sorted(open_, key=lambda d: d.a.value if d.a else "")  # entry 3 < entry 5
    assert addition.a is not None and addition.a.value == "5"
    resolve_contribution(
        project, human, addition.work_id, addition.row_key, "cited_entry", "b", "entry 4 fits", CH
    )
    resolve_contribution(
        project, human, base.work_id, base.row_key, "cited_entry", "neither", "unclear", CH
    )
    assert contribution_agreement(project, human).disagreements == []
    items = {i.name: i for i in final_items(project) if i.work_id == refs[0]}
    assert items["linear attention"].cited_entry == 4
    assert items["softmax attention"].cited_entry is None  # dropped by `neither`


def test_audit_includes_not_stated_and_cited_entry(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    for actor, label in ((ctr_a, A), (ctr_b, B)):
        _drive(project, actor, label, _reading(refs[0]))
    fields = {i.field for i in agreed_values(project, scope=C)}
    assert {"cited_entry", "absent_kind", "item_kind", "name"} <= fields
    sampled = contribution_audit_sample(project, human, random_seed=11)
    assert sampled.pack == "contribution" and sampled.items
    agreed = {(i.work_id, i.row_key, i.field) for i in agreed_values(project, scope=C)}
    assert {(i.work_id, i.row_key, i.field) for i in sampled.items} <= agreed


def test_error_rate_reported_and_ceiling(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, refs: list[str]
) -> None:
    for actor, label in ((ctr_a, A), (ctr_b, B)):
        _drive(project, actor, label, _reading(refs[0]))
    assert contribution_audit_report(project) is None
    sampled = contribution_audit_sample(project, human, random_seed=11)
    wrong = {0}
    for index, sampled_item in enumerate(sampled.items):
        contribution_audit_record(
            project,
            human,
            sampled.audit_id,
            sampled_item.work_id,
            sampled_item.row_key,
            sampled_item.field,
            index not in wrong,
            "",
            CH,
        )
    report = contribution_audit_report(project)
    assert report is not None and report.audit_id == sampled.audit_id
    assert report.labelled == report.sample_size == len(sampled.items)
    assert report.incorrect == 1
    assert report.error_rate == pytest.approx(1 / len(sampled.items))
    assert report.ceiling == EXTRACTION_ERROR_CEILING
    assert report.above_ceiling == (1 / len(sampled.items) > EXTRACTION_ERROR_CEILING)


def test_agent_cannot_resolve_or_label(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, agent: Actor, refs: list[str]
) -> None:
    for actor, label in ((ctr_a, A), (ctr_b, B)):
        _drive(project, actor, label, _reading(refs[0], cited=5 if label is A else 4))
    (d,) = contribution_agreement(project, human).disagreements
    with pytest.raises(FactoryValidationError) as e:
        resolve_contribution(project, agent, d.work_id, d.row_key, d.field, "a", "x", CH)
    assert e.value.issues[0].field == "actor"
    with pytest.raises(FactoryValidationError) as e:  # a pass session relaying over MCP
        resolve_contribution(project, ctr_a, d.work_id, d.row_key, d.field, "a", "x", Channel.MCP)
    assert e.value.issues
    resolve_contribution(project, human, d.work_id, d.row_key, d.field, "a", "ok", CH)
    sampled = contribution_audit_sample(project, human, random_seed=2)
    first = sampled.items[0]
    with pytest.raises(FactoryValidationError) as e:
        contribution_audit_record(
            project,
            agent,
            sampled.audit_id,
            first.work_id,
            first.row_key,
            first.field,
            True,
            "",
            CH,
        )
    assert e.value.issues[0].field == "actor"
