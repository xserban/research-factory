# ruff: noqa: F811
"""Audit of agreed extraction values (plan D, task 9; decision 37, acceptance 10).

A human labels a random sample of agreed values against the document; the error rate is computed
from the labels. The world is that of `test_extraction_agreement`: every work extracted twice with
the same row, so each work contributes six agreed values."""

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.extraction import AuditItemRef, ExtractionAuditSampled
from factory.model.screening import Channel, PassLabel
from factory.services import extraction_audit as ea
from factory.services.context import Project
from factory.services.extraction_audit import (
    EXTRACTION_ERROR_CEILING,
    agreed_values,
    audit_evidence,
    extraction_audit_outstanding,
    extraction_audit_record,
    extraction_audit_report,
    extraction_audit_sample,
)
from tests.test_extraction_agreement import (  # noqa: F401
    _both,
    _r,
    _run,
    ext_a,
    ext_b,
    screened,
    world,
)

CH = Channel.CLI
MISSING = "xau_01HZZZZZZZZZZZZZZZZZZZZZZZ"


@pytest.fixture
def agreed(project: Project, ext_a: Actor, ext_b: Actor, world: list[str]) -> list[str]:
    _both(project, ext_a, ext_b)
    return world


def _events(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def _fake(monkeypatch: pytest.MonkeyPatch, n: int) -> list[AuditItemRef]:
    items = [
        AuditItemRef(work_id="rf:w1", row_key="rk_0123456789ab", field=f"f{i:04d}")
        for i in range(n)
    ]
    monkeypatch.setattr(ea, "_population", lambda project: [(i, f"ext_{i.field}") for i in items])
    return items


@pytest.mark.parametrize(("n", "expected"), [(30, 30), (300, 50), (4000, 80), (2500, 50)])
def test_sample_size_is_decision_37_rule(
    project: Project,
    human: Actor,
    agreed: list[str],
    monkeypatch: pytest.MonkeyPatch,
    n: int,
    expected: int,
) -> None:
    _fake(monkeypatch, n)
    sampled = extraction_audit_sample(project, human, random_seed=1)
    assert len(sampled.items) == expected
    assert sampled.population == n


def test_agreed_values_are_sorted_and_cover_dual_rows(project: Project, agreed: list[str]) -> None:
    values = agreed_values(project)
    assert len(values) == 6 * len(agreed)
    assert values == sorted(values, key=lambda i: (i.work_id, i.row_key, i.field))


def test_sample_recorded_with_seed_and_reproducible(
    project: Project, human: Actor, agreed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake(monkeypatch, 300)
    first = extraction_audit_sample(project, human, random_seed=7)
    assert first.random_seed == 7
    (event,) = _events(project, "extraction.audit_sampled")
    assert ExtractionAuditSampled.model_validate(event.payload).items == first.items
    population = sorted((i for i, _ in ea._population(project)), key=ea._sort_key)
    expected = ea._draw(population, 50, 7)
    assert list(first.items) == expected
    assert ea._draw(population, 50, 8) != expected


def test_refused_before_agreement_or_with_unresolved_disagreements(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    with pytest.raises(FactoryValidationError):
        extraction_audit_sample(project, human, random_seed=1)  # no pass opened
    _run(project, ext_a, PassLabel.A, lambda w: [_r()])
    _run(project, ext_b, PassLabel.B, lambda w: [_r(value="2", cell="t1.r3.c3")])
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_sample(project, human, random_seed=1)
    assert "disagree" in e.value.issues[0].reason
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_bad_seed_refused(project: Project, human: Actor, agreed: list[str]) -> None:
    for seed in (-1, 2**32):
        with pytest.raises(FactoryValidationError) as e:
            extraction_audit_sample(project, human, random_seed=seed)
        assert e.value.issues[0].field == "random_seed"
    assert _events(project, "extraction.audit_sampled") == []


def test_agent_cannot_sample_or_label(
    project: Project, human: Actor, agent: Actor, agreed: list[str]
) -> None:
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_sample(project, agent, random_seed=1)
    assert e.value.issues[0].field == "actor"
    sampled = extraction_audit_sample(project, human, random_seed=1)
    item = sampled.items[0]
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_record(
            project, agent, sampled.audit_id, item.work_id, item.row_key, item.field, True, "", CH
        )
    assert e.value.issues[0].field == "actor"
    assert _events(project, "extraction.audit_labelled") == []


def test_extraction_session_cannot_relay_label_or_sample(
    project: Project, human: Actor, ext_a: Actor, agreed: list[str]
) -> None:
    sampled = extraction_audit_sample(project, human, random_seed=1)
    item = sampled.items[0]
    relay = ext_a.model_copy(update={"kind": "human"})
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_record(
            project,
            relay,
            sampled.audit_id,
            item.work_id,
            item.row_key,
            item.field,
            True,
            "",
            Channel.MCP,
        )
    assert e.value.issues[0].field == "channel"
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_sample(project, relay, random_seed=2)
    assert e.value.issues[0].field == "session"
    assert _events(project, "extraction.audit_labelled") == []


def test_second_sample_refused_until_agreed_set_changes(
    project: Project, human: Actor, agreed: list[str]
) -> None:
    assert extraction_audit_outstanding(project) is True
    extraction_audit_sample(project, human, random_seed=1)
    assert extraction_audit_outstanding(project) is False
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_sample(project, human, random_seed=2)
    assert "open" in e.value.issues[0].reason
    assert len(_events(project, "extraction.audit_sampled")) == 1


def test_outstanding_false_without_values(
    project: Project, agreed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ea, "_population", lambda project: [])
    assert extraction_audit_outstanding(project) is False


def test_record_refuses_unknown_audit_and_item_outside_sample(
    project: Project, human: Actor, agreed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake(monkeypatch, 300)
    sampled = extraction_audit_sample(project, human, random_seed=3)
    inside = {(i.work_id, i.row_key, i.field) for i in sampled.items}
    outside = next(
        i for i, _ in ea._population(project) if (i.work_id, i.row_key, i.field) not in inside
    )
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_record(
            project,
            human,
            sampled.audit_id,
            outside.work_id,
            outside.row_key,
            outside.field,
            True,
            "",
            CH,
        )
    assert e.value.issues[0].field == "field"
    item = sampled.items[0]
    with pytest.raises(FactoryValidationError) as e:
        extraction_audit_record(
            project, human, MISSING, item.work_id, item.row_key, item.field, True, "", CH
        )
    assert e.value.issues[0].field == "audit_id"
    assert _events(project, "extraction.audit_labelled") == []


def test_error_rate_computed_from_labels(
    project: Project, human: Actor, agreed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake(monkeypatch, 40)
    sampled = extraction_audit_sample(project, human, random_seed=5)
    assert len(sampled.items) == 40
    for i, item in enumerate(sampled.items):
        extraction_audit_record(
            project,
            human,
            sampled.audit_id,
            item.work_id,
            item.row_key,
            item.field,
            i >= 3,
            "wrong" if i < 3 else "",
            CH,
        )
    report = extraction_audit_report(project)
    assert report is not None
    assert (report.sample_size, report.labelled, report.incorrect) == (40, 40, 3)
    assert report.error_rate == 0.075
    assert report.ceiling == EXTRACTION_ERROR_CEILING == 0.05
    assert report.above_ceiling is True


def test_relabel_last_write_wins_and_partial_labels(
    project: Project, human: Actor, agreed: list[str]
) -> None:
    sampled = extraction_audit_sample(project, human, random_seed=5)
    item = sampled.items[0]
    args = (project, human, sampled.audit_id, item.work_id, item.row_key, item.field)
    extraction_audit_record(*args, False, "", CH)
    extraction_audit_record(*args, True, "fixed", CH)
    report = extraction_audit_report(project)
    assert report is not None
    assert (report.labelled, report.incorrect, report.error_rate) == (1, 0, 0.0)
    assert report.above_ceiling is False
    assert any(r is not None for r in report.by_group.values())


def test_ceiling_advisory_in_pilot_error_in_systematic(
    project: Project, human: Actor, agreed: list[str]
) -> None:
    sampled = extraction_audit_sample(project, human, random_seed=5)
    item = sampled.items[0]
    extraction_audit_record(
        project, human, sampled.audit_id, item.work_id, item.row_key, item.field, False, "", CH
    )
    report = extraction_audit_report(project)
    assert report is not None
    assert report.above_ceiling is True
    assert report.enforced is False  # the fixture project is a pilot


def test_evidence_shows_cited_element_text_from_pinned_conversion(
    project: Project, human: Actor, agreed: list[str]
) -> None:
    sampled = extraction_audit_sample(project, human, random_seed=5)
    evidence = audit_evidence(project, sampled.audit_id)
    assert len(evidence) == len(sampled.items) > 0
    for e in evidence:
        assert e.extraction_id
        if e.item.field == "value":
            assert (e.cell, e.element_text) == ("t1.r3.c2", "1")
        if e.item.field == "dataset":
            assert e.element_text == "Lorem ipsum dolor sit amet."
    with pytest.raises(FactoryValidationError):
        audit_evidence(project, MISSING)


def test_report_none_before_any_sample(project: Project, agreed: list[str]) -> None:
    assert extraction_audit_report(project) is None


def test_reads_do_not_raise_without_schema(project: Project) -> None:
    assert extraction_audit_report(project) is None
    assert extraction_audit_outstanding(project) is False
    assert agreed_values(project) == []
